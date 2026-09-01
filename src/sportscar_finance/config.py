from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из файла .env: токен бота, пороги тревоги, стартовые суммы."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # На сколько может качнуться доллар за день, чтобы написать предупреждение (1,5%).
    usd_rub_day_move: float = 0.015
    # На сколько может качнуться биткоин за час (4%) и за сутки (8%).
    btc_hour_move: float = 0.04
    btc_day_move: float = 0.08
    # Если рыночные деньги просели на 15% — предупреждение, на 25% — стоп.
    market_dd_warn: float = 0.15
    market_dd_kill: float = 0.25

    # Старт: 50 тысяч на спокойном счёте, 10 тысяч в биткоине, 40 тысяч на запуск работы.
    cash_rub: float = 50_000
    btc_sleeve_rub: float = 10_000
    skill_reserve_rub: float = 40_000

    # Как часто спрашивать курсы: час, 15 минут, раз в сутки.
    poll_macro_sec: int = 3600
    poll_crypto_sec: int = 900
    poll_auto_sec: int = 86400
    digest_hour_msk: int = 21

    # Сколько денег нужно, чтобы хватило на машину (цена плюс запас 10%).
    hurdle_t1: float = 5_720_000
    hurdle_t2: float = 7_150_000
    hurdle_t3: float = 12_100_000


def load_settings() -> Settings:
    """Читает настройки из .env."""
    return Settings()
