# NER 实体抽取模块（招聘领域）

本模块用于对招聘数据进行命名实体识别（NER），支持两种实现方式：

- **规则 + BERT4NER**（`ner_rule.py`）
- **DeepSeek-Flash 大模型**（`ner_model.py`）

---

## 目录结构
```text
NER/
├── jobs_align.json          # 对齐后的招聘数据（原始输入）
├── ner_rule.py              # 规则 + BERT4NER 实体抽取脚本
├── ner_rule_result.json     # 规则模型抽取结果
├── ner_model.py             # DeepSeek-Flash 大模型抽取脚本
├── ner_model_result.json    # 大模型抽取结果
└── models/
    └── bert4ner/            # BERT4NER 预训练模型（本地路径）
```

---

## 输入数据格式（`jobs_align.json`）

每一条数据为一个 JSON 对象，示例结构如下：

```json
{
  "jobName": "招聘自动驾驶感知算法工程师",
  "companyName": "重庆长线智能科技有限责任公司",
  "jobArea": "北京-海淀区",
  "degree": "硕士",
  "experience": "2-4年",
  "jobTags": "",
  "jobDescription": "职位介绍\n岗位职责：\n1、负责开发多传感器融合...",
  "companyType": "",
  "companySize": "",
  "industry": "",
  "salaryMin": 20,
  "salaryMax": 40,
  "source": "liepin",
  "jobId": "",
  "detailLink": "https://..."
}
```

## 输出数据格式（`*_result.json`）

输出在原始数据基础上，新增 namedEntity 字段，结构如下：
```json
{
  "jobName": "...",
  "companyName": "...",
  ...,
  "namedEntity": [
    { "entity": "SKILL", "word": "多传感器融合" },
    { "entity": "SKILL", "word": "BEV" },
    { "entity": "DEGREE", "word": "硕士" },
    { "entity": "MAJOR", "word": "计算机科学" },
    { "entity": "RESPONSIBILITY", "word": "负责开发多传感器融合的智驾感知系统" }
  ]
}
```