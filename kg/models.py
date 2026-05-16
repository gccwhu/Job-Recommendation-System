from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass(slots=True)
class NormalizedJob:
    job_id: str
    title: str
    company_name: str
    city_name: str
    industry_name: str
    degree_name: str
    experience_name: str
    salary_min: int
    salary_max: int
    salary_mid: float
    source: str
    description: str
    detail_link: str
    company_type: str
    company_size: str
    skills: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    raw_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeGraph:
    jobs: dict[str, NormalizedJob]
    nodes: dict[str, dict[str, Any]]
    edges: list[dict[str, Any]]
    adjacency: dict[str, list[dict[str, Any]]]
    indexes: dict[str, dict[str, set[str]]]


class JobSummary(BaseModel):
    job_id: str
    title: str
    company_name: str
    city_name: str
    industry_name: str
    degree_name: str
    experience_name: str
    salary_min: int
    salary_max: int
    salary_mid: float
    company_type: str
    company_size: str
    skills: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source: str
    detail_link: str


class RecommendationRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    desired_city: str | None = None
    desired_industry: str | None = None
    degree: str | None = None
    experience: str | None = None
    min_salary: int | None = None
    keywords: list[str] = Field(default_factory=list)
    top_k: int = 10


class RecommendationItem(JobSummary):
    score: float
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    total: int
    items: list[JobSummary]


class RecommendationResponse(BaseModel):
    total: int
    items: list[RecommendationItem]


class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    job_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class StatsResponse(BaseModel):
    backend: str
    total_jobs: int
    total_companies: int
    total_skills: int
    total_benefits: int
    total_keywords: int
    total_cities: int
    total_industries: int
    average_skills_per_job: float


class TopItem(BaseModel):
    name: str
    count: int
