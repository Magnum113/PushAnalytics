import { NextRequest, NextResponse } from "next/server";

import { supabaseRows } from "@/lib/supabase-server";

type OrderRow = {
  id: number;
  order_key: string;
  buyer_key: string;
  purchased_at: string;
  attributed_click_at: string;
  latency_minutes: number;
  revenue: number;
  order_project_id: string;
};

type ItemRow = {
  attributed_order_id: number;
  line_key: string;
  product_internal_id: string | null;
  product_external_id: string | null;
  display_name: string;
  quantity: number;
  quantity_type: string | null;
  unit_price: number | null;
  line_amount: number | null;
  status_category: string | null;
};

type ProductRow = {
  product_internal_id: string;
  name: string;
  vendor_code: string | null;
  external_id: string | null;
};

function postgrestIn(values: string[]) {
  return `in.(${values
    .map((value) => `"${value.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`)
    .join(",")})`;
}

function chunks<T>(values: T[], size: number): T[][] {
  return Array.from(
    { length: Math.ceil(values.length / size) },
    (_, index) => values.slice(index * size, (index + 1) * size),
  );
}

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const campaignId = Number(request.nextUrl.searchParams.get("campaignId"));
  const goalId = request.nextUrl.searchParams.get("goalId") ?? "";
  const orderProjectId =
    request.nextUrl.searchParams.get("orderProjectId") ?? "all";
  if (
    !Number.isSafeInteger(campaignId) ||
    campaignId <= 0 ||
    !/^[a-z0-9-]+$/.test(goalId) ||
    !/^(all|[a-z0-9-]+)$/.test(orderProjectId)
  ) {
    return NextResponse.json({ error: "Некорректный запрос" }, { status: 400 });
  }

  try {
    const orders = await supabaseRows<OrderRow>("push_attributed_orders", {
      select:
        "id,order_key,buyer_key,purchased_at,attributed_click_at,latency_minutes,revenue,order_project_id",
      campaign_id: `eq.${campaignId}`,
      goal_id: `eq.${goalId}`,
      ...(orderProjectId === "all"
        ? {}
        : { order_project_id: `eq.${orderProjectId}` }),
      order: "purchased_at.desc",
    });
    const orderIds = orders.map((order) => order.id);
    const items = orderIds.length
      ? await supabaseRows<ItemRow>("push_attributed_order_items", {
          select:
            "attributed_order_id,line_key,product_internal_id,product_external_id,display_name,quantity,quantity_type,unit_price,line_amount,status_category",
          attributed_order_id: `in.(${orderIds.join(",")})`,
          order: "attributed_order_id.asc,id.asc",
        })
      : [];
    const productInternalIds = [
      ...new Set(
        items
          .map((item) => item.product_internal_id)
          .filter((value): value is string => Boolean(value)),
      ),
    ];
    const productExternalIds = [
      ...new Set(
        items
          .map((item) => item.product_external_id)
          .filter((value): value is string => Boolean(value)),
      ),
    ];
    const [productsByInternalId, productsByExternalId] = await Promise.all([
      Promise.all(
        chunks(productInternalIds, 80).map((ids) =>
          supabaseRows<ProductRow>("push_products", {
            select: "product_internal_id,name,vendor_code,external_id",
            product_internal_id: postgrestIn(ids),
          }),
        ),
      ).then((groups) => groups.flat()),
      Promise.all(
        chunks(productExternalIds, 80).map((ids) =>
          supabaseRows<ProductRow>("push_products", {
            select: "product_internal_id,name,vendor_code,external_id",
            external_id: postgrestIn(ids),
          }),
        ),
      ).then((groups) => groups.flat()),
    ]);
    const productByInternalId = new Map(
      productsByInternalId.map((product) => [
        product.product_internal_id,
        product,
      ]),
    );
    const productByExternalId = new Map(
      productsByExternalId
        .filter((product) => product.external_id)
        .map((product) => [product.external_id as string, product]),
    );

    const itemsByOrder = new Map<number, ItemRow[]>();
    for (const item of items) {
      const rows = itemsByOrder.get(item.attributed_order_id) ?? [];
      rows.push(item);
      itemsByOrder.set(item.attributed_order_id, rows);
    }

    return NextResponse.json(
      {
        buyers: new Set(orders.map((order) => order.buyer_key)).size,
        orders: orders.map((order) => ({
          id: order.id,
          orderKey: order.order_key,
          purchasedAt: order.purchased_at,
          attributedClickAt: order.attributed_click_at,
          latencyMinutes: Number(order.latency_minutes),
          revenue: Number(order.revenue),
          orderProjectId: order.order_project_id,
          items: (itemsByOrder.get(order.id) ?? []).map((item) => {
            const product =
              (item.product_internal_id
                ? productByInternalId.get(item.product_internal_id)
                : undefined) ??
              (item.product_external_id
                ? productByExternalId.get(item.product_external_id)
                : undefined);
            return {
              lineKey: item.line_key,
              productInternalId: item.product_internal_id,
              productExternalId: item.product_external_id,
              productName: product?.name ?? null,
              vendorCode: product?.vendor_code ?? null,
              displayName: product?.name ?? item.display_name,
              catalogMatched: Boolean(product),
              quantity: Number(item.quantity),
              quantityType: item.quantity_type,
              unitPrice:
                item.unit_price === null ? null : Number(item.unit_price),
              lineAmount:
                item.line_amount === null ? null : Number(item.line_amount),
              statusCategory: item.status_category,
            };
          }),
        })),
      },
      {
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  } catch (error) {
    console.error("Purchase details Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить покупки из Supabase" },
      { status: 502 },
    );
  }
}
