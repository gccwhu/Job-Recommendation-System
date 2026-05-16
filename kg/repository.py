from __future__ import annotations

import hashlib

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from .config import Settings
from .graph import build_knowledge_graph, degree_meets, experience_meets
from .models import GraphResponse, GraphEdge, GraphNode, JobSummary, KnowledgeGraph, NormalizedJob, RecommendationItem, RecommendationRequest, StatsResponse, TopItem


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

    def sync_graph(self, graph: KnowledgeGraph) -> None:
        try:
            with self.driver.session(database=self.settings.neo4j_database) as session:
                self._create_constraints(session)
                self._replace_graph(session, graph)
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

    @staticmethod
    def _node_id(label: str, name: str) -> str:
        digest = hashlib.md5(f"{label}:{name}".encode("utf-8")).hexdigest()[:12]
        return f"{label.lower()}:{digest}"

    @staticmethod
    def _clean_list(items: list[str | None]) -> list[str]:
        return sorted(item for item in items if item)

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
        query = """
        MATCH (j:Job)
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
             [item IN $keywords WHERE item IN keywords OR item IN skills] AS matched_keywords
        WITH j, c, city, industry, degree, exp, skills, benefits, keywords,
             matched_skills, missing_skills,
             size(matched_skills) * 4.0
             + size(matched_keywords) * 1.5
             + CASE WHEN $desired_city IS NOT NULL AND city.name = $desired_city THEN 3.0 ELSE 0.0 END
             + CASE WHEN $desired_industry IS NOT NULL AND industry.name = $desired_industry THEN 2.5 ELSE 0.0 END
             + CASE WHEN $min_salary IS NOT NULL AND j.salary_max >= $min_salary THEN 1.0 ELSE 0.0 END
             AS score
        WHERE score > 0
          AND (size($skills) = 0 OR size(matched_skills) > 0 OR score >= 4.0)
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
            score AS score
        ORDER BY score DESC, j.salary_mid DESC, size(skills) DESC
        LIMIT $top_k
        """
        params = {
            "skills": profile.skills,
            "keywords": profile.keywords,
            "desired_city": profile.desired_city,
            "desired_industry": profile.desired_industry,
            "min_salary": profile.min_salary,
            "top_k": profile.top_k,
        }
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, **params).data()

        items: list[RecommendationItem] = []
        for record in records:
            summary = self._record_to_summary(record)
            reasons = []
            matched_skills = self._clean_list(record["matched_skills"])
            missing_skills = self._clean_list(record["missing_skills"])
            if matched_skills:
                reasons.append(f"匹配技能 {', '.join(matched_skills)}")
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
            if not reasons:
                reasons.append(f"Cypher 图谱得分 {record['score']:.1f}")
            items.append(
                RecommendationItem(
                    **summary.model_dump(),
                    score=round(record["score"], 2),
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    reasons=reasons,
                )
            )
        return items

    def similar_jobs(self, job_id: str, top_k: int = 10) -> list[RecommendationItem]:
        query = """
        MATCH (base:Job {job_id: $job_id})
        OPTIONAL MATCH (base)-[:POSTED_BY]->(base_company:Company)
        OPTIONAL MATCH (base)-[:LOCATED_IN]->(base_city:City)
        OPTIONAL MATCH (base)-[:IN_INDUSTRY]->(base_industry:Industry)
        OPTIONAL MATCH (base)-[:REQUIRES_SKILL]->(base_skill:Skill)
        WITH base, base_company, base_city, base_industry, collect(DISTINCT base_skill.name) AS base_skills
        MATCH (j:Job)
        WHERE j.job_id <> base.job_id
        OPTIONAL MATCH (j)-[:POSTED_BY]->(c:Company)
        OPTIONAL MATCH (j)-[:LOCATED_IN]->(city:City)
        OPTIONAL MATCH (j)-[:IN_INDUSTRY]->(industry:Industry)
        OPTIONAL MATCH (j)-[:REQUIRES_DEGREE]->(degree:Degree)
        OPTIONAL MATCH (j)-[:REQUIRES_EXPERIENCE]->(exp:Experience)
        OPTIONAL MATCH (j)-[:REQUIRES_SKILL]->(skill:Skill)
        OPTIONAL MATCH (j)-[:HAS_BENEFIT]->(benefit:Benefit)
        OPTIONAL MATCH (j)-[:HAS_KEYWORD]->(keyword:Keyword)
        WITH base, base_company, base_city, base_industry, base_skills,
             j, c, city, industry, degree, exp,
             collect(DISTINCT skill.name) AS skills,
             collect(DISTINCT benefit.name) AS benefits,
             collect(DISTINCT keyword.name) AS keywords
        WITH j, c, city, industry, degree, exp, skills, benefits, keywords,
             [item IN skills WHERE item IN base_skills] AS matched_skills,
             base_company, base_city, base_industry, base_skills
        WITH j, c, city, industry, degree, exp, skills, benefits, keywords, matched_skills, base_skills,
             size(matched_skills) * 3.0
             + CASE WHEN base_city IS NOT NULL AND city.name = base_city.name THEN 2.0 ELSE 0.0 END
             + CASE WHEN base_industry IS NOT NULL AND industry.name = base_industry.name THEN 2.0 ELSE 0.0 END
             + CASE WHEN base_company IS NOT NULL AND c.name = base_company.name THEN 1.0 ELSE 0.0 END
             AS score
        WHERE score > 0
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
            [item IN base_skills WHERE NOT item IN matched_skills] AS missing_skills,
            score AS score
        ORDER BY score DESC, j.salary_mid DESC
        LIMIT $top_k
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, job_id=job_id, top_k=top_k).data()

        items: list[RecommendationItem] = []
        for record in records:
            summary = self._record_to_summary(record)
            matched_skills = self._clean_list(record["matched_skills"])
            missing_skills = self._clean_list(record["missing_skills"])
            reasons = []
            if matched_skills:
                reasons.append(f"共享技能 {', '.join(matched_skills)}")
            if summary.city_name:
                reasons.append(f"同城候选 {summary.city_name}")
            if summary.industry_name:
                reasons.append(f"行业关联 {summary.industry_name}")
            items.append(
                RecommendationItem(
                    **summary.model_dump(),
                    score=round(record["score"], 2),
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    reasons=reasons,
                )
            )
        return items

    def job_graph(self, job_id: str) -> GraphResponse | None:
        query = """
        MATCH (j:Job {job_id: $job_id})
        OPTIONAL MATCH (j)-[r]->(n)
        RETURN
            j.job_id AS job_id,
            j.title AS job_title,
            properties(j) AS job_props,
            type(r) AS relation,
            CASE WHEN n IS NULL THEN NULL ELSE labels(n)[0] END AS target_label,
            CASE WHEN n IS NULL THEN NULL ELSE coalesce(n.name, n.job_id) END AS target_name,
            CASE WHEN n IS NULL THEN NULL ELSE properties(n) END AS target_props
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, job_id=job_id).data()
        if not records:
            return None

        source = records[0]
        source_id = f"job:{job_id}"
        nodes = [
            GraphNode(
                id=source_id,
                label="Job",
                name=source["job_title"],
                properties=source["job_props"],
            )
        ]
        edges: list[GraphEdge] = []
        for record in records:
            if not record["target_label"] or not record["target_name"]:
                continue
            target_id = self._node_id(record["target_label"], record["target_name"])
            nodes.append(
                GraphNode(
                    id=target_id,
                    label=record["target_label"],
                    name=record["target_name"],
                    properties=record["target_props"] or {},
                )
            )
            edges.append(
                GraphEdge(
                    source=source_id,
                    target=target_id,
                    relation=record["relation"],
                    properties={},
                )
            )
        unique_nodes = {node.id: node for node in nodes}
        return GraphResponse(job_id=job_id, nodes=list(unique_nodes.values()), edges=edges)

    def top_skills(self, limit: int = 20) -> list[TopItem]:
        query = """
        MATCH (:Job)-[:REQUIRES_SKILL]->(s:Skill)
        RETURN s.name AS name, count(*) AS count
        ORDER BY count DESC, name ASC
        LIMIT $limit
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            records = session.run(query, limit=limit).data()
        return [TopItem(name=record["name"], count=record["count"]) for record in records]
