from __future__ import annotations

import hashlib

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from .config import Settings
from .graph import build_knowledge_graph, degree_meets, experience_meets
from .models import (
    GraphEdge,
    GraphInsightsResponse,
    GraphNode,
    GraphResponse,
    JobSummary,
    KnowledgeGraph,
    NormalizedJob,
    ReasoningPath,
    RecommendationItem,
    RecommendationRequest,
    StatsResponse,
    TopItem,
)


class HydratedGraphView:
    def __init__(self, graph: KnowledgeGraph, backend_name: str = "neo4j"):
        self.graph = graph
        self.backend_name = backend_name

    def stats(self) -> StatsResponse:
        total_skills = len(self.graph.indexes["skills"])
        total_benefits = len(self.graph.indexes["benefits"])
        total_keywords = len(self.graph.indexes["keywords"])
        avg_skills = round(
            sum(len(job.skills) for job in self.graph.jobs.values()) / max(len(self.graph.jobs), 1),
            2,
        )
        avg_benefits = round(
            sum(len(job.benefits) for job in self.graph.jobs.values()) / max(len(self.graph.jobs), 1),
            2,
        )
        return StatsResponse(
            backend=self.backend_name,
            total_jobs=len(self.graph.jobs),
            total_companies=len(self.graph.indexes["companies"]),
            total_skills=total_skills,
            total_benefits=total_benefits,
            total_keywords=total_keywords,
            total_cities=len(self.graph.indexes["cities"]),
            total_industries=len(self.graph.indexes["industries"]),
            average_skills_per_job=avg_skills,
            average_benefits_per_job=avg_benefits,
        )


class Neo4jGraphRepository(HydratedGraphView):
    def __init__(self, settings: Settings, allow_empty: bool = False):
        self.settings = settings
        self.allow_empty = allow_empty
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self._bootstrap()

    def _bootstrap(self) -> None:
        try:
            with self.driver.session(database=self.settings.neo4j_database) as session:
                session.run("RETURN 1").consume()
                self._create_constraints(session)
                hydrated_graph = self._hydrate_graph(session)
                if hydrated_graph.jobs:
                    self._ensure_similarity_graph(session, hydrated_graph)
        except Neo4jError as exc:
            self.driver.close()
            raise RuntimeError(f"Neo4j 初始化失败: {exc}") from exc
        if not hydrated_graph.jobs and not self.allow_empty:
            raise RuntimeError("Neo4j 中尚未导入岗位图谱，请先执行 `python scripts/import_neo4j.py`")

        super().__init__(hydrated_graph, backend_name="neo4j")

    def _create_constraints(self, session) -> None:
        statements = [
            "CREATE CONSTRAINT job_id IF NOT EXISTS FOR (n:Job) REQUIRE n.job_id IS UNIQUE",
            "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (n:Company) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT city_name IF NOT EXISTS FOR (n:City) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT industry_name IF NOT EXISTS FOR (n:Industry) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT degree_name IF NOT EXISTS FOR (n:Degree) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT experience_name IF NOT EXISTS FOR (n:Experience) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (n:Skill) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT benefit_name IF NOT EXISTS FOR (n:Benefit) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT keyword_name IF NOT EXISTS FOR (n:Keyword) REQUIRE n.name IS UNIQUE",
        ]
        for statement in statements:
            session.run(statement).consume()

    def _replace_graph(self, session, graph: KnowledgeGraph) -> None:
        labels = ["Job", "Company", "City", "Industry", "Degree", "Experience", "Skill", "Benefit", "Keyword"]
        session.run(
            """
            MATCH (n)
            WHERE any(label IN labels(n) WHERE label IN $labels)
            DETACH DELETE n
            """,
            labels=labels,
        ).consume()
        query = """
        UNWIND $rows AS row
        MERGE (j:Job {job_id: row.job_id})
        SET j.title = row.title,
            j.salary_min = row.salary_min,
            j.salary_max = row.salary_max,
            j.salary_mid = row.salary_mid,
            j.source = row.source,
            j.detail_link = row.detail_link,
            j.description = row.description
        MERGE (c:Company {name: row.company_name})
        SET c.company_type = row.company_type,
            c.company_size = row.company_size
        MERGE (city:City {name: row.city_name})
        MERGE (industry:Industry {name: row.industry_name})
        MERGE (degree:Degree {name: row.degree_name})
        MERGE (exp:Experience {name: row.experience_name})
        MERGE (j)-[:POSTED_BY]->(c)
        MERGE (j)-[:LOCATED_IN]->(city)
        MERGE (j)-[:IN_INDUSTRY]->(industry)
        MERGE (j)-[:REQUIRES_DEGREE]->(degree)
        MERGE (j)-[:REQUIRES_EXPERIENCE]->(exp)
        MERGE (c)-[:BELONGS_TO]->(industry)
        FOREACH (skill_name IN row.skills |
            MERGE (skill:Skill {name: skill_name})
            MERGE (j)-[:REQUIRES_SKILL]->(skill)
        )
        FOREACH (benefit_name IN row.benefits |
            MERGE (benefit:Benefit {name: benefit_name})
            MERGE (j)-[:HAS_BENEFIT]->(benefit)
        )
        FOREACH (keyword_name IN row.keywords |
            MERGE (keyword:Keyword {name: keyword_name})
            MERGE (j)-[:HAS_KEYWORD]->(keyword)
        )
        """
        rows = [
            {
                "job_id": job.job_id,
                "title": job.title,
                "company_name": job.company_name or "未知公司",
                "city_name": job.city_name,
                "industry_name": job.industry_name,
                "degree_name": job.degree_name,
                "experience_name": job.experience_name,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_mid": job.salary_mid,
                "source": job.source,
                "detail_link": job.detail_link,
                "description": job.description,
                "company_type": job.company_type,
                "company_size": job.company_size,
                "skills": job.skills,
                "benefits": job.benefits,
                "keywords": job.keywords,
            }
            for job in graph.jobs.values()
        ]
        session.run(query, rows=rows).consume()

    @staticmethod
    def _similarity_rows(graph: KnowledgeGraph) -> list[dict[str, object]]:
        jobs = list(graph.jobs.values())
        rows: list[dict[str, object]] = []
        for index, left in enumerate(jobs):
            left_skills = set(left.skills)
            left_benefits = set(left.benefits)
            for right in jobs[index + 1:]:
                shared_skills = sorted(left_skills.intersection(right.skills))
                shared_benefits = sorted(left_benefits.intersection(right.benefits))
                same_city = left.city_name == right.city_name
                same_industry = left.industry_name == right.industry_name
                same_company = left.company_name == right.company_name
                score = (
                    len(shared_skills) * 3.0
                    + len(shared_benefits) * 0.6
                    + (1.5 if same_city else 0.0)
                    + (1.5 if same_industry else 0.0)
                    + (1.0 if same_company else 0.0)
                )
                if score < 3.0:
                    continue
                rows.append(
                    {
                        "left_job_id": left.job_id,
                        "right_job_id": right.job_id,
                        "score": round(score, 4),
                        "shared_skills": shared_skills,
                        "shared_benefits": shared_benefits,
                        "same_city": same_city,
                        "same_industry": same_industry,
                        "same_company": same_company,
                    }
                )
        return rows

    def _build_similarity_graph(self, session, graph: KnowledgeGraph) -> None:
        session.run("MATCH ()-[r:SIMILAR_TO]-() DELETE r").consume()
        rows = self._similarity_rows(graph)
        if not rows:
            return
        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Job {job_id: row.left_job_id})
            MATCH (b:Job {job_id: row.right_job_id})
            MERGE (a)-[r:SIMILAR_TO]->(b)
            SET r.score = row.score,
                r.shared_skills = row.shared_skills,
                r.shared_benefits = row.shared_benefits,
                r.same_city = row.same_city,
                r.same_industry = row.same_industry,
                r.same_company = row.same_company
            """,
            rows=rows,
        ).consume()

    def _ensure_similarity_graph(self, session, graph: KnowledgeGraph) -> None:
        count = session.run(
            "MATCH ()-[r:SIMILAR_TO]-() RETURN count(DISTINCT r) AS count"
        ).single()["count"]
        if count == 0:
            self._build_similarity_graph(session, graph)

    def sync_graph(self, graph: KnowledgeGraph) -> None:
        try:
            with self.driver.session(database=self.settings.neo4j_database) as session:
                self._create_constraints(session)
                self._replace_graph(session, graph)
                self._build_similarity_graph(session, graph)
        except Neo4jError as exc:
            raise RuntimeError(f"Neo4j 图谱同步失败: {exc}") from exc
        self.graph = graph

    def _hydrate_graph(self, session) -> KnowledgeGraph:
        query = """
        MATCH (j:Job)-[:POSTED_BY]->(c:Company)
        OPTIONAL MATCH (j)-[:LOCATED_IN]->(city:City)
        OPTIONAL MATCH (j)-[:IN_INDUSTRY]->(industry:Industry)
        OPTIONAL MATCH (j)-[:REQUIRES_DEGREE]->(degree:Degree)
        OPTIONAL MATCH (j)-[:REQUIRES_EXPERIENCE]->(exp:Experience)
        OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
        OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
        OPTIONAL MATCH (j)-[:HAS_KEYWORD]->(keyword:Keyword)
        RETURN
            j.job_id AS job_id,
            j.title AS title,
            c.name AS company_name,
            city.name AS city_name,
            industry.name AS industry_name,
            degree.name AS degree_name,
            exp.name AS experience_name,
            j.salary_min AS salary_min,
            j.salary_max AS salary_max,
            j.salary_mid AS salary_mid,
            j.source AS source,
            j.description AS description,
            j.detail_link AS detail_link,
            c.company_type AS company_type,
            c.company_size AS company_size,
            collect(DISTINCT skill.name) AS skills,
            collect(DISTINCT benefit.name) AS benefits,
            collect(DISTINCT keyword.name) AS keywords
        """
        records = session.run(query).data()
        jobs = [
            NormalizedJob(
                job_id=record["job_id"],
                title=record["title"],
                company_name=record["company_name"],
                city_name=record["city_name"] or "未知",
                industry_name=record["industry_name"] or "未知行业",
                degree_name=record["degree_name"] or "不限",
                experience_name=record["experience_name"] or "不限",
                salary_min=record["salary_min"] or 0,
                salary_max=record["salary_max"] or 0,
                salary_mid=record["salary_mid"] or 0.0,
                source=record["source"] or "51job",
                description=record["description"] or "",
                detail_link=record["detail_link"] or "",
                company_type=record["company_type"] or "",
                company_size=record["company_size"] or "",
                skills=sorted(filter(None, record["skills"])),
                benefits=sorted(filter(None, record["benefits"])),
                keywords=sorted(filter(None, record["keywords"])),
                raw_tags=[],
            )
            for record in records
        ]
        return build_knowledge_graph(jobs)

    def close(self) -> None:
        self.driver.close()

    def stats(self) -> StatsResponse:
        with self.driver.session(database=self.settings.neo4j_database) as session:
            counts = {
                "total_jobs": session.run("MATCH (n:Job) RETURN count(n) AS count").single()["count"],
                "total_companies": session.run("MATCH (n:Company) RETURN count(n) AS count").single()["count"],
                "total_skills": session.run("MATCH (n:Skill) RETURN count(n) AS count").single()["count"],
                "total_benefits": session.run("MATCH (n:Benefit) RETURN count(n) AS count").single()["count"],
                "total_keywords": session.run("MATCH (n:Keyword) RETURN count(n) AS count").single()["count"],
                "total_cities": session.run("MATCH (n:City) RETURN count(n) AS count").single()["count"],
                "total_industries": session.run("MATCH (n:Industry) RETURN count(n) AS count").single()["count"],
                "total_similarity_edges": session.run("MATCH ()-[r:SIMILAR_TO]-() RETURN count(DISTINCT r) AS count").single()["count"],
            }
            averages = session.run(
                """
                MATCH (j:Job)
                OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
                WITH j, count(DISTINCT skill) AS skill_count
                OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
                WITH j, skill_count, count(DISTINCT benefit) AS benefit_count
                RETURN round(avg(skill_count), 2) AS average_skills_per_job,
                       round(avg(benefit_count), 2) AS average_benefits_per_job
                """
            ).single()
        if averages is None:
            return super().stats()
        return StatsResponse(
            backend=self.backend_name,
            total_jobs=counts["total_jobs"] or 0,
            total_companies=counts["total_companies"] or 0,
            total_skills=counts["total_skills"] or 0,
            total_benefits=counts["total_benefits"] or 0,
            total_keywords=counts["total_keywords"] or 0,
            total_cities=counts["total_cities"] or 0,
            total_industries=counts["total_industries"] or 0,
            average_skills_per_job=averages["average_skills_per_job"] or 0.0,
            average_benefits_per_job=averages["average_benefits_per_job"] or 0.0,
            total_similarity_edges=counts["total_similarity_edges"] or 0,
        )

    @staticmethod
    def _node_id(label: str, name: str) -> str:
        digest = hashlib.md5(f"{label}:{name}".encode("utf-8")).hexdigest()[:12]
        return f"{label.lower()}:{digest}"

    @staticmethod
    def _compact_graph_properties(label: str, properties: dict | None) -> dict:
        properties = properties or {}
        allowed_keys = {
            "Job": ["job_id", "title", "salary_min", "salary_max", "salary_mid", "source", "detail_link"],
            "Company": ["name", "company_type", "company_size"],
            "City": ["name"],
            "Industry": ["name"],
            "Degree": ["name"],
            "Experience": ["name"],
            "Skill": ["name"],
            "Benefit": ["name"],
            "Keyword": ["name"],
        }.get(label)
        if allowed_keys is None:
            return properties
        return {key: properties[key] for key in allowed_keys if key in properties and properties[key] not in (None, "")}

    @staticmethod
    def _clean_list(items: list[str | None]) -> list[str]:
        return sorted(item for item in items if item)

    @staticmethod
    def _breakdown_total(breakdown: dict[str, float]) -> float:
        return round(sum(breakdown.values()), 2)

    @classmethod
    def _record_to_summary(cls, record) -> JobSummary:
        return JobSummary(
            job_id=record["job_id"],
            title=record["title"],
            company_name=record["company_name"],
            city_name=record["city_name"] or "未知",
            industry_name=record["industry_name"] or "未知行业",
            degree_name=record["degree_name"] or "不限",
            experience_name=record["experience_name"] or "不限",
            salary_min=record["salary_min"] or 0,
            salary_max=record["salary_max"] or 0,
            salary_mid=record["salary_mid"] or 0.0,
            company_type=record["company_type"] or "",
            company_size=record["company_size"] or "",
            skills=cls._clean_list(record["skills"]),
            benefits=cls._clean_list(record["benefits"]),
            keywords=cls._clean_list(record["keywords"]),
            source=record["source"] or "51job",
            detail_link=record["detail_link"] or "",
        )

    @staticmethod
    def _summary_query(match_clause: str, where_clause: str = "") -> str:
        return f"""
        {match_clause}
        OPTIONAL MATCH (j)-[:POSTED_BY]->(c:Company)
        OPTIONAL MATCH (j)-[:LOCATED_IN]->(city:City)
        OPTIONAL MATCH (j)-[:IN_INDUSTRY]->(industry:Industry)
        OPTIONAL MATCH (j)-[:REQUIRES_DEGREE]->(degree:Degree)
        OPTIONAL MATCH (j)-[:REQUIRES_EXPERIENCE]->(exp:Experience)
        OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
        OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
        OPTIONAL MATCH (j)-[:HAS_KEYWORD]->(keyword:Keyword)
        WITH j, c, city, industry, degree, exp,
             collect(DISTINCT skill.name) AS skills,
             collect(DISTINCT benefit.name) AS benefits,
             collect(DISTINCT keyword.name) AS keywords
        {where_clause}
        RETURN
            j.job_id AS job_id,
            j.title AS title,
            c.name AS company_name,
            city.name AS city_name,
            industry.name AS industry_name,
            degree.name AS degree_name,
            exp.name AS experience_name,
            j.salary_min AS salary_min,
            j.salary_max AS salary_max,
            j.salary_mid AS salary_mid,
            c.company_type AS company_type,
            c.company_size AS company_size,
            skills AS skills,
            benefits AS benefits,
            keywords AS keywords,
            j.source AS source,
            j.detail_link AS detail_link
        """

    def list_jobs(
        self,
        *,
        keyword: str | None = None,
        city: str | None = None,
        industry: str | None = None,
        degree: str | None = None,
        experience: str | None = None,
        skills: list[str] | None = None,
        min_salary: int | None = None,
        limit: int = 20,
    ) -> list[JobSummary]:
        skills = skills or []
        query = self._summary_query(
            "MATCH (j:Job)",
            """
            WHERE ($city IS NULL OR city.name = $city)
              AND ($industry IS NULL OR industry.name = $industry)
              AND ($degree IS NULL OR degree.name = $degree)
              AND ($experience IS NULL OR exp.name = $experience)
              AND ($min_salary IS NULL OR j.salary_max >= $min_salary)
              AND (size($skills) = 0 OR all(skill_name IN $skills WHERE skill_name IN skills))
              AND (
                    $keyword IS NULL
                    OR toLower(j.title) CONTAINS $keyword
                    OR toLower(c.name) CONTAINS $keyword
                    OR any(item IN skills WHERE toLower(item) CONTAINS $keyword)
                    OR any(item IN keywords WHERE toLower(item) CONTAINS $keyword)
              )
            """,
        ) + "\nORDER BY j.salary_mid DESC, size(skills) DESC, j.title ASC\nLIMIT $limit"
        params = {
            "keyword": keyword.strip().lower() if keyword else None,
            "city": city,
            "industry": industry,
            "degree": degree,
            "experience": experience,
            "skills": skills,
            "min_salary": min_salary,
            "limit": limit,
        }
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, **params).data()
        return [self._record_to_summary(record) for record in records]

    def get_job(self, job_id: str) -> JobSummary | None:
        query = self._summary_query("MATCH (j:Job {job_id: $job_id})") + "\nLIMIT 1"
        with self.driver.session(database=self.settings.neo4j_database) as session:
            record = session.run(query, job_id=job_id).single()
        return self._record_to_summary(record) if record else None

    def recommend_by_profile(self, profile: RecommendationRequest) -> list[RecommendationItem]:
        path_scores = self._multi_hop_score_rows(profile.seed_job_id, max_hops=profile.max_hops) if profile.seed_job_id else []
        query = """
        MATCH (j:Job)
        WHERE ($seed_job_id IS NULL OR j.job_id <> $seed_job_id)
        OPTIONAL MATCH (j)-[:POSTED_BY]->(c:Company)
        OPTIONAL MATCH (j)-[:LOCATED_IN]->(city:City)
        OPTIONAL MATCH (j)-[:IN_INDUSTRY]->(industry:Industry)
        OPTIONAL MATCH (j)-[:REQUIRES_DEGREE]->(degree:Degree)
        OPTIONAL MATCH (j)-[:REQUIRES_EXPERIENCE]->(exp:Experience)
        OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
        OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
        OPTIONAL MATCH (j)-[:HAS_KEYWORD]->(keyword:Keyword)
        WITH j, c, city, industry, degree, exp,
             collect(DISTINCT skill.name) AS skills,
             collect(DISTINCT benefit.name) AS benefits,
             collect(DISTINCT keyword.name) AS keywords
        WHERE ($min_salary IS NULL OR j.salary_max >= $min_salary)
        WITH j, c, city, industry, degree, exp, skills, benefits, keywords,
             [item IN $skills WHERE item IN skills] AS matched_skills,
             [item IN $skills WHERE NOT item IN skills] AS missing_skills,
             [item IN $keywords WHERE item IN keywords OR item IN skills] AS matched_keywords,
             [item IN $preferred_benefits WHERE item IN benefits] AS matched_benefits,
             coalesce([row IN $path_scores WHERE row.job_id = j.job_id | row.score][0], 0.0) AS path_score
        WITH j, c, city, industry, degree, exp, skills, benefits, keywords,
             matched_skills, missing_skills, matched_keywords, matched_benefits, path_score,
             size(matched_skills) * 4.0
             + CASE WHEN size($skills) = 0 THEN 0.0 ELSE (toFloat(size(matched_skills)) / size($skills)) * 2.0 END
             + size(matched_keywords) * 1.5
             + size(matched_benefits) * 1.2
             + CASE WHEN $desired_city IS NOT NULL AND city.name = $desired_city THEN 3.0 ELSE 0.0 END
             + CASE WHEN $desired_industry IS NOT NULL AND industry.name = $desired_industry THEN 2.5 ELSE 0.0 END
             + CASE WHEN $min_salary IS NOT NULL AND j.salary_max >= $min_salary THEN 1.0 ELSE 0.0 END
             + path_score * 0.35
             AS pre_score
        WHERE pre_score > 0
          AND (
                size($skills) = 0
                OR size(matched_skills) > 0
                OR size(matched_keywords) > 0
                OR size(matched_benefits) > 0
                OR path_score > 0
              )
        RETURN
            j.job_id AS job_id,
            j.title AS title,
            c.name AS company_name,
            city.name AS city_name,
            industry.name AS industry_name,
            degree.name AS degree_name,
            exp.name AS experience_name,
            j.salary_min AS salary_min,
            j.salary_max AS salary_max,
            j.salary_mid AS salary_mid,
            c.company_type AS company_type,
            c.company_size AS company_size,
            skills AS skills,
            benefits AS benefits,
            keywords AS keywords,
            j.source AS source,
            j.detail_link AS detail_link,
            matched_skills AS matched_skills,
            missing_skills AS missing_skills,
            matched_keywords AS matched_keywords,
            matched_benefits AS matched_benefits,
            path_score AS path_score,
            pre_score AS pre_score
        ORDER BY pre_score DESC, j.salary_mid DESC, size(skills) DESC
        LIMIT $candidate_limit
        """
        params = {
            "skills": profile.skills,
            "keywords": profile.keywords,
            "preferred_benefits": profile.preferred_benefits,
            "desired_city": profile.desired_city,
            "desired_industry": profile.desired_industry,
            "min_salary": profile.min_salary,
            "seed_job_id": profile.seed_job_id,
            "path_scores": path_scores,
            "candidate_limit": min(max(profile.top_k * 8, 30), 200),
        }
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, **params).data()

        items: list[RecommendationItem] = []
        for record in records:
            summary = self._record_to_summary(record)
            if profile.degree and not degree_meets(profile.degree, summary.degree_name):
                continue
            if profile.experience and not experience_meets(profile.experience, summary.experience_name):
                continue
            reasons = []
            matched_skills = self._clean_list(record["matched_skills"])
            missing_skills = self._clean_list(record["missing_skills"])
            matched_keywords = self._clean_list(record["matched_keywords"])
            matched_benefits = self._clean_list(record["matched_benefits"])
            breakdown = {
                "skills": round(len(matched_skills) * 4.0, 2),
                "skill_coverage": round((len(matched_skills) / len(profile.skills)) * 2.0, 2) if profile.skills else 0.0,
                "keywords": round(len(matched_keywords) * 1.5, 2),
                "benefits": round(len(matched_benefits) * 1.2, 2),
                "city": 3.0 if profile.desired_city and summary.city_name == profile.desired_city else 0.0,
                "industry": 2.5 if profile.desired_industry and summary.industry_name == profile.desired_industry else 0.0,
                "salary": 1.0 if profile.min_salary is not None and summary.salary_max >= profile.min_salary else 0.0,
                "degree": 1.0 if profile.degree and degree_meets(profile.degree, summary.degree_name) else 0.0,
                "experience": 1.0 if profile.experience and experience_meets(profile.experience, summary.experience_name) else 0.0,
                "multi_hop": round((record["path_score"] or 0.0) * 0.35, 2),
            }
            if matched_skills:
                reasons.append(f"匹配技能 {', '.join(matched_skills)}")
            if matched_keywords:
                reasons.append(f"关键词命中 {', '.join(matched_keywords[:4])}")
            if matched_benefits:
                reasons.append(f"福利匹配 {', '.join(matched_benefits[:4])}")
            if profile.desired_city and summary.city_name == profile.desired_city:
                reasons.append(f"城市匹配 {summary.city_name}")
            if profile.desired_industry and summary.industry_name == profile.desired_industry:
                reasons.append(f"行业匹配 {summary.industry_name}")
            if profile.min_salary is not None and summary.salary_max >= profile.min_salary:
                reasons.append(f"薪资满足 {summary.salary_min}-{summary.salary_max}k")
            if profile.degree and degree_meets(profile.degree, summary.degree_name):
                reasons.append(f"学历匹配 {summary.degree_name}")
            if profile.experience and experience_meets(profile.experience, summary.experience_name):
                reasons.append(f"经验匹配 {summary.experience_name}")
            if profile.seed_job_id and (record["path_score"] or 0) > 0:
                reasons.append(f"{profile.max_hops} 跳内图谱关联度 {record['path_score']:.1f}")
            if not reasons:
                reasons.append(f"综合得分 {self._breakdown_total(breakdown):.1f}")
            items.append(
                RecommendationItem(
                    **summary.model_dump(),
                    score=self._breakdown_total(breakdown),
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    reasons=reasons,
                    score_breakdown=breakdown,
                )
            )
        items.sort(key=lambda item: (item.score, item.salary_mid, len(item.skills)), reverse=True)
        top_items = items[: profile.top_k]
        if profile.seed_job_id:
            for item in top_items:
                item.reasoning_paths = self.multi_hop_reasoning(
                    profile.seed_job_id,
                    target_job_id=item.job_id,
                    max_hops=profile.max_hops,
                    limit=2,
                )
        return top_items

    def similar_jobs(self, job_id: str, top_k: int = 10) -> list[RecommendationItem]:
        query = """
        MATCH (base:Job {job_id: $job_id})-[sim:SIMILAR_TO]-(j:Job)
        OPTIONAL MATCH (j)-[:POSTED_BY]->(c:Company)
        OPTIONAL MATCH (j)-[:LOCATED_IN]->(city:City)
        OPTIONAL MATCH (j)-[:IN_INDUSTRY]->(industry:Industry)
        OPTIONAL MATCH (j)-[:REQUIRES_DEGREE]->(degree:Degree)
        OPTIONAL MATCH (j)-[:REQUIRES_EXPERIENCE]->(exp:Experience)
        OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
        OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
        OPTIONAL MATCH (j)-[:HAS_KEYWORD]->(keyword:Keyword)
        WITH sim, j, c, city, industry, degree, exp,
             collect(DISTINCT skill.name) AS skills,
             collect(DISTINCT benefit.name) AS benefits,
             collect(DISTINCT keyword.name) AS keywords
        RETURN
            j.job_id AS job_id,
            j.title AS title,
            c.name AS company_name,
            city.name AS city_name,
            industry.name AS industry_name,
            degree.name AS degree_name,
            exp.name AS experience_name,
            j.salary_min AS salary_min,
            j.salary_max AS salary_max,
            j.salary_mid AS salary_mid,
            c.company_type AS company_type,
            c.company_size AS company_size,
            skills AS skills,
            benefits AS benefits,
            keywords AS keywords,
            j.source AS source,
            j.detail_link AS detail_link,
            sim.shared_skills AS matched_skills,
            sim.shared_benefits AS matched_benefits,
            sim.same_city AS same_city,
            sim.same_industry AS same_industry,
            sim.same_company AS same_company,
            sim.score AS score
        ORDER BY sim.score DESC, j.salary_mid DESC
        LIMIT $top_k
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, job_id=job_id, top_k=top_k).data()

        items: list[RecommendationItem] = []
        for record in records:
            summary = self._record_to_summary(record)
            matched_skills = self._clean_list(record["matched_skills"])
            matched_benefits = self._clean_list(record["matched_benefits"])
            reasons = []
            if matched_skills:
                reasons.append(f"共享技能 {', '.join(matched_skills)}")
            if matched_benefits:
                reasons.append(f"共享福利 {', '.join(matched_benefits[:3])}")
            if record["same_city"]:
                reasons.append(f"同城候选 {summary.city_name}")
            if record["same_industry"]:
                reasons.append(f"行业关联 {summary.industry_name}")
            if record["same_company"]:
                reasons.append(f"同公司 {summary.company_name}")
            items.append(
                RecommendationItem(
                    **summary.model_dump(),
                    score=round(record["score"], 2),
                    matched_skills=matched_skills,
                    missing_skills=[],
                    reasons=reasons,
                    score_breakdown={"similarity_edge": round(record["score"], 2)},
                    reasoning_paths=self.multi_hop_reasoning(job_id, target_job_id=summary.job_id, max_hops=3, limit=2),
                )
            )
        return items

    @staticmethod
    def _path_explanation(node_names: list[str], relations: list[str]) -> str:
        if not relations:
            return ""
        steps: list[str] = []
        for index, relation in enumerate(relations):
            source = node_names[index] if index < len(node_names) else ""
            target = node_names[index + 1] if index + 1 < len(node_names) else ""
            steps.append(f"{source} -[{relation}]- {target}")
        return "；".join(steps)

    def _multi_hop_records(
        self,
        job_id: str,
        *,
        target_job_id: str | None = None,
        max_hops: int = 3,
        limit: int = 10,
        prefer_multi_hop: bool = False,
    ) -> list[dict]:
        safe_hops = max(1, min(max_hops, 4))
        candidate_limit = min(max(limit * 4, 50), 400)
        relation_score = """
            CASE type($rel)
                WHEN 'SIMILAR_TO' THEN coalesce($rel.score, 8.0)
                WHEN 'REQUIRES_SKILL' THEN 3.0
                WHEN 'HAS_BENEFIT' THEN 1.2
                WHEN 'LOCATED_IN' THEN 2.0
                WHEN 'IN_INDUSTRY' THEN 2.0
                WHEN 'POSTED_BY' THEN 1.5
                WHEN 'HAS_KEYWORD' THEN 0.8
                WHEN 'BELONGS_TO' THEN 0.8
                WHEN 'REQUIRES_DEGREE' THEN 0.6
                WHEN 'REQUIRES_EXPERIENCE' THEN 0.6
                ELSE 0.4
            END
        """
        query = f"""
        MATCH (seed:Job {{job_id: $job_id}})
        CALL (seed) {{
            MATCH (seed)-[sim:SIMILAR_TO]-(target:Job)
            WHERE $max_hops >= 1
              AND target.job_id <> seed.job_id
              AND ($target_job_id IS NULL OR target.job_id = $target_job_id)
            WITH target,
                 [coalesce(seed.title, seed.job_id), coalesce(target.title, target.job_id)] AS node_names,
                 ['SIMILAR_TO'] AS relations,
                 1 AS hops,
                 coalesce(sim.score, 8.0) AS path_score,
                 3 AS path_rank
            ORDER BY path_score DESC, target.title ASC
            LIMIT $candidate_limit
            RETURN target, node_names, relations, hops, round(path_score, 2) AS path_score, path_rank

            UNION ALL

            MATCH (seed)-[r1]-(entity)-[r2]-(target:Job)
            WHERE $max_hops >= 2
              AND target.job_id <> seed.job_id
              AND ($target_job_id IS NULL OR target.job_id = $target_job_id)
              AND NOT entity:Job
              AND type(r1) <> 'SIMILAR_TO'
              AND type(r2) <> 'SIMILAR_TO'
            WITH target,
                 [coalesce(seed.title, seed.job_id), coalesce(entity.name, entity.title, entity.job_id), coalesce(target.title, target.job_id)] AS node_names,
                 [type(r1), type(r2)] AS relations,
                 2 AS hops,
                 0 AS path_rank,
                 ({relation_score.replace("$rel", "r1")} + {relation_score.replace("$rel", "r2")}) AS raw_score
            WITH target, node_names, relations, hops, path_rank, round((raw_score / 2.0) * (1.0 / 2.0), 2) AS path_score
            ORDER BY path_score DESC, target.title ASC
            LIMIT $candidate_limit
            RETURN target, node_names, relations, hops, path_score, path_rank

            UNION ALL

            MATCH (seed)-[sim1:SIMILAR_TO]-(mid:Job)-[sim2:SIMILAR_TO]-(target:Job)
            WHERE $max_hops >= 2
              AND mid.job_id <> seed.job_id
              AND target.job_id <> seed.job_id
              AND target.job_id <> mid.job_id
              AND ($target_job_id IS NULL OR target.job_id = $target_job_id)
            WITH target,
                 [coalesce(seed.title, seed.job_id), coalesce(mid.title, mid.job_id), coalesce(target.title, target.job_id)] AS node_names,
                 ['SIMILAR_TO', 'SIMILAR_TO'] AS relations,
                 2 AS hops,
                 2 AS path_rank,
                 (coalesce(sim1.score, 8.0) + coalesce(sim2.score, 8.0)) AS raw_score
            WITH target, node_names, relations, hops, path_rank, round((raw_score / 2.0) * (1.0 / 2.0), 2) AS path_score
            ORDER BY path_score DESC, target.title ASC
            LIMIT $candidate_limit
            RETURN target, node_names, relations, hops, path_score, path_rank

            UNION ALL

            MATCH (seed)-[r1]-(entity)-[r2]-(mid:Job)-[sim:SIMILAR_TO]-(target:Job)
            WHERE $max_hops >= 3
              AND mid.job_id <> seed.job_id
              AND target.job_id <> seed.job_id
              AND target.job_id <> mid.job_id
              AND ($target_job_id IS NULL OR target.job_id = $target_job_id)
              AND NOT entity:Job
              AND type(r1) <> 'SIMILAR_TO'
              AND type(r2) <> 'SIMILAR_TO'
            WITH target,
                 [coalesce(seed.title, seed.job_id), coalesce(entity.name, entity.title, entity.job_id), coalesce(mid.title, mid.job_id), coalesce(target.title, target.job_id)] AS node_names,
                 [type(r1), type(r2), 'SIMILAR_TO'] AS relations,
                 3 AS hops,
                 1 AS path_rank,
                 ({relation_score.replace("$rel", "r1")} + {relation_score.replace("$rel", "r2")} + coalesce(sim.score, 8.0)) AS raw_score
            WITH target, node_names, relations, hops, path_rank, round((raw_score / 3.0) * (1.0 / 3.0), 2) AS path_score
            ORDER BY path_score DESC, target.title ASC
            LIMIT $candidate_limit
            RETURN target, node_names, relations, hops, path_score, path_rank
        }}
        ORDER BY target.job_id,
                 CASE WHEN $prefer_multi_hop THEN path_rank ELSE 0 END,
                 path_score DESC,
                 hops ASC
        WITH target,
             collect({{
                node_names: node_names,
                relations: relations,
                hop_count: hops,
                score: path_score,
                path_rank: path_rank
             }})[0] AS best
        RETURN target.job_id AS target_job_id,
               target.title AS target_title,
               best.node_names AS node_names,
               best.relations AS relations,
               best.hop_count AS hop_count,
               best.score AS score,
               best.path_rank AS path_rank
        ORDER BY CASE WHEN $prefer_multi_hop THEN path_rank ELSE 0 END,
                 score DESC,
                 hop_count ASC,
                 target_title ASC
        LIMIT $limit
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            return session.run(
                query,
                job_id=job_id,
                target_job_id=target_job_id,
                max_hops=safe_hops,
                candidate_limit=candidate_limit,
                prefer_multi_hop=prefer_multi_hop,
                limit=limit,
            ).data()

    def _multi_hop_score_rows(self, job_id: str | None, *, max_hops: int = 3) -> list[dict[str, object]]:
        if not job_id:
            return []
        records = self._multi_hop_records(job_id, max_hops=max_hops, limit=200)
        return [{"job_id": record["target_job_id"], "score": record["score"]} for record in records]

    def multi_hop_reasoning(
        self,
        job_id: str,
        *,
        target_job_id: str | None = None,
        max_hops: int = 3,
        limit: int = 10,
    ) -> list[ReasoningPath]:
        records = self._multi_hop_records(
            job_id,
            target_job_id=target_job_id,
            max_hops=max_hops,
            limit=limit,
            prefer_multi_hop=True,
        )
        paths: list[ReasoningPath] = []
        for record in records:
            node_names = [item for item in record["node_names"] if item]
            relations = [item for item in record["relations"] if item]
            paths.append(
                ReasoningPath(
                    target_job_id=record["target_job_id"],
                    target_title=record["target_title"] or "",
                    hop_count=record["hop_count"] or 0,
                    score=record["score"] or 0.0,
                    node_names=node_names,
                    relations=relations,
                    explanation=self._path_explanation(node_names, relations),
                )
            )
        return paths

    def job_graph(self, job_id: str) -> GraphResponse | None:
        source_query = """
        MATCH (j:Job {job_id: $job_id})
        RETURN j.job_id AS job_id,
               j.title AS job_title,
               properties(j) AS job_props
        LIMIT 1
        """
        neighbor_query = """
        MATCH (j:Job {job_id: $job_id})
        MATCH (j)-[r]-(n)
        WHERE NOT n:Job AND type(r) <> 'SIMILAR_TO'
        RETURN
            type(r) AS relation,
            labels(n)[0] AS target_label,
            coalesce(n.name, n.title, n.job_id) AS target_name,
            n.job_id AS target_job_id,
            properties(n) AS target_props,
            properties(r) AS relation_props
        ORDER BY
            CASE type(r)
                WHEN 'REQUIRES_SKILL' THEN 1
                WHEN 'LOCATED_IN' THEN 2
                WHEN 'IN_INDUSTRY' THEN 3
                WHEN 'POSTED_BY' THEN 4
                WHEN 'HAS_BENEFIT' THEN 5
                WHEN 'HAS_KEYWORD' THEN 6
                ELSE 7
            END,
            target_name ASC
        LIMIT 80
        """
        similar_query = """
        MATCH (j:Job {job_id: $job_id})-[r:SIMILAR_TO]-(n:Job)
        RETURN
            type(r) AS relation,
            labels(n)[0] AS target_label,
            coalesce(n.title, n.job_id) AS target_name,
            n.job_id AS target_job_id,
            properties(n) AS target_props,
            properties(r) AS relation_props
        ORDER BY coalesce(r.score, 0.0) DESC, target_name ASC
        LIMIT 16
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            source = session.run(source_query, job_id=job_id).single()
            if source is None:
                return None
            records = session.run(neighbor_query, job_id=job_id).data()
            records.extend(session.run(similar_query, job_id=job_id).data())

        source_id = f"job:{job_id}"
        nodes = [
            GraphNode(
                id=source_id,
                label="Job",
                name=source["job_title"],
                properties=self._compact_graph_properties("Job", source["job_props"]),
            )
        ]
        edges: list[GraphEdge] = []
        for record in records:
            if not record["target_label"] or not record["target_name"]:
                continue
            target_id = (
                f"job:{record['target_job_id']}"
                if record["target_label"] == "Job" and record.get("target_job_id")
                else self._node_id(record["target_label"], record["target_name"])
            )
            nodes.append(
                GraphNode(
                    id=target_id,
                    label=record["target_label"],
                    name=record["target_name"],
                    properties=self._compact_graph_properties(record["target_label"], record["target_props"]),
                )
            )
            edges.append(
                GraphEdge(
                    source=source_id,
                    target=target_id,
                    relation=record["relation"],
                    properties=self._compact_graph_properties("Relation", record["relation_props"]),
                )
            )
        unique_nodes = {node.id: node for node in nodes}
        return GraphResponse(job_id=job_id, nodes=list(unique_nodes.values()), edges=edges)

    def top_skills(self, limit: int = 20) -> list[TopItem]:
        return self._top_entities("Skill", "REQUIRES_SKILL", limit)

    def graph_insights(self, limit: int = 10) -> GraphInsightsResponse:
        return GraphInsightsResponse(
            top_skills=self.top_skills(limit=limit),
            top_cities=self._top_entities("City", "LOCATED_IN", limit),
            top_industries=self._top_entities("Industry", "IN_INDUSTRY", limit),
            top_benefits=self._top_entities("Benefit", "HAS_BENEFIT", limit),
        )

    def _top_entities(self, label: str, relation: str, limit: int) -> list[TopItem]:
        query = f"""
        MATCH (:Job)-[:{relation}]->(n:{label})
        RETURN n.name AS name, count(*) AS count
        ORDER BY count DESC, name ASC
        LIMIT $limit
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, limit=limit).data()
        return [TopItem(name=record["name"], count=record["count"]) for record in records]
