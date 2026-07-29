begin;

create table if not exists public.push_manual_overrides (
  id bigint generated always as identity primary key,
  source_kind text not null,
  campaign_id bigint references public.push_campaigns(id)
    on update cascade on delete cascade,
  scenario_mailing_id bigint references public.push_scenario_mailings(id)
    on update cascade on delete cascade,
  project_id text references public.push_projects(id)
    on update cascade on delete restrict,
  name text,
  title text,
  body text,
  application_names text[],
  notes text,
  is_hidden boolean,
  changed_by text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_manual_overrides_campaign_unique unique (campaign_id),
  constraint push_manual_overrides_scenario_mailing_unique
    unique (scenario_mailing_id),
  constraint push_manual_overrides_source_check
    check (
      (
        source_kind = 'mass'
        and campaign_id is not null
        and scenario_mailing_id is null
      )
      or (
        source_kind = 'trigger'
        and campaign_id is null
        and scenario_mailing_id is not null
      )
    ),
  constraint push_manual_overrides_name_length_check
    check (name is null or char_length(name) <= 300),
  constraint push_manual_overrides_title_length_check
    check (title is null or char_length(title) <= 500),
  constraint push_manual_overrides_body_length_check
    check (body is null or char_length(body) <= 4000),
  constraint push_manual_overrides_notes_length_check
    check (notes is null or char_length(notes) <= 2000),
  constraint push_manual_overrides_changed_by_check
    check (
      btrim(changed_by) <> ''
      and char_length(changed_by) <= 200
    ),
  constraint push_manual_overrides_applications_check
    check (
      application_names is null
      or (
        cardinality(application_names) <= 20
        and array_position(application_names, null) is null
      )
    )
);

create index if not exists push_manual_overrides_project_idx
  on public.push_manual_overrides (project_id)
  where project_id is not null;

create index if not exists push_manual_overrides_updated_at_idx
  on public.push_manual_overrides (updated_at desc);

create table if not exists public.push_manual_override_history (
  id bigint generated always as identity primary key,
  override_id bigint references public.push_manual_overrides(id)
    on update cascade on delete set null,
  source_kind text not null,
  campaign_id bigint,
  scenario_mailing_id bigint,
  action text not null,
  snapshot jsonb not null,
  changed_by text not null,
  changed_at timestamptz not null default now(),
  constraint push_manual_override_history_source_kind_check
    check (source_kind in ('mass', 'trigger')),
  constraint push_manual_override_history_action_check
    check (action in ('insert', 'update', 'delete'))
);

create index if not exists push_manual_override_history_campaign_idx
  on public.push_manual_override_history (campaign_id, changed_at desc)
  where campaign_id is not null;

create index if not exists push_manual_override_history_scenario_idx
  on public.push_manual_override_history (
    scenario_mailing_id,
    changed_at desc
  )
  where scenario_mailing_id is not null;

create schema if not exists private;
revoke all on schema private from public;

create or replace function private.set_push_manual_override_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function private.log_push_manual_override_change()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
  record_value public.push_manual_overrides;
begin
  record_value := case when tg_op = 'DELETE' then old else new end;

  insert into public.push_manual_override_history (
    override_id,
    source_kind,
    campaign_id,
    scenario_mailing_id,
    action,
    snapshot,
    changed_by
  )
  values (
    case when tg_op = 'DELETE' then null else record_value.id end,
    record_value.source_kind,
    record_value.campaign_id,
    record_value.scenario_mailing_id,
    lower(tg_op),
    to_jsonb(record_value),
    record_value.changed_by
  );

  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

drop trigger if exists set_push_manual_override_updated_at
  on public.push_manual_overrides;
create trigger set_push_manual_override_updated_at
before update on public.push_manual_overrides
for each row
execute function private.set_push_manual_override_updated_at();

drop trigger if exists log_push_manual_override_change
  on public.push_manual_overrides;
create trigger log_push_manual_override_change
after insert or update or delete on public.push_manual_overrides
for each row
execute function private.log_push_manual_override_change();

alter table public.push_manual_overrides enable row level security;
alter table public.push_manual_override_history enable row level security;

revoke all on table
  public.push_manual_overrides,
  public.push_manual_override_history
from anon, authenticated;

grant select, insert, update, delete on table
  public.push_manual_overrides,
  public.push_manual_override_history
to service_role;

grant usage, select on sequence
  public.push_manual_overrides_id_seq,
  public.push_manual_override_history_id_seq
to service_role;

revoke all on function
  private.set_push_manual_override_updated_at(),
  private.log_push_manual_override_change()
from public, anon, authenticated;

grant usage on schema private to service_role;
grant execute on function
  private.set_push_manual_override_updated_at(),
  private.log_push_manual_override_change()
to service_role;

comment on table public.push_manual_overrides is
  'Sparse employee overrides for mass and trigger push metadata. Null fields continue to inherit synchronized Mindbox values.';
comment on table public.push_manual_override_history is
  'Immutable audit trail of employee-created push metadata overrides.';
comment on column public.push_manual_overrides.is_hidden is
  'When true, the push is omitted from analytical dashboards but remains available in the editor.';

commit;
