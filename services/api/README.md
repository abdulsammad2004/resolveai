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
| `LLM_PROVIDER` | `openai` | Chat model client: `openai`, or `fake` for deterministic offline replies (tests) |
| `LLM_CHAT_MODEL` | empty | Chat model name. No default on purpose; calls fail with a clear config error until it is set |
| `EMBEDDING_PRICE_PER_MTOK` | `0.02` | USD per million embedding tokens, for `llm_calls.cost_usd` |
| `LLM_INPUT_PRICE_PER_MTOK` | `0` | USD per million chat input tokens |
| `LLM_OUTPUT_PRICE_PER_MTOK` | `0` | USD per million chat output tokens |
| `RETRIEVAL_TOP_K` | `8` | Nearest chunks fetched per knowledge search |
| `RETRIEVAL_MIN_SCORE` | `0.30` | Cosine similarity below which a chunk is dropped (escalate instead of guessing) |
| `RETRIEVAL_KEEP` | `5` | Chunks returned after the threshold |
| `WIDGET_DEV_ALLOW_LOCALHOST` | `false` | Also allow `http://localhost:3000` as the page embedding the chat widget (local testing). Startup fails if it is `true` in production |
| `WIDGET_TOKEN_TTL_MINUTES` | `60` | Lifetime of a widget token (one conversation, no user) |
| `WIDGET_CONVERSATION_RATE_PER_MINUTE` | `10` | Widget messages per conversation per minute; more get `429` |
| `WIDGET_IP_RATE_PER_MINUTE` | `30` | Widget messages per client IP per minute; more get `429` |
| `WIDGET_DAILY_TOKEN_BUDGET` | `200000` | Chat tokens (input + output) per workspace per UTC day. Above it the widget replies with the fallback message without calling the LLM |
| `DECISION_PROVIDER` | `clef` | Message classifier: `clef` (Cloudflare Clef-flash, falling back to the chat LLM), `llm`, or `fake` (tests) |
| `CLOUDFLARE_ACCOUNT_ID` | empty | Cloudflare account for Workers AI. Empty: classification uses the chat LLM |
| `CLOUDFLARE_API_TOKEN` | empty | API token with Workers AI permission. Never logged |
| `CLEF_FLASH_PRICE_PER_MTOK` | `0.09` | USD per million Clef input tokens (output isn't billed), for `llm_calls.cost_usd` |
| `CLASSIFY_MIN_CONFIDENCE` | `0.6` | Below this intent confidence, a widget message is answered from the knowledge base |
| `NEEDS_HUMAN_THRESHOLD` | `0.7` | At or above this needs-human probability, a widget message becomes a ticket |

Prices are never hardcoded: set them from your provider's current price list. Every model call
(document embedding, query embedding, and later chat) writes one row to `llm_calls` with tokens,
cost, latency and status. Prompt and document text is never stored there.

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
# Tests use the fake embedder, fake chat client, a fake job queue and an in-memory widget
# rate limiter: no OpenAI key or Redis needed.
pytest
```

## Knowledge search

`POST /api/v1/knowledge/search` with `{"query": "..."}` (1 to 500 characters, any workspace
member) embeds the query and runs a cosine search over chunks of `ready` documents in the
caller's workspace, using the HNSW index under row-level security. Results below
`RETRIEVAL_MIN_SCORE` are dropped; an empty `results` list is a normal `200`.

## Customer chat widget

Visitors are not users. A widget session is authenticated by the workspace's
`widget_public_key` plus an origin check, and gets a short-lived widget token
(`type="widget"`, scoped to one conversation). Widget tokens are rejected by every dashboard
endpoint, and user tokens are rejected by every widget endpoint.

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `POST /api/v1/widget/session` | key + origin | Start or resume a conversation; returns the widget token |
| `POST /api/v1/widget/messages` | widget token | Ask a question; the answer streams back as Server-Sent Events |
| `GET /api/v1/widget/conversation` | widget token | Messages of this conversation |
| `POST /api/v1/widget/feedback` | widget token | Thumbs up/down on an assistant answer (latest rating wins) |
| `GET /api/v1/conversations` | user | Inbox: newest activity first, `?status=`, cursor pagination, counts per status |
| `GET /api/v1/conversations/{id}` | user | Transcript with citations and customer feedback |
| `PATCH /api/v1/conversations/{id}` | user | `{"status": "closed"}` (or `open` / `needs_human`) |

**Key lookup under RLS.** The key is resolved before any tenant context exists, through the
`SECURITY DEFINER` function `resolve_widget_key(key)`. It is owned by the migrations role, has a
fixed `search_path`, is executable only by `resolveai_app`, and returns only the workspace id
and allowed origins.

**Origin check.** The widget runs in an iframe served by the web app, so the browser's
`Origin` header is the web app, not the customer's site. `widget.js` gives the iframe the
embedding page's origin via `postMessage` (the browser sets `event.origin`, so the page can't
fake it), and the iframe sends it as `host_origin`. The API requires the `Origin` header to be
either a web app origin (`CORS_ORIGINS`) or the host page itself, and `host_origin` to be in
the workspace's `allowed_origins`. Unknown key → `404`, origin not allowed → `403`.

**Answers.** The customer message is stored, then retrieval runs. With no sources above
`RETRIEVAL_MIN_SCORE`, or with the daily token budget used up, the LLM is not called: the reply
is the fixed fallback, `grounded=false`, and the conversation becomes `needs_human`. Otherwise
the `answer_v1` prompt receives the sources as `<source id="S1">` blocks (untrusted data) plus
the last 6 messages. The stream sends:

- `event: token`, `data: {"text": "..."}`: raw model output, for display while it arrives
- `event: final`, `data: {"id", "content", "citations", "grounded"}`: the stored message.
  Clients must replace the streamed text with this
- `event: error`, `data: {"message": "..."}`: a safe message; resending the same text retries
  without storing the question twice

After streaming, only `[S#]` ids that were actually retrieved are kept. If none remain, the
answer becomes the fallback. Each chat call writes an `llm_calls` row (`purpose=chat`), and the
assistant message links to it through `llm_call_id`.

Rate limits and the budget live in Redis. Rate limits fail open if Redis is unreachable. The
budget fails closed, so the widget answers with the fallback rather than spending blindly. The
client IP is `request.client.host`, which uvicorn resolves from `X-Forwarded-For` only for
trusted proxies (`--forwarded-allow-ips`, default `127.0.0.1`, which covers the local Next.js
proxy).

## Classification and routing

Every widget message is classified before anything else (`app/ai/decisions.py`): intent,
priority and the probability that a person is needed. Only the message and the two messages
before it are sent. The default provider is Cloudflare's **Clef-flash** decision model
(`@cf/cloudflare/clef-flash` over the Workers AI REST API, 5s timeout, one retry), which
returns a probability for every option. If Cloudflare isn't configured or the call fails, the
chat LLM answers the same questions with structured output (prompt `classify_v1`). Every call is
metered in `llm_calls` with `purpose=classify` (`provider=cloudflare` for Clef, input tokens
only), and the classification is stored on the customer message.

Routing (`decide_route` in `app/modules/conversations/chat.py`):

| Classification | Reply | Ticket |
| --- | --- | --- |
| `greeting` / `thanks` (confident, needs-human below threshold, priority not high/urgent) | Short fixed reply, no retrieval, no LLM | No |
| `needs_human_prob >= NEEDS_HUMAN_THRESHOLD`, or a confident `order_status`, `refund_request`, `complaint`, `account_change`, or a greeting with a serious request | "Thanks — I've passed this to our team…" (no action is attempted) | Yes, conversation `needs_human` |
| `knowledge_question`, low confidence, or classification unavailable | Grounded RAG answer | Only if the answer falls back |
| Daily token budget used up | Fallback message, nothing classified | Yes |

A conversation reuses its open ticket (its priority only ever rises); after the ticket is
resolved, the next handoff opens a new one. Ticket subjects are the first 80 characters of the
triggering message.

Check your Cloudflare setup with `python scripts/smoke_classify.py`: it classifies five sample
messages with the real Clef client and prints intent, priority, needs-human and confidence
(nothing is written to the database).

## Tickets

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/tickets` | Urgent first, then newest. Filters `status`, `priority`, `intent`, `assignee` (`me`, `unassigned`, `any`), cursor pagination, plus workspace-wide `counts` |
| `GET /api/v1/tickets/{id}` | Ticket, classification and the conversation transcript |
| `POST /api/v1/tickets` | Manual ticket `{subject, description, contact_email?}`, classified like a widget message |
| `PATCH /api/v1/tickets/{id}` | `status`, `priority`, `assignee_id` (must be a member; `null` unassigns) |

Any member may use them. Changes write nothing else yet; the audit log comes later.

## Mock orders

`POST /api/v1/mock-orders/seed` (owner/admin) inserts 10 sample orders into the current
workspace; it is idempotent (existing order numbers are left alone). `GET /api/v1/mock-orders`
lists them. They stand in for a real order API until order lookup tools arrive.

## Prompts

Prompts live as versioned files in `app/ai/prompts/` (`<name>_<version>.md`) and are loaded
with `load_prompt(name, version)`. Never edit a released version in place: add `answer_v2.md`
and switch callers to it, so `llm_calls.prompt_version` stays meaningful.
