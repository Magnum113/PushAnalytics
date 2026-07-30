import { NextRequest, NextResponse } from "next/server";

import { supabaseRpc } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const goalId = request.nextUrl.searchParams.get("goalId") ?? "";
  const rawCampaignIds = request.nextUrl.searchParams.get("campaignIds") ?? "";
  const rawProjectIds = request.nextUrl.searchParams.get("projectIds") ?? "";
  const campaignIds = rawCampaignIds
    .split(",")
    .filter(Boolean)
    .map(Number);
  const projectIds = rawProjectIds.split(",").filter(Boolean);

  if (
    !/^[a-z0-9-]+$/.test(goalId) ||
    campaignIds.length > 200 ||
    campaignIds.length !== projectIds.length ||
    campaignIds.some(
      (campaignId) =>
        !Number.isSafeInteger(campaignId) || campaignId <= 0,
    ) ||
    projectIds.some((projectId) => !/^[a-z0-9-]+$/.test(projectId))
  ) {
    return NextResponse.json({ error: "Некорректный запрос" }, { status: 400 });
  }

  if (!campaignIds.length) {
    return NextResponse.json({ buyers: 0 });
  }

  try {
    const buyers = await supabaseRpc<number>(
      "push_matching_project_unique_buyer_count",
      {
        campaign_ids: campaignIds,
        project_ids: projectIds,
        selected_goal_id: goalId,
      },
    );
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
