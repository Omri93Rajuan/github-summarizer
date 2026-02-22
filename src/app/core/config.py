"""Runtime configuration loaded from environment variables."""

import os


class Settings:
    @property
    def nebius_api_key(self) -> str:
        value = os.environ.get("NEBIUS_API_KEY")
        if not value:
            raise EnvironmentError("NEBIUS_API_KEY environment variable is not set.")
        return value


settings = Settings()

