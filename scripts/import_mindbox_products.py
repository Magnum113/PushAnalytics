#!/usr/bin/env python3
"""Import a Mindbox product CSV and enrich attributed purchase lines.

Mindbox's analytics export contains order lines and product identifiers, while
human-readable names live in the product catalog. This script joins both
sources without storing customer or raw order identifiers.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sync_supabase_pg_meta import execute_sql


JSON_DELIMITER = "$push_product_catalog$"
MAX_PAYLOAD_BYTES = 600_000

ALIASES = {
    "product_internal_id": {
        "internalid",
        "productinternalid",
        "mindboxid",
        "идентификатормindbox",
        "внутреннийидентификатор",
        "внутреннийидентификаторпродукта",
    },
    "name": {
        "name",
        "productname",
        "название",
        "названиепродукта",
        "наименованиетовара",
        "наименованиепродукта",
    },
    "vendor_code": {
        "vendorcode",
        "productvendorcode",
        "article",
        "sku",
        "артикул",
        "кодтовара",
    },
    "external_id": {
        "externalid",
        "productexternalid",
        "внешнийидентификатор",
        "внешнийидентификаторпродукта",
    },
    "external_system_id": {
        "externalsystemid",
        "externalsysteminternalid",
        "системавнешнегоидентификатора",
        "внешняясистема",
    },
    "picture_url": {
        "pictureurl",
        "productpictureurl",
        "imageurl",
        "photo",
        "фото",
        "изображение",
        "ссылкаизображения",
    },
}


def normalized_header(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", value)


def decode_csv(path: Path) -> str:
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Не удалось определить кодировку CSV")


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = decode_csv(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    headers = [header.strip() for header in (reader.fieldnames or []) if header]
    if not headers:
        raise RuntimeError("В CSV не найдена строка заголовков")
    rows = [
        {
            str(key).strip(): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        for row in reader
    ]
    return headers, rows


def resolve_column(
    headers: list[str],
    field: str,
    explicit: str | None,
    *,
    required: bool,
) -> str | None:
    if explicit:
        if explicit not in headers:
            raise RuntimeError(
                f"Колонка {explicit!r} отсутствует. Доступны: {', '.join(headers)}"
            )
        return explicit
    normalized = {header: normalized_header(header) for header in headers}
    for header, value in normalized.items():
        if value in ALIASES[field]:
            return header
    if required:
        option = field.replace("_", "-")
        raise RuntimeError(
            f"Не удалось определить колонку {field!r}. Доступны: "
            f"{', '.join(headers)}. Укажите её через --{option}-column."
        )
    return None


def build_products(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
    *,
    identifier_columns: list[str],
    purchase_refs: dict[str, str | None] | None,
) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    reference_lookup: dict[str, set[str]] = {}
    if purchase_refs is not None:
        for internal_id, external_id in purchase_refs.items():
            for identifier in (internal_id, external_id):
                if not identifier:
                    continue
                reference_lookup.setdefault(identifier, set()).add(internal_id)
    now = datetime.now(UTC).isoformat()
    for row in rows:
        name = row.get(columns["name"] or "", "").strip()
        if not name:
            continue
        source_internal_id = row.get(
            columns["product_internal_id"] or "", ""
        ).strip()
        identifiers = {
            row.get(column, "").strip()
            for column in identifier_columns
            if row.get(column, "").strip()
        }
        if source_internal_id:
            identifiers.add(source_internal_id)
        if purchase_refs is None:
            target_internal_ids = (
                {source_internal_id} if source_internal_id else set()
            )
        else:
            target_internal_ids = {
                internal_id
                for identifier in identifiers
                for internal_id in reference_lookup.get(identifier, set())
            }
        for internal_id in target_internal_ids:
            products[internal_id] = {
                "productInternalId": internal_id,
                "name": name,
                "vendorCode": (
                    row.get(columns["vendor_code"] or "", "").strip() or None
                ),
                "externalId": (
                    purchase_refs.get(internal_id)
                    if purchase_refs is not None
                    else row.get(columns["external_id"] or "", "").strip() or None
                ),
                "externalSystemId": (
                    row.get(
                        columns["external_system_id"] or "", ""
                    ).strip()
                    or None
                ),
                "pictureUrl": (
                    row.get(columns["picture_url"] or "", "").strip() or None
                ),
                "sourceUpdatedAt": now,
            }
    return list(products.values())


def build_sql(products: list[dict[str, Any]]) -> str:
    payload = json.dumps(products, ensure_ascii=False, separators=(",", ":"))
    if JSON_DELIMITER in payload:
        raise RuntimeError("Каталог неожиданно содержит SQL-разделитель")
    return f"""
begin;

create temporary table push_product_catalog_payload (
  doc jsonb not null
) on commit drop;

insert into push_product_catalog_payload (doc)
values ({JSON_DELIMITER}{payload}{JSON_DELIMITER}::jsonb);

with product_rows as (
  select product
  from push_product_catalog_payload
  cross join lateral jsonb_array_elements(doc) as rows(product)
)
insert into public.push_products (
  product_internal_id,
  name,
  vendor_code,
  external_id,
  external_system_id,
  picture_url,
  source,
  source_updated_at,
  updated_at
)
select
  product->>'productInternalId',
  product->>'name',
  nullif(product->>'vendorCode', ''),
  nullif(product->>'externalId', ''),
  nullif(product->>'externalSystemId', ''),
  nullif(product->>'pictureUrl', ''),
  'mindbox_product_export',
  (product->>'sourceUpdatedAt')::timestamptz,
  now()
from product_rows
on conflict (product_internal_id) do update
set
  name = excluded.name,
  vendor_code = excluded.vendor_code,
  external_id = excluded.external_id,
  external_system_id = excluded.external_system_id,
  picture_url = excluded.picture_url,
  source = excluded.source,
  source_updated_at = excluded.source_updated_at,
  updated_at = now();

update public.push_attributed_order_items as item
set
  display_name = product.name,
  updated_at = now()
from public.push_products as product
where
  product.product_internal_id = item.product_internal_id
  and item.display_name is distinct from product.name;

commit;

select json_build_object(
  'catalogProducts', (select count(*) from public.push_products),
  'namedPurchaseLines', (
    select count(*)
    from public.push_attributed_order_items as item
    join public.push_products as product
      on product.product_internal_id = item.product_internal_id
  ),
  'unresolvedPurchaseLines', (
    select count(*)
    from public.push_attributed_order_items as item
    left join public.push_products as product
      on product.product_internal_id = item.product_internal_id
    where product.product_internal_id is null
  )
) as result;
"""


def split_products(
    products: list[dict[str, Any]],
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for product in products:
        candidate = [*current, product]
        size = len(
            json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if current and size > max_payload_bytes:
            chunks.append(current)
            current = [product]
        else:
            current.append(product)
    if current:
        chunks.append(current)
    return chunks


def purchase_product_refs() -> dict[str, str | None]:
    rows = execute_sql(
        """
        select distinct on (product_internal_id)
          product_internal_id,
          product_external_id
        from public.push_attributed_order_items
        where product_internal_id is not null
        order by
          product_internal_id,
          (product_external_id is not null) desc;
        """
    )
    return {
        str(row["product_internal_id"]): (
            str(row["product_external_id"])
            if row.get("product_external_id")
            else None
        )
        for row in rows
        if row.get("product_internal_id")
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Импортировать CSV каталога Mindbox в Supabase"
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--product-internal-id-column")
    parser.add_argument("--name-column")
    parser.add_argument("--vendor-code-column")
    parser.add_argument("--external-id-column")
    parser.add_argument("--external-system-id-column")
    parser.add_argument("--picture-url-column")
    parser.add_argument(
        "--all-products",
        action="store_true",
        help="Импортировать весь экспорт, а не только товары из заказов дашборда",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv_path.is_file():
        raise RuntimeError(f"Файл не найден: {args.csv_path}")
    headers, rows = read_rows(args.csv_path)
    columns = {
        "product_internal_id": resolve_column(
            headers,
            "product_internal_id",
            args.product_internal_id_column,
            required=False,
        ),
        "name": resolve_column(
            headers, "name", args.name_column, required=True
        ),
        "vendor_code": resolve_column(
            headers,
            "vendor_code",
            args.vendor_code_column,
            required=False,
        ),
        "external_id": resolve_column(
            headers,
            "external_id",
            args.external_id_column,
            required=False,
        ),
        "external_system_id": resolve_column(
            headers,
            "external_system_id",
            args.external_system_id_column,
            required=False,
        ),
        "picture_url": resolve_column(
            headers,
            "picture_url",
            args.picture_url_column,
            required=False,
        ),
    }
    identifier_columns = [
        header
        for header in headers
        if normalized_header(header).startswith("productids")
    ]
    if columns["external_id"]:
        identifier_columns.append(columns["external_id"])
    needed_products: dict[str, str | None] | None = None
    if not args.all_products:
        needed_products = purchase_product_refs()
    products = build_products(
        rows,
        columns,
        identifier_columns=sorted(set(identifier_columns)),
        purchase_refs=needed_products,
    )
    if args.all_products and not columns["product_internal_id"]:
        raise RuntimeError(
            "В экспорте нет внутреннего ID Mindbox: полный импорт невозможен. "
            "Импортируйте товары заказов без --all-products."
        )
    if not products:
        raise RuntimeError(
            "В CSV нет строк одновременно с внутренним ID Mindbox и названием"
        )
    chunks = split_products(products)
    print(
        json.dumps(
            {
                "sourceRows": len(rows),
                "productsReady": len(products),
                "purchaseProductsRequested": (
                    len(needed_products)
                    if needed_products is not None
                    else None
                ),
                "identifierColumns": identifier_columns,
                "chunks": len(chunks),
                "columns": columns,
                "dryRun": args.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.dry_run:
        for chunk in chunks:
            execute_sql(build_sql(chunk))
        result = execute_sql(
            """
            select json_build_object(
              'catalogProducts', (
                select count(*) from public.push_products
              ),
              'namedPurchaseLines', (
                select count(*)
                from public.push_attributed_order_items as item
                join public.push_products as product
                  on product.product_internal_id = item.product_internal_id
              ),
              'unresolvedPurchaseLines', (
                select count(*)
                from public.push_attributed_order_items as item
                left join public.push_products as product
                  on product.product_internal_id = item.product_internal_id
                where product.product_internal_id is null
              )
            ) as result;
            """
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1) from error
