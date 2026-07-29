import { NextResponse } from "next/server";

import {
  applyPushOverride,
  mapOverrides,
  PUSH_OVERRIDES_SELECT,
  type PushManualOverrideRow,
} from "@/lib/push-overrides";
import {
  adminAccessConfigured,
  isAdminRequest,
} from "@/lib/admin-auth";
import { pgMetaQuery, supabaseRows } from "@/lib/supabase-server";

type ProjectRow = {
  id: string;
  name: string;
  short_name: string;
};

type CampaignRow = {
  id: number;
  campaign_key: string;
  project_id: string;
  project_assignment_source: string;
  project_assignment_reason: string | null;
  name: string;
  title: string;
  body: string;
  application_names: string[];
  sent_at: string;
  generated_at: string;
};

type ScenarioRow = {
  id: number;
  name: string;
};

type MailingRow = {
  id: number;
  scenario_id: number;
  project_id: string;
  project_assignment_source: string;
  project_assignment_reason: string | null;
  message_key: string;
  name: string;
  title: string;
  body: string;
  application_names: string[];
  first_activity_at: string | null;
  last_activity_at: string | null;
  generated_at: string;
};

type ManualChanges = {
  projectId: string | null;
  name: string | null;
  title: string | null;
  body: string | null;
  applicationNames: string[] | null;
  notes: string | null;
  isHidden: boolean | null;
};

type SavePayload = {
  sourceKind: "mass" | "trigger";
  sourceId: number;
  changedBy: string;
  changes: ManualChanges;
};

export const dynamic = "force-dynamic";

function unauthorized(request: Request) {
  return NextResponse.json(
    {
      error: adminAccessConfigured(request)
        ? "Неверный ключ редактора"
        : "Ключ редактора не настроен на сервере",
    },
    { status: adminAccessConfigured(request) ? 401 : 503 },
  );
}

function cleanText(
  value: unknown,
  maxLength: number,
  field: string,
) {
  if (value === null) return null;
  if (typeof value !== "string" || value.length > maxLength) {
    throw new Error(`Некорректное поле ${field}`);
  }
  return value;
}

function parsePayload(value: unknown): SavePayload {
  if (!value || typeof value !== "object") {
    throw new Error("Некорректный запрос");
  }
  const source = value as Record<string, unknown>;
  const sourceKind = source.sourceKind;
  const sourceId = Number(source.sourceId);
  const changedBy = cleanText(source.changedBy, 200, "changedBy");
  const rawChanges = source.changes;

  if (
    (sourceKind !== "mass" && sourceKind !== "trigger") ||
    !Number.isInteger(sourceId) ||
    sourceId <= 0 ||
    !changedBy?.trim() ||
    !rawChanges ||
    typeof rawChanges !== "object"
  ) {
    throw new Error("Не заполнены обязательные поля");
  }

  const changes = rawChanges as Record<string, unknown>;
  const rawApplications = changes.applicationNames;
  let applicationNames: string[] | null = null;
  if (rawApplications !== null) {
    if (
      !Array.isArray(rawApplications) ||
      rawApplications.length > 20 ||
      rawApplications.some(
        (item) => typeof item !== "string" || item.length > 200,
      )
    ) {
      throw new Error("Некорректный список приложений");
    }
    applicationNames = [
      ...new Set(
        rawApplications
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    ];
  }

  if (
    changes.projectId !== null &&
    typeof changes.projectId !== "string"
  ) {
    throw new Error("Некорректный проект");
  }
  if (
    changes.isHidden !== null &&
    typeof changes.isHidden !== "boolean"
  ) {
    throw new Error("Некорректная видимость");
  }

  return {
    sourceKind,
    sourceId,
    changedBy: changedBy.trim(),
    changes: {
      projectId:
        typeof changes.projectId === "string"
          ? changes.projectId
          : null,
      name: cleanText(changes.name, 300, "name"),
      title: cleanText(changes.title, 500, "title"),
      body: cleanText(changes.body, 4000, "body"),
      applicationNames,
      notes: cleanText(changes.notes, 2000, "notes"),
      isHidden:
        typeof changes.isHidden === "boolean"
          ? changes.isHidden
          : null,
    },
  };
}

function encodedJson(value: unknown) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64");
}

async function loadEditorData() {
  const [projects, campaigns, scenarios, mailings, overrides] =
    await Promise.all([
      supabaseRows<ProjectRow>("push_projects", {
        select: "id,name,short_name",
        is_active: "eq.true",
        order: "sort_order.asc",
      }),
      supabaseRows<CampaignRow>("push_campaigns", {
        select:
          "id,campaign_key,project_id,project_assignment_source,project_assignment_reason,name,title,body,application_names,sent_at,generated_at",
        order: "sent_at.desc",
      }),
      supabaseRows<ScenarioRow>("push_scenarios", {
        select: "id,name",
        is_active: "eq.true",
      }),
      supabaseRows<MailingRow>("push_scenario_mailings", {
        select:
          "id,scenario_id,project_id,project_assignment_source,project_assignment_reason,message_key,name,title,body,application_names,first_activity_at,last_activity_at,generated_at",
        mailing_type: "eq.trigger",
        is_test: "eq.false",
        order: "last_activity_at.desc",
      }),
      pgMetaQuery<PushManualOverrideRow>(PUSH_OVERRIDES_SELECT),
    ]);

  const campaignOverrides = mapOverrides(overrides, "mass");
  const mailingOverrides = mapOverrides(overrides, "trigger");
  const scenarioById = new Map(
    scenarios.map((scenario) => [scenario.id, scenario]),
  );

  const massPushes = campaigns.map((campaign) => {
    const override = campaignOverrides.get(campaign.id) ?? null;
    const effective = applyPushOverride(campaign, override ?? undefined);
    return {
      sourceKind: "mass" as const,
      sourceId: campaign.id,
      sourceKey: campaign.campaign_key,
      sourceContext: "Массовая рассылка",
      sourceDate: campaign.sent_at,
      assignmentSource: campaign.project_assignment_source,
      assignmentReason: campaign.project_assignment_reason,
      original: {
        projectId: campaign.project_id,
        name: campaign.name,
        title: campaign.title,
        body: campaign.body,
        applicationNames: campaign.application_names,
      },
      effective: {
        projectId: effective.project_id,
        name: effective.name,
        title: effective.title,
        body: effective.body,
        applicationNames: effective.application_names,
        isHidden: effective.isHidden,
      },
      override,
    };
  });

  const triggerPushes = mailings.map((mailing) => {
    const override = mailingOverrides.get(mailing.id) ?? null;
    const effective = applyPushOverride(mailing, override ?? undefined);
    return {
      sourceKind: "trigger" as const,
      sourceId: mailing.id,
      sourceKey: mailing.message_key,
      sourceContext:
        scenarioById.get(mailing.scenario_id)?.name ??
        "Trigger-сценарий",
      sourceDate:
        mailing.last_activity_at ?? mailing.first_activity_at,
      assignmentSource: mailing.project_assignment_source,
      assignmentReason: mailing.project_assignment_reason,
      original: {
        projectId: mailing.project_id,
        name: mailing.name,
        title: mailing.title,
        body: mailing.body,
        applicationNames: mailing.application_names,
      },
      effective: {
        projectId: effective.project_id,
        name: effective.name,
        title: effective.title,
        body: effective.body,
        applicationNames: effective.application_names,
        isHidden: effective.isHidden,
      },
      override,
    };
  });

  const pushes = [...massPushes, ...triggerPushes].sort(
    (left, right) =>
      new Date(right.sourceDate ?? 0).getTime() -
      new Date(left.sourceDate ?? 0).getTime(),
  );

  return {
    projects: projects.map((project) => ({
      id: project.id,
      name: project.name,
      shortName: project.short_name,
    })),
    applicationOptions: [
      ...new Set(
        pushes.flatMap((push) => [
          ...push.original.applicationNames,
          ...push.effective.applicationNames,
        ]),
      ),
    ].sort((left, right) => left.localeCompare(right, "ru")),
    pushes,
  };
}

export async function GET(request: Request) {
  if (!isAdminRequest(request)) return unauthorized(request);

  try {
    return NextResponse.json(await loadEditorData(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error("Push editor load failed", error);
    return NextResponse.json(
      { error: "Не удалось загрузить редактор из Supabase" },
      { status: 502 },
    );
  }
}

export async function PATCH(request: Request) {
  if (!isAdminRequest(request)) return unauthorized(request);

  try {
    const payload = parsePayload(await request.json());
    const encoded = encodedJson(payload);
    const sourceColumn =
      payload.sourceKind === "mass"
        ? "campaign_id"
        : "scenario_mailing_id";
    const otherSourceColumn =
      payload.sourceKind === "mass"
        ? "scenario_mailing_id"
        : "campaign_id";
    const sourceTable =
      payload.sourceKind === "mass"
        ? "public.push_campaigns"
        : "public.push_scenario_mailings";

    const rows = await pgMetaQuery<{ id: number }>(`
      with payload as (
        select convert_from(
          decode('${encoded}', 'base64'),
          'utf8'
        )::jsonb as doc
      )
      insert into public.push_manual_overrides (
        source_kind,
        ${sourceColumn},
        ${otherSourceColumn},
        project_id,
        name,
        title,
        body,
        application_names,
        notes,
        is_hidden,
        changed_by
      )
      select
        payload.doc->>'sourceKind',
        (payload.doc->>'sourceId')::bigint,
        null,
        payload.doc#>>'{changes,projectId}',
        payload.doc#>>'{changes,name}',
        payload.doc#>>'{changes,title}',
        payload.doc#>>'{changes,body}',
        case
          when payload.doc#>'{changes,applicationNames}' = 'null'::jsonb
            then null
          else (
            select coalesce(array_agg(item.value order by item.ordinality), '{}')
            from jsonb_array_elements_text(
              payload.doc#>'{changes,applicationNames}'
            ) with ordinality as item(value, ordinality)
          )
        end,
        payload.doc#>>'{changes,notes}',
        (payload.doc#>>'{changes,isHidden}')::boolean,
        payload.doc->>'changedBy'
      from payload
      where exists (
        select 1
        from ${sourceTable} as source
        where source.id = (payload.doc->>'sourceId')::bigint
      )
      on conflict (${sourceColumn}) do update
      set
        project_id = excluded.project_id,
        name = excluded.name,
        title = excluded.title,
        body = excluded.body,
        application_names = excluded.application_names,
        notes = excluded.notes,
        is_hidden = excluded.is_hidden,
        changed_by = excluded.changed_by
      returning id;
    `);

    if (!rows.length) {
      return NextResponse.json(
        { error: "Пуш не найден" },
        { status: 404 },
      );
    }

    return NextResponse.json(await loadEditorData());
  } catch (error) {
    console.error("Push editor save failed", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Не удалось сохранить правки",
      },
      { status: 400 },
    );
  }
}

export async function DELETE(request: Request) {
  if (!isAdminRequest(request)) return unauthorized(request);

  try {
    const payload = parsePayload(await request.json());
    const encoded = encodedJson(payload);
    const sourceColumn =
      payload.sourceKind === "mass"
        ? "campaign_id"
        : "scenario_mailing_id";

    await pgMetaQuery<{ id: number }>(`
      with payload as (
        select convert_from(
          decode('${encoded}', 'base64'),
          'utf8'
        )::jsonb as doc
      ),
      marked as (
        update public.push_manual_overrides as manual_override
        set changed_by = payload.doc->>'changedBy'
        from payload
        where manual_override.${sourceColumn} =
          (payload.doc->>'sourceId')::bigint
        returning manual_override.id
      )
      delete from public.push_manual_overrides as manual_override
      using marked
      where manual_override.id = marked.id
      returning manual_override.id;
    `);

    return NextResponse.json(await loadEditorData());
  } catch (error) {
    console.error("Push editor reset failed", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Не удалось сбросить правки",
      },
      { status: 400 },
    );
  }
}
