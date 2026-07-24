begin;

create table if not exists public.push_projects (
  id text primary key,
  name text not null,
  short_name text not null,
  description text not null,
  sort_order smallint not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_projects_id_format check (id ~ '^[a-z0-9-]+$')
);

create table if not exists public.push_goals (
  id text primary key,
  name text not null,
  short_name text not null,
  description text not null,
  sort_order smallint not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_goals_id_format check (id ~ '^[a-z0-9-]+$')
);

create table if not exists public.push_project_rules (
  id bigint generated always as identity primary key,
  project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  match_field text not null,
  match_value text not null,
  priority smallint not null default 100,
  notes text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_project_rules_match_field_check
    check (match_field in ('folder_internal_id', 'mailing_internal_id')),
  constraint push_project_rules_match_unique unique (match_field, match_value)
);

create index if not exists push_project_rules_project_id_idx
  on public.push_project_rules (project_id);

create index if not exists push_project_rules_lookup_idx
  on public.push_project_rules (is_active, match_field, match_value, priority);

create table if not exists public.push_campaigns (
  id bigint generated always as identity primary key,
  campaign_key text not null unique,
  project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  project_assignment_source text not null default 'rule',
  project_assignment_reason text,
  name text not null,
  title text not null default '',
  body text not null default '',
  sent_at timestamptz not null,
  attribution_status text not null,
  attribution_window_hours smallint not null default 24,
  attribution_model text not null default 'last_click',
  source text not null default 'mindbox',
  mailing_ids text[] not null default '{}',
  folder_internal_ids text[] not null default '{}',
  sent bigint not null default 0,
  delivered bigint not null default 0,
  clicked bigint not null default 0,
  not_delivered bigint not null default 0,
  platform_ios bigint not null default 0,
  platform_android bigint not null default 0,
  platform_unknown bigint not null default 0,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_campaigns_assignment_source_check
    check (project_assignment_source in ('rule', 'manual', 'fallback')),
  constraint push_campaigns_status_check
    check (attribution_status in ('collecting', 'complete')),
  constraint push_campaigns_window_check
    check (attribution_window_hours > 0 and attribution_window_hours <= 720),
  constraint push_campaigns_counts_check
    check (
      sent >= 0
      and delivered >= 0
      and clicked >= 0
      and not_delivered >= 0
      and platform_ios >= 0
      and platform_android >= 0
      and platform_unknown >= 0
    )
);

create index if not exists push_campaigns_project_sent_at_idx
  on public.push_campaigns (project_id, sent_at desc);

create index if not exists push_campaigns_sent_at_idx
  on public.push_campaigns (sent_at desc);

create table if not exists public.push_campaign_goal_metrics (
  campaign_id bigint not null references public.push_campaigns(id)
    on update cascade on delete cascade,
  goal_id text not null references public.push_goals(id)
    on update cascade on delete restrict,
  orders bigint not null default 0,
  revenue numeric(16, 2) not null default 0,
  latency_0_1h bigint not null default 0,
  latency_1_4h bigint not null default 0,
  latency_4_12h bigint not null default 0,
  latency_12_24h bigint not null default 0,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (campaign_id, goal_id),
  constraint push_campaign_goal_metrics_values_check
    check (
      orders >= 0
      and revenue >= 0
      and latency_0_1h >= 0
      and latency_1_4h >= 0
      and latency_4_12h >= 0
      and latency_12_24h >= 0
    )
);

create index if not exists push_campaign_goal_metrics_goal_id_idx
  on public.push_campaign_goal_metrics (goal_id, campaign_id);

create table if not exists public.push_sync_runs (
  id bigint generated always as identity primary key,
  source text not null default 'mindbox',
  status text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  generated_at timestamptz,
  campaigns_upserted integer not null default 0,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  constraint push_sync_runs_status_check
    check (status in ('running', 'succeeded', 'failed')),
  constraint push_sync_runs_campaigns_check
    check (campaigns_upserted >= 0)
);

create index if not exists push_sync_runs_started_at_idx
  on public.push_sync_runs (started_at desc);

insert into public.push_projects (
  id,
  name,
  short_name,
  description,
  sort_order
)
values
  (
    'blizko-app',
    'Отдельное приложение Blizko',
    'Blizko · приложение',
    'Push-рассылки отдельного приложения доставки продуктов Blizko.',
    10
  ),
  (
    '05-main',
    'Основной проект 05.ru',
    '05.ru · основной проект',
    'Push-рассылки основного приложения 05.ru, включая интернет-магазин техники.',
    20
  ),
  (
    'blizko-in-05',
    'Blizko внутри приложения 05.ru',
    'Blizko внутри 05.ru',
    'Push-рассылки сценария Blizko, встроенного в основное приложение 05.ru.',
    30
  )
on conflict (id) do update
set
  name = excluded.name,
  short_name = excluded.short_name,
  description = excluded.description,
  sort_order = excluded.sort_order,
  is_active = true,
  updated_at = now();

insert into public.push_goals (
  id,
  name,
  short_name,
  description,
  sort_order
)
values
  (
    'blizko-app',
    'Заказы Blizko (отдельное приложение)',
    'Blizko · приложение',
    'Заказы доставки продуктов из отдельного приложения Blizko.',
    10
  ),
  (
    '05-app',
    'Заказы в приложении (ИМ)',
    '05.ru · приложение',
    'Заказы техники, оформленные в основном приложении 05.ru.',
    20
  ),
  (
    'blizko-in-05',
    'Заказ в Blizko',
    'Blizko внутри 05.ru',
    'Заказы доставки продуктов Blizko через сценарий внутри 05.ru.',
    30
  ),
  (
    'all-orders',
    'Заказы',
    'Все заказы',
    'Все заказы без ограничения на продукт, приложение или точку контакта.',
    40
  )
on conflict (id) do update
set
  name = excluded.name,
  short_name = excluded.short_name,
  description = excluded.description,
  sort_order = excluded.sort_order,
  is_active = true,
  updated_at = now();

insert into public.push_project_rules (
  project_id,
  match_field,
  match_value,
  priority,
  notes
)
values (
  'blizko-in-05',
  'folder_internal_id',
  '0e07c12c-bd8a-48a1-b033-10aec22bc954',
  100,
  'Текущая папка продуктовых push Blizko. Предварительно отнесена к Blizko внутри 05.ru по brandInternalId=05ru и ссылкам blizko.05.ru; назначение нужно подтвердить в Mindbox.'
)
on conflict (match_field, match_value) do update
set
  project_id = excluded.project_id,
  priority = excluded.priority,
  notes = excluded.notes,
  is_active = true,
  updated_at = now();

alter table public.push_projects enable row level security;
alter table public.push_goals enable row level security;
alter table public.push_project_rules enable row level security;
alter table public.push_campaigns enable row level security;
alter table public.push_campaign_goal_metrics enable row level security;
alter table public.push_sync_runs enable row level security;

revoke all on table
  public.push_projects,
  public.push_goals,
  public.push_project_rules,
  public.push_campaigns,
  public.push_campaign_goal_metrics,
  public.push_sync_runs
from anon, authenticated;

grant select on table
  public.push_projects,
  public.push_goals,
  public.push_campaigns,
  public.push_campaign_goal_metrics
to anon, authenticated;

grant select on table
  public.push_project_rules,
  public.push_sync_runs
to authenticated;

grant select on table
  public.push_projects,
  public.push_goals,
  public.push_project_rules,
  public.push_campaigns,
  public.push_campaign_goal_metrics,
  public.push_sync_runs
to service_role;

grant insert, update, delete on table
  public.push_campaigns,
  public.push_campaign_goal_metrics,
  public.push_sync_runs
to service_role;

grant usage, select on sequence
  public.push_campaigns_id_seq,
  public.push_sync_runs_id_seq
to service_role;

drop policy if exists "read push projects" on public.push_projects;
create policy "read push projects"
  on public.push_projects
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push goals" on public.push_goals;
create policy "read push goals"
  on public.push_goals
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push campaigns" on public.push_campaigns;
create policy "read push campaigns"
  on public.push_campaigns
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push campaign goal metrics"
  on public.push_campaign_goal_metrics;
create policy "read push campaign goal metrics"
  on public.push_campaign_goal_metrics
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push project rules"
  on public.push_project_rules;
create policy "read push project rules"
  on public.push_project_rules
  for select
  to authenticated
  using (true);

drop policy if exists "read push sync runs"
  on public.push_sync_runs;
create policy "read push sync runs"
  on public.push_sync_runs
  for select
  to authenticated
  using (true);

comment on table public.push_projects is
  'Business dimension used to filter pushes by application or product context.';
comment on table public.push_goals is
  'Mindbox target-action dimension used independently from the push project.';
comment on table public.push_project_rules is
  'Auditable rules that assign a Mindbox folder or mailing to a push project.';
comment on table public.push_campaigns is
  'PII-free campaign metadata and current aggregate delivery/click metrics.';
comment on table public.push_campaign_goal_metrics is
  'Custom last-click attribution metrics by push campaign and Mindbox goal.';
comment on table public.push_sync_runs is
  'Operational log of Mindbox to Supabase synchronization runs.';

commit;
