#!/usr/bin/env python3
"""Validate the tracked Stage 0 baseline without accessing production systems."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "baselines" / "2026-07-30"
REQUIRED_FILES = (
    "manifest.json",
    "configuration.json",
    "supabase_snapshot.json",
    "golden_traces.json",
    "golden_diagnostics.json",
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?<![0-9a-fA-F])(?:\+7|8)[\s()\-]*\d{3}"
    r"[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:password|secret|token|anon_key|service_role_key)"
    r"\s*[=:]\s*[\"']?[^\"'\s,}]{8,}"
)
UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\b"
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
    )
    args = parser.parse_args()
    baseline = args.baseline.resolve()

    failures: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    def check(code: str, condition: bool, detail: str) -> None:
        checks.append({"code": code, "passed": bool(condition), "detail": detail})
        if not condition:
            failures.append(f"{code}: {detail}")

    missing = [name for name in REQUIRED_FILES if not (baseline / name).is_file()]
    check("required_files", not missing, f"missing={missing}")
    if missing:
        write_report(baseline, checks, failures, warnings)
        raise SystemExit(1)

    manifest = load_json(baseline / "manifest.json")
    configuration = load_json(baseline / "configuration.json")
    supabase = load_json(baseline / "supabase_snapshot.json")
    golden = load_json(baseline / "golden_traces.json")
    diagnostics = load_json(baseline / "golden_diagnostics.json")

    hashes = manifest.get("artifactHashes", {})
    bad_hashes = [
        name
        for name, expected in hashes.items()
        if not (baseline / name).is_file()
        or sha256(baseline / name) != expected
    ]
    check("artifact_hashes", not bad_hashes, f"mismatches={bad_hashes}")
    check(
        "config_hash",
        manifest.get("configHash") == configuration.get("configHash"),
        "manifest and configuration hashes must match",
    )

    git_state = manifest.get("git", {})
    check(
        "git_commit",
        bool(re.fullmatch(r"[0-9a-f]{40}", str(git_state.get("head") or ""))),
        f"head={git_state.get('head')}",
    )

    folder_checks = configuration.get("projectFolderChecks", [])
    check(
        "project_folder_count",
        len(folder_checks) == 3,
        f"observed={len(folder_checks)}",
    )
    bad_folders = [
        row
        for row in folder_checks
        if row.get("exactActiveMatches") != 1 or row.get("parentInternalIds")
    ]
    check(
        "project_folders_exact",
        not bad_folders,
        f"invalid={bad_folders}",
    )

    quality = supabase.get("quality", {})
    quality_failures = {
        key: value
        for key, value in quality.items()
        if (isinstance(value, list) and value)
        or (not isinstance(value, list) and value not in (0, None))
    }
    check(
        "supabase_quality",
        not quality_failures,
        f"nonZero={quality_failures}",
    )

    traces = golden.get("publishedAttributedOrders", [])
    check(
        "published_trace_count",
        len(traces) == diagnostics.get("tracedPublishedOrders"),
        (
            f"traces={len(traces)} "
            f"diagnostics={diagnostics.get('tracedPublishedOrders')}"
        ),
    )

    bad_identifiers: list[str] = []
    bad_trace_winners: list[str] = []
    bad_click_windows: list[str] = []
    bad_click_ordering: list[str] = []
    for trace in traces:
        order_key = str(trace.get("order_key") or "")
        buyer_key = str(trace.get("buyer_key") or "")
        if not HEX_64.fullmatch(order_key) or not HEX_64.fullmatch(buyer_key):
            bad_identifiers.append(order_key)
        if (
            trace.get("rawTraceStatus") != "traced"
            or trace.get("winnerMatchesPublished") is not True
        ):
            bad_trace_winners.append(order_key)
        purchased_at = parse_time(str(trace["purchased_at"]))
        clicks = trace.get("eligibleMobilePushClicks", [])
        click_times = [parse_time(str(click["clickedAt"])) for click in clicks]
        if click_times != sorted(click_times):
            bad_click_ordering.append(order_key)
        if any(
            click_at > purchased_at
            or (purchased_at - click_at).total_seconds() > 24 * 60 * 60
            for click_at in click_times
        ):
            bad_click_windows.append(order_key)
        computed = trace.get("computedWinner")
        if clicks and computed != clicks[-1]:
            bad_trace_winners.append(order_key)
    check(
        "pii_free_keys",
        not bad_identifiers,
        f"invalidHashKeys={bad_identifiers[:5]}",
    )
    check(
        "golden_winners",
        not bad_trace_winners,
        f"invalidOrders={sorted(set(bad_trace_winners))[:5]}",
    )
    check(
        "golden_click_window",
        not bad_click_windows,
        f"invalidOrders={bad_click_windows[:5]}",
    )
    check(
        "golden_click_ordering",
        not bad_click_ordering,
        f"invalidOrders={bad_click_ordering[:5]}",
    )

    mass_sources = {
        str(trace["source_key"])
        for trace in traces
        if trace.get("source_kind") == "mass"
    }
    trigger_expectations = golden.get("triggerPushExpectations", [])
    expected_trigger_count = int(
        supabase.get("summary", {}).get("triggerMailings") or 0
    )
    check(
        "mass_push_sample",
        len(mass_sources) >= 10,
        f"massPushes={len(mass_sources)}",
    )
    check(
        "all_trigger_pushes",
        len(trigger_expectations) == expected_trigger_count,
        (
            f"golden={len(trigger_expectations)} "
            f"supabase={expected_trigger_count}"
        ),
    )

    project_counts = golden.get("selection", {}).get("byOrderProject", {})
    undersampled_projects = {
        key: value for key, value in project_counts.items() if int(value) < 20
    }
    check(
        "order_project_samples",
        not undersampled_projects,
        f"counts={project_counts}",
    )

    known_names = {
        reason.split(":", 1)[1]
        for trace in traces
        for reason in trace.get("selectionReasons", [])
        if reason.startswith("known_campaign:")
    }
    check(
        "known_campaigns",
        {"К матчу готовы", "За окном +30"} <= known_names,
        f"found={sorted(known_names)}",
    )

    cases = golden.get("diagnosticCases", {})
    required_diagnostics = (
        "transactionWinner",
        "massTriggerCompetition",
        "noPriorMobilePushClick",
        "lastClickOutside24h",
        "closestInside24h",
    )
    missing_cases = [
        code for code in required_diagnostics if not cases.get(code)
    ]
    check(
        "diagnostic_cases",
        not missing_cases,
        f"missing={missing_cases}",
    )

    zero_order_pushes = golden.get("zeroOrderPushes", [])
    check(
        "zero_order_push",
        bool(zero_order_pushes),
        f"count={len(zero_order_pushes)}",
    )

    exact_boundary = [
        trace
        for trace in traces
        if int(trace.get("latency_minutes") or -1) in (0, 1440)
    ]
    if not exact_boundary:
        closest = max(
            (int(trace.get("latency_minutes") or -1) for trace in traces),
            default=-1,
        )
        warnings.append(
            "В опубликованных заказах нет события ровно на 0/1440-й минуте; "
            f"зафиксирован ближайший доступный случай ({closest} мин.)."
        )

    for table, state in manifest.get("mindboxDelta", {}).items():
        latest = state.get("latestVersion")
        cached = state.get("localCacheMaxVersion")
        if isinstance(latest, int) and isinstance(cached, int) and cached < latest:
            warnings.append(
                f"{table}: локальный кэш v{cached}, доступный Delta v{latest}."
            )

    captured_files_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(baseline.iterdir())
        if path.is_file() and path.suffix in {".json", ".md"}
    )
    pii_scan_text = UUID.sub("", captured_files_text)
    pii_hits = {
        "emails": len(EMAIL.findall(pii_scan_text)),
        "phones": len(PHONE.findall(pii_scan_text)),
        "secretAssignments": len(SECRET_ASSIGNMENT.findall(pii_scan_text)),
    }
    check(
        "no_obvious_pii_or_secrets",
        not any(pii_hits.values()),
        f"hits={pii_hits}",
    )

    write_report(baseline, checks, failures, warnings)
    if failures:
        raise SystemExit(1)


def write_report(
    baseline: Path,
    checks: list[dict[str, Any]],
    failures: list[str],
    warnings: list[str],
) -> None:
    result = {
        "status": "failed" if failures else ("passed_with_warnings" if warnings else "passed"),
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
    }
    (baseline / "validation_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Stage 0 validation report",
        "",
        f"**Status:** `{result['status']}`",
        "",
        "## Automated checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for row in checks:
        detail = str(row["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{row['code']}` | "
            f"{'PASS' if row['passed'] else 'FAIL'} | {detail} |"
        )
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- Нет.")
    lines.extend(["", "## Failures", ""])
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- Нет.")
    lines.append("")
    (baseline / "validation_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
