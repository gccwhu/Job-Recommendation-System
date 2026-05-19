from fastapi.testclient import TestClient

from kg.api import app
from kg.models import (
    GraphInsightsResponse,
    GraphResponse,
    JobSummary,
    MultiHopReasoningResponse,
    ReasoningPath,
    RecommendationItem,
    RecommendationResponse,
    SearchResponse,
    StatsResponse,
    TopItem,
)


class FakeRepository:
    backend_name = "neo4j"

    def stats(self):
        return StatsResponse(
            backend="neo4j",
            total_jobs=2,
            total_companies=2,
            total_skills=4,
            total_benefits=2,
            total_keywords=3,
            total_cities=1,
            total_industries=1,
            average_skills_per_job=2.0,
            average_benefits_per_job=1.0,
            total_similarity_edges=1,
        )

    def list_jobs(self, **_kwargs):
        return [self.get_job("job-1")]

    def get_job(self, job_id):
        return JobSummary(
            job_id=job_id,
            title="机器学习工程师",
            company_name="甲公司",
            city_name="上海",
            industry_name="互联网",
            degree_name="本科",
            experience_name="3-5年",
            salary_min=20,
            salary_max=35,
            salary_mid=27.5,
            company_type="民营",
            company_size="150-500人",
            skills=["Python", "PyTorch"],
            benefits=["带薪年假"],
            keywords=["模型训练"],
            source="51job",
            detail_link="",
        )

    def job_graph(self, job_id):
        return GraphResponse(job_id=job_id, nodes=[], edges=[])

    def similar_jobs(self, _job_id, top_k=10):
        return [
            RecommendationItem(
                **self.get_job("job-2").model_dump(),
                score=8.0,
                matched_skills=["Python"],
                missing_skills=[],
                reasons=["共享技能 Python"],
                score_breakdown={"similarity_edge": 8.0},
            )
        ][:top_k]

    def recommend_by_profile(self, _profile):
        return [
            RecommendationItem(
                **self.get_job("job-1").model_dump(),
                score=10.0,
                matched_skills=["Python", "PyTorch"],
                missing_skills=[],
                reasons=["匹配技能 Python, PyTorch"],
                score_breakdown={"skills": 8.0, "city": 2.0},
            )
        ]

    def top_skills(self, limit=20):
        return [TopItem(name="Python", count=10)][:limit]

    def graph_insights(self, limit=10):
        return GraphInsightsResponse(
            top_skills=[TopItem(name="Python", count=10)][:limit],
            top_cities=[TopItem(name="上海", count=10)][:limit],
            top_industries=[TopItem(name="互联网", count=10)][:limit],
            top_benefits=[TopItem(name="带薪年假", count=8)][:limit],
        )

    def multi_hop_reasoning(self, job_id, **_kwargs):
        return [
            ReasoningPath(
                target_job_id="job-2",
                target_title="AI算法工程师",
                hop_count=2,
                score=1.5,
                node_names=[job_id, "Python", "job-2"],
                relations=["REQUIRES_SKILL", "REQUIRES_SKILL"],
                explanation=f"{job_id} -[REQUIRES_SKILL]- Python；Python -[REQUIRES_SKILL]- job-2",
            )
        ]


class FakeService:
    def __init__(self):
        self.repository = FakeRepository()

    def normalize_skills(self, skills):
        return skills

    def normalize_keywords(self, keywords):
        return keywords

    def normalize_benefits(self, benefits):
        return benefits


def test_api_routes(monkeypatch):
    monkeypatch.setattr("kg.api.create_service", lambda: FakeService())
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/stats").status_code == 200
    assert client.get("/jobs").status_code == 200
    assert client.get("/jobs/job-1").status_code == 200
    assert client.get("/jobs/job-1/graph").status_code == 200
    assert client.get("/jobs/job-1/similar").status_code == 200
    assert client.get("/jobs/job-1/reasoning").status_code == 200
    assert client.get("/skills/top").status_code == 200
    assert client.get("/graph/insights").status_code == 200
    assert client.post(
        "/recommend/profile",
        json={"skills": ["Python"], "preferred_benefits": ["带薪年假"], "top_k": 5},
    ).status_code == 200
