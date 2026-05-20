from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import KnowledgeGraph, NormalizedJob
from .taxonomy import extract_entities

# 类别属性的序数映射，用于后续的偏序比较（如：学历是否达标）
DEGREE_ORDER = {
    "不限": 0,
    "大专": 1,
    "本科": 2,
    "硕士": 3,
    "博士": 4,
}

# 【性能优化】预编译正则表达式，避免在循环中重复编译，降低 CPU 开销
_EXP_RANGE_PATTERN = re.compile(r"(\d+)\s*[-~]\s*(\d+)")
_EXP_PLUS_PATTERN = re.compile(r"(\d+)\+?年")


# =========================================================================
# 🌟 阶段一：数据清洗与实体对齐 (Data Sanitization & Entity Alignment)
# =========================================================================

def normalize_degree(value: str) -> str:
    """
    学历实体归一化。
    将非结构化的招聘文本映射到标准的离散类别中，便于图谱节点合并。
    """
    raw = (value or "").strip()
    if not raw or raw in {"无要求", "不限"}:
        return "不限"
    # 【逻辑优化】改为 elif，一旦命中直接返回，避免冗余的后续判断
    elif "博士" in raw:
        return "博士"
    elif "硕士" in raw:
        return "硕士"
    elif "本科" in raw:
        return "本科"
    elif "大专" in raw:
        return "大专"
    return raw


def normalize_experience(value: str) -> str:
    """工作经验文本归一化"""
    raw = (value or "").strip()
    if not raw or raw in {"无经验", "不限"}:
        return "不限"
    elif "应届" in raw or "在校" in raw:
        return "应届/在校"
    elif "年以上" in raw:
        return raw.replace("年以上", "+年")
    return raw


def parse_experience_lower_bound(value: str) -> int:
    """
    特征工程：提取工作经验的数值下界。
    将 "3-5年" 或 "5年以上" 提取为整数 3 或 5，用于推荐算法中的硬性过滤。
    """
    normalized = normalize_experience(value)
    if normalized in {"不限", "应届/在校"}:
        return 0
    
    # 使用预编译的正则匹配区间，如 "3-5"
    range_match = _EXP_RANGE_PATTERN.search(normalized)
    if range_match:
        return int(range_match.group(1))
        
    # 使用预编译的正则匹配下限，如 "5+年"
    plus_match = _EXP_PLUS_PATTERN.search(normalized)
    if plus_match:
        return int(plus_match.group(1))
        
    return 0


def degree_meets(user_degree: str | None, job_degree: str) -> bool:
    """评估用户学历是否满足岗位要求（基于预定义的偏序关系）"""
    if not user_degree:
        return True
    return DEGREE_ORDER.get(normalize_degree(user_degree), 0) >= DEGREE_ORDER.get(job_degree, 0)


def experience_meets(user_experience: str | None, job_experience: str) -> bool:
    """评估用户经验是否满足岗位要求"""
    if not user_experience:
        return True
    return parse_experience_lower_bound(user_experience) >= parse_experience_lower_bound(job_experience)


# =========================================================================
# 🌟 阶段二：哈希与唯一性保障 (Idempotency & Unique Identifiers)
# =========================================================================

def _stable_job_id(item: dict[str, Any]) -> str:
    """
    【架构设计】生成幂等（Idempotent）的稳定主键 ID。
    依据：职位名 + 公司名 + 城市 拼接后的 MD5 散列值。
    意义：防止多次运行清洗流水线时，同一条数据在图谱中产生重复的冗余节点。
    """
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
    """生成全局唯一的图节点标识符，格式：标签名:MD5前12位"""
    digest = hashlib.md5(f"{label}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"{label.lower()}:{digest}"


# =========================================================================
# 🌟 阶段三：内存图谱构建 (In-Memory Graph Construction)
# =========================================================================

def load_source_jobs(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_jobs(raw_jobs: Iterable[dict[str, Any]]) -> list[NormalizedJob]:
    """ETL-Transform 核心：将非结构化字典转换为强类型的数据类 (Dataclass)"""
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
        
        # 调用外挂的 NLP 抽取模块（NER），提取技能、福利和关键词
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
    """
    核心图计算构造器：将离散的岗位对象映射为图论中的点(Nodes)和边(Edges)。
    同时构建了邻接表(Adjacency List)和倒排索引(Inverted Index)，
    为后续写入 Neo4j 或在内存中直接做多跳推理打下基础。
    """
    job_map: dict[str, NormalizedJob] = {}
    nodes: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    
    # 构建倒排索引（Inverted Index）：例如 "Python" -> [job_id_1, job_id_2]
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
        """注册节点，确保唯一性"""
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "name": name,
                "properties": properties,
            }

    def add_edge(source: str, target: str, relation: str, **properties: Any) -> None:
        """注册边（三元组），利用 set 去重"""
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
        
        # 1. 挂载中心节点：Job
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

        # 2. 生成外围实体节点 ID
        company_node_id = _node_id("Company", job.company_name or "未知公司")
        city_node_id = _node_id("City", job.city_name)
        industry_node_id = _node_id("Industry", job.industry_name)
        degree_node_id = _node_id("Degree", job.degree_name)
        experience_node_id = _node_id("Experience", job.experience_name)

        # 3. 挂载外围实体节点
        add_node(company_node_id, "Company", job.company_name or "未知公司", company_type=job.company_type, company_size=job.company_size)
        add_node(city_node_id, "City", job.city_name)
        add_node(industry_node_id, "Industry", job.industry_name)
        add_node(degree_node_id, "Degree", job.degree_name)
        add_node(experience_node_id, "Experience", job.experience_name)

        # 4. 构建拓扑关系边 (Topology Construction)
        add_edge(job_node_id, company_node_id, "POSTED_BY")
        add_edge(job_node_id, city_node_id, "LOCATED_IN")
        add_edge(job_node_id, industry_node_id, "IN_INDUSTRY")
        add_edge(job_node_id, degree_node_id, "REQUIRES_DEGREE")
        add_edge(job_node_id, experience_node_id, "REQUIRES_EXPERIENCE")
        add_edge(company_node_id, industry_node_id, "BELONGS_TO")

        # 5. 更新倒排索引
        indexes["companies"][job.company_name].add(job.job_id)
        indexes["cities"][job.city_name].add(job.job_id)
        indexes["industries"][job.industry_name].add(job.job_id)
        indexes["degrees"][job.degree_name].add(job.job_id)
        indexes["experiences"][job.experience_name].add(job.job_id)

        # 6. 处理动态长度实体 (Skills, Benefits, Keywords)
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