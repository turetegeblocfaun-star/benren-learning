from __future__ import annotations

from app.schemas.common import ApiModel


class UploadTypeCapability(ApiModel):
    extensions: list[str]
    mime_types: list[str]
    max_bytes: int
    max_duration_seconds: int | None = None


class UploadCapabilities(ApiModel):
    audio: UploadTypeCapability
    text: UploadTypeCapability
    image: UploadTypeCapability
    max_image_count_per_batch: int
    max_batch_items: int
    max_batch_bytes: int
    max_pdf_pages: int
    direct_upload_enabled: bool
    direct_upload_threshold_bytes: int
    direct_upload_expires_seconds: int


class ProviderCapability(ApiModel):
    provider: str
    configured: bool


class SecurityCapability(ApiModel):
    cookie_http_only: bool
    cookie_secure_in_production: bool
    same_site: str
    csrf_origin_protection: bool


class CapabilitiesResponse(ApiModel):
    api_contract_version: str
    upload: UploadCapabilities
    providers: dict[str, ProviderCapability]
    features: dict[str, bool]
    security: SecurityCapability
