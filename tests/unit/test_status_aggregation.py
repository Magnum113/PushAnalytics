from __future__ import annotations

import pytest

from push_analytics_core import DataQualityError, aggregate_message_statuses


def status(
    row_id: str,
    message_id: str,
    name: str,
    *,
    version_at: str = "2026-07-01T10:00:00Z",
    deleted: bool = False,
) -> dict[str, object]:
    return {
        "messageStatusId": row_id,
        "messageId": message_id,
        "mailingStatusSystemName": name,
        "_rowversion_ts": version_at,
        "_isDeleted": deleted,
    }


def test_statuses_count_unique_message_instances_and_balance_delivery() -> None:
    rows = [
        status("s1", "m1", "Sent"),
        status("s2", "m1", "Sent"),
        status("s3", "m2", "Sent"),
        status("n1", "m2", "NotDelivered"),
        status("c1", "m1", "Clicked"),
        status("c2", "m1", "Clicked"),
        status("ignored", "m1", "Opened"),
        status("deleted", "m2", "Clicked", deleted=True),
    ]
    assert aggregate_message_statuses(rows) == {
        "sent": 2,
        "notDelivered": 1,
        "delivered": 1,
        "clicked": 1,
        "ctr": 1.0,
    }


def test_status_latest_row_can_delete_previous_status() -> None:
    rows = [
        status("same", "m1", "Sent"),
        status(
            "same",
            "m1",
            "Sent",
            version_at="2026-07-01T11:00:00Z",
            deleted=True,
        ),
    ]
    assert aggregate_message_statuses(rows) == {
        "sent": 0,
        "notDelivered": 0,
        "delivered": 0,
        "clicked": 0,
        "ctr": 0.0,
    }


def test_empty_denominator_returns_zero_ctr() -> None:
    assert aggregate_message_statuses([]) == {
        "sent": 0,
        "notDelivered": 0,
        "delivered": 0,
        "clicked": 0,
        "ctr": 0.0,
    }


def test_click_without_sent_is_blocker() -> None:
    with pytest.raises(DataQualityError, match="clicked_exceeds_sent"):
        aggregate_message_statuses([status("c1", "m1", "Clicked")])
