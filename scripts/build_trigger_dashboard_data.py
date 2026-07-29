#!/usr/bin/env python3
"""Build a PII-free dataset for Mindbox MobilePush mailings of type trigger.

The script reads the shared local Delta parquet cache. Attribution competes
across every MobilePush click (mass, trigger, and transaction), but only orders
whose winning click belongs to a trigger mailing are emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import pyarrow.dataset as ds

from build_dashboard_data import (
    GOALS,
    POINTS_OF_CONTACT,
    campaign_title,
    money_value,
    number_value,
    order_project_id,
    platform,
    utc,
)
from mindbox_delta import RAW_DIR, ROOT, load_env


OUTPUT = ROOT / "data" / "generated" / "trigger_dashboard.json"
MASS_DATASET = ROOT / "dashboard" / "public" / "data" / "dashboard.json"
PROJECT_RULES_PATH = ROOT / "data" / "trigger_project_rules.json"
CONTENT_PATH = ROOT / "data" / "trigger_content.json"
MOSCOW = ZoneInfo("Europe/Moscow")
WINDOW = timedelta(hours=24)
LEADING_COPY = re.compile(r"^(?:к\s+)?(?:копия\s+|copy of\s+)*", re.IGNORECASE)
TRAILING_STEP = re.compile(r"\s+\d+$")


def cached_files(prefix: str) -> list[Path]:
    files = sorted(RAW_DIR.glob(f"{prefix}_v*.parquet"))
    if not files:
        raise RuntimeError(
            f"В локальном Delta-кэше нет файлов {prefix}. "
            "Сначала обновите общий Mindbox-кэш."
        )
    return files


def latest_rows(
    rows: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    latest: dict[Any, dict[str, Any]] = {}
    for row in rows:
        row_key = key(row)
        previous = latest.get(row_key)
        if (
            previous is None
            or row.get("_rowversion_ts") > previous.get("_rowversion_ts")
        ):
            latest[row_key] = row
    return [row for row in latest.values() if not row.get("_isDeleted")]


def parquet_rows(
    prefix: str,
    *,
    columns: list[str],
    filter_expression: Any | None = None,
    batch_size: int = 100_000,
) -> Iterable[dict[str, Any]]:
    dataset = ds.dataset(
        [str(path) for path in cached_files(prefix)],
        format="parquet",
    )
    for batch in dataset.to_batches(
        columns=columns,
        filter=filter_expression,
        batch_size=batch_size,
    ):
        yield from batch.to_pylist()


def canonical_map_for_customers(customer_ids: set[int]) -> dict[int, int]:
    """Resolve only customer merge chains that can affect this attribution run."""
    direct: dict[int, int] = {}
    pending = set(customer_ids)
    while pending:
        wanted = sorted(pending)
        rows = latest_rows(
            parquet_rows(
                "CDP_MergedCustomers",
                columns=[
                    "unmergedCustomerId",
                    "mergedCustomerId",
                    "_isDeleted",
                    "_rowversion_ts",
                ],
                filter_expression=ds.field("unmergedCustomerId").isin(wanted),
            ),
            lambda row: int(row["unmergedCustomerId"]),
        )
        pending = set()
        for row in rows:
            source = row.get("unmergedCustomerId")
            target = row.get("mergedCustomerId")
            if source is None or target is None:
                continue
            source_id = int(source)
            target_id = int(target)
            direct[source_id] = target_id
            if target_id not in direct and target_id not in customer_ids:
                pending.add(target_id)
        customer_ids.update(pending)

    resolved: dict[int, int] = {}
    for customer_id in customer_ids:
        seen: set[int] = set()
        current = customer_id
        while current in direct and current not in seen:
            seen.add(current)
            current = direct[current]
        resolved[customer_id] = current
    return resolved


def secret_hash(secret: bytes, namespace: str, value: Any) -> str:
    return hmac.new(
        secret,
        f"{namespace}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def plain_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_message_name(name: str) -> str:
    value = campaign_title(name)
    value = LEADING_COPY.sub("", value).strip()
    return re.sub(r"\s{2,}", " ", value).strip(" .")


def message_group_key(scenario_id: str, title: str) -> str:
    return hashlib.sha256(
        f"{scenario_id}:{title.casefold()}".encode("utf-8")
    ).hexdigest()[:24]


def scenario_name(titles: list[str], scenario_id: str) -> str:
    cleaned = [TRAILING_STEP.sub("", title).strip() for title in titles if title]
    if not cleaned:
        return f"Сценарий {scenario_id}"
    words = [title.split() for title in cleaned]
    common: list[str] = []
    for parts in zip(*words, strict=False):
        if len({part.casefold() for part in parts}) != 1:
            break
        common.append(parts[0])
    candidate = " ".join(common).strip(" .")
    if len(candidate) >= 5:
        return candidate
    return min(cleaned, key=len)


def project_assignment(
    mailing: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[str, str, str] | None:
    mailing_id = str(mailing["id"])
    if mailing_id in set(rules.get("excludedMailingIds", [])):
        return None
    override = rules.get("mailingOverrides", {}).get(mailing_id)
    if override:
        return override, "manual", f"mailing_internal_id={mailing_id}"
    folder_id = str(mailing.get("folderInternalId") or "")
    project_id = rules.get("folderRules", {}).get(folder_id)
    if project_id:
        return project_id, "rule", f"folder_internal_id={folder_id}"
    return "05-main", "fallback", "unclassified_trigger_mailing"


def inferred_application(project_id: str, platform_id: str) -> str:
    product = "Blizko" if project_id == "blizko-app" else "05ru"
    if platform_id == "ios":
        return f"iOS приложение {product}"
    if platform_id == "android":
        return f"Android приложение {product}"
    return f"Приложение {product}"


def moscow_date(value: datetime) -> date:
    return utc(value).astimezone(MOSCOW).date()


def number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def qualifies(
    order: dict[str, Any],
    goal_id: str,
    order_statuses: dict[str, set[str]],
    order_external_statuses: dict[str, set[str]],
) -> bool:
    order_id = str(order["id"])
    categories = order_statuses.get(order_id, set())
    external_statuses = order_external_statuses.get(order_id, set())
    point = str(order.get("firstPointOfContactInternalId") or "")
    if goal_id == "blizko-app":
        return point in POINTS_OF_CONTACT[goal_id] and bool(
            categories & {"Paid", "Delivered"}
        )
    if goal_id == "05-app":
        return point in POINTS_OF_CONTACT[goal_id] and "CheckedOut" in categories
    if goal_id == "blizko-in-05":
        return point in POINTS_OF_CONTACT[goal_id] and "Create" in external_statuses
    return bool(categories & {"CheckedOut", "Paid", "Delivered"})


def load_mass_campaign_mapping() -> dict[str, dict[str, str]]:
    if not MASS_DATASET.exists():
        return {}
    payload = json.loads(MASS_DATASET.read_text(encoding="utf-8"))
    result: dict[str, dict[str, str]] = {}
    for push in payload.get("pushes", []):
        for mailing_id in push.get("mailingIds", []):
            result[str(mailing_id)] = {
                "campaignKey": str(push["id"]),
                "projectId": str(push["projectId"]),
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since",
        default="2026-05-01",
        help="Начало периода активности trigger push, YYYY-MM-DD",
    )
    args = parser.parse_args()
    since_date = date.fromisoformat(args.since)
    since = datetime.combine(since_date, datetime.min.time(), tzinfo=MOSCOW)
    cutoff_utc = since.astimezone(UTC) - WINDOW
    now = datetime.now(UTC)

    env = load_env()
    hash_secret = (env.get("SHIFR_KEY") or env.get("SECRET_KEY") or "").encode(
        "utf-8"
    )
    if not hash_secret:
        raise RuntimeError("Для PII-free HMAC нужен SHIFR_KEY в PushAnalytics/.env")

    project_rules = json.loads(PROJECT_RULES_PATH.read_text(encoding="utf-8"))
    content_overrides: dict[str, dict[str, str]] = json.loads(
        CONTENT_PATH.read_text(encoding="utf-8")
    )

    mailing_columns = [
        "id",
        "name",
        "systemName",
        "type",
        "channel",
        "creationDateTimeUtc",
        "lastUpdateDateTimeUtc",
        "folderInternalId",
        "_isDeleted",
        "_rowversion_ts",
    ]
    mailings = latest_rows(
        parquet_rows("Mailings_Mailings", columns=mailing_columns),
        lambda row: str(row["id"]),
    )
    mobile_mailings = {
        str(row["id"]): row
        for row in mailings
        if row.get("channel") == "MobilePush"
    }
    trigger_mailings = {
        mailing_id: row
        for mailing_id, row in mobile_mailings.items()
        if row.get("type") == "trigger"
    }

    status_columns = [
        "messageId",
        "messageStatusId",
        "mailingStatusSystemName",
        "dateTimeUtc",
        "unmergedCustomerId",
        "mailingInternalId",
        "mailingVariantNum",
        "mailingSourceEntityType",
        "mailingSourceEntityId",
        "notSentSystemName",
        "notDeliveredReasonSystemName",
        "_isDeleted",
        "_rowversion_ts",
    ]
    trigger_status_filter = (
        ds.field("mailingInternalId").isin(list(trigger_mailings))
        & (ds.field("dateTimeUtc") >= cutoff_utc.replace(tzinfo=None))
    )
    trigger_status_rows = latest_rows(
        parquet_rows(
            "Mailings_CustomerMessagesStatuses",
            columns=status_columns,
            filter_expression=trigger_status_filter,
        ),
        lambda row: str(row["messageStatusId"]),
    )

    trigger_statuses = [
        row
        for row in trigger_status_rows
        if str(row.get("mailingInternalId") or "") in trigger_mailings
        and str(row.get("mailingSourceEntityType") or "").startswith("Scenario")
        and row.get("mailingSourceEntityId")
    ]

    status_by_scenario_mailing: dict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for row in trigger_statuses:
        status_by_scenario_mailing[
            (
                str(row["mailingSourceEntityId"]),
                str(row["mailingInternalId"]),
            )
        ].append(row)

    grouped_mailings: dict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    group_statuses: dict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    group_assignments: dict[tuple[str, str], tuple[str, str, str]] = {}
    mailing_to_group: dict[str, tuple[str, str]] = {}

    for (scenario_id, mailing_id), rows in status_by_scenario_mailing.items():
        mailing = trigger_mailings[mailing_id]
        assignment = project_assignment(mailing, project_rules)
        if assignment is None:
            continue
        title = normalized_message_name(str(mailing["name"]))
        group_key = (scenario_id, message_group_key(scenario_id, title))
        grouped_mailings[group_key].append(mailing)
        group_statuses[group_key].extend(rows)
        mailing_to_group[mailing_id] = group_key
        previous = group_assignments.get(group_key)
        if previous is not None and previous[0] != assignment[0]:
            raise RuntimeError(
                f"Один trigger-message назначен двум проектам: {group_key}"
            )
        group_assignments[group_key] = assignment

    scenario_titles: dict[str, list[str]] = defaultdict(list)
    for (scenario_id, _), rows in grouped_mailings.items():
        scenario_titles[scenario_id].append(
            normalized_message_name(str(rows[0]["name"]))
        )

    scenarios: list[dict[str, Any]] = []
    scenario_ids = sorted({key[0] for key in grouped_mailings})
    for scenario_id in scenario_ids:
        rows = [
            row
            for (row_scenario_id, _), statuses_for_group in group_statuses.items()
            if row_scenario_id == scenario_id
            for row in statuses_for_group
        ]
        activity = [utc(row["dateTimeUtc"]) for row in rows if row.get("dateTimeUtc")]
        scenarios.append(
            {
                "scenarioId": scenario_id,
                "name": scenario_name(scenario_titles[scenario_id], scenario_id),
                "sourceEntityType": sorted(
                    {
                        str(row.get("mailingSourceEntityType") or "Scenario")
                        for row in rows
                    }
                )[0],
                "firstActivityAt": min(activity).isoformat() if activity else None,
                "lastActivityAt": max(activity).isoformat() if activity else None,
            }
        )

    logical_mailings: list[dict[str, Any]] = []
    daily_metrics: list[dict[str, Any]] = []
    logical_key_by_group: dict[tuple[str, str], str] = {}
    project_by_group: dict[tuple[str, str], str] = {}

    for group_key in sorted(grouped_mailings):
        scenario_id, stable_key = group_key
        rows = grouped_mailings[group_key]
        statuses_for_group = group_statuses[group_key]
        project_id, assignment_source, assignment_reason = group_assignments[
            group_key
        ]
        message_key = stable_key
        logical_key_by_group[group_key] = message_key
        project_by_group[group_key] = project_id
        mailing_ids = sorted(str(row["id"]) for row in rows)
        platforms = sorted({platform(str(row["name"])) for row in rows})
        override = next(
            (
                content_overrides[mailing_id]
                for mailing_id in mailing_ids
                if mailing_id in content_overrides
            ),
            {},
        )
        title = str(
            override.get("title")
            or normalized_message_name(str(rows[0]["name"]))
        )
        body = str(override.get("body") or "")
        applications = sorted(
            {
                str(content_overrides.get(mailing_id, {}).get("application"))
                for mailing_id in mailing_ids
                if content_overrides.get(mailing_id, {}).get("application")
            }
        )
        if not applications:
            applications = sorted(
                {
                    inferred_application(
                        project_id,
                        platform(str(row["name"])),
                    )
                    for row in rows
                }
            )
        activity = [
            utc(row["dateTimeUtc"])
            for row in statuses_for_group
            if row.get("dateTimeUtc")
        ]
        logical_mailings.append(
            {
                "scenarioId": scenario_id,
                "messageKey": message_key,
                "projectId": project_id,
                "projectAssignmentSource": assignment_source,
                "projectAssignmentReason": assignment_reason,
                "name": " / ".join(sorted(str(row["name"]) for row in rows)),
                "title": title,
                "body": body,
                "mailingType": "trigger",
                "mailingIds": mailing_ids,
                "folderInternalIds": sorted(
                    {
                        str(row["folderInternalId"])
                        for row in rows
                        if row.get("folderInternalId")
                    }
                ),
                "applications": applications,
                "platforms": platforms,
                "contentSource": (
                    str(override.get("source") or "manual")
                    if override
                    else "inferred"
                ),
                "firstActivityAt": min(activity).isoformat() if activity else None,
                "lastActivityAt": max(activity).isoformat() if activity else None,
                "mindboxCreatedAt": min(
                    utc(row["creationDateTimeUtc"]) for row in rows
                ).isoformat(),
                "mindboxUpdatedAt": max(
                    utc(row["lastUpdateDateTimeUtc"]) for row in rows
                ).isoformat(),
                "isTest": False,
            }
        )

        states: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in statuses_for_group:
            states[
                (str(row["mailingInternalId"]), int(row["messageId"]))
            ].append(row)

        metrics: dict[date, dict[str, Any]] = defaultdict(
            lambda: {
                "participants": 0,
                "recipients": set(),
                "sent": 0,
                "clicked": 0,
                "notSent": 0,
                "notDelivered": 0,
                "notSentReasons": Counter(),
                "notDeliveredReasons": Counter(),
            }
        )
        for state_rows in states.values():
            sent_rows = [
                row
                for row in state_rows
                if row.get("mailingStatusSystemName") == "Sent"
            ]
            not_sent_rows = [
                row
                for row in state_rows
                if row.get("mailingStatusSystemName") == "NotSent"
            ]
            anchor_rows = sent_rows or not_sent_rows or state_rows
            anchor = min(utc(row["dateTimeUtc"]) for row in anchor_rows)
            cohort_date = moscow_date(anchor)
            if cohort_date < since_date:
                continue
            metric = metrics[cohort_date]
            metric["participants"] += 1
            customer_ids = {
                int(row["unmergedCustomerId"])
                for row in state_rows
                if row.get("unmergedCustomerId") is not None
            }
            metric["recipients"].update(customer_ids)
            if sent_rows:
                metric["sent"] += 1
            if any(
                row.get("mailingStatusSystemName") == "Clicked"
                for row in state_rows
            ) and sent_rows:
                metric["clicked"] += 1
            if not_sent_rows and not sent_rows:
                metric["notSent"] += 1
                metric["notSentReasons"].update(
                    str(row.get("notSentSystemName") or "Unknown")
                    for row in not_sent_rows
                )
            not_delivered_rows = [
                row
                for row in state_rows
                if row.get("mailingStatusSystemName") == "NotDelivered"
            ]
            if not_delivered_rows:
                metric["notDelivered"] += 1
                metric["notDeliveredReasons"].update(
                    str(row.get("notDeliveredReasonSystemName") or "Unknown")
                    for row in not_delivered_rows
                )

        for metric_date, metric in sorted(metrics.items()):
            daily_metrics.append(
                {
                    "scenarioId": scenario_id,
                    "messageKey": message_key,
                    "date": metric_date.isoformat(),
                    "participants": metric["participants"],
                    "uniqueRecipients": len(metric["recipients"]),
                    "sent": metric["sent"],
                    "deliveredEstimated": max(
                        0,
                        metric["sent"] - metric["notDelivered"],
                    ),
                    "clicked": metric["clicked"],
                    "notSent": metric["notSent"],
                    "notDelivered": metric["notDelivered"],
                    "notSentReasons": dict(metric["notSentReasons"]),
                    "notDeliveredReasons": dict(
                        metric["notDeliveredReasons"]
                    ),
                }
            )

    all_click_statuses = latest_rows(
        parquet_rows(
            "Mailings_CustomerMessagesStatuses",
            columns=status_columns,
            filter_expression=(
                ds.field("mailingInternalId").isin(list(mobile_mailings))
                & (ds.field("mailingStatusSystemName") == "Clicked")
                & (ds.field("dateTimeUtc") >= cutoff_utc.replace(tzinfo=None))
            ),
        ),
        lambda row: str(row["messageStatusId"]),
    )

    order_columns = [
        "id",
        "unmergedCustomerId",
        "firstDateTimeUtc",
        "firstPointOfContactInternalId",
        "priceWithDiscounts",
        "paidAmount",
        "_isDeleted",
        "_rowversion_ts",
    ]
    order_filter = ds.field("firstDateTimeUtc") >= cutoff_utc.replace(tzinfo=None)
    orders = latest_rows(
        parquet_rows(
            "ProcessingOrders_Orders",
            columns=order_columns,
            filter_expression=order_filter,
        ),
        lambda row: str(row["id"]),
    )

    relevant_customer_ids = {
        int(row["unmergedCustomerId"])
        for row in chain(all_click_statuses, orders)
        if row.get("unmergedCustomerId") is not None
    }
    canonical = canonical_map_for_customers(relevant_customer_ids)

    mass_campaign_by_mailing = load_mass_campaign_mapping()
    clicks_by_customer: dict[
        int, list[tuple[datetime, str, str, int]]
    ] = defaultdict(list)
    touchpoints: list[dict[str, Any]] = []
    for row in all_click_statuses:
        if (
            row.get("mailingStatusSystemName") != "Clicked"
            or row.get("unmergedCustomerId") is None
            or row.get("dateTimeUtc") is None
        ):
            continue
        mailing_id = str(row["mailingInternalId"])
        customer_id = int(row["unmergedCustomerId"])
        canonical_id = canonical.get(customer_id, customer_id)
        click_time = utc(row["dateTimeUtc"])
        status_id = str(row["messageStatusId"])
        message_id = int(row["messageId"])
        clicks_by_customer[canonical_id].append(
            (click_time, mailing_id, status_id, message_id)
        )

        source: dict[str, Any] | None = None
        group_key = mailing_to_group.get(mailing_id)
        if group_key is not None:
            source = {
                "sourceKind": "trigger",
                "scenarioId": group_key[0],
                "sourceKey": logical_key_by_group[group_key],
                "projectId": project_by_group[group_key],
            }
        elif mailing_id in mass_campaign_by_mailing:
            source = {
                "sourceKind": "mass",
                "sourceKey": mass_campaign_by_mailing[mailing_id]["campaignKey"],
                "projectId": mass_campaign_by_mailing[mailing_id]["projectId"],
            }
        if source is not None:
            touchpoints.append(
                {
                    **source,
                    "touchpointKey": secret_hash(
                        hash_secret, "click-status", status_id
                    ),
                    "mailingId": mailing_id,
                    "messageInstanceKey": secret_hash(
                        hash_secret, "message", message_id
                    ),
                    "buyerKey": secret_hash(
                        hash_secret, "customer", canonical_id
                    ),
                    "clickedAt": click_time.isoformat(),
                }
            )
    for clicks in clicks_by_customer.values():
        clicks.sort(key=lambda item: item[0])
    click_times_by_customer = {
        customer_id: [item[0] for item in clicks]
        for customer_id, clicks in clicks_by_customer.items()
    }
    candidate_orders: list[
        tuple[dict[str, Any], tuple[datetime, str, str, int]]
    ] = []
    for order in orders:
        if (
            order.get("unmergedCustomerId") is None
            or order.get("firstDateTimeUtc") is None
        ):
            continue
        order_time = utc(order["firstDateTimeUtc"])
        if order_time < since.astimezone(UTC):
            continue
        customer_id = int(order["unmergedCustomerId"])
        canonical_id = canonical.get(customer_id, customer_id)
        clicks = clicks_by_customer.get(canonical_id, [])
        if not clicks:
            continue
        position = bisect_right(
            click_times_by_customer[canonical_id],
            order_time,
        ) - 1
        if position < 0:
            continue
        winner = clicks[position]
        if order_time - winner[0] > WINDOW:
            continue
        if winner[1] not in mailing_to_group:
            continue
        if order_project_id(
            str(order.get("firstPointOfContactInternalId") or "")
        ) is None:
            continue
        candidate_orders.append((order, winner))

    candidate_order_ids = {str(order["id"]) for order, _ in candidate_orders}
    purchase_columns = [
        "orderId",
        "pricePerItem",
        "priceOfLine",
        "quantity",
        "quantityType",
        "lineId",
        "lineNumber",
        "statusInternalId",
        "productInternalId",
        "_rowversion_ts",
    ]
    purchases = latest_rows(
        parquet_rows(
            "ProcessingOrders_Purchases",
            columns=purchase_columns,
            filter_expression=ds.field("orderId").isin(
                list(candidate_order_ids) or ["__none__"]
            ),
        ),
        lambda row: (
            str(row["orderId"]),
            str(row.get("lineId") or row.get("lineNumber")),
        ),
    )

    purchase_status_columns = [
        "internalId",
        "externalId",
        "categorySystemName",
        "_isDeleted",
        "_rowversion_ts",
    ]
    purchase_statuses = latest_rows(
        parquet_rows(
            "ProcessingOrders_PurchaseStatuses",
            columns=purchase_status_columns,
        ),
        lambda row: str(row["internalId"]),
    )
    status_category = {
        str(row["internalId"]): str(row.get("categorySystemName") or "")
        for row in purchase_statuses
    }
    status_external = {
        str(row["internalId"]): str(row.get("externalId") or "")
        for row in purchase_statuses
    }

    order_statuses: dict[str, set[str]] = defaultdict(set)
    order_external_statuses: dict[str, set[str]] = defaultdict(set)
    purchase_lines_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in purchases:
        order_id = str(line["orderId"])
        status_id = str(line.get("statusInternalId") or "")
        order_statuses[order_id].add(status_category.get(status_id, ""))
        order_external_statuses[order_id].add(status_external.get(status_id, ""))
        purchase_lines_by_order[order_id].append(line)

    product_external_columns = [
        "productInternalId",
        "externalSystemInternalId",
        "externalId",
        "_isDeleted",
        "_rowversion_ts",
    ]
    relevant_product_ids = {
        str(line["productInternalId"])
        for line in purchases
        if line.get("productInternalId") is not None
    }
    product_external_rows = (
        latest_rows(
            parquet_rows(
                "PDP_ProductExternalIds",
                columns=product_external_columns,
                filter_expression=ds.field("productInternalId").isin(
                    sorted(relevant_product_ids)
                ),
            ),
            lambda row: (
                str(row["productInternalId"]),
                str(row["externalSystemInternalId"]),
            ),
        )
        if relevant_product_ids
        else []
    )
    product_external_candidates: dict[
        str, list[tuple[str, str]]
    ] = defaultdict(list)
    for row in product_external_rows:
        product_id = str(row.get("productInternalId") or "")
        external_id = str(row.get("externalId") or "")
        external_system_id = str(row.get("externalSystemInternalId") or "")
        if product_id and external_id:
            product_external_candidates[product_id].append(
                (external_system_id, external_id)
            )
    product_external: dict[str, tuple[str, str]] = {}
    for product_id, candidates in product_external_candidates.items():
        candidates.sort(key=lambda item: (item[0] != "1", item[0], item[1]))
        product_external[product_id] = candidates[0]

    attributed_orders: list[dict[str, Any]] = []
    seen_goal_orders: set[tuple[str, str]] = set()
    for order, winner in candidate_orders:
        order_id = str(order["id"])
        order_time = utc(order["firstDateTimeUtc"])
        click_time, mailing_id, status_id, _ = winner
        group_key = mailing_to_group[mailing_id]
        scenario_id, _ = group_key
        message_key = logical_key_by_group[group_key]
        customer_id = int(order["unmergedCustomerId"])
        canonical_id = canonical.get(customer_id, customer_id)
        order_key = plain_hash(order_id)
        items: list[dict[str, Any]] = []
        for index, line in enumerate(purchase_lines_by_order.get(order_id, [])):
            product_id = str(line.get("productInternalId") or "")
            external_system_id, external_id = product_external.get(
                product_id, ("", "")
            )
            line_identity = str(
                line.get("lineId")
                or line.get("lineNumber")
                or f"{product_id}:{index}"
            )
            status_id_for_line = str(line.get("statusInternalId") or "")
            items.append(
                {
                    "lineKey": plain_hash(f"{order_id}:{line_identity}"),
                    "productInternalId": product_id or None,
                    "productExternalId": external_id or None,
                    "productExternalSystemId": external_system_id or None,
                    "displayName": (
                        f"Товар · SKU {external_id}"
                        if external_id
                        else f"Товар · ID {product_id}"
                    ),
                    "quantity": number_value(line.get("quantity")),
                    "quantityType": str(line.get("quantityType") or "") or None,
                    "unitPrice": number_value(line.get("pricePerItem")),
                    "lineAmount": number_value(line.get("priceOfLine")),
                    "statusInternalId": status_id_for_line or None,
                    "statusCategory": status_category.get(
                        status_id_for_line, ""
                    )
                    or None,
                    "statusExternalId": status_external.get(
                        status_id_for_line, ""
                    )
                    or None,
                }
            )
        for goal in GOALS:
            goal_id = str(goal["id"])
            if not qualifies(
                order,
                goal_id,
                order_statuses,
                order_external_statuses,
            ):
                continue
            unique_key = (goal_id, order_key)
            if unique_key in seen_goal_orders:
                continue
            seen_goal_orders.add(unique_key)
            attributed_orders.append(
                {
                    "scenarioId": scenario_id,
                    "messageKey": message_key,
                    "touchpointKey": secret_hash(
                        hash_secret, "click-status", status_id
                    ),
                    "goalId": goal_id,
                    "orderProjectId": order_project_id(
                        str(order.get("firstPointOfContactInternalId") or "")
                    ),
                    "orderKey": order_key,
                    "buyerKey": secret_hash(
                        hash_secret, "customer", canonical_id
                    ),
                    "purchasedAt": order_time.isoformat(),
                    "attributedClickAt": click_time.isoformat(),
                    "latencyMinutes": round(
                        (order_time - click_time).total_seconds() / 60
                    ),
                    "revenue": money_value(order),
                    "firstPointOfContactId": str(
                        order.get("firstPointOfContactInternalId") or ""
                    ),
                    "statusCategories": sorted(
                        value
                        for value in order_statuses.get(order_id, set())
                        if value
                    ),
                    "statusExternalIds": sorted(
                        value
                        for value in order_external_statuses.get(order_id, set())
                        if value
                    ),
                    "items": items,
                }
            )

    winning_touchpoint_keys = {
        order["touchpointKey"] for order in attributed_orders
    }
    attributed_touchpoints = [
        touchpoint
        for touchpoint in touchpoints
        if touchpoint["touchpointKey"] in winning_touchpoint_keys
    ]

    payload = {
        "generatedAt": now.isoformat(),
        "source": "mindbox-delta-cache",
        "sourceCoverage": {
            "since": since_date.isoformat(),
            "lastStatusAt": max(
                (utc(row["dateTimeUtc"]) for row in trigger_statuses),
                default=None,
            ).isoformat()
            if trigger_statuses
            else None,
        },
        "attribution": {
            "windowHours": 24,
            "model": "Последний клик среди всех MobilePush",
        },
        "scenarios": scenarios,
        "mailings": logical_mailings,
        "dailyMetrics": daily_metrics,
        "touchpoints": attributed_touchpoints,
        "attributedOrders": attributed_orders,
    }

    if any(mailing["mailingType"] != "trigger" for mailing in logical_mailings):
        raise RuntimeError("В trigger payload попала рассылка другого типа")
    if any(
        order["latencyMinutes"] < 0 or order["latencyMinutes"] > 1440
        for order in attributed_orders
    ):
        raise RuntimeError("Найден заказ вне окна атрибуции 0–24 часа")
    if len(seen_goal_orders) != len(attributed_orders):
        raise RuntimeError("Дублируются trigger-заказы внутри цели")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "scenarios": len(scenarios),
                "logicalMailings": len(logical_mailings),
                "dailyMetrics": len(daily_metrics),
                "touchpoints": len(attributed_touchpoints),
                "attributedOrders": len(attributed_orders),
                "ordersByGoal": dict(
                    Counter(
                        order["goalId"] for order in attributed_orders
                    )
                ),
                "lastStatusAt": payload["sourceCoverage"]["lastStatusAt"],
                "containsRawCustomerOrOrderIds": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"Ошибка: {error}", file=sys.stderr)
        raise
