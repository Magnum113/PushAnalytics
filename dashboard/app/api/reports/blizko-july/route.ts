import { NextResponse } from "next/server";

import {
  applyPushOverride,
  mapOverrides,
  PUSH_OVERRIDES_SELECT,
  type PushManualOverrideRow,
} from "@/lib/push-overrides";
import {
  pgMetaQuery,
  supabaseRows,
  supabaseRpc,
} from "@/lib/supabase-server";

type CampaignRow = {
  id: number;
  campaign_key: string;
  project_id: string;
  name: string;
  title: string;
  body: string;
  application_names: string[];
  sent_at: string;
  sent: number;
  delivered: number;
  clicked: number;
  not_delivered: number;
  generated_at: string;
};

type MetricRow = {
  campaign_id: number;
  goal_id: string;
  order_project_id: string;
  orders: number;
  buyers: number;
  revenue: number;
};

const JULY_START = new Date("2026-06-30T21:00:00.000Z");
const AUGUST_START = new Date("2026-07-31T21:00:00.000Z");
const RESEARCH_PATTERN =
  /опрос|расскажите|интервью|вопрос|промокод за пару минут|поделитесь/i;

export const dynamic = "force-dynamic";

function isJulyMoscow(value: string) {
  const date = new Date(value);
  return date >= JULY_START && date < AUGUST_START;
}

export async function GET() {
  try {
    const [sourceCampaigns, overrides] = await Promise.all([
      supabaseRows<CampaignRow>("push_campaigns", {
        select:
          "id,campaign_key,project_id,name,title,body,application_names,sent_at,sent,delivered,clicked,not_delivered,generated_at",
        order: "sent_at.asc",
      }),
      pgMetaQuery<PushManualOverrideRow>(PUSH_OVERRIDES_SELECT),
    ]);
    const overrideByCampaign = mapOverrides(overrides, "mass");
    const campaigns = sourceCampaigns
      .map((campaign) =>
        applyPushOverride(
          campaign,
          overrideByCampaign.get(campaign.id) ?? undefined,
        ),
      )
      .filter(
        (campaign) =>
          !campaign.isHidden &&
          campaign.project_id === "blizko-app" &&
          isJulyMoscow(campaign.sent_at),
      );

    const campaignIds = campaigns.map((campaign) => campaign.id);
    const idFilter = `in.(${campaignIds.join(",")})`;
    const metrics = campaignIds.length
      ? await supabaseRows<MetricRow>(
          "push_campaign_goal_order_project_metrics",
          {
            select:
              "campaign_id,goal_id,order_project_id,orders,buyers,revenue",
            campaign_id: idFilter,
            goal_id: "eq.all-orders",
          },
        )
      : [];

    const uniqueBuyers = campaignIds.length
      ? await supabaseRpc<number>("push_unique_buyer_count_v2", {
          campaign_ids: campaignIds,
          selected_goal_id: "all-orders",
          selected_order_project_id: "blizko-app",
        })
      : 0;

    const metricsByCampaign = new Map<
      number,
      Map<string, { orders: number; buyers: number; revenue: number }>
    >();
    for (const metric of metrics) {
      const campaignMetrics =
        metricsByCampaign.get(metric.campaign_id) ?? new Map();
      campaignMetrics.set(metric.order_project_id, {
        orders: Number(metric.orders),
        buyers: Number(metric.buyers),
        revenue: Number(metric.revenue),
      });
      metricsByCampaign.set(metric.campaign_id, campaignMetrics);
    }

    const reportCampaigns = campaigns.map((campaign) => {
      const projectMetrics = metricsByCampaign.get(campaign.id) ?? new Map();
      const target = projectMetrics.get("blizko-app") ?? {
        orders: 0,
        buyers: 0,
        revenue: 0,
      };
      const allProjects = [...projectMetrics.values()].reduce(
        (total, metric) => ({
          orders: total.orders + metric.orders,
          buyers: total.buyers + metric.buyers,
          revenue: total.revenue + metric.revenue,
        }),
        { orders: 0, buyers: 0, revenue: 0 },
      );

      return {
        id: campaign.campaign_key,
        databaseId: campaign.id,
        name: campaign.name,
        title: campaign.title,
        body: campaign.body,
        applications: campaign.application_names,
        sentAt: campaign.sent_at,
        sent: Number(campaign.sent),
        delivered: Number(campaign.delivered),
        clicked: Number(campaign.clicked),
        notDelivered: Number(campaign.not_delivered),
        type: RESEARCH_PATTERN.test(`${campaign.title} ${campaign.body}`)
          ? "research"
          : "commercial",
        orders: target.orders,
        buyers: target.buyers,
        revenue: target.revenue,
        ordersInOtherProjects: Math.max(
          0,
          allProjects.orders - target.orders,
        ),
      };
    });

    const totals = reportCampaigns.reduce(
      (total, campaign) => ({
        sent: total.sent + campaign.sent,
        delivered: total.delivered + campaign.delivered,
        clicked: total.clicked + campaign.clicked,
        orders: total.orders + campaign.orders,
        revenue: total.revenue + campaign.revenue,
        ordersInOtherProjects:
          total.ordersInOtherProjects + campaign.ordersInOtherProjects,
      }),
      {
        sent: 0,
        delivered: 0,
        clicked: 0,
        orders: 0,
        revenue: 0,
        ordersInOtherProjects: 0,
      },
    );

    const generatedAt =
      campaigns
        .map((campaign) => campaign.generated_at)
        .sort()
        .at(-1) ?? new Date().toISOString();
    const dataThrough =
      campaigns.map((campaign) => campaign.sent_at).sort().at(-1) ??
      generatedAt;

    return NextResponse.json(
      {
        generatedAt,
        dataThrough,
        source: "supabase",
        scope: {
          pushProjectId: "blizko-app",
          orderProjectId: "blizko-app",
          goalId: "all-orders",
          attributionModel: "Последний клик",
          attributionWindowHours: 24,
          timezone: "Europe/Moscow",
          periodStart: "2026-07-01",
          periodEndExclusive: "2026-08-01",
        },
        summary: {
          campaigns: reportCampaigns.length,
          commercialCampaigns: reportCampaigns.filter(
            (campaign) => campaign.type === "commercial",
          ).length,
          researchCampaigns: reportCampaigns.filter(
            (campaign) => campaign.type === "research",
          ).length,
          uniqueBuyers: Number(uniqueBuyers),
          ...totals,
        },
        campaigns: reportCampaigns,
      },
      {
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  } catch (error) {
    console.error("Blizko July report load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить июльский отчет из Supabase" },
      { status: 502 },
    );
  }
}
