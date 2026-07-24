begin;

create table if not exists public.push_attributed_orders (
  id bigint generated always as identity primary key,
  campaign_id bigint not null references public.push_campaigns(id)
    on update cascade on delete cascade,
  goal_id text not null references public.push_goals(id)
    on update cascade on delete restrict,
  order_key text not null,
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
  constraint push_attributed_orders_unique
    unique (campaign_id, goal_id, order_key),
  constraint push_attributed_orders_key_check
    check (order_key ~ '^[a-f0-9]{64}$'),
  constraint push_attributed_orders_values_check
    check (
      latency_minutes >= 0
      and latency_minutes <= 1440
      and revenue >= 0
      and purchased_at >= attributed_click_at
    )
);

create index if not exists push_attributed_orders_campaign_goal_date_idx
  on public.push_attributed_orders (campaign_id, goal_id, purchased_at desc);

create table if not exists public.push_attributed_order_items (
  id bigint generated always as identity primary key,
  attributed_order_id bigint not null
    references public.push_attributed_orders(id)
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
  constraint push_attributed_order_items_unique
    unique (attributed_order_id, line_key),
  constraint push_attributed_order_items_key_check
    check (line_key ~ '^[a-f0-9]{64}$'),
  constraint push_attributed_order_items_values_check
    check (
      quantity >= 0
      and (unit_price is null or unit_price >= 0)
      and (line_amount is null or line_amount >= 0)
    )
);

create index if not exists push_attributed_order_items_order_idx
  on public.push_attributed_order_items (attributed_order_id);

alter table public.push_attributed_orders enable row level security;
alter table public.push_attributed_order_items enable row level security;

revoke all on table
  public.push_attributed_orders,
  public.push_attributed_order_items
from anon, authenticated;

grant select on table
  public.push_attributed_orders,
  public.push_attributed_order_items
to anon, authenticated, service_role;

grant insert, update, delete on table
  public.push_attributed_orders,
  public.push_attributed_order_items
to service_role;

grant usage, select on sequence
  public.push_attributed_orders_id_seq,
  public.push_attributed_order_items_id_seq
to service_role;

drop policy if exists "read push attributed orders"
  on public.push_attributed_orders;
create policy "read push attributed orders"
  on public.push_attributed_orders
  for select
  to anon, authenticated
  using (true);

drop policy if exists "read push attributed order items"
  on public.push_attributed_order_items;
create policy "read push attributed order items"
  on public.push_attributed_order_items
  for select
  to anon, authenticated
  using (true);

comment on table public.push_attributed_orders is
  'PII-free order facts attributed to a push by custom 24-hour last-click logic. Raw order and customer identifiers are never stored.';
comment on column public.push_attributed_orders.order_key is
  'SHA-256 of the Mindbox order id, used only as an anonymous stable key.';
comment on table public.push_attributed_order_items is
  'PII-free product lines for an attributed order. Product names are unavailable in the current Mindbox Delta export, so display_name is derived from external SKU.';

commit;
