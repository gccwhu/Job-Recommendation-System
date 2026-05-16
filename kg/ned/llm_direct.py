"""
直接大模型消歧模块

直接将实体列表发送给 DeepSeek-V4-Flash 进行消歧，
不经过 Sentence-BERT 聚类预处理。

策略：按 entity 类型分批，每批不超过 max_batch_size 个实体，
让模型直接输出合并映射。

环境变量：
  DEEPSEEK_API_KEY   — API Key（必需）
  DEEPSEEK_BASE_URL  — API 地址（默认 https://api.deepseek.com）
  NED_LLM_MODEL      — 模型名（默认 deepseek-chat，即 deepseek-v4-flash）
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger


def _call_deepseek(messages: list[dict], model: str = "") -> str:
    """调用 DeepSeek API（OpenAI 兼容接口）"""
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY", "your_api_key_here")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not model:
        model = os.getenv("NED_LLM_MODEL", "deepseek-chat")

    if not api_key:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")

    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


SYSTEM_PROMPT = """\
你是招聘领域的实体消歧专家。你的任务是将同一类型下的实体进行归并：
- 将表述不同但含义相同的实体合并为一个标准词（如 "Python编程" 和 "Python"）
- 将含义不同的实体保持独立（如 "机器学习" 和 "深度学习" 是不同实体）
- 标准词应选择最简洁、最常用的形式
- 只合并你有把握的，不确定的保持原样

返回 JSON 格式：
{"groups": [{"canonical": "标准词", "variants": ["变体1", "变体2", ...]}]}
其中 variants 包含 canonical 自身。未被任何 group 包含的实体视为独立实体（自成一组）。"""


def _build_user_prompt(entity_type: str, words: list[str], context: str) -> str:
    return (
        f"实体类型：{entity_type}\n"
        f"上下文：{context}\n\n"
        f"以下是 {len(words)} 个待消歧实体，请归并同义实体：\n"
        + json.dumps(words, ensure_ascii=False)
    )


def _parse_llm_response(raw: str) -> list[dict]:
    """解析 LLM 返回的 groups 列表"""
    result = json.loads(raw)
    groups = result.get("groups", [])
    # 校验结构
    valid = []
    for g in groups:
        canon = g.get("canonical", "").strip()
        variants = g.get("variants", [])
        if canon and variants:
            valid.append({"canonical": canon, "variants": variants})
    return valid


def direct_llm_disambiguate(
    records: list[dict],
    context: str = "AI岗位招聘数据，实体来自职位描述",
    max_batch_size: int = 100,
) -> tuple[dict[str, dict[str, str]], dict[str, list[dict]]]:
    """
    直接用 DeepSeek-V4-Flash 对所有实体做消歧。

    参数：
        records:          NER 记录列表（需含 namedEntity 字段）
        context:          提供给模型的上下文
        max_batch_size:   每批最多发送的实体数

    返回：
        (mapping, raw_groups)
        mapping:     { entity_type: { word: canonical } }
        raw_groups:  { entity_type: [group, ...] } 原始分组结果
    """
    # 按类型统计所有唯一实体
    type_entities: dict[str, list[str]] = defaultdict(list)
    type_freq: dict[str, Counter] = defaultdict(Counter)

    for rec in records:
        for ent in (rec.get("namedEntity") or []):
            word = (ent.get("word") or "").strip()
            etype = ent.get("entity", "")
            if word and etype:
                type_freq[etype][word] += 1

    for etype, freq in type_freq.items():
        # 按频次降序，高频实体排前面
        type_entities[etype] = sorted(freq, key=lambda w: freq[w], reverse=True)

    # 逐类型调用 LLM
    all_mapping: dict[str, dict[str, str]] = {}
    all_raw_groups: dict[str, list[dict]] = {}

    for etype, words in type_entities.items():
        if not words:
            continue

        logger.info(f"[{etype}] 共 {len(words)} 个唯一实体")

        # 分批
        batches = [
            words[i : i + max_batch_size]
            for i in range(0, len(words), max_batch_size)
        ]
        type_mapping: dict[str, str] = {}
        type_groups: list[dict] = []

        for batch_idx, batch in enumerate(batches):
            logger.info(
                f"[{etype}] 批次 {batch_idx + 1}/{len(batches)}，"
                f"发送 {len(batch)} 个实体"
            )
            user_msg = _build_user_prompt(etype, batch, context)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            try:
                t0 = time.time()
                raw = _call_deepseek(messages)
                elapsed = time.time() - t0
                logger.info(f"[{etype}] 批次 {batch_idx + 1} LLM 响应，耗时 {elapsed:.1f}s")

                groups = _parse_llm_response(raw)
                type_groups.extend(groups)

                # 构建映射
                for group in groups:
                    canonical = group["canonical"]
                    for variant in group["variants"]:
                        type_mapping[variant] = canonical

                # 未被映射的实体 → 自映射
                mapped_words = set(type_mapping.keys())
                for w in batch:
                    if w not in mapped_words:
                        type_mapping[w] = w

            except Exception as e:
                logger.error(f"[{etype}] 批次 {batch_idx + 1} 调用失败: {e}")
                # 失败时自映射
                for w in batch:
                    type_mapping.setdefault(w, w)

        all_mapping[etype] = type_mapping
        all_raw_groups[etype] = type_groups

    return all_mapping, all_raw_groups


def apply_direct_llm_mapping(
    records: list[dict],
    mapping: dict[str, dict[str, str]],
) -> list[dict]:
    """将直接 LLM 消歧映射应用到记录上（记录内同类型去重）"""
    results = []
    for rec in records:
        entities = rec.get("namedEntity") or []
        new_entities = []
        seen: set[str] = set()

        for ent in entities:
            word = (ent.get("word") or "").strip()
            etype = ent.get("entity", "")
            if not word or not etype:
                continue

            type_map = mapping.get(etype, {})
            canonical = type_map.get(word, word)

            dedup_key = f"{etype}|{canonical.lower()}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            new_entities.append({"entity": etype, "word": canonical})

        out = dict(rec)
        out["namedEntity"] = new_entities
        results.append(out)

    return results


def run_direct_llm_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    context: str = "AI岗位招聘数据，实体来自职位描述",
    max_batch_size: int = 100,
) -> dict:
    """
    直接大模型消歧流水线（端到端）。

    输出：
        llm_direct_mapping.json   — LLM 返回的原始分组
        llm_direct_result.json    — 消歧后的记录
        llm_direct_summary.json   — 统计摘要
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"加载数据: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        records = json.load(f)
    logger.info(f"共 {len(records)} 条记录")

    t0 = time.time()
    mapping, raw_groups = direct_llm_disambiguate(
        records, context=context, max_batch_size=max_batch_size,
    )
    llm_time = time.time() - t0

    # 保存原始分组
    with open(output_dir / "llm_direct_mapping.json", "w", encoding="utf-8") as f:
        json.dump(raw_groups, f, ensure_ascii=False, indent=2)
    logger.info(f"原始分组已保存 llm_direct_mapping.json")

    # 应用映射
    results = apply_direct_llm_mapping(records, mapping)

    with open(output_dir / "llm_direct_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"消歧结果已保存 llm_direct_result.json")

    # 统计
    total_unique = sum(len(m) for m in mapping.values())
    merged_count = sum(
        1 for m in mapping.values() for k, v in m.items() if k != v
    )
    group_count = sum(len(g) for g in raw_groups.values())

    summary = {
        "input_records": len(records),
        "output_records": len(results),
        "total_unique_entities": total_unique,
        "merged_pairs": merged_count,
        "llm_groups": group_count,
        "time_seconds": round(llm_time, 2),
    }
    with open(output_dir / "llm_direct_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"摘要已保存 llm_direct_summary.json")

    return summary
