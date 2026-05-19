from __future__ import annotations

from functools import lru_cache

from .config import Settings
from .repository import Neo4jGraphRepository
from .taxonomy import normalize_skill


class KnowledgeGraphService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.repository = Neo4jGraphRepository(settings)

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def normalize_skills(self, skills: list[str]) -> list[str]:
        normalized: list[str] = []
        for skill in skills:
            canonical = normalize_skill(skill) or skill.strip()
            if canonical and canonical not in normalized:
                normalized.append(canonical)
        return normalized

    def normalize_keywords(self, keywords: list[str]) -> list[str]:
        return self._dedupe(keywords)

    def normalize_benefits(self, benefits: list[str]) -> list[str]:
        return self._dedupe(benefits)


@lru_cache(maxsize=1)
def create_service() -> KnowledgeGraphService:
    settings = Settings.from_env()
    return KnowledgeGraphService(settings)
