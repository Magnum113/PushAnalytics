from __future__ import annotations

from datetime import UTC, datetime, timedelta

from push_analytics_core import (
    aggregate_goal_orders,
    aggregate_message_statuses,
    attribute_orders,
    build_customer_merge_map,
    build_folder_project_map,
    group_mailings,
    order_revenue,
    qualifying_goal_ids,
    resolve_mailing_project,
    same_project_orders,
)


def test_synthetic_pipeline_from_folder_to_goal_aggregates(
    folder_fixture: list[dict[str, object]],
    project_roots: dict[str, str],
) -> None:
    folder_projects = build_folder_project_map(folder_fixture, project_roots)
    mailings = [
        {
            "id": "ios",
            "name": "Push Полезный набор IOS",
            "projectId": resolve_mailing_project(
                {"id": "ios", "folderInternalId": "child-app"},
                folder_projects,
            )[0],
            "folderInternalId": "child-app",
            "sentAt": "2026-07-20T10:00:00Z",
            "_isDeleted": False,
        },
        {
            "id": "android",
            "name": "Push Полезный набор Android",
            "projectId": resolve_mailing_project(
                {"id": "android", "folderInternalId": "child-app"},
                folder_projects,
            )[0],
            "folderInternalId": "child-app",
            "sentAt": "2026-07-20T10:01:00Z",
            "_isDeleted": False,
        },
    ]
    groups = group_mailings(mailings)
    assert len(groups) == 1

    statuses = [
        {
            "messageStatusId": "s1",
            "messageId": "message-1",
            "mailingStatusSystemName": "Sent",
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-20T10:02:00Z",
        },
        {
            "messageStatusId": "c1",
            "messageId": "message-1",
            "mailingStatusSystemName": "Clicked",
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-20T10:03:00Z",
        },
    ]
    assert aggregate_message_statuses(statuses)["clicked"] == 1

    merge_map = build_customer_merge_map(
        [
            {
                "unmergedCustomerId": 10,
                "mergedCustomerId": 20,
                "_isDeleted": False,
                "_rowversion_ts": "2026-07-20T10:00:00Z",
            }
        ]
    )
    purchased_at = datetime(2026, 7, 20, 12, tzinfo=UTC)
    order = {
        "orderKey": "order-hash",
        "buyerKey": "buyer-hash",
        "customerId": 20,
        "purchasedAt": purchased_at,
        "firstPointOfContactId": "blizkoios",
        "statusCategories": ["CheckedOut", "Paid"],
        "statusExternalIds": ["Create"],
        "priceWithDiscounts": 799,
    }
    attributed, issues = attribute_orders(
        [
            {
                "clickId": "click-hash",
                "customerId": 10,
                "mailingType": "mass",
                "channel": "MobilePush",
                "mailingId": "ios",
                "clickedAt": purchased_at - timedelta(minutes=15),
            }
        ],
        [order],
        merge_map=merge_map,
    )
    assert issues == []
    assert attributed[0]["winnerMailingId"] == "ios"

    rules = [
        {
            "goalId": "all-orders",
            "effectiveFrom": "2026-07-01T00:00:00Z",
            "effectiveTo": None,
            "pointIds": [],
            "statusCategories": ["CheckedOut", "Paid", "Delivered"],
            "statusExternalIds": [],
            "matchMode": "any",
        },
        {
            "goalId": "blizko-app",
            "effectiveFrom": "2026-07-01T00:00:00Z",
            "effectiveTo": None,
            "pointIds": ["blizkoios", "blizkoandroid"],
            "statusCategories": ["Paid", "Delivered"],
            "statusExternalIds": [],
            "matchMode": "any",
        },
    ]
    metric_rows = [
        {
            "goalId": goal_id,
            "orderKey": order["orderKey"],
            "buyerKey": order["buyerKey"],
            "revenue": order_revenue(order),
        }
        for goal_id in qualifying_goal_ids(order, rules)
    ]
    assert aggregate_goal_orders(metric_rows) == {
        "all-orders": {"orders": 1, "buyers": 1, "revenue": 799.0},
        "blizko-app": {"orders": 1, "buyers": 1, "revenue": 799.0},
    }
    same_project = same_project_orders(
        [
            {
                **metric_rows[0],
                "sourceId": attributed[0]["winnerMailingId"],
                "orderProjectId": "blizko-app",
            }
        ],
        {"ios": "blizko-app"},
        ["blizko-app"],
    )
    assert len(same_project) == 1
