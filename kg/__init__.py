"""基于知识图谱的职位推荐系统后端包。"""

from .config import Settings
from .service import create_service

__all__ = ["Settings", "create_service"]
