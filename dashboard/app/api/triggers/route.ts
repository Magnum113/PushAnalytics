import { NextResponse } from "next/server";

import {
  applyPushOverride,
  mapOverrides,
  PUSH_OVERRIDES_SELECT,
  type PushManualOverrideRow,
} from "@/lib/push-overrides";
import { pgMetaQuery, supabaseRows } from "@/lib/supabase-server";

type ProjectRow = { id: string; name: string; short_name: string };
type GoalRow = ProjectRow;
type ScenarioRow = {
  id: number;
  mindbox_scenario_id: string;
  name: string;
  first_activity_at: string | null;
  last_activity_at: string | null;
};
type MailingRow = {
  id: number;
  scenario_id: number;
  project_id: string;
  message_key: string;
  name: string;
  title: string;
  body: string;
  mailing_type: "trigger";
  application_names: string[];
  platforms: string[];
  first_activity_at: string | null;
  last_activity_at: string | null;
  generated_at: string;
};
type DailyRow = {
  scenario_mailing_id: number;
  metric_date: string;
  participants: number;
  unique_recipients: number;
  sent: number;
  delivered_estimated: number;
  clicked: number;
  not_sent: number;
  not_delivered: number;
  not_sent_reasons: Record<string, number>;
  not_delivered_reasons: Record<string, number>;
};
type OrderRow = {
  scenario_mailing_id: number;
  goal_id: string;
  order_project_id: string;
  buyer_key: string;
  purchased_at: string;
  revenue: number;
  latency_minutes: number;
};

type MetricAccumulator = {
  orders: number;
  buyers: Set<string>;
  revenue: number;
  latency: [number, number, number, number];
};

function moscowMonth(value: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    timeZone: "Europe/Moscow",
  }).formatToParts(new Date(value));
  return `${parts.find((part) => part.type === "year")?.value}-${parts.find((part) => part.type === "month")?.value}`;
}

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [
      projects,
      goals,
      scenarios,
      mailings,
      dailyRows,
      orders,
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
        supabaseRows<ScenarioRow>("push_scenarios", {
          select:
            "id,mindbox_scenario_id,name,first_activity_at,last_activity_at",
          is_active: "eq.true",
          order: "last_activity_at.desc",
        }),
        supabaseRows<MailingRow>("push_scenario_mailings", {
          select:
            "id,scenario_id,project_id,message_key,name,title,body,mailing_type,application_names,platforms,first_activity_at,last_activity_at,generated_at",
          mailing_type: "eq.trigger",
          is_test: "eq.false",
          order: "last_activity_at.desc",
        }),
        supabaseRows<DailyRow>("push_scenario_daily_metrics", {
          select:
            "scenario_mailing_id,metric_date,participants,unique_recipients,sent,delivered_estimated,clicked,not_sent,not_delivered,not_sent_reasons,not_delivered_reasons",
          order: "metric_date.asc",
        }),
        supabaseRows<OrderRow>("push_trigger_attributed_orders", {
          select:
            "scenario_mailing_id,goal_id,order_project_id,buyer_key,purchased_at,revenue,latency_minutes",
          order: "purchased_at.asc",
        }),
        pgMetaQuery<PushManualOverrideRow>(PUSH_OVERRIDES_SELECT),
      ]);

    const overrideByMailing = mapOverrides(overrides, "trigger");
    const effectiveMailings = mailings
      .map((mailing) =>
        applyPushOverride(
          mailing,
          overrideByMailing.get(mailing.id) ?? undefined,
        ),
      )
      .filter((mailing) => !mailing.isHidden);

    const maxMetricDate = dailyRows
      .map((row) => row.metric_date)
      .sort()
      .at(-1);
    const sevenDayCutoff = maxMetricDate
      ? new Date(`${maxMetricDate}T23:59:59+03:00`).getTime() -
        7 * 24 * 60 * 60 * 1000
      : 0;
    const accumulators = new Map<string, MetricAccumulator>();
    const selectionAccumulators = new Map<string, MetricAccumulator>();
    const mailingProject = new Map(
      effectiveMailings.map((mailing) => [
        mailing.id,
        mailing.project_id,
      ]),
    );
    const add = (
      mailingId: number,
      period: string,
      goalId: string,
      orderProjectId: string,
      order: OrderRow,
    ) => {
      const key = `${mailingId}:${period}:${goalId}:${orderProjectId}`;
      const metric = accumulators.get(key) ?? {
        orders: 0,
        buyers: new Set<string>(),
        revenue: 0,
        latency: [0, 0, 0, 0],
      };
      metric.orders += 1;
      metric.buyers.add(order.buyer_key);
      metric.revenue += Number(order.revenue);
      const latencyIndex =
        Number(order.latency_minutes) <= 60
          ? 0
          : Number(order.latency_minutes) <= 240
            ? 1
            : Number(order.latency_minutes) <= 720
              ? 2
              : 3;
      metric.latency[latencyIndex] += 1;
      accumulators.set(key, metric);
    };
    const addSelection = (
      period: string,
      goalId: string,
      orderProjectId: string,
      pushProjectId: string,
      order: OrderRow,
    ) => {
      const key = `${period}:${goalId}:${orderProjectId}:${pushProjectId}`;
      const metric = selectionAccumulators.get(key) ?? {
        orders: 0,
        buyers: new Set<string>(),
        revenue: 0,
        latency: [0, 0, 0, 0],
      };
      metric.orders += 1;
      metric.buyers.add(order.buyer_key);
      metric.revenue += Number(order.revenue);
      const latencyIndex =
        Number(order.latency_minutes) <= 60
          ? 0
          : Number(order.latency_minutes) <= 240
            ? 1
            : Number(order.latency_minutes) <= 720
              ? 2
              : 3;
      metric.latency[latencyIndex] += 1;
      selectionAccumulators.set(key, metric);
    };

    for (const order of orders) {
      if (!mailingProject.has(order.scenario_mailing_id)) continue;
      const periods = ["all", moscowMonth(order.purchased_at)];
      if (new Date(order.purchased_at).getTime() >= sevenDayCutoff) {
        periods.push("7d");
      }
      for (const period of periods) {
        for (const selectedOrderProject of [
          order.order_project_id,
          "all",
        ]) {
          add(
            order.scenario_mailing_id,
            period,
            order.goal_id,
            selectedOrderProject,
            order,
          );
          for (const selectedPushProject of [
            mailingProject.get(order.scenario_mailing_id) ?? "all",
            "all",
          ]) {
            addSelection(
              period,
              order.goal_id,
              selectedOrderProject,
              selectedPushProject,
              order,
            );
          }
        }
      }
    }

    const scenarioById = new Map(
      scenarios.map((scenario) => [scenario.id, scenario]),
    );
    const generatedAt =
      mailings.map((mailing) => mailing.generated_at).sort().at(-1) ??
      new Date().toISOString();

    return NextResponse.json(
      {
        generatedAt,
        sourceCoverageEnd: maxMetricDate,
        attribution: {
          windowHours: 24,
          model: "Последний клик среди всех MobilePush",
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
        selectionOrderMetrics: [
          ...selectionAccumulators.entries(),
        ].map(([key, metric]) => {
          const [period, goalId, orderProjectId, pushProjectId] =
            key.split(":");
          return {
            period,
            goalId,
            orderProjectId,
            pushProjectId,
            orders: metric.orders,
            buyers: metric.buyers.size,
            revenue: metric.revenue,
            latency: metric.latency,
          };
        }),
        messages: effectiveMailings.map((mailing) => ({
          id: mailing.id,
          scenarioId: mailing.scenario_id,
          mindboxScenarioId:
            scenarioById.get(mailing.scenario_id)?.mindbox_scenario_id ?? "",
          scenarioName:
            scenarioById.get(mailing.scenario_id)?.name ?? "Сценарий",
          projectId: mailing.project_id,
          messageKey: mailing.message_key,
          name: mailing.name,
          title: mailing.title,
          body: mailing.body,
          mailingType: mailing.mailing_type,
          applications: mailing.application_names,
          manuallyEdited: Boolean(mailing.manualOverride),
          platforms: mailing.platforms,
          firstActivityAt: mailing.first_activity_at,
          lastActivityAt: mailing.last_activity_at,
          daily: dailyRows
            .filter((row) => row.scenario_mailing_id === mailing.id)
            .map((row) => ({
              date: row.metric_date,
              participants: Number(row.participants),
              uniqueRecipients: Number(row.unique_recipients),
              sent: Number(row.sent),
              delivered: Number(row.delivered_estimated),
              clicked: Number(row.clicked),
              notSent: Number(row.not_sent),
              notDelivered: Number(row.not_delivered),
              notSentReasons: row.not_sent_reasons,
              notDeliveredReasons: row.not_delivered_reasons,
            })),
          orderMetrics: [...accumulators.entries()]
            .filter(([key]) => key.startsWith(`${mailing.id}:`))
            .map(([key, metric]) => {
              const [, period, goalId, orderProjectId] = key.split(":");
              return {
                period,
                goalId,
                orderProjectId,
                orders: metric.orders,
                buyers: metric.buyers.size,
                revenue: metric.revenue,
                latency: metric.latency,
              };
            }),
        })),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("Trigger dashboard Supabase load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить trigger-пуши из Supabase" },
      { status: 502 },
    );
  }
}
