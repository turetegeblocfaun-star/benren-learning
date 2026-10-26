from __future__ import annotations

import io
import json
import subprocess
import tempfile
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_invite_code
from app.db import create_app_engine, get_db
from app.models import Base
from app.models.entities import ProcessingJob
from app.services.jobs import claim_next_job
from app.services.materials.processing import execute_job
from app.services.storage.local import LocalStorage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env.production.local"
INVITE_CODE = "stage1-real-backend-smoke"


def _required(env: dict[str, str | None], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing:{key}")
    return value


def _settings(env: dict[str, str | None], directory: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{directory / 'stage1-real-smoke.db'}",
        storage_root=directory / "storage",
        session_signing_key=SecretStr("stage1-real-smoke-signing-key-with-32-characters"),
        invite_code_hashes=[hash_invite_code(INVITE_CODE)],
        llm_provider="deepseek",
        title_model_id="deepseek-flash",
        model_api_key=SecretStr(_required(env, "DEEPSEEK_API_KEY")),
        asr_provider="volcengine",
        asr_model_id="volc-bigasr-standard-v1",
        asr_auth_mode="api_key",
        asr_api_key=SecretStr(_required(env, "VOLCENGINE_BIGASR_API_KEY")),
        asr_resource_id="volc.bigasr.auc",
        asr_mode="standard",
        asr_poll_seconds=0.5,
        ocr_provider="volcengine",
        ocr_model_id="MultiLanguageOCR@2022-08-31",
        ocr_access_key_id=SecretStr(_required(env, "VOLCENGINE_ACCESS_KEY_ID")),
        ocr_secret_access_key=SecretStr(_required(env, "VOLCENGINE_SECRET_ACCESS_KEY")),
        ocr_action="MultiLanguageOCR",
        ocr_version="2022-08-31",
    )


def _audio_bytes(directory: Path) -> bytes:
    aiff_path = directory / "stage1-real-smoke.aiff"
    wav_path = directory / "stage1-real-smoke.wav"
    subprocess.run(
        [
            "/usr/bin/say",
            "-v",
            "Tingting",
            "光合作用需要光照，二氧化碳和水，并且会释放氧气。",
            "-o",
            str(aiff_path),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "/usr/bin/afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@16000",
            str(aiff_path),
            str(wav_path),
        ],
        check=True,
        capture_output=True,
    )
    return wav_path.read_bytes()


def _image_bytes(text: str) -> bytes:
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 72)
    except OSError:
        font = ImageFont.load_default()
    draw.text((70, 150), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _require(response: Any, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(f"api:{response.status_code}")
    return cast(dict[str, Any], response.json())


def _drain_jobs(
    factory: sessionmaker[Session], settings: Settings, storage: LocalStorage, limit: int = 100
) -> int:
    completed = 0
    for _ in range(limit):
        with factory() as db:
            job = claim_next_job(db, "stage1-real-smoke-worker")
            job_id = job.id if job else None
            db.commit()
        if job_id is None:
            return completed
        with factory() as db:
            claimed = db.get(ProcessingJob, job_id)
            if claimed is None:
                raise RuntimeError("job:missing")
            execute_job(db, settings=settings, storage=storage, job=claimed)
            db.commit()
        completed += 1
    return completed


def _run(settings: Settings, directory: Path) -> dict[str, object]:
    engine = create_app_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    storage = LocalStorage(settings.storage_root)

    from app import main as app_module

    app_module.settings = settings
    test_app = app_module.create_app()

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_settings] = lambda: settings

    try:
        with TestClient(test_app) as client:
            _require(client.post("/api/v1/auth/invite-session", json={"invite_code": INVITE_CODE}))
            course = _require(
                client.post(
                    "/api/v1/courses",
                    json={},
                    headers={"Idempotency-Key": f"real-course-{uuid.uuid4().hex}"},
                ),
                201,
            )
            manifest = {
                "items": [
                    {"client_item_id": "audio", "declared_type": "audio", "upload_index": 0},
                    {"client_item_id": "text", "declared_type": "text", "upload_index": 1},
                    {
                        "client_item_id": "board",
                        "declared_type": "board_image",
                        "upload_index": 2,
                    },
                    {
                        "client_item_id": "handwriting",
                        "declared_type": "handwriting_image",
                        "upload_index": 3,
                    },
                ]
            }
            batch = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/material-batches",
                    data={"manifest": json.dumps(manifest, ensure_ascii=False)},
                    files=[
                        (
                            "files",
                            ("光合作用课堂.wav", _audio_bytes(directory), "audio/wav"),
                        ),
                        (
                            "files",
                            (
                                "光合作用讲义.txt",
                                "光合作用把光能转化为化学能。".encode(),
                                "text/plain",
                            ),
                        ),
                        (
                            "files",
                            (
                                "光合作用板书.png",
                                _image_bytes("光合作用  二氧化碳  氧气"),
                                "image/png",
                            ),
                        ),
                        (
                            "files",
                            ("光合作用手写.png", _image_bytes("叶绿体  光能  有机物"), "image/png"),
                        ),
                    ],
                    headers={"Idempotency-Key": f"real-upload-{uuid.uuid4().hex}"},
                ),
                202,
            )

            if _drain_jobs(factory, settings, storage, limit=4) != 4:
                raise RuntimeError("jobs:extraction-incomplete")

            material_ids = [item["id"] for item in batch["materials"]]
            for index, material_id in enumerate(material_ids):
                material = _require(client.get(f"/api/v1/materials/{material_id}"))
                if material["status"] == "failed":
                    raise RuntimeError(f"material:{material['error_code']}")
                if material["status"] == "needs_review":
                    version = _require(
                        client.get(
                            f"/api/v1/materials/{material_id}/versions/"
                            f"{material['active_parse_version_id']}"
                        )
                    )
                    review_segments = [
                        {"segment_id": item["id"], "action": "accept"}
                        for item in version["segments"]
                        if item["review_required"]
                    ]
                    _require(
                        client.patch(
                            f"/api/v1/materials/{material_id}/corrections",
                            json={
                                "expected_version": material["version"],
                                "corrections": review_segments,
                            },
                            headers={"Idempotency-Key": f"real-accept-{index}-{uuid.uuid4().hex}"},
                        )
                    )

            _drain_jobs(factory, settings, storage)
            final_materials = [
                _require(client.get(f"/api/v1/materials/{material_id}"))
                for material_id in material_ids
            ]
            if any(item["status"] != "usable" for item in final_materials):
                raise RuntimeError("materials:not-usable")

            title = _require(client.get(f"/api/v1/courses/{course['id']}/title-candidate"))
            current_course = _require(client.get(f"/api/v1/courses/{course['id']}"))
            _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/title-confirmations",
                    json={
                        "candidate_id": title["candidates"][0]["id"],
                        "expected_course_version": current_course["version"],
                    },
                    headers={"Idempotency-Key": f"real-title-{uuid.uuid4().hex}"},
                )
            )
            snapshot = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/context-snapshots",
                    json={
                        "task_type": "stage1_validation",
                        "selected_materials": [
                            {
                                "id": item["id"],
                                "parse_version": item["active_parse_version_id"],
                                "selected_order": index,
                            }
                            for index, item in enumerate(final_materials)
                        ],
                    },
                    headers={"Idempotency-Key": f"real-context-{uuid.uuid4().hex}"},
                ),
                201,
            )
            locators = {
                _require(client.get(f"/api/v1/source-refs/{source_id}"))["locator_type"]
                for source_id in snapshot["source_ref_ids"]
            }
            for material_id in material_ids:
                original = client.get(f"/api/v1/materials/{material_id}/original")
                if original.status_code != 200 or not original.content:
                    raise RuntimeError("original:unavailable")
            return {
                "status": "passed",
                "material_count": len(final_materials),
                "material_statuses": sorted({item["status"] for item in final_materials}),
                "title_model_id": title["returned_model_id"],
                "coverage_status": snapshot["coverage_status"],
                "locator_types": sorted(locators),
            }
    finally:
        engine.dispose()


def main() -> None:
    env = dict(dotenv_values(ENV_FILE))
    with tempfile.TemporaryDirectory(prefix="benren-stage1-real-backend-") as temp:
        try:
            result = _run(_settings(env, Path(temp)), Path(temp))
        except Exception as exc:  # noqa: BLE001 - keep smoke output redacted
            result = {"status": "failed", "error_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
