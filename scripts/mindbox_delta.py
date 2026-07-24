#!/usr/bin/env python3
"""Small Delta Sharing reader for the local Push Analytics prototype.

The module intentionally uses only the Python standard library and pyarrow.
Secrets are read from ../.env and never printed. Parquet files are cached in
data/raw/, which is excluded from Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq
import certifi


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Не найден файл {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class TableRef:
    schema: str
    table: str
    share: str = "exports"

    @property
    def slug(self) -> str:
        return f"{self.schema}.{self.table}"


class DeltaClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _json_lines(self, path: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/x-ndjson, application/json",
                "User-Agent": "PushAnalytics/0.1",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=120, context=SSL_CONTEXT
            ) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Mindbox Delta Sharing: HTTP {error.code}: {body}") from error

        rows: list[dict[str, Any]] = []
        for line in payload.splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def changes(
        self, ref: TableRef, start_version: int, end_version: int
    ) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {"startingVersion": start_version, "endingVersion": end_version}
        )
        path = (
            f"/shares/{urllib.parse.quote(ref.share)}/schemas/"
            f"{urllib.parse.quote(ref.schema)}/tables/{urllib.parse.quote(ref.table)}"
            f"/changes?{params}"
        )
        return self._json_lines(path)

    def latest_version(self, ref: TableRef) -> int:
        actions = self.changes(ref, 0, 9)
        versions: list[int] = []
        for action in actions:
            metadata = action.get("metaData") or action.get("metadata")
            if isinstance(metadata, dict):
                version = metadata.get("version")
                if version is not None:
                    versions.append(int(version))
        if not versions:
            raise RuntimeError(f"Не удалось определить версию таблицы {ref.slug}")
        return max(versions)

    def add_actions(
        self, ref: TableRef, start_version: int, end_version: int
    ) -> Iterable[tuple[int, dict[str, Any]]]:
        ranges: list[tuple[int, int]] = []
        start = max(0, start_version)
        while start <= end_version:
            end = min(start + 9, end_version)
            ranges.append((start, end))
            start = end + 1

        def fetch_range(version_range: tuple[int, int]) -> list[dict[str, Any]]:
            return self.changes(ref, version_range[0], version_range[1])

        with ThreadPoolExecutor(max_workers=min(8, len(ranges) or 1)) as executor:
            action_batches = executor.map(fetch_range, ranges)
            for actions in action_batches:
                for action in actions:
                    add = action.get("add")
                    if not isinstance(add, dict) or not add.get("url"):
                        continue
                    version = int(add.get("version", 0))
                    yield version, add

    def read_table(
        self,
        ref: TableRef,
        start_version: int,
        end_version: int,
        *,
        columns: list[str] | None = None,
        refresh: bool = False,
    ) -> pa.Table:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        actions = list(self.add_actions(ref, start_version, end_version))

        def local_file(item: tuple[int, tuple[int, dict[str, Any]]]) -> Path:
            index, (version, add) = item
            url = str(add["url"])
            digest = hashlib.sha1(url.split("?", 1)[0].encode("utf-8")).hexdigest()[:12]
            cache_file = RAW_DIR / (
                f"{ref.schema}_{ref.table}_v{version}_{index}_{digest}.parquet"
            )
            if refresh or not cache_file.exists():
                request = urllib.request.Request(
                    url, headers={"User-Agent": "PushAnalytics/0.1"}
                )
                with urllib.request.urlopen(
                    request, timeout=300, context=SSL_CONTEXT
                ) as response:
                    cache_file.write_bytes(response.read())
            return cache_file

        with ThreadPoolExecutor(max_workers=min(8, len(actions) or 1)) as executor:
            cache_files = list(executor.map(local_file, enumerate(actions)))

        tables: list[pa.Table] = []
        for cache_file in cache_files:
            try:
                tables.append(pq.read_table(cache_file, columns=columns))
            except pa.ArrowInvalid:
                # Schema discovery is more useful than a hard failure when a
                # requested optional column is not available in the project.
                tables.append(pq.read_table(cache_file))

        if not tables:
            return pa.table({})
        return pa.concat_tables(tables, promote_options="default")


def client_from_env() -> DeltaClient:
    env = load_env()
    base_url = env.get("URL_DATABASE", "").strip()
    token = env.get("SECRET_KEY", "").strip()
    if not base_url or not token:
        raise RuntimeError("В .env должны быть заполнены URL_DATABASE и SECRET_KEY")
    return DeltaClient(base_url, token)


def value_for_json(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def inspect_table(args: argparse.Namespace) -> None:
    ref = TableRef(*args.table.split(".", 1))
    client = client_from_env()
    latest = client.latest_version(ref)
    start = max(0, latest - args.versions + 1)
    table = client.read_table(ref, start, latest, refresh=args.refresh)
    print(
        json.dumps(
            {
                "table": ref.slug,
                "versionRange": [start, latest],
                "rows": table.num_rows,
                "columns": table.column_names,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if table.num_rows:
        rows = table.slice(max(0, table.num_rows - args.limit), args.limit).to_pylist()
        print(
            json.dumps(
                [
                    {key: value_for_json(value) for key, value in row.items()}
                    for row in rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read Mindbox Delta Sharing tables")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="Download and inspect a recent table slice")
    inspect.add_argument("table", help="Schema.Table, e.g. Mailings.Mailings")
    inspect.add_argument("--versions", type=int, default=30)
    inspect.add_argument("--limit", type=int, default=20)
    inspect.add_argument("--refresh", action="store_true")
    inspect.set_defaults(func=inspect_table)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as error:  # noqa: BLE001 - CLI should return a concise error.
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
