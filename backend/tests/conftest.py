from __future__ import annotations

import io
import json
import wave
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_invite_code
from app.db import create_app_engine, get_db
from app.models import Base
from app.models.entities import ProcessingJob
from app.services.jobs import claim_next_job
from app.services.materials.processing import execute_job
from app.services.storage.local import LocalStorage

INVITE_A = "stage-one-user-a"
INVITE_B = "stage-one-user-b"


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_root=tmp_path / "storage",
        session_signing_key="test-session-signing-key-with-32-characters",
        invite_code_hashes=[hash_invite_code(INVITE_A), hash_invite_code(INVITE_B)],
        direct_context_token_limit=400,
        direct_context_safety_margin=40,
        job_poll_seconds=0.01,
    )


@pytest.fixture
def session_factory(
    test_settings: Settings,
) -> Generator[sessionmaker[Session], None, None]:
    engine = create_app_engine(test_settings.database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
    session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    from app import main

    monkeypatch.setattr(main, "settings", test_settings)
    test_app = main.create_app()

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(test_app) as test_client:
        yield test_client


@pytest.fixture
def login() -> Callable[[TestClient, str], None]:
    def perform(client: TestClient, invite: str = INVITE_A) -> None:
        response = client.post("/api/v1/auth/invite-session", json={"invite_code": invite})
        assert response.status_code == 200, response.text

    return perform


@pytest.fixture
def run_jobs(session_factory: sessionmaker[Session], test_settings: Settings) -> Callable[[], None]:
    def run() -> None:
        storage = LocalStorage(test_settings.storage_root)
        for _ in range(100):
            with session_factory() as db:
                job = claim_next_job(db, "pytest-worker")
                job_id = job.id if job else None
                db.commit()
            if job_id is None:
                return
            with session_factory() as db:
                claimed = db.get(ProcessingJob, job_id)
                assert claimed is not None
                execute_job(db, settings=test_settings, storage=storage, job=claimed)
                db.commit()
        raise AssertionError("job queue did not become idle")

    return run


def create_course(client: TestClient, key: str = "course-key-0001") -> dict[str, object]:
    response = client.post("/api/v1/courses", json={}, headers={"Idempotency-Key": key})
    assert response.status_code == 201, response.text
    return response.json()


def png_bytes(color: tuple[int, int, int] = (245, 245, 230)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 8_000)
    return buffer.getvalue()


def docx_bytes(*paragraphs: str) -> bytes:
    buffer = io.BytesIO()
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


def pdf_bytes(text: str) -> bytes:
    """Build a small text-layer PDF without adding a test-only dependency."""
    buffer = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(buffer)
    return buffer.getvalue()


def upload_manifest(
    client: TestClient,
    course_id: str,
    manifest: dict[str, object],
    files: list[tuple[str, tuple[str, bytes, str]]],
    key: str,
):
    return client.post(
        f"/api/v1/courses/{course_id}/material-batches",
        data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        files=files,
        headers={"Idempotency-Key": key},
    )
