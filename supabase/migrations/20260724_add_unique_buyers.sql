begin;

alter table public.push_campaign_goal_metrics
  add column if not exists buyers bigint not null default 0;

alter table public.push_attributed_orders
  add column if not exists buyer_key text;

update public.push_attributed_orders
set buyer_key = order_key
where buyer_key is null;

alter table public.push_attributed_orders
  alter column buyer_key set not null;

alter table public.push_campaign_goal_metrics
  drop constraint if exists push_campaign_goal_metrics_buyers_check;

alter table public.push_campaign_goal_metrics
  add constraint push_campaign_goal_metrics_buyers_check
  check (buyers >= 0 and buyers <= orders);

alter table public.push_attributed_orders
  drop constraint if exists push_attributed_orders_buyer_key_check;

alter table public.push_attributed_orders
  add constraint push_attributed_orders_buyer_key_check
  check (buyer_key ~ '^[a-f0-9]{64}$');

create index if not exists push_attributed_orders_campaign_goal_buyer_idx
  on public.push_attributed_orders (campaign_id, goal_id, buyer_key);

create or replace function public.push_unique_buyer_count(
  campaign_ids bigint[],
  selected_goal_id text
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
    and attributed_order.goal_id = selected_goal_id;
$$;

grant execute on function public.push_unique_buyer_count(bigint[], text)
  to anon, authenticated, service_role;

update public.push_campaign_goal_metrics as metric
set buyers = actual.buyers
from (
  select
    campaign_id,
    goal_id,
    count(distinct buyer_key)::bigint as buyers
  from public.push_attributed_orders
  group by campaign_id, goal_id
) as actual
where metric.campaign_id = actual.campaign_id
  and metric.goal_id = actual.goal_id;

comment on column public.push_campaign_goal_metrics.buyers is
  'Unique attributed buyers for the campaign and goal.';
comment on column public.push_attributed_orders.buyer_key is
  'SHA-256 pseudonymous canonical Mindbox customer key; raw customer identifiers are never stored.';

commit;
