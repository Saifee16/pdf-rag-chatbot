import httpx
from fastapi import status

from app.core.exceptions import AppError
from app.providers.base import ChatProvider, GeneratedAnswer


class GatewayChatProvider(ChatProvider):
    name = "gateway"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_alias: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model_alias
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> GeneratedAnswer:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-Gateway-Key"] = self.api_key

        try:
            response = httpx.post(
                f"{self.base_url}/api/v1/chat",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()["data"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise AppError(
                message="LLM gateway request failed.",
                code="GATEWAY_REQUEST_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return GeneratedAnswer(
            content=payload["content"],
            provider=f"gateway:{payload['provider']}",
            model=payload["model"],
        )
