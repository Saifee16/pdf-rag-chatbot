# PDF RAG Chatbot

[![CI](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/ci.yml/badge.svg)](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/codeql.yml/badge.svg)](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/codeql.yml)
[![Security](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/security.yml/badge.svg)](https://github.com/Saifee16/pdf-rag-chatbot/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A reusable, infrastructure-complete **PDF Retrieval-Augmented Generation API** built with FastAPI, Celery, Redis, Qdrant, SQLAlchemy/Alembic, PyMuPDF, and pluggable AI providers.

Upload PDFs, index them asynchronously, inspect retrieval, ask grounded questions, receive page-aware citations, preserve conversations, and deploy the complete stack with Docker Compose.

> This repository is designed as a reusable RAG backend and learning reference. It intentionally keeps extraction, chunking, retrieval, prompt assembly, and citation mapping visible instead of hiding the core pipeline behind a RAG framework.

## Why this repository exists

A toy PDF chatbot usually does this:

```text
upload file
↓
extract text
↓
put all text in prompt
↓
ask LLM
```

That approach breaks when documents grow, ingestion becomes slow, multiple documents are involved, prompts exceed context limits, embeddings change, or a deployment needs observability and persistence.

This project models RAG as an actual system:

```text
OFFLINE INGESTION
PDF → secure-ish upload validation → storage → queue → extraction
    → page-aware chunks → embeddings → Qdrant → ready document

ONLINE QUESTION ANSWERING
question → query embedding → filtered dense retrieval → ranked chunks
         → confidence gate → grounded prompt → LLM → citation validation → persisted answer
```

## Features

### RAG pipeline

- asynchronous PDF ingestion
- page-aware PyMuPDF text extraction
- local Tesseract OCR fallback for scanned/image-only pages
- deterministic native/scanned/mixed page classification with OCR page and time limits
- custom chunking with configurable overlap
- batched document embeddings
- query/document embedding semantics
- dense vector retrieval through Qdrant
- configurable top-k and score threshold
- evidence-based retrieval confidence with configurable abstention
- grounded insufficient-evidence response without an LLM call when confidence is low
- document-scoped retrieval filters
- retrieval traces
- page-aware citations
- conversation history
- retrieval-only debug endpoint
- index compatibility fingerprint
- explicit reindex workflow

### Provider support

- Gemini chat
- Gemini embeddings
- OpenAI chat
- OpenAI embeddings
- optional Project 3 LLM API Gateway for chat routing/fallback
- provider contracts isolated from RAG services
- provider-level system instruction separation

### Storage and infrastructure

- PostgreSQL-ready SQLAlchemy metadata layer
- SQLite local metadata mode
- Alembic schema migrations
- Qdrant vector database
- Redis
- Celery background worker
- local PDF storage adapter
- OCR runs locally in the worker; PDF pixels and OCR output never leave the deployment
- Docker image running as non-root
- Docker Compose topology
- named persistent volumes

### Security baseline

- optional `X-API-Key` authentication
- constant-time API-key comparison
- upload size limit
- extension validation
- MIME validation
- `%PDF-` magic signature validation
- UUID-generated storage filenames
- SHA-256 duplicate detection
- document text treated as untrusted prompt data
- system policy kept separate from document/user prompt
- validated citation references
- request IDs
- security response headers
- `.env` excluded from Git and Docker build context
- CodeQL
- Gitleaks full-history secret scanning
- Trivy filesystem vulnerability/misconfiguration scanning
- Trivy built-container vulnerability scanning
- SARIF uploads to GitHub code scanning
- production fail-closed configuration guardrails
- `pip-audit` CI job
- Dependabot

### Developer experience

- typed FastAPI response models
- Swagger/OpenAPI docs
- 80% CI coverage floor
- Ruff linting and formatting
- migration smoke tests
- Compose configuration validation
- Docker build CI
- GHCR publishing on semantic-version tags
- automatic GitHub release creation
- issue and PR templates
- architecture documentation
- threat model
- provider extension guide
- retrieval evaluation guide
- detailed `NOTES.md`

---

## Architecture

```text
                               CLIENT
                                  │
                                  ▼
                         ┌──────────────────┐
                         │   FastAPI API    │
                         │ auth / schemas   │
                         │ request context  │
                         └───────┬──────────┘
                                 │
                  ┌──────────────┴───────────────┐
                  │                              │
            document upload                  chat/query
                  │                              │
                  ▼                              ▼
          LocalStorageService             RetrievalService
                  │                              │
                  ▼                              ├── query embedding
          PostgreSQL metadata                    │
                  │                              ▼
                  ▼                         Qdrant search
             Redis queue                         │
                  │                              ▼
                  ▼                         ranked chunks
            Celery worker                        │
                  │                              ▼
       ┌──────────┼──────────┐               RAGService
       │          │          │                    │
       ▼          ▼          ▼                    ├── conversation history
   PyMuPDF   TextChunker  Embeddings               ├── system instruction
       │          │          │                    ├── document contexts
       └──────────┴──────────┘                    └── current question
                  │                                   │
                  ▼                                   ▼
                Qdrant                       ChatProvider adapter
                                                      │
                                      ┌───────────────┼───────────────┐
                                      ▼               ▼               ▼
                                   Gemini          OpenAI       Project 3 Gateway
```

Read the complete architecture description in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Project structure

```text
pdf-rag-chatbot/
│
├── app/
│   ├── __init__.py
│   ├── dependencies.py
│   ├── main.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── chat.py
│   │           ├── conversations.py
│   │           ├── documents.py
│   │           ├── health.py
│   │           ├── index.py
│   │           └── retrieval.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   ├── middleware.py
│   │   └── security.py
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── database.py
│   │   └── models.py
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── gateway.py
│   │   ├── gemini.py
│   │   ├── openai.py
│   │   └── registry.py
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── conversation_repository.py
│   │   ├── document_repository.py
│   │   └── retrieval_repository.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── chat.py
│   │   ├── common.py
│   │   ├── document.py
│   │   ├── health.py
│   │   ├── index.py
│   │   └── retrieval.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chunking_service.py
│   │   ├── conversation_service.py
│   │   ├── index_config.py
│   │   ├── ingestion_service.py
│   │   ├── pdf_service.py
│   │   ├── rag_service.py
│   │   ├── retrieval_service.py
│   │   ├── storage_service.py
│   │   ├── task_dispatcher.py
│   │   └── vector_store.py
│   │
│   └── tasks/
│       ├── __init__.py
│       ├── celery_app.py
│       └── document_tasks.py
│
├── alembic/
│   ├── versions/
│   │   └── 0001_initial.py
│   ├── env.py
│   └── script.py.mako
│
├── data/
│   └── uploads/
│       └── .gitkeep
│
├── docs/
│   ├── ADDING_A_PROVIDER.md
│   ├── ARCHITECTURE.md
│   ├── EVALUATION.md
│   ├── SECURITY_CHECKS.md
│   └── THREAT_MODEL.md
│
├── evaluation/
│   ├── __init__.py
│   ├── evaluate_retrieval.py
│   └── golden_queries.example.json
│
├── prompts/
│   └── rag_system.txt
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fakes.py
│   └── test_*.py
│
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── codeql.yml
│   │   ├── publish-ghcr.yml
│   │   ├── release.yml
│   │   └── security.yml
│   ├── dependabot.yml
│   └── PULL_REQUEST_TEMPLATE.md
│
├── .dockerignore
├── .editorconfig
├── .env.example
├── .gitignore
├── .python-version
├── alembic.ini
├── compose.yaml
├── CONTRIBUTING.md
├── docker-entrypoint.sh
├── Dockerfile
├── LICENSE
├── NOTES.md
├── pyproject.toml
├── README.md
├── requirements-dev.txt
├── requirements.txt
└── SECURITY.md
```

---

## API routes

| Method | Route | Purpose | Auth when enabled |
|---|---|---|---|
| `GET` | `/api/v1/health` | Process liveness | Public |
| `GET` | `/api/v1/ready` | DB/Redis/Qdrant/provider readiness | Public |
| `GET` | `/api/v1/index/info` | Current index configuration/fingerprint | Required |
| `POST` | `/api/v1/documents` | Upload and queue a PDF | Required |
| `GET` | `/api/v1/documents` | List documents | Required |
| `GET` | `/api/v1/documents/{document_id}` | Read document/index status | Required |
| `POST` | `/api/v1/documents/{document_id}/reindex` | Queue reindexing | Required |
| `DELETE` | `/api/v1/documents/{document_id}` | Delete vectors, file, metadata | Required |
| `POST` | `/api/v1/retrieval/search` | Inspect dense retrieval directly | Required |
| `POST` | `/api/v1/chat` | Ask a grounded RAG question | Required |
| `GET` | `/api/v1/conversations` | List conversations | Required |
| `GET` | `/api/v1/conversations/{conversation_id}` | Read conversation messages | Required |
| `DELETE` | `/api/v1/conversations/{conversation_id}` | Delete a conversation | Required |

---

## Quick start: complete stack with Docker Compose

### 1. Clone

```bash
git clone https://github.com/Saifee16/pdf-rag-chatbot.git
cd pdf-rag-chatbot
```

### 2. Create environment file

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

### 3. Configure one provider

The simplest default is Gemini:

```env
CHAT_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
CHAT_MODEL=gemini-3.5-flash
EMBEDDING_MODEL=gemini-embedding-001
GEMINI_API_KEY=your_real_key
```

Or direct OpenAI:

```env
CHAT_PROVIDER=openai
EMBEDDING_PROVIDER=openai
CHAT_MODEL=your_supported_openai_chat_model
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=your_real_key
```

Or use Project 3 Gateway for chat while keeping direct embeddings:

```env
CHAT_PROVIDER=gateway
EMBEDDING_PROVIDER=gemini

GATEWAY_URL=http://host.docker.internal:8001
GATEWAY_API_KEY=your_gateway_key
GATEWAY_MODEL_ALIAS=fast

GEMINI_API_KEY=your_real_key
EMBEDDING_MODEL=gemini-embedding-001
```

The Project 3 gateway integration is optional. This repository remains a standalone RAG service.

### 4. Start infrastructure and application

```bash
docker compose up --build
```

Services:

```text
api      http://127.0.0.1:8000
worker   background PDF ingestion
Postgres internal Compose network
a Redis broker/backend
Qdrant vector database
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

### 5. Verify readiness

```bash
curl http://127.0.0.1:8000/api/v1/ready
```

A healthy stack returns `ready: true` with component status for:

- database
- Redis
- Qdrant
- chat provider configuration
- embedding provider configuration

---

## First RAG workflow

### 1. Upload a PDF

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/documents \
  -F "file=@./example.pdf"
```

Example accepted response:

```json
{
  "success": true,
  "request_id": "...",
  "data": {
    "document": {
      "id": "0a87789b-9ad2-4a42-a084-f900bd657f31",
      "original_filename": "example.pdf",
      "status": "pending",
      "page_count": 0,
      "chunk_count": 0
    },
    "task_id": "..."
  }
}
```

The route returns HTTP `202 Accepted`. Ingestion continues in the Celery worker.

### 2. Poll the document

```bash
curl \
  http://127.0.0.1:8000/api/v1/documents/0a87789b-9ad2-4a42-a084-f900bd657f31
```

Status lifecycle:

```text
pending
   ↓
processing
   ↓
ready
```

Failure:

```text
pending/processing
   ↓
failed
```

When ready, the document includes page count, chunk count, embedding provider/model, and index fingerprint.

### 3. Inspect retrieval before chat

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/retrieval/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the incident response time?",
    "document_ids": ["0a87789b-9ad2-4a42-a084-f900bd657f31"],
    "top_k": 5,
    "score_threshold": 0.35
  }'
```

The response shows ranked chunks, pages, text, and similarity scores.

Retrieval accepts an explicit `mode`: `dense` (compatibility/fallback mode),
`hybrid` (dense plus PostgreSQL full-text candidates fused with reciprocal rank
fusion), or `hybrid_rerank` (hybrid followed by the provider-abstracted,
deterministic local reranker). The released default is `hybrid` based on the
synthetic benchmark; set `RETRIEVAL_MODE` or pass `mode` per request.
All modes retain ready-document, index-fingerprint, document-ID filtering,
trace, and citation boundaries.

### 4. Ask the RAG assistant

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the incident response time?",
    "document_ids": ["0a87789b-9ad2-4a42-a084-f900bd657f31"]
  }'
```

Response shape:

```json
{
  "success": true,
  "request_id": "...",
  "data": {
    "conversation_id": "...",
    "message_id": "...",
    "answer": "The policy states ... [1]",
    "citations": [
      {
        "citation_number": 1,
        "chunk_id": "...",
        "document_id": "...",
        "filename": "example.pdf",
        "page_number": 4,
        "score": 0.812345,
        "excerpt": "..."
      }
    ],
    "retrieval_trace_id": "...",
    "provider": "gemini",
    "model": "gemini-3.5-flash",
    "retrieved_chunk_count": 5
  }
}
```

### 5. Continue the conversation

Send the returned `conversation_id`:

```json
{
  "question": "Summarize that in one sentence.",
  "conversation_id": "previous-conversation-id",
  "document_ids": ["document-id"]
}
```

Conversation history helps clarify intent. It is not treated as source evidence for factual document claims.

---

## API authentication

Authentication is disabled by default for local learning:

```env
API_AUTH_ENABLED=false
```

For a remotely reachable deployment, enable the baseline service API-key control:

```env
API_AUTH_ENABLED=true
API_KEYS=replace-with-a-long-random-key,optional-rotating-key
```

Protected requests require:

```http
X-API-Key: replace-with-a-long-random-key
```

Example:

```bash
curl \
  -H "X-API-Key: ${API_KEY}" \
  http://127.0.0.1:8000/api/v1/documents
```

This is a simple service-to-service access control. It is **not** a user/organization identity system.

Read [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) before exposing the service to untrusted clients.

---

## PDF upload controls

The local storage service validates:

```text
.pdf extension
allowed PDF MIME type
configured maximum bytes
configured maximum page count
%PDF- file signature
SHA-256 duplicate document hash
```

The server stores the file under a UUID-derived name rather than the user-controlled filename.

Default maximum:

```env
MAX_PDF_SIZE_MB=25
MAX_PDF_PAGES=5000
```

The original filename remains metadata for citations and UI display.

### Scanned PDFs

The baseline uses text extraction, not OCR.

A scanned/image-only PDF with no extractable text is marked failed with a message explaining that an OCR extension is required.

OCR is an intentional v2 extension point.

---

## Chunking

Default:

```env
CHUNK_SIZE=1200
CHUNK_OVERLAP=200
```

The custom chunker:

- normalizes whitespace
- preserves page boundaries
- never merges text across pages
- prefers paragraph or sentence-like boundaries after 60% of the target chunk size
- falls back to a hard character boundary
- carries overlap forward
- guarantees forward progress

Page-aware chunking makes citation metadata straightforward:

```text
chunk
├── document_id
├── page_number
├── chunk_index
└── text
```

Changing chunk size or overlap changes the index fingerprint and requires reindexing existing documents.

---

## Embeddings

The default Gemini embedding adapter uses separate retrieval semantics for:

```text
documents → RETRIEVAL_DOCUMENT
query     → RETRIEVAL_QUERY
```

The OpenAI adapter exposes the same internal `EmbeddingProvider` contract through OpenAI's embeddings API.

The rest of the application sees only:

```python
embed_documents(texts) -> list[list[float]]
embed_query(text) -> list[float]
```

It does not understand provider SDK response objects.

---

## Vector retrieval

Qdrant stores one dense vector per chunk.

Payload contains:

```text
chunk_id
document_id
filename
page_number
chunk_index
text
index_fingerprint
```

Retrieval:

```text
question
↓
query embedding
↓
optional document ID filter
↓
cosine similarity search
↓
score threshold
↓
top-k
```

Defaults:

```env
RETRIEVAL_TOP_K=5
RETRIEVAL_SCORE_THRESHOLD=0.35
```

These values are starting points. Evaluate them on your own documents and questions.

---

## Index fingerprint and reindexing

Current fingerprint inputs:

```text
EMBEDDING_PROVIDER
EMBEDDING_MODEL
CHUNK_SIZE
CHUNK_OVERLAP
```

View current index configuration:

```http
GET /api/v1/index/info
```

If you change the embedding model or chunking configuration:

```text
old document fingerprint
        ≠
current configuration fingerprint
```

Default retrieval excludes stale documents.

Explicitly selecting a stale document returns:

```text
409 INDEX_CONFIGURATION_MISMATCH
```

Reindex:

```http
POST /api/v1/documents/{document_id}/reindex
```

This prevents silent mixing of incompatible embedding/chunk configurations.

---

## Grounding and prompt-injection boundary

The policy lives in:

```text
prompts/rag_system.txt
```

The RAG service passes it separately as provider-level policy:

```text
Gemini       system_instruction
OpenAI       instructions
Gateway      role=system
```

The normal prompt contains:

```text
conversation history
retrieved document contexts
current question
```

Retrieved chunks are wrapped like:

```xml
<document_context citation="1" document="policy.pdf" page="4">
  ...untrusted PDF text...
</document_context>
```

The system prompt explicitly treats document text as untrusted source data and says never to obey instructions found inside it.

This is a trust-boundary improvement, not a claim that prompt injection is perfectly solved.

---

## Citations

The model is instructed to cite numbered retrieved contexts:

```text
[1]
[2]
[1][3]
```

The application parses citation numbers from the generated answer.

Then it validates each number against the actual retrieval list:

```text
model says [99]
retrieval only has 5 hits
↓
[99] citation metadata is discarded
```

Valid citations are mapped back to:

- chunk ID
- document ID
- filename
- page number
- retrieval score
- excerpt

The application validates citation references; it does not prove that every generated sentence is logically entailed by the cited source.

---

## Conversation persistence

The relational database stores:

```text
Conversation
    ↓ one-to-many
Message
```

Messages contain:

```text
role
content
citations_json
created_at
```

The service sends only a configurable number of recent messages to the RAG prompt:

```env
CONVERSATION_HISTORY_MESSAGES=6
```

The full persisted conversation can still contain more messages.

---

## Retrieval traces

Every retrieval stores:

```text
query
top_k
selected document IDs
ranked result metadata
latency_ms
optional conversation_id
timestamp
```

The chat response returns:

```text
retrieval_trace_id
```

This gives a debugging link between:

```text
user question
↓
retrieved chunk set
↓
generated answer
```

---

## Database migrations

The project uses Alembic.

Apply all migrations:

```bash
alembic upgrade head
```

Downgrade the latest migration:

```bash
alembic downgrade -1
```

Create a revision after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe schema change"
```

Review generated migrations before applying them.

The Docker API entrypoint runs:

```text
alembic upgrade head
↓
uvicorn
```

The worker does not run migrations independently.

---

## Local development without Compose

Docker Compose is the recommended first run because the application requires Redis and Qdrant for the complete architecture.

For direct Python development:

### 1. Virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install

```bash
pip install -r requirements-dev.txt
```

### 3. Environment

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Set a real AI provider key.

### 4. Start Redis and Qdrant

Example with Docker:

```bash
docker run --rm -p 6379:6379 redis:8.8-alpine
docker run --rm -p 6333:6333 qdrant/qdrant:v1.18.2
```

### 5. Apply migration

```bash
alembic upgrade head
```

### 6. Start API

```bash
uvicorn app.main:app --reload
```

### 7. Start worker

In another terminal:

```bash
celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO
```

On Windows, Celery worker behavior can differ by execution pool. Docker Compose provides the most consistent project environment.

---

## Tests

Run:

```bash
pytest
```

CI-equivalent coverage command:

```bash
pytest \
  --cov=app \
  --cov=evaluation \
  --cov-report=term-missing \
  --cov-fail-under=80
```

The tests use:

- temporary SQLite sessions
- FastAPI dependency overrides
- async HTTPX API client
- real PyMuPDF-generated in-memory PDFs
- fake deterministic chat/embedding providers
- fake vector store for service tests
- real in-memory Qdrant client for vector-store adapter tests
- fake Celery task dispatcher

No paid AI provider call is required by the automated test suite.

---

## Code quality

Lint:

```bash
ruff check .
```

Apply safe fixes:

```bash
ruff check . --fix
```

Format:

```bash
ruff format .
```

Verify formatting:

```bash
ruff format --check .
```

Dependency audit:

```bash
pip-audit -r requirements.txt
```

---

## Retrieval evaluation

The project includes a retrieval evaluation CLI and a provider-free synthetic
regression benchmark.

Create a golden query file from:

```text
evaluation/golden_queries.example.json
```

Run:

```bash
python -m evaluation.evaluate_retrieval \
  --base-url http://127.0.0.1:8000 \
  --dataset evaluation/golden_queries.json \
  --top-k 5
```

Metrics:

```text
hit rate@k
MRR@k
```

For a provider-free comparison of all modes on a safe synthetic fixture:

```bash
python -m evaluation.run_retrieval_benchmark --iterations 50
```

The benchmark uses the 46-query V2 fixture and reports Recall@K, Precision@K,
HitRate@K, MRR, nDCG@K, no-answer false positives, category breakdowns, and
p50/p95 latency for dense, hybrid, and opt-in hybrid-rerank modes. Run the
quality regression gate with:

```bash
python -m evaluation.run_retrieval_benchmark \
  --baseline evaluation/results/retrieval_benchmark_v2.json \
  --check-regression
```

See
[`docs/EVALUATION.md`](docs/EVALUATION.md) for interpretation and the checked-in
synthetic fixture and baseline.

For the deterministic, provider-free OCR subset (native, image-only, mixed, blank,
malformed, and OCR-page-limit fixtures), run:

```bash
python -m evaluation.run_ocr_benchmark
```

The benchmark uses safe synthetic PDFs generated at runtime and reports extraction
success, retrieval Recall@3, citation page accuracy, and observational OCR
ingestion latency. `--real-ocr` exercises the local Tesseract executable installed
by the Docker image and CI; it does not call an external OCR service.

Read [`docs/EVALUATION.md`](docs/EVALUATION.md) before comparing chunking or embedding configurations.

---

## Docker image

Build:

```bash
docker build -t pdf-rag-chatbot .
```

The same image supports two process roles:

API:

```bash
docker run --env-file .env -p 8000:8000 pdf-rag-chatbot api
```

Worker:

```bash
docker run --env-file .env pdf-rag-chatbot worker
```

A standalone container still needs reachable database/Redis/Qdrant endpoints and shared document storage where appropriate. Use Compose for the full local topology.

The image includes the `tesseract-ocr` engine and English language data for local
scanned-PDF processing. OCR temporary images are created under the configured
storage directory, removed after each page, and are not part of the Git or Docker
release context.

---

## Docker Compose

```bash
docker compose up --build
```

Stop:

```bash
docker compose down
```

Delete persistent local volumes too:

```bash
docker compose down -v
```

Be careful: `-v` deletes local PostgreSQL, Redis, Qdrant, and uploaded-document volume data for this Compose project.

---

## CI/CD

### CI

`.github/workflows/ci.yml` runs on pushes and pull requests targeting `main`.

Jobs:

```text
Lint and Format
Tests and Coverage
Migration Smoke Test
Dependency Audit
Validate Compose
Build Docker Image
```

### Code and security scanning

`.github/workflows/codeql.yml` runs CodeQL on:

- push to `main`
- pull requests to `main`
- weekly schedule

`.github/workflows/security.yml` adds three independent jobs:

```text
Gitleaks Secret Scan
Trivy Filesystem Scan
Trivy Container Scan
```

Gitleaks checks the full Git history. Trivy generates SARIF reports for filesystem and built-container scans and blocks fixable `HIGH` or `CRITICAL` findings. Push and scheduled security runs upload SARIF to GitHub code scanning; pull requests still execute the blocking scans but skip SARIF upload. Organization-owned repositories should configure the `GITLEAKS_LICENSE` secret required by the official Gitleaks Action.

Read [`docs/SECURITY_CHECKS.md`](docs/SECURITY_CHECKS.md) for the exact gates and the security claims this project does not make.

### Production fail-closed configuration

Local defaults remain beginner-friendly. When:

```env
APP_ENV=production
```

settings validation refuses to start if:

```text
APP_DEBUG=true
API_AUTH_ENABLED=false
API_KEYS is empty
ALLOWED_HOSTS contains *
```

A minimal production baseline is therefore:

```env
APP_ENV=production
APP_DEBUG=false
API_AUTH_ENABLED=true
API_KEYS=<long-random-service-key>
ALLOWED_HOSTS=rag.example.com
```

This protects against accidentally deploying the local defaults as production. It does not replace TLS, rate limiting, a secret manager, network controls, or tenant authorization.

### Container publishing

Pushing a semantic version tag such as:

```text
v1.0.0
```

triggers `.github/workflows/publish-ghcr.yml`.

The workflow publishes semver container tags to:

```text
ghcr.io/<owner>/<repository>
```

### GitHub releases

The same semantic version tag independently triggers `.github/workflows/release.yml`, which creates a GitHub Release using generated notes.

Release and container publication do not depend on one workflow triggering the other.

---

## Publish your first release

After CI is green on `main`:

```bash
git checkout main
git pull origin main
git tag v1.0.0
git push origin v1.0.0
```

Then verify:

```text
Actions → Publish GHCR Image
Actions → GitHub Release
Packages → container package
Releases → v1.0.0
```

---

## Configuration reference

### Application

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `PDF RAG Chatbot` | API title |
| `APP_ENV` | `local` | Environment label |
| `APP_DEBUG` | `true` | FastAPI debug behavior |
| `API_V1_PREFIX` | `/api/v1` | API prefix |
| `DOCS_ENABLED` | `true` | Swagger/ReDoc/OpenAPI |
| `LOG_LEVEL` | `INFO` | Application logging |

### Infrastructure

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./rag.db` | Metadata DB |
| `POSTGRES_DB` | `pdf_rag` | Compose PostgreSQL database |
| `POSTGRES_USER` | `postgres` | Compose PostgreSQL user |
| `POSTGRES_PASSWORD` | `postgres` | Compose local password; change outside local use |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/backend |
| `QDRANT_URL` | `http://localhost:6333` | Vector DB |
| `QDRANT_API_KEY` | empty | Qdrant authentication |
| `QDRANT_COLLECTION` | `pdf_chunks` | Vector collection |

### Storage/upload

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_DIR` | `./data/uploads` | PDF storage |
| `MAX_PDF_SIZE_MB` | `25` | Upload byte limit |
| `MAX_PDF_PAGES` | `5000` | PDF page-count limit |

### Local OCR

| Variable | Default | Purpose |
|---|---|---|
| `OCR_ENABLED` | `true` | Enable local OCR fallback for pages below the native-text threshold |
| `OCR_MIN_NATIVE_TEXT_CHARS` | `32` | Native text length at or above which OCR is skipped |
| `OCR_MAX_PAGES` | `50` | Maximum scanned pages OCR may process per document |
| `OCR_TIMEOUT_SECONDS` | `30` | Per-page local OCR subprocess timeout |
| `OCR_DOCUMENT_TIMEOUT_SECONDS` | `900` | Total OCR deadline per document |
| `OCR_DPI` | `200` | Rendering resolution for OCR page images |
| `OCR_LANGUAGES` | `eng` | Comma-separated local Tesseract language identifiers |
| `OCR_EXECUTABLE` | `tesseract` | Local Tesseract executable name or path |

### RAG/indexing

| Variable | Default | Purpose |
|---|---|---|
| `CHUNK_SIZE` | `1200` | Target characters/chunk |
| `CHUNK_OVERLAP` | `200` | Carry-over characters |
| `EMBEDDING_BATCH_SIZE` | `32` | Documents per embedding batch |
| `RETRIEVAL_TOP_K` | `5` | Default result count |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.35` | Default minimum similarity |
| `RETRIEVAL_ABSTENTION_ENABLED` | `true` | Return grounded insufficient-evidence responses below the confidence threshold |
| `RETRIEVAL_CONFIDENCE_THRESHOLD` | `0.50` | Evidence confidence threshold for accepting retrieved context |
| `RETRIEVAL_MODE` | `hybrid` | `dense`, `hybrid`, or `hybrid_rerank` |
| `HYBRID_DENSE_CANDIDATES` | `20` | Dense candidate pool before fusion |
| `HYBRID_LEXICAL_CANDIDATES` | `20` | Lexical candidate pool before fusion |
| `RETRIEVAL_RRF_K` | `60` | Reciprocal-rank fusion smoothing constant |
| `RERANKER_PROVIDER` | `deterministic` | `none` or local deterministic reranker |
| `RERANK_CANDIDATES` | `20` | Candidate pool passed to reranking |
| `CONVERSATION_HISTORY_MESSAGES` | `6` | Recent messages in prompt |
| `RAG_SYSTEM_PROMPT_PATH` | `./prompts/rag_system.txt` | Grounding policy |

### AI providers

| Variable | Default | Purpose |
|---|---|---|
| `CHAT_PROVIDER` | `gemini` | `gemini`, `openai`, or `gateway` |
| `EMBEDDING_PROVIDER` | `gemini` | `gemini` or `openai` |
| `CHAT_MODEL` | `gemini-3.5-flash` | Direct provider chat model |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Direct embedding model |
| `GEMINI_API_KEY` | empty | Gemini credential |
| `OPENAI_API_KEY` | empty | OpenAI credential |
| `GATEWAY_URL` | `http://localhost:8001` | Project 3 gateway URL |
| `GATEWAY_API_KEY` | empty | Gateway credential |
| `GATEWAY_MODEL_ALIAS` | `fast` | Gateway routing alias |
| `PROVIDER_TIMEOUT_SECONDS` | `60` | Direct/gateway client timeout |

### Security

| Variable | Default | Purpose |
|---|---|---|
| `API_AUTH_ENABLED` | `false` | Enable `X-API-Key` auth |
| `API_KEYS` | empty | Comma-separated accepted keys |
| `CORS_ORIGINS` | empty | Comma-separated allowed origins |
| `ALLOWED_HOSTS` | `*` | Trusted Host middleware; wildcard rejected in production |

### Worker testing

| Variable | Default | Purpose |
|---|---|---|
| `CELERY_TASK_ALWAYS_EAGER` | `false` | Execute Celery tasks eagerly |

---

## Reusing this repository

### Build an internal policy assistant

Keep the architecture and change:

- app name
- system prompt
- upload authorization
- document source
- evaluation dataset

### Build a research-paper assistant

Consider adding:

- metadata fields for authors/year
- citation formatting

### Build a legal-document assistant

Do not just change the prompt. Add domain-specific evaluation, stronger access control, retention controls, audit requirements, and qualified human review.

### Replace local storage with S3

Implement another storage service matching the operations used by document routes and ingestion:

```text
save PDF
delete object
provide an extraction-readable location/stream
```

Then bind it through dependency injection.

### Add another AI provider

Read [`docs/ADDING_A_PROVIDER.md`](docs/ADDING_A_PROVIDER.md).

---

## Important limitations

This v1 intentionally does not include:

- layout-aware table extraction
- multi-tenancy
- end-user accounts
- streaming responses
- distributed tracing
- object storage
- answer-level automated evaluation

OCR for scanned/image-only PDFs is included as the Cycle 4 local/offline extension.
The remaining limitations are documented so users know the baseline's scope.

---

## Learning notes

`NOTES.md` is a project-specific learning manual written for someone who already completed:

1. AI Engineering Starter Kit
2. Lead Scoring ML API
3. LLM API Gateway

It focuses on what is new in Project 4:

- RAG architecture
- offline ingestion vs online inference
- streamed uploads
- file-signature validation
- Celery/Redis
- task retries and idempotence
- PDF page extraction
- chunking and overlap
- deterministic chunk IDs
- embeddings
- vector search
- Qdrant
- index fingerprints
- retrieval traces
- grounded prompt assembly
- prompt-injection boundary
- citations
- retrieval evaluation
- Alembic
- full infrastructure topology

Read [`NOTES.md`](NOTES.md).

---

## Security

Read:

- [`SECURITY.md`](SECURITY.md)
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md)

Never commit `.env`, provider API keys, service API keys, production database credentials, or confidential uploaded documents. Gitleaks scans Git history, Trivy scans the repository and built image, and production settings fail closed on unsafe debug/auth/host defaults. See [`docs/SECURITY_CHECKS.md`](docs/SECURITY_CHECKS.md).

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md).

Pull requests should explicitly state whether a change affects:

```text
extraction
chunking
embeddings
retrieval
prompt policy
citation behavior
index compatibility
```

and whether document reindexing is required.

---

## License

MIT. See [`LICENSE`](LICENSE).
