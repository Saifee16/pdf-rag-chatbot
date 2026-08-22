# Architecture

## System purpose

PDF RAG Chatbot is a reusable Retrieval-Augmented Generation service. It keeps document ingestion and online question answering as separate execution paths so slow PDF extraction and embedding work does not block chat requests.

## High-level topology

```text
                         ┌──────────────────────────┐
                         │       API client         │
                         └────────────┬─────────────┘
                                      │ HTTP
                         ┌────────────▼─────────────┐
                         │       FastAPI API        │
                         │ auth / validation / IDs  │
                         └──────┬───────────┬───────┘
                                │           │
                       metadata │           │ task dispatch
                                │           │
                     ┌──────────▼───┐   ┌───▼─────────────┐
                     │ PostgreSQL   │   │ Redis / Celery  │
                     │ documents    │   │ ingestion queue │
                     │ chunks       │   └───┬─────────────┘
                     │ conversations│       │
                     │ traces       │   ┌───▼─────────────┐
                     └──────────────┘   │ Celery worker   │
                                            │
                          ┌─────────────────┼─────────────────┐
                          │                 │                 │
                    ┌─────▼─────┐     ┌─────▼──────┐   ┌────▼─────┐
                    │ File store│     │ PDF extract│   │ Embedding│
                    │ PDF bytes │     │ PyMuPDF    │   │ provider │
                    └───────────┘     └────────────┘   └────┬─────┘
                                                             │ vectors
                                                        ┌────▼─────┐
                                                        │ Qdrant   │
                                                        │ vectors  │
                                                        └──────────┘
```

## Offline ingestion path

```text
POST /documents
      ↓
stream PDF to LocalStorageService
      ↓
extension + MIME + %PDF- + size checks
      ↓
SHA-256 duplicate check
      ↓
Document(status=pending)
      ↓
Celery task ID returned with HTTP 202
      ↓
worker marks document processing
      ↓
PyMuPDF page extraction
      ↓
page-aware chunking
      ↓
document embeddings in batches
      ↓
Qdrant collection dimension check
      ↓
replace previous document vectors
      ↓
store deterministic chunk metadata
      ↓
Document(status=ready)
```

The API acknowledges the upload before the full indexing pipeline completes. Clients poll `GET /api/v1/documents/{document_id}` until the document is `ready` or `failed`.

## Online retrieval path

```text
query
  ↓
resolve eligible ready documents
  ↓
verify index fingerprint compatibility
  ↓
embed query with RETRIEVAL_QUERY semantics
  ↓
Qdrant cosine search (dense candidates)
  ├── dense mode → top-k + score threshold
  └── hybrid modes → PostgreSQL FTS candidates → reciprocal-rank fusion
                          └── optional deterministic/local reranker
  ↓
evidence-based confidence decision
  ├── accepted → persist trace and return ranked chunks
  └── abstained → persist trace with reason and return no chunks
```

`POST /api/v1/retrieval/search` exposes this path without generation. This is deliberate: retrieval can be debugged and evaluated independently from the LLM.

Requests support `mode=dense`, `mode=hybrid`, or `mode=hybrid_rerank`. The
default is configurable with `RETRIEVAL_MODE` and is `hybrid` for the released
configuration because the synthetic benchmark improves quality. `dense` remains
the explicit compatibility/fallback mode. Hybrid lexical candidates use the same ready,
fingerprint-compatible document filter as dense search. PostgreSQL uses the GIN
expression index from migration `0002`; SQLite uses a deterministic token
overlap fallback for local tests.

The confidence gate combines the strongest dense and lexical evidence, channel
agreement, and the top-score margin. It is enabled by default with
`RETRIEVAL_ABSTENTION_ENABLED=true` and `RETRIEVAL_CONFIDENCE_THRESHOLD=0.50`.
The retrieval and chat responses expose additive `retrieval_confidence`,
`abstained`, and `abstention_reason` metadata. When a query is abstained, chat
returns a grounded insufficient-evidence answer with empty citations and skips
the provider call entirely. Set the enabled flag to `false` for compatibility
experiments; the confidence metadata remains observable.

## Online RAG chat path

```text
question
  ↓
load/create conversation
  ↓
load recent conversation history
  ↓
persist user message
  ↓
RetrievalService.retrieve()
  ↓
confidence gate
  ├── abstained → insufficient-evidence answer, empty citations, no provider call
  └── accepted →
number each retrieved context [1], [2], ...
  ↓
system instruction sent through provider system channel
  ↓
history + untrusted document context + question sent as user prompt
  ↓
provider generates grounded answer
  ↓
parse citation numbers used by answer
  ↓
map valid numbers back to retrieved chunk metadata
  ↓
persist assistant message + citations
  ↓
return answer, citations, provider/model, retrieval trace ID
```

## Data ownership by storage system

### Relational database

The relational database owns application metadata and relationships:

- documents
- chunk metadata/text
- conversations
- messages
- retrieval traces

It does not own vector similarity search.

### Qdrant

Qdrant owns dense vectors and searchable retrieval payloads:

- chunk vector
- chunk ID
- document ID
- filename
- page number
- chunk index
- chunk text
- index fingerprint

The relational database remains the source of truth for document status and index eligibility.

### File storage

The default `LocalStorageService` owns original PDF bytes. The storage boundary is intentionally isolated so an S3-compatible implementation can replace local disk later without rewriting extraction or retrieval logic.

## Provider boundaries

```text
RAGService
   ↓ ChatProvider
   ├── GeminiProvider
   ├── OpenAIProvider
   └── GatewayChatProvider  → optional Project 3 gateway

Ingestion/Retrieval
   ↓ EmbeddingProvider
   ├── GeminiProvider
   └── OpenAIProvider

Retrieval reranking
   ↓ Reranker protocol
   └── DeterministicReranker (offline/local)
```

The RAG service never imports a provider SDK.

`ChatProvider.generate()` receives two separate values:

- `system_instruction`: application policy/trust boundary
- `prompt`: conversation history, retrieved source data, and current question

This separation avoids representing untrusted PDF text as system policy.

## Index fingerprint

An index is only compatible with the settings used to create it. The fingerprint hashes:

```text
embedding provider
embedding model
chunk size
chunk overlap
```

If any of these change, old documents are considered stale for the current retrieval configuration. Selected stale documents return `INDEX_CONFIGURATION_MISMATCH`; the client can then call the reindex route.

The fingerprint is a compatibility guard, not a security signature.

## Idempotent ingestion strategy

Chunk IDs are deterministic UUID5 values based on:

```text
document UUID
page number
chunk index
chunk text SHA-256
```

Before inserting new points, the worker deletes prior vectors for the document. The relational chunk set is also replaced.

Therefore retrying the same ingestion job does not intentionally append duplicate chunks.

## Failure model

### Permanent ingestion failures

Example:

- PDF has no extractable text

The document is marked `failed` and the Celery task does not retry.

### Transient/unknown ingestion failures

The Celery task retries with exponential countdown and eventually marks the document `failed` after the retry limit.

### Provider failures

Direct Gemini/OpenAI adapters normalize unexpected SDK errors to HTTP 502 application errors. The optional Project 3 gateway can be used when multi-provider fallback/retry policy is required.

## API security boundary

Public:

- `GET /api/v1/health`
- `GET /api/v1/ready`

Protected when `API_AUTH_ENABLED=true`:

- index info
- document routes
- retrieval
- chat
- conversations

The baseline uses static API keys with constant-time comparison. It is a service-to-service starter control, not an end-user identity system.

## Deployment topology

Docker Compose runs:

```text
api
worker
db       PostgreSQL
redis    Celery broker/backend
qdrant   vector database
```

Named volumes persist:

- PostgreSQL data
- Redis append-only data
- Qdrant data
- uploaded PDFs

The API container applies Alembic migrations before starting Uvicorn. Both API and worker run as a non-root user inside the image.

## Intentional boundaries for v1

Not included in this baseline:

- OCR for scanned PDFs
- table-specific extraction
- multi-tenancy
- end-user JWT/OAuth
- object-storage adapter
- distributed tracing
- streaming generation
- automatic embedding-model migration

These are explicit extensions, not hidden TODOs required for the core v1 to function.
