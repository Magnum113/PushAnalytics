#!/usr/bin/env python3
"""Build a PII-free local JSON dataset for the Blizko push dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from mindbox_delta import TableRef, client_from_env


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dashboard" / "public" / "data" / "dashboard.json"
CONTENT_OVERRIDES = ROOT / "data" / "push_content.json"
PROJECT_RULES_PATH = ROOT / "data" / "project_rules.json"
WINDOW = timedelta(hours=24)

PROJECTS = [
    {
        "id": "blizko-app",
        "name": "Отдельное приложение Blizko",
        "shortName": "Blizko · приложение",
    },
    {
        "id": "05-main",
        "name": "Основной проект 05.ru",
        "shortName": "05.ru · основной проект",
    },
    {
        "id": "blizko-in-05",
        "name": "Blizko внутри приложения 05.ru",
        "shortName": "Blizko внутри 05.ru",
    },
]

GOALS = [
    {
        "id": "blizko-app",
        "name": "Заказы Blizko (отдельное приложение)",
        "shortName": "Blizko · приложение",
    },
    {
        "id": "05-app",
        "name": "Заказы в приложении (ИМ)",
        "shortName": "05.ru · приложение",
    },
    {
        "id": "blizko-in-05",
        "name": "Заказ в Blizko",
        "shortName": "Blizko внутри 05.ru",
    },
    {"id": "all-orders", "name": "Заказы", "shortName": "Все заказы"},
]

POINTS_OF_CONTACT = {
    "blizko-app": {
        "97f9a0dd-62d5-4e6c-8538-d4d00ffe221a",  # blizkoios
        "af005e5f-d68b-462d-9dbb-c3b5e9a9617b",  # blizkoandroid
    },
    "05-app": {"10", "11"},  # Android приложение, iOS приложение
    "blizko-in-05": {
        "a1e1fd26-d7fd-416a-8447-b528dc8e12cd",  # Darkstore
        "70e2ff71-c63d-4061-a1c3-4282860287aa",  # AndroidAppDarkstore
        "998ee3ed-7579-43f9-8fe1-4129fb0805f6",  # IosAppDarkstore
    },
}

ORDER_PROJECT_POINTS = {
    "blizko-app": {
        "97f9a0dd-62d5-4e6c-8538-d4d00ffe221a",  # blizkoios
        "af005e5f-d68b-462d-9dbb-c3b5e9a9617b",  # blizkoandroid
        "a349e806-a88e-432b-be10-0d8746f4d6e5",  # blizkoandroidsandbox
    },
    "05-main": {
        "9",  # Сайт
        "10",  # Android приложение
        "11",  # iOS приложение
        "43bce559-5c95-4967-82d9-3985cc97d614",  # Маркетплейс
    },
    "blizko-in-05": {
        "a1e1fd26-d7fd-416a-8447-b528dc8e12cd",  # Darkstore
        "70e2ff71-c63d-4061-a1c3-4282860287aa",  # AndroidAppDarkstore
        "998ee3ed-7579-43f9-8fe1-4129fb0805f6",  # IosAppDarkstore
    },
}


def order_project_id(point_id: str) -> str | None:
    for project_id, point_ids in ORDER_PROJECT_POINTS.items():
        if point_id in point_ids:
            return project_id
    return None


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def current_rows(
    rows: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    latest: dict[Any, dict[str, Any]] = {}
    for row in rows:
        row_key = key(row)
        previous = latest.get(row_key)
        if previous is None or row.get("_rowversion_ts") > previous.get("_rowversion_ts"):
            latest[row_key] = row
    return [
        row
        for row in latest.values()
        if not row.get("_isDeleted")
    ]


PLATFORM_PATTERN = re.compile(
    r"\s*(?:Android|Андроид|Андройд|Айфон|iPhone|IOS|iOS)\s*$",
    flags=re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\s*\d{1,2}\s*[.]\s*\d{1,2}\s*$")
PUSH_PREFIX = re.compile(r"^\s*Push[.]?\s*", flags=re.IGNORECASE)
COPY_PREFIX = re.compile(r"^\s*Копия\s+", flags=re.IGNORECASE)


def campaign_title(name: str) -> str:
    value = COPY_PREFIX.sub("", name.strip())
    previous = ""
    while value != previous:
        previous = value
        value = PLATFORM_PATTERN.sub("", value)
        value = DATE_PATTERN.sub("", value)
    value = PUSH_PREFIX.sub("", value)
    return re.sub(r"\s{2,}", " ", value).strip(" .")


def campaign_key(row: dict[str, Any]) -> str:
    return campaign_title(str(row["name"])).casefold()


def campaign_group_key(
    row: dict[str, Any],
    rules: dict[str, Any],
) -> str:
    mailing_id = str(row["id"])
    override = rules.get("campaignGroupOverrides", {}).get(mailing_id)
    if override:
        return str(override)
    created = utc(row.get("creationDateTimeUtc"))
    month = created.strftime("%Y-%m") if created else "unknown"
    return f"{month}:{campaign_key(row)}"


def platform(name: str) -> str:
    lowered = name.casefold()
    if any(label in lowered for label in ("android", "андроид", "андройд")):
        return "android"
    if any(label in lowered for label in ("айфон", "iphone", "ios")):
        return "ios"
    return "unknown"


def canonical_map(merge_rows: list[dict[str, Any]]) -> dict[int, int]:
    direct: dict[int, int] = {}
    for row in merge_rows:
        source = row.get("unmergedCustomerId")
        target = row.get("mergedCustomerId")
        if source is not None and target is not None:
            direct[int(source)] = int(target)

    def resolve(customer_id: int) -> int:
        seen: set[int] = set()
        current = customer_id
        while current in direct and current not in seen:
            seen.add(current)
            current = direct[current]
        return current

    return {customer_id: resolve(customer_id) for customer_id in direct}


def money_value(row: dict[str, Any]) -> float:
    value = row.get("priceWithDiscounts")
    if value is None:
        value = row.get("paidAmount")
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def number_value(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def hashed_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assign_project(
    row: dict[str, Any],
    rules: dict[str, dict[str, str]],
) -> tuple[str, str, str] | None:
    mailing_id = str(row["id"])
    override = rules.get("mailingOverrides", {}).get(mailing_id)
    if override:
        return override, "manual", f"mailing_internal_id={mailing_id}"

    folder_id = str(row.get("folderInternalId") or "")
    project_id = rules.get("folderRules", {}).get(folder_id)
    if project_id:
        return project_id, "rule", f"folder_internal_id={folder_id}"
    return None


def version_start_for_cutoff(
    client: Any,
    ref: TableRef,
    latest_version: int,
    cutoff: datetime,
) -> int:
    """Find the first Delta version whose rows can include the requested period."""

    matching_versions: list[int] = []
    for version, add in client.add_actions(ref, 0, latest_version):
        raw_stats = add.get("stats")
        if not raw_stats:
            continue
        try:
            stats = json.loads(raw_stats)
            value = stats.get("maxValues", {}).get("_rowversion_ts")
            if not value:
                continue
            maximum = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if utc(maximum) >= cutoff:
            matching_versions.append(version)
    if not matching_versions:
        return max(0, latest_version - 180)
    return max(0, min(matching_versions) - 1)


def validate_dashboard_payload(payload: dict[str, Any]) -> list[str]:
    pushes = payload["pushes"]
    campaign_ids: set[str] = set()
    for push in pushes:
        campaign_id = str(push["id"])
        if campaign_id in campaign_ids:
            raise RuntimeError(f"Дублируется campaign id: {campaign_id}")
        campaign_ids.add(campaign_id)
        if not str(push.get("title") or "").strip():
            raise RuntimeError(f"У кампании {campaign_id} нет текста заголовка")
        if not push.get("applications"):
            raise RuntimeError(f"У кампании {campaign_id} не указано приложение")
        if push["sent"] < push["delivered"] or push["sent"] < push["notDelivered"]:
            raise RuntimeError(f"Некорректная доставка у кампании {campaign_id}")
        if sum(push["platforms"].values()) != push["delivered"]:
            raise RuntimeError(f"Платформы не сходятся с доставкой: {campaign_id}")
        for goal in GOALS:
            goal_id = goal["id"]
            metric = push["goals"][goal_id]
            orders = push["attributedOrders"][goal_id]
            if metric["orders"] != len(orders):
                raise RuntimeError(
                    f"Не сходится число заказов {campaign_id}/{goal_id}"
                )
            buyer_keys = [order["buyerKey"] for order in orders]
            if metric["buyers"] != len(set(buyer_keys)):
                raise RuntimeError(
                    f"Не сходится число покупателей {campaign_id}/{goal_id}"
                )
            if sum(metric["latency"]) != metric["orders"]:
                raise RuntimeError(
                    f"Не сходятся интервалы атрибуции {campaign_id}/{goal_id}"
                )
            order_keys = [order["orderKey"] for order in orders]
            if len(order_keys) != len(set(order_keys)):
                raise RuntimeError(
                    f"Дублируются заказы {campaign_id}/{goal_id}"
                )
            if any(
                order["latencyMinutes"] < 0
                or order["latencyMinutes"] > int(WINDOW.total_seconds() / 60)
                for order in orders
            ):
                raise RuntimeError(
                    f"Заказ вне окна атрибуции {campaign_id}/{goal_id}"
                )
            missing_order_projects = [
                order["firstPointOfContactId"]
                for order in orders
                if not order.get("orderProjectId")
            ]
            if missing_order_projects:
                raise RuntimeError(
                    "Не классифицирован проект заказа "
                    f"{campaign_id}/{goal_id}: "
                    + ", ".join(sorted(set(missing_order_projects)))
                )
    return [
        "campaign_ids_unique",
        "content_and_application_complete",
        "delivery_balances",
        "platform_totals",
        "goal_order_totals",
        "goal_buyer_totals",
        "attribution_window_0_24h",
        "order_projects_complete",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--campaigns",
        type=int,
        default=None,
        help="Необязательное ограничение количества последних кампаний на проект",
    )
    parser.add_argument(
        "--since",
        default="2026-05-01",
        help="Начальная дата рассылок включительно, YYYY-MM-DD",
    )
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)

    client = client_from_env()
    project_rules = json.loads(PROJECT_RULES_PATH.read_text(encoding="utf-8"))
    valid_project_ids = {project["id"] for project in PROJECTS}
    configured_project_ids = {
        *project_rules.get("folderRules", {}).values(),
        *project_rules.get("mailingOverrides", {}).values(),
    }
    unknown_project_ids = configured_project_ids - valid_project_ids
    if unknown_project_ids:
        raise RuntimeError(
            "В project_rules.json указаны неизвестные проекты: "
            + ", ".join(sorted(unknown_project_ids))
        )

    content_overrides: dict[str, dict[str, str]] = {}
    if CONTENT_OVERRIDES.exists():
        content_overrides = json.loads(CONTENT_OVERRIDES.read_text(encoding="utf-8"))

    mailing_ref = TableRef("Mailings", "Mailings")
    mailing_latest = client.latest_version(mailing_ref)
    mailing_table = client.read_table(
        mailing_ref,
        0,
        mailing_latest,
        refresh=args.refresh,
    )
    mailings = current_rows(mailing_table.to_pylist(), lambda row: row["id"])
    classified_mailings: list[dict[str, Any]] = []
    for row in mailings:
        if row.get("channel") != "MobilePush" or row.get("type") != "mass":
            continue
        assignment = assign_project(row, project_rules)
        if assignment is None:
            continue
        project_id, assignment_source, assignment_reason = assignment
        classified_mailings.append(
            {
                **row,
                "_projectId": project_id,
                "_projectAssignmentSource": assignment_source,
                "_projectAssignmentReason": assignment_reason,
            }
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for mailing in classified_mailings:
        grouped[
            (
                mailing["_projectId"],
                campaign_group_key(mailing, project_rules),
            )
        ].append(mailing)

    recent_groups: list[tuple[str, list[dict[str, Any]]]] = []
    for project in PROJECTS:
        project_groups = [
            (project["id"], rows)
            for (project_id, _), rows in grouped.items()
            if project_id == project["id"]
        ]
        project_groups.sort(
            key=lambda item: max(
                utc(row["creationDateTimeUtc"]) for row in item[1]
            ),
            reverse=True,
        )
        project_groups = [
            item
            for item in project_groups
            if max(utc(row["creationDateTimeUtc"]) for row in item[1]) >= since
        ]
        recent_groups.extend(
            project_groups[: args.campaigns]
            if args.campaigns is not None
            else project_groups
        )
    recent_groups.sort(
        key=lambda item: max(
            utc(row["creationDateTimeUtc"]) for row in item[1]
        ),
        reverse=True,
    )

    selected_mailing_ids = {
        str(row["id"]) for _, rows in recent_groups for row in rows
    }
    if not selected_mailing_ids:
        raise RuntimeError(
            "Не найдены MobilePush-рассылки, классифицированные в project_rules.json"
        )

    status_ref = TableRef("Mailings", "CustomerMessagesStatuses")
    status_latest = client.latest_version(status_ref)
    status_start = version_start_for_cutoff(
        client,
        status_ref,
        status_latest,
        since - timedelta(days=1),
    )
    status_table = client.read_table(
        status_ref,
        status_start,
        status_latest,
        columns=[
            "messageId",
            "messageStatusId",
            "mailingStatusSystemName",
            "dateTimeUtc",
            "unmergedCustomerId",
            "mailingInternalId",
            "_isDeleted",
            "_rowversion_ts",
        ],
        refresh=args.refresh,
    )
    status_rows = current_rows(
        status_table.to_pylist(), lambda row: row["messageStatusId"]
    )

    status_sets: dict[str, dict[str, set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    sent_times: dict[str, list[datetime]] = defaultdict(list)
    all_clicks: list[dict[str, Any]] = []
    for row in status_rows:
        mailing_id = str(row.get("mailingInternalId") or "")
        status = str(row.get("mailingStatusSystemName") or "")
        message_id = row.get("messageId")
        if message_id is None:
            continue
        if mailing_id in selected_mailing_ids:
            status_sets[mailing_id][status].add(int(message_id))
            if status == "Sent" and row.get("dateTimeUtc"):
                sent_times[mailing_id].append(utc(row["dateTimeUtc"]))
        if (
            status == "Clicked"
            and row.get("unmergedCustomerId") is not None
            and row.get("dateTimeUtc") is not None
        ):
            all_clicks.append(row)

    recent_groups = [
        (
            project_id,
            [
                row
                for row in rows
                if status_sets[str(row["id"])]["Sent"]
            ],
        )
        for project_id, rows in recent_groups
    ]
    recent_groups = [
        (project_id, rows)
        for project_id, rows in recent_groups
        if rows
    ]
    if not recent_groups:
        raise RuntimeError(
            "У классифицированных рассылок нет фактических статусов Sent"
        )
    selected_mailing_ids = {
        str(row["id"]) for _, rows in recent_groups for row in rows
    }
    unsent_mailing_ids = sorted(
        {
            str(row["id"])
            for rows in grouped.values()
            for row in rows
            if utc(row.get("creationDateTimeUtc")) >= since
            and not status_sets[str(row["id"])]["Sent"]
        }
    )
    missing_content = sorted(
        selected_mailing_ids - content_overrides.keys()
    )
    if missing_content:
        raise RuntimeError(
            "Нет проверенного текста/приложения для рассылок: "
            + ", ".join(missing_content)
        )

    earliest_campaign = min(
        (
            min(sent_times[str(row["id"])])
            if sent_times[str(row["id"])]
            else utc(row["creationDateTimeUtc"])
        )
        for _, rows in recent_groups
        for row in rows
    )

    order_ref = TableRef("ProcessingOrders", "Orders")
    order_latest = client.latest_version(order_ref)
    order_start = version_start_for_cutoff(
        client,
        order_ref,
        order_latest,
        since - timedelta(days=1),
    )
    order_table = client.read_table(
        order_ref,
        order_start,
        order_latest,
        refresh=args.refresh,
    )
    orders = current_rows(order_table.to_pylist(), lambda row: row["id"])
    orders = [
        row
        for row in orders
        if row.get("unmergedCustomerId") is not None
        and utc(row.get("firstDateTimeUtc")) is not None
        and utc(row["firstDateTimeUtc"]) >= earliest_campaign
    ]
    order_ids = {str(row["id"]) for row in orders}

    purchase_ref = TableRef("ProcessingOrders", "Purchases")
    purchase_latest = client.latest_version(purchase_ref)
    purchase_start = version_start_for_cutoff(
        client,
        purchase_ref,
        purchase_latest,
        since - timedelta(days=1),
    )
    purchase_table = client.read_table(
        purchase_ref,
        purchase_start,
        purchase_latest,
        refresh=args.refresh,
    )
    purchases = current_rows(
        purchase_table.to_pylist(),
        lambda row: (str(row["orderId"]), str(row.get("lineId") or row.get("lineNumber"))),
    )
    purchases = [row for row in purchases if str(row["orderId"]) in order_ids]

    purchase_status_ref = TableRef("ProcessingOrders", "PurchaseStatuses")
    purchase_status_latest = client.latest_version(purchase_status_ref)
    purchase_status_table = client.read_table(
        purchase_status_ref,
        0,
        purchase_status_latest,
        refresh=args.refresh,
    )
    purchase_statuses = current_rows(
        purchase_status_table.to_pylist(), lambda row: row["internalId"]
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
    order_status_external: dict[str, set[str]] = defaultdict(set)
    purchase_lines_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in purchases:
        order_id = str(line["orderId"])
        status_id = str(line.get("statusInternalId"))
        order_statuses[order_id].add(status_category.get(status_id, ""))
        order_status_external[order_id].add(status_external.get(status_id, ""))
        purchase_lines_by_order[order_id].append(line)

    product_external_ref = TableRef("PDP", "ProductExternalIds")
    product_external_latest = client.latest_version(product_external_ref)
    product_external_table = client.read_table(
        product_external_ref,
        0,
        product_external_latest,
        refresh=args.refresh,
    )
    product_external_rows = current_rows(
        product_external_table.to_pylist(),
        lambda row: (
            str(row["productInternalId"]),
            str(row["externalSystemInternalId"]),
        ),
    )
    product_external_candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
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

    merge_ref = TableRef("CDP", "MergedCustomers")
    merge_latest = client.latest_version(merge_ref)
    merge_table = client.read_table(
        merge_ref,
        0,
        merge_latest,
        refresh=args.refresh,
    )
    merge_rows = current_rows(
        merge_table.to_pylist(), lambda row: row["unmergedCustomerId"]
    )
    merged = canonical_map(merge_rows)

    clicks_by_customer: dict[int, list[tuple[datetime, str]]] = defaultdict(list)
    for click in all_clicks:
        customer_id = int(click["unmergedCustomerId"])
        canonical_id = merged.get(customer_id, customer_id)
        clicks_by_customer[canonical_id].append(
            (utc(click["dateTimeUtc"]), str(click["mailingInternalId"]))
        )
    for clicks in clicks_by_customer.values():
        clicks.sort(key=lambda item: item[0])

    def qualifies(order: dict[str, Any], goal_id: str) -> bool:
        order_id = str(order["id"])
        categories = order_statuses.get(order_id, set())
        external_statuses = order_status_external.get(order_id, set())
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

    attribution: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for goal in GOALS:
        goal_id = goal["id"]
        for order in orders:
            if not qualifies(order, goal_id):
                continue
            customer_id = int(order["unmergedCustomerId"])
            canonical_id = merged.get(customer_id, customer_id)
            order_time = utc(order["firstDateTimeUtc"])
            clicks = clicks_by_customer.get(canonical_id, [])
            if not clicks:
                continue
            click_times = [item[0] for item in clicks]
            position = bisect_right(click_times, order_time) - 1
            if position < 0:
                continue
            click_time, mailing_id = clicks[position]
            if order_time - click_time > WINDOW:
                continue
            if mailing_id not in selected_mailing_ids:
                continue
            order_id = str(order["id"])
            order_key = hashed_key(order_id)
            items: list[dict[str, Any]] = []
            for line in purchase_lines_by_order.get(order_id, []):
                product_id = str(line.get("productInternalId") or "")
                external_system_id, external_id = product_external.get(
                    product_id, ("", "")
                )
                line_identity = str(
                    line.get("lineId")
                    or line.get("lineNumber")
                    or f"{product_id}:{len(items)}"
                )
                status_id = str(line.get("statusInternalId") or "")
                items.append(
                    {
                        "lineKey": hashed_key(f"{order_id}:{line_identity}"),
                        "productInternalId": product_id,
                        "productExternalId": external_id,
                        "productExternalSystemId": external_system_id,
                        "displayName": (
                            f"Товар · SKU {external_id}"
                            if external_id.isdigit()
                            else (
                                f"Товар · ID {product_id}"
                                if product_id.isdigit()
                                else (
                                    f"Товар · SKU …{external_id[-8:]}"
                                    if external_id
                                    else f"Товар · ID …{product_id[-8:]}"
                                )
                            )
                        ),
                        "quantity": number_value(line.get("quantity")),
                        "quantityType": str(line.get("quantityType") or ""),
                        "unitPrice": number_value(line.get("pricePerItem")),
                        "lineAmount": number_value(line.get("priceOfLine")),
                        "statusInternalId": status_id,
                        "statusCategory": status_category.get(status_id, ""),
                        "statusExternalId": status_external.get(status_id, ""),
                    }
                )
            attribution[goal_id][mailing_id].append(
                {
                    "orderKey": order_key,
                    "buyerKey": hashed_key(
                        f"push-analytics-customer:{canonical_id}"
                    ),
                    "purchasedAt": order_time.isoformat(),
                    "attributedClickAt": click_time.isoformat(),
                    "latencyMinutes": round(
                        (order_time - click_time).total_seconds() / 60
                    ),
                    "revenue": money_value(order),
                    "latencyHours": (order_time - click_time).total_seconds() / 3600,
                    "firstPointOfContactId": str(
                        order.get("firstPointOfContactInternalId") or ""
                    ),
                    "orderProjectId": order_project_id(
                        str(order.get("firstPointOfContactInternalId") or "")
                    ),
                    "statusCategories": sorted(
                        value
                        for value in order_statuses.get(order_id, set())
                        if value
                    ),
                    "statusExternalIds": sorted(
                        value
                        for value in order_status_external.get(order_id, set())
                        if value
                    ),
                    "items": items,
                }
            )

    dashboard_pushes: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for project_id, group in recent_groups:
        group_ids = sorted(str(row["id"]) for row in group)
        override = next(
            (
                content_overrides[mailing_id]
                for mailing_id in group_ids
                if mailing_id in content_overrides
            ),
            {},
        )
        title = override.get("title") or campaign_title(str(group[0]["name"]))
        body = override.get("body", "")
        applications = sorted(
            {
                content_overrides[mailing_id]["application"]
                for mailing_id in group_ids
                if content_overrides.get(mailing_id, {}).get("application")
            }
        )
        campaign_sent_times = [
            value for mailing_id in group_ids for value in sent_times[mailing_id]
        ]
        sent_at = (
            min(campaign_sent_times)
            if campaign_sent_times
            else min(utc(row["creationDateTimeUtc"]) for row in group)
        )
        sent = sum(len(status_sets[mid]["Sent"]) for mid in group_ids)
        not_delivered = sum(
            len(status_sets[mid]["NotDelivered"]) for mid in group_ids
        )
        clicked = sum(len(status_sets[mid]["Clicked"]) for mid in group_ids)
        delivered = max(0, sent - not_delivered)
        platforms = {"ios": 0, "android": 0, "unknown": 0}
        for row in group:
            mailing_id = str(row["id"])
            mailing_delivery = max(
                0,
                len(status_sets[mailing_id]["Sent"])
                - len(status_sets[mailing_id]["NotDelivered"]),
            )
            platforms[platform(str(row["name"]))] += mailing_delivery

        goal_metrics: dict[str, dict[str, Any]] = {}
        attributed_orders: dict[str, list[dict[str, Any]]] = {}
        for goal in GOALS:
            events = [
                event
                for mailing_id in group_ids
                for event in attribution[goal["id"]][mailing_id]
            ]
            latency = [0, 0, 0, 0]
            for event in events:
                hours = event["latencyHours"]
                if hours <= 1:
                    latency[0] += 1
                elif hours <= 4:
                    latency[1] += 1
                elif hours <= 12:
                    latency[2] += 1
                else:
                    latency[3] += 1
            goal_metrics[goal["id"]] = {
                "orders": len(events),
                "buyers": len({event["buyerKey"] for event in events}),
                "revenue": round(sum(event["revenue"] for event in events)),
                "latency": latency,
            }
            attributed_orders[goal["id"]] = [
                {
                    key: value
                    for key, value in event.items()
                    if key != "latencyHours"
                }
                for event in events
            ]

        dashboard_pushes.append(
            {
                "id": "+".join(group_ids),
                "projectId": project_id,
                "projectAssignment": {
                    "source": str(group[0]["_projectAssignmentSource"]),
                    "reason": str(group[0]["_projectAssignmentReason"]),
                },
                "mailingIds": group_ids,
                "folderInternalIds": sorted(
                    {
                        str(row["folderInternalId"])
                        for row in group
                        if row.get("folderInternalId") is not None
                    }
                ),
                "name": " / ".join(
                    sorted(str(row["name"]) for row in group)
                ),
                "title": title,
                "body": body,
                "applications": applications,
                "sentAt": sent_at.isoformat(),
                "status": "complete" if now - sent_at >= WINDOW else "collecting",
                "sent": sent,
                "delivered": delivered,
                "clicked": clicked,
                "notDelivered": not_delivered,
                "platforms": platforms,
                "goals": goal_metrics,
                "attributedOrders": attributed_orders,
            }
        )

    payload = {
        "generatedAt": now.isoformat(),
        "source": "mindbox",
        "defaultGoalId": "all-orders",
        "defaultProjectId": "all",
        "sourceNote": (
            "Фактические статусы и заказы из Mindbox. Доставка рассчитана как "
            "Sent − NotDelivered. Заголовок, текст и приложение проверены в карточках "
            "рассылок Mindbox. Проект назначается переопределением конкретной рассылки "
            "по фактическому приложению отправки."
            " Детали покупок обезличены: идентификаторы клиентов не сохраняются, "
            "номера заказов и клиентов заменены SHA-256-хэшами. Названия товаров в Delta-выгрузке "
            "не передаются, поэтому позиции показаны по внешнему SKU."
        ),
        "attribution": {"windowHours": 24, "model": "Последний клик"},
        "projects": PROJECTS,
        "goals": GOALS,
        "pushes": dashboard_pushes,
    }
    quality_checks = validate_dashboard_payload(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "campaigns": len(dashboard_pushes),
                "mailings": len(selected_mailing_ids),
                "classifiedWithoutSentStatus": unsent_mailing_ids,
                "statuses": status_table.num_rows,
                "orders": len(orders),
                "versionRanges": {
                    "statuses": [status_start, status_latest],
                    "orders": [order_start, order_latest],
                    "purchases": [purchase_start, purchase_latest],
                },
                "qualityChecks": quality_checks,
                "campaignsByProject": {
                    project["id"]: sum(
                        push["projectId"] == project["id"]
                        for push in dashboard_pushes
                    )
                    for project in PROJECTS
                },
                "attributedOrders": {
                    goal["id"]: sum(
                        push["goals"][goal["id"]]["orders"]
                        for push in dashboard_pushes
                    )
                    for goal in GOALS
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
