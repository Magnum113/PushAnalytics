#!/usr/bin/env python3
"""Synchronize the PII-free trigger-push snapshot with self-hosted Supabase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from mindbox_delta import ROOT
from sync_supabase_pg_meta import execute_sql


DATASET = ROOT / "data" / "generated" / "trigger_dashboard.json"
DELIMITER = "$trigger_push_payload$"
BATCH_SIZE = 500


def batches(values: list[dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def payload_sql(payload: dict[str, Any], statement: str) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if DELIMITER in encoded:
        raise RuntimeError("JSON payload unexpectedly contains the SQL delimiter")
    return f"""
begin;
with payload as (
  select {DELIMITER}{encoded}{DELIMITER}::jsonb as doc
)
{statement}
commit;
"""


def sync_dimensions(dataset: dict[str, Any]) -> None:
    dimension_data = {
        "generatedAt": dataset["generatedAt"],
        "scenarios": dataset["scenarios"],
        "mailings": dataset["mailings"],
    }
    statement = """
, scenario_rows as (
  select
    scenario,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'scenarios') as rows(scenario)
)
insert into public.push_scenarios (
  mindbox_scenario_id,
  name,
  source_entity_type,
  first_activity_at,
  last_activity_at,
  is_active,
  generated_at,
  updated_at
)
select
  scenario->>'scenarioId',
  scenario->>'name',
  coalesce(scenario->>'sourceEntityType', 'Scenario'),
  nullif(scenario->>'firstActivityAt', '')::timestamptz,
  nullif(scenario->>'lastActivityAt', '')::timestamptz,
  true,
  scenario_rows.generated_at,
  now()
from scenario_rows
on conflict (mindbox_scenario_id) do update set
  name = excluded.name,
  source_entity_type = excluded.source_entity_type,
  first_activity_at = excluded.first_activity_at,
  last_activity_at = excluded.last_activity_at,
  is_active = true,
  generated_at = excluded.generated_at,
  updated_at = now();

with payload as (
  select $trigger_push_payload$%s$trigger_push_payload$::jsonb as doc
),
mailing_rows as (
  select
    mailing,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'mailings') as rows(mailing)
)
insert into public.push_scenario_mailings (
  scenario_id,
  project_id,
  message_key,
  project_assignment_source,
  project_assignment_reason,
  name,
  title,
  body,
  mailing_type,
  mailing_ids,
  folder_internal_ids,
  application_names,
  platforms,
  content_source,
  first_activity_at,
  last_activity_at,
  mindbox_created_at,
  mindbox_updated_at,
  is_test,
  generated_at,
  updated_at
)
select
  scenario.id,
  mailing->>'projectId',
  mailing->>'messageKey',
  coalesce(mailing->>'projectAssignmentSource', 'fallback'),
  mailing->>'projectAssignmentReason',
  mailing->>'name',
  coalesce(mailing->>'title', ''),
  coalesce(mailing->>'body', ''),
  'trigger',
  array(select jsonb_array_elements_text(coalesce(mailing->'mailingIds', '[]'))),
  array(select jsonb_array_elements_text(coalesce(mailing->'folderInternalIds', '[]'))),
  array(select jsonb_array_elements_text(coalesce(mailing->'applications', '[]'))),
  array(select jsonb_array_elements_text(coalesce(mailing->'platforms', '[]'))),
  coalesce(mailing->>'contentSource', 'inferred'),
  nullif(mailing->>'firstActivityAt', '')::timestamptz,
  nullif(mailing->>'lastActivityAt', '')::timestamptz,
  nullif(mailing->>'mindboxCreatedAt', '')::timestamptz,
  nullif(mailing->>'mindboxUpdatedAt', '')::timestamptz,
  coalesce((mailing->>'isTest')::boolean, false),
  mailing_rows.generated_at,
  now()
from mailing_rows
join public.push_scenarios as scenario
  on scenario.mindbox_scenario_id = mailing->>'scenarioId'
on conflict (scenario_id, message_key) do update set
  project_id = excluded.project_id,
  project_assignment_source = excluded.project_assignment_source,
  project_assignment_reason = excluded.project_assignment_reason,
  name = excluded.name,
  title = excluded.title,
  body = excluded.body,
  mailing_ids = excluded.mailing_ids,
  folder_internal_ids = excluded.folder_internal_ids,
  application_names = excluded.application_names,
  platforms = excluded.platforms,
  content_source = excluded.content_source,
  first_activity_at = excluded.first_activity_at,
  last_activity_at = excluded.last_activity_at,
  mindbox_created_at = excluded.mindbox_created_at,
  mindbox_updated_at = excluded.mindbox_updated_at,
  is_test = excluded.is_test,
  generated_at = excluded.generated_at,
  updated_at = now();
"""
    encoded = json.dumps(
        dimension_data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    execute_sql(payload_sql(dimension_data, statement % encoded))


def sync_daily_metrics(dataset: dict[str, Any]) -> None:
    for rows in batches(dataset["dailyMetrics"]):
        execute_sql(
            payload_sql(
                {"generatedAt": dataset["generatedAt"], "rows": rows},
                """
, metric_rows as (
  select
    metric,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'rows') as rows(metric)
)
insert into public.push_scenario_daily_metrics (
  scenario_mailing_id,
  metric_date,
  participants,
  unique_recipients,
  sent,
  delivered_estimated,
  clicked,
  not_sent,
  not_delivered,
  not_sent_reasons,
  not_delivered_reasons,
  generated_at,
  updated_at
)
select
  mailing.id,
  (metric->>'date')::date,
  (metric->>'participants')::bigint,
  (metric->>'uniqueRecipients')::bigint,
  (metric->>'sent')::bigint,
  (metric->>'deliveredEstimated')::bigint,
  (metric->>'clicked')::bigint,
  (metric->>'notSent')::bigint,
  (metric->>'notDelivered')::bigint,
  coalesce(metric->'notSentReasons', '{}'::jsonb),
  coalesce(metric->'notDeliveredReasons', '{}'::jsonb),
  metric_rows.generated_at,
  now()
from metric_rows
join public.push_scenarios as scenario
  on scenario.mindbox_scenario_id = metric->>'scenarioId'
join public.push_scenario_mailings as mailing
  on mailing.scenario_id = scenario.id
 and mailing.message_key = metric->>'messageKey'
on conflict (scenario_mailing_id, metric_date) do update set
  participants = excluded.participants,
  unique_recipients = excluded.unique_recipients,
  sent = excluded.sent,
  delivered_estimated = excluded.delivered_estimated,
  clicked = excluded.clicked,
  not_sent = excluded.not_sent,
  not_delivered = excluded.not_delivered,
  not_sent_reasons = excluded.not_sent_reasons,
  not_delivered_reasons = excluded.not_delivered_reasons,
  generated_at = excluded.generated_at,
  updated_at = now();
""",
            )
        )


def sync_touchpoints(dataset: dict[str, Any]) -> None:
    for rows in batches(dataset["touchpoints"]):
        execute_sql(
            payload_sql(
                {"generatedAt": dataset["generatedAt"], "rows": rows},
                """
, touchpoint_rows as (
  select
    touchpoint,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'rows') as rows(touchpoint)
)
insert into public.push_click_touchpoints (
  touchpoint_key,
  source_kind,
  campaign_id,
  scenario_mailing_id,
  project_id,
  mailing_internal_id,
  message_instance_key,
  buyer_key,
  clicked_at,
  generated_at,
  updated_at
)
select
  touchpoint->>'touchpointKey',
  touchpoint->>'sourceKind',
  case when touchpoint->>'sourceKind' = 'mass' then campaign.id end,
  case when touchpoint->>'sourceKind' = 'trigger' then mailing.id end,
  touchpoint->>'projectId',
  touchpoint->>'mailingId',
  touchpoint->>'messageInstanceKey',
  touchpoint->>'buyerKey',
  (touchpoint->>'clickedAt')::timestamptz,
  touchpoint_rows.generated_at,
  now()
from touchpoint_rows
left join public.push_campaigns as campaign
  on touchpoint->>'sourceKind' = 'mass'
 and campaign.campaign_key = touchpoint->>'sourceKey'
left join public.push_scenarios as scenario
  on touchpoint->>'sourceKind' = 'trigger'
 and scenario.mindbox_scenario_id = touchpoint->>'scenarioId'
left join public.push_scenario_mailings as mailing
  on mailing.scenario_id = scenario.id
 and mailing.message_key = touchpoint->>'sourceKey'
on conflict (touchpoint_key) do update set
  source_kind = excluded.source_kind,
  campaign_id = excluded.campaign_id,
  scenario_mailing_id = excluded.scenario_mailing_id,
  project_id = excluded.project_id,
  mailing_internal_id = excluded.mailing_internal_id,
  message_instance_key = excluded.message_instance_key,
  buyer_key = excluded.buyer_key,
  clicked_at = excluded.clicked_at,
  generated_at = excluded.generated_at,
  updated_at = now();
""",
            )
        )


def sync_orders(dataset: dict[str, Any]) -> None:
    for rows in batches(dataset["attributedOrders"], 100):
        execute_sql(
            payload_sql(
                {"generatedAt": dataset["generatedAt"], "rows": rows},
                """
, order_rows as (
  select
    attributed_order,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'rows') as rows(attributed_order)
)
insert into public.push_trigger_attributed_orders (
  scenario_mailing_id,
  touchpoint_id,
  goal_id,
  order_project_id,
  order_key,
  buyer_key,
  purchased_at,
  attributed_click_at,
  latency_minutes,
  revenue,
  first_point_of_contact_id,
  status_categories,
  status_external_ids,
  generated_at,
  updated_at
)
select
  mailing.id,
  touchpoint.id,
  attributed_order->>'goalId',
  attributed_order->>'orderProjectId',
  attributed_order->>'orderKey',
  attributed_order->>'buyerKey',
  (attributed_order->>'purchasedAt')::timestamptz,
  (attributed_order->>'attributedClickAt')::timestamptz,
  (attributed_order->>'latencyMinutes')::integer,
  (attributed_order->>'revenue')::numeric(16, 2),
  attributed_order->>'firstPointOfContactId',
  array(select jsonb_array_elements_text(coalesce(attributed_order->'statusCategories', '[]'))),
  array(select jsonb_array_elements_text(coalesce(attributed_order->'statusExternalIds', '[]'))),
  order_rows.generated_at,
  now()
from order_rows
join public.push_scenarios as scenario
  on scenario.mindbox_scenario_id = attributed_order->>'scenarioId'
join public.push_scenario_mailings as mailing
  on mailing.scenario_id = scenario.id
 and mailing.message_key = attributed_order->>'messageKey'
join public.push_click_touchpoints as touchpoint
  on touchpoint.touchpoint_key = attributed_order->>'touchpointKey'
on conflict (goal_id, order_key) do update set
  scenario_mailing_id = excluded.scenario_mailing_id,
  touchpoint_id = excluded.touchpoint_id,
  order_project_id = excluded.order_project_id,
  buyer_key = excluded.buyer_key,
  purchased_at = excluded.purchased_at,
  attributed_click_at = excluded.attributed_click_at,
  latency_minutes = excluded.latency_minutes,
  revenue = excluded.revenue,
  first_point_of_contact_id = excluded.first_point_of_contact_id,
  status_categories = excluded.status_categories,
  status_external_ids = excluded.status_external_ids,
  generated_at = excluded.generated_at,
  updated_at = now();

with payload as (
  select $trigger_push_payload$%s$trigger_push_payload$::jsonb as doc
),
item_rows as (
  select
    attributed_order,
    item,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'rows') as rows(attributed_order)
  cross join lateral jsonb_array_elements(
    coalesce(attributed_order->'items', '[]'::jsonb)
  ) as items(item)
)
insert into public.push_trigger_attributed_order_items (
  attributed_order_id,
  line_key,
  product_internal_id,
  product_external_id,
  product_external_system_id,
  display_name,
  quantity,
  quantity_type,
  unit_price,
  line_amount,
  status_internal_id,
  status_category,
  status_external_id,
  generated_at,
  updated_at
)
select
  attributed_order_row.id,
  item->>'lineKey',
  item->>'productInternalId',
  item->>'productExternalId',
  item->>'productExternalSystemId',
  item->>'displayName',
  (item->>'quantity')::numeric(14, 3),
  item->>'quantityType',
  nullif(item->>'unitPrice', '')::numeric(16, 2),
  nullif(item->>'lineAmount', '')::numeric(16, 2),
  item->>'statusInternalId',
  item->>'statusCategory',
  item->>'statusExternalId',
  item_rows.generated_at,
  now()
from item_rows
join public.push_trigger_attributed_orders as attributed_order_row
  on attributed_order_row.goal_id = attributed_order->>'goalId'
 and attributed_order_row.order_key = attributed_order->>'orderKey'
on conflict (attributed_order_id, line_key) do update set
  product_internal_id = excluded.product_internal_id,
  product_external_id = excluded.product_external_id,
  product_external_system_id = excluded.product_external_system_id,
  display_name = excluded.display_name,
  quantity = excluded.quantity,
  quantity_type = excluded.quantity_type,
  unit_price = excluded.unit_price,
  line_amount = excluded.line_amount,
  status_internal_id = excluded.status_internal_id,
  status_category = excluded.status_category,
  status_external_id = excluded.status_external_id,
  generated_at = excluded.generated_at,
  updated_at = now();
""" % json.dumps(
                    {"generatedAt": dataset["generatedAt"], "rows": rows},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )


def finalize(dataset: dict[str, Any]) -> None:
    marker = dataset["generatedAt"].replace("'", "''")
    execute_sql(
        f"""
begin;
delete from public.push_trigger_attributed_order_items
where generated_at < '{marker}'::timestamptz;
delete from public.push_trigger_attributed_orders
where generated_at < '{marker}'::timestamptz;
delete from public.push_click_touchpoints
where source_kind = 'trigger'
  and generated_at < '{marker}'::timestamptz;
delete from public.push_scenario_daily_metrics
where generated_at < '{marker}'::timestamptz;
delete from public.push_scenario_mailings
where generated_at < '{marker}'::timestamptz;
update public.push_scenarios
set is_active = false, updated_at = now()
where generated_at < '{marker}'::timestamptz;
insert into public.push_sync_runs (
  source,
  status,
  started_at,
  finished_at,
  generated_at,
  campaigns_upserted,
  metadata
)
values (
  'mindbox-trigger',
  'succeeded',
  now(),
  now(),
  '{marker}'::timestamptz,
  {len(dataset["mailings"])},
  jsonb_build_object(
    'scenarios', {len(dataset["scenarios"])},
    'dailyMetrics', {len(dataset["dailyMetrics"])},
    'attributedOrders', {len(dataset["attributedOrders"])},
    'touchpoints', {len(dataset["touchpoints"])},
    'mailingType', 'trigger',
    'attribution', 'global-mobile-push-last-click-24h'
  )
);
commit;
"""
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    if any(row.get("mailingType") != "trigger" for row in dataset["mailings"]):
        raise RuntimeError("В наборе есть рассылка не типа trigger")
    summary = {
        "scenarios": len(dataset["scenarios"]),
        "mailings": len(dataset["mailings"]),
        "dailyMetrics": len(dataset["dailyMetrics"]),
        "touchpoints": len(dataset["touchpoints"]),
        "attributedOrders": len(dataset["attributedOrders"]),
        "generatedAt": dataset["generatedAt"],
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    sync_dimensions(dataset)
    sync_daily_metrics(dataset)
    sync_touchpoints(dataset)
    sync_orders(dataset)
    finalize(dataset)
    print(json.dumps({**summary, "status": "succeeded"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
