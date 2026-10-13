# Eval suite

Runs the real pipeline (classifier, retrieval, grounded answers, widget agent with mock orders,
drafting job) against a dedicated **eval workspace** and scores it. Everything in it is fictional:
the help docs in `fixtures/kb/` (a made-up store, Juniper & Pine Outfitters) and the sample orders
from `app/modules/orders/service.py`. Evals never read your real workspaces or uploads.

## Run

From `services/api`, with Postgres up and `OPENAI_API_KEY`, `LLM_CHAT_MODEL` (and Cloudflare for
`--classifier clef`) in `.env`:

```powershell
.\.venv\Scripts\python scripts\run_evals.py                          # everything
.\.venv\Scripts\python scripts\run_evals.py --limit 3                # 3 cases per category
.\.venv\Scripts\python scripts\run_evals.py --category classification --classify-version v2
.\.venv\Scripts\python scripts\run_evals.py --category classification --benchmark-classifier
.\.venv\Scripts\python scripts\run_evals.py --compare evals\reports\baseline.json
```

| Option | Meaning |
| --- | --- |
| `--category X` | only this category (repeatable) |
| `--limit N` | at most N cases per category |
| `--classifier clef\|llm` | `clef`: Clef with the LLM fallback, as in production; `llm`: the LLM only |
| `--classify-version v2\|v3` | classifier version (default `CLASSIFY_VERSION`) |
| `--benchmark-classifier` | also run the classification cases with Clef alone and the LLM alone: accuracy, latency and cost per 1k messages |
| `--compare report.json` | metric deltas and pass→fail cases against an earlier run; exit 1 on a quality regression |
| `--no-judge` | skip the LLM-as-judge |

Each run writes `reports/<run id>.json` and `.md` (git-ignored, except `.gitkeep` and an optional
`baseline.json` you choose to commit) and prints a summary. A report records the dataset version
(a hash of `cases/` and `fixtures/`, independent of git), the chat, judge and embedding models, the
classifier and its version, and the retrieval settings.

**Cost cap:** `EVAL_MAX_COST_USD` (default 1.00). The runner checks the run's `llm_calls` cost
before every case and stops once it reaches the cap (the report says `stopped_early`).

## Cases (`cases/*.yaml`)

| Category | What is checked |
| --- | --- |
| `classification` | intent, priority (a list of acceptable values) and needs_human, including Roman Urdu and mixed-language messages and messages with earlier turns |
| `knowledge` | recall@k for the expected doc, key-fact coverage and groundedness (LLM judge, prompt `eval_judge_v1`), citation validity |
| `unanswerable` | the widget falls back (offers a teammate, no ticket) instead of answering |
| `agent` | order lookups (right/wrong email, unknown order, missing email); refund/cancel hand off and the drafting job proposes the action, never executes it |
| `safety` | prompt injection, lookups without the right email, other customers' data |
| `small_talk` | greetings and off-topic messages get a short reply, no ticket |

Every pipeline case is also checked for: no action executed, no order changed, and no sample
order's email or tracking number in the reply unless the order is in `orders_in_scope`.

**Holdout:** `classification_holdout.yaml` and `knowledge_holdout.yaml` (about 20% of those
categories) were written separately and are not used while writing prompts. Reports show
`*.holdout.*` metrics separately. Don't read them when tuning a prompt; add new holdout cases the
same way (written by someone who isn't tuning).

## Layout

- `cases.py`: case schema, loading, dataset version
- `scoring.py`: pure scorers (no I/O), unit-tested in `tests/test_eval_scoring.py`
- `harness.py`: eval workspace, fixture ingestion, running cases, metrics, benchmark
- `report.py`: JSON/Markdown reports and run comparison
- `tests/test_eval_smoke.py`: 8 real cases through the harness with fake models (runs in pytest)
