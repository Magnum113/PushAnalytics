#!/usr/bin/env python3
"""Capture a reproducible, PII-free Stage 0 baseline.

The script is read-only with respect to Mindbox and Supabase. It records:

- Git and local source fingerprints;
- latest Mindbox Delta versions and freshness;
- effective project/goal/contact configuration;
- current Supabase aggregates, schema metadata, and quality invariants;
- a deterministic golden sample of attributed and non-attributed orders;
- all competing MobilePush clicks for the selected orders.

Raw order and customer identifiers are used only in memory. Persisted order,
buyer, status, and message identifiers are SHA-256/HMAC values.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import subprocess
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pyarrow.dataset as ds

from build_dashboard_data import (
    GOALS,
    ORDER_PROJECT_POINTS,
    POINTS_OF_CONTACT,
    money_value,
    order_project_id,
    utc,
)
from build_trigger_dashboard_data import latest_rows, parquet_rows
from mindbox_delta import ROOT, TableRef, client_from_env, load_env
from sync_supabase_pg_meta import execute_sql


DEFAULT_OUTPUT = ROOT / "baselines" / "2026-07-30"
SINCE = datetime(2026, 5, 1, tzinfo=UTC)
WINDOW = timedelta(hours=24)

DELTA_TABLES = (
    TableRef("CDP", "Folders"),
    TableRef("Mailings", "Mailings"),
    TableRef("Mailings", "CustomerMessagesStatuses"),
    TableRef("ProcessingOrders", "Orders"),
    TableRef("ProcessingOrders", "Purchases"),
    TableRef("ProcessingOrders", "PurchaseStatuses"),
    TableRef("ProcessingOrders", "PointsOfContact"),
    TableRef("CDP", "MergedCustomers"),
    TableRef("PDP", "ProductExternalIds"),
)

CONFIG_FILES = (
    ROOT / "data" / "project_rules.json",
    ROOT / "data" / "trigger_project_rules.json",
    ROOT / "data" / "push_content.json",
    ROOT / "data" / "trigger_content.json",
)

SOURCE_FILES = (
    ROOT / "scripts" / "build_dashboard_data.py",
    ROOT / "scripts" / "build_trigger_dashboard_data.py",
    ROOT / "scripts" / "sync_supabase.py",
    ROOT / "scripts" / "sync_supabase_pg_meta.py",
    ROOT / "scripts" / "sync_trigger_supabase_pg_meta.py",
    ROOT / "scripts" / "validate_supabase_data.py",
    ROOT / "scripts" / "validate_trigger_supabase_data.py",
)

EXPECTED_FOLDERS = {
    "Пуши по 05ру в приложении 05ру": {
        "internalId": "b4476805-41cf-4e89-a51f-cd88c25ef859",
        "projectId": "05-main",
    },
    "Пуши по Близко в приложении 05ру": {
        "internalId": "88976d9a-80ba-47e0-b514-32b833ba3350",
        "projectId": "blizko-in-05",
    },
    "Пуши в отдельном приложении Близко": {
        "internalId": "5973dc8f-9411-4de3-a53b-32c87497812c",
        "projectId": "blizko-app",
    },
}

KNOWN_CAMPAIGN_PATTERNS = (
    "К матчу готовы",
    "За окном +30",
)


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc(value).isoformat()
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def plain_hash(namespace: str, value: Any) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode("utf-8")).hexdigest()


def secret_hash(secret: bytes, namespace: str, value: Any) -> str:
    return hmac.new(
        secret,
        f"{namespace}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def capture_git() -> dict[str, Any]:
    status = git_output("status", "--porcelain=v1")
    return {
        "head": git_output("rev-parse", "HEAD"),
        "branch": git_output("branch", "--show-current"),
        "originMain": git_output("rev-parse", "origin/main"),
        "isDirty": bool(status),
        "workingTreeStatus": status.splitlines(),
        "sourceFiles": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": file_sha256(path),
            }
            for path in SOURCE_FILES
        ],
    }


def _rowversion_from_stats(add: dict[str, Any]) -> datetime | None:
    raw_stats = add.get("stats")
    if not raw_stats:
        return None
    try:
        stats = json.loads(raw_stats)
    except (TypeError, json.JSONDecodeError):
        return None
    raw_value = stats.get("maxValues", {}).get("_rowversion_ts")
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None


def capture_delta_versions() -> dict[str, Any]:
    client = client_from_env()
    result: dict[str, Any] = {}
    for ref in DELTA_TABLES:
        latest = client.latest_version(ref)
        window_end = latest
        additions: list[dict[str, Any]] = []
        while window_end >= 0 and not additions:
            # Mindbox Delta Sharing accepts at most ten versions per request.
            window_start = max(0, window_end - 9)
            actions = client.changes(ref, window_start, window_end)
            additions = [
                action["add"]
                for action in actions
                if isinstance(action.get("add"), dict)
            ]
            window_end = window_start - 1
        rowversions = [
            value
            for value in (_rowversion_from_stats(add) for add in additions)
            if value is not None
        ]
        cached_versions = [
            int(match.group(1))
            for path in (ROOT / "data" / "raw").glob(
                f"{ref.schema}_{ref.table}_v*.parquet"
            )
            if (
                match := re.search(
                    r"_v(\d+)_",
                    path.name,
                )
            )
        ]
        result[ref.slug] = {
            "latestVersion": latest,
            "latestDataAt": (
                max(rowversions).astimezone(UTC).isoformat()
                if rowversions
                else None
            ),
            "latestWindowAdds": len(additions),
            "localCacheMaxVersion": max(cached_versions) if cached_versions else None,
            "localCacheFiles": len(cached_versions),
        }
    return result


def capture_configuration() -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in CONFIG_FILES:
        content = json.loads(path.read_text(encoding="utf-8"))
        files[str(path.relative_to(ROOT))] = {
            "sha256": file_sha256(path),
            "content": content,
        }

    database_configuration = {
        "projects": execute_sql(
            """
            select id, name, short_name, description, sort_order, is_active
            from public.push_projects
            order by sort_order, id;
            """
        ),
        "goals": execute_sql(
            """
            select id, name, short_name, description, sort_order, is_active
            from public.push_goals
            order by sort_order, id;
            """
        ),
        "projectRules": execute_sql(
            """
            select
              project_id,
              match_field,
              match_value,
              priority,
              notes,
              is_active
            from public.push_project_rules
            order by match_field, match_value;
            """
        ),
        "orderProjectPoints": execute_sql(
            """
            select point_id, point_name, project_id, notes
            from public.push_order_project_points
            order by project_id, point_id;
            """
        ),
        "manualOverrides": execute_sql(
            """
            select
              source_kind,
              campaign_id,
              scenario_mailing_id,
              project_id,
              name,
              title,
              body,
              application_names,
              is_hidden,
              updated_at
            from public.push_manual_overrides
            order by source_kind, campaign_id, scenario_mailing_id;
            """
        ),
    }

    effective = {
        "codeGoals": GOALS,
        "codeGoalPoints": {
            key: sorted(value) for key, value in POINTS_OF_CONTACT.items()
        },
        "codeOrderProjectPoints": {
            key: sorted(value) for key, value in ORDER_PROJECT_POINTS.items()
        },
        "expectedFolders": EXPECTED_FOLDERS,
        "files": files,
        "database": database_configuration,
    }
    folder_rows = latest_rows(
        (
            row
            for row in parquet_rows(
                "CDP_Folders",
                columns=[
                    "internalId",
                    "systemName",
                    "name",
                    "parentInternalId",
                    "_isDeleted",
                    "_rowversion_ts",
                ],
            )
            if row.get("internalId") is not None
        ),
        lambda row: str(row["internalId"]),
    )
    observed_folders = [
        {
            "internalId": str(row["internalId"]),
            "systemName": row.get("systemName"),
            "name": row.get("name"),
            "parentInternalId": row.get("parentInternalId"),
            "sourceRowversionAt": row.get("_rowversion_ts"),
        }
        for row in folder_rows
        if row.get("name") in EXPECTED_FOLDERS
    ]
    folder_checks = []
    for name, expected in EXPECTED_FOLDERS.items():
        matches = [
            row
            for row in observed_folders
            if row["name"] == name
            and row["internalId"] == expected["internalId"]
        ]
        folder_checks.append(
            {
                "name": name,
                "expectedInternalId": expected["internalId"],
                "expectedProjectId": expected["projectId"],
                "exactActiveMatches": len(matches),
                "parentInternalIds": sorted(
                    {
                        str(row["parentInternalId"])
                        for row in matches
                        if row["parentInternalId"] is not None
                    }
                ),
            }
        )
    return {
        **effective,
        "configHash": canonical_json_hash(effective),
        "observedProjectFolders": observed_folders,
        "projectFolderChecks": folder_checks,
    }


def capture_supabase() -> dict[str, Any]:
    summary = execute_sql(
        """
        select jsonb_build_object(
          'campaigns', (select count(*) from public.push_campaigns),
          'campaignGoalMetrics', (
            select count(*) from public.push_campaign_goal_metrics
          ),
          'massAttributedOrders', (
            select count(*) from public.push_attributed_orders
          ),
          'massAttributedOrderItems', (
            select count(*) from public.push_attributed_order_items
          ),
          'products', (select count(*) from public.push_products),
          'scenarios', (
            select count(*) from public.push_scenarios where is_active
          ),
          'triggerMailings', (
            select count(*) from public.push_scenario_mailings
            where not is_test
          ),
          'triggerDailyMetrics', (
            select count(*) from public.push_scenario_daily_metrics
          ),
          'triggerAttributedOrders', (
            select count(*) from public.push_trigger_attributed_orders
          ),
          'triggerAttributedOrderItems', (
            select count(*) from public.push_trigger_attributed_order_items
          ),
          'manualOverrides', (
            select count(*) from public.push_manual_overrides
          ),
          'massGeneratedAt', (
            select max(generated_at) from public.push_campaigns
          ),
          'massLatestSentAt', (
            select max(sent_at) from public.push_campaigns
          ),
          'triggerGeneratedAt', (
            select max(generated_at) from public.push_scenario_mailings
          ),
          'triggerLatestActivityAt', (
            select max(last_activity_at) from public.push_scenario_mailings
          ),
          'lastSuccessfulSyncAt', (
            select max(finished_at)
            from public.push_sync_runs
            where status = 'succeeded'
          )
        ) as value;
        """
    )[0]["value"]

    mass_metrics = execute_sql(
        """
        select
          campaign.campaign_key,
          campaign.project_id,
          campaign.name,
          campaign.title,
          campaign.sent_at,
          campaign.mailing_ids,
          campaign.folder_internal_ids,
          campaign.application_names,
          campaign.sent,
          campaign.delivered,
          campaign.clicked,
          campaign.not_delivered,
          campaign.platform_ios,
          campaign.platform_android,
          campaign.platform_unknown,
          metric.goal_id,
          metric.orders,
          metric.buyers,
          metric.revenue,
          metric.latency_0_1h,
          metric.latency_1_4h,
          metric.latency_4_12h,
          metric.latency_12_24h
        from public.push_campaigns as campaign
        join public.push_campaign_goal_metrics as metric
          on metric.campaign_id = campaign.id
        order by campaign.sent_at, campaign.campaign_key, metric.goal_id;
        """
    )

    mass_order_project_metrics = execute_sql(
        """
        select
          campaign.campaign_key,
          metric.goal_id,
          metric.order_project_id,
          metric.orders,
          metric.buyers,
          metric.revenue,
          metric.latency_0_1h,
          metric.latency_1_4h,
          metric.latency_4_12h,
          metric.latency_12_24h
        from public.push_campaign_goal_order_project_metrics as metric
        join public.push_campaigns as campaign
          on campaign.id = metric.campaign_id
        order by
          campaign.campaign_key,
          metric.goal_id,
          metric.order_project_id;
        """
    )

    trigger_metrics = execute_sql(
        """
        select
          scenario.mindbox_scenario_id,
          mailing.message_key,
          mailing.project_id,
          mailing.name,
          mailing.title,
          mailing.mailing_ids,
          mailing.folder_internal_ids,
          mailing.application_names,
          mailing.first_activity_at,
          mailing.last_activity_at,
          goal.id as goal_id,
          coalesce(metric.orders, 0)::bigint as orders,
          coalesce(metric.buyers, 0)::bigint as buyers,
          coalesce(metric.revenue, 0)::numeric(16, 2) as revenue,
          coalesce(metric.latency_0_1h, 0)::bigint as latency_0_1h,
          coalesce(metric.latency_1_4h, 0)::bigint as latency_1_4h,
          coalesce(metric.latency_4_12h, 0)::bigint as latency_4_12h,
          coalesce(metric.latency_12_24h, 0)::bigint as latency_12_24h
        from public.push_scenario_mailings as mailing
        join public.push_scenarios as scenario
          on scenario.id = mailing.scenario_id
        cross join public.push_goals as goal
        left join public.push_trigger_goal_metrics as metric
          on metric.scenario_mailing_id = mailing.id
         and metric.goal_id = goal.id
        where not mailing.is_test
        order by
          scenario.mindbox_scenario_id,
          mailing.message_key,
          goal.id;
        """
    )

    trigger_daily_metrics = execute_sql(
        """
        select
          scenario.mindbox_scenario_id,
          mailing.message_key,
          metric.metric_date,
          metric.participants,
          metric.unique_recipients,
          metric.sent,
          metric.delivered_estimated,
          metric.clicked,
          metric.not_sent,
          metric.not_delivered
        from public.push_scenario_daily_metrics as metric
        join public.push_scenario_mailings as mailing
          on mailing.id = metric.scenario_mailing_id
        join public.push_scenarios as scenario
          on scenario.id = mailing.scenario_id
        order by
          scenario.mindbox_scenario_id,
          mailing.message_key,
          metric.metric_date;
        """
    )

    quality = execute_sql(
        """
        with mass_actual as (
          select
            campaign_id,
            goal_id,
            count(*)::bigint as orders,
            count(distinct buyer_key)::bigint as buyers,
            round(coalesce(sum(revenue), 0), 2)::numeric(16, 2) as revenue
          from public.push_attributed_orders
          group by campaign_id, goal_id
        ),
        physical_order_winners as (
          select
            order_key,
            count(distinct winner) as winners
          from (
            select
              order_key,
              'mass:' || campaign_id::text as winner
            from public.push_attributed_orders
            where goal_id = 'all-orders'
            union all
            select
              order_key,
              'trigger:' || scenario_mailing_id::text as winner
            from public.push_trigger_attributed_orders
            where goal_id = 'all-orders'
          ) as all_winners
          group by order_key
        )
        select jsonb_build_object(
          'massBadDelivery', (
            select count(*) from public.push_campaigns
            where delivered <> greatest(sent - not_delivered, 0)
               or platform_ios + platform_android + platform_unknown
                  <> delivered
               or clicked > sent
          ),
          'massBadMetricCardinality', (
            select count(*)
            from (
              select campaign_id
              from public.push_campaign_goal_metrics
              group by campaign_id
              having count(*) <> (
                select count(*) from public.push_goals where is_active
              )
            ) as invalid
          ),
          'massBadAttributionWindow', (
            select count(*) from public.push_attributed_orders
            where latency_minutes not between 0 and 1440
               or attributed_click_at > purchased_at
          ),
          'massBadMetricTotals', (
            select count(*)
            from public.push_campaign_goal_metrics as metric
            left join mass_actual as actual
              using (campaign_id, goal_id)
            where metric.orders <> coalesce(actual.orders, 0)
               or metric.buyers <> coalesce(actual.buyers, 0)
               or metric.revenue <> coalesce(actual.revenue, 0)
          ),
          'triggerInvalidDailyMetrics', (
            select count(*) from public.push_scenario_daily_metrics
            where clicked > sent
               or delivered_estimated > sent
               or not_delivered > sent
               or unique_recipients > participants
          ),
          'triggerOrdersOutsideWindow', (
            select count(*) from public.push_trigger_attributed_orders
            where latency_minutes not between 0 and 1440
               or attributed_click_at > purchased_at
          ),
          'duplicatePhysicalWinners', (
            select count(*) from physical_order_winners where winners > 1
          ),
          'massOrphanItems', (
            select count(*)
            from public.push_attributed_order_items as item
            left join public.push_attributed_orders as attributed_order
              on attributed_order.id = item.attributed_order_id
            where attributed_order.id is null
          ),
          'triggerOrphanItems', (
            select count(*)
            from public.push_trigger_attributed_order_items as item
            left join public.push_trigger_attributed_orders as attributed_order
              on attributed_order.id = item.attributed_order_id
            where attributed_order.id is null
          ),
          'unknownOrderProjects', (
            select count(*)
            from (
              select order_project_id, first_point_of_contact_id
              from public.push_attributed_orders
              union all
              select order_project_id, first_point_of_contact_id
              from public.push_trigger_attributed_orders
            ) as attributed_order
            left join public.push_order_project_points as point
              on point.point_id = attributed_order.first_point_of_contact_id
            where attributed_order.order_project_id is null
               or point.project_id is null
               or attributed_order.order_project_id <> point.project_id
          ),
          'rlsDisabledTables', (
            select coalesce(jsonb_agg(relname order by relname), '[]'::jsonb)
            from pg_class
            where relnamespace = 'public'::regnamespace
              and relkind = 'r'
              and relname like 'push_%'
              and not relrowsecurity
          )
        ) as value;
        """
    )[0]["value"]

    schema = execute_sql(
        """
        select
          table_schema,
          table_name,
          column_name,
          data_type,
          is_nullable,
          ordinal_position
        from information_schema.columns
        where table_schema = 'public'
          and table_name like 'push_%'
        order by table_name, ordinal_position;
        """
    )

    return {
        "summary": summary,
        "quality": quality,
        "massMetrics": mass_metrics,
        "massOrderProjectMetrics": mass_order_project_metrics,
        "triggerMetrics": trigger_metrics,
        "triggerDailyMetrics": trigger_daily_metrics,
        "schema": schema,
    }


def supabase_order_candidates() -> list[dict[str, Any]]:
    return execute_sql(
        """
        select
          'mass'::text as source_kind,
          campaign.campaign_key as source_key,
          campaign.project_id as push_project_id,
          campaign.name as push_name,
          campaign.title as push_title,
          campaign.mailing_ids,
          attributed_order.goal_id,
          attributed_order.order_key,
          attributed_order.buyer_key,
          attributed_order.purchased_at,
          attributed_order.attributed_click_at,
          attributed_order.latency_minutes,
          attributed_order.revenue,
          attributed_order.order_project_id,
          attributed_order.first_point_of_contact_id,
          attributed_order.status_categories,
          attributed_order.status_external_ids
        from public.push_attributed_orders as attributed_order
        join public.push_campaigns as campaign
          on campaign.id = attributed_order.campaign_id
        where attributed_order.goal_id = 'all-orders'
        union all
        select
          'trigger'::text as source_kind,
          scenario.mindbox_scenario_id || ':' || mailing.message_key
            as source_key,
          mailing.project_id as push_project_id,
          mailing.name as push_name,
          mailing.title as push_title,
          mailing.mailing_ids,
          attributed_order.goal_id,
          attributed_order.order_key,
          attributed_order.buyer_key,
          attributed_order.purchased_at,
          attributed_order.attributed_click_at,
          attributed_order.latency_minutes,
          attributed_order.revenue,
          attributed_order.order_project_id,
          attributed_order.first_point_of_contact_id,
          attributed_order.status_categories,
          attributed_order.status_external_ids
        from public.push_trigger_attributed_orders as attributed_order
        join public.push_scenario_mailings as mailing
          on mailing.id = attributed_order.scenario_mailing_id
        join public.push_scenarios as scenario
          on scenario.id = mailing.scenario_id
        where attributed_order.goal_id = 'all-orders'
        order by purchased_at, source_kind, source_key, order_key;
        """
    )


def supabase_order_items() -> dict[tuple[str, str], list[dict[str, Any]]]:
    rows = execute_sql(
        """
        select
          'mass'::text as source_kind,
          attributed_order.order_key,
          item.line_key,
          item.product_internal_id,
          item.product_external_id,
          item.product_external_system_id,
          item.display_name,
          item.quantity,
          item.quantity_type,
          item.unit_price,
          item.line_amount,
          item.status_category,
          item.status_external_id
        from public.push_attributed_order_items as item
        join public.push_attributed_orders as attributed_order
          on attributed_order.id = item.attributed_order_id
        where attributed_order.goal_id = 'all-orders'
        union all
        select
          'trigger'::text as source_kind,
          attributed_order.order_key,
          item.line_key,
          item.product_internal_id,
          item.product_external_id,
          item.product_external_system_id,
          item.display_name,
          item.quantity,
          item.quantity_type,
          item.unit_price,
          item.line_amount,
          item.status_category,
          item.status_external_id
        from public.push_trigger_attributed_order_items as item
        join public.push_trigger_attributed_orders as attributed_order
          on attributed_order.id = item.attributed_order_id
        where attributed_order.goal_id = 'all-orders'
        order by source_kind, order_key, line_key;
        """
    )
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[(str(row["source_kind"]), str(row["order_key"]))].append(
            {
                key: value
                for key, value in row.items()
                if key not in {"source_kind", "order_key"}
            }
        )
    return result


def select_published_orders(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)

    def include(row: dict[str, Any], reason: str) -> None:
        key = (str(row["source_kind"]), str(row["order_key"]))
        selected[key] = row
        reasons[key].add(reason)

    for row in rows:
        name = str(row.get("push_name") or "")
        for pattern in KNOWN_CAMPAIGN_PATTERNS:
            if pattern.casefold() in name.casefold():
                include(row, f"known_campaign:{pattern}")

    for project_id in ("05-main", "blizko-in-05", "blizko-app"):
        project_rows = [
            row for row in rows if row.get("order_project_id") == project_id
        ]
        project_rows.sort(
            key=lambda row: (
                str(row.get("purchased_at") or ""),
                str(row["source_kind"]),
                str(row["order_key"]),
            )
        )
        for row in project_rows[:20]:
            include(row, f"order_project_sample:{project_id}")

    trigger_rows = [row for row in rows if row["source_kind"] == "trigger"]
    trigger_rows.sort(
        key=lambda row: (
            str(row.get("purchased_at") or ""),
            str(row["order_key"]),
        )
    )
    for row in trigger_rows[:10]:
        include(row, "trigger_sample")

    latency_rows = sorted(
        rows,
        key=lambda row: (
            -int(row.get("latency_minutes") or 0),
            str(row["order_key"]),
        ),
    )
    for row in latency_rows[:10]:
        include(row, "closest_published_to_24h")

    result: list[dict[str, Any]] = []
    for key, row in sorted(
        selected.items(),
        key=lambda item: (
            str(item[1].get("purchased_at") or ""),
            item[0],
        ),
    ):
        result.append({**row, "selectionReasons": sorted(reasons[key])})

    counts = {
        "selected": len(result),
        "knownCampaignOrders": sum(
            any(reason.startswith("known_campaign:") for reason in row["selectionReasons"])
            for row in result
        ),
        "byOrderProject": {
            project_id: sum(
                row.get("order_project_id") == project_id for row in result
            )
            for project_id in ("05-main", "blizko-in-05", "blizko-app")
        },
        "trigger": sum(row["source_kind"] == "trigger" for row in result),
    }
    return result, counts


def build_direct_merge_map() -> tuple[dict[int, int], list[list[int]]]:
    rows = latest_rows(
        (
            row
            for row in parquet_rows(
                "CDP_MergedCustomers",
                columns=[
                    "unmergedCustomerId",
                    "mergedCustomerId",
                    "_isDeleted",
                    "_rowversion_ts",
                ],
            )
            if row.get("unmergedCustomerId") is not None
        ),
        lambda row: int(row["unmergedCustomerId"]),
    )
    direct: dict[int, int] = {}
    for row in rows:
        source = row.get("unmergedCustomerId")
        target = row.get("mergedCustomerId")
        if source is not None and target is not None:
            direct[int(source)] = int(target)

    cycles: list[list[int]] = []
    checked: set[int] = set()
    for origin in direct:
        if origin in checked:
            continue
        seen: dict[int, int] = {}
        current = origin
        path: list[int] = []
        while current in direct:
            if current in seen:
                cycles.append(path[seen[current] :])
                break
            if current in checked:
                break
            seen[current] = len(path)
            path.append(current)
            current = direct[current]
        checked.update(path)
    return direct, cycles


def make_resolver(direct: dict[int, int]):
    memo: dict[int, int] = {}

    def resolve(customer_id: int) -> int:
        if customer_id in memo:
            return memo[customer_id]
        path: list[int] = []
        positions: dict[int, int] = {}
        current = customer_id
        while current in direct and current not in memo:
            if current in positions:
                cycle = path[positions[current] :]
                canonical = min(cycle)
                for value in cycle:
                    memo[value] = canonical
                break
            positions[current] = len(path)
            path.append(current)
            current = direct[current]
        canonical = memo.get(current, current)
        for value in reversed(path):
            canonical = memo.get(value, canonical)
            memo[value] = canonical
        memo[customer_id] = canonical
        return canonical

    return resolve


def current_raw_state() -> dict[str, Any]:
    mailings = latest_rows(
        parquet_rows(
            "Mailings_Mailings",
            columns=[
                "id",
                "name",
                "type",
                "channel",
                "folderInternalId",
                "_isDeleted",
                "_rowversion_ts",
            ],
        ),
        lambda row: str(row["id"]),
    )
    mobile_mailings = {
        str(row["id"]): {
            "name": str(row.get("name") or ""),
            "type": str(row.get("type") or ""),
            "folderInternalId": str(row.get("folderInternalId") or ""),
        }
        for row in mailings
        if row.get("channel") == "MobilePush"
    }

    click_rows = latest_rows(
        parquet_rows(
            "Mailings_CustomerMessagesStatuses",
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
            filter_expression=(
                (ds.field("mailingStatusSystemName") == "Clicked")
                & (ds.field("dateTimeUtc") >= SINCE.replace(tzinfo=None))
                & (
                    ds.field("mailingInternalId").isin(
                        sorted(mobile_mailings)
                    )
                )
            ),
        ),
        lambda row: str(row["messageStatusId"]),
    )

    orders = latest_rows(
        parquet_rows(
            "ProcessingOrders_Orders",
            columns=[
                "id",
                "unmergedCustomerId",
                "firstDateTimeUtc",
                "firstPointOfContactInternalId",
                "priceWithDiscounts",
                "paidAmount",
                "_isDeleted",
                "_rowversion_ts",
            ],
            filter_expression=ds.field("firstDateTimeUtc")
            >= SINCE.replace(tzinfo=None),
        ),
        lambda row: str(row["id"]),
    )

    purchase_statuses = latest_rows(
        parquet_rows(
            "ProcessingOrders_PurchaseStatuses",
            columns=[
                "internalId",
                "categorySystemName",
                "externalId",
                "_isDeleted",
                "_rowversion_ts",
            ],
        ),
        lambda row: str(row["internalId"]),
    )
    category_by_status = {
        str(row["internalId"]): str(row.get("categorySystemName") or "")
        for row in purchase_statuses
    }
    external_by_status = {
        str(row["internalId"]): str(row.get("externalId") or "")
        for row in purchase_statuses
    }

    purchases = latest_rows(
        parquet_rows(
            "ProcessingOrders_Purchases",
            columns=[
                "orderId",
                "lineId",
                "lineNumber",
                "statusInternalId",
                "_rowversion_ts",
            ],
        ),
        lambda row: (
            str(row["orderId"]),
            str(row.get("lineId") or row.get("lineNumber")),
        ),
    )
    status_categories_by_order: dict[str, set[str]] = defaultdict(set)
    status_external_by_order: dict[str, set[str]] = defaultdict(set)
    for row in purchases:
        status_id = str(row.get("statusInternalId") or "")
        order_id = str(row["orderId"])
        category = category_by_status.get(status_id, "")
        external = external_by_status.get(status_id, "")
        if category:
            status_categories_by_order[order_id].add(category)
        if external:
            status_external_by_order[order_id].add(external)

    return {
        "mobileMailings": mobile_mailings,
        "clickRows": click_rows,
        "orders": orders,
        "statusCategoriesByOrder": status_categories_by_order,
        "statusExternalByOrder": status_external_by_order,
    }


def click_payload(
    row: dict[str, Any],
    mailing: dict[str, Any],
    hash_secret: bytes,
) -> dict[str, Any]:
    return {
        "clickedAt": utc(row["dateTimeUtc"]).isoformat(),
        "mailingId": str(row["mailingInternalId"]),
        "mailingType": mailing["type"],
        "mailingName": mailing["name"],
        "folderInternalId": mailing["folderInternalId"],
        "messageInstanceKey": secret_hash(
            hash_secret,
            "message",
            row["messageId"],
        ),
        "clickStatusKey": secret_hash(
            hash_secret,
            "click-status",
            row["messageStatusId"],
        ),
    }


def build_golden_baseline(
    hash_secret: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = supabase_order_candidates()
    selected, selection_summary = select_published_orders(candidates)
    items = supabase_order_items()

    raw = current_raw_state()
    direct, merge_cycles = build_direct_merge_map()
    resolve = make_resolver(direct)

    raw_orders_by_hash: dict[str, dict[str, Any]] = {}
    qualifying_orders: list[dict[str, Any]] = []
    for order in raw["orders"]:
        order_id = str(order["id"])
        order_key = hashlib.sha256(order_id.encode("utf-8")).hexdigest()
        raw_orders_by_hash[order_key] = order
        categories = raw["statusCategoriesByOrder"].get(order_id, set())
        if categories & {"CheckedOut", "Paid", "Delivered"}:
            qualifying_orders.append(order)

    clicks_by_customer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw["clickRows"]:
        customer = row.get("unmergedCustomerId")
        mailing_id = str(row.get("mailingInternalId") or "")
        if customer is None or mailing_id not in raw["mobileMailings"]:
            continue
        canonical = resolve(int(customer))
        clicks_by_customer[canonical].append(
            click_payload(
                row,
                raw["mobileMailings"][mailing_id],
                hash_secret,
            )
        )
    for clicks in clicks_by_customer.values():
        clicks.sort(
            key=lambda click: (
                click["clickedAt"],
                click["mailingId"],
                click["clickStatusKey"],
            )
        )

    published_traces: list[dict[str, Any]] = []
    winner_mismatches: list[dict[str, Any]] = []
    missing_raw_orders: list[str] = []
    for selected_order in selected:
        order_key = str(selected_order["order_key"])
        raw_order = raw_orders_by_hash.get(order_key)
        if raw_order is None:
            missing_raw_orders.append(order_key)
            published_traces.append(
                {
                    **selected_order,
                    "items": items.get(
                        (
                            str(selected_order["source_kind"]),
                            order_key,
                        ),
                        [],
                    ),
                    "rawTraceStatus": "missing_order_in_current_delta_cache",
                }
            )
            continue
        raw_customer = raw_order.get("unmergedCustomerId")
        canonical = resolve(int(raw_customer)) if raw_customer is not None else None
        purchased_at = utc(raw_order.get("firstDateTimeUtc"))
        all_clicks = clicks_by_customer.get(canonical, []) if canonical is not None else []
        eligible_clicks = [
            click
            for click in all_clicks
            if purchased_at - WINDOW
            <= datetime.fromisoformat(click["clickedAt"])
            <= purchased_at
        ]
        winner = eligible_clicks[-1] if eligible_clicks else None
        expected_mailing_ids = {
            str(value) for value in selected_order.get("mailing_ids") or []
        }
        winner_matches = bool(
            winner and winner["mailingId"] in expected_mailing_ids
        )
        trace = {
            **selected_order,
            "items": items.get(
                (
                    str(selected_order["source_kind"]),
                    order_key,
                ),
                [],
            ),
            "rawTraceStatus": "traced",
            "computedOrderProjectId": order_project_id(
                str(raw_order.get("firstPointOfContactInternalId") or "")
            ),
            "computedRevenue": money_value(raw_order),
            "eligibleMobilePushClicks": eligible_clicks,
            "computedWinner": winner,
            "winnerMatchesPublished": winner_matches,
        }
        published_traces.append(trace)
        if not winner_matches:
            winner_mismatches.append(
                {
                    "sourceKind": selected_order["source_kind"],
                    "sourceKey": selected_order["source_key"],
                    "orderKey": order_key,
                    "publishedClickAt": selected_order["attributed_click_at"],
                    "computedWinner": winner,
                }
            )

    diagnostic_candidates: dict[str, list[dict[str, Any]]] = {
        "transactionWinner": [],
        "massTriggerCompetition": [],
        "noPriorMobilePushClick": [],
        "lastClickOutside24h": [],
        "closestInside24h": [],
    }
    closest_inside: list[tuple[float, dict[str, Any]]] = []
    for order in sorted(
        qualifying_orders,
        key=lambda row: (
            utc(row.get("firstDateTimeUtc")) or datetime.min.replace(tzinfo=UTC),
            str(row["id"]),
        ),
    ):
        if order.get("unmergedCustomerId") is None:
            continue
        purchased_at = utc(order.get("firstDateTimeUtc"))
        if purchased_at is None:
            continue
        canonical = resolve(int(order["unmergedCustomerId"]))
        clicks = clicks_by_customer.get(canonical, [])
        timestamps = [
            datetime.fromisoformat(click["clickedAt"]) for click in clicks
        ]
        position = bisect_right(timestamps, purchased_at) - 1
        order_id = str(order["id"])
        base = {
            "orderKey": hashlib.sha256(order_id.encode("utf-8")).hexdigest(),
            "buyerKey": secret_hash(hash_secret, "customer", canonical),
            "purchasedAt": purchased_at.isoformat(),
            "orderProjectId": order_project_id(
                str(order.get("firstPointOfContactInternalId") or "")
            ),
            "revenue": money_value(order),
            "statusCategories": sorted(
                raw["statusCategoriesByOrder"].get(order_id, set())
            ),
            "statusExternalIds": sorted(
                raw["statusExternalByOrder"].get(order_id, set())
            ),
        }
        if position < 0:
            if len(diagnostic_candidates["noPriorMobilePushClick"]) < 10:
                diagnostic_candidates["noPriorMobilePushClick"].append(base)
            continue
        winner = clicks[position]
        click_at = timestamps[position]
        latency = purchased_at - click_at
        if latency > WINDOW:
            if len(diagnostic_candidates["lastClickOutside24h"]) < 10:
                diagnostic_candidates["lastClickOutside24h"].append(
                    {
                        **base,
                        "lastClick": winner,
                        "latencyMinutes": round(latency.total_seconds() / 60),
                    }
                )
            continue
        eligible = [
            click
            for click in clicks
            if purchased_at - WINDOW
            <= datetime.fromisoformat(click["clickedAt"])
            <= purchased_at
        ]
        traced = {
            **base,
            "eligibleMobilePushClicks": eligible,
            "winner": winner,
            "latencyMinutes": round(latency.total_seconds() / 60),
        }
        if (
            winner["mailingType"] == "transaction"
            and len(diagnostic_candidates["transactionWinner"]) < 10
        ):
            diagnostic_candidates["transactionWinner"].append(traced)
        eligible_types = {click["mailingType"] for click in eligible}
        if (
            {"mass", "trigger"} <= eligible_types
            and len(diagnostic_candidates["massTriggerCompetition"]) < 10
        ):
            diagnostic_candidates["massTriggerCompetition"].append(traced)
        closest_inside.append((latency.total_seconds(), traced))

        if all(len(rows) >= 10 for key, rows in diagnostic_candidates.items() if key != "closestInside24h"):
            # Continue collecting only long-latency examples for the boundary sample.
            pass

    closest_inside.sort(key=lambda item: (-item[0], item[1]["orderKey"]))
    diagnostic_candidates["closestInside24h"] = [
        row for _, row in closest_inside[:10]
    ]

    zero_order_campaigns = execute_sql(
        """
        select
          'mass'::text as source_kind,
          campaign.campaign_key as source_key,
          campaign.project_id,
          campaign.name,
          campaign.title,
          campaign.sent_at,
          campaign.sent,
          campaign.delivered,
          campaign.clicked
        from public.push_campaigns as campaign
        join public.push_campaign_goal_metrics as metric
          on metric.campaign_id = campaign.id
         and metric.goal_id = 'all-orders'
        where metric.orders = 0
        union all
        select
          'trigger'::text as source_kind,
          scenario.mindbox_scenario_id || ':' || mailing.message_key
            as source_key,
          mailing.project_id,
          mailing.name,
          mailing.title,
          mailing.first_activity_at as sent_at,
          coalesce(sum(daily.sent), 0)::bigint as sent,
          coalesce(sum(daily.delivered_estimated), 0)::bigint as delivered,
          coalesce(sum(daily.clicked), 0)::bigint as clicked
        from public.push_scenario_mailings as mailing
        join public.push_scenarios as scenario
          on scenario.id = mailing.scenario_id
        left join public.push_scenario_daily_metrics as daily
          on daily.scenario_mailing_id = mailing.id
        left join public.push_trigger_goal_metrics as metric
          on metric.scenario_mailing_id = mailing.id
         and metric.goal_id = 'all-orders'
        where not mailing.is_test
          and coalesce(metric.orders, 0) = 0
        group by
          scenario.mindbox_scenario_id,
          mailing.message_key,
          mailing.project_id,
          mailing.name,
          mailing.title,
          mailing.first_activity_at
        order by source_kind, project_id, sent_at, source_key;
        """
    )

    trigger_pushes = execute_sql(
        """
        select
          scenario.mindbox_scenario_id,
          mailing.message_key,
          mailing.project_id,
          mailing.name,
          mailing.title,
          mailing.mailing_ids,
          mailing.folder_internal_ids,
          mailing.application_names,
          mailing.first_activity_at,
          mailing.last_activity_at,
          coalesce(sum(daily.sent), 0)::bigint as sent,
          coalesce(sum(daily.delivered_estimated), 0)::bigint
            as delivered_estimated,
          coalesce(sum(daily.clicked), 0)::bigint as clicked,
          coalesce(sum(daily.not_sent), 0)::bigint as not_sent,
          coalesce(sum(daily.not_delivered), 0)::bigint as not_delivered,
          (
            select jsonb_agg(
              jsonb_build_object(
                'goalId', goal.id,
                'orders', coalesce(metric.orders, 0),
                'buyers', coalesce(metric.buyers, 0),
                'revenue', coalesce(metric.revenue, 0),
                'latency0To1h', coalesce(metric.latency_0_1h, 0),
                'latency1To4h', coalesce(metric.latency_1_4h, 0),
                'latency4To12h', coalesce(metric.latency_4_12h, 0),
                'latency12To24h', coalesce(metric.latency_12_24h, 0)
              )
              order by goal.sort_order, goal.id
            )
            from public.push_goals as goal
            left join public.push_trigger_goal_metrics as metric
              on metric.scenario_mailing_id = mailing.id
             and metric.goal_id = goal.id
            where goal.is_active
          ) as goals
        from public.push_scenario_mailings as mailing
        join public.push_scenarios as scenario
          on scenario.id = mailing.scenario_id
        left join public.push_scenario_daily_metrics as daily
          on daily.scenario_mailing_id = mailing.id
        where not mailing.is_test
        group by
          mailing.id,
          scenario.mindbox_scenario_id,
          mailing.message_key,
          mailing.project_id,
          mailing.name,
          mailing.title,
          mailing.mailing_ids,
          mailing.folder_internal_ids,
          mailing.application_names,
          mailing.first_activity_at,
          mailing.last_activity_at
        order by
          scenario.mindbox_scenario_id,
          mailing.message_key;
        """
    )

    golden = {
        "selection": selection_summary,
        "publishedAttributedOrders": published_traces,
        "diagnosticCases": diagnostic_candidates,
        "zeroOrderPushes": zero_order_campaigns,
        "triggerPushExpectations": trigger_pushes,
    }
    diagnostics = {
        "publishedCandidates": len(candidates),
        "selectedPublishedOrders": len(selected),
        "tracedPublishedOrders": sum(
            row.get("rawTraceStatus") == "traced" for row in published_traces
        ),
        "missingRawOrders": missing_raw_orders,
        "winnerMismatches": winner_mismatches,
        "mergeCycles": [
            [plain_hash("customer", value) for value in cycle]
            for cycle in merge_cycles
        ],
        "rawCounts": {
            "mobileMailings": len(raw["mobileMailings"]),
            "mobilePushClicks": len(raw["clickRows"]),
            "ordersSince": len(raw["orders"]),
            "qualifyingAllOrders": len(qualifying_orders),
        },
        "diagnosticCaseCounts": {
            key: len(value) for key, value in diagnostic_candidates.items()
        },
    }
    return golden, diagnostics


def report_markdown(
    manifest: dict[str, Any],
    supabase: dict[str, Any],
    golden_diagnostics: dict[str, Any],
) -> str:
    blockers: list[str] = []
    warnings: list[str] = []
    quality = supabase["quality"]
    for key, value in quality.items():
        if key == "rlsDisabledTables":
            if value:
                blockers.append(f"`{key}`: {value}")
        elif int(value) != 0:
            blockers.append(f"`{key}`: {value}")
    if golden_diagnostics["winnerMismatches"]:
        blockers.append(
            "Golden-трассировка не подтверждает опубликованного победителя "
            f"для {len(golden_diagnostics['winnerMismatches'])} заказов."
        )
    if golden_diagnostics["missingRawOrders"]:
        warnings.append(
            "Не найдены в текущем Delta-кэше "
            f"{len(golden_diagnostics['missingRawOrders'])} опубликованных заказов."
        )
    if golden_diagnostics["mergeCycles"]:
        blockers.append(
            "Обнаружены циклы объединения клиентов: "
            f"{len(golden_diagnostics['mergeCycles'])}."
        )

    delta_latest = max(
        (
            value.get("latestDataAt")
            for value in manifest["mindboxDelta"].values()
            if value.get("latestDataAt")
        ),
        default=None,
    )
    published_latest = supabase["summary"].get("triggerLatestActivityAt")
    if delta_latest and published_latest and str(published_latest) < str(delta_latest):
        warnings.append(
            "Delta-источник новее опубликованного аналитического снимка; "
            "baseline фиксирует текущую публикацию, а не ещё не пересчитанные события."
        )

    assessment = (
        "Needs revision"
        if blockers
        else ("Share with caveats" if warnings else "Ready to share")
    )
    lines = [
        "# Stage 0 baseline",
        "",
        f"**Captured at:** {manifest['capturedAt']}",
        "",
        f"**Git commit:** `{manifest['git']['head']}`",
        "",
        f"**Assessment:** `{assessment}`",
        "",
        "## Scope",
        "",
        "Read-only baseline текущей опубликованной аналитики, конфигурации и "
        "доступного Mindbox Delta-кэша. Исходные ID клиентов и заказов не "
        "сохраняются.",
        "",
        "## Counts",
        "",
        f"- Mass campaigns: {supabase['summary']['campaigns']}",
        f"- Mass attributed rows: {supabase['summary']['massAttributedOrders']}",
        f"- Trigger mailings: {supabase['summary']['triggerMailings']}",
        f"- Trigger attributed rows: {supabase['summary']['triggerAttributedOrders']}",
        f"- Golden published orders: {golden_diagnostics['selectedPublishedOrders']}",
        f"- Traced published orders: {golden_diagnostics['tracedPublishedOrders']}",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(
        [f"- {value}" for value in blockers]
        or ["- Блокирующих автоматических проверок не обнаружено."]
    )
    lines.extend(["", "## Caveats", ""])
    lines.extend(
        [f"- {value}" for value in warnings]
        or ["- Дополнительных caveats не зафиксировано."]
    )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `manifest.json` — Git, Delta versions и source fingerprints.",
            "- `configuration.json` — правила и config hash.",
            "- `supabase_snapshot.json` — агрегаты, схема и SQL quality checks.",
            "- `golden_traces.json` — PII-free трассировки заказов и кликов.",
            "- `golden_diagnostics.json` — полнота и расхождения трассировок.",
            "- `validation_report.md` — результат автоматических проверок.",
            "- `manual_verification.md` — ручная сверка с Mindbox UI.",
            "",
            "## Validation commands",
            "",
            "1. `python scripts/validate_stage0_baseline.py`.",
            "2. `python scripts/validate_supabase_data.py`.",
            "3. `python scripts/validate_trigger_supabase_data.py`.",
            "4. `cd dashboard && npm run lint && npm run build`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for tracked PII-free baseline artifacts",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    env = load_env()
    hash_secret_value = env.get("SHIFR_KEY") or env.get("SECRET_KEY")
    if not hash_secret_value:
        raise RuntimeError("Для PII-free baseline нужен SHIFR_KEY или SECRET_KEY")
    hash_secret = hash_secret_value.encode("utf-8")

    captured_at = datetime.now(UTC).isoformat()
    manifest = {
        "capturedAt": captured_at,
        "periodSince": SINCE.isoformat(),
        "timezone": "Europe/Moscow",
        "attribution": {
            "channel": "MobilePush",
            "mailingTypes": ["mass", "trigger", "transaction"],
            "model": "last_click",
            "windowHours": 24,
        },
        "git": capture_git(),
        "mindboxDelta": capture_delta_versions(),
        "environmentPresence": {
            key: bool(env.get(key))
            for key in (
                "URL_DATABASE",
                "SECRET_KEY",
                "SHIFR_KEY",
                "NEXT_PUBLIC_SUPABASE_URL",
                "SUPABASE_SERVICE_ROLE_KEY",
                "SUPABASE_STUDIO_USER",
                "SUPABASE_STUDIO_PASSWORD",
                "PUSH_ANALYTICS_ADMIN_KEY",
            )
        },
    }
    configuration = capture_configuration()
    supabase = capture_supabase()
    golden, golden_diagnostics = build_golden_baseline(hash_secret)

    manifest["configHash"] = configuration["configHash"]
    manifest["artifactHashes"] = {}

    write_json(output / "configuration.json", configuration)
    write_json(output / "supabase_snapshot.json", supabase)
    write_json(output / "golden_traces.json", golden)
    write_json(output / "golden_diagnostics.json", golden_diagnostics)

    for name in (
        "configuration.json",
        "supabase_snapshot.json",
        "golden_traces.json",
        "golden_diagnostics.json",
    ):
        manifest["artifactHashes"][name] = file_sha256(output / name)

    write_json(output / "manifest.json", manifest)
    (output / "README.md").write_text(
        report_markdown(manifest, supabase, golden_diagnostics),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(output),
                "capturedAt": captured_at,
                "gitCommit": manifest["git"]["head"],
                "configHash": configuration["configHash"],
                "supabaseSummary": supabase["summary"],
                "quality": supabase["quality"],
                "goldenDiagnostics": golden_diagnostics,
            },
            ensure_ascii=False,
            indent=2,
            default=json_default,
        )
    )


if __name__ == "__main__":
    main()
