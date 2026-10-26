from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.core.errors import ApiError
from app.providers.asr import VolcengineAsrProvider
from app.providers.llm import DeepSeekTitleProvider
from app.providers.ocr import VolcengineOcrProvider
from app.schemas.providers import TitleScopeItem

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env.production.local"


def _required(env: dict[str, str | None], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing:{key}")
    return value


def _settings(env: dict[str, str | None]) -> Settings:
    return Settings(
        llm_provider="deepseek",
        title_model_id="deepseek-flash",
        model_api_key=_required(env, "DEEPSEEK_API_KEY"),
        asr_provider="volcengine",
        asr_model_id="volc-bigasr-standard-v1",
        asr_auth_mode="api_key",
        asr_api_key=_required(env, "VOLCENGINE_BIGASR_API_KEY"),
        asr_resource_id="volc.bigasr.auc",
        asr_mode="standard",
        ocr_provider="volcengine",
        ocr_model_id="MultiLanguageOCR@2022-08-31",
        ocr_access_key_id=_required(env, "VOLCENGINE_ACCESS_KEY_ID"),
        ocr_secret_access_key=_required(env, "VOLCENGINE_SECRET_ACCESS_KEY"),
        ocr_action="MultiLanguageOCR",
        ocr_version="2022-08-31",
    )


def _safe_error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ApiError):
        return {"status": "failed", "error_type": exc.code, "message": exc.message}
    return {"status": "failed", "error_type": type(exc).__name__}


def _deepseek(settings: Settings) -> dict[str, object]:
    system_prompt = (PROJECT_ROOT / "backend/app/prompts/BL-SYS-001-v2.8.0.txt").read_text()
    title_prompt = (PROJECT_ROOT / "backend/app/prompts/BL-TITLE-001-v2.8.0.txt").read_text()
    provider = DeepSeekTitleProvider(settings, system_prompt, title_prompt)
    result = provider.generate_title(
        [
            TitleScopeItem(
                material_id="mat_smoke",
                display_name="光合作用课堂笔记.txt",
                source_ref_id="src_smoke",
                excerpt="植物利用光能，把二氧化碳和水转化为有机物并释放氧气。",
            )
        ]
    )
    return {
        "status": "passed",
        "provider": "deepseek",
        "model_id": result.returned_model_id,
        "candidate_count": len(result.candidates),
    }


def _ocr(settings: Settings, directory: Path) -> dict[str, object]:
    image_path = directory / "ocr-smoke.png"
    image = Image.new("RGB", (1400, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 76)
    draw.text((70, 110), "第一阶段真实识别测试", fill="black", font=font)
    image.save(image_path)
    result = VolcengineOcrProvider(settings).extract(image_path, image_path.name)
    return {
        "status": "passed",
        "provider": result.provider,
        "model_id": result.model_id,
        "segment_count": len(result.segments),
    }


def _asr(settings: Settings, directory: Path) -> dict[str, object]:
    aiff_path = directory / "asr-smoke.aiff"
    wav_path = directory / "asr-smoke.wav"
    subprocess.run(
        [
            "/usr/bin/say",
            "-v",
            "Tingting",
            "这是一段用于验证课堂录音识别的测试语音。",
            "-o",
            str(aiff_path),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff_path), str(wav_path)],
        check=True,
        capture_output=True,
    )
    result = VolcengineAsrProvider(settings).transcribe(wav_path, wav_path.name)
    return {
        "status": "passed",
        "provider": result.provider,
        "model_id": result.model_id,
        "segment_count": len(result.segments),
    }


def main() -> None:
    env = dict(dotenv_values(ENV_FILE))
    settings = _settings(env)
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="benren-provider-smoke-") as temp:
        directory = Path(temp)
        for name, check in (
            ("deepseek", lambda: _deepseek(settings)),
            ("ocr", lambda: _ocr(settings, directory)),
            ("asr", lambda: _asr(settings, directory)),
        ):
            try:
                results[name] = check()
            except Exception as exc:  # noqa: BLE001 - the smoke output must remain redacted
                results[name] = _safe_error(exc)
    print(json.dumps(results, ensure_ascii=False))
    if any(item.get("status") != "passed" for item in results.values() if isinstance(item, dict)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
