# Stage 0 validation report

**Status:** `passed_with_warnings`

## Automated checks

| Check | Result | Detail |
| --- | --- | --- |
| `required_files` | PASS | missing=[] |
| `artifact_hashes` | PASS | mismatches=[] |
| `config_hash` | PASS | manifest and configuration hashes must match |
| `git_commit` | PASS | head=91a7863efcb828d23f9de279293a2947614ff364 |
| `project_folder_count` | PASS | observed=3 |
| `project_folders_exact` | PASS | invalid=[] |
| `supabase_quality` | PASS | nonZero={} |
| `published_trace_count` | PASS | traces=113 diagnostics=113 |
| `pii_free_keys` | PASS | invalidHashKeys=[] |
| `golden_winners` | PASS | invalidOrders=[] |
| `golden_click_window` | PASS | invalidOrders=[] |
| `golden_click_ordering` | PASS | invalidOrders=[] |
| `mass_push_sample` | PASS | massPushes=11 |
| `all_trigger_pushes` | PASS | golden=8 supabase=8 |
| `order_project_samples` | PASS | counts={'05-main': 32, 'blizko-app': 57, 'blizko-in-05': 24} |
| `known_campaigns` | PASS | found=['За окном +30', 'К матчу готовы'] |
| `diagnostic_cases` | PASS | missing=[] |
| `zero_order_push` | PASS | count=7 |
| `no_obvious_pii_or_secrets` | PASS | hits={'emails': 0, 'phones': 0, 'secretAssignments': 0} |

## Warnings

- В опубликованных заказах нет события ровно на 0/1440-й минуте; зафиксирован ближайший доступный случай (1439 мин.).
- CDP.MergedCustomers: локальный кэш v693, доступный Delta v694.
- Mailings.CustomerMessagesStatuses: локальный кэш v2154, доступный Delta v2164.
- Mailings.Mailings: локальный кэш v666, доступный Delta v667.
- PDP.ProductExternalIds: локальный кэш v63, доступный Delta v69.
- ProcessingOrders.Orders: локальный кэш v1493, доступный Delta v1495.
- ProcessingOrders.PointsOfContact: локальный кэш v730, доступный Delta v731.
- ProcessingOrders.PurchaseStatuses: локальный кэш v255, доступный Delta v685.
- ProcessingOrders.Purchases: локальный кэш v1506, доступный Delta v1508.

## Failures

- Нет.
