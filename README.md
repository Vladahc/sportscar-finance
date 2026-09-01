# Копилка на Xiaomi SU7

Проект помогает за два года накопить на машину Xiaomi SU7 в России. На старте есть 100 000 рублей.

Что внутри:

- разбор, куда класть деньги: `docs/analiz-xiaomi-su7-24m.md`
- как купить машину дешевле салона и ездить в России: `docs/vetka-pokupki.md`
- план дел по неделям: `docs/plan-rabot.md`
- текст для умной модели: `docs/prompt-xiaomi-su7-invest.md`
- расчёт множества случайных историй: `python scripts/monte_carlo.py`
- помощник в Telegram (сам сделки не открывает, только предупреждает)

Как запустить помощника:

```
python -m pip install -e .
copy .env.example .env
```

В файл `.env` впиши токен бота и номер своего чата. Потом:

```
python -m sportscar_finance
```

Запускай из папки проекта, чтобы нашлись `.env` и файл памяти `data/state.json`.
