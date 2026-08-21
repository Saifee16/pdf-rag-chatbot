# Contributing

Contributions to PDF RAG Chatbot are welcome when they improve the reusable RAG baseline without obscuring the core architecture.

## Development setup

Clone:

```bash
git clone https://github.com/Saifee16/pdf-rag-chatbot.git
cd pdf-rag-chatbot
```

Create a virtual environment.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### macOS/Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

Install:

```bash
pip install -r requirements-dev.txt
```

Copy environment template:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env` or uploaded documents.

## Recommended infrastructure

The full application requires Redis and Qdrant, plus a relational database.

The easiest complete development environment is:

```bash
docker compose up --build
```

For direct Python execution, start Redis and Qdrant separately, apply Alembic migrations, run Uvicorn, and run a Celery worker.

## Quality gate

Run before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest --cov=app --cov=evaluation --cov-report=term-missing --cov-fail-under=80
```

Validate migrations after schema work:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Validate Compose:

```bash
docker compose config --quiet
```

Build the image after Docker/runtime changes:

```bash
docker build -t pdf-rag-chatbot .
```

## Security gates

GitHub runs a separate `Security` workflow with:

```text
Gitleaks Secret Scan
Trivy Filesystem Scan
Trivy Container Scan
```

The Trivy jobs block fixable `HIGH` and `CRITICAL` findings. Push/scheduled runs upload Trivy SARIF to code scanning; pull requests still block on scan results but skip the SARIF upload step. CodeQL and `pip-audit` remain separate automated checks. Organization-owned repositories must configure the `GITLEAKS_LICENSE` secret required by the official Gitleaks Action.

Before changing production configuration behavior, run the test suite and preserve the fail-closed `APP_ENV=production` guardrails in `app/core/config.py`.

Do not add Gitleaks or Trivy ignore rules merely to make CI green. Any suppression must be narrowly scoped, documented, and justified in the pull request.

See `docs/SECURITY_CHECKS.md`.

## Branches

Create a focused branch from `main`:

```bash
git checkout main
git pull origin main
git checkout -b feature/short-description
```

Examples:

```text
feature/s3-storage-adapter
feature/hybrid-retrieval
fix/reindex-queue-failure
```

## RAG changes require extra reasoning

A pull request must explicitly state whether it changes:

- PDF extraction
- chunk boundaries
- chunk overlap
- embedding provider/model
- vector payload
- retrieval filters
- retrieval threshold
- top-k behavior
- RAG system policy
- citation parsing

If the change affects embedding or chunk configuration, state whether existing documents require reindexing.

## Database schema changes

Do not rely on `Base.metadata.create_all()` for application schema evolution.

After editing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe schema change"
```

Review the generated migration manually.

Then run migration tests.

## Adding an AI provider

Read:

```text
docs/ADDING_A_PROVIDER.md
```

Keep SDK-specific request/response shapes inside the provider adapter.

Do not import provider SDKs into `RAGService`, `RetrievalService`, or endpoint modules.

## Tests

Automated tests should not spend provider API credits.

Prefer:

- fake SDK-shaped clients for provider adapters
- deterministic fake embedding providers
- fake chat providers
- FastAPI dependency overrides
- temporary/in-memory infrastructure where appropriate

Add a real-network integration test only as an explicitly opt-in test and document the required secret/cost implications.

## Retrieval changes

When retrieval behavior changes, create or update a small golden-query dataset and run:

```bash
python -m evaluation.evaluate_retrieval \
  --base-url http://127.0.0.1:8000 \
  --dataset evaluation/golden_queries.json \
  --top-k 5
```

Record the baseline and changed hit rate/MRR values in the PR description when the claim is that retrieval improved.

## Security

Do not include secrets, confidential documents, or sensitive extracted text in:

- commits
- issues
- pull requests
- screenshots
- logs
- test fixtures

Use private GitHub security reporting for vulnerabilities.

## Pull request content

A good PR explains:

1. what changed
2. why it changed
3. how it was tested
4. RAG/index compatibility impact
5. migration impact
6. security impact, when relevant

Keep one pull request focused on one logical change.
