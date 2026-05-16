# NED — 实体消歧模块

对 NER 抽取结果进行消歧（Named Entity Disambiguation），将不同表述的同一实体归并为统一标准词。

提供两条**独立并行**的消歧路径，按需选择。

---

## 路径一：传统方法

规则词典 + 字符串聚类，无需大模型，运行速度快。

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1 | 预处理 | 统一小写、去首尾空格、`/` → 空格、合并连续空白 |
| 2 | 规则词典 | 200+ 核心标准词及变体（技能、学历、专业），仅在同 entity 类型内匹配 |
| 3 | 字符串聚类 | 编辑距离 + 阈值 0.85 贪心聚类 |

```bash
python kg/ned/main.py
```

## 路径二：直接大模型消歧

直接将实体列表发送给 DeepSeek-V4-Flash 进行消歧，不分步聚类，一步到位。

需要设置环境变量：

```bash
export DEEPSEEK_API_KEY=your_key_here
# 可选：export DEEPSEEK_BASE_URL=https://api.deepseek.com
# 可选：export NED_LLM_MODEL=deepseek-chat

python kg/ned/main.py --direct-llm
```

---

**核心原则**（两条路径均遵循）：只在同 entity 类型内消歧（SKILL 只与 SKILL 合并，DEGREE 只与 DEGREE 合并），避免跨类型误归一化。

## 文件结构

```
kg/ned/
├── main.py              # 入口（两条路径统一入口）
├── traditional.py       # 传统消歧器 + 流水线（规则词典 + 字符串聚类）
├── llm_direct.py        # 直接大模型消歧（DeepSeek-V4-Flash）
└── README.md
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input` | `datasets/.../ner_merged_filtered.json` | 输入文件 |
| `--output-dir` | `datasets/.../ned_result/` | 输出目录 |
| `--fuzzy-threshold` | 0.85 | 传统方法字符串聚类阈值 |
| `--direct-llm` | False | 启用直接大模型消歧路径 |
| `--max-batch-size` | 100 | LLM 每批最多实体数 |
| `--context` | AI岗位招聘数据... | LLM 上下文提示 |

## 输出文件

### 传统方法（`datasets/knowledge_graph_result/ned_result/`）

| 文件 | 内容 |
|------|------|
| `step1_preprocessed.json` | 预处理后的实体（归一化结果） |
| `step2_rule_matched.json` | 规则词典命中/未命中详情 |
| `step3_fuzzy_clustered.json` | 字符串聚类合并组 |
| `step4_traditional_result.json` | 传统消歧最终结果 |
| `unresolved_entities.json` | 未解析低频实体（供人工检查） |
| `ned_result.json` | 最终结果 |
| `pipeline_summary.json` | 流水线统计摘要 |

### 直接 LLM 消歧（`--direct-llm`）

| 文件 | 内容 |
|------|------|
| `llm_direct_mapping.json` | DeepSeek 返回的原始分组 |
| `llm_direct_result.json` | 消歧后的记录 |
| `llm_direct_summary.json` | 统计摘要 |

## 输入数据

输入来自 `datasets/knowledge_graph_result/ner_result/ner_merged_filtered.json`，由 `filter_empty.py` 生成：
- 合并 `ner_model_result.json`（主）和 `ner_rule_result.json`（备）
- 过滤掉 `jobDescription` 为空或 `namedEntity` 为 None 的记录

## 扩展词典

编辑 `traditional.py` 中的规则词典：
- `_DEGREE_DICT`：学历标准词
- `_MAJOR_DICT`：专业标准词
- `SKILL_ALIASES`（来自 `kg/taxonomy.py`）：技能标准词
