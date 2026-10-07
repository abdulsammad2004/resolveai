# ResolveAI API Service

FastAPI backend service for ResolveAI multi-tenant AI customer support SaaS.

## Development Setup (Windows PowerShell)

### 1. Start Infrastructure Services
Start PostgreSQL (with pgvector) and Redis using Docker Compose:
```powershell
docker compose -f ../../infra/docker-compose.yml up -d
```

`infra/postgres/init.sql` creates two roles and two databases on first start:

| Role | Used by | Notes |
| --- | --- | --- |
| `resolveai` | Alembic migrations, test setup | Owns the tables. Never used by the running API. |
| `resolveai_app` | The API at runtime | Not a superuser, no `BYPASSRLS`, owns nothing, so row-level security always applies. |

Databases: `resolveai` (dev) and `resolveai_test` (pytest). `init.sql` only runs on an empty
volume. If you created the volume before these roles existed, recreate it (this deletes local data):
```powershell
docker compose -f ../../infra/docker-compose.yml down -v
docker compose -f ../../infra/docker-compose.yml up -d
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -e ".[dev]"
```

### 4. Configure Environment
```powershell
Copy-Item .env.example .env
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `resolveai_app@.../resolveai` | API runtime connection (RLS-enforced role) |
| `MIGRATIONS_DATABASE_URL` | `resolveai@.../resolveai` | Owner connection used only by Alembic |
| `TEST_DATABASE_URL` | `resolveai_app@.../resolveai_test` | Runtime connection used by pytest |
| `TEST_MIGRATIONS_DATABASE_URL` | `resolveai@.../resolveai_test` | Owner connection pytest uses to migrate/truncate |
| `JWT_SECRET` | dev-only placeholder | HMAC key for access tokens. **Required in production**; startup fails without it |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | Refresh token (httpOnly cookie) lifetime |
| `REFRESH_COOKIE_SECURE` | `false` | Sets `Secure` on the refresh cookie. Must be `true` in production |
| `REDIS_URL` | `redis://localhost:6379/0` | Job queue (arq) used by the API and worker |
| `EMBEDDING_PROVIDER` | `openai` | `openai`, or `fake` for deterministic offline vectors (dev/tests) |
| `OPENAI_API_KEY` | empty | Required only when `EMBEDDING_PROVIDER=openai`; the worker refuses to start without it |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIM` | `1536` | Must match the `vector(1536)` column; changing it needs a migration |
| `STORAGE_BACKEND` | `local` | Where uploaded files are stored (`local` only for now) |
| `LOCAL_STORAGE_DIR` | `./storage` | Upload directory for the local backend (gitignored) |
| `MAX_UPLOAD_MB` | `20` | Upload size limit; larger files get `413` |

### 5. Run Database Migrations
```powershell
# Create a new migration revision:
alembic revision --autogenerate -m "initial migration"

# Apply migrations to head (runs as MIGRATIONS_DATABASE_URL):
alembic upgrade head

# Target another database explicitly:
alembic -x db_url=postgresql+asyncpg://resolveai:resolveai@localhost:5432/resolveai_test upgrade head
```

### 6. Run the Development Server
```powershell
uvicorn app.main:app --reload --port 8000
```

### 7. Run the Background Worker
Document ingestion (parse, chunk, embed, store) runs in an [arq](https://arq-docs.helpmanual.io/)
worker, built from the same codebase. In a second terminal, from `services/api`:
```powershell
.\.venv\Scripts\Activate.ps1
arq app.workers.main.WorkerSettings
```
Add `--watch app` to restart it on code changes. Run it from `services/api` so it picks up
`.env` and shares `LOCAL_STORAGE_DIR` with the API. Uploads made while the worker is down stay
`uploaded` and are processed once it starts.

### 8. Run Linting and Tests
```powershell
# Check code style with Ruff:
ruff check .

# Run test suite (needs Postgres running; migrates resolveai_test automatically).
# Tests use the fake embedder and a fake job queue: no OpenAI key or Redis needed.
pytest
```

