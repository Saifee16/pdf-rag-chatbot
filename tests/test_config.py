import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(CHUNK_SIZE=500, CHUNK_OVERLAP=500)

    assert "CHUNK_OVERLAP must be smaller than CHUNK_SIZE" in str(exc_info.value)


def test_pdf_page_limit_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(MAX_PDF_PAGES=0)


def test_ocr_resource_and_language_limits_are_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, OCR_TIMEOUT_SECONDS=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, OCR_LANGUAGES="eng;cat")

    settings = Settings(
        _env_file=None,
        OCR_ENABLED=True,
        OCR_LANGUAGES="eng, deu",
        OCR_DPI=200,
        OCR_MAX_PAGES=5,
    )
    assert settings.ocr_languages == "eng, deu"


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_ENV": "production",
        "APP_DEBUG": False,
        "API_AUTH_ENABLED": True,
        "API_KEYS": "unit-test-key-placeholder",
        "ALLOWED_HOSTS": "rag.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(APP_DEBUG=True)

    assert "APP_DEBUG must be false" in str(exc_info.value)


def test_production_requires_api_authentication() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(API_AUTH_ENABLED=False)

    assert "API_AUTH_ENABLED must be true" in str(exc_info.value)


def test_production_requires_at_least_one_api_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(API_KEYS="")

    assert "API_KEYS must contain at least one key" in str(exc_info.value)


def test_production_rejects_wildcard_allowed_hosts() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(ALLOWED_HOSTS="rag.example.com,*")

    assert "ALLOWED_HOSTS must not contain '*'" in str(exc_info.value)


def test_production_accepts_hardened_baseline() -> None:
    settings = _production_settings()

    assert settings.app_env == "production"
    assert settings.app_debug is False
    assert settings.api_auth_enabled is True
    assert settings.parsed_api_keys
    assert settings.parsed_allowed_hosts == ["rag.example.com"]
