from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from jinja2 import Environment, FileSystemLoader, ChoiceLoader


class Settings(BaseSettings):
    """Application-wide settings, loaded from .env via pydantic-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite-preview"
    gemini_thinking_level: str = ""  # "high" | "medium" | "low" | "none" | "" (disabled)

    # Snowflake connection (Spider 2.0-Snow benchmark)
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_warehouse: str = ""
    snowflake_database: str = ""

    # Spider 2.0-Snow benchmark root
    spider_snow_dir: Path = Path("Test/spider_snow")

    # Paths resolved relative to project root
    db_dir: Path = Path("Databases")
    test_file: Path = Path("Test/dev.json")
    profiles_dir: Path = Path("profiles")
    prompts_dir: Path = Path("src/insightxpert/prompts")

    # BIRD mini_dev benchmark root (Test/mini_dev/minidev/MINIDEV after download)
    mini_dev_dir: Path = Path("Test/mini_dev/minidev/MINIDEV")

    # ------------------------------------------------------------------ #
    # Benchmark-aware path helpers                                         #
    # benchmark is "bird_dev" (default) or "mini_dev"                     #
    # ------------------------------------------------------------------ #

    def get_db_path(self, db_id: str, benchmark: str = "bird_dev") -> Path:
        """Return the SQLite file path for the given database ID."""
        if benchmark == "mini_dev":
            return self.mini_dev_dir / "dev_databases" / db_id / f"{db_id}.sqlite"
        return self.db_dir / f"{db_id}.sqlite"

    def get_test_file(self, benchmark: str = "bird_dev") -> Path:
        """Return the JSON question file for the given benchmark."""
        if benchmark == "mini_dev":
            return self.mini_dev_dir / "mini_dev_sqlite.json"
        if benchmark == "spider_snow":
            return self.spider_snow_dir / "spider2_snow.json"
        return self.test_file

    def get_db_dir(self, benchmark: str = "bird_dev") -> Path:
        """Return the database root directory for the given benchmark.

        For mini_dev, each DB lives at <db_dir>/<db_id>/<db_id>.sqlite.
        For bird_dev, each DB lives at <db_dir>/<db_id>.sqlite.
        """
        if benchmark == "mini_dev":
            return self.mini_dev_dir / "dev_databases"
        if benchmark == "spider_snow":
            return self.spider_snow_dir
        return self.db_dir

    def get_profiles_dir(self, benchmark: str = "bird_dev") -> Path:
        """Return the profiles base directory for the given benchmark.

        mini_dev profiles live under profiles/mini_dev/ to avoid collisions
        with bird_dev profiles (both share database names like toxicology).
        """
        if benchmark == "mini_dev":
            return self.profiles_dir / "mini_dev"
        if benchmark == "spider_snow":
            return self.profiles_dir / "spider_snow"
        return self.profiles_dir

    def get_dialect(self, benchmark: str = "bird_dev") -> str:
        """Return the SQL dialect for the given benchmark."""
        if benchmark == "spider_snow":
            return "snowflake"
        return "sqlite"

    def get_snowflake_config(self) -> dict[str, str]:
        """Return Snowflake connection parameters."""
        return {
            "account": self.snowflake_account,
            "user": self.snowflake_user,
            "password": self.snowflake_password,
            "warehouse": self.snowflake_warehouse,
            "database": self.snowflake_database,
        }

    # Runtime override: set via --prompt-dir CLI flag
    _prompt_override_dir: Path | None = None

    def get_jinja_env(self) -> Environment:
        """Return a Jinja2 Environment pointed at the prompts directory.

        If _prompt_override_dir is set, templates there take priority
        (ChoiceLoader falls back to the default prompts_dir).
        """
        default_loader = FileSystemLoader(str(self.prompts_dir))
        if self._prompt_override_dir and self._prompt_override_dir.is_dir():
            override_loader = FileSystemLoader(str(self._prompt_override_dir))
            loader = ChoiceLoader([override_loader, default_loader])
        else:
            loader = default_loader
        return Environment(
            loader=loader,
            trim_blocks=True,
            lstrip_blocks=True,
        )


settings = Settings()
