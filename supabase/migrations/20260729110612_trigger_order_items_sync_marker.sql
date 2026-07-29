begin;

alter table public.push_trigger_attributed_order_items
  add column if not exists generated_at timestamptz;

update public.push_trigger_attributed_order_items
set generated_at = coalesce(generated_at, now())
where generated_at is null;

alter table public.push_trigger_attributed_order_items
  alter column generated_at set not null;

create index if not exists push_trigger_order_items_generated_at_idx
  on public.push_trigger_attributed_order_items (generated_at);

comment on column public.push_trigger_attributed_order_items.generated_at is
  'Marker of the source snapshot used for idempotent synchronization.';

commit;
