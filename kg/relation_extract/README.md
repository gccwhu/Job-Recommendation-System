# 知识图谱关系抽取

## 📝 项目简介
本项目为知识图谱/信息抽取课程的实践作业。主要任务是基于给定的招聘岗位描述（Job Description）和已经识别出的命名实体（Named Entities），从中抽取实体之间的三种预定义关系，以构建后续的知识图谱。

本项目分别采用了**传统NLP级联管线方法**与**LLM大语言模型提示工程方法**进行了对比实现。

### 🎯 目标关系定义
本项目仅提取以下三种核心关系：
1. **Include (包含)**: 实体A包含实体B，或实体B属于实体A的一部分。
2. **Apply_To (应用于)**: 实体A被应用于实体B，或使用实体A来完成实体B。
3. **Co_Occurrence (共现/相关)**: 实体A和实体B在上下文中紧密相关、并列出现或经常一起使用。

---

## 📂 项目目录结构
```text
.

├── relation_extract.py             # 抽取方法一：基于 规则+句法+语义 的传统级联抽取脚本
├── relation_llm.py                 # 抽取方法二：基于 LLM (大语言模型) 的智能抽取脚本
└── README.md                       # 项目说明文档
```

---

## 🧠 方法一：传统级联混合抽取管线 (`relation_exact_1.py`)
该方法采用了一种自底向上的级联过滤策略，兼顾了抽取的**准确率**与**召回率**。系统分为三个层级，逐层处理实体对 (Entity Pair)：

1. **第一层：基于规则与词典 (Rule-based)**
   - 构建了不同关系的触发词典（如：`包括`、`用于`、`及` 等）。
   - 通过正则表达式匹配实体间的固定模式（Pattern），对高置信度的短距离关系进行快速拦截与抽取。
2. **第二层：基于句法依存无向图 (Syntax-based)**
   - 引入 `spaCy` (zh_core_web_trf) 进行依存句法分析。
   - 结合 `networkx` 将句法树转化为无向图，计算两个实体在句法树上的**最短依存路径 (SDP, Shortest Dependency Path)**。
   - 通过判断路径跳数（距离截断）及路径上的依存标签（如 `conj` 并列, `dobj` 动宾, `prep` 介宾等）推断关系。
3. **第三层：基于深度学习零样本语义分类 (Semantic-based)**
   - 作为兜底策略，针对句法难以捕捉的隐含关系，使用 `mDeBERTa-v3-base-mnli-xnli` 零样本分类模型。
   - 采用 Prompt 思想（如 `"[E1]实体A[/E1] 包含 [E2]实体B[/E2]"`）将关系抽取转化为自然语言推理（NLI）分类任务。

---

## 🤖 方法二：大语言模型抽取 (`relation_llm.py`)
该方法利用生成式大语言模型（如通义千问、DeepSeek、GPT-4等）强大的阅读理解能力进行关系抽取。为了克服大模型的“幻觉”问题，采用了以下工程优化：

1. **严格的 Prompt Engineering**: 
   - 明确约束模型只能输出指定的 `Include`、`Apply_To`、`Co_Occurrence` 三种关系。
   - 强制约束三元组的 `subject` 和 `object` 必须原封不动地取自传入的 `entity_list`，严禁模型自行捏造实体。
2. **格式化输出约束**: 要求模型仅输出 JSON Array 格式，并利用正则表达式对返回的 Markdown 标记（如 ` ```json `）进行清洗，保证 100% 的 JSON 解析成功率。
3. **降温处理**: 将 `temperature` 设为 `0.1`，降低模型输出的随机性，提高客观事实提取的稳定性。
4. **流控与持久化**: 加入 `sleep(30)` 防止触发 API 的速率限制 (Rate Limit)，并采用边抽边存的策略防止意外中断导致数据丢失。

---

## ⚙️ 环境依赖与运行说明

### 1. 安装依赖包
请确保使用 Python 3.8+ 环境，并运行以下命令安装依赖：
```bash
pip install spacy torch networkx transformers openai
```

### 2. 下载 spaCy 中文模型 (仅方法一需要)
```bash
python -m spacy download zh_core_web_trf
```

### 3. 运行代码

**运行传统管线方法：**
```bash
python relation_exact_1.py
```
*运行后将在 `extraction_results/` 目录下生成四个步骤的 JSON 结果文件。*

**运行大模型提取方法：**
在使用前，请先在代码中配置您的 `API_KEY` 和 `BASE_URL`：
```python
# 修改 relation_llm.py 中的初始化配置
client = OpenAI(
    api_key="你的API_KEY", 
    base_url="你的BASE_URL" 
)
```
然后运行：
```bash
python relation_llm.py
```
*运行后，结果会追加到原数据的 `relations` 字段，并实时保存在 `llm_results.json` 中。*

---

## 📊 数据格式示例

**输入数据 (`ned_result.json`)**
```json
{
  "jobName": "自动驾驶感知算法工程师",
  "jobDescription": "负责开发多传感器融合的智驾感知系统，基于BEV的视觉检测...",
  "namedEntity": [
    {"entity": "SKILL", "word": "多传感器融合"},
    {"entity": "SKILL", "word": "BEV"},
    {"entity": "SKILL", "word": "视觉检测"}
  ]
}
```

**输出数据 (以 LLM 方法为例)**
会在原 JSON 结构中新增 `relations` 字段：
```json
{
  "jobName": "自动驾驶感知算法工程师",
  "jobDescription": "负责开发多传感器融合的智驾感知系统，基于BEV的视觉检测...",
  "namedEntity": [ ... ],
  "relations": [
    {
      "subject": "BEV",
      "relation": "Apply_To",
      "object": "视觉检测"
    },
    {
      "subject": "多传感器融合",
      "relation": "Apply_To",
      "object": "负责开发多传感器融合的智驾感知系统"
    }
  ]
}
```

