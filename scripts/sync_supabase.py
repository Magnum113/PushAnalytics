#!/usr/bin/env python3
"""Upsert the PII-free dashboard aggregate into self-hosted Supabase."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import certifi

from mindbox_delta import ROOT, load_env


DATASET = ROOT / "dashboard" / "public" / "data" / "dashboard.json"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class SupabaseRest:
    def __init__(self, base_url: str, service_role_key: str):
        self.base_url = base_url.rstrip("/")
        self.service_role_key = service_role_key

    def request(
        self,
        table: str,
        *,
        method: str,
        payload: Any | None = None,
        query: str = "",
        prefer: str = "return=representation",
    ) -> Any:
        suffix = f"?{query}" if query else ""
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/rest/v1/{table}{suffix}",
            data=body,
            method=method,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Prefer": prefer,
                "User-Agent": "PushAnalytics/0.2",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
                context=SSL_CONTEXT,
            ) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else None
        except urllib.error.HTTPError as error:
            response_body = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"Supabase REST {method} {table}: HTTP {error.code}: "
                f"{response_body}"
            ) from error


def campaign_payload(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    generated_at = dataset["generatedAt"]
    attribution = dataset["attribution"]
    rows: list[dict[str, Any]] = []
    for push in dataset["pushes"]:
        assignment = push.get("projectAssignment", {})
        platforms = push["platforms"]
        rows.append(
            {
                "campaign_key": push["id"],
                "project_id": push["projectId"],
                "project_assignment_source": assignment.get("source", "fallback"),
                "project_assignment_reason": assignment.get("reason"),
                "name": push["name"],
                "title": push["title"],
                "body": push["body"],
                "sent_at": push["sentAt"],
                "attribution_status": push["status"],
                "attribution_window_hours": attribution["windowHours"],
                "attribution_model": "last_click",
                "source": dataset["source"],
                "mailing_ids": push.get("mailingIds", push["id"].split("+")),
                "folder_internal_ids": push.get("folderInternalIds", []),
                "application_names": push.get("applications", []),
                "sent": push["sent"],
                "delivered": push["delivered"],
                "clicked": push["clicked"],
                "not_delivered": push["notDelivered"],
                "platform_ios": platforms["ios"],
                "platform_android": platforms["android"],
                "platform_unknown": platforms["unknown"],
                "generated_at": generated_at,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    return rows


def goal_metric_payload(
    dataset: dict[str, Any],
    campaign_ids: dict[str, int],
) -> list[dict[str, Any]]:
    generated_at = dataset["generatedAt"]
    rows: list[dict[str, Any]] = []
    for push in dataset["pushes"]:
        campaign_id = campaign_ids[push["id"]]
        for goal_id, metric in push["goals"].items():
            latency = metric["latency"]
            rows.append(
                {
                    "campaign_id": campaign_id,
                    "goal_id": goal_id,
                    "orders": metric["orders"],
                    "buyers": metric["buyers"],
                    "revenue": metric["revenue"],
                    "latency_0_1h": latency[0],
                    "latency_1_4h": latency[1],
                    "latency_4_12h": latency[2],
                    "latency_12_24h": latency[3],
                    "generated_at": generated_at,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
    return rows


def attributed_order_payload(
    dataset: dict[str, Any],
    campaign_ids: dict[str, int],
) -> list[dict[str, Any]]:
    generated_at = dataset["generatedAt"]
    rows: list[dict[str, Any]] = []
    for push in dataset["pushes"]:
        campaign_id = campaign_ids[push["id"]]
        for goal_id, orders in push.get("attributedOrders", {}).items():
            for order in orders:
                rows.append(
                    {
                        "campaign_id": campaign_id,
                        "goal_id": goal_id,
                        "order_key": order["orderKey"],
                        "buyer_key": order["buyerKey"],
                        "purchased_at": order["purchasedAt"],
                        "attributed_click_at": order["attributedClickAt"],
                        "latency_minutes": order["latencyMinutes"],
                        "revenue": order["revenue"],
                        "first_point_of_contact_id": (
                            order.get("firstPointOfContactId") or None
                        ),
                        "order_project_id": order["orderProjectId"],
                        "status_categories": order.get("statusCategories", []),
                        "status_external_ids": order.get("statusExternalIds", []),
                        "generated_at": generated_at,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
    return rows


def attributed_item_payload(
    dataset: dict[str, Any],
    campaign_ids: dict[str, int],
    attributed_order_ids: dict[tuple[int, str, str], int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for push in dataset["pushes"]:
        campaign_id = campaign_ids[push["id"]]
        for goal_id, orders in push.get("attributedOrders", {}).items():
            for order in orders:
                attributed_order_id = attributed_order_ids[
                    (campaign_id, goal_id, order["orderKey"])
                ]
                for item in order.get("items", []):
                    rows.append(
                        {
                            "attributed_order_id": attributed_order_id,
                            "line_key": item["lineKey"],
                            "product_internal_id": (
                                item.get("productInternalId") or None
                            ),
                            "product_external_id": (
                                item.get("productExternalId") or None
                            ),
                            "product_external_system_id": (
                                item.get("productExternalSystemId") or None
                            ),
                            "display_name": item["displayName"],
                            "quantity": item["quantity"],
                            "quantity_type": item.get("quantityType") or None,
                            "unit_price": item.get("unitPrice"),
                            "line_amount": item.get("lineAmount"),
                            "status_internal_id": (
                                item.get("statusInternalId") or None
                            ),
                            "status_category": (
                                item.get("statusCategory") or None
                            ),
                            "status_external_id": (
                                item.get("statusExternalId") or None
                            ),
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверить локальный payload без записи в Supabase",
    )
    args = parser.parse_args()

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    campaigns = campaign_payload(dataset)
    metric_count = sum(len(push["goals"]) for push in dataset["pushes"])
    attributed_order_count = sum(
        len(orders)
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
    )
    attributed_item_count = sum(
        len(order.get("items", []))
        for push in dataset["pushes"]
        for orders in push.get("attributedOrders", {}).values()
        for order in orders
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "campaigns": len(campaigns),
                    "goalMetrics": metric_count,
                    "attributedOrders": attributed_order_count,
                    "attributedOrderItems": attributed_item_count,
                    "projects": sorted(
                        {campaign["project_id"] for campaign in campaigns}
                    ),
                    "containsCustomerIdentifiers": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    env = load_env()
    base_url = env.get("NEXT_PUBLIC_SUPABASE_URL", "").strip()
    service_role_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base_url or not service_role_key:
        raise RuntimeError(
            "Для серверной синхронизации добавьте в PushAnalytics/.env "
            "SUPABASE_SERVICE_ROLE_KEY. NEXT_PUBLIC_SUPABASE_ANON_KEY "
            "предназначен только для чтения и не используется для записи."
        )

    client = SupabaseRest(base_url, service_role_key)
    sync_runs = client.request(
        "push_sync_runs",
        method="POST",
        payload={
            "status": "running",
            "source": dataset["source"],
            "generated_at": dataset["generatedAt"],
        },
    )
    sync_run_id = int(sync_runs[0]["id"])

    try:
        saved_campaigns = client.request(
            "push_campaigns",
            method="POST",
            payload=campaigns,
            query=urllib.parse.urlencode({"on_conflict": "campaign_key"}),
            prefer="resolution=merge-duplicates,return=representation",
        )
        campaign_ids = {
            str(row["campaign_key"]): int(row["id"]) for row in saved_campaigns
        }
        metrics = goal_metric_payload(dataset, campaign_ids)
        client.request(
            "push_campaign_goal_metrics",
            method="POST",
            payload=metrics,
            query=urllib.parse.urlencode(
                {"on_conflict": "campaign_id,goal_id"},
            ),
            prefer="resolution=merge-duplicates,return=minimal",
        )
        client.request(
            "push_attributed_orders",
            method="DELETE",
            query=urllib.parse.urlencode(
                {
                    "campaign_id": (
                        "in.(" + ",".join(map(str, campaign_ids.values())) + ")"
                    )
                },
            ),
            prefer="return=minimal",
        )
        attributed_orders = attributed_order_payload(dataset, campaign_ids)
        saved_attributed_orders = (
            client.request(
                "push_attributed_orders",
                method="POST",
                payload=attributed_orders,
                prefer="return=representation",
            )
            if attributed_orders
            else []
        )
        attributed_order_ids = {
            (
                int(row["campaign_id"]),
                str(row["goal_id"]),
                str(row["order_key"]),
            ): int(row["id"])
            for row in saved_attributed_orders
        }
        attributed_items = attributed_item_payload(
            dataset,
            campaign_ids,
            attributed_order_ids,
        )
        if attributed_items:
            client.request(
                "push_attributed_order_items",
                method="POST",
                payload=attributed_items,
                prefer="return=minimal",
            )
        client.request(
            "push_sync_runs",
            method="PATCH",
            query=urllib.parse.urlencode({"id": f"eq.{sync_run_id}"}),
            payload={
                "status": "succeeded",
                "finished_at": datetime.now(UTC).isoformat(),
                "campaigns_upserted": len(saved_campaigns),
                "metadata": {
                    "goalMetricsUpserted": len(metrics),
                    "attributedOrdersUpserted": len(attributed_orders),
                    "attributedOrderItemsUpserted": len(attributed_items),
                },
            },
            prefer="return=minimal",
        )
    except Exception as error:
        client.request(
            "push_sync_runs",
            method="PATCH",
            query=urllib.parse.urlencode({"id": f"eq.{sync_run_id}"}),
            payload={
                "status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "error_message": str(error)[:1000],
            },
            prefer="return=minimal",
        )
        raise

    print(
        json.dumps(
            {
                "syncRunId": sync_run_id,
                "campaignsUpserted": len(saved_campaigns),
                "goalMetricsUpserted": len(metrics),
                "attributedOrdersUpserted": len(attributed_orders),
                "attributedOrderItemsUpserted": len(attributed_items),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
