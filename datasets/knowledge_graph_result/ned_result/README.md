# NED 消歧结果

本目录存放实体消歧（Named Entity Disambiguation）的输出文件，由 `kg/ned/main.py` 生成。

## 传统方法输出

运行 `python kg/ned/main.py` 产生以下文件：

| 文件 | 内容 |
|------|------|
| `step1_preprocessed.json` | 预处理后的实体，每个实体增加 `normalized` 字段（小写、去空格、`/` → 空格） |
| `step2_rule_matched.json` | 规则词典匹配详情。每条记录含 `matched`（命中）和 `unmatched`（未命中）列表 |
| `step3_fuzzy_clustered.json` | 字符串聚类结果。按 entity 类型分组，展示编辑距离 ≥ 0.85 的合并组 |
| `step4_traditional_result.json` | 传统消歧最终结果，实体已归一化并记录内去重 |
| `unresolved_entities.json` | 低频孤立实体（出现 ≤ 2 次且未命中规则词典），供人工检查或大模型处理 |
| `ned_result.json` | 最终结果（与 `step4_traditional_result.json` 相同） |
| `pipeline_summary.json` | 流水线统计摘要（输入/输出记录数、规则命中数、模糊合并数等） |

## 直接大模型消歧输出

运行 `python kg/ned/main.py --direct-llm` 产生以下文件：

| 文件 | 内容 |
|------|------|
| `llm_direct_mapping.json` | DeepSeek 返回的原始分组结果，按 entity 类型组织 |
| `llm_direct_result.json` | 消歧后的记录，实体已归一化并记录内去重 |
| `llm_direct_summary.json` | 统计摘要（唯一实体数、合并对数、LLM 分组数、耗时） |

## 数据格式

每条记录的基本结构：

```json
{
  "jobName": "...",
  "companyName": "...",
  "namedEntity": [
    {"entity": "SKILL", "word": "Python"},
    {"entity": "DEGREE", "word": "硕士"}
  ]
}
```

消歧后 `word` 字段会被替换为标准词，同类型内重复实体被去除。
