"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { ProjectMultiSelect } from "./project-multiselect";

type GoalMetrics = {
  orders: number;
  buyers: number;
  revenue: number;
  latency: [number, number, number, number];
};

type Push = {
  id: string;
  databaseId?: number;
  projectId: string;
  name: string;
  title: string;
  body: string;
  applications: string[];
  sentAt: string;
  status: "complete" | "collecting";
  sent: number;
  delivered: number;
  clicked: number;
  notDelivered: number;
  platforms: {
    ios: number;
    android: number;
    unknown: number;
  };
  goals: Record<string, GoalMetrics>;
  orderProjectGoals?: Record<string, Record<string, GoalMetrics>>;
};

type DashboardData = {
  generatedAt: string;
  source: "supabase" | "mindbox" | "demo";
  sourceNote: string;
  defaultGoalId?: string;
  attribution: {
    windowHours: number;
    model: string;
  };
  projects: Array<{
    id: string;
    name: string;
    shortName: string;
  }>;
  goals: Array<{
    id: string;
    name: string;
    shortName: string;
  }>;
  pushes: Push[];
};

const fallbackData: DashboardData = {
  generatedAt: "2026-07-23T14:00:00+03:00",
  source: "demo",
  sourceNote: "Демонстрационные данные — ожидается локальная синхронизация Mindbox",
  defaultGoalId: "blizko-app",
  attribution: { windowHours: 24, model: "Последний клик" },
  projects: [
    {
      id: "blizko-app",
      name: "Отдельное приложение Blizko",
      shortName: "Blizko · приложение",
    },
    {
      id: "05-main",
      name: "Основной проект 05.ru",
      shortName: "05.ru · основной проект",
    },
    {
      id: "blizko-in-05",
      name: "Blizko внутри приложения 05.ru",
      shortName: "Blizko внутри 05.ru",
    },
  ],
  goals: [
    {
      id: "blizko-app",
      name: "Заказы Blizko (отдельное приложение)",
      shortName: "Blizko · приложение",
    },
    {
      id: "05-app",
      name: "Заказы в приложении (ИМ)",
      shortName: "05.ru · приложение",
    },
    {
      id: "blizko-in-05",
      name: "Заказ в Blizko",
      shortName: "Blizko внутри 05.ru",
    },
    { id: "all-orders", name: "Заказы", shortName: "Все заказы" },
  ],
  pushes: [
    {
      id: "demo-1",
      projectId: "blizko-app",
      name: "Blizko · Доставка за 29 минут",
      title: "Ужин уже близко 🥬",
      body: "Свежие продукты доставим от 29 минут. Загляните в Blizko — всё нужное уже рядом.",
      applications: ["Android приложение Blizko", "iOS приложение Blizko"],
      sentAt: "2026-07-22T17:30:00+03:00",
      status: "complete",
      sent: 38740,
      delivered: 36188,
      clicked: 1941,
      notDelivered: 2552,
      platforms: { ios: 13208, android: 21860, unknown: 1120 },
      goals: {
        "blizko-app": { orders: 164, buyers: 151, revenue: 286340, latency: [71, 47, 31, 15] },
        "05-app": { orders: 19, buyers: 18, revenue: 782400, latency: [7, 5, 4, 3] },
        "blizko-in-05": { orders: 41, buyers: 37, revenue: 70430, latency: [18, 12, 7, 4] },
        "all-orders": { orders: 224, buyers: 198, revenue: 1139170, latency: [96, 64, 42, 22] },
      },
    },
    {
      id: "demo-2",
      projectId: "blizko-app",
      name: "Blizko · Фрукты со скидкой",
      title: "Лето — на вкус 🍑",
      body: "Сочные фрукты и ягоды со скидкой до 25%. Закажите сегодня в Blizko.",
      applications: ["Android приложение Blizko", "iOS приложение Blizko"],
      sentAt: "2026-07-20T11:00:00+03:00",
      status: "complete",
      sent: 42120,
      delivered: 39984,
      clicked: 1698,
      notDelivered: 2136,
      platforms: { ios: 14574, android: 24456, unknown: 954 },
      goals: {
        "blizko-app": { orders: 129, buyers: 119, revenue: 214780, latency: [58, 36, 24, 11] },
        "05-app": { orders: 14, buyers: 13, revenue: 594700, latency: [5, 4, 3, 2] },
        "blizko-in-05": { orders: 33, buyers: 30, revenue: 55980, latency: [14, 10, 6, 3] },
        "all-orders": { orders: 176, buyers: 157, revenue: 865460, latency: [77, 50, 33, 16] },
      },
    },
    {
      id: "demo-3",
      projectId: "blizko-in-05",
      name: "Blizko · Завтрак",
      title: "Доброе утро начинается здесь",
      body: "Молоко, яйца, выпечка и любимый кофе — привезём к вашему завтраку.",
      applications: ["Android приложение 05ru", "iOS приложение 05ru"],
      sentAt: "2026-07-18T08:15:00+03:00",
      status: "complete",
      sent: 36450,
      delivered: 34627,
      clicked: 2137,
      notDelivered: 1823,
      platforms: { ios: 12241, android: 21450, unknown: 936 },
      goals: {
        "blizko-app": { orders: 187, buyers: 169, revenue: 318610, latency: [94, 51, 29, 13] },
        "05-app": { orders: 11, buyers: 11, revenue: 436900, latency: [5, 3, 2, 1] },
        "blizko-in-05": { orders: 46, buyers: 41, revenue: 78320, latency: [22, 13, 8, 3] },
        "all-orders": { orders: 244, buyers: 216, revenue: 833830, latency: [121, 67, 39, 17] },
      },
    },
    {
      id: "demo-4",
      projectId: "blizko-in-05",
      name: "Blizko · Бесплатная доставка",
      title: "Доставка — 0 ₽",
      body: "Соберите корзину от 1 500 ₽ — доставку возьмём на себя. Только до конца дня.",
      applications: ["Android приложение 05ru", "iOS приложение 05ru"],
      sentAt: "2026-07-15T14:00:00+03:00",
      status: "complete",
      sent: 40780,
      delivered: 38516,
      clicked: 2822,
      notDelivered: 2264,
      platforms: { ios: 13860, android: 23709, unknown: 947 },
      goals: {
        "blizko-app": { orders: 236, buyers: 214, revenue: 461220, latency: [101, 72, 43, 20] },
        "05-app": { orders: 17, buyers: 16, revenue: 687500, latency: [7, 5, 3, 2] },
        "blizko-in-05": { orders: 54, buyers: 48, revenue: 101670, latency: [24, 16, 10, 4] },
        "all-orders": { orders: 307, buyers: 270, revenue: 1250390, latency: [132, 93, 56, 26] },
      },
    },
    {
      id: "demo-5",
      projectId: "05-main",
      name: "Blizko · Повторный заказ",
      title: "Повторим любимое?",
      body: "Товары из прошлого заказа ждут в корзине. Один клик — и они снова у вас.",
      applications: ["Android приложение 05ru", "iOS приложение 05ru"],
      sentAt: "2026-07-12T18:00:00+03:00",
      status: "complete",
      sent: 22160,
      delivered: 21470,
      clicked: 1853,
      notDelivered: 690,
      platforms: { ios: 7853, android: 13024, unknown: 593 },
      goals: {
        "blizko-app": { orders: 213, buyers: 191, revenue: 390140, latency: [116, 58, 27, 12] },
        "05-app": { orders: 8, buyers: 8, revenue: 301600, latency: [4, 2, 1, 1] },
        "blizko-in-05": { orders: 39, buyers: 35, revenue: 72560, latency: [20, 11, 6, 2] },
        "all-orders": { orders: 260, buyers: 228, revenue: 764300, latency: [140, 71, 34, 15] },
      },
    },
  ],
};

type PurchaseItem = {
  lineKey: string;
  productInternalId: string | null;
  productExternalId: string | null;
  productName: string | null;
  vendorCode: string | null;
  displayName: string;
  catalogMatched: boolean;
  quantity: number;
  quantityType: string | null;
  unitPrice: number | null;
  lineAmount: number | null;
  statusCategory: string | null;
};

type AttributedOrder = {
  id: number;
  orderKey: string;
  purchasedAt: string;
  attributedClickAt: string;
  latencyMinutes: number;
  revenue: number;
  orderProjectId: string;
  items: PurchaseItem[];
};

const emptyData: DashboardData = {
  ...fallbackData,
  generatedAt: new Date(0).toISOString(),
  source: "supabase",
  sourceNote: "",
  defaultGoalId: "all-orders",
  attribution: { windowHours: 24, model: "Последний клик" },
  projects: [],
  goals: [],
  pushes: [],
};

const number = new Intl.NumberFormat("ru-RU");
const money = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 0,
});
const compactMoney = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  notation: "compact",
  maximumFractionDigits: 1,
});
const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});
const monthName = new Intl.DateTimeFormat("ru-RU", {
  month: "long",
  timeZone: "Europe/Moscow",
});

function monthKey(value: string) {
  const parts = new Intl.DateTimeFormat("ru-RU", {
    year: "numeric",
    month: "2-digit",
    timeZone: "Europe/Moscow",
  }).formatToParts(new Date(value));
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  return `${year}-${month}`;
}

function monthLabel(value: string) {
  const label = monthName.format(new Date(`${value}-15T12:00:00+03:00`));
  return label.charAt(0).toLocaleUpperCase("ru") + label.slice(1);
}

function percent(value: number, base: number) {
  return base ? `${((value / base) * 100).toFixed(2).replace(".", ",")}%` : "—";
}

function delta(value: number, baseline: number) {
  if (!baseline) return "—";
  const result = ((value - baseline) / baseline) * 100;
  return `${result >= 0 ? "+" : ""}${result.toFixed(1).replace(".", ",")}%`;
}

function countText(value: number, one: string, few: string, many: string) {
  const mod100 = value % 100;
  const mod10 = value % 10;
  const noun =
    mod100 >= 11 && mod100 <= 14
      ? many
      : mod10 === 1
        ? one
        : mod10 >= 2 && mod10 <= 4
          ? few
          : many;
  return `${number.format(value)} ${noun}`;
}

function buyersText(value: number) {
  return countText(value, "покупатель", "покупателя", "покупателей");
}

function ordersText(value: number) {
  return countText(value, "заказ", "заказа", "заказов");
}

const emptyGoalMetrics: GoalMetrics = {
  orders: 0,
  buyers: 0,
  revenue: 0,
  latency: [0, 0, 0, 0],
};

function metricsFor(
  push: Push,
  goalId: string,
): GoalMetrics {
  return (
    push.orderProjectGoals?.[push.projectId]?.[goalId] ?? emptyGoalMetrics
  );
}

export default function Home() {
  const [data, setData] = useState<DashboardData>(emptyData);
  const [goalId, setGoalId] = useState("all-orders");
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"date" | "ctr" | "orders">("date");
  const [period, setPeriod] = useState("all");
  const [metric, setMetric] = useState<"orders" | "ctr" | "revenue">("orders");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [purchasesOpen, setPurchasesOpen] = useState(false);
  const [purchasesLoading, setPurchasesLoading] = useState(false);
  const [purchasesError, setPurchasesError] = useState("");
  const [attributedOrders, setAttributedOrders] = useState<AttributedOrder[]>([]);
  const [attributedBuyers, setAttributedBuyers] = useState(0);
  const [totalBuyerResult, setTotalBuyerResult] = useState<{
    key: string;
    buyers: number | null;
    error: boolean;
  } | null>(null);
  const unresolvedProductLines = attributedOrders.reduce(
    (total, order) =>
      total + order.items.filter((item) => !item.catalogMatched).length,
    0,
  );

  useEffect(() => {
    fetch("/api/dashboard", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Supabase dashboard is unavailable");
        return response.json();
      })
      .then((next: DashboardData) => {
        setData(next);
        setGoalId(
          next.defaultGoalId ??
            next.goals[0]?.id ??
            "all-orders",
        );
        setSelectedProjectIds(next.projects.map((project) => project.id));
        setSelectedId(next.pushes[0]?.id ?? "");
      })
      .catch(() => setLoadError("Не удалось загрузить данные из Supabase."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!purchasesOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPurchasesOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [purchasesOpen]);

  const selectedProjectSet = useMemo(
    () => new Set(selectedProjectIds),
    [selectedProjectIds],
  );

  const visiblePushes = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    const latestSentAt = Math.max(
      ...data.pushes.map((push) => new Date(push.sentAt).getTime()),
    );
    const cutoff = latestSentAt - 7 * 24 * 60 * 60 * 1000;
    const filtered = data.pushes.filter(
      (push) =>
        (period === "all" ||
          (period === "7d"
            ? new Date(push.sentAt).getTime() >= cutoff
            : monthKey(push.sentAt) === period)) &&
        selectedProjectSet.has(push.projectId) &&
        (!normalized ||
          `${push.name} ${push.title} ${push.body}`
            .toLocaleLowerCase("ru")
            .includes(normalized)),
    );

    return [...filtered].sort((a, b) => {
      if (sort === "ctr") {
        return (
          b.clicked / Math.max(b.delivered, 1) -
          a.clicked / Math.max(a.delivered, 1)
        );
      }
      if (sort === "orders") {
        return (
          metricsFor(b, goalId).orders -
          metricsFor(a, goalId).orders
        );
      }
      return new Date(b.sentAt).getTime() - new Date(a.sentAt).getTime();
    });
  }, [
    data.pushes,
    goalId,
    period,
    query,
    selectedProjectSet,
    sort,
  ]);

  const availableMonths = useMemo(
    () =>
      [...new Set(data.pushes.map((push) => monthKey(push.sentAt)))].sort(),
    [data.pushes],
  );

  useEffect(() => {
    const campaignIds = visiblePushes
      .map((push) => push.databaseId)
      .filter((value): value is number => Boolean(value));
    const projectIds = visiblePushes.map((push) => push.projectId);
    const requestKey =
      `${goalId}:${campaignIds.join(",")}:${projectIds.join(",")}`;
    if (!campaignIds.length || campaignIds.length !== visiblePushes.length) {
      return;
    }

    const controller = new AbortController();
    const params = new URLSearchParams({
      goalId,
      campaignIds: campaignIds.join(","),
      projectIds: projectIds.join(","),
    });
    fetch(`/api/buyers?${params}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Buyer count is unavailable");
        return response.json();
      })
      .then((payload: { buyers: number }) => {
        setTotalBuyerResult({
          key: requestKey,
          buyers: Number(payload.buyers),
          error: false,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setTotalBuyerResult({ key: requestKey, buyers: null, error: true });
    });
    return () => controller.abort();
  }, [goalId, visiblePushes]);

  const totals = useMemo(
    () =>
      visiblePushes.reduce(
        (acc, push) => {
          const goal = metricsFor(push, goalId);
          acc.sent += push.sent;
          acc.delivered += push.delivered;
          acc.clicked += push.clicked;
          acc.notDelivered += push.notDelivered;
          acc.orders += goal.orders;
          acc.revenue += goal.revenue;
          goal.latency.forEach((value, index) => {
            acc.latency[index] += value;
          });
          return acc;
        },
        {
          sent: 0,
          delivered: 0,
          clicked: 0,
          notDelivered: 0,
          orders: 0,
          revenue: 0,
          latency: [0, 0, 0, 0],
        },
      ),
    [goalId, visiblePushes],
  );
  const totalBuyerRequestKey =
    `${goalId}:${visiblePushes
      .map((push) => push.databaseId)
      .filter((value): value is number => Boolean(value))
      .join(",")}:${visiblePushes.map((push) => push.projectId).join(",")}`;
  const resolvedTotalBuyerResult =
    visiblePushes.length === 0
      ? { buyers: 0, error: false }
      : totalBuyerResult?.key === totalBuyerRequestKey
        ? totalBuyerResult
        : { buyers: null, error: false };
  const resolvedTotalBuyers = resolvedTotalBuyerResult.buyers;

  const selected =
    visiblePushes.find((push) => push.id === selectedId) ??
    visiblePushes[0] ??
    data.pushes[0];
  const selectedGoal = selected
    ? metricsFor(selected, goalId)
    : emptyGoalMetrics;
  const currentGoal = data.goals.find((goal) => goal.id === goalId);
  const selectedProject = data.projects.find(
    (project) => project.id === selected?.projectId,
  );
  const projectScopeName =
    selectedProjectIds.length === data.projects.length
      ? "Все проекты"
      : selectedProjectIds.length === 1
        ? (data.projects.find(
            (project) => project.id === selectedProjectIds[0],
          )?.shortName ?? "Выбранный проект")
        : `${selectedProjectIds.length} проекта`;
  const avgCtr =
    visiblePushes.reduce(
      (sum, push) => sum + push.clicked / Math.max(push.delivered, 1),
      0,
    ) / Math.max(visiblePushes.length, 1);
  const topPush = visiblePushes
    .filter((push) => metricsFor(push, goalId).orders > 0)
    .sort(
      (a, b) =>
        metricsFor(b, goalId).orders /
          Math.max(b.clicked, 1) -
          metricsFor(a, goalId).orders /
            Math.max(a.clicked, 1) ||
        metricsFor(b, goalId).orders -
          metricsFor(a, goalId).orders,
    )[0];
  const bestCtrPush = [...visiblePushes].sort(
    (a, b) =>
      b.clicked / Math.max(b.delivered, 1) -
      a.clicked / Math.max(a.delivered, 1),
  )[0];
  const chartPushes = [...visiblePushes].sort(
    (a, b) => new Date(a.sentAt).getTime() - new Date(b.sentAt).getTime(),
  ).slice(-12);
  const chartMetric = (push: Push) => {
    if (metric === "ctr") {
      return (push.clicked / Math.max(push.delivered, 1)) * 100;
    }
    if (metric === "revenue") {
      return metricsFor(push, goalId).revenue;
    }
    return metricsFor(push, goalId).orders;
  };
  const chartMax = Math.max(...chartPushes.map(chartMetric), 1);
  const formatChartMetric = (value: number) => {
    if (metric === "ctr") return `${value.toFixed(2).replace(".", ",")}%`;
    if (metric === "revenue") return compactMoney.format(value);
    return number.format(value);
  };
  const selectedPlatformTotal = selected
    ? selected.platforms.android +
      selected.platforms.ios +
      selected.platforms.unknown
    : 0;

  async function openPurchases() {
    if (!selected?.databaseId) return;
    setPurchasesOpen(true);
    setPurchasesLoading(true);
    setPurchasesError("");
    setAttributedOrders([]);
    setAttributedBuyers(0);
    try {
      const params = new URLSearchParams({
        campaignId: String(selected.databaseId),
        goalId,
      });
      const response = await fetch(`/api/purchases?${params}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Purchase details are unavailable");
      const payload = (await response.json()) as {
        buyers: number;
        orders: AttributedOrder[];
      };
      setAttributedOrders(payload.orders);
      setAttributedBuyers(payload.buyers);
    } catch {
      setPurchasesError("Не удалось загрузить покупки из Supabase.");
    } finally {
      setPurchasesLoading(false);
    }
  }

  if (loading) {
    return (
      <main className="state-screen">
        <div className="state-card">
          <span className="state-mark">P</span>
          <p className="eyebrow">PUSH ANALYTICS</p>
          <h1>Загружаем данные из Supabase</h1>
          <p>Собираем рассылки, цели и атрибутированные покупки.</p>
        </div>
      </main>
    );
  }

  if (loadError && !data.pushes.length) {
    return (
      <main className="state-screen">
        <div className="state-card error">
          <span className="state-mark">!</span>
          <p className="eyebrow">PUSH ANALYTICS</p>
          <h1>Данные не загрузились</h1>
          <p>{loadError} Проверьте локальный Supabase и параметры в PushAnalytics/.env.</p>
          <button onClick={() => window.location.reload()}>Повторить</button>
        </div>
      </main>
    );
  }

  return (
    <main className="dashboard-shell">
      <section className="content">
        <header className="topbar">
          <div>
            <h1>PUSH ANALYTICS</h1>
            <p className="subtitle">От отправки до покупки</p>
          </div>
          <div className="topbar-actions">
            <Link className="report-link secondary-link" href="/triggers">
              Триггерные пуши
            </Link>
            <Link className="report-link secondary-link" href="/pushes">
              Редактор пушей
            </Link>
            <Link className="report-link" href="/blizko-july">
              Отчет Blizko · июль
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path d="M5 12h14M14 7l5 5-5 5" />
              </svg>
            </Link>
            <div className="sync-status">
              <span>Обновлено {dateTime.format(new Date(data.generatedAt))}</span>
              <strong>
                {data.attribution.model}, {data.attribution.windowHours} ч
              </strong>
            </div>
          </div>
        </header>

        <section className="command-bar" aria-label="Фильтры отчёта">
          <ProjectMultiSelect
            projects={data.projects.map((project) => ({
              ...project,
              count: data.pushes.filter(
                (push) => push.projectId === project.id,
              ).length,
            }))}
            selectedIds={selectedProjectIds}
            onChange={setSelectedProjectIds}
          />
          <label className="command-control goal-filter">
            <span>Цель / статус заказа</span>
            <select value={goalId} onChange={(event) => setGoalId(event.target.value)}>
              {data.goals.map((goal) => (
                <option key={goal.id} value={goal.id}>
                  {goal.name}
                </option>
              ))}
            </select>
          </label>
          <label className="command-control search-filter">
            <span>Поиск</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Текст или название"
            />
          </label>
          <div className="period-switch" aria-label="Период">
            <button
              className={period === "7d" ? "selected" : ""}
              aria-pressed={period === "7d"}
              onClick={() => setPeriod("7d")}
            >
              7 дней
            </button>
            {availableMonths.map((month) => (
              <button
                key={month}
                className={period === month ? "selected" : ""}
                aria-pressed={period === month}
                onClick={() => setPeriod(month)}
              >
                {monthLabel(month)}
              </button>
            ))}
            <button
              className={period === "all" ? "selected" : ""}
              aria-pressed={period === "all"}
              onClick={() => setPeriod("all")}
            >
              Вся выборка
            </button>
          </div>
        </section>

        <section className="kpi-strip" aria-label="Ключевые показатели">
          <article>
            <span>Отправлено</span>
            <strong>{number.format(totals.sent)}</strong>
            <small>{percent(totals.delivered, totals.sent)} доставлено</small>
          </article>
          <article>
            <span>Открыли</span>
            <strong>{number.format(totals.clicked)}</strong>
            <small>CTR {percent(totals.clicked, totals.delivered)}</small>
          </article>
          <article className="primary-kpi">
            <span>Заказы</span>
            <strong>{number.format(totals.orders)}</strong>
            <small>{percent(totals.orders, totals.clicked)} после клика</small>
          </article>
          <article className="buyers-kpi">
            <span>Покупатели</span>
            <strong>
              {resolvedTotalBuyers === null
                ? "—"
                : number.format(resolvedTotalBuyers)}
            </strong>
            <small>
              {resolvedTotalBuyerResult.error
                ? "не удалось загрузить"
                : resolvedTotalBuyers === null
                  ? "считаем…"
                  : "уникальные клиенты"}
            </small>
          </article>
          <article>
            <span>Выручка</span>
            <strong>{money.format(totals.revenue)}</strong>
            <small>
              Средний чек{" "}
              {money.format(totals.orders ? totals.revenue / totals.orders : 0)}
            </small>
          </article>
        </section>

        <section className="hero-grid" aria-label="Главная аналитика">
          <article className="performance-panel">
            <div className="performance-head">
              <div>
                <h2>{projectScopeName}</h2>
              </div>
              <div className="metric-switch" aria-label="Метрика графика">
                {[
                  ["orders", "Заказы"],
                  ["ctr", "CTR"],
                  ["revenue", "Выручка"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    className={metric === id ? "selected" : ""}
                    aria-pressed={metric === id}
                    onClick={() => setMetric(id as typeof metric)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="performance-summary">
              <div>
                <span>
                  {metric === "orders"
                    ? currentGoal?.shortName
                    : metric === "ctr"
                      ? "CTR"
                      : "Выручка"}
                </span>
                <strong>
                  {metric === "orders"
                    ? number.format(totals.orders)
                    : metric === "ctr"
                      ? percent(totals.clicked, totals.delivered)
                      : compactMoney.format(totals.revenue)}
                </strong>
                <small>
                  {metric === "orders"
                    ? "заказов в выборке"
                    : metric === "ctr"
                      ? `${number.format(totals.clicked)} открытий`
                      : resolvedTotalBuyers === null
                        ? ordersText(totals.orders)
                        : `${ordersText(totals.orders)} · ${buyersText(
                            resolvedTotalBuyers,
                          )}`}
                </small>
              </div>
              <div className="summary-buyers">
                <span>Покупатели</span>
                <strong>
                  {resolvedTotalBuyers === null
                    ? "—"
                    : number.format(resolvedTotalBuyers)}
                </strong>
                <small>
                  {resolvedTotalBuyerResult.error
                    ? "не удалось загрузить"
                    : resolvedTotalBuyers === null
                      ? "считаем…"
                      : "уникальные клиенты"}
                </small>
              </div>
              <div className="summary-rate">
                <span>Конверсия</span>
                <strong>{percent(totals.orders, totals.clicked)}</strong>
                <small>из открытий в заказ</small>
              </div>
            </div>

            <div className="campaign-chart" aria-label="Сравнение последних рассылок">
              {chartPushes.map((push) => {
                const value = chartMetric(push);
                const height = value ? Math.max(10, (value / chartMax) * 100) : 3;
                return (
                  <button
                    key={push.id}
                    className={`chart-column ${selected?.id === push.id ? "selected" : ""}`}
                    aria-label={`${push.title || push.name}: ${formatChartMetric(value)}${
                      metric === "orders"
                        ? `, ${buyersText(
                            metricsFor(push, goalId).buyers,
                          )}`
                        : ""
                    }`}
                    aria-pressed={selected?.id === push.id}
                    onClick={() => setSelectedId(push.id)}
                  >
                    <span className="chart-value">
                      {formatChartMetric(value)}
                      {metric === "orders" && (
                        <span className="chart-buyers">
                          {buyersText(
                            metricsFor(push, goalId).buyers,
                          )}
                        </span>
                      )}
                    </span>
                    <span className="chart-rail">
                      <span
                        className="chart-fill"
                        style={{ "--bar-height": `${height}%` } as React.CSSProperties}
                      />
                    </span>
                    <span className="chart-date">
                      {dateTime.format(new Date(push.sentAt)).split(",")[0]}
                    </span>
                    <small>{push.title || push.name}</small>
                  </button>
                );
              })}
            </div>
          </article>

          <article
            className={`signal-panel ${
              visiblePushes.length > 0 && !topPush ? "no-orders" : ""
            }`}
          >
            {topPush ? (
              <>
                <span className="signal-label">Лучший результат</span>
                <h2>{topPush.title || topPush.name}</h2>
                <div className="signal-message">
                  <p>{topPush.body || topPush.name}</p>
                </div>
                <div className="signal-rate">
                  <strong>
                    {percent(
                      metricsFor(topPush, goalId).orders,
                      topPush.clicked,
                    )}
                  </strong>
                  <span>конверсия после клика</span>
                </div>
                <div className="signal-facts">
                  <span>
                    {ordersText(
                      metricsFor(topPush, goalId).orders,
                    )}
                  </span>
                  <span>
                    {buyersText(
                      metricsFor(topPush, goalId).buyers,
                    )}
                  </span>
                  <span>CTR {percent(topPush.clicked, topPush.delivered)}</span>
                </div>
                <button className="text-action" onClick={() => setSelectedId(topPush.id)}>
                  Разобрать пуш <span aria-hidden="true">↘</span>
                </button>
              </>
            ) : visiblePushes.length > 0 ? (
              <>
                <span className="signal-label">Результат</span>
                <h2>Заказов пока нет</h2>
                <div className="signal-empty-copy">
                  <p>
                    В выбранном срезе нет заказов, сделанных в проекте
                    соответствующего пуша.
                  </p>
                </div>
                {bestCtrPush && (
                  <>
                    <div className="signal-message engagement-signal">
                      <span>Лучший CTR</span>
                      <strong>{bestCtrPush.title || bestCtrPush.name}</strong>
                    </div>
                    <div className="signal-facts">
                      <span>
                        Лучший CTR{" "}
                        {percent(bestCtrPush.clicked, bestCtrPush.delivered)}
                      </span>
                      <span>{number.format(bestCtrPush.clicked)} открытий</span>
                    </div>
                    <button
                      className="text-action"
                      onClick={() => setSelectedId(bestCtrPush.id)}
                    >
                      Посмотреть пуш с лучшим CTR{" "}
                      <span aria-hidden="true">↘</span>
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <span className="signal-label">Результат</span>
                <h2>Нет данных для сравнения</h2>
                <p>Нет пушей в выбранном периоде.</p>
              </>
            )}
          </article>
        </section>

        <section className="campaign-layout">
          <article className="panel mailings-panel">
            <div className="panel-heading table-heading">
              <div>
                <h2>Рассылки</h2>
                <p className="section-description">{visiblePushes.length} кампаний</p>
              </div>
              <label>
                <span>Сортировать</span>
                <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
                  <option value="date">Сначала новые</option>
                  <option value="ctr">По CTR</option>
                  <option value="orders">По заказам</option>
                </select>
              </label>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Сообщение</th>
                    <th>Отправлено</th>
                    <th>Открыли</th>
                    <th>CTR</th>
                    <th>Заказы</th>
                    <th>Покупатели</th>
                    <th>Клик → заказ</th>
                    <th>Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {visiblePushes.map((push) => {
                    const goal = metricsFor(push, goalId);
                    return (
                      <tr
                        key={push.id}
                        className={selected?.id === push.id ? "selected-row" : ""}
                        onClick={() => setSelectedId(push.id)}
                      >
                        <td>
                          <button
                            className="mailing-name"
                            onClick={() => setSelectedId(push.id)}
                            aria-label={`Показать ${push.name}`}
                          >
                            <span>{push.title || push.name}</span>
                            <small>
                              <span className="project-tag">
                                {
                                  data.projects.find(
                                    (project) => project.id === push.projectId,
                                  )?.shortName
                                }
                              </span>
                              {dateTime.format(new Date(push.sentAt))}
                            </small>
                          </button>
                        </td>
                        <td data-label="Отправлено">
                          <strong>{number.format(push.sent)}</strong>
                          <small>{percent(push.delivered, push.sent)} доставлено</small>
                        </td>
                        <td data-label="Открыли">{number.format(push.clicked)}</td>
                        <td data-label="CTR"><strong>{percent(push.clicked, push.delivered)}</strong></td>
                        <td data-label="Заказы"><strong className="order-value">{number.format(goal.orders)}</strong></td>
                        <td data-label="Покупатели">
                          <strong>{number.format(goal.buyers)}</strong>
                        </td>
                        <td data-label="Клик → заказ">{percent(goal.orders, push.clicked)}</td>
                        <td data-label="Выручка">{money.format(goal.revenue)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!visiblePushes.length && (
                <div className="empty-state">
                  <strong>Пуши не найдены</strong>
                  <span>Измените проект, запрос или период.</span>
                </div>
              )}
            </div>
          </article>
        </section>

        {selected && (
          <section className="panel detail-panel">
            <div className="panel-heading detail-heading">
              <div>
                <span className="detail-kicker">Выбранный пуш</span>
                <h2>{selected.title || selected.name}</h2>
              </div>
              <div className="detail-heading-actions">
                <div className="selected-benchmark">
                  <span>CTR к среднему</span>
                  <strong>
                    {delta(
                      selected.clicked / Math.max(selected.delivered, 1),
                      avgCtr,
                    )}
                  </strong>
                </div>
                <button
                  className="purchases-button"
                  disabled={!selectedGoal.orders}
                  onClick={openPurchases}
                >
                  <span className="purchases-button-metrics">
                    <strong>Заказы · {number.format(selectedGoal.orders)}</strong>
                    <small>{buyersText(selectedGoal.buyers)}</small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </button>
              </div>
            </div>

            <div className="detail-sections">
              <article className="message-section">
                <div className="subhead">
                  <span>Сообщение</span>
                  <small>{dateTime.format(new Date(selected.sentAt))}</small>
                </div>
                <div className="push-preview">
                  <div className="phone-top">
                    <span className="app-icon">Б</span>
                    <span>{selectedProject?.shortName ?? "Push"}</span>
                    <small>сейчас</small>
                  </div>
                  <strong>{selected.title || "Заголовок не выгружен"}</strong>
                  <p>{selected.body || "Текст нужно добавить из карточки рассылки Mindbox."}</p>
                </div>
                <dl className="message-facts">
                  <div>
                    <dt>Проект</dt>
                    <dd>{selectedProject?.name ?? selected.projectId}</dd>
                  </div>
                  <div className="applications-fact">
                    <dt>Приложение</dt>
                    <dd>
                      {selected.applications?.length
                        ? selected.applications.join(" · ")
                        : "Не указано"}
                    </dd>
                  </div>
                </dl>
              </article>

              <article className="latency-section">
                <div className="subhead">
                  <span>Скорость заказа</span>
                  <div className="subhead-metrics">
                    <strong>{percent(selectedGoal.orders, selected.clicked)}</strong>
                    <small>
                      {ordersText(selectedGoal.orders)} ·{" "}
                      {buyersText(selectedGoal.buyers)}
                    </small>
                  </div>
                </div>
                <div className="latency-bars">
                  {[
                    ["до 1 часа", selectedGoal.latency[0]],
                    ["1–4 часа", selectedGoal.latency[1]],
                    ["4–12 часов", selectedGoal.latency[2]],
                    ["12–24 часа", selectedGoal.latency[3]],
                  ].map(([label, value]) => {
                    const numericValue = Number(value);
                    const max = Math.max(...selectedGoal.latency, 1);
                    return (
                      <div className="latency-row" key={String(label)}>
                        <span>{label}</span>
                        <div className="bar-track">
                          <div
                            className="bar-fill"
                            style={{ width: `${(numericValue / max) * 100}%` }}
                          />
                        </div>
                        <strong>{number.format(numericValue)}</strong>
                      </div>
                    );
                  })}
                </div>
                <div className="speed-callout">
                  <strong>
                    {percent(selectedGoal.latency[0], selectedGoal.orders)}
                  </strong>
                  <span>заказов происходит в первый час после клика</span>
                </div>
              </article>

              <article className="quality-section">
                <div className="subhead">
                  <span>Доставка и платформы</span>
                  <strong>{percent(selected.delivered, selected.sent)}</strong>
                </div>
                <div className="platform-stack" aria-label="Распределение по платформам">
                  <span
                    className="android"
                    style={{
                      width: `${(selected.platforms.android / Math.max(selectedPlatformTotal, 1)) * 100}%`,
                    }}
                  />
                  <span
                    className="ios"
                    style={{
                      width: `${(selected.platforms.ios / Math.max(selectedPlatformTotal, 1)) * 100}%`,
                    }}
                  />
                  <span
                    className="unknown"
                    style={{
                      width: `${(selected.platforms.unknown / Math.max(selectedPlatformTotal, 1)) * 100}%`,
                    }}
                  />
                </div>
                <div className="platform-legend">
                  <div>
                    <span><i className="android" />Android</span>
                    <strong>{percent(selected.platforms.android, selectedPlatformTotal)}</strong>
                  </div>
                  <div>
                    <span><i className="ios" />iOS</span>
                    <strong>{percent(selected.platforms.ios, selectedPlatformTotal)}</strong>
                  </div>
                  <div>
                    <span><i className="unknown" />Не определено</span>
                    <strong>{percent(selected.platforms.unknown, selectedPlatformTotal)}</strong>
                  </div>
                </div>
                <div className="delivery-loss">
                  <span>Не доставлено</span>
                  <strong>{number.format(selected.notDelivered)}</strong>
                  <small>{percent(selected.notDelivered, selected.sent)} от отправленных</small>
                </div>
              </article>
            </div>
          </section>
        )}

        {purchasesOpen && selected && (
          <div
            className="purchase-modal-backdrop"
            onMouseDown={(event) => {
              if (event.currentTarget === event.target) {
                setPurchasesOpen(false);
              }
            }}
          >
            <section
              className="purchase-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="purchase-modal-title"
            >
              <header className="purchase-modal-head">
                <div>
                  <span className="modal-kicker">Покупки после пуша</span>
                  <h2 id="purchase-modal-title">{selected.title || selected.name}</h2>
                </div>
                <button
                  className="modal-close"
                  onClick={() => setPurchasesOpen(false)}
                  aria-label="Закрыть покупки"
                >
                  ×
                </button>
              </header>

              <div className="purchase-summary">
                <div>
                  <span>Заказов</span>
                  <strong>{number.format(attributedOrders.length)}</strong>
                </div>
                <div>
                  <span>Покупателей</span>
                  <strong>{number.format(attributedBuyers)}</strong>
                </div>
                <div>
                  <span>Выручка</span>
                  <strong>
                    {money.format(
                      attributedOrders.reduce(
                        (sum, order) => sum + order.revenue,
                        0,
                      ),
                    )}
                  </strong>
                </div>
                <div>
                  <span>Средний чек</span>
                  <strong>
                    {money.format(
                      attributedOrders.length
                        ? attributedOrders.reduce(
                            (sum, order) => sum + order.revenue,
                            0,
                          ) / attributedOrders.length
                        : 0,
                    )}
                  </strong>
                </div>
              </div>

              {!purchasesLoading && unresolvedProductLines > 0 && (
                <div className="purchase-catalog-note" role="status">
                  Для {number.format(unresolvedProductLines)} товарных позиций
                  каталог Mindbox ещё не загружен — временно показаны ID и SKU.
                </div>
              )}

              <div className="purchase-modal-body">
                {purchasesLoading && (
                  <div className="purchase-state">Загружаем покупки из Supabase…</div>
                )}
                {purchasesError && (
                  <div className="purchase-state error">{purchasesError}</div>
                )}
                {!purchasesLoading &&
                  !purchasesError &&
                  !attributedOrders.length && (
                    <div className="purchase-state">
                      Для этого пуша и выбранной цели покупок нет.
                    </div>
                  )}
                {!purchasesLoading &&
                  attributedOrders.map((order, orderIndex) => (
                    <article className="purchase-card" key={order.id}>
                      <div className="purchase-card-head">
                        <div>
                          <span>Заказ {orderIndex + 1}</span>
                          <strong>{dateTime.format(new Date(order.purchasedAt))}</strong>
                          <small>
                            {data.projects.find(
                              (project) =>
                                project.id === order.orderProjectId,
                            )?.name ?? order.orderProjectId}
                          </small>
                        </div>
                        <div>
                          <span>
                            после клика ·{" "}
                            {order.latencyMinutes < 60
                              ? `${order.latencyMinutes} мин`
                              : `${(order.latencyMinutes / 60)
                                  .toFixed(1)
                                  .replace(".", ",")} ч`}
                          </span>
                          <strong>{money.format(order.revenue)}</strong>
                        </div>
                      </div>
                      <div className="purchase-items">
                        {order.items.length ? (
                          order.items.map((item) => (
                            <div className="purchase-item" key={item.lineKey}>
                              <div>
                                <strong>{item.displayName}</strong>
                                <span>
                                  {number.format(item.quantity)} шт.
                                  {item.unitPrice !== null
                                    ? ` · ${money.format(item.unitPrice)} за ед.`
                                    : ""}
                                </span>
                              </div>
                              <strong>
                                {item.lineAmount !== null
                                  ? money.format(item.lineAmount)
                                  : "—"}
                              </strong>
                            </div>
                          ))
                        ) : (
                          <p className="no-items">
                            Состав заказа не передан Mindbox.
                          </p>
                        )}
                      </div>
                    </article>
                  ))}
              </div>
            </section>
          </div>
        )}
      </section>
    </main>
  );
}
