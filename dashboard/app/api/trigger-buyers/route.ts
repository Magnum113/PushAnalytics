import { NextRequest, NextResponse } from "next/server";

import { supabaseRows, supabaseRpc } from "@/lib/supabase-server";

type LatestMetricRow = { metric_date: string };

export const dynamic = "force-dynamic";

function nextMonth(monthKey: string) {
  const [year, month] = monthKey.split("-").map(Number);
  return month === 12
    ? `${year + 1}-01`
    : `${year}-${String(month + 1).padStart(2, "0")}`;
}

export async function GET(request: NextRequest) {
  const goalId = request.nextUrl.searchParams.get("goalId") ?? "";
  const period = request.nextUrl.searchParams.get("period") ?? "all";
  const mailingIds = (
    request.nextUrl.searchParams.get("scenarioMailingIds") ?? ""
  )
    .split(",")
    .filter(Boolean)
    .map(Number);
  const projectIds = (
    request.nextUrl.searchParams.get("projectIds") ?? ""
  )
    .split(",")
    .filter(Boolean);

  if (
    !/^[a-z0-9-]+$/.test(goalId) ||
    !/^(all|7d|20\d{2}-\d{2})$/.test(period) ||
    mailingIds.length > 200 ||
    mailingIds.length !== projectIds.length ||
    mailingIds.some(
      (mailingId) =>
        !Number.isSafeInteger(mailingId) || mailingId <= 0,
    ) ||
    projectIds.some((projectId) => !/^[a-z0-9-]+$/.test(projectId))
  ) {
    return NextResponse.json({ error: "Некорректный запрос" }, { status: 400 });
  }

  if (!mailingIds.length) {
    return NextResponse.json({ buyers: 0 });
  }

  try {
    let purchasedFrom: string | null = null;
    let purchasedUntil: string | null = null;
    if (/^20\d{2}-\d{2}$/.test(period)) {
      purchasedFrom = `${period}-01T00:00:00+03:00`;
      purchasedUntil = `${nextMonth(period)}-01T00:00:00+03:00`;
    } else if (period === "7d") {
      const [latestMetric] = await supabaseRows<LatestMetricRow>(
        "push_scenario_daily_metrics",
        {
          select: "metric_date",
          order: "metric_date.desc",
          limit: "1",
        },
      );
      if (!latestMetric) {
        return NextResponse.json({ buyers: 0 });
      }
      const coverageEnd = new Date(
        `${latestMetric.metric_date}T23:59:59.999+03:00`,
      );
      purchasedFrom = new Date(
        coverageEnd.getTime() - 7 * 24 * 60 * 60 * 1000,
      ).toISOString();
      purchasedUntil = new Date(coverageEnd.getTime() + 1).toISOString();
    }

    const buyers = await supabaseRpc<number>(
      "push_trigger_matching_project_unique_buyer_count",
      {
        scenario_mailing_ids: mailingIds,
        project_ids: projectIds,
        selected_goal_id: goalId,
        purchased_from: purchasedFrom,
        purchased_until: purchasedUntil,
      },
    );
    return NextResponse.json(
      { buyers: Number(buyers) },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("Trigger buyer count Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить покупателей trigger-пушей" },
      { status: 502 },
    );
  }
}
