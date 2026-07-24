"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

type Campaign = {
  id: string;
  databaseId: number;
  name: string;
  title: string;
  body: string;
  applications: string[];
  sentAt: string;
  sent: number;
  delivered: number;
  clicked: number;
  notDelivered: number;
  type: "commercial" | "research";
  orders: number;
  buyers: number;
  revenue: number;
  ordersInOtherProjects: number;
};

type ReportData = {
  generatedAt: string;
  dataThrough: string;
  source: "supabase";
  scope: {
    pushProjectId: string;
    orderProjectId: string;
    goalId: string;
    attributionModel: string;
    attributionWindowHours: number;
    timezone: string;
    periodStart: string;
    periodEndExclusive: string;
  };
  summary: {
    campaigns: number;
    commercialCampaigns: number;
    researchCampaigns: number;
    sent: number;
    delivered: number;
    clicked: number;
    orders: number;
    uniqueBuyers: number;
    revenue: number;
    ordersInOtherProjects: number;
  };
  campaigns: Campaign[];
};

const number = new Intl.NumberFormat("ru-RU");
const money = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 0,
});
const date = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  timeZone: "Europe/Moscow",
});
const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});

function rate(value: number, base: number) {
  return base > 0 ? (value / base) * 100 : 0;
}

function percent(value: number, base: number) {
  return `${rate(value, base).toFixed(2).replace(".", ",")}%`;
}

function ArrowIcon({ direction = "right" }: { direction?: "left" | "right" }) {
  return (
    <svg
      aria-hidden="true"
      className={direction === "left" ? "arrow-icon is-left" : "arrow-icon"}
      viewBox="0 0 24 24"
    >
      <path d="M5 12h14M14 7l5 5-5 5" />
    </svg>
  );
}

function summarize(campaigns: Campaign[]) {
  return campaigns.reduce(
    (total, campaign) => ({
      delivered: total.delivered + campaign.delivered,
      clicked: total.clicked + campaign.clicked,
      orders: total.orders + campaign.orders,
    }),
    { delivered: 0, clicked: 0, orders: 0 },
  );
}

export default function BlizkoJulyReport() {
  const [data, setData] = useState<ReportData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/reports/blizko-july", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as
            | { error?: string }
            | null;
          throw new Error(payload?.error ?? `HTTP ${response.status}`);
        }
        return response.json() as Promise<ReportData>;
      })
      .then(setData)
      .catch((requestError: unknown) => {
        if (requestError instanceof Error && requestError.name === "AbortError") {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Не удалось загрузить отчет",
        );
      });

    return () => controller.abort();
  }, []);

  const analysis = useMemo(() => {
    if (!data) return null;

    const commercial = data.campaigns
      .filter((campaign) => campaign.type === "commercial")
      .sort((a, b) => b.orders - a.orders || b.clicked - a.clicked);
    const research = data.campaigns.filter(
      (campaign) => campaign.type === "research",
    );
    const topByOrders = commercial[0];
    const topByConversion = [...commercial].sort(
      (a, b) =>
        rate(b.orders, b.clicked) - rate(a.orders, a.clicked) ||
        b.orders - a.orders,
    )[0];
    const topByRevenue = [...commercial].sort(
      (a, b) => b.revenue - a.revenue,
    )[0];
    const topPair = summarize(commercial.slice(0, 2));
    const rest = summarize(commercial.slice(2));
    const researchTotals = summarize(research);

    return {
      commercial,
      research,
      topByOrders,
      topByConversion,
      topByRevenue,
      topPair,
      rest,
      researchTotals,
    };
  }, [data]);

  if (error) {
    return (
      <main className="report-state">
        <div>
          <p>PUSH ANALYTICS</p>
          <h1>Отчет не загрузился</h1>
          <p>{error}</p>
          <button onClick={() => window.location.reload()}>Повторить</button>
        </div>
      </main>
    );
  }

  if (!data || !analysis) {
    return (
      <main className="report-state">
        <div>
          <p>PUSH ANALYTICS</p>
          <h1>Собираем июльский отчет</h1>
          <p>Загружаем тексты, открытия и покупки из Supabase.</p>
        </div>
      </main>
    );
  }

  const maxOrders = Math.max(
    ...analysis.commercial.map((campaign) => campaign.orders),
    1,
  );
  const topPairOrderShare = rate(
    analysis.topPair.orders,
    data.summary.orders,
  );

  return (
    <main className="july-report">
      <header className="report-nav">
        <Link href="/" className="report-back">
          <ArrowIcon direction="left" />
          PUSH ANALYTICS
        </Link>
        <span>Обновлено {dateTime.format(new Date(data.generatedAt))}</span>
      </header>

      <article className="report-document">
        <header className="report-title">
          <div>
            <h1>Пуши Blizko за июль</h1>
            <p>
              Отдельное приложение · данные по {date.format(new Date(data.dataThrough))}
            </p>
          </div>
          <dl className="report-scope">
            <div>
              <dt>Покупка</dt>
              <dd>в приложении Blizko</dd>
            </div>
            <div>
              <dt>Атрибуция</dt>
              <dd>последний клик · 24 ч</dd>
            </div>
          </dl>
        </header>

        <section className="executive-summary" aria-labelledby="summary-title">
          <h2 id="summary-title">Executive Summary</h2>
          <div className="summary-grid">
            <p>
              <strong>
                {number.format(data.summary.orders)} заказов от{" "}
                {number.format(data.summary.uniqueBuyers)} покупателей.
              </strong>{" "}
              Они принесли {money.format(data.summary.revenue)} после клика по
              июльским пушам отдельного приложения Blizko.
            </p>
            <p>
              <strong>
                Два лидирующих текста дали {topPairOrderShare.toFixed(0)}% всех
                заказов.
              </strong>{" "}
              Их общий CTR —{" "}
              {percent(analysis.topPair.clicked, analysis.topPair.delivered)},
              конверсия клика в заказ —{" "}
              {percent(analysis.topPair.orders, analysis.topPair.clicked)}.
            </p>
            <p>
              <strong>
                Лучший результат дает конкретный продукт в понятном контексте.
              </strong>{" "}
              Локальная еда и готовое футбольное комбо обошли общие сообщения
              про категории по открытию и покупке.
            </p>
          </div>
        </section>

        <section className="report-kpis" aria-label="Итоги июля">
          <article>
            <span>Коммерческих пушей</span>
            <strong>{data.summary.commercialCampaigns}</strong>
            <small>+ {data.summary.researchCampaigns} исследовательских</small>
          </article>
          <article>
            <span>Доставлено</span>
            <strong>{number.format(data.summary.delivered)}</strong>
            <small>{percent(data.summary.delivered, data.summary.sent)} от отправок</small>
          </article>
          <article>
            <span>Открыли</span>
            <strong>{number.format(data.summary.clicked)}</strong>
            <small>CTR {percent(data.summary.clicked, data.summary.delivered)}</small>
          </article>
          <article className="is-accent">
            <span>Заказы · покупатели</span>
            <strong>
              {number.format(data.summary.orders)} ·{" "}
              {number.format(data.summary.uniqueBuyers)}
            </strong>
            <small>
              {percent(data.summary.orders, data.summary.clicked)} после клика
            </small>
          </article>
          <article>
            <span>Выручка</span>
            <strong>{money.format(data.summary.revenue)}</strong>
            <small>
              Средний заказ{" "}
              {money.format(data.summary.revenue / Math.max(data.summary.orders, 1))}
            </small>
          </article>
        </section>

        <section className="report-section" aria-labelledby="ranking-title">
          <div className="section-copy">
            <h2 id="ranking-title">Два текста заметно подняли планку</h2>
            <p>
              «{analysis.topByOrders.title}» и «
              {analysis.commercial[1]?.title}» собрали{" "}
              {number.format(analysis.topPair.orders)} заказов. У остальных
              коммерческих пушей общий CTR —{" "}
              {percent(analysis.rest.clicked, analysis.rest.delivered)}, а
              конверсия после клика —{" "}
              {percent(analysis.rest.orders, analysis.rest.clicked)}.
            </p>
          </div>

          <figure className="orders-ranking">
            <figcaption>
              <strong>Заказы по коммерческим пушам</strong>
              <span>
                Только покупки в отдельном приложении Blizko · 24 часа после
                последнего клика
              </span>
            </figcaption>
            <div className="ranking-list">
              {analysis.commercial.map((campaign, index) => (
                <div className="ranking-row" key={campaign.id}>
                  <span className="ranking-position">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="ranking-label">{campaign.title}</span>
                  <span className="ranking-track" aria-hidden="true">
                    <span
                      style={{
                        width: `${(campaign.orders / maxOrders) * 100}%`,
                      }}
                    />
                  </span>
                  <strong>{campaign.orders}</strong>
                </div>
              ))}
            </div>
          </figure>
        </section>

        <section className="report-section" aria-labelledby="why-title">
          <div className="section-copy">
            <h2 id="why-title">Что сработало в тексте — и почему</h2>
            <p>
              Ниже — интерпретация наблюдаемого результата, а не доказанная
              причинность: аудитории, время отправки и предложения различались.
            </p>
          </div>

          <div className="insight-list">
            <article>
              <span>01</span>
              <div>
                <h3>Знакомая еда и конкретные названия лучше цепляют внимание</h3>
                <p>
                  «{analysis.topByOrders.title}» прямо называет чуду, пирожки,
                  блины и Равзу. Это самый высокий коммерческий CTR —{" "}
                  {percent(
                    analysis.topByOrders.clicked,
                    analysis.topByOrders.delivered,
                  )}{" "}
                  — и максимум заказов: {analysis.topByOrders.orders}. Читатель
                  сразу понимает, что именно получит.
                </p>
              </div>
            </article>
            <article>
              <span>02</span>
              <div>
                <h3>Ситуация + готовое комбо лучше доводят к заказу</h3>
                <p>
                  «{analysis.topByConversion.title}» связывает чемпионат,
                  момент «самое время» и готовый набор из чипсов и напитков.
                  Результат — лучшая конверсия после клика:{" "}
                  {percent(
                    analysis.topByConversion.orders,
                    analysis.topByConversion.clicked,
                  )}{" "}
                  и самая высокая выручка —{" "}
                  {money.format(analysis.topByRevenue.revenue)}.
                </p>
              </div>
            </article>
            <article>
              <span>03</span>
              <div>
                <h3>Общие категории работают ровнее, но слабее открываются</h3>
                <p>
                  Пуши про напитки, фрукты и готовые блюда получили коммерческий
                  CTR около 0,72–0,85%. В них есть товарная категория, но меньше
                  отличимого повода открыть сообщение именно сейчас.
                </p>
              </div>
            </article>
            <article>
              <span>04</span>
              <div>
                <h3>Исследовательские пуши нужно оценивать отдельно</h3>
                <p>
                  У {analysis.research.length} малых рассылок всего{" "}
                  {number.format(analysis.researchTotals.delivered)} доставленное
                  сообщение и {analysis.researchTotals.clicked} открытия. Их CTR
                  нельзя сравнивать с массовыми продажными пушами, а ноль заказов
                  не означает, что опрос или интервью провалились.
                </p>
              </div>
            </article>
          </div>
        </section>

        <section className="report-section" aria-labelledby="table-title">
          <div className="section-copy">
            <h2 id="table-title">Все пуши за июль</h2>
            <p>
              Таблица показывает полный текст и точные значения. Покупатели
              считаются уникально внутри каждого пуша; в итогах месяца — уникально
              по всей выборке.
            </p>
          </div>

          <div className="report-table-wrap">
            <table className="report-table">
              <thead>
                <tr>
                  <th>Пуш</th>
                  <th>Отправка</th>
                  <th>Открытие</th>
                  <th>Покупка</th>
                  <th>Конверсия</th>
                  <th>Выручка</th>
                </tr>
              </thead>
              <tbody>
                {data.campaigns.map((campaign) => (
                  <tr key={campaign.id}>
                    <td>
                      <div className="message-cell">
                        <span
                          className={`message-type is-${campaign.type}`}
                        >
                          {campaign.type === "commercial"
                            ? "Продажи"
                            : "Исследование"}
                        </span>
                        <strong>{campaign.title}</strong>
                        {campaign.body && <p>{campaign.body}</p>}
                        <small>{date.format(new Date(campaign.sentAt))}</small>
                      </div>
                    </td>
                    <td data-label="Отправка">
                      <strong>{number.format(campaign.sent)}</strong>
                      <small>
                        {percent(campaign.delivered, campaign.sent)} доставлено
                      </small>
                    </td>
                    <td data-label="Открытие">
                      <strong>{number.format(campaign.clicked)}</strong>
                      <small>CTR {percent(campaign.clicked, campaign.delivered)}</small>
                    </td>
                    <td data-label="Покупка">
                      <strong>
                        {campaign.orders} · {campaign.buyers}
                      </strong>
                      <small>заказов · покупателей</small>
                    </td>
                    <td data-label="Конверсия">
                      <strong>{percent(campaign.orders, campaign.clicked)}</strong>
                      <small>клик → заказ</small>
                    </td>
                    <td data-label="Выручка">
                      <strong>{money.format(campaign.revenue)}</strong>
                      <small>
                        чек{" "}
                        {campaign.orders
                          ? money.format(campaign.revenue / campaign.orders)
                          : "—"}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="report-section action-section" aria-labelledby="action-title">
          <div className="section-copy">
            <h2 id="action-title">Что повторить в следующих пушах</h2>
          </div>
          <ol className="action-list">
            <li>
              Строить текст вокруг одного знакомого продукта или готового набора,
              а не широкой категории.
            </li>
            <li>
              Добавлять конкретный момент потребления: матч, ужин, перекус,
              завтрак — и сразу показывать, что положить в корзину.
            </li>
            <li>
              Проверить вывод A/B-тестом на одной аудитории и в одно время:
              «категория» против «конкретный набор + повод».
            </li>
          </ol>
        </section>

        <section className="report-section report-caveats" aria-labelledby="caveats-title">
          <div>
            <h2 id="caveats-title">Что еще важно проверить</h2>
            <p>
              Повторяются ли лидеры на сопоставимых сегментах, влияет ли время
              отправки и какая доля покупателей совершает повторный заказ.
            </p>
          </div>
          <div>
            <strong>Ограничения</strong>
            <p>
              Июль еще не завершен. Это наблюдательная атрибуция, а не
              инкрементальный эффект. Один заказ после июльского пуша был оформлен
              в другом проекте и исключен из основных итогов этой страницы.
            </p>
          </div>
        </section>

        <footer className="report-footer">
          <span>
            Supabase · снимок {dateTime.format(new Date(data.generatedAt))}
          </span>
          <Link href="/">
            Вернуться в общий дашборд
            <ArrowIcon />
          </Link>
        </footer>
      </article>
    </main>
  );
}
