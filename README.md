# sportscar-finance

Контур на 24 месяца: накопить на Xiaomi SU7 в РФ со 100 000 ₽.

- Анализ и ранжирование каналов: `docs/analiz-xiaomi-su7-24m.md`
- План работ: `docs/plan-rabot.md`
- Промпт модели: `docs/prompt-xiaomi-su7-invest.md`
- Монте-Карло: `python scripts/monte_carlo.py`
- Telegram-агент сигналов (не автоторговля):

```
python -m pip install -e .
copy .env.example .env
# заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
python -m sportscar_finance
```

Запускать из корня репозитория, чтобы подхватились `.env` и `data/state.json`.
