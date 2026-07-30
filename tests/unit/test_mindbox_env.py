from __future__ import annotations

from pathlib import Path

from mindbox_delta import load_env


def test_load_env_supports_ci_environment_without_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VITE_SUPABASE_URL", "https://ci.example")
    values = load_env(tmp_path / "missing.env")
    assert values["VITE_SUPABASE_URL"] == "https://ci.example"


def test_process_environment_overrides_quoted_local_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "VALUE='from-file'\n"
        "EMPTY=\n"
        "IGNORED_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUE", "from-process")
    values = load_env(env_file)
    assert values["VALUE"] == "from-process"
    assert values["EMPTY"] == ""
