# Retrieval Evaluation

## Why retrieval is evaluated separately

A RAG answer can be wrong because:

1. the correct chunk was not retrieved
2. the correct chunk was retrieved but the model ignored/misread it
3. the source document itself did not contain the answer

If retrieval and generation are tested only as one black box, these failure classes are difficult to separate.

The project exposes:

```http
POST /api/v1/retrieval/search
```

and includes:

```text
evaluation/evaluate_retrieval.py
```

so the retrieval layer can be measured without asking the LLM to generate prose.

## Golden query format

Copy the example file:

```bash
cp evaluation/golden_queries.example.json evaluation/golden_queries.json
```

Example:

```json
[
  {
    "question": "What is the incident response window?",
    "expected_document_ids": [
      "1480a273-bc65-4f8f-b2eb-6c60a29f060a"
    ]
  },
  {
    "question": "Who approves enterprise refunds?",
    "expected_document_ids": [
      "993bb5dc-c17c-4d48-8824-c94c81cdfa2d"
    ]
  }
]
```

The expected unit in v1 is a document ID rather than a chunk ID. This keeps the first evaluation workflow easy to maintain even when chunk boundaries change.

## Run the evaluator

Start the API, make sure the documents are ready, then run:

```bash
python -m evaluation.evaluate_retrieval \
  --base-url http://127.0.0.1:8000 \
  --dataset evaluation/golden_queries.json \
  --top-k 5
```

When API authentication is enabled:

```bash
python -m evaluation.evaluate_retrieval \
  --base-url http://127.0.0.1:8000 \
  --dataset evaluation/golden_queries.json \
  --top-k 5 \
  --api-key "$PDF_RAG_API_KEY"
```

## Hit rate@k

For one query:

```text
1 = at least one expected document appears in top k
0 = no expected document appears in top k
```

Across all queries:

```text
hit rate@k = successful query hits / total queries
```

Example:

```text
8 queries
6 retrieve an expected document in top 5
hit rate@5 = 6 / 8 = 0.75
```

Hit rate answers:

> Does retrieval find a relevant expected document at all?

## Mean Reciprocal Rank (MRR)@k

For each query, find the rank of the first expected document:

```text
rank 1 → reciprocal rank 1.0
rank 2 → reciprocal rank 0.5
rank 4 → reciprocal rank 0.25
not found in top k → 0
```

Then average reciprocal ranks.

MRR answers:

> How early does the first expected result appear?

A system can have high hit rate but weak MRR if relevant documents regularly appear at rank 5 rather than rank 1.

## What to change one variable at a time

Useful experiments:

```text
CHUNK_SIZE
CHUNK_OVERLAP
EMBEDDING_PROVIDER
EMBEDDING_MODEL
RETRIEVAL_TOP_K
RETRIEVAL_SCORE_THRESHOLD
```

When chunk or embedding configuration changes, the index fingerprint changes. Reindex documents before comparing retrieval results.

## Evaluation discipline

Use a table such as:

| Run | Embedding | Chunk | Overlap | top-k | threshold | Hit rate | MRR |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | model-a | 1200 | 200 | 5 | 0.35 | 0.78 | 0.61 |
| smaller chunks | model-a | 700 | 120 | 5 | 0.35 | 0.82 | 0.66 |

Do not change five variables simultaneously and then claim one specific change caused the improvement.

## What v1 does not measure

The included evaluator does not measure:

- answer correctness
- citation entailment
- faithfulness
- hallucination rate
- answer completeness
- human preference

Those belong in a generation/RAG evaluation layer. The v1 evaluator is intentionally retrieval-specific.
