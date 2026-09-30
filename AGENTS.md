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
