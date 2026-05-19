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
    preferred_benefits: list[str] = Field(default_factory=list)
    seed_job_id: str | None = None
    max_hops: int = Field(default=3, ge=1, le=4)
    top_k: int = 10


class RecommendationItem(JobSummary):
    score: float
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    reasoning_paths: list["ReasoningPath"] = Field(default_factory=list)


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


class ReasoningPath(BaseModel):
    target_job_id: str
    target_title: str
    hop_count: int
    score: float
    node_names: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    explanation: str


class MultiHopReasoningResponse(BaseModel):
    job_id: str
    paths: list[ReasoningPath] = Field(default_factory=list)


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
    average_benefits_per_job: float = 0.0
    total_similarity_edges: int = 0


class TopItem(BaseModel):
    name: str
    count: int


class GraphInsightsResponse(BaseModel):
    top_skills: list[TopItem] = Field(default_factory=list)
    top_cities: list[TopItem] = Field(default_factory=list)
    top_industries: list[TopItem] = Field(default_factory=list)
    top_benefits: list[TopItem] = Field(default_factory=list)
