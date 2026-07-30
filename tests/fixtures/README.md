# Test fixtures

- `delta/` содержит только синтетические строки без PII.
- `golden/stage0_expectations.json` фиксирует хэши и ключевые ожидания
  baseline `baselines/2026-07-30`.
- Полные golden-трассы не копируются: regression-тесты читают tracked baseline
  и проверяют его против зафиксированных хэшей.
- Изменение golden-ожиданий требует обновления ручной сверки и описания причины
  в `baselines/<date>/manual_verification.md`.
