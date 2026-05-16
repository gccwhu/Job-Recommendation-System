from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    data_file: Path = Path("datasets/data_collect_result/processed/jobs.json")
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    neo4j_database: str = ""

    @staticmethod
    def _require_env(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(f"缺少必需环境变量 `{name}`")
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        return cls(
            data_file=Path(os.getenv("KG_DATA_FILE", "datasets/data_collect_result/processed/jobs.json")),
            neo4j_uri=cls._require_env("NEO4J_URI"),
            neo4j_user=cls._require_env("NEO4J_USER"),
            neo4j_password=cls._require_env("NEO4J_PASSWORD"),
            neo4j_database=cls._require_env("NEO4J_DATABASE"),
        )
