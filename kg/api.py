from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import GraphResponse, JobSummary, RecommendationRequest, RecommendationResponse, SearchResponse, StatsResponse, TopItem
from .service import create_service

app = FastAPI(title="Knowledge Graph Job Recommendation System", version="1.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    service = create_service()
    return {"status": "ok", "backend": service.repository.backend_name}


@app.get("/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    return create_service().repository.stats()


@app.get("/jobs", response_model=SearchResponse)
def list_jobs(
    keyword: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    degree: str | None = None,
    experience: str | None = None,
    skills: list[str] = Query(default=[]),
    min_salary: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    service = create_service()
    items = service.repository.list_jobs(
        keyword=keyword,
        city=city,
        industry=industry,
        degree=degree,
        experience=experience,
        skills=service.normalize_skills(skills),
        min_salary=min_salary,
        limit=limit,
    )
    return SearchResponse(total=len(items), items=items)


@app.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    item = create_service().repository.get_job(job_id)
    if item is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return item


@app.get("/jobs/{job_id}/graph", response_model=GraphResponse)
def get_job_graph(job_id: str) -> GraphResponse:
    graph = create_service().repository.job_graph(job_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="岗位图谱不存在")
    return graph


@app.get("/jobs/{job_id}/similar", response_model=RecommendationResponse)
def similar_jobs(
    job_id: str,
    top_k: int = Query(default=10, ge=1, le=50),
) -> RecommendationResponse:
    items = create_service().repository.similar_jobs(job_id, top_k=top_k)
    return RecommendationResponse(total=len(items), items=items)


@app.post("/recommend/profile", response_model=RecommendationResponse)
def recommend_by_profile(profile: RecommendationRequest) -> RecommendationResponse:
    service = create_service()
    normalized_profile = profile.model_copy(
        update={
            "skills": service.normalize_skills(profile.skills),
            "top_k": max(1, min(profile.top_k, 50)),
        }
    )
    items = service.repository.recommend_by_profile(normalized_profile)
    return RecommendationResponse(total=len(items), items=items)


@app.get("/skills/top", response_model=list[TopItem])
def top_skills(limit: int = Query(default=20, ge=1, le=100)) -> list[TopItem]:
    return create_service().repository.top_skills(limit=limit)
