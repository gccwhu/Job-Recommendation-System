"""
过滤空数据脚本

过滤 ner_rule_result.json 和 ner_model_result.json 中
jobDescription 为空或 namedEntity 为 None 的记录，并合并两个 NER 结果
（model 优先，model 为空时回退到 rule）。

用法：python filter_empty.py
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent
RULE_FILE = DATA_DIR / "ner_rule_result.json"
MODEL_FILE = DATA_DIR / "ner_model_result.json"
OUTPUT_FILE = DATA_DIR / "ner_merged_filtered.json"


def is_valid_record(record: dict) -> bool:
    """记录有效：jobDescription 非空且 namedEntity 非空"""
    desc = (record.get("jobDescription") or "").strip()
    if not desc:
        return False
    ents = record.get("namedEntity")
    if ents is None:
        return False
    return True


def merge_entities(model_record: dict, rule_record: dict) -> list[dict]:
    """合并策略：model 优先，model 无实体时回退到 rule"""
    model_ents = model_record.get("namedEntity")
    if model_ents:
        return model_ents
    return rule_record.get("namedEntity") or []


def build_job_key(record: dict) -> str:
    """用 jobName + companyName 作为去重键"""
    return f"{record.get('jobName', '')}|{record.get('companyName', '')}"


def main():
    with open(RULE_FILE, encoding="utf-8") as f:
        rule_data = json.load(f)
    with open(MODEL_FILE, encoding="utf-8") as f:
        model_data = json.load(f)

    # 建立 rule 索引
    rule_index = {build_job_key(r): r for r in rule_data}

    merged = []
    skipped_empty_desc = 0
    skipped_no_entity = 0

    for model_rec in model_data:
        desc = (model_rec.get("jobDescription") or "").strip()
        if not desc:
            skipped_empty_desc += 1
            continue

        key = build_job_key(model_rec)
        rule_rec = rule_index.get(key, {})
        entities = merge_entities(model_rec, rule_rec)

        if not entities:
            skipped_no_entity += 1
            continue

        out = dict(model_rec)
        out["namedEntity"] = entities
        merged.append(out)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"原始 model 记录数: {len(model_data)}")
    print(f"跳过空 jobDescription: {skipped_empty_desc}")
    print(f"跳过无实体记录: {skipped_no_entity}")
    print(f"合并后有效记录数: {len(merged)}")
    print(f"输出文件: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
