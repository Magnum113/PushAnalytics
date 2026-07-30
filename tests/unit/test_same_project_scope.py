from __future__ import annotations

import pytest

from push_analytics_core import (
    DataQualityError,
    aggregate_order_selection,
    normalize_project_selection,
    same_project_orders,
)


SOURCE_PROJECTS = {
    "push-05": "05-main",
    "push-app": "blizko-app",
    "push-in-05": "blizko-in-05",
}


def attributed_order(
    order_key: str,
    source_id: str,
    order_project_id: str,
    *,
    buyer_key: str = "buyer-1",
    revenue: float = 100,
) -> dict[str, object]:
    return {
        "orderKey": order_key,
        "sourceId": source_id,
        "orderProjectId": order_project_id,
        "buyerKey": buyer_key,
        "revenue": revenue,
    }


def test_project_selection_is_stable_and_rejects_empty_or_unknown() -> None:
    assert normalize_project_selection(
        ["blizko-app", "05-main", "blizko-app"],
        SOURCE_PROJECTS.values(),
    ) == ("05-main", "blizko-app")

    with pytest.raises(DataQualityError, match="project_selection_empty"):
        normalize_project_selection([], SOURCE_PROJECTS.values())
    with pytest.raises(DataQualityError, match="project_selection_unknown"):
        normalize_project_selection(
            ["unknown"],
            SOURCE_PROJECTS.values(),
        )


def test_single_project_keeps_only_orders_matching_that_push_project() -> None:
    rows = [
        attributed_order("matched", "push-05", "05-main"),
        attributed_order("cross", "push-05", "blizko-app"),
        attributed_order("other-push", "push-app", "blizko-app"),
    ]
    assert same_project_orders(
        rows,
        SOURCE_PROJECTS,
        ["05-main"],
    ) == [rows[0]]


def test_multiselect_matches_each_order_to_its_own_push_project() -> None:
    rows = [
        attributed_order("05-ok", "push-05", "05-main"),
        attributed_order("05-cross", "push-05", "blizko-app"),
        attributed_order("app-ok", "push-app", "blizko-app"),
        attributed_order("app-cross", "push-app", "05-main"),
        attributed_order("not-selected", "push-in-05", "blizko-in-05"),
    ]
    assert same_project_orders(
        rows,
        SOURCE_PROJECTS,
        ["05-main", "blizko-app"],
    ) == [rows[0], rows[2]]


def test_effective_manual_project_is_used_without_changing_attribution() -> None:
    rows = [
        attributed_order("before-override", "push-05", "05-main"),
        attributed_order("after-override", "push-05", "blizko-app"),
    ]
    effective_projects = {
        **SOURCE_PROJECTS,
        "push-05": "blizko-app",
    }
    assert same_project_orders(
        rows,
        effective_projects,
        ["blizko-app"],
    ) == [rows[1]]


def test_unknown_source_is_a_quality_blocker() -> None:
    with pytest.raises(
        DataQualityError,
        match="same_project_source_unknown",
    ):
        same_project_orders(
            [
                attributed_order(
                    "unknown-source",
                    "missing",
                    "05-main",
                )
            ],
            SOURCE_PROJECTS,
            ["05-main"],
        )


def test_selection_aggregate_deduplicates_orders_and_buyers_globally() -> None:
    rows = [
        attributed_order("o1", "push-05", "05-main", buyer_key="buyer-1"),
        attributed_order(
            "o1",
            "push-05",
            "05-main",
            buyer_key="buyer-1",
            revenue=999,
        ),
        attributed_order(
            "o2",
            "push-app",
            "blizko-app",
            buyer_key="buyer-1",
            revenue=50.125,
        ),
        attributed_order(
            "o3",
            "push-app",
            "blizko-app",
            buyer_key="buyer-2",
            revenue=25,
        ),
    ]
    assert aggregate_order_selection(rows) == {
        "orders": 3,
        "buyers": 2,
        "revenue": 175.12,
    }
    assert aggregate_order_selection([]) == {
        "orders": 0,
        "buyers": 0,
        "revenue": 0,
    }
