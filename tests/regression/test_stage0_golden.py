from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "baselines" / "2026-07-30"
EXPECTATIONS = json.loads(
    (
        ROOT
        / "tests"
        / "fixtures"
        / "golden"
        / "stage0_expectations.json"
    ).read_text(encoding="utf-8")
)


def load(name: str) -> object:
    return json.loads((BASELINE / name).read_text(encoding="utf-8"))


def sha256(name: str) -> str:
    return hashlib.sha256((BASELINE / name).read_bytes()).hexdigest()


def test_baseline_commit_config_and_artifact_hashes_are_frozen() -> None:
    manifest = load("manifest.json")
    assert manifest["git"]["head"] == EXPECTATIONS["gitCommit"]
    assert manifest["configHash"] == EXPECTATIONS["configHash"]
    assert manifest["artifactHashes"] == EXPECTATIONS["artifactHashes"]
    for name, expected in EXPECTATIONS["artifactHashes"].items():
        assert sha256(name) == expected


def test_all_published_golden_orders_reproduce_the_winner_and_window() -> None:
    golden = load("golden_traces.json")
    traces = golden["publishedAttributedOrders"]
    assert len(traces) == EXPECTATIONS["publishedGoldenOrders"]
    order_keys = set()
    for trace in traces:
        assert trace["rawTraceStatus"] == "traced"
        assert trace["winnerMatchesPublished"] is True
        assert trace["order_key"] not in order_keys
        order_keys.add(trace["order_key"])

        purchased_at = datetime.fromisoformat(trace["purchased_at"])
        clicks = trace["eligibleMobilePushClicks"]
        click_times = [
            datetime.fromisoformat(click["clickedAt"]) for click in clicks
        ]
        assert click_times == sorted(click_times)
        assert all(
            timedelta(0) <= purchased_at - click_at <= timedelta(hours=24)
            for click_at in click_times
        )
        assert trace["computedWinner"] == clicks[-1]


def test_golden_sample_covers_mass_trigger_projects_and_diagnostics() -> None:
    golden = load("golden_traces.json")
    traces = golden["publishedAttributedOrders"]
    mass_pushes = {
        trace["source_key"]
        for trace in traces
        if trace["source_kind"] == "mass"
    }
    assert len(mass_pushes) >= EXPECTATIONS["massPushesMinimum"]
    assert len(golden["triggerPushExpectations"]) == EXPECTATIONS["triggerPushes"]

    project_counts = Counter(trace["order_project_id"] for trace in traces)
    assert all(
        project_counts[project] >= EXPECTATIONS["projectOrderMinimum"]
        for project in ("05-main", "blizko-app", "blizko-in-05")
    )
    for rows in golden["diagnosticCases"].values():
        assert len(rows) == EXPECTATIONS["diagnosticCasesPerType"]


def test_known_campaign_order_projects_do_not_change() -> None:
    golden = load("golden_traces.json")
    actual: dict[str, Counter[str]] = defaultdict(Counter)
    for trace in golden["publishedAttributedOrders"]:
        for reason in trace["selectionReasons"]:
            if not reason.startswith("known_campaign:"):
                continue
            campaign = reason.split(":", 1)[1]
            actual[campaign][trace["order_project_id"]] += 1
    assert {
        campaign: dict(counter)
        for campaign, counter in actual.items()
    } == EXPECTATIONS["knownCampaigns"]


def test_supabase_snapshot_quality_is_zero_and_details_reconcile() -> None:
    snapshot = load("supabase_snapshot.json")
    assert all(
        value == [] if isinstance(value, list) else value == 0
        for value in snapshot["quality"].values()
    )
    summary = snapshot["summary"]
    assert summary["campaigns"] == 39
    assert summary["triggerMailings"] == EXPECTATIONS["triggerPushes"]
    assert summary["massAttributedOrders"] == 832
    assert summary["triggerAttributedOrders"] == 207


def test_baseline_has_no_obvious_contacts_or_secrets() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(BASELINE.iterdir())
        if path.is_file() and path.suffix in {".json", ".md"}
    )
    text = re.sub(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}\b",
        "",
        text,
    )
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    assert not re.search(
        r"(?<![0-9a-fA-F])(?:\+7|8)[\s()\-]*\d{3}"
        r"[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}",
        text,
    )
    assert not re.search(
        r"(?i)(?:password|secret|token|anon_key|service_role_key)"
        r"\s*[=:]\s*[\"']?[^\"'\s,}]{8,}",
        text,
    )
