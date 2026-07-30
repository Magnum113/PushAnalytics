from __future__ import annotations

from decimal import Decimal

import pytest

from push_analytics_core import (
    DataQualityError,
    aggregate_goal_orders,
    order_matches_rule,
    order_revenue,
    qualifying_goal_ids,
    select_goal_rule,
    validate_order_statuses,
)


def base_order(**overrides: object) -> dict[str, object]:
    return {
        "orderKey": "o1",
        "buyerKey": "b1",
        "purchasedAt": "2026-07-20T12:00:00Z",
        "firstPointOfContactId": "blizkoios",
        "statusCategories": ["CheckedOut", "Paid"],
        "statusExternalIds": ["Create"],
        **overrides,
    }


def rule(
    goal_id: str = "all-orders",
    **overrides: object,
) -> dict[str, object]:
    return {
        "goalId": goal_id,
        "effectiveFrom": "2026-07-01T00:00:00Z",
        "effectiveTo": "2026-08-01T00:00:00Z",
        "pointIds": [],
        "statusCategories": ["CheckedOut"],
        "statusExternalIds": [],
        "matchMode": "any",
        **overrides,
    }


def test_select_goal_rule_uses_effective_version_and_end_is_exclusive() -> None:
    rules = [
        rule(effectiveFrom="2026-06-01T00:00:00Z", effectiveTo="2026-07-01T00:00:00Z"),
        rule(effectiveFrom="2026-07-01T00:00:00Z", effectiveTo=None),
    ]
    selected = select_goal_rule(rules, "all-orders", "2026-07-01T00:00:00Z")
    assert selected is rules[1]


def test_goal_rule_missing_or_overlapping_version_is_blocker() -> None:
    with pytest.raises(DataQualityError, match="goal_rule_cardinality"):
        select_goal_rule([], "all-orders", "2026-07-01T00:00:00Z")
    with pytest.raises(DataQualityError, match="goal_rule_cardinality"):
        select_goal_rule(
            [rule(effectiveTo=None), rule(effectiveTo=None)],
            "all-orders",
            "2026-07-20T00:00:00Z",
        )
    with pytest.raises(DataQualityError, match="goal_rule_cardinality"):
        select_goal_rule(
            [rule(effectiveFrom="2026-08-01T00:00:00Z", effectiveTo=None)],
            "all-orders",
            "2026-07-20T00:00:00Z",
        )


def test_unknown_statuses_create_issues() -> None:
    issues = validate_order_statuses(
        base_order(
            statusCategories=["CheckedOut", "Mystery"],
            statusExternalIds=["Create", "Unknown"],
        ),
        known_categories={"CheckedOut", "Paid", "Delivered"},
        known_external_statuses={"Create"},
    )
    assert issues == [
        {"code": "unknown_status_category", "value": "Mystery"},
        {"code": "unknown_external_status", "value": "Unknown"},
    ]
    assert validate_order_statuses(
        base_order(),
        known_categories={"CheckedOut", "Paid"},
        known_external_statuses={"Create"},
    ) == []


def test_order_rule_point_filter_any_mode_and_rule_without_statuses() -> None:
    assert not order_matches_rule(
        base_order(),
        rule(pointIds=["different"]),
    )
    assert order_matches_rule(
        base_order(),
        rule(statusCategories=["Delivered", "Paid"]),
    )
    assert order_matches_rule(
        base_order(),
        rule(statusCategories=[], statusExternalIds=["Create"]),
    )
    assert order_matches_rule(
        base_order(),
        rule(statusCategories=[], statusExternalIds=[]),
    )
    assert not order_matches_rule(
        base_order(),
        rule(statusCategories=["Delivered"], statusExternalIds=["Cancelled"]),
    )


def test_order_rule_all_mode_requires_all_categories_and_external_statuses() -> None:
    assert order_matches_rule(
        base_order(),
        rule(
            statusCategories=["CheckedOut", "Paid"],
            statusExternalIds=["Create"],
            matchMode="all",
        ),
    )
    assert not order_matches_rule(
        base_order(),
        rule(
            statusCategories=["CheckedOut", "Delivered"],
            statusExternalIds=["Create"],
            matchMode="all",
        ),
    )


def test_order_can_qualify_for_multiple_goals_without_duplicates() -> None:
    rules = [
        rule("all-orders"),
        rule(
            "blizko-app",
            pointIds=["blizkoios"],
            statusCategories=["Paid"],
        ),
    ]
    assert qualifying_goal_ids(base_order(), rules) == [
        "all-orders",
        "blizko-app",
    ]


def test_order_revenue_priority_and_zero_fallback() -> None:
    assert order_revenue(
        {"priceWithDiscounts": Decimal("10.50"), "paidAmount": 20}
    ) == 10.5
    assert order_revenue(
        {"priceWithDiscounts": None, "paidAmount": Decimal("20.25")}
    ) == 20.25
    assert order_revenue({"priceWithDiscounts": 0, "paidAmount": 20}) == 0
    assert order_revenue({}) == 0


def test_aggregates_dedupe_orders_count_buyers_and_do_not_expand_items() -> None:
    rows = [
        {
            "goalId": "all-orders",
            "orderKey": "o1",
            "buyerKey": "b1",
            "revenue": 100,
            "items": ["i1", "i2"],
        },
        {
            "goalId": "all-orders",
            "orderKey": "o1",
            "buyerKey": "b1",
            "revenue": 100,
            "items": ["duplicate"],
        },
        {
            "goalId": "all-orders",
            "orderKey": "o2",
            "buyerKey": "b1",
            "revenue": 50.125,
        },
        {
            "goalId": "blizko-app",
            "orderKey": "o1",
            "buyerKey": "b1",
            "revenue": 100,
        },
    ]
    assert aggregate_goal_orders(rows) == {
        "all-orders": {
            "orders": 2,
            "buyers": 1,
            "revenue": 150.12,
        },
        "blizko-app": {
            "orders": 1,
            "buyers": 1,
            "revenue": 100.0,
        },
    }
    assert aggregate_goal_orders([]) == {}
