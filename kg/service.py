from __future__ import annotations

from functools import lru_cache

from .config import Settings
from .repository import Neo4jGraphRepository
from .taxonomy import normalize_skill


class KnowledgeGraphService:
    """
    知识图谱业务逻辑服务层 (Service Layer)
    
    架构设计说明：
    作为 API 层 (FastAPI) 和 仓储层 (Repository) 之间的桥梁。
    负责在进行图数据库查询前，对前端传入的用户画像和非标准数据进行“归一化”和“实体对齐”。
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        # 初始化图数据库操作对象，接管所有与 Neo4j 的底层通信
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
        """
        技能实体归一化 (Entity Normalization)
        
        功能：将用户输入的非标准技能（如 "ML", "cv"）统一映射为图谱中的标准词（如 "机器学习", "计算机视觉"）。
        """
        normalized: list[str] = []
        # 【算法优化】：引入哈希集合(Set)记录已处理实体
        # 将原有的 List 遍历去重优化为 O(1) 的哈希查找，整体时间复杂度由 O(N^2) 降至 O(N)
        seen: set[str] = set()

        for skill in skills:
            # 1. 实体对齐：通过 taxonomy 的字典规则获取标准词，若无命中则保留去空后的原词
            canonical = normalize_skill(skill) or skill.strip()
            
            # 2. 脏数据过滤与顺序去重
            if canonical and canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)
                
        return normalized

    def normalize_keywords(self, keywords: list[str]) -> list[str]:
        return self._dedupe(keywords)

    def normalize_benefits(self, benefits: list[str]) -> list[str]:
        return self._dedupe(benefits)


# 【架构优化】：单例模式 (Singleton Pattern) 注入
@lru_cache(maxsize=1)
def create_service() -> KnowledgeGraphService:
    """
    工厂函数：创建并获取 KnowledgeGraphService 的全局单例。
    
    设计意图：
    利用 Python 标准库的 @lru_cache(maxsize=1) 实现极其轻量的单例模式。
    确保在 FastAPI 服务的整个生命周期内：
    1. 环境变量和配置 (Settings) 只加载一次。
    2. 核心图数据库驱动 (Neo4jGraphRepository 底层的 Driver 连接池) 只实例化一次。
    彻底避免每次 API 请求都重新建立 TCP/数据库连接，极大保障高并发场景下的接口毫秒级响应。
    """
    settings = Settings.from_env()
    return KnowledgeGraphService(settings)