from __future__ import annotations

import pytest

from push_analytics_core import (
    DataQualityError,
    build_customer_merge_map,
    canonical_customer,
)


def merge(
    source: int | None,
    target: int | None,
    *,
    version_at: str = "2026-07-01T10:00:00Z",
    deleted: bool = False,
) -> dict[str, object]:
    return {
        "unmergedCustomerId": source,
        "mergedCustomerId": target,
        "_rowversion_ts": version_at,
        "_isDeleted": deleted,
    }


def test_simple_chain_and_two_sources_resolve_to_one_customer() -> None:
    mapping = build_customer_merge_map(
        [
            merge(1, 2),
            merge(2, 3),
            merge(4, 3),
        ]
    )
    assert mapping == {1: 3, 2: 3, 3: 3, 4: 3}
    assert canonical_customer(1, mapping) == 3
    assert canonical_customer("9", mapping) == 9


def test_latest_merge_row_wins_and_deleted_or_null_rows_do_not_apply() -> None:
    mapping = build_customer_merge_map(
        [
            merge(1, 2),
            merge(1, 3, version_at="2026-07-01T11:00:00Z"),
            merge(4, 5, deleted=True),
            merge(None, 6),
            merge(7, None),
        ]
    )
    assert mapping == {1: 3, 3: 3}


def test_merge_cycle_is_blocker() -> None:
    with pytest.raises(DataQualityError, match="customer_merge_cycle"):
        build_customer_merge_map([merge(1, 2), merge(2, 1)])
