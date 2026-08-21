# Security Policy

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected vulnerability.

Use GitHub's private security advisory flow for this repository.

Include:

- a clear description
- affected endpoint/component
- reproduction steps
- potential impact
- a suggested remediation, when available

Do not include real provider keys, API keys, database passwords, confidential document contents, or access tokens in the report body or screenshots.

## Secrets

Never commit:

- `.env`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `GATEWAY_API_KEY`
- application `API_KEYS`
- database passwords
- Qdrant API keys
- production credentials

If a secret is committed, assume compromise and rotate/revoke it immediately. Deleting the secret from the latest commit does not remove it from existing Git history.

## Automated security gates

The repository configures:

- CodeQL for Python static analysis
- Gitleaks for Git-history secret detection
- Trivy filesystem scanning for dependency and repository/IaC findings
- Trivy container scanning for OS and library vulnerabilities
- `pip-audit` for Python dependency advisory checks
- Dependabot for dependency update proposals

Trivy filesystem and container jobs fail on fixable `HIGH` or `CRITICAL` findings. Push and scheduled runs upload Trivy SARIF reports to GitHub code scanning; pull requests still run the blocking scans but skip SARIF upload. Gitleaks fails the security workflow when a secret leak is detected. Organization-owned repositories must configure the `GITLEAKS_LICENSE` secret required by the official Gitleaks Action; personal-account repositories do not require it.

A workflow existing in the repository is not proof that a specific commit passed it. Verify the actual GitHub Actions and code-scanning results before release. See [`docs/SECURITY_CHECKS.md`](docs/SECURITY_CHECKS.md).

## Production configuration guardrails

When `APP_ENV=production`, settings validation refuses to start with:

- `APP_DEBUG=true`
- `API_AUTH_ENABLED=false`
- an empty `API_KEYS` value
- wildcard `ALLOWED_HOSTS`

These fail-closed checks reduce accidental insecure deployment. They do not replace production identity, rate limiting, TLS, network controls, or a secret manager.

## Deployment warning

`API_AUTH_ENABLED=false` is provided for local learning and trusted development environments.

Do not expose paid-provider-backed chat, embedding, document, or retrieval routes to untrusted networks without an access-control layer.

The built-in `X-API-Key` mechanism is a basic service-to-service baseline. Production systems may require:

- centralized identity
- per-user or per-service credentials
- tenant isolation
- quotas/rate limits
- credential lifecycle management
- audit policy

## Uploaded documents

Uploaded PDF contents and extracted chunk text must be treated as untrusted data.

The baseline implements size, extension, MIME, PDF-signature, storage-name, and duplicate checks. It does not provide malware scanning, OCR sandboxing, content disarm/reconstruction, or regulated-data controls.

## Prompt injection

The application keeps RAG policy separate from retrieved document context and labels document context as untrusted source data. This reduces trust-boundary confusion but does not prove complete resistance to prompt injection.

Do not attach dangerous tools, secrets, or privileged actions to the RAG model without separate authorization and policy enforcement.

## Data privacy and retention

The baseline persists:

- PDF bytes
- extracted chunk text
- document metadata
- conversations
- citations
- retrieval traces

Define production-specific retention, deletion, encryption, backup, and data-residency policies before using confidential or regulated data.

See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for the baseline threat model.

## Supported code

Security fixes target the current `main` branch unless a release-specific policy is announced later.
