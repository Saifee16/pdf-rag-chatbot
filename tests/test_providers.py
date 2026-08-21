from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.providers.gateway import GatewayChatProvider
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider


class FakeGeminiInteractions:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="Gemini answer")


class FakeGeminiModels:
    def embed_content(self, *, contents, **kwargs):
        items = contents if isinstance(contents, list) else [contents]
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[float(index), 1.0]) for index, _ in enumerate(items)
            ]
        )


class FakeGeminiClient:
    def __init__(self) -> None:
        self.interactions = FakeGeminiInteractions()
        self.models = FakeGeminiModels()


def test_gemini_adapter_normalizes_generation_and_embeddings() -> None:
    provider = GeminiProvider(api_key="key", chat_model="chat", embedding_model="embed")
    provider.client = FakeGeminiClient()

    answer = provider.generate(system_instruction="policy", prompt="hello")
    documents = provider.embed_documents(["a", "b"])
    query = provider.embed_query("a")

    assert answer.content == "Gemini answer"
    assert answer.provider == "gemini"
    assert provider.client.interactions.kwargs["system_instruction"] == "policy"
    assert provider.client.interactions.kwargs["input"] == "hello"
    assert provider.client.interactions.kwargs["store"] is False
    assert len(documents) == 2
    assert query == [0.0, 1.0]


class FakeOpenAIResponses:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="OpenAI answer")


class FakeOpenAIEmbeddings:
    def create(self, *, input, **kwargs):
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[float(index), 2.0]) for index, _ in enumerate(input)]
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeOpenAIResponses()
        self.embeddings = FakeOpenAIEmbeddings()


def test_openai_adapter_normalizes_generation_and_embeddings() -> None:
    provider = OpenAIProvider(
        api_key="key",
        chat_model="chat",
        embedding_model="embed",
        timeout_seconds=10,
    )
    provider.client = FakeOpenAIClient()

    assert provider.generate(system_instruction="policy", prompt="hello").content == "OpenAI answer"
    assert provider.client.responses.kwargs["instructions"] == "policy"
    assert provider.client.responses.kwargs["input"] == "hello"
    assert provider.client.responses.kwargs["store"] is False
    assert provider.embed_documents(["a", "b"])[1] == [1.0, 2.0]
    assert provider.embed_query("a") == [0.0, 2.0]


def test_gateway_provider_parses_project_3_shape(monkeypatch) -> None:
    provider = GatewayChatProvider(
        base_url="http://gateway",
        api_key="key",
        model_alias="fast",
        timeout_seconds=10,
    )
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "data": {
                    "content": "Gateway answer",
                    "provider": "gemini",
                    "model": "gemini-test",
                }
            }

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    answer = provider.generate(system_instruction="policy", prompt="hello")

    assert answer.content == "Gateway answer"
    assert answer.provider == "gateway:gemini"
    assert captured["headers"]["X-Gateway-Key"] == "key"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "hello"},
    ]


def test_provider_sdk_failures_are_normalized() -> None:
    provider = GeminiProvider(api_key="key", chat_model="chat", embedding_model="embed")

    class BrokenInteractions:
        def create(self, **kwargs):
            raise RuntimeError("sdk failure")

    provider.client = SimpleNamespace(
        interactions=BrokenInteractions(),
        models=FakeGeminiModels(),
    )

    with pytest.raises(AppError) as exc_info:
        provider.generate(system_instruction="policy", prompt="hello")

    assert exc_info.value.code == "GEMINI_GENERATION_FAILED"
    assert exc_info.value.status_code == 502
