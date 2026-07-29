#!/usr/bin/env python3
"""Validate trigger-push analytics invariants in Supabase."""

from __future__ import annotations

import json

from sync_supabase_pg_meta import execute_sql


QUERY = """
select jsonb_build_object(
  'activeScenarios', (
    select count(*) from public.push_scenarios where is_active
  ),
  'triggerMailings', (
    select count(*) from public.push_scenario_mailings where not is_test
  ),
  'nonTriggerMailings', (
    select count(*) from public.push_scenario_mailings
    where mailing_type <> 'trigger'
  ),
  'dailyMetrics', (
    select count(*) from public.push_scenario_daily_metrics
  ),
  'invalidDailyMetrics', (
    select count(*) from public.push_scenario_daily_metrics
    where clicked > sent
       or delivered_estimated > sent
       or not_delivered > sent
       or unique_recipients > participants
  ),
  'attributedOrders', (
    select count(*) from public.push_trigger_attributed_orders
  ),
  'uniqueAllOrderBuyers', (
    select count(distinct buyer_key)
    from public.push_trigger_attributed_orders
    where goal_id = 'all-orders'
  ),
  'allOrders', (
    select count(*)
    from public.push_trigger_attributed_orders
    where goal_id = 'all-orders'
  ),
  'ordersOutsideWindow', (
    select count(*) from public.push_trigger_attributed_orders
    where latency_minutes not between 0 and 1440
       or purchased_at < attributed_click_at
  ),
  'duplicateGoalOrders', (
    select count(*)
    from (
      select goal_id, order_key
      from public.push_trigger_attributed_orders
      group by goal_id, order_key
      having count(*) > 1
    ) as duplicates
  ),
  'orderItems', (
    select count(*) from public.push_trigger_attributed_order_items
  ),
  'orphanOrderItems', (
    select count(*)
    from public.push_trigger_attributed_order_items as item
    left join public.push_trigger_attributed_orders as attributed_order
      on attributed_order.id = item.attributed_order_id
    where attributed_order.id is null
  ),
  'rlsEnabled', (
    select bool_and(relrowsecurity)
    from pg_class
    where oid in (
      'public.push_scenarios'::regclass,
      'public.push_scenario_mailings'::regclass,
      'public.push_scenario_daily_metrics'::regclass,
      'public.push_click_touchpoints'::regclass,
      'public.push_trigger_attributed_orders'::regclass,
      'public.push_trigger_attributed_order_items'::regclass
    )
  )
) as validation;
"""


def main() -> None:
    rows = execute_sql(QUERY)
    validation = rows[0]["validation"]
    failures = {
        key: validation[key]
        for key in (
            "nonTriggerMailings",
            "invalidDailyMetrics",
            "ordersOutsideWindow",
            "duplicateGoalOrders",
            "orphanOrderItems",
        )
        if validation[key] != 0
    }
    if not validation["rlsEnabled"]:
        failures["rlsEnabled"] = False
    print(
        json.dumps(
            {
                **validation,
                "status": "failed" if failures else "passed",
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
