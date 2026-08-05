# Security Policy

## Supported Versions

DataClaw is pre-1.0. Security fixes are applied to the latest `main` branch and the latest tagged release when practical.

## Reporting a Vulnerability

**Do not open a public issue for a suspected vulnerability.**

Preferred: open a [private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository.

Fallback (if the repository's security advisory feature is not yet enabled): email **`info@getdataclaw.xyz`**. We will acknowledge within 72 hours.

Include:

- A clear description of the issue.
- Reproduction steps or proof of concept.
- Impacted version or commit SHA.
- Any known mitigation.

We will investigate, propose a fix, and coordinate disclosure. Please give us a reasonable window before public disclosure.

## Security Model

- Connector credentials are encrypted at rest with Fernet using `MASTER_KEY`.
- The IDE SQL execution path is read-only and rejects writes, DDL, comments outside quoted strings, and multiple statements (`backend/app/services/sql_safety.py`).
- OpenAI / connector API credentials are loaded from environment variables and must not be committed.
- Session cookies are HMAC-signed with `SESSION_SECRET` (HttpOnly, SameSite=Lax).
- The default Docker Compose setup is intended for local development and self-hosted evaluation, not multi-tenant public internet exposure without additional hardening (TLS termination, restricted `CORS_ORIGINS`, rotated `MASTER_KEY` / `SESSION_SECRET`).

## Hardening Checklist (production)

- Set `MASTER_KEY` and `SESSION_SECRET` to long random values per environment (32+ bytes).
- Switch `DATABASE_URL` and `DEMO_DATABASE_URL` from SQLite to managed Postgres.
- Set `CORS_ORIGINS` to your frontend's exact origin(s); never use `*`.
- Front the API with TLS.
- Rotate connector credentials regularly; the `encrypted_credentials` column in `connectors` is updated whenever a successful `test()` persists new credentials.
