"use client";

import Link from "next/link";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type Project = {
  id: string;
  name: string;
  shortName: string;
};

type PushValues = {
  projectId: string;
  name: string;
  title: string;
  body: string;
  applicationNames: string[];
};

type ManualOverride = {
  id: number;
  project_id: string | null;
  name: string | null;
  title: string | null;
  body: string | null;
  application_names: string[] | null;
  notes: string | null;
  is_hidden: boolean | null;
  changed_by: string;
  updated_at: string;
};

type EditablePush = {
  sourceKind: "mass" | "trigger";
  sourceId: number;
  sourceKey: string;
  sourceContext: string;
  sourceDate: string | null;
  assignmentSource: string;
  assignmentReason: string | null;
  original: PushValues;
  effective: PushValues & { isHidden: boolean };
  override: ManualOverride | null;
};

type EditorData = {
  projects: Project[];
  applicationOptions: string[];
  pushes: EditablePush[];
};

type Draft = PushValues & {
  applicationsText: string;
  notes: string;
  isHidden: boolean;
};

const PAGE_SIZE = 30;
const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});

function draftFrom(push: EditablePush): Draft {
  return {
    ...push.effective,
    applicationsText: push.effective.applicationNames.join(", "),
    notes: push.override?.notes ?? "",
    isHidden: push.effective.isHidden,
  };
}

function applicationsFrom(value: string) {
  return [
    ...new Set(
      value
        .split(/[,;\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

function sameApplications(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    left.every((item, index) => item === right[index])
  );
}

function inherited<T>(value: T, original: T) {
  return Object.is(value, original) ? null : value;
}

function displayName(push: EditablePush) {
  return (
    push.effective.name ||
    push.effective.title ||
    push.sourceContext ||
    "Пуш без названия"
  );
}

export default function PushEditorPage() {
  const [adminKey, setAdminKey] = useState("");
  const [editorName, setEditorName] = useState("");
  const [data, setData] = useState<EditorData | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<
    "all" | "mass" | "trigger"
  >("all");
  const [projectFilter, setProjectFilter] = useState("all");
  const [editFilter, setEditFilter] = useState<
    "all" | "edited" | "hidden"
  >("all");
  const [page, setPage] = useState(1);

  const load = useCallback(async (
    key: string,
    preferredSelection = "",
  ) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/admin/pushes", {
        cache: "no-store",
        headers: { "x-push-admin-key": key },
      });
      const payload = (await response.json()) as
        | EditorData
        | { error?: string };
      if (!response.ok || !("pushes" in payload)) {
        throw new Error(
          "error" in payload
            ? payload.error
            : "Не удалось открыть редактор",
        );
      }
      setData(payload);
      sessionStorage.setItem("push-analytics-admin-key", key);
      const selectedPush =
        payload.pushes.find(
          (push) =>
            `${push.sourceKind}:${push.sourceId}` ===
            preferredSelection,
        ) ?? payload.pushes[0];
      setSelectedKey(
        selectedPush
          ? `${selectedPush.sourceKind}:${selectedPush.sourceId}`
          : "",
      );
      setDraft(selectedPush ? draftFrom(selectedPush) : null);
    } catch (loadError) {
      setData(null);
      sessionStorage.removeItem("push-analytics-admin-key");
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Не удалось открыть редактор",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const storedKey =
      sessionStorage.getItem("push-analytics-admin-key") ?? "";
    const storedName =
      sessionStorage.getItem("push-analytics-editor-name") ?? "";
    queueMicrotask(() => {
      setAdminKey(storedKey);
      setEditorName(storedName);
      const localDevelopment =
        process.env.NODE_ENV === "development" &&
        (window.location.hostname === "localhost" ||
          window.location.hostname === "127.0.0.1");
      if (storedKey || localDevelopment) void load(storedKey);
    });
  }, [load]);

  const filteredPushes = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase("ru");
    return data.pushes.filter((push) => {
      if (
        typeFilter !== "all" &&
        push.sourceKind !== typeFilter
      ) {
        return false;
      }
      if (
        projectFilter !== "all" &&
        push.effective.projectId !== projectFilter
      ) {
        return false;
      }
      if (editFilter === "edited" && !push.override) return false;
      if (editFilter === "hidden" && !push.effective.isHidden) {
        return false;
      }
      if (!normalized) return true;
      return [
        push.effective.name,
        push.effective.title,
        push.effective.body,
        push.sourceContext,
      ]
        .join(" ")
        .toLocaleLowerCase("ru")
        .includes(normalized);
    });
  }, [
    data,
    editFilter,
    projectFilter,
    query,
    typeFilter,
  ]);

  const pageCount = Math.max(
    1,
    Math.ceil(filteredPushes.length / PAGE_SIZE),
  );
  const safePage = Math.min(page, pageCount);
  const pagePushes = filteredPushes.slice(
    (safePage - 1) * PAGE_SIZE,
    safePage * PAGE_SIZE,
  );
  const selected =
    data?.pushes.find(
      (push) =>
        `${push.sourceKind}:${push.sourceId}` === selectedKey,
    ) ?? null;

  const currentApplications = draft
    ? applicationsFrom(draft.applicationsText)
    : [];
  const isDirty = Boolean(
    selected &&
      draft &&
      (draft.projectId !== selected.effective.projectId ||
        draft.name !== selected.effective.name ||
        draft.title !== selected.effective.title ||
        draft.body !== selected.effective.body ||
        !sameApplications(
          currentApplications,
          selected.effective.applicationNames,
        ) ||
        draft.notes !== (selected.override?.notes ?? "") ||
        draft.isHidden !== selected.effective.isHidden),
  );

  function selectPush(push: EditablePush) {
    if (
      isDirty &&
      !window.confirm(
        "Есть несохранённые изменения. Перейти к другому пушу?",
      )
    ) {
      return;
    }
    setSelectedKey(`${push.sourceKind}:${push.sourceId}`);
    setDraft(draftFrom(push));
    setNotice("");
  }

  async function unlock(event: FormEvent) {
    event.preventDefault();
    if (!adminKey.trim()) {
      setError("Введите ключ редактора");
      return;
    }
    await load(adminKey.trim(), selectedKey);
  }

  async function mutate(
    method: "PATCH" | "DELETE",
    changes: Record<string, unknown>,
  ) {
    if (!selected || !draft) return;
    if (!editorName.trim()) {
      setError("Укажите имя сотрудника перед сохранением");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/admin/pushes", {
        method,
        headers: {
          "Content-Type": "application/json",
          "x-push-admin-key": adminKey,
        },
        body: JSON.stringify({
          sourceKind: selected.sourceKind,
          sourceId: selected.sourceId,
          changedBy: editorName.trim(),
          changes,
        }),
      });
      const payload = (await response.json()) as
        | EditorData
        | { error?: string };
      if (!response.ok || !("pushes" in payload)) {
        throw new Error(
          "error" in payload
            ? payload.error
            : "Не удалось сохранить изменения",
        );
      }
      sessionStorage.setItem(
        "push-analytics-editor-name",
        editorName.trim(),
      );
      setData(payload);
      const refreshed = payload.pushes.find(
        (push) =>
          push.sourceKind === selected.sourceKind &&
          push.sourceId === selected.sourceId,
      );
      if (refreshed) setDraft(draftFrom(refreshed));
      setNotice(
        method === "DELETE"
          ? "Ручные правки сброшены"
          : "Изменения сохранены",
      );
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Не удалось сохранить изменения",
      );
    } finally {
      setSaving(false);
    }
  }

  async function save() {
    if (!selected || !draft) return;
    const applications = applicationsFrom(
      draft.applicationsText,
    );
    await mutate("PATCH", {
      projectId: inherited(
        draft.projectId,
        selected.original.projectId,
      ),
      name: inherited(draft.name, selected.original.name),
      title: inherited(draft.title, selected.original.title),
      body: inherited(draft.body, selected.original.body),
      applicationNames: sameApplications(
        applications,
        selected.original.applicationNames,
      )
        ? null
        : applications,
      notes: draft.notes.trim() || null,
      isHidden: draft.isHidden ? true : null,
    });
  }

  async function reset() {
    if (
      !selected?.override ||
      !window.confirm(
        "Сбросить все ручные правки этого пуша и снова использовать значения из Mindbox?",
      )
    ) {
      return;
    }
    await mutate("DELETE", {
      projectId: null,
      name: null,
      title: null,
      body: null,
      applicationNames: null,
      notes: null,
      isHidden: null,
    });
  }

  if (!data) {
    return (
      <main className="push-editor-shell">
        <section className="editor-content">
          <header className="editor-topbar">
            <div>
              <h1>PUSH ANALYTICS</h1>
              <p>Редактор пушей</p>
            </div>
            <nav className="editor-nav" aria-label="Разделы">
              <Link href="/">Дашборд</Link>
              <Link href="/triggers">Trigger-пуши</Link>
              <span aria-current="page">Редактор</span>
            </nav>
          </header>
          <section className="editor-unlock">
            <div>
              <span className="editor-eyebrow">Служебный доступ</span>
              <h2>Разблокировать редактор</h2>
              <p>
                Ручные правки сохраняются отдельно от синхронизации
                Mindbox и применяются в обоих дашбордах.
              </p>
            </div>
            <form onSubmit={unlock}>
              <label>
                <span>Ключ редактора</span>
                <input
                  autoComplete="current-password"
                  onChange={(event) =>
                    setAdminKey(event.target.value)
                  }
                  placeholder="Введите служебный ключ"
                  type="password"
                  value={adminKey}
                />
              </label>
              <button disabled={loading} type="submit">
                {loading ? "Проверяем…" : "Открыть редактор"}
              </button>
              {error ? (
                <p className="editor-form-error" role="alert">
                  {error}
                </p>
              ) : null}
            </form>
          </section>
        </section>
      </main>
    );
  }

  return (
    <main className="push-editor-shell">
      <section className="editor-content">
        <header className="editor-topbar">
          <div>
            <h1>PUSH ANALYTICS</h1>
            <p>Редактор пушей</p>
          </div>
          <nav className="editor-nav" aria-label="Разделы">
            <Link href="/">Дашборд</Link>
            <Link href="/triggers">Trigger-пуши</Link>
            <span aria-current="page">Редактор</span>
          </nav>
          <div className="editor-protection">
            <span aria-hidden="true">✓</span>
            <div>
              <strong>Правки защищены</strong>
              <small>Синхронизация их не перезапишет</small>
            </div>
          </div>
        </header>

        <section
          className="editor-toolbar"
          aria-label="Фильтры пушей"
        >
          <label className="editor-search">
            <span>Поиск</span>
            <input
              onChange={(event) => {
                setPage(1);
                setQuery(event.target.value);
              }}
              placeholder="Название, заголовок или текст"
              type="search"
              value={query}
            />
          </label>
          <label>
            <span>Тип</span>
            <select
              onChange={(event) => {
                setPage(1);
                setTypeFilter(
                  event.target.value as
                    | "all"
                    | "mass"
                    | "trigger",
                );
              }}
              value={typeFilter}
            >
              <option value="all">Все пуши</option>
              <option value="mass">Массовые</option>
              <option value="trigger">Trigger</option>
            </select>
          </label>
          <label>
            <span>Проект</span>
            <select
              onChange={(event) => {
                setPage(1);
                setProjectFilter(event.target.value);
              }}
              value={projectFilter}
            >
              <option value="all">Все проекты</option>
              {data.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Состояние</span>
            <select
              onChange={(event) => {
                setPage(1);
                setEditFilter(
                  event.target.value as
                    | "all"
                    | "edited"
                    | "hidden",
                );
              }}
              value={editFilter}
            >
              <option value="all">Все</option>
              <option value="edited">С ручными правками</option>
              <option value="hidden">Скрытые</option>
            </select>
          </label>
          <div className="editor-result-count">
            <strong>{filteredPushes.length}</strong>
            <span>пушей найдено</span>
          </div>
        </section>

        <section className="editor-workspace">
          <div className="editor-list-panel">
            <div className="editor-table-wrap">
              <table className="editor-table">
                <thead>
                  <tr>
                    <th>Пуш</th>
                    <th>Тип</th>
                    <th>Проект</th>
                    <th>Дата</th>
                    <th>Правки</th>
                  </tr>
                </thead>
                <tbody>
                  {pagePushes.map((push) => {
                    const key = `${push.sourceKind}:${push.sourceId}`;
                    const project = data.projects.find(
                      (item) =>
                        item.id === push.effective.projectId,
                    );
                    return (
                      <tr
                        className={
                          key === selectedKey ? "selected-row" : ""
                        }
                        key={key}
                        onClick={() => selectPush(push)}
                      >
                        <td>
                          <button
                            className="editor-push-name"
                            onClick={() => selectPush(push)}
                            type="button"
                          >
                            <strong>{displayName(push)}</strong>
                            <span>
                              {push.effective.body ||
                                push.effective.title ||
                                "Текст пока не добавлен"}
                            </span>
                          </button>
                        </td>
                        <td>
                          <span
                            className={`editor-type-tag ${push.sourceKind}`}
                          >
                            {push.sourceKind === "mass"
                              ? "Массовый"
                              : "Trigger"}
                          </span>
                        </td>
                        <td>
                          <span className="editor-project-tag">
                            {project?.shortName ??
                              push.effective.projectId}
                          </span>
                        </td>
                        <td>
                          {push.sourceDate
                            ? dateTime.format(
                                new Date(push.sourceDate),
                              )
                            : "—"}
                        </td>
                        <td>
                          {push.override ? (
                            <span className="editor-edited-tag">
                              Изменён
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!pagePushes.length ? (
                <div className="editor-empty">
                  <strong>Пуши не найдены</strong>
                  <span>Измените фильтры или поисковый запрос.</span>
                </div>
              ) : null}
            </div>
            {pageCount > 1 ? (
              <div className="editor-pagination">
                <span>
                  Страница {safePage} из {pageCount}
                </span>
                <div>
                  <button
                    disabled={safePage === 1}
                    onClick={() =>
                      setPage((value) => Math.max(1, value - 1))
                    }
                    type="button"
                  >
                    Назад
                  </button>
                  <button
                    disabled={safePage === pageCount}
                    onClick={() =>
                      setPage((value) =>
                        Math.min(pageCount, value + 1),
                      )
                    }
                    type="button"
                  >
                    Далее
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <aside className="editor-form-panel">
            {selected && draft ? (
              <>
                <div className="editor-form-heading">
                  <div>
                    <span className="editor-eyebrow">
                      Редактирование
                    </span>
                    <h2>{displayName(selected)}</h2>
                    <p>
                      Поля без ручных изменений продолжат
                      обновляться из Mindbox.
                    </p>
                  </div>
                  <div className="editor-source-tags">
                    <span className={selected.sourceKind}>
                      {selected.sourceKind === "mass"
                        ? "Массовый"
                        : "Trigger"}
                    </span>
                    <span>Mindbox</span>
                  </div>
                </div>

                <label className="editor-field">
                  <span>
                    Рабочее название
                    <FieldSource
                      overridden={
                        draft.name !== selected.original.name
                      }
                      onReset={() =>
                        setDraft((value) =>
                          value
                            ? {
                                ...value,
                                name: selected.original.name,
                              }
                            : value,
                        )
                      }
                    />
                  </span>
                  <input
                    maxLength={300}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        name: event.target.value,
                      })
                    }
                    value={draft.name}
                  />
                </label>

                <label className="editor-field">
                  <span>
                    Заголовок
                    <FieldSource
                      overridden={
                        draft.title !== selected.original.title
                      }
                      onReset={() =>
                        setDraft((value) =>
                          value
                            ? {
                                ...value,
                                title: selected.original.title,
                              }
                            : value,
                        )
                      }
                    />
                  </span>
                  <input
                    maxLength={500}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        title: event.target.value,
                      })
                    }
                    placeholder="Заголовок пуша"
                    value={draft.title}
                  />
                </label>

                <label className="editor-field">
                  <span>
                    Текст пуша
                    <FieldSource
                      overridden={
                        draft.body !== selected.original.body
                      }
                      onReset={() =>
                        setDraft((value) =>
                          value
                            ? {
                                ...value,
                                body: selected.original.body,
                              }
                            : value,
                        )
                      }
                    />
                  </span>
                  <textarea
                    maxLength={4000}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        body: event.target.value,
                      })
                    }
                    placeholder="Добавьте текст пуша"
                    rows={4}
                    value={draft.body}
                  />
                </label>

                <label className="editor-field">
                  <span>
                    Проект
                    <FieldSource
                      overridden={
                        draft.projectId !==
                        selected.original.projectId
                      }
                      onReset={() =>
                        setDraft((value) =>
                          value
                            ? {
                                ...value,
                                projectId:
                                  selected.original.projectId,
                              }
                            : value,
                        )
                      }
                    />
                  </span>
                  <select
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        projectId: event.target.value,
                      })
                    }
                    value={draft.projectId}
                  >
                    {data.projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="editor-field">
                  <span>
                    Приложения
                    <FieldSource
                      overridden={
                        !sameApplications(
                          currentApplications,
                          selected.original.applicationNames,
                        )
                      }
                      onReset={() =>
                        setDraft((value) =>
                          value
                            ? {
                                ...value,
                                applicationsText:
                                  selected.original.applicationNames.join(
                                    ", ",
                                  ),
                              }
                            : value,
                        )
                      }
                    />
                  </span>
                  <textarea
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        applicationsText: event.target.value,
                      })
                    }
                    placeholder="Через запятую"
                    rows={2}
                    value={draft.applicationsText}
                  />
                  {data.applicationOptions.length ? (
                    <div
                      className="editor-application-options"
                      aria-label="Известные приложения"
                    >
                      {data.applicationOptions.map((application) => {
                        const selectedApplication =
                          currentApplications.includes(application);
                        return (
                          <button
                            className={
                              selectedApplication ? "selected" : ""
                            }
                            key={application}
                            onClick={(event) => {
                              event.preventDefault();
                              const next = selectedApplication
                                ? currentApplications.filter(
                                    (item) => item !== application,
                                  )
                                : [
                                    ...currentApplications,
                                    application,
                                  ];
                              setDraft({
                                ...draft,
                                applicationsText: next.join(", "),
                              });
                            }}
                            type="button"
                          >
                            {selectedApplication ? "✓ " : "+ "}
                            {application}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                  <small>
                    Укажите названия через запятую. Новые значения
                    также допустимы.
                  </small>
                </label>

                <label className="editor-field">
                  <span>
                    Комментарий
                    <em>только для сотрудников</em>
                  </span>
                  <textarea
                    maxLength={2000}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        notes: event.target.value,
                      })
                    }
                    placeholder="Почему внесена правка"
                    rows={3}
                    value={draft.notes}
                  />
                </label>

                <label className="editor-visibility">
                  <div>
                    <strong>Скрыть из дашбордов</strong>
                    <span>
                      Пуш останется в редакторе и истории
                    </span>
                  </div>
                  <input
                    checked={draft.isHidden}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        isHidden: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />
                </label>

                <label className="editor-field editor-name-field">
                  <span>Кто вносит изменения</span>
                  <input
                    maxLength={200}
                    onChange={(event) =>
                      setEditorName(event.target.value)
                    }
                    placeholder="Имя сотрудника"
                    value={editorName}
                  />
                </label>

                {error ? (
                  <p className="editor-form-error" role="alert">
                    {error}
                  </p>
                ) : null}
                {notice ? (
                  <p className="editor-form-notice" role="status">
                    {notice}
                  </p>
                ) : null}

                <div className="editor-form-actions">
                  <button
                    className="editor-save"
                    disabled={saving || !isDirty}
                    onClick={save}
                    type="button"
                  >
                    {saving ? "Сохраняем…" : "Сохранить изменения"}
                  </button>
                  <button
                    className="editor-reset"
                    disabled={saving || !selected.override}
                    onClick={reset}
                    type="button"
                  >
                    Сбросить ручные правки
                  </button>
                </div>

                {selected.override ? (
                  <p className="editor-last-change">
                    Последнее изменение:{" "}
                    <strong>{selected.override.changed_by}</strong> ·{" "}
                    {dateTime.format(
                      new Date(selected.override.updated_at),
                    )}
                  </p>
                ) : (
                  <p className="editor-last-change">
                    Ручных изменений пока нет
                  </p>
                )}
              </>
            ) : (
              <div className="editor-empty-form">
                <strong>Выберите пуш</strong>
                <span>Его параметры появятся здесь.</span>
              </div>
            )}
          </aside>
        </section>
      </section>
    </main>
  );
}

function FieldSource({
  overridden,
  onReset,
}: {
  overridden: boolean;
  onReset: () => void;
}) {
  if (!overridden) return <em>из Mindbox</em>;
  return (
    <button
      className="editor-field-reset"
      onClick={(event) => {
        event.preventDefault();
        onReset();
      }}
      type="button"
    >
      Вернуть из Mindbox
    </button>
  );
}
