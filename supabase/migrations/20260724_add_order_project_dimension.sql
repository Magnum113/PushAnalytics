begin;

create table if not exists public.push_order_project_points (
  point_id text primary key,
  point_name text not null,
  project_id text not null references public.push_projects(id)
    on update cascade on delete restrict,
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.push_order_project_points (
  point_id,
  point_name,
  project_id,
  notes
)
values
  (
    '97f9a0dd-62d5-4e6c-8538-d4d00ffe221a',
    'blizkoios',
    'blizko-app',
    'Отдельное iOS-приложение Blizko.'
  ),
  (
    'af005e5f-d68b-462d-9dbb-c3b5e9a9617b',
    'blizkoandroid',
    'blizko-app',
    'Отдельное Android-приложение Blizko.'
  ),
  (
    'a349e806-a88e-432b-be10-0d8746f4d6e5',
    'blizkoandroidsandbox',
    'blizko-app',
    'Тестовая Android-точка отдельного приложения Blizko.'
  ),
  (
    '10',
    'Android приложение',
    '05-main',
    'Основное Android-приложение 05.ru.'
  ),
  (
    '11',
    'iOS приложение',
    '05-main',
    'Основное iOS-приложение 05.ru.'
  ),
  (
    '9',
    'Сайт',
    '05-main',
    'Основной веб-проект 05.ru.'
  ),
  (
    '43bce559-5c95-4967-82d9-3985cc97d614',
    'Маркетплейс',
    '05-main',
    'Маркетплейс 05.ru.'
  ),
  (
    'a1e1fd26-d7fd-416a-8447-b528dc8e12cd',
    'Darkstore',
    'blizko-in-05',
    'Blizko внутри 05.ru, веб-точка.'
  ),
  (
    '70e2ff71-c63d-4061-a1c3-4282860287aa',
    'AndroidAppDarkstore',
    'blizko-in-05',
    'Blizko внутри Android-приложения 05.ru.'
  ),
  (
    '998ee3ed-7579-43f9-8fe1-4129fb0805f6',
    'IosAppDarkstore',
    'blizko-in-05',
    'Blizko внутри iOS-приложения 05.ru.'
  )
on conflict (point_id) do update
set
  point_name = excluded.point_name,
  project_id = excluded.project_id,
  notes = excluded.notes,
  updated_at = now();

alter table public.push_attributed_orders
  add column if not exists order_project_id text;

update public.push_attributed_orders as attributed_order
set order_project_id = point.project_id
from public.push_order_project_points as point
where point.point_id = attributed_order.first_point_of_contact_id
  and attributed_order.order_project_id is distinct from point.project_id;

do $$
begin
  if exists (
    select 1
    from public.push_attributed_orders
    where order_project_id is null
  ) then
    raise exception
      'Cannot require order_project_id: some attributed orders have an unmapped point of contact';
  end if;
end
$$;

alter table public.push_attributed_orders
  alter column order_project_id set not null;

alter table public.push_attributed_orders
  drop constraint if exists push_attributed_orders_order_project_id_fkey;

alter table public.push_attributed_orders
  add constraint push_attributed_orders_order_project_id_fkey
  foreign key (order_project_id)
  references public.push_projects(id)
  on update cascade
  on delete restrict;

create index if not exists push_attributed_orders_campaign_goal_project_date_idx
  on public.push_attributed_orders (
    campaign_id,
    goal_id,
    order_project_id,
    purchased_at desc
  );

create index if not exists push_attributed_orders_campaign_goal_project_buyer_idx
  on public.push_attributed_orders (
    campaign_id,
    goal_id,
    order_project_id,
    buyer_key
  );

create or replace view public.push_campaign_goal_order_project_metrics
with (security_invoker = true)
as
select
  attributed_order.campaign_id,
  attributed_order.goal_id,
  attributed_order.order_project_id,
  count(*)::bigint as orders,
  count(distinct attributed_order.buyer_key)::bigint as buyers,
  round(coalesce(sum(attributed_order.revenue), 0), 2)::numeric(16, 2)
    as revenue,
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
      and attributed_order.latency_minutes <= 1440
  )::bigint as latency_12_24h
from public.push_attributed_orders as attributed_order
group by
  attributed_order.campaign_id,
  attributed_order.goal_id,
  attributed_order.order_project_id;

create or replace function public.push_unique_buyer_count_v2(
  campaign_ids bigint[],
  selected_goal_id text,
  selected_order_project_id text
)
returns bigint
language sql
stable
security invoker
set search_path = ''
as $$
  select count(distinct attributed_order.buyer_key)::bigint
  from public.push_attributed_orders as attributed_order
  where attributed_order.campaign_id = any(campaign_ids)
    and attributed_order.goal_id = selected_goal_id
    and (
      selected_order_project_id = 'all'
      or attributed_order.order_project_id = selected_order_project_id
    );
$$;

alter table public.push_order_project_points enable row level security;

revoke all on table public.push_order_project_points
from anon, authenticated;

grant select on table public.push_order_project_points
to anon, authenticated, service_role;

grant insert, update, delete on table public.push_order_project_points
to service_role;

drop policy if exists "read push order project points"
  on public.push_order_project_points;
create policy "read push order project points"
  on public.push_order_project_points
  for select
  to anon, authenticated
  using (true);

revoke all on table public.push_campaign_goal_order_project_metrics
from anon, authenticated;

grant select on table public.push_campaign_goal_order_project_metrics
to anon, authenticated, service_role;

grant execute on function public.push_unique_buyer_count_v2(
  bigint[],
  text,
  text
) to anon, authenticated, service_role;

comment on table public.push_order_project_points is
  'Auditable mapping from Mindbox first point of contact to the project where an attributed order was created.';
comment on column public.push_attributed_orders.order_project_id is
  'Normalized project where the order was created; independent from push_campaigns.project_id and from the selected Mindbox goal.';
comment on view public.push_campaign_goal_order_project_metrics is
  'Attributed order aggregates split by campaign, goal and actual order project.';

commit;
