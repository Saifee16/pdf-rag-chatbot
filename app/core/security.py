import secrets
from typing import Annotated

from fastapi import Header, status

from app.core.config import get_settings
from app.core.exceptions import AppError


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    settings = get_settings()
    if not settings.api_auth_enabled:
        return

    if not settings.parsed_api_keys:
        raise AppError(
            message="API authentication is enabled but no API keys are configured.",
            code="API_AUTH_MISCONFIGURED",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    is_valid = False
    if x_api_key is not None:
        for configured_key in settings.parsed_api_keys:
            is_valid |= secrets.compare_digest(x_api_key, configured_key)

    if not is_valid:
        raise AppError(
            message="A valid X-API-Key header is required.",
            code="INVALID_API_KEY",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
