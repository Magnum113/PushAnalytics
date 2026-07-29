export type PushManualOverrideRow = {
  id: number;
  source_kind: "mass" | "trigger";
  campaign_id: number | null;
  scenario_mailing_id: number | null;
  project_id: string | null;
  name: string | null;
  title: string | null;
  body: string | null;
  application_names: string[] | null;
  notes: string | null;
  is_hidden: boolean | null;
  changed_by: string;
  created_at: string;
  updated_at: string;
};

type EditablePush = {
  id: number;
  project_id: string;
  name: string;
  title: string;
  body: string;
  application_names: string[];
};

export type EffectivePush<T extends EditablePush> = T & {
  manualOverride: PushManualOverrideRow | null;
  isHidden: boolean;
};

export function mapOverrides(
  overrides: PushManualOverrideRow[],
  sourceKind: "mass" | "trigger",
) {
  return new Map(
    overrides
      .filter((override) => override.source_kind === sourceKind)
      .map((override) => [
        sourceKind === "mass"
          ? override.campaign_id
          : override.scenario_mailing_id,
        override,
      ]),
  );
}

export function applyPushOverride<T extends EditablePush>(
  push: T,
  override: PushManualOverrideRow | undefined,
): EffectivePush<T> {
  return {
    ...push,
    project_id: override?.project_id ?? push.project_id,
    name: override?.name ?? push.name,
    title: override?.title ?? push.title,
    body: override?.body ?? push.body,
    application_names:
      override?.application_names ?? push.application_names,
    manualOverride: override ?? null,
    isHidden: override?.is_hidden ?? false,
  };
}

export const PUSH_OVERRIDES_SELECT = `
  select
    id,
    source_kind,
    campaign_id,
    scenario_mailing_id,
    project_id,
    name,
    title,
    body,
    application_names,
    notes,
    is_hidden,
    changed_by,
    created_at,
    updated_at
  from public.push_manual_overrides
`;
