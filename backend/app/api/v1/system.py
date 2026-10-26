from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings
from app.schemas.system import (
    CapabilitiesResponse,
    ProviderCapability,
    SecurityCapability,
    UploadCapabilities,
    UploadTypeCapability,
)

router = APIRouter(tags=["system"])


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities(settings: AppSettings) -> CapabilitiesResponse:
    llm_configured = settings.llm_provider == "mock" or bool(
        settings.model_api_key.get_secret_value() and settings.generation_model_id
    )
    asr_configured = settings.asr_provider == "mock" or bool(
        settings.asr_api_key.get_secret_value()
        if settings.asr_auth_mode == "api_key"
        else settings.asr_app_key.get_secret_value()
        and settings.asr_access_key.get_secret_value()
    )
    ocr_configured = settings.ocr_provider == "mock" or bool(
        settings.ocr_access_key_id.get_secret_value()
        and settings.ocr_secret_access_key.get_secret_value()
    )
    return CapabilitiesResponse(
        api_contract_version="2026-09-integration-v3",
        upload=UploadCapabilities(
            audio=UploadTypeCapability(
                extensions=[".mp3", ".m4a", ".wav", ".webm", ".ogg", ".opus"],
                mime_types=[
                    "audio/mpeg",
                    "audio/mp4",
                    "audio/wav",
                    "audio/webm",
                    "audio/ogg",
                    "audio/opus",
                ],
                max_bytes=settings.max_audio_bytes,
                max_duration_seconds=settings.max_audio_duration_seconds,
            ),
            text=UploadTypeCapability(
                extensions=[".txt", ".md", ".docx", ".pdf"],
                mime_types=[
                    "text/plain",
                    "text/markdown",
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ],
                max_bytes=settings.max_text_bytes,
            ),
            image=UploadTypeCapability(
                extensions=[".jpg", ".jpeg", ".png", ".webp"],
                mime_types=["image/jpeg", "image/png", "image/webp"],
                max_bytes=settings.max_image_bytes,
            ),
            max_image_count_per_batch=settings.max_image_count_per_batch,
            max_batch_items=settings.max_batch_items,
            max_batch_bytes=settings.max_batch_bytes,
            max_pdf_pages=settings.max_pdf_pages,
            direct_upload_enabled=settings.storage_provider == "s3",
            direct_upload_threshold_bytes=settings.direct_upload_threshold_bytes,
            direct_upload_expires_seconds=settings.direct_upload_expires_seconds,
        ),
        providers={
            "llm": ProviderCapability(provider=settings.llm_provider, configured=llm_configured),
            "asr": ProviderCapability(provider=settings.asr_provider, configured=asr_configured),
            "ocr": ProviderCapability(provider=settings.ocr_provider, configured=ocr_configured),
            "official_search": ProviderCapability(
                provider=settings.official_search_provider,
                configured=settings.official_search_provider != "disabled",
            ),
            "external_calendar": ProviderCapability(
                provider=settings.external_calendar_provider,
                configured=settings.external_calendar_provider != "disabled",
            ),
            "notification": ProviderCapability(
                provider=settings.notification_provider,
                configured=settings.notification_provider != "disabled",
            ),
            "sft": ProviderCapability(
                provider=settings.sft_provider,
                configured=settings.sft_provider != "disabled",
            ),
        },
        features={
            "p0_learning": True,
            "p1_subjective_review": True,
            "p1_external_calendar": settings.external_calendar_provider != "disabled",
            "p2_organizations": True,
            "p2_cross_course": True,
            "p2_sft": settings.sft_provider != "disabled",
            "task_cancellation": True,
        },
        security=SecurityCapability(
            cookie_http_only=True,
            cookie_secure_in_production=True,
            same_site="lax",
            csrf_origin_protection=settings.csrf_origin_protection,
        ),
    )
