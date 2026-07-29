"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

type Project = { id: string; name: string; shortName: string };
type Goal = Project;
type DailyMetric = {
  date: string;
  participants: number;
  uniqueRecipients: number;
  sent: number;
  delivered: number;
  clicked: number;
  notSent: number;
  notDelivered: number;
  notSentReasons: Record<string, number>;
  notDeliveredReasons: Record<string, number>;
};
type OrderMetric = {
  period: string;
  goalId: string;
  orderProjectId: string;
  orders: number;
  buyers: number;
  revenue: number;
  latency: [number, number, number, number];
};
type TriggerMessage = {
  id: number;
  scenarioId: number;
  mindboxScenarioId: string;
  scenarioName: string;
  projectId: string;
  messageKey: string;
  name: string;
  title: string;
  body: string;
  mailingType: "trigger";
  applications: string[];
  platforms: string[];
  firstActivityAt: string | null;
  lastActivityAt: string | null;
  daily: DailyMetric[];
  orderMetrics: OrderMetric[];
};
type TriggerData = {
  generatedAt: string;
  sourceCoverageEnd: string | null;
  attribution: { windowHours: number; model: string };
  projects: Project[];
  goals: Goal[];
  selectionOrderMetrics: Array<
    OrderMetric & {
      pushProjectId: string;
    }
  >;
  messages: TriggerMessage[];
};
type PurchaseItem = {
  lineKey: string;
  displayName: string;
  vendorCode: string | null;
  catalogMatched: boolean;
  quantity: number;
  quantityType: string | null;
  unitPrice: number | null;
  lineAmount: number | null;
  statusCategory: string | null;
};
type Purchase = {
  id: number;
  orderKey: string;
  purchasedAt: string;
  attributedClickAt: string;
  latencyMinutes: number;
  revenue: number;
  orderProjectId: string;
  items: PurchaseItem[];
};

const number = new Intl.NumberFormat("ru-RU");
const money = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 0,
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
const emptyData: TriggerData = {
  generatedAt: new Date(0).toISOString(),
  sourceCoverageEnd: null,
  attribution: { windowHours: 24, model: "Последний клик" },
  projects: [],
  goals: [],
  selectionOrderMetrics: [],
  messages: [],
};

function percent(value: number, base: number) {
  return base ? `${((value / base) * 100).toFixed(2).replace(".", ",")}%` : "—";
}

function monthLabel(month: string) {
  const value = monthName.format(new Date(`${month}-15T12:00:00+03:00`));
  return value.charAt(0).toLocaleUpperCase("ru") + value.slice(1);
}

function inPeriod(date: string, period: string, coverageEnd: string | null) {
  if (period === "all") return true;
  if (period === "7d") {
    if (!coverageEnd) return false;
    const cutoff =
      new Date(`${coverageEnd}T23:59:59+03:00`).getTime() -
      7 * 24 * 60 * 60 * 1000;
    return new Date(`${date}T12:00:00+03:00`).getTime() >= cutoff;
  }
  return date.startsWith(period);
}

function dailyTotals(
  message: TriggerMessage,
  period: string,
  coverageEnd: string | null,
) {
  return message.daily
    .filter((metric) => inPeriod(metric.date, period, coverageEnd))
    .reduce(
      (total, metric) => ({
        participants: total.participants + metric.participants,
        recipients: total.recipients + metric.uniqueRecipients,
        sent: total.sent + metric.sent,
        delivered: total.delivered + metric.delivered,
        clicked: total.clicked + metric.clicked,
        notSent: total.notSent + metric.notSent,
        notDelivered: total.notDelivered + metric.notDelivered,
      }),
      {
        participants: 0,
        recipients: 0,
        sent: 0,
        delivered: 0,
        clicked: 0,
        notSent: 0,
        notDelivered: 0,
      },
    );
}

function orderTotals(
  message: TriggerMessage,
  period: string,
  goalId: string,
  orderProjectId: string,
) {
  return (
    message.orderMetrics.find(
      (metric) =>
        metric.period === period &&
        metric.goalId === goalId &&
        metric.orderProjectId === orderProjectId,
    ) ?? {
      orders: 0,
      buyers: 0,
      revenue: 0,
      latency: [0, 0, 0, 0] as [number, number, number, number],
    }
  );
}

export default function TriggerPushesPage() {
  const [data, setData] = useState<TriggerData>(emptyData);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [projectId, setProjectId] = useState("all");
  const [goalId, setGoalId] = useState("all-orders");
  const [orderProjectId, setOrderProjectId] = useState("all");
  const [period, setPeriod] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [purchasesOpen, setPurchasesOpen] = useState(false);
  const [purchasesLoading, setPurchasesLoading] = useState(false);
  const [purchasesError, setPurchasesError] = useState("");
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [purchaseBuyers, setPurchaseBuyers] = useState(0);

  useEffect(() => {
    fetch("/api/triggers", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Trigger API is unavailable");
        return response.json();
      })
      .then((payload: TriggerData) => {
        setData(payload);
        setSelectedId(payload.messages[0]?.id ?? null);
      })
      .catch(() => setLoadError("Не удалось загрузить trigger-пуши из Supabase."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!purchasesOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPurchasesOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [purchasesOpen]);

  const months = useMemo(
    () =>
      [
        ...new Set(
          data.messages.flatMap((message) =>
            message.daily.map((metric) => metric.date.slice(0, 7)),
          ),
        ),
      ].sort(),
    [data.messages],
  );

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    return data.messages
      .filter((message) => {
        const daily = dailyTotals(message, period, data.sourceCoverageEnd);
        return (
          daily.participants > 0 &&
          (projectId === "all" || message.projectId === projectId) &&
          (!normalized ||
            `${message.scenarioName} ${message.name} ${message.title} ${message.body}`
              .toLocaleLowerCase("ru")
              .includes(normalized))
        );
      })
      .sort((a, b) => {
        const orderDifference =
          orderTotals(b, period, goalId, orderProjectId).orders -
          orderTotals(a, period, goalId, orderProjectId).orders;
        if (orderDifference) return orderDifference;
        return (
          new Date(b.lastActivityAt ?? 0).getTime() -
          new Date(a.lastActivityAt ?? 0).getTime()
        );
      });
  }, [
    data.messages,
    data.sourceCoverageEnd,
    goalId,
    orderProjectId,
    period,
    projectId,
    query,
  ]);

  const totals = useMemo(
    () =>
      visible.reduce(
        (total, message) => {
          const daily = dailyTotals(message, period, data.sourceCoverageEnd);
          const orders = orderTotals(
            message,
            period,
            goalId,
            orderProjectId,
          );
          total.sent += daily.sent;
          total.delivered += daily.delivered;
          total.clicked += daily.clicked;
          total.notSent += daily.notSent;
          total.orders += orders.orders;
          total.buyers += orders.buyers;
          total.revenue += orders.revenue;
          return total;
        },
        {
          sent: 0,
          delivered: 0,
          clicked: 0,
          notSent: 0,
          orders: 0,
          buyers: 0,
          revenue: 0,
        },
      ),
    [
      data.sourceCoverageEnd,
      goalId,
      orderProjectId,
      period,
      visible,
    ],
  );

  const selected =
    visible.find((message) => message.id === selectedId) ??
    visible[0] ??
    data.messages[0];
  const exactSelectionMetric = !query.trim()
    ? (data.selectionOrderMetrics ?? []).find(
        (metric) =>
          metric.period === period &&
          metric.goalId === goalId &&
          metric.orderProjectId === orderProjectId &&
          metric.pushProjectId === projectId,
      )
    : undefined;
  const resolvedOrders = exactSelectionMetric?.orders ?? totals.orders;
  const resolvedBuyers = exactSelectionMetric?.buyers ?? totals.buyers;
  const resolvedRevenue = exactSelectionMetric?.revenue ?? totals.revenue;
  const bestByOrder = visible
    .filter(
      (message) =>
        orderTotals(message, period, goalId, orderProjectId).orders > 0,
    )
    .sort((a, b) => {
      const aDaily = dailyTotals(a, period, data.sourceCoverageEnd);
      const bDaily = dailyTotals(b, period, data.sourceCoverageEnd);
      return (
        orderTotals(b, period, goalId, orderProjectId).orders /
          Math.max(bDaily.clicked, 1) -
        orderTotals(a, period, goalId, orderProjectId).orders /
          Math.max(aDaily.clicked, 1)
      );
    })[0];
  const bestByCtr = [...visible].sort((a, b) => {
    const aDaily = dailyTotals(a, period, data.sourceCoverageEnd);
    const bDaily = dailyTotals(b, period, data.sourceCoverageEnd);
    return (
      bDaily.clicked / Math.max(bDaily.delivered, 1) -
      aDaily.clicked / Math.max(aDaily.delivered, 1)
    );
  })[0];

  async function openPurchases(message: TriggerMessage) {
    setSelectedId(message.id);
    setPurchasesOpen(true);
    setPurchasesLoading(true);
    setPurchasesError("");
    setPurchases([]);
    try {
      const params = new URLSearchParams({
        scenarioMailingId: String(message.id),
        goalId,
        orderProjectId,
        period,
      });
      const response = await fetch(`/api/trigger-purchases?${params}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Purchases are unavailable");
      const payload = (await response.json()) as {
        buyers: number;
        orders: Purchase[];
      };
      setPurchaseBuyers(payload.buyers);
      setPurchases(payload.orders);
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
          <p className="eyebrow">PUSH ANALYTICS</p>
          <h1>Загружаем trigger-пуши</h1>
          <p>Собираем сценарии, отклики и покупки.</p>
        </div>
      </main>
    );
  }
  if (loadError) {
    return (
      <main className="state-screen">
        <div className="state-card">
          <p className="eyebrow">PUSH ANALYTICS</p>
          <h1>Данные не загрузились</h1>
          <p>{loadError}</p>
          <button onClick={() => window.location.reload()}>Повторить</button>
        </div>
      </main>
    );
  }

  return (
    <main className="dashboard-shell trigger-dashboard">
      <section className="content">
        <header className="topbar">
          <div>
            <h1>PUSH ANALYTICS</h1>
            <p className="subtitle">Триггерные пуши</p>
          </div>
          <div className="topbar-actions">
            <Link className="report-link secondary-link" href="/">
              Массовые пуши
            </Link>
            <div className="sync-status">
              <span>
                Данные по {data.sourceCoverageEnd ?? "—"}
              </span>
              <strong>Только type = trigger · 24 ч</strong>
            </div>
          </div>
        </header>

        <section className="command-bar" aria-label="Фильтры trigger-пушей">
          <label className="command-control project-filter">
            <span>Проект пуша</span>
            <select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="all">Все проекты</option>
              {data.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="command-control goal-filter">
            <span>Целевое действие</span>
            <select
              value={goalId}
              onChange={(event) => setGoalId(event.target.value)}
            >
              {data.goals.map((goal) => (
                <option key={goal.id} value={goal.id}>
                  {goal.name}
                </option>
              ))}
            </select>
          </label>
          <label className="command-control order-project-filter">
            <span>Где сделана покупка</span>
            <select
              value={orderProjectId}
              onChange={(event) => setOrderProjectId(event.target.value)}
            >
              <option value="all">Все проекты заказов</option>
              {data.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
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
              placeholder="Сценарий или сообщение"
            />
          </label>
          <div className="period-switch trigger-periods" aria-label="Период">
            <button
              className={period === "7d" ? "selected" : ""}
              onClick={() => setPeriod("7d")}
            >
              7 дней
            </button>
            {months.map((month) => (
              <button
                key={month}
                className={period === month ? "selected" : ""}
                onClick={() => setPeriod(month)}
              >
                {monthLabel(month)}
              </button>
            ))}
            <button
              className={period === "all" ? "selected" : ""}
              onClick={() => setPeriod("all")}
            >
              Весь период
            </button>
          </div>
        </section>

        <section className="trigger-kpis" aria-label="Итоги">
          <article>
            <span>Отправлено</span>
            <strong>{number.format(totals.sent)}</strong>
            <small>{number.format(totals.notSent)} не отправлено</small>
          </article>
          <article>
            <span>Открыли</span>
            <strong>{number.format(totals.clicked)}</strong>
            <small>CTR {percent(totals.clicked, totals.delivered)}</small>
          </article>
          <article className="accent">
            <span>Заказы</span>
            <strong>{number.format(resolvedOrders)}</strong>
            <small>{percent(resolvedOrders, totals.clicked)} после клика</small>
          </article>
          <article>
            <span>Покупатели</span>
            <strong>{number.format(resolvedBuyers)}</strong>
            <small>уникальные в выборке</small>
          </article>
          <article>
            <span>Выручка</span>
            <strong>{money.format(resolvedRevenue)}</strong>
            <small>
              {resolvedOrders
                ? `Средний чек ${money.format(resolvedRevenue / resolvedOrders)}`
                : "Покупок нет"}
            </small>
          </article>
        </section>

        <section className="trigger-signal">
          <div>
            <span className="signal-label">
              {bestByOrder ? "Лучше конвертирует" : "Сигнал по отклику"}
            </span>
            <h2>
              {(bestByOrder ?? bestByCtr)?.title ||
                (bestByOrder ?? bestByCtr)?.scenarioName ||
                "Недостаточно данных"}
            </h2>
            <p>
              {bestByOrder
                ? `${number.format(orderTotals(bestByOrder, period, goalId, orderProjectId).orders)} заказов · ${percent(
                    orderTotals(bestByOrder, period, goalId, orderProjectId)
                      .orders,
                    dailyTotals(
                      bestByOrder,
                      period,
                      data.sourceCoverageEnd,
                    ).clicked,
                  )} после клика`
                : bestByCtr
                  ? `Покупок по выбранной цели нет. Показываем лучший CTR: ${percent(
                      dailyTotals(bestByCtr, period, data.sourceCoverageEnd)
                        .clicked,
                      dailyTotals(bestByCtr, period, data.sourceCoverageEnd)
                        .delivered,
                    )}.`
                  : "Измените фильтры, чтобы увидеть результат."}
            </p>
          </div>
          <div className="trigger-signal-note">
            <strong>Честное сравнение</strong>
            <span>
              Заказ получает последний клик среди массовых, trigger и
              transaction MobilePush за 24 часа.
            </span>
          </div>
        </section>

        <section className="panel trigger-table-panel">
          <div className="panel-heading">
            <div>
              <h2>Сценарии и сообщения</h2>
              <p className="section-description">
                {visible.length} trigger-сообщений
              </p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="trigger-table">
              <thead>
                <tr>
                  <th>Сценарий / сообщение</th>
                  <th>Отправлено</th>
                  <th>Открыли</th>
                  <th>CTR</th>
                  <th>Не отправлено</th>
                  <th>Заказы</th>
                  <th>Покупатели</th>
                  <th>Выручка</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((message) => {
                  const daily = dailyTotals(
                    message,
                    period,
                    data.sourceCoverageEnd,
                  );
                  const orders = orderTotals(
                    message,
                    period,
                    goalId,
                    orderProjectId,
                  );
                  return (
                    <tr
                      key={message.id}
                      className={selected?.id === message.id ? "selected-row" : ""}
                      onClick={() => setSelectedId(message.id)}
                    >
                      <td>
                        <button
                          className="mailing-name trigger-name"
                          onClick={() => setSelectedId(message.id)}
                        >
                          <span>{message.title || message.name}</span>
                          <small>
                            <span className="project-tag">
                              {data.projects.find(
                                (project) => project.id === message.projectId,
                              )?.shortName}
                            </span>
                            {message.scenarioName}
                          </small>
                        </button>
                      </td>
                      <td data-label="Отправлено">
                        <strong>{number.format(daily.sent)}</strong>
                      </td>
                      <td data-label="Открыли">
                        {number.format(daily.clicked)}
                      </td>
                      <td data-label="CTR">
                        <strong>{percent(daily.clicked, daily.delivered)}</strong>
                      </td>
                      <td data-label="Не отправлено">
                        {number.format(daily.notSent)}
                      </td>
                      <td data-label="Заказы">
                        <strong className="order-value">
                          {number.format(orders.orders)}
                        </strong>
                      </td>
                      <td data-label="Покупатели">
                        {number.format(orders.buyers)}
                      </td>
                      <td data-label="Выручка">{money.format(orders.revenue)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!visible.length && (
              <div className="empty-state">
                <strong>Нет trigger-пушей в этой выборке</strong>
                <span>Измените проект, период или поисковый запрос.</span>
              </div>
            )}
          </div>
        </section>

        {selected && (
          <section className="trigger-detail">
            <div className="trigger-detail-copy">
              <span className="signal-label">Выбранное сообщение</span>
              <h2>{selected.title || selected.name}</h2>
              <p>
                {selected.body ||
                  "Текст сообщения пока определяется по названию рассылки Mindbox."}
              </p>
              <div className="trigger-tags">
                <span>{selected.scenarioName}</span>
                {selected.applications.map((application) => (
                  <span key={application}>{application}</span>
                ))}
              </div>
            </div>
            <div className="trigger-detail-action">
              <span>Покупки по выбранным фильтрам</span>
              <strong>
                {number.format(
                  orderTotals(selected, period, goalId, orderProjectId).orders,
                )}
              </strong>
              <button
                disabled={
                  orderTotals(selected, period, goalId, orderProjectId).orders ===
                  0
                }
                onClick={() => openPurchases(selected)}
              >
                Посмотреть заказы
              </button>
            </div>
          </section>
        )}
      </section>

      {purchasesOpen && selected && (
        <div
          className="purchase-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setPurchasesOpen(false);
          }}
        >
          <section
            className="purchase-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="trigger-purchases-title"
          >
            <header className="purchase-modal-head">
              <div>
                <span className="modal-kicker">Покупки после trigger-пуша</span>
                <h2 id="trigger-purchases-title">
                  {selected.title || selected.name}
                </h2>
              </div>
              <button
                className="modal-close"
                aria-label="Закрыть"
                onClick={() => setPurchasesOpen(false)}
              >
                ×
              </button>
            </header>
            <div className="purchase-summary">
              <div>
                <span>Заказы</span>
                <strong>{number.format(purchases.length)}</strong>
              </div>
              <div>
                <span>Покупатели</span>
                <strong>{number.format(purchaseBuyers)}</strong>
              </div>
              <div>
                <span>Выручка</span>
                <strong>
                  {money.format(
                    purchases.reduce((sum, order) => sum + order.revenue, 0),
                  )}
                </strong>
              </div>
              <div>
                <span>Окно</span>
                <strong>24 ч</strong>
              </div>
            </div>
            <div className="purchase-modal-body">
              {purchasesLoading && (
                <div className="purchase-state">Загружаем покупки…</div>
              )}
              {purchasesError && (
                <div className="purchase-state error">{purchasesError}</div>
              )}
              {!purchasesLoading &&
                !purchasesError &&
                purchases.length === 0 && (
                  <div className="purchase-state">
                    Заказов по выбранным фильтрам нет.
                  </div>
                )}
              {!purchasesLoading &&
                purchases.map((order) => (
                  <article className="purchase-card" key={order.id}>
                    <div className="purchase-card-head">
                      <div>
                        <span>Покупка</span>
                        <strong>
                          {dateTime.format(new Date(order.purchasedAt))}
                        </strong>
                        <small>
                          через {number.format(order.latencyMinutes)} мин после
                          клика
                        </small>
                      </div>
                      <div>
                        <span>Сумма</span>
                        <strong>{money.format(order.revenue)}</strong>
                        <small>
                          {data.projects.find(
                            (project) =>
                              project.id === order.orderProjectId,
                          )?.shortName ?? order.orderProjectId}
                        </small>
                      </div>
                    </div>
                    <div className="purchase-items">
                      {order.items.map((item) => (
                        <div className="purchase-item" key={item.lineKey}>
                          <div>
                            <strong>{item.displayName}</strong>
                            <span>
                              {number.format(item.quantity)}
                              {item.quantityType ? ` ${item.quantityType}` : ""}
                              {item.vendorCode
                                ? ` · артикул ${item.vendorCode}`
                                : ""}
                            </span>
                          </div>
                          <strong>
                            {item.lineAmount === null
                              ? "—"
                              : money.format(item.lineAmount)}
                          </strong>
                        </div>
                      ))}
                      {!order.items.length && (
                        <p className="no-items">
                          Состав заказа не передан в выгрузке.
                        </p>
                      )}
                    </div>
                  </article>
                ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
