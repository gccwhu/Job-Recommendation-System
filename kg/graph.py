from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import KnowledgeGraph, NormalizedJob
from .taxonomy import extract_entities

DEGREE_ORDER = {
    "不限": 0,
    "大专": 1,
    "本科": 2,
    "硕士": 3,
    "博士": 4,
}


def normalize_degree(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw in {"无要求", "不限"}:
        return "不限"
    if "博士" in raw:
        return "博士"
    if "硕士" in raw:
        return "硕士"
    if "本科" in raw:
        return "本科"
    if "大专" in raw:
        return "大专"
    return raw


def normalize_experience(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw in {"无经验", "不限"}:
        return "不限"
    if "应届" in raw or "在校" in raw:
        return "应届/在校"
    if "年以上" in raw:
        return raw.replace("年以上", "+年")
    return raw


def parse_experience_lower_bound(value: str) -> int:
    normalized = normalize_experience(value)
    if normalized in {"不限", "应届/在校"}:
        return 0
    range_match = re.search(r"(\d+)\s*[-~]\s*(\d+)", normalized)
    if range_match:
        return int(range_match.group(1))
    plus_match = re.search(r"(\d+)\+?年", normalized)
    if plus_match:
        return int(plus_match.group(1))
    return 0


def degree_meets(user_degree: str | None, job_degree: str) -> bool:
    if not user_degree:
        return True
    return DEGREE_ORDER.get(normalize_degree(user_degree), 0) >= DEGREE_ORDER.get(job_degree, 0)


def experience_meets(user_experience: str | None, job_experience: str) -> bool:
    if not user_experience:
        return True
    return parse_experience_lower_bound(user_experience) >= parse_experience_lower_bound(job_experience)


def _stable_job_id(item: dict[str, Any]) -> str:
    existing = str(item.get("_job_id", "")).strip()
    if existing:
        return existing
    base = "|".join(
        [
            item.get("jobName", "").strip(),
            item.get("companyName", "").strip(),
            item.get("jobAreaString", "").strip(),
        ]
    )
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_salary(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _node_id(label: str, name: str) -> str:
    digest = hashlib.md5(f"{label}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"{label.lower()}:{digest}"


def load_source_jobs(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_jobs(raw_jobs: Iterable[dict[str, Any]]) -> list[NormalizedJob]:
    normalized_jobs: list[NormalizedJob] = []
    for item in raw_jobs:
        job_id = _stable_job_id(item)
        title = _safe_text(item.get("jobName"))
        company_name = _safe_text(item.get("companyName"))
        city_name = _safe_text(item.get("jobAreaString")) or "未知"
        industry_name = _safe_text(item.get("industryType1Str")) or "未知行业"
        degree_name = normalize_degree(_safe_text(item.get("degreeString")))
        experience_name = normalize_experience(_safe_text(item.get("workYearString")))
        salary_min = _safe_salary(item.get("salaryMin"))
        salary_max = _safe_salary(item.get("salaryMax"))
        salary_mid = round((salary_min + salary_max) / 2, 1) if salary_max else float(salary_min)
        description = _safe_text(item.get("jobDescribe"))
        detail_link = _safe_text(item.get("_detail_link"))
        source = _safe_text(item.get("source")) or "51job"
        company_type = _safe_text(item.get("companyTypeString"))
        company_size = _safe_text(item.get("companySizeString"))
        extraction = extract_entities(title=title, tags=_safe_text(item.get("jobTags")), description=description)

        normalized_jobs.append(
            NormalizedJob(
                job_id=job_id,
                title=title,
                company_name=company_name,
                city_name=city_name,
                industry_name=industry_name,
                degree_name=degree_name,
                experience_name=experience_name,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_mid=salary_mid,
                source=source,
                description=description,
                detail_link=detail_link,
                company_type=company_type,
                company_size=company_size,
                skills=extraction.skills,
                benefits=extraction.benefits,
                keywords=extraction.keywords,
                raw_tags=extraction.raw_tags,
            )
        )
    return normalized_jobs


def build_knowledge_graph(jobs: Iterable[NormalizedJob]) -> KnowledgeGraph:
    job_map: dict[str, NormalizedJob] = {}
    nodes: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    indexes: dict[str, dict[str, set[str]]] = {
        "skills": defaultdict(set),
        "benefits": defaultdict(set),
        "keywords": defaultdict(set),
        "cities": defaultdict(set),
        "industries": defaultdict(set),
        "companies": defaultdict(set),
        "degrees": defaultdict(set),
        "experiences": defaultdict(set),
    }

    def add_node(node_id: str, label: str, name: str, **properties: Any) -> None:
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "name": name,
                "properties": properties,
            }

    def add_edge(source: str, target: str, relation: str, **properties: Any) -> None:
        key = (source, target, relation)
        if key in seen_edges:
            return
        seen_edges.add(key)
        payload = {
            "source": source,
            "target": target,
            "relation": relation,
            "properties": properties,
        }
        edges.append(payload)
        adjacency[source].append(payload)

    for job in jobs:
        job_map[job.job_id] = job
        job_node_id = f"job:{job.job_id}"
        add_node(
            job_node_id,
            "Job",
            job.title,
            job_id=job.job_id,
            company_name=job.company_name,
            city_name=job.city_name,
            industry_name=job.industry_name,
            degree_name=job.degree_name,
            experience_name=job.experience_name,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_mid=job.salary_mid,
            source=job.source,
            detail_link=job.detail_link,
            company_type=job.company_type,
            company_size=job.company_size,
        )

        company_node_id = _node_id("Company", job.company_name or "未知公司")
        city_node_id = _node_id("City", job.city_name)
        industry_node_id = _node_id("Industry", job.industry_name)
        degree_node_id = _node_id("Degree", job.degree_name)
        experience_node_id = _node_id("Experience", job.experience_name)

        add_node(company_node_id, "Company", job.company_name or "未知公司", company_type=job.company_type, company_size=job.company_size)
        add_node(city_node_id, "City", job.city_name)
        add_node(industry_node_id, "Industry", job.industry_name)
        add_node(degree_node_id, "Degree", job.degree_name)
        add_node(experience_node_id, "Experience", job.experience_name)

        add_edge(job_node_id, company_node_id, "POSTED_BY")
        add_edge(job_node_id, city_node_id, "LOCATED_IN")
        add_edge(job_node_id, industry_node_id, "IN_INDUSTRY")
        add_edge(job_node_id, degree_node_id, "REQUIRES_DEGREE")
        add_edge(job_node_id, experience_node_id, "REQUIRES_EXPERIENCE")
        add_edge(company_node_id, industry_node_id, "BELONGS_TO")

        indexes["companies"][job.company_name].add(job.job_id)
        indexes["cities"][job.city_name].add(job.job_id)
        indexes["industries"][job.industry_name].add(job.job_id)
        indexes["degrees"][job.degree_name].add(job.job_id)
        indexes["experiences"][job.experience_name].add(job.job_id)

        for skill in job.skills:
            node_id = _node_id("Skill", skill)
            add_node(node_id, "Skill", skill)
            add_edge(job_node_id, node_id, "REQUIRES_SKILL")
            indexes["skills"][skill].add(job.job_id)

        for benefit in job.benefits:
            node_id = _node_id("Benefit", benefit)
            add_node(node_id, "Benefit", benefit)
            add_edge(job_node_id, node_id, "HAS_BENEFIT")
            indexes["benefits"][benefit].add(job.job_id)

        for keyword in job.keywords:
            node_id = _node_id("Keyword", keyword)
            add_node(node_id, "Keyword", keyword)
            add_edge(job_node_id, node_id, "HAS_KEYWORD")
            indexes["keywords"][keyword].add(job.job_id)

    return KnowledgeGraph(
        jobs=job_map,
        nodes=nodes,
        edges=edges,
        adjacency=dict(adjacency),
        indexes=indexes,
    )


def load_graph_from_file(path: Path) -> KnowledgeGraph:
    return build_knowledge_graph(normalize_jobs(load_source_jobs(path)))
