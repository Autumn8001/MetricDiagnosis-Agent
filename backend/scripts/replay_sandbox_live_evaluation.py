"""Read-only replay of an explicit six-run journal; no model/env/migration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.api.task_schemas import TaskDetailResponse
from app.evaluation import load_ground_truth_cases
from app.persistence.task_read_repository import InvestigationTaskReadRepository
from scripts.run_sandbox_live_evaluation import score_run
from scripts.serve_live_browser_task_acceptance import SafeArgumentParser, validate_database_url


def validate_records(events):
    plans = [e for e in events if e["event"] == "plan_frozen"]
    finals = [e for e in events if e["event"] == "batch_finished"]
    records = [e for e in events if e["event"] == "run_scored"]
    if len(plans) != 1 or len(finals) != 1 or not 0 < len(records) <= 6:
        raise ValueError("completed_journal_required")
    run_ids = [str(UUID(r["run_id"])) for r in records]
    slots = [(r["case_id"], r["repetition"]) for r in records]
    allowed_cases = {c["case_id"] for c in plans[0]["plan"]["cases"]}
    if len(set(run_ids)) != len(records) or len(set(slots)) != len(records):
        raise ValueError("duplicate_run_or_slot")
    if any(case not in allowed_cases or type(rep) is not int or rep not in (1, 2) for case, rep in slots):
        raise ValueError("invalid_case_slot")
    return plans[0]["plan"], records


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args(argv)
    try:
        validate_database_url(args.database_url)
        journal = Path(args.journal)
        if journal.stat().st_size > 1_000_000:
            raise ValueError("journal_too_large")
        plan, records = validate_records([json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()])
        # Only repository-relative files already enumerated by the current
        # preparation script can be hashed; never follow journal-supplied paths.
        from scripts.prepare_sandbox_evaluation import prepare
        if prepare()["source_sha256"] != plan["source_sha256"]:
            raise ValueError("frozen_sources_changed_use_original_revision")
        cases = {c.case_id: c for c in load_ground_truth_cases(ROOT / "warehouse/benchmark_cases.json")}
        import psycopg
        with psycopg.connect(args.database_url, connect_timeout=5) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '10s'")
            reader = InvestigationTaskReadRepository(connection)
            for record in records:
                source = str(UUID(record["source_id"]))
                identity = connection.execute(
                    "SELECT provider,environment FROM app_state.data_sources WHERE source_id=%s", (source,),
                ).fetchone()
                if identity != ("synthetic", "sandbox"):
                    raise ValueError("source_identity_mismatch")
                raw = reader.get_details(record["run_id"], source, "sandbox")
                raw["run"]["provider"] = "synthetic"
                detail = TaskDetailResponse.model_validate(raw)
                score = score_run(detail, cases[record["case_id"]])
                if score != record["score"]:
                    raise ValueError("persisted_score_changed")
        print(json.dumps({"status": "passed", "replayed_runs": len(records), "new_model_calls": 0,
                          "journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
                          "scope": "journal_scores_match_readonly_postgres_not_product_acceptance"}))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "code": "sandbox_evaluation_replay_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
