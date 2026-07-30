from __future__ import annotations

import pytest

from push_analytics_core import (
    DataQualityError,
    group_mailings,
    logical_group_key,
    normalize_mailing_name,
    normalize_platform_suffix,
    platform_from_mailing,
)


def mailing(
    mailing_id: str,
    name: str,
    *,
    project: str = "blizko-app",
    sent_at: str = "2026-07-19T15:01:00Z",
    **extra: object,
) -> dict[str, object]:
    return {
        "id": mailing_id,
        "name": name,
        "projectId": project,
        "sentAt": sent_at,
        "_isDeleted": False,
        **extra,
    }


def test_platform_detection_uses_explicit_then_name_and_unknown() -> None:
    assert platform_from_mailing({"platform": "IOS"}) == "ios"
    assert platform_from_mailing({"name": "Пуш Андроид"}) == "android"
    assert platform_from_mailing({"systemName": "promo_iphone"}) == "ios"
    assert platform_from_mailing({"name": "Без платформы"}) == "unknown"


def test_normalization_removes_copy_push_and_repeated_platform_suffixes() -> None:
    assert normalize_platform_suffix("promo_android_iOS") == "promo"
    assert normalize_mailing_name("Копия Push. К матчу готовы Android") == (
        "к матчу готовы"
    )
    assert normalize_mailing_name("Copy of Push За окном +30 IOS") == (
        "за окном +30"
    )


def test_group_key_priority_manual_utm_system_name_then_normalized_name() -> None:
    base = mailing(
        "m1",
        "Push Promo Android",
        utmCampaign="Summer",
        systemName="promo_android",
    )
    assert logical_group_key(base, manual_groups={"m1": "fixed"}) == (
        "manual:fixed"
    )
    assert logical_group_key(base) == "utm:blizko-app:summer:"

    without_utm = {**base, "utmCampaign": ""}
    assert logical_group_key(without_utm) == "system:blizko-app:promo:"

    without_system = {**without_utm, "systemName": ""}
    assert logical_group_key(without_system) == (
        "name:blizko-app:2026-07-19:promo:"
    )
    assert logical_group_key({"id": "empty", "name": ""}) is None


def test_ios_android_pair_groups_but_dates_projects_and_ab_variants_do_not() -> None:
    pair = [
        mailing("ios", "Push К матчу готовы IOS"),
        mailing("android", "Push К матчу готовы Android"),
    ]
    assert len(group_mailings(pair)) == 1
    assert len(next(iter(group_mailings(pair).values()))) == 2

    different_date = mailing(
        "tomorrow",
        "Push К матчу готовы Android",
        sent_at="2026-07-20T15:01:00Z",
    )
    assert len(group_mailings([pair[0], different_date])) == 2

    different_project = mailing(
        "main",
        "Push К матчу готовы Android",
        project="05-main",
    )
    assert len(group_mailings([pair[0], different_project])) == 2

    a = mailing("a", "Push Promo Android", abVariant="A")
    b = mailing("b", "Push Promo IOS", abVariant="B")
    assert len(group_mailings([a, b])) == 2


def test_manual_rule_can_group_different_names() -> None:
    groups = group_mailings(
        [
            mailing("one", "One Android"),
            mailing("two", "Two IOS"),
        ],
        manual_groups={"one": "campaign", "two": "campaign"},
    )
    assert list(groups) == ["manual:campaign"]


def test_deleted_variant_is_ignored() -> None:
    deleted = mailing("deleted", "Push Promo Android")
    deleted["_isDeleted"] = True
    assert group_mailings([deleted]) == {}


@pytest.mark.parametrize(
    "rows",
    [
        [
            mailing("a1", "Push Promo Android"),
            mailing("a2", "Push Promo Android"),
        ],
        [
            mailing("a", "Push Promo Android"),
            mailing("i", "Push Promo IOS"),
            mailing("u", "Push Promo"),
        ],
    ],
)
def test_duplicate_or_three_variants_are_blockers(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(DataQualityError, match="ambiguous_mailing_group"):
        group_mailings(rows)


def test_ungroupable_mailing_is_blocker() -> None:
    with pytest.raises(DataQualityError, match="mailing_group_key_missing"):
        group_mailings([{"id": "x", "name": "", "_isDeleted": False}])
