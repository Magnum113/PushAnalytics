from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from push_analytics_core import (
    DataQualityError,
    attribute_orders,
    moscow_calendar_date,
    visible_attributions,
)


PURCHASED = datetime(2026, 7, 20, 12, tzinfo=UTC)


def click(
    click_id: str,
    minutes_before: float,
    *,
    customer: int | None = 1,
    mailing_type: str = "mass",
    channel: str = "MobilePush",
    mailing_id: str | None = None,
) -> dict[str, object]:
    return {
        "clickId": click_id,
        "customerId": customer,
        "mailingType": mailing_type,
        "channel": channel,
        "mailingId": mailing_id or click_id,
        "clickedAt": PURCHASED - timedelta(minutes=minutes_before),
    }


def order(
    key: str = "o1",
    *,
    customer: int | None = 1,
    purchased_at: datetime = PURCHASED,
) -> dict[str, object]:
    return {
        "orderKey": key,
        "customerId": customer,
        "purchasedAt": purchased_at,
        "buyerKey": f"buyer-{customer}",
        "revenue": 100,
    }


def test_one_click_and_exact_24_hour_boundary_are_attributed() -> None:
    attributions, issues = attribute_orders(
        [click("c1", 30), click("boundary", 24 * 60)],
        [order()],
    )
    assert issues == []
    assert attributions[0]["winnerClickId"] == "c1"
    assert attributions[0]["latencyMinutes"] == 30

    boundary_only, _ = attribute_orders(
        [click("boundary", 24 * 60)],
        [order()],
    )
    assert boundary_only[0]["latencySeconds"] == 24 * 60 * 60
    assert boundary_only[0]["latencyMinutes"] == 1440


def test_24_hours_and_one_second_click_after_order_and_no_click_are_excluded() -> None:
    too_old = {
        **click("old", 24 * 60),
        "clickedAt": PURCHASED - timedelta(hours=24, seconds=1),
    }
    after = click("after", -1)
    attributions, issues = attribute_orders(
        [too_old, after],
        [order()],
    )
    assert attributions == []
    assert issues == []


def test_latest_mass_and_trigger_click_wins_globally() -> None:
    clicks = [
        click("mass-old", 60, mailing_type="mass"),
        click("mass-new", 30, mailing_type="mass"),
        click("trigger", 10, mailing_type="trigger"),
    ]
    attributions, _ = attribute_orders(clicks, [order()])
    assert attributions[0]["winnerClickId"] == "trigger"
    assert attributions[0]["sourceKind"] == "trigger"


def test_transaction_wins_but_is_hidden_from_mass_trigger_views() -> None:
    attributions, _ = attribute_orders(
        [
            click("mass", 30, mailing_type="mass"),
            click("transaction", 5, mailing_type="transaction"),
        ],
        [order()],
    )
    assert attributions[0]["sourceKind"] == "transaction"
    assert visible_attributions(attributions, {"mass", "trigger"}) == []
    assert visible_attributions(attributions, {"transaction"}) == attributions


def test_email_unsupported_type_other_customer_and_customerless_click_are_ignored() -> None:
    attributions, _ = attribute_orders(
        [
            click("mass", 30),
            click("email", 1, channel="Email"),
            click("other-type", 2, mailing_type="service"),
            click("other-customer", 3, customer=2),
            click("customerless", 4, customer=None),
        ],
        [order()],
    )
    assert attributions[0]["winnerClickId"] == "mass"


def test_click_and_order_customers_are_canonicalized_after_merge() -> None:
    attributions, _ = attribute_orders(
        [click("before-merge", 20, customer=1)],
        [order(customer=2)],
        merge_map={1: 3, 2: 3, 3: 3},
    )
    assert attributions[0]["canonicalCustomerId"] == 3


def test_duplicate_click_id_keeps_latest_event() -> None:
    older = click("same", 60)
    newer = click("same", 10)
    attributions, _ = attribute_orders([newer, older], [order()])
    assert attributions[0]["latencyMinutes"] == 10


def test_missing_customer_is_quality_issue_and_duplicate_order_is_blocker() -> None:
    attributions, issues = attribute_orders(
        [click("c1", 30)],
        [order(customer=None)],
    )
    assert attributions == []
    assert issues == [{"code": "order_without_customer", "orderKey": "o1"}]

    with pytest.raises(DataQualityError, match="duplicate_order"):
        attribute_orders(
            [click("c1", 30)],
            [order(), order()],
        )


def test_utc_normalization_tie_break_and_moscow_calendar_date() -> None:
    clicks = [
        {
            **click("a", 30),
            "clickedAt": "2026-07-20T11:30:00Z",
        },
        {
            **click("b", 30),
            "clickedAt": datetime(2026, 7, 20, 11, 30),
        },
    ]
    attributions, _ = attribute_orders(
        clicks,
        [{**order(), "purchasedAt": "2026-07-20T12:00:00+00:00"}],
    )
    assert attributions[0]["winnerClickId"] == "b"
    assert moscow_calendar_date("2026-07-20T21:30:00Z") == "2026-07-21"
