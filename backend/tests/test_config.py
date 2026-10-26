from __future__ import annotations

import pytest

from app.core.config import Settings


def test_uppercase_cloud_environment_variables_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENREN_APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TITLE_MODEL_ID", "deepseek-chat")
    monkeypatch.setenv("INVITE_CODE_HASHES", '["hash-one"]')

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.llm_provider == "deepseek"
    assert settings.title_model_id == "deepseek-chat"
    assert settings.invite_code_hashes == ["hash-one"]


def test_product_environment_overrides_vefaas_reserved_app_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "volcengine_cnbeijingprod_new")
    monkeypatch.setenv("BENREN_APP_ENV", "production")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"


def test_retired_deepseek_flash_route_uses_canonical_request_model() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        title_model_id="deepseek-v4-flash",
        generation_model_id="deepseek-v4-flash",
        tutor_model_id="deepseek-v4-flash",
        verify_model_id="deepseek-v4-flash",
        plan_model_id="deepseek-v4-flash",
        date_model_id="deepseek-v4-flash",
    )

    for route in (
        "title_model_id",
        "generation_model_id",
        "tutor_model_id",
        "verify_model_id",
        "plan_model_id",
        "date_model_id",
    ):
        assert getattr(settings, route) == "deepseek-flash"


def test_deepseek_model_migration_preserves_other_routes() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        title_model_id="deepseek-v4-flash",
        verify_model_id="deepseek-v4-pro",
    )
    assert settings.title_model_id == "deepseek-flash"
    assert settings.generation_model_id == "deepseek-flash"
    assert settings.verify_model_id == "deepseek-v4-pro"

    mock = Settings(_env_file=None, title_model_id="deepseek-v4-flash")
    assert mock.title_model_id == "deepseek-v4-flash"
