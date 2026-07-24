begin;

update public.push_project_rules
set
  is_active = false,
  notes = 'Папка содержит рассылки для разных приложений. Заменено точными правилами по mailing_internal_id после проверки карточек Mindbox 2026-07-23.',
  updated_at = now()
where match_field = 'folder_internal_id'
  and match_value = '0e07c12c-bd8a-48a1-b033-10aec22bc954';

insert into public.push_project_rules (
  project_id,
  match_field,
  match_value,
  priority,
  notes,
  is_active
)
values
  ('blizko-app', 'mailing_internal_id', 'd464ee9b-3cd6-4c94-894d-eb6bccb5055f', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '19805fbd-10aa-4095-8cc1-b0d7dc74c2c5', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'f8748fdd-0578-49ef-b312-da5a64b50bf5', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'bf61dcc2-8aa9-4958-9313-d227bb1a66b5', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '32e9a545-b303-40a7-9e1a-dbb3fe6d3ff4', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'e196139d-0ce6-4c5b-9d4a-a41d9c7cf3b6', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '2cf99025-ddd3-4bd8-9734-e996c200294f', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '7d82b510-1b22-401c-af1a-01968a213e74', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'a348f229-f68c-41be-bfa5-7e2304706895', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '0f5997b1-f383-446f-badc-50e638ddf054', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', '84d2aab7-53cd-4edf-a9c9-70733a29ba07', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'fe9ddb59-9449-4cf1-835e-cd5bab556661', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'ef5d6067-cbd7-4d6b-b639-668fd51c4819', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'e1e30f77-0892-4e80-9785-3f046cc1c471', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'd29056a9-480e-4d2c-a42d-84d4bdd23bd7', 10, 'Android приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-app', 'mailing_internal_id', 'ee44ad48-4bb3-48bc-8f90-3a5996fd36af', 10, 'iOS приложение Blizko; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-in-05', 'mailing_internal_id', '3580fd29-37f1-40e0-9928-8888617f3e69', 10, 'Android приложение 05ru; проверено в карточке Mindbox 2026-07-23.', true),
  ('blizko-in-05', 'mailing_internal_id', '908fba62-4430-4e27-8970-5bf85411bf82', 10, 'iOS приложение 05ru; проверено в карточке Mindbox 2026-07-23.', true)
on conflict (match_field, match_value) do update
set
  project_id = excluded.project_id,
  priority = excluded.priority,
  notes = excluded.notes,
  is_active = excluded.is_active,
  updated_at = now();

commit;
