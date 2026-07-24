import { NextRequest, NextResponse } from "next/server";

import { supabaseRpc } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const goalId = request.nextUrl.searchParams.get("goalId") ?? "";
  const orderProjectId =
    request.nextUrl.searchParams.get("orderProjectId") ?? "all";
  const rawCampaignIds = request.nextUrl.searchParams.get("campaignIds") ?? "";
  const campaignIds = rawCampaignIds
    .split(",")
    .filter(Boolean)
    .map(Number);

  if (
    !/^[a-z0-9-]+$/.test(goalId) ||
    !/^(all|[a-z0-9-]+)$/.test(orderProjectId) ||
    campaignIds.length > 200 ||
    campaignIds.some(
      (campaignId) =>
        !Number.isSafeInteger(campaignId) || campaignId <= 0,
    )
  ) {
    return NextResponse.json({ error: "Некорректный запрос" }, { status: 400 });
  }

  if (!campaignIds.length) {
    return NextResponse.json({ buyers: 0 });
  }

  try {
    const buyers = await supabaseRpc<number>("push_unique_buyer_count_v2", {
      campaign_ids: campaignIds,
      selected_goal_id: goalId,
      selected_order_project_id: orderProjectId,
    });
    return NextResponse.json(
      { buyers: Number(buyers) },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("Buyer count Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить покупателей из Supabase" },
      { status: 502 },
    );
  }
}
