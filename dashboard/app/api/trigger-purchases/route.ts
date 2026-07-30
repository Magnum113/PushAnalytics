import { NextRequest, NextResponse } from "next/server";

import { pgMetaQuery, supabaseRows } from "@/lib/supabase-server";

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
type LatestMetricRow = { metric_date: string };

function postgrestIn(values: string[]) {
  return `in.(${values
    .map((value) => `"${value.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`)
    .join(",")})`;
}

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const scenarioMailingId = Number(
    request.nextUrl.searchParams.get("scenarioMailingId"),
  );
  const goalId = request.nextUrl.searchParams.get("goalId") ?? "";
  const period = request.nextUrl.searchParams.get("period") ?? "all";
  if (
    !Number.isSafeInteger(scenarioMailingId) ||
    scenarioMailingId <= 0 ||
    !/^[a-z0-9-]+$/.test(goalId) ||
    !/^(all|7d|20\d{2}-\d{2})$/.test(period)
  ) {
    return NextResponse.json({ error: "Некорректный запрос" }, { status: 400 });
  }

  try {
    const [mailing] = await pgMetaQuery<{ project_id: string }>(`
      select
        coalesce(manual.project_id, mailing.project_id) as project_id
      from public.push_scenario_mailings as mailing
      left join public.push_manual_overrides as manual
        on manual.source_kind = 'trigger'
       and manual.scenario_mailing_id = mailing.id
      where mailing.id = ${scenarioMailingId}
      limit 1
    `);
    if (!mailing) {
      return NextResponse.json(
        { error: "Trigger-пуш не найден" },
        { status: 404 },
      );
    }
    const baseFilters: Record<string, string> = {
      select:
        "id,order_key,buyer_key,purchased_at,attributed_click_at,latency_minutes,revenue,order_project_id",
      scenario_mailing_id: `eq.${scenarioMailingId}`,
      goal_id: `eq.${goalId}`,
      order_project_id: `eq.${mailing.project_id}`,
      order: "purchased_at.desc",
    };
    if (/^20\d{2}-\d{2}$/.test(period)) {
      const [year, month] = period.split("-").map(Number);
      const nextMonth = month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
      baseFilters.purchased_at = `gte.${period}-01T00:00:00+03:00`;
      baseFilters.and = `(purchased_at.lt.${nextMonth}-01T00:00:00+03:00)`;
    }
    let orders = await supabaseRows<OrderRow>(
      "push_trigger_attributed_orders",
      baseFilters,
    );
    if (period === "7d") {
      const [latestMetric] = await supabaseRows<LatestMetricRow>(
        "push_scenario_daily_metrics",
        {
          select: "metric_date",
          order: "metric_date.desc",
          limit: "1",
        },
      );
      const latest = latestMetric
        ? new Date(`${latestMetric.metric_date}T23:59:59+03:00`).getTime()
        : 0;
      orders = orders.filter(
        (order) =>
          new Date(order.purchased_at).getTime() >=
          latest - 7 * 24 * 60 * 60 * 1000,
      );
    }

    const orderIds = orders.map((order) => order.id);
    const items = orderIds.length
      ? await supabaseRows<ItemRow>("push_trigger_attributed_order_items", {
          select:
            "attributed_order_id,line_key,product_internal_id,product_external_id,display_name,quantity,quantity_type,unit_price,line_amount,status_category",
          attributed_order_id: `in.(${orderIds.join(",")})`,
          order: "attributed_order_id.asc,id.asc",
        })
      : [];
    const internalIds = [
      ...new Set(
        items
          .map((item) => item.product_internal_id)
          .filter((value): value is string => Boolean(value)),
      ),
    ];
    const externalIds = [
      ...new Set(
        items
          .map((item) => item.product_external_id)
          .filter((value): value is string => Boolean(value)),
      ),
    ];
    const [byInternal, byExternal] = await Promise.all([
      internalIds.length
        ? supabaseRows<ProductRow>("push_products", {
            select: "product_internal_id,name,vendor_code,external_id",
            product_internal_id: postgrestIn(internalIds),
          })
        : [],
      externalIds.length
        ? supabaseRows<ProductRow>("push_products", {
            select: "product_internal_id,name,vendor_code,external_id",
            external_id: postgrestIn(externalIds),
          })
        : [],
    ]);
    const productByInternal = new Map(
      byInternal.map((product) => [product.product_internal_id, product]),
    );
    const productByExternal = new Map(
      byExternal
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
                ? productByInternal.get(item.product_internal_id)
                : undefined) ??
              (item.product_external_id
                ? productByExternal.get(item.product_external_id)
                : undefined);
            return {
              lineKey: item.line_key,
              displayName: product?.name ?? item.display_name,
              vendorCode: product?.vendor_code ?? null,
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
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("Trigger purchases Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить покупки trigger-пуша" },
      { status: 502 },
    );
  }
}
