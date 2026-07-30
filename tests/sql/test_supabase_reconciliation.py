from __future__ import annotations

import json
from pathlib import Path

import pytest

from mindbox_delta import load_env
from sync_supabase_pg_meta import execute_sql


ROOT = Path(__file__).resolve().parents[2]
BASELINE_SUMMARY = json.loads(
    (ROOT / "baselines" / "2026-07-30" / "supabase_snapshot.json").read_text(
        encoding="utf-8"
    )
)["summary"]


def require_live_supabase() -> None:
    env = load_env()
    missing = [
        key
        for key in (
            "VITE_SUPABASE_URL",
            "SUPABASE_STUDIO_USER",
            "SUPABASE_STUDIO_PASSWORD",
        )
        if not env.get(key)
    ]
    if missing:
        pytest.skip(f"Supabase pg-meta credentials missing: {missing}")


@pytest.mark.live_sql
def test_live_table_counts_match_frozen_baseline() -> None:
    require_live_supabase()
    result = execute_sql(
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
          )
        ) as value;
        """
    )[0]["value"]
    for key, actual in result.items():
        assert actual == BASELINE_SUMMARY[key]


@pytest.mark.live_sql
def test_live_aggregates_equal_order_details() -> None:
    require_live_supabase()
    checks = execute_sql(
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
        trigger_actual as (
          select
            scenario_mailing_id,
            goal_id,
            count(*)::bigint as orders,
            count(distinct buyer_key)::bigint as buyers,
            round(coalesce(sum(revenue), 0), 2)::numeric(16, 2) as revenue
          from public.push_trigger_attributed_orders
          group by scenario_mailing_id, goal_id
        )
        select jsonb_build_object(
          'badMassMetrics', (
            select count(*)
            from public.push_campaign_goal_metrics as metric
            left join mass_actual as actual
              using (campaign_id, goal_id)
            where metric.orders <> coalesce(actual.orders, 0)
               or metric.buyers <> coalesce(actual.buyers, 0)
               or metric.revenue <> coalesce(actual.revenue, 0)
          ),
          'badTriggerMetrics', (
            select count(*)
            from public.push_trigger_goal_metrics as metric
            left join trigger_actual as actual
              using (scenario_mailing_id, goal_id)
            where metric.orders <> coalesce(actual.orders, 0)
               or metric.buyers <> coalesce(actual.buyers, 0)
               or metric.revenue <> coalesce(actual.revenue, 0)
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
          )
        ) as value;
        """
    )[0]["value"]
    assert checks == {
        "badMassMetrics": 0,
        "badTriggerMetrics": 0,
        "massOrphanItems": 0,
        "triggerOrphanItems": 0,
    }


@pytest.mark.live_sql
def test_live_physical_order_has_one_global_winner_and_rls_is_enabled() -> None:
    require_live_supabase()
    checks = execute_sql(
        """
        with winners as (
          select order_key, 'mass:' || campaign_id::text as winner
          from public.push_attributed_orders
          where goal_id = 'all-orders'
          union all
          select order_key, 'trigger:' || scenario_mailing_id::text as winner
          from public.push_trigger_attributed_orders
          where goal_id = 'all-orders'
        )
        select jsonb_build_object(
          'duplicateWinners', (
            select count(*)
            from (
              select order_key
              from winners
              group by order_key
              having count(distinct winner) > 1
            ) as duplicate
          ),
          'ordersOutsideWindow', (
            select count(*)
            from (
              select latency_minutes, attributed_click_at, purchased_at
              from public.push_attributed_orders
              union all
              select latency_minutes, attributed_click_at, purchased_at
              from public.push_trigger_attributed_orders
            ) as attributed_order
            where latency_minutes not between 0 and 1440
               or attributed_click_at > purchased_at
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
    assert checks == {
        "duplicateWinners": 0,
        "ordersOutsideWindow": 0,
        "rlsDisabledTables": [],
    }


@pytest.mark.live_sql
def test_matching_project_buyer_rpcs_equal_direct_distinct_counts() -> None:
    require_live_supabase()
    checks = execute_sql(
        """
        with mass_selection as (
          select
            campaign.id,
            coalesce(manual.project_id, campaign.project_id) as project_id
          from public.push_campaigns as campaign
          left join public.push_manual_overrides as manual
            on manual.source_kind = 'mass'
           and manual.campaign_id = campaign.id
        ),
        trigger_selection as (
          select
            mailing.id,
            coalesce(manual.project_id, mailing.project_id) as project_id
          from public.push_scenario_mailings as mailing
          left join public.push_manual_overrides as manual
            on manual.source_kind = 'trigger'
           and manual.scenario_mailing_id = mailing.id
          where not mailing.is_test
        )
        select jsonb_build_object(
          'massRpc', (
            select public.push_matching_project_unique_buyer_count(
              array_agg(id order by id),
              array_agg(project_id order by id),
              'all-orders'
            )
            from mass_selection
          ),
          'massDirect', (
            select count(distinct attributed_order.buyer_key)
            from public.push_attributed_orders as attributed_order
            join mass_selection as selected
              on selected.id = attributed_order.campaign_id
             and selected.project_id =
               attributed_order.order_project_id
            where attributed_order.goal_id = 'all-orders'
          ),
          'triggerRpc', (
            select
              public.push_trigger_matching_project_unique_buyer_count(
                array_agg(id order by id),
                array_agg(project_id order by id),
                'all-orders',
                null,
                null
              )
            from trigger_selection
          ),
          'triggerDirect', (
            select count(distinct attributed_order.buyer_key)
            from public.push_trigger_attributed_orders as attributed_order
            join trigger_selection as selected
              on selected.id = attributed_order.scenario_mailing_id
             and selected.project_id =
               attributed_order.order_project_id
            where attributed_order.goal_id = 'all-orders'
          )
        ) as value;
        """
    )[0]["value"]
    assert checks["massRpc"] == checks["massDirect"]
    assert checks["triggerRpc"] == checks["triggerDirect"]


@pytest.mark.live_sql
def test_same_project_scope_keeps_cross_project_rows_for_audit() -> None:
    require_live_supabase()
    checks = execute_sql(
        """
        with scoped as (
          select
            attributed_order.order_key,
            attributed_order.order_project_id,
            coalesce(manual.project_id, campaign.project_id)
              as push_project_id
          from public.push_attributed_orders as attributed_order
          join public.push_campaigns as campaign
            on campaign.id = attributed_order.campaign_id
          left join public.push_manual_overrides as manual
            on manual.source_kind = 'mass'
           and manual.campaign_id = campaign.id
          where attributed_order.goal_id = 'all-orders'
        )
        select jsonb_build_object(
          'matching', count(*) filter (
            where order_project_id = push_project_id
          ),
          'crossProject', count(*) filter (
            where order_project_id <> push_project_id
          )
        ) as value
        from scoped;
        """
    )[0]["value"]
    assert checks["matching"] > 0
    assert checks["crossProject"] > 0


@pytest.mark.live_sql
def test_matching_project_functions_are_invoker_and_validate_pair_lengths() -> None:
    require_live_supabase()
    functions = execute_sql(
        """
        select
          proname,
          prosecdef
        from pg_proc
        where pronamespace = 'public'::regnamespace
          and proname in (
            'push_matching_project_unique_buyer_count',
            'push_trigger_matching_project_unique_buyer_count'
          )
        order by proname;
        """
    )
    assert functions == [
        {
            "proname": "push_matching_project_unique_buyer_count",
            "prosecdef": False,
        },
        {
            "proname": "push_trigger_matching_project_unique_buyer_count",
            "prosecdef": False,
        },
    ]
    with pytest.raises(RuntimeError, match="equal cardinality"):
        execute_sql(
            """
            select public.push_matching_project_unique_buyer_count(
              array[1::bigint],
              array['05-main'::text, 'blizko-app'::text],
              'all-orders'
            );
            """
        )
