from __future__ import annotations

import re
from dataclasses import dataclass


SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "人工智能": ("人工智能", "ai", "人工智能算法"),
    "机器学习": ("机器学习", "machine learning", "ml", "机器学习模型"),
    "深度学习": ("深度学习",),
    "大模型": ("大模型", "llm", "openai", "国内大模型"),
    "Agent": ("agent", "agents"),
    "NLP": ("nlp", "文本分类", "实体识别"),
    "计算机视觉": ("计算机视觉", "cv", "图像处理", "图像识别", "图像分割", "医学影像处理", "图像配准"),
    "Python": ("python",),
    "Java": ("java",),
    "C++": ("c++",),
    "SQL": ("sql",),
    "MySQL": ("mysql",),
    "Redis": ("redis",),
    "Docker": ("docker",),
    "Linux": ("linux",),
    "TensorFlow": ("tensorflow",),
    "PyTorch": ("pytorch",),
    "MATLAB": ("matlab",),
    "JavaScript": ("javascript",),
    "HTML/CSS": ("html", "css"),
    "API": ("api",),
    "自动化": ("自动化", "plc"),
    "算法开发": ("算法开发", "算法", "模型训练", "调优"),
    "数据分析": ("数据分析", "大数据"),
    "软件工程": ("软件工程", "系统架构", "技术选型", "需求分析", "数据结构", "编程语言", "编程", "调试", "测试"),
    "物联网": ("物联网", "智能制造"),
    "机器人": ("机器人", "具身机器人"),
    "医学AI": ("医疗", "医学", "生物医学工程", "医疗信息化"),
}

BENEFIT_KEYWORDS = {
    "五险一金",
    "六险一金",
    "五险",
    "补充医疗保险",
    "医疗保险",
    "子女医疗保险",
    "带薪年假",
    "带薪病假",
    "年终奖金",
    "年终奖",
    "绩效奖金",
    "项目奖金",
    "股票期权",
    "定期体检",
    "员工旅游",
    "专业培训",
    "培训",
    "交通补贴",
    "通讯补贴",
    "餐饮补贴",
    "有餐补",
    "餐补",
    "周末双休",
    "双休",
    "免费班车",
    "弹性工作",
    "节日福利",
    "法定节假",
    "零食下午茶",
    "下午茶",
    "工伤保险",
    "公积金",
    "社保",
    "包住",
    "包吃住",
    "出差补贴",
    "晋升空间大",
    "体检",
    "底薪",
    "提成",
    "大小周",
}

STOP_KEYWORDS = {
    "计算机",
    "计算机科学",
    "数学",
    "电子",
    "电子信息",
    "管理",
    "销售",
    "营销",
    "英语",
    "技术交流",
    "方案设计",
    "项目管理",
    "团队建设",
    "团队管理",
    "技术文档",
    "需求调研",
    "指导",
    "方向",
    "产品",
    "专家",
    "工程师",
    "高级",
    "研发",
    "开发",
    "技术研究",
    "解决方案",
}


@dataclass(slots=True)
class ExtractionResult:
    skills: list[str]
    benefits: list[str]
    keywords: list[str]
    raw_tags: list[str]


def _normalize_token(token: str) -> str:
    return re.sub(r"\s+", " ", token.strip()).lower()


def split_tags(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,，/|、;；]+", value)
    result: list[str] = []
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip()
        if cleaned:
            result.append(cleaned)
    return result


def normalize_skill(token: str) -> str | None:
    normalized = _normalize_token(token)
    for canonical, aliases in SKILL_ALIASES.items():
        if normalized == _normalize_token(canonical):
            return canonical
        if any(normalized == _normalize_token(alias) for alias in aliases):
            return canonical
    return None


def extract_entities(title: str, tags: str, description: str = "") -> ExtractionResult:
    raw_tokens = split_tags(tags)
    content = " ".join([title or "", description or ""]).lower()

    skills: set[str] = set()
    benefits: set[str] = set()
    keywords: set[str] = set()

    for token in raw_tokens:
        canonical_skill = normalize_skill(token)
        if canonical_skill:
            skills.add(canonical_skill)
            continue
        if token in BENEFIT_KEYWORDS:
            benefits.add(token)
            continue
        if token not in STOP_KEYWORDS and 1 < len(token) <= 20:
            keywords.add(token)

    for canonical, aliases in SKILL_ALIASES.items():
        all_aliases = (_normalize_token(canonical),) + tuple(_normalize_token(alias) for alias in aliases)
        if any(alias in content for alias in all_aliases):
            skills.add(canonical)

    ordered_raw_tags = sorted(dict.fromkeys(raw_tokens))
    return ExtractionResult(
        skills=sorted(skills),
        benefits=sorted(benefits),
        keywords=sorted(keywords),
        raw_tags=ordered_raw_tags,
    )
