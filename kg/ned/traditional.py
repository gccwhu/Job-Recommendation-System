"""
传统消歧模块

分层策略：预处理 → 规则词典 → 字符串聚类 → 最终结果
每一步中间结果均保存到输出目录。
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from loguru import logger

from kg.taxonomy import SKILL_ALIASES


# ═══════════════════════════════════════════════════════════════════════════
# 预处理
# ═══════════════════════════════════════════════════════════════════════════

def preprocess(text: str) -> str:
    """归一化：小写、/ → 空格、去首尾空白、合并连续空白"""
    text = text.lower().strip()
    text = text.replace("/", " ")
    text = re.sub(r"\s+", " ", text)
    return text


# ═══════════════════════════════════════════════════════════════════════════
# 规则词典
# ═══════════════════════════════════════════════════════════════════════════

def _build_skill_dict() -> dict[str, str]:
    """从 taxonomy.SKILL_ALIASES 构建 SKILL 类型的变体 → 标准词映射"""
    d: dict[str, str] = {}
    for canonical, aliases in SKILL_ALIASES.items():
        canon_norm = preprocess(canonical)
        d[canon_norm] = canonical
        for alias in aliases:
            d[preprocess(alias)] = canonical
    return d


_DEGREE_DICT: dict[str, str] = {
    "硕士": "硕士", "硕士研究生": "硕士", "研究生": "硕士",
    "博士": "博士", "博士研究生": "博士", "phd": "博士",
    "本科": "本科", "大学本科": "本科", "学士": "本科", "bachelor": "本科",
    "大专": "大专", "专科": "大专",
    "高中": "高中", "中专": "中专",
}

_MAJOR_DICT: dict[str, str] = {
    "计算机科学": "计算机科学与技术", "计算机科学与技术": "计算机科学与技术",
    "计算机": "计算机科学与技术", "计算机技术": "计算机科学与技术",
    "软件工程": "软件工程",
    "人工智能": "人工智能",
    "电子信息": "电子信息工程", "电子信息工程": "电子信息工程",
    "电子工程": "电子信息工程",
    "通信工程": "通信工程", "通信": "通信工程",
    "自动化": "自动化",
    "数学": "数学", "应用数学": "数学",
    "物理学": "物理学", "物理": "物理学",
    "统计学": "统计学", "统计": "统计学",
    "机械工程": "机械工程", "机械": "机械工程",
    "电气工程": "电气工程", "电气": "电气工程",
    "数据科学": "数据科学",
    "图像处理": "计算机视觉", "计算机视觉": "计算机视觉",
    "信号处理": "信号与信息处理", "信号与信息处理": "信号与信息处理",
    "生物医学工程": "生物医学工程",
    "声学": "声学",
    "微电子": "微电子学", "微电子学": "微电子学",
    "控制工程": "控制科学与工程", "控制科学与工程": "控制科学与工程",
}

RULE_DICTS: dict[str, dict[str, str]] = {
    "SKILL": _build_skill_dict(),
    "DEGREE": _DEGREE_DICT,
    "MAJOR": _MAJOR_DICT,
}


# ═══════════════════════════════════════════════════════════════════════════
# 字符串聚类
# ═══════════════════════════════════════════════════════════════════════════

def edit_distance_similarity(a: str, b: str) -> float:
    """计算归一化后的序列相似度"""
    return SequenceMatcher(None, preprocess(a), preprocess(b)).ratio()


def cluster_entities(
    words: list[str],
    threshold: float = 0.85,
) -> list[list[str]]:
    """
    贪心聚类（仅同类型内调用）。
    按频次降序，逐个尝试归入已有簇；无法归入则新建簇。
    返回簇列表，每个簇是 [代表词, ...变体]。
    """
    clusters: list[list[str]] = []
    for word in words:
        matched = False
        for cluster in clusters:
            rep = cluster[0]
            if edit_distance_similarity(word, rep) >= threshold:
                cluster.append(word)
                matched = True
                break
        if not matched:
            clusters.append([word])
    return clusters


# ═══════════════════════════════════════════════════════════════════════════
# 传统消歧器
# ═══════════════════════════════════════════════════════════════════════════

class TraditionalDisambiguator:
    """
    分层传统消歧器

    使用方法：
        disambiguator = TraditionalDisambiguator()
        disambiguator.fit(records)
        results = disambiguator.disambiguate_all(records)
        disambiguator.save_unresolved("unresolved.json")
    """

    def __init__(self, fuzzy_threshold: float = 0.85):
        self.fuzzy_threshold = fuzzy_threshold
        self.entity_freq: dict[str, Counter] = defaultdict(Counter)
        self.mapping: dict[str, dict[str, str]] = {}
        self.unresolved: dict[str, list[list[str]]] = {}

    def fit(self, records: list[dict]) -> None:
        """扫描所有记录，构建全局消歧映射"""
        for rec in records:
            for ent in rec.get("namedEntity") or []:
                word = (ent.get("word") or "").strip()
                etype = ent.get("entity", "")
                if word and etype:
                    self.entity_freq[etype][word] += 1

        for etype, freq in self.entity_freq.items():
            type_mapping: dict[str, str] = {}
            rule_dict = RULE_DICTS.get(etype, {})

            # 第一层：规则词典
            unresolved_words: list[str] = []
            for word in freq:
                norm = preprocess(word)
                canonical = rule_dict.get(norm)
                if canonical:
                    type_mapping[word] = canonical
                else:
                    unresolved_words.append(word)

            # 第二层：字符串聚类
            unresolved_words.sort(key=lambda w: freq[w], reverse=True)
            clusters = cluster_entities(unresolved_words, self.fuzzy_threshold)
            for cluster in clusters:
                rep = cluster[0]
                for word in cluster:
                    type_mapping[word] = rep

            self.mapping[etype] = type_mapping

            low_freq_clusters = [
                c for c in clusters
                if len(c) == 1 and freq[c[0]] <= 2 and c[0] not in rule_dict
            ]
            if low_freq_clusters:
                self.unresolved[etype] = low_freq_clusters

    def disambiguate_record(self, record: dict) -> dict:
        """对单条记录做消歧（记录内同类型去重）"""
        entities = record.get("namedEntity") or []
        seen: set[str] = set()
        new_entities: list[dict] = []

        for ent in entities:
            word = (ent.get("word") or "").strip()
            etype = ent.get("entity", "")
            if not word or not etype:
                continue

            type_map = self.mapping.get(etype, {})
            canonical = type_map.get(word, word)

            dedup_key = f"{etype}|{preprocess(canonical)}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            new_entities.append({"entity": etype, "word": canonical})

        out = dict(record)
        out["namedEntity"] = new_entities
        return out

    def disambiguate_all(self, records: list[dict]) -> list[dict]:
        """先 fit 再批量消歧"""
        self.fit(records)
        return [self.disambiguate_record(r) for r in records]

    def save_unresolved(self, path: str | Path) -> None:
        """保存未解析的低频实体簇（JSON），供人工标注"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.unresolved, f, ensure_ascii=False, indent=2)

    def summary(self) -> dict:
        """消歧统计摘要"""
        total_entities = sum(len(c) for c in self.entity_freq.values())
        total_mapped = sum(len(m) for m in self.mapping.values())
        rule_hits = 0
        fuzzy_hits = 0
        for etype, type_map in self.mapping.items():
            rule_dict = RULE_DICTS.get(etype, {})
            for word in type_map:
                if preprocess(word) in rule_dict:
                    rule_hits += 1
                elif type_map[word] != word:
                    fuzzy_hits += 1
        unresolved_count = sum(
            len(clusters) for clusters in self.unresolved.values()
        )
        return {
            "total_unique_entities": total_entities,
            "rule_resolved": rule_hits,
            "fuzzy_merged": fuzzy_hits,
            "unresolved_low_freq": unresolved_count,
            "mapping_size": total_mapped,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 流水线
# ═══════════════════════════════════════════════════════════════════════════

def _save_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    fuzzy_threshold: float = 0.85,
) -> dict:
    """
    执行传统消歧流水线。

    输出目录结构：
        step1_preprocessed.json       — 预处理后的实体（归一化）
        step2_rule_matched.json       — 规则词典命中结果
        step3_fuzzy_clustered.json    — 字符串聚类结果
        step4_traditional_result.json — 传统消歧最终结果
        unresolved_entities.json      — 未解析低频实体
        ned_result.json               — 最终结果
        pipeline_summary.json         — 流水线统计摘要
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 加载数据 ──────────────────────────────────────────────────────────
    logger.info(f"加载数据: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        records = json.load(f)
    logger.info(f"共 {len(records)} 条记录")

    # ── 第一步：预处理 ────────────────────────────────────────────────────
    logger.info("=== 第一步：预处理（归一化）===")
    preprocessed = []
    for rec in records:
        new_ents = []
        for ent in (rec.get("namedEntity") or []):
            word = (ent.get("word") or "").strip()
            if not word:
                continue
            new_ents.append({
                "entity": ent["entity"],
                "word": word,
                "normalized": preprocess(word),
            })
        out = dict(rec)
        out["namedEntity"] = new_ents
        preprocessed.append(out)
    _save_json(preprocessed, output_dir / "step1_preprocessed.json")
    logger.info("预处理完成，已保存 step1_preprocessed.json")

    # ── 第二步：规则词典匹配 ──────────────────────────────────────────────
    logger.info("=== 第二步：规则词典匹配 ===")
    trad = TraditionalDisambiguator(fuzzy_threshold=fuzzy_threshold)
    trad.fit(records)

    rule_details = []
    for rec in records:
        matched = []
        unmatched = []
        for ent in (rec.get("namedEntity") or []):
            word = (ent.get("word") or "").strip()
            etype = ent.get("entity", "")
            if not word:
                continue
            rule_dict = RULE_DICTS.get(etype, {})
            canonical = rule_dict.get(preprocess(word))
            if canonical:
                matched.append({"entity": etype, "original": word, "canonical": canonical})
            else:
                unmatched.append({"entity": etype, "word": word})
        rule_details.append({
            "jobName": rec.get("jobName", ""),
            "companyName": rec.get("companyName", ""),
            "matched": matched,
            "unmatched": unmatched,
        })
    _save_json(rule_details, output_dir / "step2_rule_matched.json")
    logger.info(
        f"规则命中: {sum(len(r['matched']) for r in rule_details)}，"
        f"未命中: {sum(len(r['unmatched']) for r in rule_details)}"
    )

    # ── 第三步：字符串聚类 ────────────────────────────────────────────────
    logger.info("=== 第三步：字符串聚类（编辑距离）===")
    cluster_report = {}
    for etype, type_map in trad.mapping.items():
        groups: dict[str, list[str]] = {}
        for word, canonical in type_map.items():
            groups.setdefault(canonical, []).append(word)
        merged = {k: v for k, v in groups.items() if len(v) > 1}
        cluster_report[etype] = {
            "total_unique": len(type_map),
            "merged_groups": len(merged),
            "groups": merged,
        }
    _save_json(cluster_report, output_dir / "step3_fuzzy_clustered.json")
    logger.info(
        f"字符串聚类完成，共 {sum(v['merged_groups'] for v in cluster_report.values())} 个合并组"
    )

    # ── 第四步：传统消歧最终结果 ──────────────────────────────────────────
    logger.info("=== 第四步：传统消歧最终结果 ===")
    trad_results = trad.disambiguate_all(records)
    _save_json(trad_results, output_dir / "step4_traditional_result.json")

    trad.save_unresolved(output_dir / "unresolved_entities.json")

    trad_summary = trad.summary()
    logger.info(f"  规则命中: {trad_summary['rule_resolved']}")
    logger.info(f"  模糊合并: {trad_summary['fuzzy_merged']}")
    logger.info(f"  未解析低频: {trad_summary['unresolved_low_freq']}")

    # ── 最终结果 ──────────────────────────────────────────────────────────
    _save_json(trad_results, output_dir / "ned_result.json")
    logger.info("最终结果已保存 ned_result.json")

    summary = {
        "input_records": len(records),
        "output_records": len(trad_results),
        "traditional": trad_summary,
    }
    _save_json(summary, output_dir / "pipeline_summary.json")
    logger.info("流水线摘要已保存 pipeline_summary.json")

    return summary
