# Adding an AI Provider

The service deliberately separates chat and embedding contracts. A provider may implement one or both.

## 1. Choose the capability

Chat providers implement:

```python
class ChatProvider(ABC):
    name: str
    model: str

    @property
    def configured(self) -> bool:
        ...

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> GeneratedAnswer:
        ...
```

Embedding providers implement:

```python
class EmbeddingProvider(ABC):
    name: str
    model: str

    @property
    def configured(self) -> bool:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

## 2. Keep the trust boundary

Do not concatenate `system_instruction` with the untrusted RAG prompt unless your provider has no concept of a system/instruction channel and you have explicitly accepted that limitation.

The current adapters map the system policy as follows:

```text
Gemini       system_instruction=
OpenAI       instructions=
Project 3    role=system message
```

Document text remains inside the ordinary prompt.

## 3. Normalize output

Return:

```python
GeneratedAnswer(
    content="...",
    provider="provider-name",
    model="provider-model-id",
)
```

Do not return SDK response objects from an adapter.

## 4. Normalize failures

Configuration failure example:

```python
raise AppError(
    message="Example provider is not configured.",
    code="EXAMPLE_NOT_CONFIGURED",
    status_code=503,
)
```

Unexpected upstream failure example:

```python
try:
    response = client.generate(...)
except AppError:
    raise
except Exception as exc:
    raise AppError(
        message="Example generation failed.",
        code="EXAMPLE_GENERATION_FAILED",
        status_code=502,
    ) from exc
```

The API should not leak provider stack traces or raw credentials to clients.

## 5. Add settings

Add only provider-specific configuration to `app/core/config.py` and `.env.example`.

Example:

```python
example_api_key: str = Field(default="", alias="EXAMPLE_API_KEY")
```

If the provider needs a different model field, add it explicitly. Avoid hardcoding secrets.

## 6. Register the provider

Update `app/providers/registry.py`.

For a chat provider:

```python
example = ExampleProvider(...)
chat_providers={
    "gemini": gemini,
    "openai": openai,
    "gateway": gateway,
    "example": example,
}
```

For an embedding provider:

```python
embedding_providers={
    "gemini": gemini,
    "openai": openai,
    "example": example,
}
```

Update the `Literal[...]` values in `Settings` so Pydantic accepts the provider name.

## 7. Think about index compatibility

Changing the embedding provider or model changes the index fingerprint automatically because both fields are part of the fingerprint.

Therefore existing documents become stale for the new configuration and must be reindexed.

A new chat-only provider does not require document reindexing.

## 8. Add adapter tests

Tests should use fake SDK-shaped clients rather than paid network calls.

Minimum chat assertions:

- system policy is mapped to the provider's policy channel
- prompt is passed separately
- output is normalized to `GeneratedAnswer`
- provider/model identity is preserved
- SDK failures become `AppError`

Minimum embedding assertions:

- multiple document inputs return the same number of vectors
- one query returns one vector
- vectors become plain `list[float]`
- query/document task semantics are mapped when the provider supports them
- SDK failures become `AppError`

## 9. Run the full quality gate

```bash
ruff check .
ruff format --check .
pytest --cov=app --cov=evaluation --cov-report=term-missing --cov-fail-under=80
```

If embedding behavior changed, also run a retrieval evaluation and document whether reindexing is required.
