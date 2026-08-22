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

For an offline, provider-free comparison of the three retrieval modes, run:

```bash
python -m evaluation.run_retrieval_benchmark --iterations 50
```

The versioned synthetic fixture at `evaluation/fixtures/retrieval_benchmark_v2.json`
contains 46 queries over 12 public chunks: 32 positive cases and 14 negative
or no-answer cases. It deliberately covers exact lexical,
paraphrase, low-keyword semantic, keyword and semantic distractors, multiple
relevant chunks, split answers, repeated terminology, rare entities, numeric/date
queries, negatives, and dense/lexical/hybrid/reranking decision cases. Fixture
integrity checks reject duplicate IDs, missing rankings, unknown references, and
insufficient category coverage.

The evaluator reports Recall@K, Precision@K, HitRate@K, MRR, nDCG@K, no-answer
false-positive rate, per-category results, and p50/p95 latency for `dense`,
`hybrid`, and `hybrid_rerank`. Results are deterministic for quality metrics;
latency is machine-dependent. Save a machine-readable result with `--output`.

CI runs the quality-only and abstention regression gate (latency is observed, not
thresholded):

```bash
python -m evaluation.run_retrieval_benchmark \
  --check-regression
```

### Cycle 3 confidence and abstention evaluation

Calibration is deterministic and separated from the final held-out split: case
IDs whose numeric suffix is divisible by four are held out, and all other cases
are used for calibration. The selected hybrid threshold is `0.50`, chosen only
from calibration candidates with positive false-abstain rate at or below 10%.
The checked-in report is `evaluation/results/retrieval_abstention_v3.json`.

| Split / mode | Recall@3 | MRR | nDCG@3 | Negative FP | Positive false-abstain |
|---|---:|---:|---:|---:|---:|
| Held-out dense | 0.875 | 0.4583 | 0.5625 | 0.0000 | 0.0000 |
| Held-out hybrid | 0.750 | 0.6875 | 0.7039 | 0.0000 | 0.0000 |
| Held-out hybrid + rerank | 0.750 | 0.7500 | 0.7500 | 0.0000 | 0.0000 |

Without the confidence gate, held-out negative FP is `1.0000` for every mode;
the gate therefore removes all fixture false positives without sacrificing a
positive case in this split. The synthetic evidence is not a claim that hybrid
universally beats dense: dense retains higher Recall@3/HitRate@3 in the broader
comparison, while hybrid has substantially better MRR and nDCG@3. Reranking has
no aggregate fixture-quality improvement and remains opt-in because it adds
latency. Negative/no-answer cases still expose a future abstention-calibration
and answer-quality problem shared by all retrieval modes.

The checked-in baseline is synthetic and contains no private documents,
document-derived text, embeddings, or provider data. It is intentionally kept
separate from production retrieval code so fixture-specific shortcuts cannot
improve the score.

The Cycle 1 five-query reference remains documented in the release history.
Cycle 2 uses the broader fixture to make trade-offs visible: hybrid materially
improves MRR and nDCG over dense-only, while reranking adds local CPU latency
without a reliable fixture-quality improvement. Therefore `hybrid` remains the
default and `hybrid_rerank` remains an explicit opt-in mode.

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

## Recall@k

Recall@k is the fraction of expected relevant IDs present in the first k
results. With one relevant chunk it is equivalent to a hit-rate check; with
multiple relevant chunks it rewards retrieving more of the set.

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

## nDCG@k

nDCG discounts relevant results by rank and normalizes against the ideal order.
The evaluator uses binary relevance for the synthetic fixture; a future domain
dataset can provide graded relevance labels.

## What to change one variable at a time

Useful experiments:

```text
CHUNK_SIZE
CHUNK_OVERLAP
EMBEDDING_PROVIDER
EMBEDDING_MODEL
RETRIEVAL_TOP_K
    RETRIEVAL_SCORE_THRESHOLD
    RETRIEVAL_MODE
    HYBRID_DENSE_CANDIDATES
    HYBRID_LEXICAL_CANDIDATES
    RETRIEVAL_RRF_K
    RERANKER_PROVIDER
    RERANK_CANDIDATES
```

When chunk or embedding configuration changes, the index fingerprint changes. Reindex documents before comparing retrieval results.

## Evaluation discipline

Use a table such as:

| Run | Embedding | Chunk | Overlap | top-k | threshold | Hit rate | MRR |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | model-a | 1200 | 200 | 5 | 0.35 | 0.78 | 0.61 |
| smaller chunks | model-a | 700 | 120 | 5 | 0.35 | 0.82 | 0.66 |

Do not change five variables simultaneously and then claim one specific change caused the improvement.

## What the synthetic benchmark does not measure

The included evaluator does not measure:

- answer correctness
- citation entailment
- faithfulness
- hallucination rate
- answer completeness
- human preference

Those belong in a generation/RAG evaluation layer. This evaluator is intentionally
retrieval-specific and should not be presented as a production quality guarantee.
