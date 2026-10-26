from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Cloud consoles and the checked-in example use conventional uppercase
        # environment keys (BENREN_APP_ENV, MODEL_API_KEY, ...).
        case_sensitive=False,
        populate_by_name=True,
    )

    # veFaaS reserves APP_ENV and overwrites it with an internal deployment
    # marker. Prefer the product-scoped key in cloud environments while still
    # accepting APP_ENV for existing local setups.
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("BENREN_APP_ENV", "APP_ENV"),
    )
    app_base_url: str = "http://localhost:3100"
    api_base_url: str = "http://127.0.0.1:8100"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data/db/benren_learning.db'}"
    storage_root: Path = PROJECT_ROOT / "data/storage"
    storage_provider: Literal["local", "s3"] = "local"
    s3_endpoint: str = "https://tos-s3-cn-beijing.volces.com"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = ""
    s3_region: str = "cn-beijing"
    backup_enabled: bool = False
    backup_interval_seconds: int = 300
    backup_object_key: str = "db_backup/benren_learning.db"

    auth_mode: Literal["invite"] = "invite"
    session_signing_key: SecretStr = SecretStr("development-only-change-this-secret")
    invite_code_hashes: list[str] = Field(default_factory=list)
    timed_invite_code_hashes: list[str] = Field(default_factory=list)
    session_cookie_name: str = "bl_session"
    session_ttl_hours: int = 168
    csrf_origin_protection: bool = True
    csrf_trusted_origins: list[str] = Field(default_factory=list)
    internal_governance_subject_hashes: list[str] = Field(default_factory=list)

    llm_provider: Literal["mock", "deepseek"] = "mock"
    title_model_id: str = "mock-title-v1"
    model_api_key: SecretStr = SecretStr("")
    model_base_url: str = "https://api.deepseek.com"
    title_timeout_seconds: int = 30
    generation_model_id: str = ""
    tutor_model_id: str = ""
    verify_model_id: str = ""
    plan_model_id: str = ""
    date_model_id: str = ""
    generation_timeout_seconds: int = 90
    tutor_timeout_seconds: int = 60
    plan_timeout_seconds: int = 60

    asr_provider: Literal["mock", "volcengine"] = "mock"
    asr_model_id: str = "mock-asr-v1"
    asr_auth_mode: Literal["api_key", "legacy"] = "api_key"
    asr_api_key: SecretStr = SecretStr("")
    asr_app_key: SecretStr = SecretStr("")
    asr_access_key: SecretStr = SecretStr("")
    asr_resource_id: str = "volc.bigasr.auc"
    asr_base_url: str = "https://openspeech.bytedance.com/api/v3/auc/bigmodel"
    asr_mode: Literal["standard", "flash"] = "standard"
    asr_timeout_seconds: int = 300
    asr_poll_seconds: float = 3.0

    ocr_provider: Literal["mock", "volcengine"] = "mock"
    ocr_model_id: str = "mock-ocr-v1"
    ocr_access_key_id: SecretStr = SecretStr("")
    ocr_secret_access_key: SecretStr = SecretStr("")
    ocr_action: Literal["OCRNormal", "MultiLanguageOCR"] = "MultiLanguageOCR"
    ocr_version: str = "2022-08-31"
    ocr_timeout_seconds: int = 60

    max_audio_bytes: int = 200 * 1024 * 1024
    max_audio_duration_seconds: int = 3 * 60 * 60
    max_image_bytes: int = 20 * 1024 * 1024
    max_image_count_per_batch: int = 50
    max_text_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 300
    max_batch_items: int = 60
    max_batch_bytes: int = 500 * 1024 * 1024
    # The public API gateway rejects request bodies around 16 MiB. Files at or
    # above this conservative threshold are uploaded straight to private TOS
    # and are still verified by the backend before becoming materials.
    direct_upload_threshold_bytes: int = 8 * 1024 * 1024
    direct_upload_expires_seconds: int = 15 * 60

    direct_context_token_limit: int = 100_000
    direct_context_safety_margin: int = 10_000
    context_policy_version: str = "indexed-context-v2"
    retrieval_config_version: str = "hybrid-embedding-v2"
    retrieval_chunk_chars: int = 800
    retrieval_chunk_overlap_chars: int = 120
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.08
    retrieval_vector_floor: float = 0.2
    embedding_provider: Literal["local", "openai_compatible"] = "local"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model_id: str = "local-hash-ngram-v1"
    embedding_dimensions: int = 384
    embedding_batch_size: int = 64
    embedding_timeout_seconds: int = 60
    tutor_max_turns: int = 12
    default_timezone: str = "Asia/Shanghai"
    default_review_duration_min: int = 10
    calendar_confirmation_ttl_minutes: int = 15

    # 第三阶段扩展能力默认安全关闭；只有白名单和凭据同时存在时才允许外呼。
    official_search_provider: Literal["disabled", "mock", "volcengine"] = "disabled"
    official_search_api_key: SecretStr = SecretStr("")
    official_search_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    official_search_model_id: str = ""
    official_search_allowed_domains: list[str] = Field(default_factory=list)
    official_search_policy_version: str = "official-whitelist-v1"
    official_search_timeout_seconds: int = 45

    external_calendar_provider: Literal["disabled", "mock", "generic_oauth"] = "disabled"
    external_calendar_client_id: str = ""
    external_calendar_client_secret: SecretStr = SecretStr("")
    external_calendar_authorize_url: str = ""
    external_calendar_token_url: str = ""
    external_calendar_events_url: str = ""
    external_calendar_scopes: list[str] = Field(default_factory=lambda: ["calendar.events"])
    external_calendar_redirect_uri: str = ""
    external_calendar_timeout_seconds: int = 30

    notification_provider: Literal["disabled", "mock", "webhook"] = "disabled"
    notification_webhook_url: str = ""
    notification_webhook_secret: SecretStr = SecretStr("")
    notification_timeout_seconds: int = 15

    sft_provider: Literal["disabled", "mock", "volcengine"] = "disabled"
    sft_api_key: SecretStr = SecretStr("")
    sft_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    sft_launch_path: str = "/fine_tuning/jobs"
    sft_min_authorized_records: int = 20

    job_max_attempts: int = 3
    job_heartbeat_seconds: int = 10
    job_stale_seconds: int = 120
    job_poll_seconds: float = 1.0

    raw_retention_days: int = 30
    derived_retention_days: int = 30
    audit_retention_days: int = 180
    delete_sla_hours: int = 24

    log_level: str = "INFO"
    log_redaction_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3100"])

    @field_validator("storage_root", mode="before")
    @classmethod
    def resolve_storage_root(cls, value: object) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path

    @field_validator(
        "max_audio_bytes",
        "max_audio_duration_seconds",
        "max_image_bytes",
        "max_image_count_per_batch",
        "max_text_bytes",
        "max_pdf_pages",
        "max_batch_items",
        "max_batch_bytes",
        "direct_upload_threshold_bytes",
        "direct_upload_expires_seconds",
        "direct_context_token_limit",
        "retrieval_chunk_chars",
        "retrieval_top_k",
        "embedding_dimensions",
        "embedding_batch_size",
        "embedding_timeout_seconds",
        "tutor_max_turns",
        "default_review_duration_min",
        "calendar_confirmation_ttl_minutes",
        "official_search_timeout_seconds",
        "external_calendar_timeout_seconds",
        "notification_timeout_seconds",
        "sft_min_authorized_records",
        "job_max_attempts",
        "job_heartbeat_seconds",
        "job_stale_seconds",
        "raw_retention_days",
        "derived_retention_days",
        "audit_retention_days",
        "delete_sla_hours",
        "backup_interval_seconds",
    )
    @classmethod
    def positive_numbers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("retrieval_chunk_overlap_chars")
    @classmethod
    def non_negative_overlap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @field_validator("retrieval_min_score")
    @classmethod
    def valid_retrieval_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("must be between 0 and 1")
        return value

    @field_validator("retrieval_vector_floor")
    @classmethod
    def valid_vector_floor(cls, value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError("must be between 0 (inclusive) and 1 (exclusive)")
        return value

    @model_validator(mode="after")
    def inherit_stage_models(self) -> Settings:
        # 未单独配置时复用已经真实验收的模型，避免把 Mock model_id
        # 误发给正式 DeepSeek 网关。三个路由仍可在环境变量中独立覆盖。
        self.generation_model_id = self.generation_model_id or self.title_model_id
        self.tutor_model_id = self.tutor_model_id or self.title_model_id
        self.verify_model_id = self.verify_model_id or self.title_model_id
        self.plan_model_id = self.plan_model_id or self.generation_model_id
        self.date_model_id = self.date_model_id or self.generation_model_id
        # DeepSeek retired V4 Flash on 2026-09-11. Its legacy API name is
        # accepted but responses now identify deepseek-flash. Migrate this
        # known route before requests/audit snapshots are built, rather than
        # weakening the providers' requested/returned model identity gate.
        if self.llm_provider == "deepseek":
            for route in (
                "title_model_id",
                "generation_model_id",
                "tutor_model_id",
                "verify_model_id",
                "plan_model_id",
                "date_model_id",
            ):
                if getattr(self, route) == "deepseek-v4-flash":
                    setattr(self, route, "deepseek-flash")
        return self

    def validate_runtime_secrets(self) -> None:
        if self.app_env != "production":
            return
        if len(self.session_signing_key.get_secret_value()) < 32:
            raise ValueError("SESSION_SIGNING_KEY must contain at least 32 characters")
        if not self.invite_code_hashes:
            raise ValueError("INVITE_CODE_HASHES cannot be empty in production")
        if not self.csrf_origin_protection:
            raise ValueError("CSRF_ORIGIN_PROTECTION=true is required in production")
        if not self.app_base_url.startswith("https://") or not self.api_base_url.startswith(
            "https://"
        ):
            raise ValueError("APP_BASE_URL and API_BASE_URL must use HTTPS in production")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            raise ValueError("CORS_ORIGINS must use HTTPS in production")
        if self.storage_provider != "s3":
            raise ValueError("STORAGE_PROVIDER=s3 is required in production")
        if not (
            self.s3_endpoint
            and self.s3_access_key.get_secret_value()
            and self.s3_secret_key.get_secret_value()
            and self.s3_bucket
            and self.s3_region
        ):
            raise ValueError(
                "S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY/S3_BUCKET/S3_REGION are required"
            )
        if not self.backup_enabled:
            raise ValueError("BACKUP_ENABLED=true is required in production")
        if self.llm_provider == "deepseek" and not self.model_api_key.get_secret_value():
            raise ValueError("MODEL_API_KEY is required for the DeepSeek provider")
        if self.embedding_provider == "openai_compatible" and not (
            self.embedding_api_key.get_secret_value()
            and self.embedding_base_url
            and self.embedding_model_id
        ):
            raise ValueError(
                "EMBEDDING_API_KEY/EMBEDDING_BASE_URL/EMBEDDING_MODEL_ID are required "
                "for the OpenAI-compatible embedding provider"
            )
        if self.asr_provider == "volcengine":
            if self.asr_auth_mode == "api_key" and not self.asr_api_key.get_secret_value():
                raise ValueError("ASR_API_KEY is required for the Volcengine ASR provider")
            if self.asr_auth_mode == "legacy" and not (
                self.asr_app_key.get_secret_value() and self.asr_access_key.get_secret_value()
            ):
                raise ValueError("ASR_APP_KEY and ASR_ACCESS_KEY are required for legacy ASR auth")
        if self.ocr_provider == "volcengine" and not (
            self.ocr_access_key_id.get_secret_value()
            and self.ocr_secret_access_key.get_secret_value()
        ):
            raise ValueError(
                "OCR_ACCESS_KEY_ID and OCR_SECRET_ACCESS_KEY are required for Volcengine OCR"
            )
        if self.official_search_provider == "volcengine" and not (
            self.official_search_api_key.get_secret_value()
            and self.official_search_model_id
            and self.official_search_allowed_domains
        ):
            raise ValueError(
                "OFFICIAL_SEARCH_API_KEY/OFFICIAL_SEARCH_MODEL_ID/"
                "OFFICIAL_SEARCH_ALLOWED_DOMAINS are required"
            )
        if self.external_calendar_provider == "generic_oauth" and not all(
            [
                self.external_calendar_client_id,
                self.external_calendar_client_secret.get_secret_value(),
                self.external_calendar_authorize_url,
                self.external_calendar_token_url,
                self.external_calendar_events_url,
                self.external_calendar_redirect_uri,
            ]
        ):
            raise ValueError("external calendar OAuth configuration is incomplete")
        if self.notification_provider == "webhook" and not (
            self.notification_webhook_url
            and self.notification_webhook_secret.get_secret_value()
        ):
            raise ValueError("notification webhook configuration is incomplete")
        if self.sft_provider == "volcengine" and not self.sft_api_key.get_secret_value():
            raise ValueError("SFT_API_KEY is required for the Volcengine SFT provider")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_secrets()
    return settings
