begin;

alter table public.push_campaigns
  add column if not exists application_names text[] not null default '{}';

comment on column public.push_campaigns.application_names is
  'Exact Mindbox mobile applications used by the Android and iOS variants of the grouped campaign.';

commit;
