"""Pure Push Analytics rules used as the executable automation specification.

The module intentionally has no filesystem, network, or database I/O. Current
production builders are not switched to it in Stage 1; tests establish the
contract that later refactoring must preserve.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo


WINDOW = timedelta(hours=24)
MOSCOW = ZoneInfo("Europe/Moscow")
SUPPORTED_PUSH_TYPES = {"mass", "trigger", "transaction"}
PLATFORM_PATTERN = re.compile(
    r"(?:[\s._/-]+)(?:android|андроид|андройд|iphone|айфон|ios)$",
    re.IGNORECASE,
)
PUSH_PREFIX = re.compile(r"^\s*(?:копия\s+|copy of\s+)*(?:push[.\s]+)?", re.I)
WHITESPACE = re.compile(r"\s+")


class DataQualityError(RuntimeError):
    """A deterministic issue that must block certified publication."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def as_utc(value: datetime | str) -> datetime:
    """Normalize supported timestamps to timezone-aware UTC."""

    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def validate_schema(
    available_columns: Iterable[str],
    required_columns: Iterable[str],
) -> None:
    missing = sorted(set(required_columns) - set(available_columns))
    if missing:
        raise DataQualityError(
            "delta_schema_missing_columns",
            ", ".join(missing),
        )


def latest_state(
    rows: Iterable[dict[str, Any]],
    key: str | Callable[[dict[str, Any]], Any],
    *,
    required_columns: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Select latest non-deleted Delta row for every logical key."""

    materialized = list(rows)
    if not materialized:
        return []
    key_fn = (lambda row: row[key]) if isinstance(key, str) else key
    required = set(required_columns)
    for row in materialized:
        validate_schema(row.keys(), required)

    latest: dict[Any, dict[str, Any]] = {}
    for row in materialized:
        row_key = key_fn(row)
        if row_key is None:
            raise DataQualityError("delta_null_key", "logical key is null")
        previous = latest.get(row_key)
        if previous is None or as_utc(row["_rowversion_ts"]) > as_utc(
            previous["_rowversion_ts"]
        ):
            latest[row_key] = row
    return [
        row
        for row in latest.values()
        if not bool(row.get("_isDeleted"))
    ]


def advance_delta_cursor(previous_cursor: int, versions: Iterable[int]) -> int:
    """Advance a cursor only over a complete, idempotent version sequence."""

    pending = sorted({int(version) for version in versions if version > previous_cursor})
    if not pending:
        return previous_cursor
    expected = list(range(previous_cursor + 1, pending[-1] + 1))
    if pending != expected:
        missing = sorted(set(expected) - set(pending))
        raise DataQualityError(
            "delta_version_gap",
            f"previous={previous_cursor}; missing={missing}",
        )
    return pending[-1]


def build_folder_project_map(
    folders: Iterable[dict[str, Any]],
    project_roots_by_name: Mapping[str, str],
) -> dict[str, str | None]:
    """Resolve active folders to a project inherited from a configured root."""

    active_rows = latest_state(
        folders,
        "internalId",
        required_columns={
            "internalId",
            "name",
            "parentInternalId",
            "_isDeleted",
            "_rowversion_ts",
        },
    )
    by_id = {str(row["internalId"]): row for row in active_rows}
    root_projects: dict[str, str] = {}
    for root_name, project_id in project_roots_by_name.items():
        matches = [
            str(row["internalId"])
            for row in active_rows
            if str(row.get("name") or "") == root_name
        ]
        if len(matches) > 1:
            raise DataQualityError(
                "ambiguous_project_folder",
                f"name={root_name}; ids={sorted(matches)}",
            )
        if matches:
            root_projects[matches[0]] = project_id

    resolved: dict[str, str | None] = {}

    def resolve(folder_id: str, path: tuple[str, ...] = ()) -> str | None:
        if folder_id in resolved:
            return resolved[folder_id]
        if folder_id in path:
            cycle = " -> ".join((*path, folder_id))
            raise DataQualityError("folder_parent_cycle", cycle)
        if folder_id in root_projects:
            resolved[folder_id] = root_projects[folder_id]
            return resolved[folder_id]
        row = by_id.get(folder_id)
        if row is None:
            resolved[folder_id] = None
            return None
        parent = row.get("parentInternalId")
        if parent is None:
            resolved[folder_id] = None
            return None
        resolved[folder_id] = resolve(str(parent), (*path, folder_id))
        return resolved[folder_id]

    for current_id in by_id:
        resolve(current_id)
    return resolved


def resolve_mailing_project(
    mailing: Mapping[str, Any],
    folder_projects: Mapping[str, str | None],
    *,
    manual_overrides: Mapping[str, str] | None = None,
    locked_projects: Mapping[str, str] | None = None,
) -> tuple[str | None, str]:
    """Resolve project with manual override, then immutable lock, then folder."""

    mailing_id = str(mailing["id"])
    overrides = manual_overrides or {}
    locks = locked_projects or {}
    if mailing_id in overrides:
        return overrides[mailing_id], "manual"
    if mailing_id in locks:
        return locks[mailing_id], "locked"
    folder_id = str(mailing.get("folderInternalId") or "")
    project_id = folder_projects.get(folder_id)
    return project_id, ("folder" if project_id else "unclassified")


def platform_from_mailing(mailing: Mapping[str, Any]) -> str:
    explicit = str(mailing.get("platform") or "").casefold()
    if explicit in {"android", "ios"}:
        return explicit
    value = " ".join(
        str(mailing.get(field) or "")
        for field in ("name", "systemName", "applicationName")
    ).casefold()
    if any(token in value for token in ("android", "андроид", "андройд")):
        return "android"
    if any(token in value for token in ("iphone", "айфон", "ios")):
        return "ios"
    return "unknown"


def normalize_platform_suffix(value: str) -> str:
    normalized = WHITESPACE.sub(" ", value.strip())
    previous = ""
    while previous != normalized:
        previous = normalized
        normalized = PLATFORM_PATTERN.sub("", normalized).strip(" ._/-")
    return normalized


def normalize_mailing_name(value: str) -> str:
    return normalize_platform_suffix(
        PUSH_PREFIX.sub("", value).strip()
    ).casefold()


def logical_group_key(
    mailing: Mapping[str, Any],
    *,
    manual_groups: Mapping[str, str] | None = None,
) -> str | None:
    mailing_id = str(mailing["id"])
    manual = manual_groups or {}
    if mailing_id in manual:
        return f"manual:{manual[mailing_id]}"

    project_id = str(mailing.get("projectId") or "")
    variant = str(mailing.get("abVariant") or "")
    utm = str(mailing.get("utmCampaign") or "").strip()
    if utm:
        return f"utm:{project_id}:{utm.casefold()}:{variant.casefold()}"

    system_name = normalize_platform_suffix(
        str(mailing.get("systemName") or "")
    )
    if system_name:
        return (
            f"system:{project_id}:{system_name.casefold()}:"
            f"{variant.casefold()}"
        )

    name = normalize_mailing_name(str(mailing.get("name") or ""))
    sent_at = mailing.get("sentAt")
    if not name or sent_at is None:
        return None
    send_date = as_utc(sent_at).date().isoformat()
    return f"name:{project_id}:{send_date}:{name}:{variant.casefold()}"


def group_mailings(
    mailings: Iterable[dict[str, Any]],
    *,
    manual_groups: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mailing in mailings:
        if mailing.get("_isDeleted"):
            continue
        group_key = logical_group_key(mailing, manual_groups=manual_groups)
        if group_key is None:
            raise DataQualityError(
                "mailing_group_key_missing",
                f"mailing={mailing.get('id')}",
            )
        groups[group_key].append(mailing)

    for group_key, variants in groups.items():
        platforms = [platform_from_mailing(row) for row in variants]
        known_platforms = [value for value in platforms if value != "unknown"]
        if len(variants) > 2 or len(known_platforms) != len(set(known_platforms)):
            raise DataQualityError(
                "ambiguous_mailing_group",
                f"group={group_key}; platforms={platforms}",
            )
    return dict(groups)


def aggregate_message_statuses(
    rows: Iterable[dict[str, Any]],
) -> dict[str, float | int]:
    current = latest_state(
        rows,
        "messageStatusId",
        required_columns={
            "messageId",
            "messageStatusId",
            "mailingStatusSystemName",
            "_isDeleted",
            "_rowversion_ts",
        },
    )
    sent: set[str] = set()
    not_delivered: set[str] = set()
    clicked: set[str] = set()
    for row in current:
        message_id = str(row["messageId"])
        status = str(row["mailingStatusSystemName"])
        if status == "Sent":
            sent.add(message_id)
        elif status == "NotDelivered":
            not_delivered.add(message_id)
        elif status == "Clicked":
            clicked.add(message_id)

    if len(clicked) > len(sent):
        raise DataQualityError(
            "clicked_exceeds_sent",
            f"clicked={len(clicked)}; sent={len(sent)}",
        )
    delivered = max(len(sent) - len(not_delivered), 0)
    ctr = len(clicked) / delivered if delivered else 0.0
    return {
        "sent": len(sent),
        "notDelivered": len(not_delivered),
        "delivered": delivered,
        "clicked": len(clicked),
        "ctr": ctr,
    }


def build_customer_merge_map(
    rows: Iterable[dict[str, Any]],
) -> dict[int, int]:
    current = latest_state(
        (row for row in rows if row.get("unmergedCustomerId") is not None),
        lambda row: int(row["unmergedCustomerId"]),
        required_columns={
            "unmergedCustomerId",
            "mergedCustomerId",
            "_isDeleted",
            "_rowversion_ts",
        },
    )
    direct = {
        int(row["unmergedCustomerId"]): int(row["mergedCustomerId"])
        for row in current
        if row.get("mergedCustomerId") is not None
    }
    all_customers = set(direct) | set(direct.values())
    resolved: dict[int, int] = {}
    for customer_id in all_customers:
        current_id = customer_id
        path: list[int] = []
        while current_id in direct:
            if current_id in path:
                cycle = " -> ".join(map(str, (*path, current_id)))
                raise DataQualityError("customer_merge_cycle", cycle)
            path.append(current_id)
            current_id = direct[current_id]
        for traversed in path:
            resolved[traversed] = current_id
        resolved[customer_id] = current_id
    return resolved


def canonical_customer(customer_id: Any, merge_map: Mapping[int, int]) -> int:
    numeric = int(customer_id)
    return int(merge_map.get(numeric, numeric))


def attribute_orders(
    clicks: Iterable[dict[str, Any]],
    orders: Iterable[dict[str, Any]],
    *,
    merge_map: Mapping[int, int] | None = None,
    window: timedelta = WINDOW,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return one global MobilePush last-click winner per eligible order."""

    merges = merge_map or {}
    unique_clicks: dict[str, dict[str, Any]] = {}
    for click in clicks:
        if click.get("channel") != "MobilePush":
            continue
        if click.get("mailingType") not in SUPPORTED_PUSH_TYPES:
            continue
        if click.get("customerId") is None:
            continue
        click_id = str(click["clickId"])
        previous = unique_clicks.get(click_id)
        if previous is None or as_utc(click["clickedAt"]) > as_utc(
            previous["clickedAt"]
        ):
            unique_clicks[click_id] = click

    clicks_by_customer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for click in unique_clicks.values():
        customer = canonical_customer(click["customerId"], merges)
        clicks_by_customer[customer].append(click)
    for customer_clicks in clicks_by_customer.values():
        customer_clicks.sort(
            key=lambda row: (
                as_utc(row["clickedAt"]),
                str(row["clickId"]),
            )
        )

    seen_orders: set[str] = set()
    attributions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for order in orders:
        order_key = str(order["orderKey"])
        if order_key in seen_orders:
            raise DataQualityError("duplicate_order", order_key)
        seen_orders.add(order_key)
        if order.get("customerId") is None:
            issues.append(
                {"code": "order_without_customer", "orderKey": order_key}
            )
            continue
        purchased_at = as_utc(order["purchasedAt"])
        customer = canonical_customer(order["customerId"], merges)
        eligible = [
            click
            for click in clicks_by_customer.get(customer, [])
            if purchased_at - window
            <= as_utc(click["clickedAt"])
            <= purchased_at
        ]
        if not eligible:
            continue
        winner = eligible[-1]
        latency = purchased_at - as_utc(winner["clickedAt"])
        # Eligibility already enforces clickedAt <= purchasedAt. Keep this
        # defensive guard for future callers, but the branch is unreachable
        # through the public function contract.
        if latency.total_seconds() < 0:  # pragma: no cover
            raise DataQualityError("negative_attribution_latency", order_key)
        attributions.append(
            {
                **order,
                "canonicalCustomerId": customer,
                "sourceKind": winner["mailingType"],
                "winnerClickId": str(winner["clickId"]),
                "winnerMailingId": str(winner["mailingId"]),
                "attributedClickAt": as_utc(winner["clickedAt"]),
                "latencySeconds": int(latency.total_seconds()),
                "latencyMinutes": int(latency.total_seconds() // 60),
            }
        )
    return attributions, issues


def visible_attributions(
    attributions: Iterable[dict[str, Any]],
    source_kinds: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = set(source_kinds)
    return [
        row for row in attributions if row.get("sourceKind") in allowed
    ]


def normalize_project_selection(
    selected_project_ids: Iterable[str],
    available_project_ids: Iterable[str],
) -> tuple[str, ...]:
    """Validate a non-empty project multiselect and return a stable tuple."""

    selected = {str(project_id) for project_id in selected_project_ids}
    if not selected:
        raise DataQualityError(
            "project_selection_empty",
            "at least one project must be selected",
        )
    available = {str(project_id) for project_id in available_project_ids}
    unknown = sorted(selected - available)
    if unknown:
        raise DataQualityError(
            "project_selection_unknown",
            ", ".join(unknown),
        )
    return tuple(sorted(selected))


def same_project_orders(
    rows: Iterable[dict[str, Any]],
    source_projects: Mapping[str, str],
    selected_project_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Apply the post-attribution same-project business scope.

    `source_projects` must already contain the effective project after manual
    overrides. Attribution winners are intentionally not recalculated here.
    """

    selected = set(
        normalize_project_selection(
            selected_project_ids,
            source_projects.values(),
        )
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row["sourceId"])
        push_project_id = source_projects.get(source_id)
        if push_project_id is None:
            raise DataQualityError(
                "same_project_source_unknown",
                source_id,
            )
        if (
            push_project_id in selected
            and str(row.get("orderProjectId") or "") == push_project_id
        ):
            result.append(row)
    return result


def aggregate_order_selection(
    rows: Iterable[dict[str, Any]],
) -> dict[str, float | int]:
    """Aggregate one selected goal without double-counting orders or buyers."""

    unique_orders: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique_orders.setdefault(str(row["orderKey"]), row)
    return {
        "orders": len(unique_orders),
        "buyers": len(
            {
                str(row["buyerKey"])
                for row in unique_orders.values()
            }
        ),
        "revenue": round(
            sum(
                float(row.get("revenue") or 0)
                for row in unique_orders.values()
            ),
            2,
        ),
    }


def select_goal_rule(
    rules: Iterable[dict[str, Any]],
    goal_id: str,
    at: datetime | str,
) -> dict[str, Any]:
    timestamp = as_utc(at)
    matches = []
    for rule in rules:
        if str(rule.get("goalId")) != goal_id:
            continue
        starts_at = rule.get("effectiveFrom")
        ends_at = rule.get("effectiveTo")
        if starts_at is not None and timestamp < as_utc(starts_at):
            continue
        if ends_at is not None and timestamp >= as_utc(ends_at):
            continue
        matches.append(rule)
    if len(matches) != 1:
        raise DataQualityError(
            "goal_rule_cardinality",
            f"goal={goal_id}; matches={len(matches)}",
        )
    return matches[0]


def validate_order_statuses(
    order: Mapping[str, Any],
    *,
    known_categories: Iterable[str],
    known_external_statuses: Iterable[str],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    known_category_set = set(known_categories)
    known_external_set = set(known_external_statuses)
    for category in order.get("statusCategories", []):
        if category not in known_category_set:
            issues.append({"code": "unknown_status_category", "value": category})
    for external in order.get("statusExternalIds", []):
        if external not in known_external_set:
            issues.append({"code": "unknown_external_status", "value": external})
    return issues


def order_matches_rule(
    order: Mapping[str, Any],
    rule: Mapping[str, Any],
) -> bool:
    allowed_points = set(rule.get("pointIds") or [])
    if allowed_points and order.get("firstPointOfContactId") not in allowed_points:
        return False

    categories = set(order.get("statusCategories") or [])
    external_statuses = set(order.get("statusExternalIds") or [])
    wanted_categories = set(rule.get("statusCategories") or [])
    wanted_external = set(rule.get("statusExternalIds") or [])
    mode = str(rule.get("matchMode") or "any")
    conditions: list[bool] = []
    if wanted_categories:
        conditions.append(
            wanted_categories <= categories
            if mode == "all"
            else bool(wanted_categories & categories)
        )
    if wanted_external:
        conditions.append(
            wanted_external <= external_statuses
            if mode == "all"
            else bool(wanted_external & external_statuses)
        )
    if not conditions:
        return True
    return all(conditions) if mode == "all" else any(conditions)


def qualifying_goal_ids(
    order: Mapping[str, Any],
    rules: Iterable[dict[str, Any]],
) -> list[str]:
    materialized = list(rules)
    purchased_at = order["purchasedAt"]
    goal_ids = sorted({str(rule["goalId"]) for rule in materialized})
    return [
        goal_id
        for goal_id in goal_ids
        if order_matches_rule(
            order,
            select_goal_rule(materialized, goal_id, purchased_at),
        )
    ]


def order_revenue(order: Mapping[str, Any]) -> float:
    value = order.get("priceWithDiscounts")
    if value is None:
        value = order.get("paidAmount")
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def aggregate_goal_orders(
    rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["goalId"]), str(row["orderKey"]))
        unique.setdefault(key, row)

    by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (goal_id, _), row in unique.items():
        by_goal[goal_id].append(row)
    return {
        goal_id: {
            "orders": len(goal_rows),
            "buyers": len(
                {str(row["buyerKey"]) for row in goal_rows}
            ),
            "revenue": round(
                sum(float(row.get("revenue") or 0) for row in goal_rows),
                2,
            ),
        }
        for goal_id, goal_rows in by_goal.items()
    }


def moscow_calendar_date(value: datetime | str) -> str:
    return as_utc(value).astimezone(MOSCOW).date().isoformat()
