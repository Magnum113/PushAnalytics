#!/usr/bin/env python3
"""Measure time from the first non-empty Blizko cart event to a purchase.

The script joins a Mindbox customer-actions export with the ProcessingOrders
Delta tables. Raw customer and order identifiers never leave the local raw
data directory; the generated report contains only deterministic SHA-256
aliases.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, TextIO
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from mindbox_delta import RAW_DIR, TableRef, client_from_env


ROOT = Path(__file__).resolve().parents[1]
MOSCOW = ZoneInfo("Europe/Moscow")
BLIZKO_POINTS = {
    "97f9a0dd-62d5-4e6c-8538-d4d00ffe221a": "iOS",
    "af005e5f-d68b-462d-9dbb-c3b5e9a9617b": "Android",
}
EXPECTED_CART_TEMPLATE = "UstanovkaSpiskaProduktovVOperaciiBlizko"


def utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def current_rows(
    rows: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    latest: dict[Any, dict[str, Any]] = {}
    for row in rows:
        row_key = key(row)
        previous = latest.get(row_key)
        if previous is None or row.get("_rowversion_ts") > previous.get("_rowversion_ts"):
            latest[row_key] = row
    return [row for row in latest.values() if not row.get("_isDeleted")]


def canonical_map(rows: Iterable[dict[str, Any]]) -> dict[int, int]:
    direct: dict[int, int] = {}
    for row in rows:
        source = row.get("unmergedCustomerId")
        target = row.get("mergedCustomerId")
        if source is not None and target is not None:
            direct[int(source)] = int(target)

    def resolve(customer_id: int) -> int:
        seen: set[int] = set()
        current = customer_id
        while current in direct and current not in seen:
            seen.add(current)
            current = direct[current]
        return current

    return {customer_id: resolve(customer_id) for customer_id in direct}


def canonical(customer_id: int, merged: dict[int, int]) -> int:
    return merged.get(customer_id, customer_id)


def line_key(row: dict[str, Any]) -> tuple[str, str]:
    identity = row.get("lineId")
    if identity is None:
        identity = row.get("lineNumber")
    if identity is None:
        identity = row.get("productInternalId")
    return str(row["orderId"]), str(identity)


def number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def alias(prefix: str, value: str, length: int = 12) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()
    return f"{prefix}-{digest[:length]}"


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_json_array(stream: TextIO, key: str) -> Iterator[dict[str, Any]]:
    """Stream objects from a top-level JSON array stored under ``key``."""

    decoder = json.JSONDecoder()
    buffer = ""
    cursor = 0
    marker = json.dumps(key)
    found_array = False
    eof = False

    while not found_array:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            raise RuntimeError(f"В JSON не найден массив {key}")
        buffer += chunk
        marker_pos = buffer.find(marker)
        if marker_pos < 0:
            buffer = buffer[-len(marker) - 128 :]
            continue
        array_pos = buffer.find("[", marker_pos + len(marker))
        if array_pos < 0:
            continue
        cursor = array_pos + 1
        found_array = True

    while True:
        while True:
            while cursor < len(buffer) and buffer[cursor] in " \r\n\t,":
                cursor += 1
            if cursor < len(buffer):
                break
            if eof:
                return
            buffer = ""
            cursor = 0
            chunk = stream.read(4 * 1024 * 1024)
            if chunk:
                buffer = chunk
            else:
                eof = True

        if buffer[cursor] == "]":
            return

        while True:
            try:
                value, end = decoder.raw_decode(buffer, cursor)
                cursor = end
                if isinstance(value, dict):
                    yield value
                break
            except json.JSONDecodeError:
                if eof:
                    raise
                buffer = buffer[cursor:]
                cursor = 0
                chunk = stream.read(4 * 1024 * 1024)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

        if cursor > 8 * 1024 * 1024:
            buffer = buffer[cursor:]
            cursor = 0


def iter_actions(paths: list[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with open_text(path) as stream:
            yield from iter_json_array(stream, "customerActions")


def action_customer_id(action: dict[str, Any]) -> int | None:
    value = ((action.get("customer") or {}).get("ids") or {}).get("mindboxId")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def action_has_products(action: dict[str, Any]) -> bool:
    products = action.get("products")
    groups = action.get("productGroups")
    return bool(products) or bool(groups)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def fmt_minutes(value: float | None) -> str:
    if value is None:
        return "—"
    minutes = int(round(value))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    return f"{minutes} мин"


def fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M:%S")


def fmt_money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def bucket(minutes: float) -> str:
    if minutes < 5:
        return "< 5 мин"
    if minutes < 15:
        return "5–14 мин"
    if minutes < 30:
        return "15–29 мин"
    if minutes < 60:
        return "30–59 мин"
    if minutes < 120:
        return "1–2 ч"
    if minutes < 240:
        return "2–4 ч"
    return "4+ ч"


def cached_rows(schema: str, table: str) -> list[dict[str, Any]]:
    """Read each locally cached Delta file once, ignoring duplicate cache names."""

    unique: dict[str, Path] = {}
    for path in RAW_DIR.glob(f"{schema}_{table}_*.parquet"):
        content_digest = path.stem.rsplit("_", 1)[-1]
        unique[content_digest] = path
    if not unique:
        raise RuntimeError(f"Нет локального Delta-кэша {schema}.{table}")
    tables = [pq.read_table(path) for path in unique.values()]
    return pa.concat_tables(tables, promote_options="default").to_pylist()


def load_delta(*, offline: bool) -> tuple[
    list[dict[str, Any]],
    dict[str, set[str]],
    dict[str, datetime],
    dict[int, int],
]:
    client = None if offline else client_from_env()

    def rows(schema: str, table: str) -> list[dict[str, Any]]:
        if offline:
            return cached_rows(schema, table)
        ref = TableRef(schema, table)
        return client.read_table(ref, 0, client.latest_version(ref)).to_pylist()

    orders = current_rows(
        rows("ProcessingOrders", "Orders"),
        lambda row: row["id"],
    )

    statuses = current_rows(
        rows("ProcessingOrders", "PurchaseStatuses"),
        lambda row: row["internalId"],
    )
    status_category = {
        str(row["internalId"]): str(row.get("categorySystemName") or "")
        for row in statuses
    }

    purchase_history = rows("ProcessingOrders", "Purchases")
    current_purchases = current_rows(purchase_history, line_key)

    current_categories: dict[str, set[str]] = defaultdict(set)
    current_purchased_lines: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in current_purchases:
        order_id = str(row["orderId"])
        category = status_category.get(str(row.get("statusInternalId") or ""), "")
        if category:
            current_categories[order_id].add(category)
        if category in {"Paid", "Delivered"}:
            current_purchased_lines[order_id].add(line_key(row))

    first_purchased_line_time: dict[tuple[str, str], datetime] = {}
    for row in purchase_history:
        category = status_category.get(str(row.get("statusInternalId") or ""), "")
        row_time = utc(row.get("_rowversion_ts"))
        if category not in {"Paid", "Delivered"} or row_time is None:
            continue
        key = line_key(row)
        previous = first_purchased_line_time.get(key)
        if previous is None or row_time < previous:
            first_purchased_line_time[key] = row_time

    actual_purchase_time: dict[str, datetime] = {}
    for order_id, keys in current_purchased_lines.items():
        times = [first_purchased_line_time[key] for key in keys if key in first_purchased_line_time]
        if times:
            actual_purchase_time[order_id] = max(times)

    merges = current_rows(
        rows("CDP", "MergedCustomers"),
        lambda row: row["unmergedCustomerId"],
    )
    return orders, current_categories, actual_purchase_time, canonical_map(merges)


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    since_msk = datetime.fromisoformat(args.since).replace(tzinfo=MOSCOW)
    till_msk = datetime.fromisoformat(args.till).replace(tzinfo=MOSCOW)
    since_utc = since_msk.astimezone(UTC)
    till_utc = till_msk.astimezone(UTC)

    orders, order_categories, actual_purchase_time, merged = load_delta(
        offline=args.offline
    )
    all_blizko_orders = [
        row
        for row in orders
        if str(row.get("firstPointOfContactInternalId") or "") in BLIZKO_POINTS
        and row.get("unmergedCustomerId") is not None
        and utc(row.get("firstDateTimeUtc")) is not None
        and since_utc <= utc(row["firstDateTimeUtc"]) < till_utc
    ]
    successful_orders = [
        row
        for row in all_blizko_orders
        if order_categories.get(str(row["id"]), set()) & {"Paid", "Delivered"}
    ]

    cart_events: dict[tuple[int, Any], list[datetime]] = defaultdict(list)
    action_ids: set[str] = set()
    action_count = 0
    nonempty_count = 0
    unexpected_templates: set[str] = set()
    unexpected_points: set[str] = set()
    missing_customer = 0
    missing_time = 0

    for action in iter_actions(args.actions):
        action_count += 1
        action_id = str(((action.get("ids") or {}).get("mindboxId")) or "")
        if action_id and action_id in action_ids:
            continue
        if action_id:
            action_ids.add(action_id)

        template = str(
            (((action.get("actionTemplate") or {}).get("ids") or {}).get("systemName"))
            or ""
        )
        if template and template != EXPECTED_CART_TEMPLATE:
            unexpected_templates.add(template)
            continue

        point = str(
            (((action.get("channel") or {}).get("ids") or {}).get("externalId"))
            or ""
        )
        if point not in {"blizkoios", "blizkoandroid"}:
            unexpected_points.add(point)
            continue
        if not action_has_products(action):
            continue
        nonempty_count += 1

        customer_id = action_customer_id(action)
        action_time = utc(action.get("dateTimeUtc"))
        if customer_id is None:
            missing_customer += 1
            continue
        if action_time is None:
            missing_time += 1
            continue
        action_msk = action_time.astimezone(MOSCOW)
        cart_events[(canonical(customer_id, merged), action_msk.date())].append(
            action_time
        )

    for events in cart_events.values():
        events.sort()

    orders_by_customer_day: dict[tuple[int, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in all_blizko_orders:
        order_time = utc(row["firstDateTimeUtc"])
        customer_id = canonical(int(row["unmergedCustomerId"]), merged)
        orders_by_customer_day[(customer_id, order_time.astimezone(MOSCOW).date())].append(
            row
        )
    for rows in orders_by_customer_day.values():
        rows.sort(key=lambda row: utc(row["firstDateTimeUtc"]))

    analyzed_ids = {str(row["id"]) for row in all_blizko_orders}
    matched: list[dict[str, Any]] = []
    reused_cart_events: set[tuple[int, datetime]] = set()
    negative_intervals = 0
    purchase_crossed_day = 0
    no_cart_in_cycle = 0

    for customer_day, day_orders in orders_by_customer_day.items():
        customer_id, _ = customer_day
        events = cart_events.get(customer_day, [])
        previous_order_time: datetime | None = None
        for order in day_orders:
            order_id = str(order["id"])
            order_time = utc(order["firstDateTimeUtc"])
            candidates = [
                event
                for event in events
                if (previous_order_time is None or event > previous_order_time)
                and event <= order_time
                and (customer_id, event) not in reused_cart_events
            ]
            if order_id in analyzed_ids:
                if not candidates:
                    no_cart_in_cycle += 1
                else:
                    cart_time = min(candidates)
                    reused_cart_events.add((customer_id, cart_time))
                    checkout_minutes = (order_time - cart_time).total_seconds() / 60
                    if checkout_minutes < 0:
                        negative_intervals += 1
                    else:
                        purchase_time = actual_purchase_time.get(order_id)
                        purchase_minutes: float | None = None
                        if purchase_time is not None:
                            if (
                                purchase_time.astimezone(MOSCOW).date()
                                == cart_time.astimezone(MOSCOW).date()
                                and purchase_time >= cart_time
                            ):
                                purchase_minutes = (
                                    purchase_time - cart_time
                                ).total_seconds() / 60
                            else:
                                purchase_crossed_day += 1
                        point_id = str(order.get("firstPointOfContactInternalId") or "")
                        matched.append(
                            {
                                "orderKey": alias("ord", order_id),
                                "platform": BLIZKO_POINTS[point_id],
                                "cartAt": cart_time,
                                "orderedAt": order_time,
                                "checkoutMinutes": checkout_minutes,
                                "purchasedAt": purchase_time,
                                "purchaseMinutes": purchase_minutes,
                                "amount": number(
                                    order.get("priceWithDiscounts")
                                    if order.get("priceWithDiscounts") is not None
                                    else order.get("paidAmount")
                                ),
                                "statuses": sorted(order_categories.get(order_id, set())),
                            }
                        )
            previous_order_time = order_time

    matched.sort(key=lambda row: (row["orderedAt"], row["orderKey"]))
    checkout_values = [row["checkoutMinutes"] for row in matched]
    purchase_values = [
        row["purchaseMinutes"] for row in matched if row["purchaseMinutes"] is not None
    ]

    def stats(values: list[float]) -> dict[str, float | int | None]:
        return {
            "count": len(values),
            "mean": sum(values) / len(values) if values else None,
            "median": percentile(values, 0.5),
            "p25": percentile(values, 0.25),
            "p75": percentile(values, 0.75),
            "p90": percentile(values, 0.9),
            "p95": percentile(values, 0.95),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }

    buckets: dict[str, int] = defaultdict(int)
    for value in checkout_values:
        buckets[bucket(value)] += 1

    return {
        "period": {
            "since": since_msk,
            "till": till_msk,
        },
        "source": {
            "actions": action_count,
            "uniqueActions": len(action_ids),
            "nonEmptyCartActions": nonempty_count,
            "allBlizkoOrders": len(all_blizko_orders),
            "successfulBlizkoOrders": len(successful_orders),
        },
        "quality": {
            "matchedOrders": len(matched),
            "noCartInCycle": no_cart_in_cycle,
            "negativeIntervals": negative_intervals,
            "purchaseCrossedDay": purchase_crossed_day,
            "missingActionCustomer": missing_customer,
            "missingActionTime": missing_time,
            "unexpectedTemplates": sorted(unexpected_templates),
            "unexpectedPoints": sorted(value for value in unexpected_points if value),
            "reusedCartEvents": len(matched) - len(reused_cart_events),
        },
        "checkout": stats(checkout_values),
        "actualPurchase": stats(purchase_values),
        "buckets": dict(buckets),
        "orders": matched,
    }


def render_report(result: dict[str, Any], output: Path) -> None:
    period = result["period"]
    source = result["source"]
    quality = result["quality"]
    checkout = result["checkout"]
    actual = result["actualPurchase"]
    orders = result["orders"]
    coverage = (
        len(orders) / source["allBlizkoOrders"] * 100
        if source["allBlizkoOrders"]
        else 0
    )

    lines = [
        "# Blizko: время от первого товара в корзине до покупки",
        "",
        f"**Период:** {fmt_dt(period['since'])} — {fmt_dt(period['till'])} "
        "(московское время, правая граница не включена).",
        "",
        "## Результат",
        "",
        f"- В анализ вошло **{fmt_int(len(orders))} заказов** из "
        f"{fmt_int(source['allBlizkoOrders'])} созданных заказов отдельного "
        f"приложения Blizko (**{coverage:.1f}%**).",
        f"- В среднем от первого непустого состояния корзины до оформления заказа: "
        f"**{fmt_minutes(checkout['mean'])}**.",
        f"- Медиана: **{fmt_minutes(checkout['median'])}**; "
        f"75% заказов оформлены не позднее чем за **{fmt_minutes(checkout['p75'])}**; "
        f"90% — за **{fmt_minutes(checkout['p90'])}**.",
    ]
    if actual["count"]:
        lines.append(
            f"- Для {fmt_int(actual['count'])} заказов удалось найти технический "
            f"timestamp первого статуса `Paid`/`Delivered` внутри того же дня: "
            f"в среднем **{fmt_minutes(actual['mean'])}**, медиана "
            f"**{fmt_minutes(actual['median'])}**."
        )

    lines.extend(
        [
            "",
            "## Распределение",
            "",
            "| Интервал до оформления | Заказов | Доля |",
            "|---|---:|---:|",
        ]
    )
    order_buckets = ["< 5 мин", "5–14 мин", "15–29 мин", "30–59 мин", "1–2 ч", "2–4 ч", "4+ ч"]
    for label in order_buckets:
        count = result["buckets"].get(label, 0)
        share = count / len(orders) * 100 if orders else 0
        lines.append(f"| {label} | {fmt_int(count)} | {share:.1f}% |")

    lines.extend(
        [
            "",
            "## Как считалось",
            "",
            "1. Заказ относится к отдельному приложению Blizko только если его первая "
            "точка контакта — `blizkoios` или `blizkoandroid`; sandbox исключен.",
            "2. Основная точка покупки — создание заказа (`firstDateTimeUtc`). "
            "Это единственная массово заполненная финальная точка в интеграции "
            "отдельного приложения Blizko.",
            "3. Для каждого покупателя и московского календарного дня заказы "
            "упорядочиваются по времени. Для заказа берется первое непустое действие "
            "корзины после предыдущего заказа этого дня и до текущего заказа.",
            "4. Контрольная метрика до `Paid`/`Delivered` рассчитывается только там, "
            "где такой статус реально пришел в Mindbox; его время приближенно "
            "берется из `_rowversion_ts` Delta.",
            "5. Один и тот же cart-event не может быть присвоен двум заказам. "
            "События и заказ должны находиться внутри одного московского дня.",
            "",
            "## Покрытие и проверки качества",
            "",
            f"- Экспортировано действий корзины: {fmt_int(source['actions'])}; "
            f"непустых состояний корзины: "
            f"{fmt_int(source['nonEmptyCartActions'])}.",
            f"- Всего production-заказов Blizko в периоде: "
            f"{fmt_int(source['allBlizkoOrders'])}; с текущей категорией "
            f"`Paid`/`Delivered`: {fmt_int(source['successfulBlizkoOrders'])}.",
            f"- Не найдено подходящего cart-event в цикле заказа: "
            f"{fmt_int(quality['noCartInCycle'])}.",
            f"- Отрицательные интервалы: {quality['negativeIntervals']}; "
            f"повторно использованные cart-events: {quality['reusedCartEvents']}.",
            f"- Фактическая оплата/доставка вышла за границу дня: "
            f"{fmt_int(quality['purchaseCrossedDay'])}; такие заказы остаются "
            "в основной метрике оформления, но исключаются из контрольной метрики.",
            "",
            "> Ограничение: приложение передает операцию «Установка корзины», а не "
            "отдельный неизменяемый timestamp первого добавления. Поэтому первое "
            "непустое состояние корзины в цикле заказа используется как технически "
            "воспроизводимый эквивалент первого добавления.",
            "",
            f"> Критичное ограничение качества: "
            f"{fmt_int(source['allBlizkoOrders'] - source['successfulBlizkoOrders'])} "
            f"из {fmt_int(source['allBlizkoOrders'])} заказов периода не имеют "
            "текущей категории `Paid`/`Delivered`. Интеграция Blizko почти не "
            "передает дальнейшие статусы заказа, поэтому результат отвечает на "
            "вопрос «сколько времени до создания заказа», а не до подтвержденной "
            "оплаты или доставки.",
            "",
            "## Источники",
            "",
            "- [Mindbox: экспорт действий клиентов]"
            "(https://developers.mindbox.ru/docs/export-customer-actions)",
            "- [Mindbox: что такое действие](https://help.mindbox.ru/docs/action)",
            "- [Mindbox: списки продуктов и корзина]"
            "(https://help.mindbox.ru/docs/personal-list)",
            "",
            "## Все заказы, использованные в анализе",
            "",
            "Идентификаторы обезличены SHA-256 и не позволяют восстановить номер "
            "заказа или клиента.",
            "",
            "| # | Заказ | Платформа | Первый товар в корзине, МСК | Оформлен, МСК | "
            "До оформления | Paid/Delivered, МСК | До Paid/Delivered | Сумма | Статусы |",
            "|---:|---|---|---|---|---:|---|---:|---:|---|",
        ]
    )
    for index, row in enumerate(orders, 1):
        lines.append(
            f"| {index} | `{row['orderKey']}` | {row['platform']} | "
            f"{fmt_dt(row['cartAt'])} | {fmt_dt(row['orderedAt'])} | "
            f"{fmt_minutes(row['checkoutMinutes'])} | {fmt_dt(row['purchasedAt'])} | "
            f"{fmt_minutes(row['purchaseMinutes'])} | {fmt_money(row['amount'])} | "
            f"{', '.join(row['statuses']) or '—'} |"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", type=Path, nargs="+", required=True)
    parser.add_argument("--since", default="2026-05-01T00:00:00")
    parser.add_argument("--till", default="2026-07-29T19:00:00")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Использовать локальный data/raw без сетевых запросов Delta Sharing",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "2026-07-29_blizko_cart_to_purchase.md",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "data" / "generated" / "blizko_cart_to_purchase.json",
    )
    args = parser.parse_args()
    missing = [str(path) for path in args.actions if not path.exists()]
    if missing:
        raise RuntimeError("Не найдены файлы действий: " + ", ".join(missing))

    result = analyze(args)
    if result["quality"]["negativeIntervals"]:
        raise RuntimeError("Обнаружены отрицательные интервалы")
    if result["quality"]["reusedCartEvents"]:
        raise RuntimeError("Один cart-event использован несколькими заказами")
    if result["quality"]["unexpectedTemplates"]:
        raise RuntimeError(
            "В выгрузке есть неожиданные шаблоны: "
            + ", ".join(result["quality"]["unexpectedTemplates"])
        )
    if result["quality"]["unexpectedPoints"]:
        raise RuntimeError(
            "В выгрузке есть неожиданные точки контакта: "
            + ", ".join(result["quality"]["unexpectedPoints"])
        )

    render_report(result, args.report)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(json_safe(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(args.report),
                "orders": len(result["orders"]),
                "averageCheckoutMinutes": result["checkout"]["mean"],
                "medianCheckoutMinutes": result["checkout"]["median"],
                "coverage": (
                    len(result["orders"])
                    / result["source"]["allBlizkoOrders"]
                    if result["source"]["allBlizkoOrders"]
                    else 0
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
