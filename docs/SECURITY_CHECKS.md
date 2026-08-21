# Security Checks and Release Gates

This document separates **implemented controls**, **automated security gates**, and **security claims that this repository does not make**.

## Automated security workflows

The repository has three security workflows/gates in addition to normal tests.

| Check | Workflow/job | What it checks | Blocking policy |
|---|---|---|---|
| CodeQL | `codeql.yml` | Python static code analysis | GitHub code-scanning result |
| Gitleaks | `security.yml / Gitleaks Secret Scan` | Hardcoded secrets in Git history | Fails when Gitleaks detects a leak |
| Trivy filesystem | `security.yml / Trivy Filesystem Scan` | Dependency and repository/IaC misconfiguration findings | Fails on fixable `HIGH`/`CRITICAL` findings |
| Trivy container | `security.yml / Trivy Container Scan` | OS and library vulnerabilities in the built image | Fails on fixable `HIGH`/`CRITICAL` vulnerabilities |
| pip-audit | `ci.yml / Dependency Audit` | Known Python dependency vulnerabilities | Fails when the audit command reports a vulnerable requirement |

Trivy also writes SARIF reports for filesystem and container scans. On push and scheduled runs, the workflow uploads those reports to GitHub code scanning; pull requests still run the blocking Trivy scans but skip the SARIF upload step.

## Production configuration fail-closed guardrails

When:

```env
APP_ENV=production
```

Pydantic settings validation refuses to create the application configuration when any of these conditions is true:

```text
APP_DEBUG=true
API_AUTH_ENABLED=false
API_KEYS is empty
ALLOWED_HOSTS contains *
```

A hardened baseline therefore looks like:

```env
APP_ENV=production
APP_DEBUG=false
API_AUTH_ENABLED=true
API_KEYS=<long-random-service-key>
ALLOWED_HOSTS=rag.example.com
```

This is an **accidental insecure-deployment guardrail**. It is not a replacement for a secret manager, identity platform, rate limiting, TLS, network policy, or tenant authorization.

## What must be green before a release

Before tagging a release, verify GitHub Actions shows success for:

```text
CI
CodeQL
Security / Gitleaks Secret Scan
Security / Trivy Filesystem Scan
Security / Trivy Container Scan
```

For repositories owned by a GitHub organization, the official Gitleaks Action currently requires a `GITLEAKS_LICENSE` repository/organization secret; personal-account repositories do not require that license.

A local test pass does not prove the GitHub-hosted security jobs passed. The repository should only claim a specific scan passed after the corresponding workflow run is green.

## Security claims this project does not make

This baseline is not:

- penetration-tested or security-certified
- a malware scanner for uploaded PDFs
- a PDF parser sandbox
- a Web Application Firewall
- a DDoS/rate-limiting layer
- a multi-tenant authorization system
- an encryption-at-rest implementation
- a complete prompt-injection solution

Read [`THREAT_MODEL.md`](THREAT_MODEL.md) and the root [`SECURITY.md`](../SECURITY.md) before internet-facing deployment.
