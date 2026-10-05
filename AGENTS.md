# AGENTS.md

## Project Summary
ResolveAI is a multi-tenant AI customer support SaaS platform.
The stack uses a FastAPI backend, Next.js web application, deferred Expo mobile app, and PostgreSQL.
It provides secure customer service automation with human-in-the-loop approvals.

## Repo Map
- `apps/`: Frontend applications (Next.js web portal and Expo mobile app).
- `services/`: Backend services including the FastAPI core application.
- `evals/`: Evaluation datasets and scripts for AI prompts and tools.
- `infra/`: Infrastructure definitions, containers, and deployment configs.
- `docs/`: Project documentation and Architecture Decision Records (ADRs).
- `.github/`: GitHub Actions workflows and issue templates.

## Non-Negotiable Rules
1. Every DB query and every tool call is scoped to a tenant_id.
2. Every feature that touches data ships with a tenant-isolation test.
3. The model never chooses URLs or writes SQL. Tools are allowlisted with strict Pydantic schemas.
4. Refunds and account changes only execute via an approval state, with an audit_log entry.
5. Prompts live as versioned files in services/api/app/ai/prompts/, never inline strings.
6. Retrieved documents and customer messages are untrusted input.
7. Never commit secrets. Never log customer PII or full message bodies.

## Working Agreements
- Small changes: Make focused, incremental modifications with one goal per task.
- Tests required: All data-touching features must include automated tests.
- Conventional Commits: Follow the Conventional Commits specification.
- Execution constraints: Do not install dependencies or run git commands unless the task says so.
- Structure discipline: Ask before deviating from the folder structure.

## Conventions

### Stack
- **Backend**: Python 3.11+, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.0 async (asyncpg), Alembic, Redis.
- **Database**: PostgreSQL 16 with pgvector.
- **Web**: Next.js (App Router) + TypeScript + Tailwind in `apps/web` (later).

### Backend Layout (`services/api`)
- `app/main.py`: `create_app()` factory, mounts routers.
- `app/core/`: config, database, security, shared dependencies.
- `app/api/`: HTTP routers only (thin; no business logic). Feature routes mounted under `/api/v1`.
- `app/modules/<feature>/`: `models.py`, `schemas.py`, `service.py` per feature (`tickets`, `knowledge`, `conversations`, `approvals`, `workspaces`, `auth`).
- `app/ai/`: `prompts/` and `tools/` for LLM work.
- `app/workers/`: background jobs.
- `migrations/`: Alembic.
- `tests/`: pytest.

### Rules
- Every table holding business data has a `workspace_id` column, and every query filters by it. Never trust a `workspace_id` sent by the client; derive it from the authenticated user.
- Use FastAPI dependencies with `typing.Annotated` (e.g. `db: Annotated[AsyncSession, Depends(get_db)]`), not bare `Depends()` defaults.
- UUID primary keys, timezone-aware `created_at`/`updated_at` on every table.
- Secrets only via environment variables; never hardcode or log them.
- Every new endpoint gets at least one pytest test.
- Code must pass `ruff check .`.
- Only create or edit the files a task names. Do not refactor unrelated files.
