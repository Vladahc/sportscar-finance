from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    usd_rub_day_move: float = 0.015
    btc_hour_move: float = 0.04
    btc_day_move: float = 0.08
    market_dd_warn: float = 0.15
    market_dd_kill: float = 0.25

    cash_rub: float = 50_000
    btc_sleeve_rub: float = 10_000
    skill_reserve_rub: float = 40_000

    poll_macro_sec: int = 3600
    poll_crypto_sec: int = 900
    poll_auto_sec: int = 86400
    digest_hour_msk: int = 21

    hurdle_t1: float = 5_720_000
    hurdle_t2: float = 7_150_000
    hurdle_t3: float = 12_100_000


def load_settings() -> Settings:
    return Settings()
