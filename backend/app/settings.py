from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str = Field("mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field("gemini_tool_call", alias="MONGODB_DB")

    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        "google/gemini-3-flash-preview", alias="OPENROUTER_MODEL"
    )
    openrouter_http_referer: str = Field(
        "http://localhost:5173", alias="OPENROUTER_HTTP_REFERER"
    )
    openrouter_title: str = Field(
        "Gemini Tool Calling Playground", alias="OPENROUTER_TITLE"
    )

    serper_api_key: Optional[str] = Field(default=None, alias="SERPER_API_KEY")
    serper_gl: str = Field("us", alias="SERPER_GL")
    serper_hl: str = Field("en", alias="SERPER_HL")

    allow_origins: str = Field("http://localhost:5173", alias="ALLOW_ORIGINS")

    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
