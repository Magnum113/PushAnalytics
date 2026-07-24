# Blizko Push Analytics

Локальный интерфейс аналитики push-рассылок Blizko на React, vinext и Vite.

## Запуск

Сначала соберите агрегированный набор в родительской папке:

```bash
cd PushAnalytics
.venv/bin/python scripts/build_dashboard_data.py --campaigns 5
```

Затем запустите интерфейс:

```bash
cd dashboard
npm install
npm run dev
```

Дашборд откроется на `http://localhost:3000/`.

## Проверки

```bash
npm run lint
npm test
```

Клиент получает только агрегированный `public/data/dashboard.json`. Секреты Mindbox, сырые Parquet-файлы и клиентские идентификаторы не входят в frontend.
