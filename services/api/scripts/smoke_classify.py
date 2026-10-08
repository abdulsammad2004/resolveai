r"""Classify five sample messages with the real Cloudflare Clef-flash client.

Checks your CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN setup. Run from services/api:

    .\.venv\Scripts\python scripts\smoke_classify.py

Nothing is written to the database. Each call costs a few hundred input tokens
(CLEF_FLASH_PRICE_PER_MTOK per million).
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.decisions import CloudflareClefClient, DecisionError
from app.core.config import get_settings

SAMPLES = [
    "Hello!",
    "How long does standard shipping take?",
    "Where is my order RA-10421? It was supposed to arrive yesterday.",
    "I was charged twice for the same order, please refund one of them.",
    "Hi, my account was hacked and money was taken",
]


async def main() -> int:
    settings = get_settings()
    token = settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else ""
    if not settings.cloudflare_account_id or not token:
        print("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in services/api/.env first.")
        return 1

    client = CloudflareClefClient(settings.cloudflare_account_id, token, meter=False)
    print(f"Clef-flash smoke test ({len(SAMPLES)} messages)\n")
    failures = 0
    for text in SAMPLES:
        started = time.perf_counter()
        try:
            c = await client.classify(text, [], workspace_id=uuid.uuid4())
        except DecisionError as exc:
            failures += 1
            cause = exc.__cause__ or exc
            print(f"FAILED  {text!r}\n        {type(cause).__name__}: {cause}\n")
            continue
        ms = (time.perf_counter() - started) * 1000
        top = sorted(c.intent_probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        print(
            f"{text!r}\n"
            f"  intent={c.intent} (confidence {c.confidence:.2f})  "
            f"priority={c.priority}  needs_human={c.needs_human_prob:.2f}\n"
            f"  top intents: {', '.join(f'{k} {v:.2f}' for k, v in top)}\n"
            f"  {c.tokens} input tokens, {ms:.0f} ms\n"
        )
    print("All calls succeeded." if not failures else f"{failures} call(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
