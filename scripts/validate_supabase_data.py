#!/usr/bin/env python3
"""Validate the synced Push Analytics dataset in Supabase."""

from __future__ import annotations

import json
from pathlib import Path

from sync_supabase_pg_meta import execute_sql

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project_rules = json.loads(
        (ROOT / "data" / "project_rules.json").read_text(encoding="utf-8")
    )
    expected_project_rules = len(project_rules.get("mailingOverrides", {}))
    by_month = execute_sql(
        """
        select
          to_char(sent_at at time zone 'Europe/Moscow', 'YYYY-MM') as month,
          project_id,
          count(*)::int as campaigns,
          sum(sent)::bigint as sent,
          sum(clicked)::bigint as clicked
        from public.push_campaigns
        group by 1, 2
        order by 1, 2;
        """
    )
    checks = execute_sql(
        """
        with actual as (
          select
            campaign_id,
            goal_id,
            count(*)::bigint as orders,
            count(distinct buyer_key)::bigint as buyers,
            round(coalesce(sum(revenue), 0))::numeric as revenue
          from public.push_attributed_orders
          group by 1, 2
        ),
        checks as (
          select
            (select count(*) from public.push_campaigns) as campaigns,
            (
              select count(*)
              from public.push_campaign_goal_metrics
            ) as metrics,
            (
              select count(*)
              from public.push_attributed_orders
            ) as attributed_orders,
            (
              select count(*)
              from public.push_attributed_order_items
            ) as items,
            (select count(*) from public.push_products) as products,
            (
              select count(*)
              from public.push_project_rules
              where is_active
                and match_field = 'mailing_internal_id'
            ) as active_project_rules,
            (
              select count(*)
              from public.push_campaigns
              where title = '' or cardinality(application_names) = 0
            ) as missing_content,
            (
              select count(*)
              from public.push_campaigns
              where delivered <> sent - not_delivered
                 or platform_ios + platform_android + platform_unknown
                    <> delivered
                 or clicked > sent
            ) as bad_delivery,
            (
              select count(*)
              from public.push_campaigns
              where (
                project_id = 'blizko-app'
                and not application_names::text ilike '%Blizko%'
              )
              or (
                project_id in ('05-main', 'blizko-in-05')
                and not application_names::text ilike '%05ru%'
              )
            ) as bad_project_app,
            (
              select count(*)
              from (
                select campaign_id
                from public.push_campaign_goal_metrics
                group by campaign_id
                having count(*) <> 4
              ) as invalid
            ) as bad_metric_cardinality,
            (
              select count(*)
              from public.push_attributed_orders
              where latency_minutes < 0
                 or latency_minutes > 1440
                 or attributed_click_at > purchased_at
            ) as bad_attribution_window,
            (
              select count(*)
              from public.push_attributed_orders as attributed_order
              left join public.push_order_project_points as point
                on point.point_id =
                  attributed_order.first_point_of_contact_id
              where attributed_order.order_project_id is null
                 or point.project_id is null
                 or attributed_order.order_project_id <> point.project_id
            ) as bad_order_project_assignment,
            (
              select count(*)
              from public.push_campaign_goal_metrics as metric
              left join actual
                using (campaign_id, goal_id)
              where metric.orders <> coalesce(actual.orders, 0)
                 or metric.buyers <> coalesce(actual.buyers, 0)
                 or metric.revenue <> coalesce(actual.revenue, 0)
            ) as bad_metric_order_totals,
            (
              select count(*)
              from public.push_campaign_goal_order_project_metrics as metric
              full join (
                select
                  campaign_id,
                  goal_id,
                  order_project_id,
                  count(*)::bigint as orders,
                  count(distinct buyer_key)::bigint as buyers,
                  round(coalesce(sum(revenue), 0), 2)::numeric(16, 2)
                    as revenue
                from public.push_attributed_orders
                group by 1, 2, 3
              ) as actual
                using (campaign_id, goal_id, order_project_id)
              where metric.campaign_id is null
                 or actual.campaign_id is null
                 or metric.orders <> actual.orders
                 or metric.buyers <> actual.buyers
                 or metric.revenue <> actual.revenue
            ) as bad_order_project_metric_totals
        )
        select * from checks;
        """
    )
    by_goal = execute_sql(
        """
        select
          goal.id as goal_id,
          count(attributed_order.id)::int as attributed_rows,
          count(distinct attributed_order.buyer_key)::int as buyers,
          coalesce(sum(attributed_order.revenue), 0)::numeric(16, 2)
            as revenue
        from public.push_goals as goal
        left join public.push_attributed_orders as attributed_order
          on attributed_order.goal_id = goal.id
        group by goal.id
        order by goal.id;
        """
    )
    july_by_order_project = execute_sql(
        """
        select
          attributed_order.order_project_id,
          count(*)::int as attributed_rows,
          count(distinct attributed_order.buyer_key)::int as buyers,
          coalesce(sum(attributed_order.revenue), 0)::numeric(16, 2)
            as revenue
        from public.push_attributed_orders as attributed_order
        join public.push_campaigns as campaign
          on campaign.id = attributed_order.campaign_id
        where campaign.sent_at >= '2026-07-01'
          and campaign.sent_at < '2026-08-01'
          and attributed_order.goal_id = 'all-orders'
        group by attributed_order.order_project_id
        order by attributed_order.order_project_id;
        """
    )
    failures = {
        key: value
        for key, value in (checks[0] if checks else {}).items()
        if key.startswith(("bad_", "missing_")) and int(value) != 0
    }
    if checks and int(checks[0]["active_project_rules"]) != expected_project_rules:
        failures["project_rule_count"] = {
            "actual": checks[0]["active_project_rules"],
            "expected": expected_project_rules,
        }
    print(
        json.dumps(
            {
                "status": "passed" if not failures else "failed",
                "checks": checks[0] if checks else {},
                "failures": failures,
                "byMonthAndProject": by_month,
                "byGoal": by_goal,
                "julyByOrderProject": july_by_order_project,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
