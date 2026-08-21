## Summary

Describe what this pull request changes.

## Why

Explain the problem or architecture reason.

## Testing

Describe how the change was tested.

## RAG impact

- Does this change extraction, chunking, embeddings, retrieval, prompts, or citations?
- Does it require document reindexing?

## Checklist

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pytest --cov=app --cov=evaluation --cov-fail-under=80`
- [ ] Migration added for schema changes
- [ ] No secrets or uploaded documents committed
- [ ] Production security guardrails still pass
- [ ] Gitleaks / Trivy findings are fixed or narrowly documented
- [ ] Documentation updated
