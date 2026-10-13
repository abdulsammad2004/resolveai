r"""Run the eval suite (evals/) against the real pipeline in the dedicated eval workspace.

Run from services/api:

    .\.venv\Scripts\python scripts\run_evals.py
    .\.venv\Scripts\python scripts\run_evals.py --category classification --classifier llm
    .\.venv\Scripts\python scripts\run_evals.py --limit 3 --compare evals\reports\baseline.json
    .\.venv\Scripts\python scripts\run_evals.py --category classification --benchmark-classifier
    .\.venv\Scripts\python scripts\run_evals.py --classify-version v2   # before/after a prompt

Calls the real providers (chat model, embeddings, Cloudflare Clef) and writes llm_calls rows to
the eval workspace only, whose data is all fictional (evals/fixtures). The run stops before the
next case once its cost reaches EVAL_MAX_COST_USD. Writes evals/reports/<run>.json and .md and
prints a summary. Exit code 1 if --compare finds a quality regression or the cap stopped the run.
Never prints keys or env values.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.decisions import (
    CloudflareClefClient,
    DecisionClient,
    FallbackDecisionClient,
    LLMDecisionClient,
)
from app.ai.embeddings import get_embedding_client
from app.ai.llm import OpenAILLMClient, get_llm_client
from app.core.config import get_settings
from app.core.database import engine
from app.core.storage import get_storage

# Register every model on the shared metadata so foreign keys resolve (as in app.workers.main).
from app.modules.approvals import models as approvals_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.conversations import models as conversations_models  # noqa: F401
from app.modules.tickets import models as tickets_models  # noqa: F401
from app.modules.workspaces import models as workspaces_models  # noqa: F401
from evals.cases import CATEGORIES, REPORTS_DIR, load_cases, select_cases
from evals.harness import CaseResult, Clients, RunMeta, run_eval
from evals.report import (
    benchmark_lines,
    compare,
    comparison_lines,
    load_report,
    summary_rows,
    to_markdown,
    write_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--category", action="append", choices=CATEGORIES, help="only this category (repeatable)"
    )
    parser.add_argument("--limit", type=int, help="at most N cases per category")
    parser.add_argument(
        "--classifier",
        choices=("clef", "llm"),
        default="clef",
        help="clef = Clef with the LLM fallback (as in production); llm = LLM only",
    )
    parser.add_argument(
        "--classify-version",
        choices=("v2", "v3"),
        help="classifier version (default: CLASSIFY_VERSION)",
    )
    parser.add_argument("--compare", type=Path, help="a previous report .json to compare with")
    parser.add_argument(
        "--benchmark-classifier",
        action="store_true",
        help="also run the classification cases with Clef alone and the LLM alone",
    )
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-as-judge")
    parser.add_argument("--label", default="", help="appended to the report file names")
    return parser.parse_args()


def build_clients(args: argparse.Namespace, version: str) -> tuple[Clients, str]:
    settings = get_settings()
    llm = get_llm_client()
    token = (
        settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else ""
    )
    clef_ready = bool(settings.cloudflare_account_id and token)

    def clef() -> CloudflareClefClient:
        return CloudflareClefClient(settings.cloudflare_account_id, token, version=version)

    decider: DecisionClient
    if args.classifier == "clef":
        if not clef_ready:
            raise SystemExit(
                "--classifier clef needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN."
            )
        decider = FallbackDecisionClient(clef(), LLMDecisionClient(llm, version=version))
    else:
        decider = LLMDecisionClient(llm, version=version)

    judge_model = settings.eval_judge_model or settings.llm_chat_model
    judge = None
    if not args.no_judge and settings.llm_provider == "openai" and settings.openai_api_key:
        judge = OpenAILLMClient(
            api_key=settings.openai_api_key.get_secret_value(),
            model=judge_model,
            tools_reasoning_effort=settings.llm_tools_reasoning_effort,
        )
    benchmark: dict[str, DecisionClient | str] = {}
    if args.benchmark_classifier:
        benchmark["clef-flash"] = clef() if clef_ready else "Cloudflare not configured"
        benchmark[f"llm ({settings.llm_chat_model})"] = LLMDecisionClient(llm, version=version)
    return (
        Clients(
            llm=llm,
            embedder=get_embedding_client(),
            decider=decider,
            judge=judge,
            benchmark=benchmark,
        ),
        judge_model if judge is not None else "(none)",
    )


def print_case(result: CaseResult) -> None:
    mark = "PASS" if result.passed else "FAIL"
    holdout = " [holdout]" if result.holdout else ""
    # Holdout details stay in the report only, so they don't leak into prompt writing.
    hidden = result.passed or result.holdout
    detail = "" if hidden else f"  {'; '.join(result.failures)[:160]}"
    print(f"  {mark} {result.id}{holdout} ({result.category}){detail}", flush=True)


async def main() -> int:
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    if settings.llm_provider == "openai" and not settings.llm_chat_model:
        print("Set OPENAI_API_KEY and LLM_CHAT_MODEL in services/api/.env first.")
        return 1
    version = args.classify_version or settings.classify_version
    clients, judge_model = build_clients(args, version)
    cases = select_cases(load_cases(), categories=args.category, limit=args.limit)
    meta = RunMeta(
        classifier=args.classifier,
        classify_version=version,
        chat_model=settings.llm_chat_model or settings.llm_provider,
        judge_model=judge_model,
        embedding_model=settings.embedding_model
        if settings.embedding_provider == "openai"
        else "fake",
        cost_cap_usd=settings.eval_max_cost_usd,
        limit=args.limit,
        categories=args.category,
    )
    print(
        f"Running {len(cases)} cases (classify {version}, classifier {args.classifier}, "
        f"chat {meta.chat_model}, judge {judge_model}, cap ${meta.cost_cap_usd})"
    )
    try:
        report = await run_eval(
            cases,
            clients,
            meta,
            get_storage(),
            benchmark=args.benchmark_classifier,
            on_case=print_case,
        )
    finally:
        await engine.dispose()

    stem = report["meta"]["run_id"] + (f"-{args.label}" if args.label else "")
    comparison = compare(load_report(args.compare), report) if args.compare else None
    json_path, md_path = write_report(report, REPORTS_DIR, stem)
    if comparison is not None:
        md_path.write_text(to_markdown(report, comparison), encoding="utf-8")

    print("\nSummary")
    width = max(len(k) for k, _ in summary_rows(report)) if report["metrics"] else 10
    for key, value in summary_rows(report):
        print(f"  {key:<{width}}  {value}")
    if "benchmark" in report:
        print("\nClassifier benchmark")
        print("\n".join("  " + line for line in benchmark_lines(report["benchmark"])))
    if comparison is not None:
        print("\nComparison")
        print("\n".join("  " + line for line in comparison_lines(comparison)))
    meta_out = report["meta"]
    print(
        f"\nDataset {meta_out['dataset_version']}, {meta_out['cases_run']} cases, "
        f"cost ${meta_out['cost_usd']:.4f}"
        + (" (STOPPED AT COST CAP)" if meta_out["stopped_early"] else "")
    )
    print(f"Report: {json_path}\n        {md_path}")
    regressed = comparison is not None and bool(comparison.quality_regressions())
    return 1 if regressed or meta_out["stopped_early"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
