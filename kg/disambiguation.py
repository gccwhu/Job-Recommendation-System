from __future__ import annotations

import re


WHITESPACE_RE = re.compile(r"\s+")

PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "，": ",",
        "；": ";",
        "：": ":",
        "—": "-",
        "－": "-",
        "／": "/",
        "、": "/",
    }
)

CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "北京": ("北京市",),
    "上海": ("上海市", "上海-浦东", "上海-浦东新区", "上海浦东", "上海浦东新区"),
    "深圳": ("深圳市",),
    "广州": ("广州市",),
    "杭州": ("杭州市",),
    "成都": ("成都市",),
    "南京": ("南京市",),
    "武汉": ("武汉市",),
    "宜昌": ("宜昌市",),
    "远程办公": ("远程", "remote", "居家办公"),
}

INDUSTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "电子/半导体/集成电路": ("电子技术/半导体/集成电路",),
    "通信/电信": ("通信/电信/网络设备", "通信/电信运营、增值服务"),
    "计算机软件/服务": ("计算机软件", "计算机服务"),
    "专业服务(咨询/人力资源/财会)": ("专业服务(咨询、人力资源、财会)",),
}

BENEFIT_ALIASES: dict[str, tuple[str, ...]] = {
    "五险一金": ("全额五险一金",),
    "六险一金": (),
    "补充医疗保险": ("医疗保险", "子女医疗保险"),
    "带薪年假": (),
    "带薪病假": (),
    "年终奖金": ("年终奖",),
    "绩效奖金": (),
    "项目奖金": (),
    "股票期权": (),
    "定期体检": ("体检",),
    "员工旅游": (),
    "专业培训": ("培训",),
    "交通补贴": (),
    "通讯补贴": (),
    "餐饮补贴": ("有餐补", "餐补"),
    "周末双休": ("双休",),
    "免费班车": (),
    "弹性工作": (),
    "节日福利": ("法定节假",),
    "零食下午茶": ("下午茶",),
    "工伤保险": (),
    "公积金": (),
    "社保": (),
    "包住": (),
    "包吃住": (),
    "出差补贴": (),
    "晋升空间大": (),
    "底薪": (),
    "提成": (),
    "大小周": (),
}

COMPANY_SUFFIX_RE = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团股份有限公司|集团)$"
)


def normalize_text(value: str) -> str:
    text = str(value or "").translate(PUNCTUATION_TRANSLATION).strip()
    return WHITESPACE_RE.sub(" ", text)


def _normalize_lookup(value: str) -> str:
    return normalize_text(value).casefold()


def _normalize_parentheses_spacing(value: str) -> str:
    value = re.sub(r"\(\s*", "(", value)
    return re.sub(r"\s*\)", ")", value)


def _resolve_alias(value: str, alias_map: dict[str, tuple[str, ...]]) -> str:
    normalized = _normalize_lookup(value)
    for canonical, aliases in alias_map.items():
        if normalized == _normalize_lookup(canonical):
            return canonical
        if any(normalized == _normalize_lookup(alias) for alias in aliases):
            return canonical
    return normalize_text(value)


def normalize_city_name(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    resolved = _resolve_alias(cleaned, CITY_ALIASES)
    if resolved != cleaned:
        return resolved

    for canonical, aliases in CITY_ALIASES.items():
        candidates = (canonical,) + aliases
        if any(candidate and _normalize_lookup(candidate) in _normalize_lookup(cleaned) for candidate in candidates):
            return canonical

    parts = [part.strip() for part in re.split(r"[/,;|-]", cleaned) if part.strip()]
    return parts[0] if parts else cleaned


def normalize_company_name(value: str) -> str:
    cleaned = _normalize_parentheses_spacing(normalize_text(value))
    if not cleaned:
        return ""
    normalized = COMPANY_SUFFIX_RE.sub("", cleaned).strip()
    return normalized or cleaned


def normalize_industry_name(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    cleaned = cleaned.replace("，", "/").replace(",", "/")
    return _resolve_alias(cleaned, INDUSTRY_ALIASES)


def normalize_benefit(value: str) -> str | None:
    cleaned = normalize_text(value)
    if not cleaned:
        return None
    normalized = _resolve_alias(cleaned, BENEFIT_ALIASES)
    if normalized in BENEFIT_ALIASES:
        return normalized
    return None
