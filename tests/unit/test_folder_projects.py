from __future__ import annotations

from copy import deepcopy

import pytest

from push_analytics_core import (
    DataQualityError,
    build_folder_project_map,
    resolve_mailing_project,
)


def test_three_project_roots_and_child_inheritance(
    folder_fixture: list[dict[str, object]],
    project_roots: dict[str, str],
) -> None:
    mapping = build_folder_project_map(folder_fixture, project_roots)
    assert mapping["root-05"] == "05-main"
    assert mapping["root-in05"] == "blizko-in-05"
    assert mapping["root-app"] == "blizko-app"
    assert mapping["child-app"] == "blizko-app"
    assert "deleted-child" not in mapping


def test_duplicate_project_root_name_is_blocker(
    folder_fixture: list[dict[str, object]],
    project_roots: dict[str, str],
) -> None:
    duplicate = deepcopy(folder_fixture[0])
    duplicate["internalId"] = "duplicate-root"
    with pytest.raises(DataQualityError, match="ambiguous_project_folder"):
        build_folder_project_map([*folder_fixture, duplicate], project_roots)


def test_folder_parent_cycle_is_blocker(project_roots: dict[str, str]) -> None:
    folders = [
        {
            "internalId": "a",
            "name": "A",
            "parentInternalId": "b",
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-01T00:00:00Z",
        },
        {
            "internalId": "b",
            "name": "B",
            "parentInternalId": "a",
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-01T00:00:00Z",
        },
    ]
    with pytest.raises(DataQualityError, match="folder_parent_cycle"):
        build_folder_project_map(folders, project_roots)


def test_unknown_or_deleted_folder_has_no_fallback(
    folder_fixture: list[dict[str, object]],
    project_roots: dict[str, str],
) -> None:
    mapping = build_folder_project_map(folder_fixture, project_roots)
    assert resolve_mailing_project(
        {"id": "new", "folderInternalId": "unknown"},
        mapping,
    ) == (None, "unclassified")
    assert resolve_mailing_project(
        {"id": "deleted", "folderInternalId": "deleted-child"},
        mapping,
    ) == (None, "unclassified")


def test_manual_override_wins_over_lock_and_lock_wins_over_moved_folder(
    folder_fixture: list[dict[str, object]],
    project_roots: dict[str, str],
) -> None:
    mapping = build_folder_project_map(folder_fixture, project_roots)
    mailing = {"id": "m1", "folderInternalId": "root-05"}
    assert resolve_mailing_project(
        mailing,
        mapping,
        locked_projects={"m1": "blizko-app"},
    ) == ("blizko-app", "locked")
    assert resolve_mailing_project(
        mailing,
        mapping,
        manual_overrides={"m1": "blizko-in-05"},
        locked_projects={"m1": "blizko-app"},
    ) == ("blizko-in-05", "manual")
    assert resolve_mailing_project(mailing, mapping) == ("05-main", "folder")


def test_rootless_top_level_and_missing_parent_are_unclassified(
    project_roots: dict[str, str],
) -> None:
    rows = [
        {
            "internalId": "top",
            "name": "Other",
            "parentInternalId": None,
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-01T00:00:00Z",
        },
        {
            "internalId": "orphan",
            "name": "Orphan",
            "parentInternalId": "missing",
            "_isDeleted": False,
            "_rowversion_ts": "2026-07-01T00:00:00Z",
        },
    ]
    mapping = build_folder_project_map(rows, project_roots)
    assert mapping == {"top": None, "missing": None, "orphan": None}
