begin;

create index if not exists push_trigger_orders_mailing_goal_project_buyer_idx
  on public.push_trigger_attributed_orders (
    scenario_mailing_id,
    goal_id,
    order_project_id,
    buyer_key
  );

create or replace function public.push_matching_project_unique_buyer_count(
  campaign_ids bigint[],
  project_ids text[],
  selected_goal_id text
)
returns bigint
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  result bigint;
begin
  if campaign_ids is null
    or project_ids is null
    or selected_goal_id is null
    or btrim(selected_goal_id) = ''
  then
    raise exception using
      errcode = '22023',
      message = 'campaign_ids, project_ids and selected_goal_id are required';
  end if;

  if cardinality(campaign_ids) <> cardinality(project_ids) then
    raise exception using
      errcode = '22023',
      message = 'campaign_ids and project_ids must have equal cardinality';
  end if;

  if array_position(campaign_ids, null) is not null
    or array_position(project_ids, null) is not null
  then
    raise exception using
      errcode = '22023',
      message = 'campaign_ids and project_ids cannot contain nulls';
  end if;

  select count(distinct attributed_order.buyer_key)::bigint
  into result
  from public.push_attributed_orders as attributed_order
  join (
    select distinct
      selected.campaign_id,
      selected.project_id
    from unnest(campaign_ids, project_ids)
      as selected(campaign_id, project_id)
  ) as selected
    on selected.campaign_id = attributed_order.campaign_id
   and selected.project_id = attributed_order.order_project_id
  where attributed_order.goal_id = selected_goal_id;

  return coalesce(result, 0);
end;
$$;

create or replace function
public.push_trigger_matching_project_unique_buyer_count(
  scenario_mailing_ids bigint[],
  project_ids text[],
  selected_goal_id text,
  purchased_from timestamptz default null,
  purchased_until timestamptz default null
)
returns bigint
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  result bigint;
begin
  if scenario_mailing_ids is null
    or project_ids is null
    or selected_goal_id is null
    or btrim(selected_goal_id) = ''
  then
    raise exception using
      errcode = '22023',
      message = 'scenario_mailing_ids, project_ids and selected_goal_id are required';
  end if;

  if cardinality(scenario_mailing_ids) <> cardinality(project_ids) then
    raise exception using
      errcode = '22023',
      message = 'scenario_mailing_ids and project_ids must have equal cardinality';
  end if;

  if array_position(scenario_mailing_ids, null) is not null
    or array_position(project_ids, null) is not null
  then
    raise exception using
      errcode = '22023',
      message = 'scenario_mailing_ids and project_ids cannot contain nulls';
  end if;

  select count(distinct attributed_order.buyer_key)::bigint
  into result
  from public.push_trigger_attributed_orders as attributed_order
  join (
    select distinct
      selected.scenario_mailing_id,
      selected.project_id
    from unnest(scenario_mailing_ids, project_ids)
      as selected(scenario_mailing_id, project_id)
  ) as selected
    on selected.scenario_mailing_id =
      attributed_order.scenario_mailing_id
   and selected.project_id = attributed_order.order_project_id
  where attributed_order.goal_id = selected_goal_id
    and (
      purchased_from is null
      or attributed_order.purchased_at >= purchased_from
    )
    and (
      purchased_until is null
      or attributed_order.purchased_at < purchased_until
    );

  return coalesce(result, 0);
end;
$$;

revoke all on function public.push_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text
) from public;

revoke all on function
public.push_trigger_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text,
  timestamptz,
  timestamptz
) from public;

grant execute on function public.push_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text
) to anon, authenticated, service_role;

grant execute on function
public.push_trigger_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text,
  timestamptz,
  timestamptz
) to anon, authenticated, service_role;

comment on function public.push_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text
) is
  'Counts distinct mass-push buyers only when each order project matches the effective project paired with its campaign.';

comment on function
public.push_trigger_matching_project_unique_buyer_count(
  bigint[],
  text[],
  text,
  timestamptz,
  timestamptz
) is
  'Counts distinct trigger-push buyers only when each order project matches the effective project paired with its mailing.';

commit;
