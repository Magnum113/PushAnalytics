from __future__ import annotations

from datetime import UTC, datetime

import pytest

from push_analytics_core import (
    DataQualityError,
    advance_delta_cursor,
    as_utc,
    latest_state,
    validate_schema,
)


def row(
    key: str | None,
    version_at: str,
    *,
    deleted: bool = False,
    value: str = "",
) -> dict[str, object]:
    return {
        "id": key,
        "value": value,
        "_isDeleted": deleted,
        "_rowversion_ts": version_at,
    }


def test_as_utc_normalizes_strings_naive_and_aware_datetimes() -> None:
    expected = datetime(2026, 7, 1, 10, tzinfo=UTC)
    assert as_utc("2026-07-01T10:00:00Z") == expected
    assert as_utc(datetime(2026, 7, 1, 10)) == expected
    assert as_utc(datetime(2026, 7, 1, 13, tzinfo=datetime.now().astimezone().tzinfo)).tzinfo == UTC


def test_validate_schema_accepts_complete_and_rejects_changed_schema() -> None:
    validate_schema({"id", "name"}, {"id"})
    with pytest.raises(DataQualityError, match="delta_schema_missing_columns") as error:
        validate_schema({"id"}, {"id", "name"})
    assert error.value.code == "delta_schema_missing_columns"
    assert error.value.detail == "name"


def test_latest_state_selects_latest_is_idempotent_and_honors_delete() -> None:
    rows = [
        row("a", "2026-07-01T10:00:00Z", value="old"),
        row("a", "2026-07-01T11:00:00Z", value="new"),
        row("a", "2026-07-01T11:00:00Z", value="repeat"),
        row("b", "2026-07-01T10:00:00Z", deleted=True),
    ]
    assert latest_state(rows, "id", required_columns={"id", "_rowversion_ts"}) == [
        rows[1]
    ]


def test_latest_state_supports_callable_empty_batch_and_null_key() -> None:
    assert latest_state([], lambda value: value["id"]) == []
    rows = [row("a", "2026-07-01T10:00:00Z")]
    assert latest_state(rows, lambda value: value["id"]) == rows
    with pytest.raises(DataQualityError, match="delta_null_key"):
        latest_state([row(None, "2026-07-01T10:00:00Z")], "id")


def test_latest_state_rejects_missing_required_column() -> None:
    with pytest.raises(DataQualityError, match="delta_schema_missing_columns"):
        latest_state(
            [{"id": "a", "_rowversion_ts": "2026-07-01T10:00:00Z"}],
            "id",
            required_columns={"id", "name"},
        )


def test_advance_delta_cursor_is_contiguous_idempotent_and_handles_empty() -> None:
    assert advance_delta_cursor(4, []) == 4
    assert advance_delta_cursor(4, [3, 4, 5, 5, 6]) == 6


def test_advance_delta_cursor_blocks_version_gap() -> None:
    with pytest.raises(DataQualityError, match="delta_version_gap") as error:
        advance_delta_cursor(4, [5, 7])
    assert error.value.detail == "previous=4; missing=[6]"
