#!/usr/bin/env python3
"""Upsert the PII-free dashboard aggregate through self-hosted Studio pg-meta.

This admin-only transport is intended for local development and manual syncs.
Studio credentials must remain in PushAnalytics/.env and must never be exposed
to the dashboard client.
"""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import certifi

from mindbox_delta import ROOT, load_env


DATASET = ROOT / "dashboard" / "public" / "data" / "dashboard.json"
PROJECT_RULES = ROOT / "data" / "project_rules.json"
PUSH_CONTENT = ROOT / "data" / "push_content.json"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
JSON_DELIMITER = "$push_analytics_payload$"
MAX_PAYLOAD_BYTES = 650_000


def build_upsert_sql(dataset: dict[str, Any]) -> str:
    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":"))
    if JSON_DELIMITER in payload:
        raise RuntimeError("JSON payload unexpectedly contains the SQL delimiter")

    return f"""
begin;

create temporary table push_analytics_payload (
  doc jsonb not null
) on commit drop;

insert into push_analytics_payload (doc)
values ({JSON_DELIMITER}{payload}{JSON_DELIMITER}::jsonb);

with payload as (
  select doc from push_analytics_payload
),
campaign_rows as (
  select
    push,
    doc
  from payload
  cross join lateral jsonb_array_elements(doc->'pushes') as items(push)
)
insert into public.push_campaigns (
  campaign_key,
  project_id,
  project_assignment_source,
  project_assignment_reason,
  name,
  title,
  body,
  sent_at,
  attribution_status,
  attribution_window_hours,
  attribution_model,
  source,
  mailing_ids,
  folder_internal_ids,
  application_names,
  sent,
  delivered,
  clicked,
  not_delivered,
  platform_ios,
  platform_android,
  platform_unknown,
  generated_at,
  updated_at
)
select
  push->>'id',
  push->>'projectId',
  coalesce(push->'projectAssignment'->>'source', 'fallback'),
  push->'projectAssignment'->>'reason',
  push->>'name',
  coalesce(push->>'title', ''),
  coalesce(push->>'body', ''),
  (push->>'sentAt')::timestamptz,
  push->>'status',
  (doc->'attribution'->>'windowHours')::smallint,
  'last_click',
  doc->>'source',
  coalesce(
    (
      select array_agg(value)
      from jsonb_array_elements_text(
        coalesce(push->'mailingIds', '[]'::jsonb)
      ) as mailing(value)
    ),
    '{{}}'::text[]
  ),
  coalesce(
    (
      select array_agg(value)
      from jsonb_array_elements_text(
        coalesce(push->'folderInternalIds', '[]'::jsonb)
      ) as folder(value)
    ),
    '{{}}'::text[]
  ),
  coalesce(
    (
      select array_agg(value)
      from jsonb_array_elements_text(
        coalesce(push->'applications', '[]'::jsonb)
      ) as application(value)
    ),
    '{{}}'::text[]
  ),
  (push->>'sent')::bigint,
  (push->>'delivered')::bigint,
  (push->>'clicked')::bigint,
  (push->>'notDelivered')::bigint,
  (push->'platforms'->>'ios')::bigint,
  (push->'platforms'->>'android')::bigint,
  (push->'platforms'->>'unknown')::bigint,
  (doc->>'generatedAt')::timestamptz,
  now()
from campaign_rows
on conflict (campaign_key) do update
set
  project_id = excluded.project_id,
  project_assignment_source = excluded.project_assignment_source,
  project_assignment_reason = excluded.project_assignment_reason,
  name = excluded.name,
  title = excluded.title,
  body = excluded.body,
  sent_at = excluded.sent_at,
  attribution_status = excluded.attribution_status,
  attribution_window_hours = excluded.attribution_window_hours,
  attribution_model = excluded.attribution_model,
  source = excluded.source,
  mailing_ids = excluded.mailing_ids,
  folder_internal_ids = excluded.folder_internal_ids,
  application_names = excluded.application_names,
  sent = excluded.sent,
  delivered = excluded.delivered,
  clicked = excluded.clicked,
  not_delivered = excluded.not_delivered,
  platform_ios = excluded.platform_ios,
  platform_android = excluded.platform_android,
  platform_unknown = excluded.platform_unknown,
  generated_at = excluded.generated_at,
  updated_at = now();

with payload as (
  select doc from push_analytics_payload
),
goal_rows as (
  select
    push->>'id' as campaign_key,
    goal.key as goal_id,
    goal.value as metric,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'pushes') as items(push)
  cross join lateral jsonb_each(push->'goals') as goal(key, value)
)
insert into public.push_campaign_goal_metrics (
  campaign_id,
  goal_id,
  orders,
  buyers,
  revenue,
  latency_0_1h,
  latency_1_4h,
  latency_4_12h,
  latency_12_24h,
  generated_at,
  updated_at
)
select
  campaign.id,
  goal_rows.goal_id,
  (goal_rows.metric->>'orders')::bigint,
  (goal_rows.metric->>'buyers')::bigint,
  (goal_rows.metric->>'revenue')::numeric(16, 2),
  (goal_rows.metric->'latency'->>0)::bigint,
  (goal_rows.metric->'latency'->>1)::bigint,
  (goal_rows.metric->'latency'->>2)::bigint,
  (goal_rows.metric->'latency'->>3)::bigint,
  goal_rows.generated_at,
  now()
from goal_rows
join public.push_campaigns as campaign
  on campaign.campaign_key = goal_rows.campaign_key
on conflict (campaign_id, goal_id) do update
set
  orders = excluded.orders,
  buyers = excluded.buyers,
  revenue = excluded.revenue,
  latency_0_1h = excluded.latency_0_1h,
  latency_1_4h = excluded.latency_1_4h,
  latency_4_12h = excluded.latency_4_12h,
  latency_12_24h = excluded.latency_12_24h,
  generated_at = excluded.generated_at,
  updated_at = now();

with payload as (
  select doc from push_analytics_payload
),
campaign_keys as (
  select push->>'id' as campaign_key
  from payload
  cross join lateral jsonb_array_elements(doc->'pushes') as items(push)
)
delete from public.push_attributed_orders as attributed_order
using public.push_campaigns as campaign, campaign_keys
where attributed_order.campaign_id = campaign.id
  and campaign.campaign_key = campaign_keys.campaign_key;

with payload as (
  select doc from push_analytics_payload
),
order_rows as (
  select
    push->>'id' as campaign_key,
    goal.key as goal_id,
    attributed_order.value as attributed_order,
    (doc->>'generatedAt')::timestamptz as generated_at
  from payload
  cross join lateral jsonb_array_elements(doc->'pushes') as items(push)
  cross join lateral jsonb_each(
    coalesce(push->'attributedOrders', '{{}}'::jsonb)
  ) as goal(key, value)
  cross join lateral jsonb_array_elements(goal.value)
    as attributed_order(value)
)
insert into public.push_attributed_orders (
  campaign_id,
  goal_id,
  order_key,
  buyer_key,
  purchased_at,
  attributed_click_at,
  latency_minutes,
  revenue,
  first_point_of_contact_id,
  order_project_id,
  status_categories,
  status_external_ids,
  generated_at,
  updated_at
)
select
  campaign.id,
  order_rows.goal_id,
  order_rows.attributed_order->>'orderKey',
  order_rows.attributed_order->>'buyerKey',
  (order_rows.attributed_order->>'purchasedAt')::timestamptz,
  (order_rows.attributed_order->>'attributedClickAt')::timestamptz,
  (order_rows.attributed_order->>'latencyMinutes')::integer,
  (order_rows.attributed_order->>'revenue')::numeric(16, 2),
  nullif(order_rows.attributed_order->>'firstPointOfContactId', ''),
  order_rows.attributed_order->>'orderProjectId',
  coalesce(
    (
      select array_agg(value)
      from jsonb_array_elements_text(
        coalesce(
          order_rows.attributed_order->'statusCategories',
          '[]'::jsonb
        )
      ) as category(value)
    ),
    '{{}}'::text[]
  ),
  coalesce(
    (
      select array_agg(value)
      from jsonb_array_elements_text(
        coalesce(
          order_rows.attributed_order->'statusExternalIds',
          '[]'::jsonb
        )
      ) as external_status(value)
    ),
    '{{}}'::text[]
  ),
  order_rows.generated_at,
  now()
from order_rows
join public.push_campaigns as campaign
  on campaign.campaign_key = order_rows.campaign_key;

with payload as (
  select doc from push_analytics_payload
),
item_rows as (
  select
    push->>'id' as campaign_key,
    goal.key as goal_id,
    attributed_order.value->>'orderKey' as order_key,
    item.value as item
  from payload
  cross join lateral jsonb_array_elements(doc->'pushes') as items(push)
  cross join lateral jsonb_each(
    coalesce(push->'attributedOrders', '{{}}'::jsonb)
  ) as goal(key, value)
  cross join lateral jsonb_array_elements(goal.value)
    as attributed_order(value)
  cross join lateral jsonb_array_elements(
    coalesce(attributed_order.value->'items', '[]'::jsonb)
  ) as item(value)
)
insert into public.push_attributed_order_items (
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
  updated_at
)
select
  attributed_order.id,
  item_rows.item->>'lineKey',
  nullif(item_rows.item->>'productInternalId', ''),
  nullif(item_rows.item->>'productExternalId', ''),
  nullif(item_rows.item->>'productExternalSystemId', ''),
  coalesce(
    (
      select product.name
      from public.push_products as product
      where product.product_internal_id =
        nullif(item_rows.item->>'productInternalId', '')
    ),
    item_rows.item->>'displayName'
  ),
  (item_rows.item->>'quantity')::numeric(14, 3),
  nullif(item_rows.item->>'quantityType', ''),
  nullif(item_rows.item->>'unitPrice', '')::numeric(16, 2),
  nullif(item_rows.item->>'lineAmount', '')::numeric(16, 2),
  nullif(item_rows.item->>'statusInternalId', ''),
  nullif(item_rows.item->>'statusCategory', ''),
  nullif(item_rows.item->>'statusExternalId', ''),
  now()
from item_rows
join public.push_campaigns as campaign
  on campaign.campaign_key = item_rows.campaign_key
join public.push_attributed_orders as attributed_order
  on attributed_order.campaign_id = campaign.id
  and attributed_order.goal_id = item_rows.goal_id
  and attributed_order.order_key = item_rows.order_key;

commit;
"""


def split_dataset(
    dataset: dict[str, Any],
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    shared = {key: value for key, value in dataset.items() if key != "pushes"}
    for push in dataset["pushes"]:
        candidate = {**shared, "pushes": [*current, push]}
        payload_size = len(
            json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if current and payload_size > max_payload_bytes:
            chunks.append({**shared, "pushes": current})
            current = [push]
        else:
            current.append(push)
    if current:
        chunks.append({**shared, "pushes": current})
    return chunks


def build_finalize_sql(dataset: dict[str, Any]) -> str:
    project_config = json.loads(PROJECT_RULES.read_text(encoding="utf-8"))
    push_content = json.loads(PUSH_CONTENT.read_text(encoding="utf-8"))
    summary = {
        "generatedAt": dataset["generatedAt"],
        "campaigns": [
            {"id": push["id"], "sentAt": push["sentAt"]}
            for push in dataset["pushes"]
        ],
        "projectRules": [
            {
                "projectId": project_id,
                "matchField": "mailing_internal_id",
                "matchValue": mailing_id,
                "notes": (
                    f"{push_content.get(mailing_id, {}).get('application', 'Приложение')}; "
                    "проверено в Mindbox 2026-07-24."
                ),
            }
            for mailing_id, project_id in project_config.get(
                "mailingOverrides", {}
            ).items()
        ],
    }
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    campaigns = len(dataset["pushes"])
    goal_metrics = sum(len(push["goals"]) for push in dataset["pushes"])
    attributed_orders = sum(
        len(orders)
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
    )
    attributed_order_items = sum(
        len(order.get("items", []))
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
        for order in orders
    )
    return f"""
begin;

create temporary table push_analytics_finalize (
  doc jsonb not null
) on commit drop;

insert into push_analytics_finalize (doc)
values ({JSON_DELIMITER}{payload}{JSON_DELIMITER}::jsonb);

with payload_campaigns as (
  select
    campaign->>'id' as campaign_key,
    (campaign->>'sentAt')::timestamptz as sent_at
  from push_analytics_finalize
  cross join lateral jsonb_array_elements(doc->'campaigns') as items(campaign)
),
payload_range as (
  select min(sent_at) as min_sent_at, max(sent_at) as max_sent_at
  from payload_campaigns
)
delete from public.push_campaigns as campaign
using payload_range
where campaign.source = 'mindbox'
  and campaign.sent_at between payload_range.min_sent_at and payload_range.max_sent_at
  and not exists (
    select 1
    from payload_campaigns
    where payload_campaigns.campaign_key = campaign.campaign_key
  );

with project_rules as (
  select rule
  from push_analytics_finalize
  cross join lateral jsonb_array_elements(doc->'projectRules') as items(rule)
)
insert into public.push_project_rules (
  project_id,
  match_field,
  match_value,
  priority,
  notes,
  is_active,
  updated_at
)
select
  rule->>'projectId',
  rule->>'matchField',
  rule->>'matchValue',
  10,
  rule->>'notes',
  true,
  now()
from project_rules
on conflict (match_field, match_value) do update
set
  project_id = excluded.project_id,
  priority = excluded.priority,
  notes = excluded.notes,
  is_active = true,
  updated_at = now();

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
  'mindbox',
  'succeeded',
  now(),
  now(),
  (
    select (doc->>'generatedAt')::timestamptz
    from push_analytics_finalize
  ),
  {campaigns},
  jsonb_build_object(
    'goalMetricsUpserted', {goal_metrics},
    'attributedOrdersUpserted', {attributed_orders},
    'attributedOrderItemsUpserted', {attributed_order_items},
    'transport', 'pg-meta-chunked'
  )
);

commit;
"""


def execute_sql(sql: str) -> Any:
    env = load_env()
    base_url = env.get("VITE_SUPABASE_URL", "").strip().rstrip("/")
    studio_user = env.get("SUPABASE_STUDIO_USER", "").strip()
    studio_password = env.get("SUPABASE_STUDIO_PASSWORD", "").strip()
    if not base_url or not studio_user or not studio_password:
        raise RuntimeError(
            "В PushAnalytics/.env нужны VITE_SUPABASE_URL, "
            "SUPABASE_STUDIO_USER и SUPABASE_STUDIO_PASSWORD"
        )

    credentials = base64.b64encode(
        f"{studio_user}:{studio_password}".encode("utf-8")
    ).decode("ascii")
    request = urllib.request.Request(
        f"{base_url}/api/platform/pg-meta/default/query",
        data=json.dumps({"query": sql}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PushAnalytics/0.2",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=120,
            context=SSL_CONTEXT,
        ) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(
            f"Supabase pg-meta: HTTP {error.code}: {body}"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверить payload без записи в Supabase",
    )
    args = parser.parse_args()

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    campaigns = len(dataset["pushes"])
    goal_metrics = sum(len(push["goals"]) for push in dataset["pushes"])
    attributed_orders = sum(
        len(orders)
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
    )
    attributed_order_items = sum(
        len(order.get("items", []))
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
        for order in orders
    )
    chunks = split_dataset(dataset)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "campaigns": campaigns,
                    "goalMetrics": goal_metrics,
                    "attributedOrders": attributed_orders,
                    "attributedOrderItems": attributed_order_items,
                    "chunks": len(chunks),
                    "largestChunkBytes": max(
                        len(
                            json.dumps(
                                chunk,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                        for chunk in chunks
                    ),
                    "containsCustomerIdentifiers": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    for chunk in chunks:
        execute_sql(build_upsert_sql(chunk))
    execute_sql(build_finalize_sql(dataset))
    print(
        json.dumps(
            {
                "campaignsUpserted": campaigns,
                "goalMetricsUpserted": goal_metrics,
                "attributedOrdersUpserted": attributed_orders,
                "attributedOrderItemsUpserted": attributed_order_items,
                "chunks": len(chunks),
                "transport": "pg-meta-chunked",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
