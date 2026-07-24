begin;

create table if not exists public.push_products (
  product_internal_id text primary key,
  name text not null,
  vendor_code text,
  external_id text,
  external_system_id text,
  picture_url text,
  source text not null default 'mindbox_product_export',
  source_updated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint push_products_name_check
    check (length(btrim(name)) > 0)
);

create index if not exists push_products_external_id_idx
  on public.push_products (external_id);

create index if not exists push_products_external_system_id_idx
  on public.push_products (external_system_id, external_id);

alter table public.push_products enable row level security;

revoke all on table public.push_products from anon, authenticated;

grant select on table public.push_products
  to anon, authenticated, service_role;

grant insert, update, delete on table public.push_products
  to service_role;

drop policy if exists "read push products" on public.push_products;
create policy "read push products"
  on public.push_products
  for select
  to anon, authenticated
  using (true);

comment on table public.push_products is
  'Non-PII product dictionary imported separately from the Mindbox product catalog. Used to resolve human-readable names for attributed order lines.';
comment on column public.push_products.product_internal_id is
  'Mindbox internal product identifier matching ProcessingOrders.Purchases.productInternalId.';

commit;
