from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baselines" / "2026-07-30"


@pytest.fixture
def project_roots() -> dict[str, str]:
    return {
        "Пуши по 05ру в приложении 05ру": "05-main",
        "Пуши по Близко в приложении 05ру": "blizko-in-05",
        "Пуши в отдельном приложении Близко": "blizko-app",
    }


@pytest.fixture
def folder_fixture() -> list[dict[str, Any]]:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "delta" / "folders.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def baseline_json() -> dict[str, Any]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in BASELINE.glob("*.json")
    }
