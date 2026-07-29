import { NextResponse } from "next/server";

import {
  applyPushOverride,
  mapOverrides,
  PUSH_OVERRIDES_SELECT,
  type PushManualOverrideRow,
} from "@/lib/push-overrides";
import { pgMetaQuery, supabaseRows } from "@/lib/supabase-server";

type ProjectRow = {
  id: string;
  name: string;
  short_name: string;
};

type GoalRow = ProjectRow;

type CampaignRow = {
  id: number;
  campaign_key: string;
  project_id: string;
  name: string;
  title: string;
  body: string;
  application_names: string[];
  sent_at: string;
  attribution_status: "complete" | "collecting";
  attribution_window_hours: number;
  attribution_model: string;
  sent: number;
  delivered: number;
  clicked: number;
  not_delivered: number;
  platform_ios: number;
  platform_android: number;
  platform_unknown: number;
  generated_at: string;
};

type GoalMetricRow = {
  campaign_id: number;
  goal_id: string;
  orders: number;
  buyers: number;
  revenue: number;
  latency_0_1h: number;
  latency_1_4h: number;
  latency_4_12h: number;
  latency_12_24h: number;
};

type OrderProjectMetricRow = GoalMetricRow & {
  order_project_id: string;
};

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [
      projects,
      goals,
      campaigns,
      metrics,
      orderProjectMetrics,
      overrides,
    ] =
      await Promise.all([
      supabaseRows<ProjectRow>("push_projects", {
        select: "id,name,short_name",
        is_active: "eq.true",
        order: "sort_order.asc",
      }),
      supabaseRows<GoalRow>("push_goals", {
        select: "id,name,short_name",
        is_active: "eq.true",
        order: "sort_order.asc",
      }),
      supabaseRows<CampaignRow>("push_campaigns", {
        select:
          "id,campaign_key,project_id,name,title,body,application_names,sent_at,attribution_status,attribution_window_hours,attribution_model,sent,delivered,clicked,not_delivered,platform_ios,platform_android,platform_unknown,generated_at",
        order: "sent_at.desc",
      }),
      supabaseRows<GoalMetricRow>("push_campaign_goal_metrics", {
        select:
          "campaign_id,goal_id,orders,buyers,revenue,latency_0_1h,latency_1_4h,latency_4_12h,latency_12_24h",
      }),
      supabaseRows<OrderProjectMetricRow>(
        "push_campaign_goal_order_project_metrics",
        {
          select:
            "campaign_id,goal_id,order_project_id,orders,buyers,revenue,latency_0_1h,latency_1_4h,latency_4_12h,latency_12_24h",
        },
      ),
      pgMetaQuery<PushManualOverrideRow>(PUSH_OVERRIDES_SELECT),
    ]);

    const overrideByCampaign = mapOverrides(overrides, "mass");
    const effectiveCampaigns = campaigns
      .map((campaign) =>
        applyPushOverride(
          campaign,
          overrideByCampaign.get(campaign.id) ?? undefined,
        ),
      )
      .filter((campaign) => !campaign.isHidden);

    const metricsByCampaign = new Map<
      number,
      Record<
        string,
        {
          orders: number;
          buyers: number;
          revenue: number;
          latency: [number, number, number, number];
        }
      >
    >();
    for (const metric of metrics) {
      const campaignMetrics = metricsByCampaign.get(metric.campaign_id) ?? {};
      campaignMetrics[metric.goal_id] = {
        orders: Number(metric.orders),
        buyers: Number(metric.buyers),
        revenue: Number(metric.revenue),
        latency: [
          Number(metric.latency_0_1h),
          Number(metric.latency_1_4h),
          Number(metric.latency_4_12h),
          Number(metric.latency_12_24h),
        ],
      };
      metricsByCampaign.set(metric.campaign_id, campaignMetrics);
    }

    const orderProjectMetricsByCampaign = new Map<
      number,
      Record<
        string,
        Record<
          string,
          {
            orders: number;
            buyers: number;
            revenue: number;
            latency: [number, number, number, number];
          }
        >
      >
    >();
    for (const metric of orderProjectMetrics) {
      const campaignMetrics =
        orderProjectMetricsByCampaign.get(metric.campaign_id) ?? {};
      const projectMetrics = campaignMetrics[metric.order_project_id] ?? {};
      projectMetrics[metric.goal_id] = {
        orders: Number(metric.orders),
        buyers: Number(metric.buyers),
        revenue: Number(metric.revenue),
        latency: [
          Number(metric.latency_0_1h),
          Number(metric.latency_1_4h),
          Number(metric.latency_4_12h),
          Number(metric.latency_12_24h),
        ],
      };
      campaignMetrics[metric.order_project_id] = projectMetrics;
      orderProjectMetricsByCampaign.set(metric.campaign_id, campaignMetrics);
    }

    const generatedAt =
      campaigns
        .map((campaign) => campaign.generated_at)
        .sort()
        .at(-1) ?? new Date().toISOString();
    const attributionWindow = campaigns[0]?.attribution_window_hours ?? 24;

    return NextResponse.json(
      {
        generatedAt,
        source: "supabase",
        sourceNote:
          "Агрегаты и обезличенные покупки загружены из Mindbox в Supabase. Доставка рассчитана как Sent − NotDelivered. Текст и приложение проверены в карточках рассылок Mindbox.",
        defaultGoalId: "all-orders",
        defaultProjectId: "all",
        defaultOrderProjectId: "all",
        attribution: {
          windowHours: attributionWindow,
          model: "Последний клик",
        },
        projects: projects.map((project) => ({
          id: project.id,
          name: project.name,
          shortName: project.short_name,
        })),
        goals: goals.map((goal) => ({
          id: goal.id,
          name: goal.name,
          shortName: goal.short_name,
        })),
        pushes: effectiveCampaigns.map((campaign) => ({
          id: campaign.campaign_key,
          databaseId: campaign.id,
          projectId: campaign.project_id,
          name: campaign.name,
          title: campaign.title,
          body: campaign.body,
          applications: campaign.application_names,
          manuallyEdited: Boolean(campaign.manualOverride),
          sentAt: campaign.sent_at,
          status: campaign.attribution_status,
          sent: Number(campaign.sent),
          delivered: Number(campaign.delivered),
          clicked: Number(campaign.clicked),
          notDelivered: Number(campaign.not_delivered),
          platforms: {
            ios: Number(campaign.platform_ios),
            android: Number(campaign.platform_android),
            unknown: Number(campaign.platform_unknown),
          },
          goals: metricsByCampaign.get(campaign.id) ?? {},
          orderProjectGoals:
            orderProjectMetricsByCampaign.get(campaign.id) ?? {},
        })),
      },
      {
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  } catch (error) {
    console.error("Dashboard Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить данные из Supabase" },
      { status: 502 },
    );
  }
}
