# backend/core/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    # App Configuration
    app_name: str = "DS API"
    debug: bool = True
    
    # LLM Provider: gemini | openai | anthropic
    llm_provider: str

    # API Keys — only the one matching llm_provider is required at runtime
    api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # Model names per provider
    gemini_model: str
    openai_model: str
    anthropic_model: str
    
    # Database Configuration
    database_url: str
    
    # JWT Configuration
    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS Origins
    cors_origins: list[str] = [
        "http://localhost:8501", 
        "http://127.0.0.1:8501",
        "http://localhost:3000"
    ]

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings():
    return Settings()