begin;

create table if not exists public.push_scenarios (
  id bigint generated always as identity primary key,
  mindbox_scenario_id text not null unique,
  name text not null,
  source_entity_type text not null default 'Scenario',
  first_activity_at timestamptz,
  last_activity_at timestamptz,
  is_active boolean not null default true,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_scenarios_mindbox_id_check
    check (btrim(mindbox_scenario_id) <> ''),
  constraint push_scenarios_activity_window_check
    check (
      first_activity_at is null
      or last_activity_at is null
      or first_activity_at <= last_activity_at
    )
);

create index if not exists push_scenarios_last_activity_idx
  on public.push_scenarios (last_activity_at desc);

create table if not exists public.push_scenario_mailings (
  id bigint generated always as identity primary key,
  scenario_id bigint not null references public.push_scenarios(id)
    on update cascade on delete cascade,
  project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  message_key text not null,
  project_assignment_source text not null default 'rule',
  project_assignment_reason text,
  name text not null,
  title text not null default '',
  body text not null default '',
  mailing_type text not null default 'trigger',
  mailing_ids text[] not null default '{}',
  folder_internal_ids text[] not null default '{}',
  application_names text[] not null default '{}',
  platforms text[] not null default '{}',
  content_source text not null default 'inferred',
  first_activity_at timestamptz,
  last_activity_at timestamptz,
  mindbox_created_at timestamptz,
  mindbox_updated_at timestamptz,
  is_test boolean not null default false,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_scenario_mailings_unique
    unique (scenario_id, message_key),
  constraint push_scenario_mailings_type_check
    check (mailing_type = 'trigger'),
  constraint push_scenario_mailings_assignment_source_check
    check (project_assignment_source in ('rule', 'manual', 'fallback')),
  constraint push_scenario_mailings_content_source_check
    check (content_source in ('inferred', 'manual', 'mindbox_ui', 'app_capture')),
  constraint push_scenario_mailings_mailing_ids_check
    check (cardinality(mailing_ids) > 0),
  constraint push_scenario_mailings_platforms_check
    check (platforms <@ array['android', 'ios', 'unknown']::text[]),
  constraint push_scenario_mailings_activity_window_check
    check (
      first_activity_at is null
      or last_activity_at is null
      or first_activity_at <= last_activity_at
    )
);

create index if not exists push_scenario_mailings_scenario_id_idx
  on public.push_scenario_mailings (scenario_id);

create index if not exists push_scenario_mailings_project_activity_idx
  on public.push_scenario_mailings (
    project_id,
    is_test,
    last_activity_at desc
  );

create table if not exists public.push_scenario_daily_metrics (
  scenario_mailing_id bigint not null
    references public.push_scenario_mailings(id)
    on update cascade on delete cascade,
  metric_date date not null,
  participants bigint not null default 0,
  unique_recipients bigint not null default 0,
  sent bigint not null default 0,
  delivered_estimated bigint not null default 0,
  clicked bigint not null default 0,
  not_sent bigint not null default 0,
  not_delivered bigint not null default 0,
  not_sent_reasons jsonb not null default '{}'::jsonb,
  not_delivered_reasons jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (scenario_mailing_id, metric_date),
  constraint push_scenario_daily_metrics_values_check
    check (
      participants >= 0
      and unique_recipients >= 0
      and sent >= 0
      and delivered_estimated >= 0
      and clicked >= 0
      and not_sent >= 0
      and not_delivered >= 0
      and delivered_estimated <= sent
      and not_delivered <= sent
      and clicked <= sent
      and unique_recipients <= participants
    )
);

create index if not exists push_scenario_daily_metrics_date_idx
  on public.push_scenario_daily_metrics (metric_date desc, scenario_mailing_id);

create table if not exists public.push_click_touchpoints (
  id bigint generated always as identity primary key,
  touchpoint_key text not null unique,
  source_kind text not null,
  campaign_id bigint references public.push_campaigns(id)
    on update cascade on delete cascade,
  scenario_mailing_id bigint references public.push_scenario_mailings(id)
    on update cascade on delete cascade,
  project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  mailing_internal_id text not null,
  message_instance_key text not null,
  buyer_key text not null,
  clicked_at timestamptz not null,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_click_touchpoints_source_check
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
  constraint push_click_touchpoints_touchpoint_key_check
    check (touchpoint_key ~ '^[a-f0-9]{64}$'),
  constraint push_click_touchpoints_message_key_check
    check (message_instance_key ~ '^[a-f0-9]{64}$'),
  constraint push_click_touchpoints_buyer_key_check
    check (buyer_key ~ '^[a-f0-9]{64}$')
);

create index if not exists push_click_touchpoints_buyer_clicked_idx
  on public.push_click_touchpoints (buyer_key, clicked_at desc);

create index if not exists push_click_touchpoints_trigger_activity_idx
  on public.push_click_touchpoints (
    scenario_mailing_id,
    clicked_at desc
  )
  where source_kind = 'trigger';

create table if not exists public.push_trigger_attributed_orders (
  id bigint generated always as identity primary key,
  scenario_mailing_id bigint not null
    references public.push_scenario_mailings(id)
    on update cascade on delete cascade,
  touchpoint_id bigint not null references public.push_click_touchpoints(id)
    on update cascade on delete cascade,
  goal_id text not null references public.push_goals(id)
    on update cascade on delete restrict,
  order_project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  order_key text not null,
  buyer_key text not null,
  purchased_at timestamptz not null,
  attributed_click_at timestamptz not null,
  latency_minutes integer not null,
  revenue numeric(16, 2) not null default 0,
  first_point_of_contact_id text,
  status_categories text[] not null default '{}',
  status_external_ids text[] not null default '{}',
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_trigger_attributed_orders_unique
    unique (goal_id, order_key),
  constraint push_trigger_attributed_orders_order_key_check
    check (order_key ~ '^[a-f0-9]{64}$'),
  constraint push_trigger_attributed_orders_buyer_key_check
    check (buyer_key ~ '^[a-f0-9]{64}$'),
  constraint push_trigger_attributed_orders_values_check
    check (
      latency_minutes >= 0
      and latency_minutes <= 1440
      and revenue >= 0
      and purchased_at >= attributed_click_at
    )
);

create index if not exists push_trigger_orders_mailing_goal_date_idx
  on public.push_trigger_attributed_orders (
    scenario_mailing_id,
    goal_id,
    purchased_at desc
  );

create index if not exists push_trigger_orders_project_goal_buyer_idx
  on public.push_trigger_attributed_orders (
    order_project_id,
    goal_id,
    buyer_key
  );

create index if not exists push_trigger_orders_touchpoint_idx
  on public.push_trigger_attributed_orders (touchpoint_id);

create table if not exists public.push_trigger_attributed_order_items (
  id bigint generated always as identity primary key,
  attributed_order_id bigint not null
    references public.push_trigger_attributed_orders(id)
    on update cascade on delete cascade,
  line_key text not null,
  product_internal_id text,
  product_external_id text,
  product_external_system_id text,
  display_name text not null,
  quantity numeric(14, 3) not null default 0,
  quantity_type text,
  unit_price numeric(16, 2),
  line_amount numeric(16, 2),
  status_internal_id text,
  status_category text,
  status_external_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_trigger_attributed_order_items_unique
    unique (attributed_order_id, line_key),
  constraint push_trigger_attributed_order_items_key_check
    check (line_key ~ '^[a-f0-9]{64}$'),
  constraint push_trigger_attributed_order_items_values_check
    check (
      quantity >= 0
      and (unit_price is null or unit_price >= 0)
      and (line_amount is null or line_amount >= 0)
    )
);

create index if not exists push_trigger_order_items_order_idx
  on public.push_trigger_attributed_order_items (attributed_order_id);

create table if not exists public.push_delta_cursors (
  table_name text primary key,
  last_version bigint not null,
  updated_at timestamptz not null default now(),
  constraint push_delta_cursors_version_check
    check (last_version >= 0)
);

create or replace view public.push_trigger_goal_metrics
with (security_invoker = true)
as
select
  attributed_order.scenario_mailing_id,
  attributed_order.goal_id,
  count(*)::bigint as orders,
  count(distinct attributed_order.buyer_key)::bigint as buyers,
  round(coalesce(sum(attributed_order.revenue), 0), 2) as revenue,
  count(*) filter (
    where attributed_order.latency_minutes <= 60
  )::bigint as latency_0_1h,
  count(*) filter (
    where attributed_order.latency_minutes > 60
      and attributed_order.latency_minutes <= 240
  )::bigint as latency_1_4h,
  count(*) filter (
    where attributed_order.latency_minutes > 240
      and attributed_order.latency_minutes <= 720
  )::bigint as latency_4_12h,
  count(*) filter (
    where attributed_order.latency_minutes > 720
  )::bigint as latency_12_24h
from public.push_trigger_attributed_orders as attributed_order
group by
  attributed_order.scenario_mailing_id,
  attributed_order.goal_id;

create or replace view public.push_trigger_goal_order_project_metrics
with (security_invoker = true)
as
select
  attributed_order.scenario_mailing_id,
  attributed_order.goal_id,
  attributed_order.order_project_id,
  count(*)::bigint as orders,
  count(distinct attributed_order.buyer_key)::bigint as buyers,
  round(coalesce(sum(attributed_order.revenue), 0), 2) as revenue,
  count(*) filter (
    where attributed_order.latency_minutes <= 60
  )::bigint as latency_0_1h,
  count(*) filter (
    where attributed_order.latency_minutes > 60
      and attributed_order.latency_minutes <= 240
  )::bigint as latency_1_4h,
  count(*) filter (
    where attributed_order.latency_minutes > 240
      and attributed_order.latency_minutes <= 720
  )::bigint as latency_4_12h,
  count(*) filter (
    where attributed_order.latency_minutes > 720
  )::bigint as latency_12_24h
from public.push_trigger_attributed_orders as attributed_order
group by
  attributed_order.scenario_mailing_id,
  attributed_order.goal_id,
  attributed_order.order_project_id;

alter table public.push_scenarios enable row level security;
alter table public.push_scenario_mailings enable row level security;
alter table public.push_scenario_daily_metrics enable row level security;
alter table public.push_click_touchpoints enable row level security;
alter table public.push_trigger_attributed_orders enable row level security;
alter table public.push_trigger_attributed_order_items enable row level security;
alter table public.push_delta_cursors enable row level security;

revoke all on table
  public.push_scenarios,
  public.push_scenario_mailings,
  public.push_scenario_daily_metrics,
  public.push_click_touchpoints,
  public.push_trigger_attributed_orders,
  public.push_trigger_attributed_order_items,
  public.push_delta_cursors
from anon, authenticated;

grant select on table
  public.push_scenarios,
  public.push_scenario_mailings,
  public.push_scenario_daily_metrics,
  public.push_trigger_attributed_orders,
  public.push_trigger_attributed_order_items
to anon, authenticated, service_role;

grant select on table
  public.push_trigger_goal_metrics,
  public.push_trigger_goal_order_project_metrics
to anon, authenticated, service_role;

grant select, insert, update, delete on table
  public.push_click_touchpoints,
  public.push_delta_cursors
to service_role;

grant insert, update, delete on table
  public.push_scenarios,
  public.push_scenario_mailings,
  public.push_scenario_daily_metrics,
  public.push_trigger_attributed_orders,
  public.push_trigger_attributed_order_items
to service_role;

grant usage, select on sequence
  public.push_scenarios_id_seq,
  public.push_scenario_mailings_id_seq,
  public.push_click_touchpoints_id_seq,
  public.push_trigger_attributed_orders_id_seq,
  public.push_trigger_attributed_order_items_id_seq
to service_role;

drop policy if exists "read push scenarios"
  on public.push_scenarios;
create policy "read push scenarios"
  on public.push_scenarios
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push scenario mailings"
  on public.push_scenario_mailings;
create policy "read push scenario mailings"
  on public.push_scenario_mailings
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push scenario daily metrics"
  on public.push_scenario_daily_metrics;
create policy "read push scenario daily metrics"
  on public.push_scenario_daily_metrics
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push trigger attributed orders"
  on public.push_trigger_attributed_orders;
create policy "read push trigger attributed orders"
  on public.push_trigger_attributed_orders
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push trigger attributed order items"
  on public.push_trigger_attributed_order_items;
create policy "read push trigger attributed order items"
  on public.push_trigger_attributed_order_items
  for select
  to anon, authenticated
  using (true);

comment on table public.push_scenarios is
  'Mindbox scenarios that initiated MobilePush mailings of type trigger.';
comment on table public.push_scenario_mailings is
  'Logical trigger push messages grouped across their Android and iOS Mindbox mailing ids.';
comment on table public.push_scenario_daily_metrics is
  'Daily trigger-push cohorts. Clicks are assigned to the day the message was sent.';
comment on column public.push_scenario_daily_metrics.delivered_estimated is
  'Sent minus NotDelivered. APNs and Firebase do not provide exact device delivery confirmation.';
comment on table public.push_click_touchpoints is
  'Private PII-free click stream shared by mass and trigger pushes for one global 24-hour last-click winner.';
comment on table public.push_trigger_attributed_orders is
  'PII-free orders won by a trigger push in the shared mass-versus-trigger last-click model.';
comment on table public.push_delta_cursors is
  'Last successfully processed Delta Sharing version for incremental synchronization.';

commit;
