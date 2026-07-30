# Stage 0 baseline

**Captured at:** 2026-07-30T07:18:23.098353+00:00

**Git commit:** `91a7863efcb828d23f9de279293a2947614ff364`

**Assessment:** `Share with caveats`

## Scope

Read-only baseline текущей опубликованной аналитики, конфигурации и доступного Mindbox Delta-кэша. Исходные ID клиентов и заказов не сохраняются.

## Counts

- Mass campaigns: 39
- Mass attributed rows: 832
- Trigger mailings: 8
- Trigger attributed rows: 207
- Golden published orders: 113
- Traced published orders: 113

## Blockers

- Блокирующих автоматических проверок не обнаружено.

## Caveats

- Delta-источник новее опубликованного аналитического снимка; baseline фиксирует текущую публикацию, а не ещё не пересчитанные события.

## Artifacts

- `manifest.json` — Git, Delta versions и source fingerprints.
- `configuration.json` — правила и config hash.
- `supabase_snapshot.json` — агрегаты, схема и SQL quality checks.
- `golden_traces.json` — PII-free трассировки заказов и кликов.
- `golden_diagnostics.json` — полнота и расхождения трассировок.
- `validation_report.md` — результат автоматических проверок.
- `manual_verification.md` — ручная сверка с Mindbox UI.

## Validation commands

1. `python scripts/validate_stage0_baseline.py`.
2. `python scripts/validate_supabase_data.py`.
3. `python scripts/validate_trigger_supabase_data.py`.
4. `cd dashboard && npm run lint && npm run build`.
