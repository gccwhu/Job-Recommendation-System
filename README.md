# 基于知识图谱的职位推荐系统

> 让 AI 帮你找到最匹配的工作！

## 选题背景

你是否在为海量招聘信息而头疼？本项目通过构建 **AI 相关岗位知识图谱**，将职位、公司、技能、行业等实体及其关系组织成一张"知识网"，从而实现更精准、更智能的职位推荐。

**核心数据来源**：前程无忧（51job）、猎聘（Liepin）、智联招聘（Zhaopin），覆盖北京、上海、深圳、广州、杭州、成都、南京、武汉 8 大城市，涉及人工智能、机器学习、深度学习、算法、NLP、LLM 等热门关键词。

## 成员分工

| 成员        | 负责模块     | 具体工作                                          |
| ----------- | ------------ | ------------------------------------------------- |
| 🥷 数据爬取 | 多源爬虫     | 51job/猎聘/智联 Selenium 自动化抓取、详情页描述提取 |
| 🧹 数据清洗 | 清洗与去重   | 字段标准化、薪资解析、重复记录过滤                |
| 🕸️ 知识图谱 | 图谱构建     | Neo4j 实体建模、关系抽取、知识网络构建            |
| ⚡ API 服务 | FastAPI 接口 | 岗位查询、图谱问答、个性化推荐接口                |
| 📊 前端展示 | 可视化       | ECharts 知识图谱可视化、职位匹配界面              |

## 项目进展

| 模块     | 状态      | 说明                                      |
| -------- | --------- | ----------------------------------------- |
| 数据爬取 | ✅ 已完成 | 支持 51job/猎聘/智联多源爬虫，自动抓取详情 |
| 数据清洗 | ✅ 已完成 | 统一字段格式，去重后 166 条有效记录       |
| 知识图谱 | ✅ 已完成 | 实体抽取、关系建模、Neo4j 同步            |
| API 服务 | ✅ 已完成 | FastAPI 查询、推荐、子图接口              |
| 前端展示 | ✅ 已完成 | 推荐表单、推荐结果、ECharts 子图展示      |

## 仓库结构

```text
.
├── job_kg/                     # 知识图谱推荐后端
│   ├── api.py
│   ├── config.py
│   ├── graph.py
│   ├── models.py
│   ├── repository.py
│   ├── service.py
│   └── taxonomy.py
├── data_pipeline/              # 数据抓取与清洗流水线
│   ├── crawler/
│   │   └── jobsdb.py
│   ├── config.py
│   ├── main.py
│   ├── processor.py
│   └── requirements.txt
├── datasets/                   # 数据产物目录
│   ├── raw/
│   │   └── jobs_raw.json
│   ├── interim/
│   │   └── jobs_cleaned.json
│   └── processed/
│       └── jobs.json
├── frontend/                   # 前端页面与静态依赖
│   ├── index.html
│   └── vendor/
├── scripts/                    # Neo4j 运维与导入脚本
│   ├── import_neo4j.py
│   ├── install_neo4j_launchd.sh
│   └── neo4j-java-runner.sh
├── docs/
│   └── repository-structure.md
├── Makefile
├── pyproject.toml
├── requirements.txt
└── README.md
```

更详细的结构说明见 `docs/repository-structure.md`。

## 快速上手

```bash
pip install -r requirements.txt
```

也可以直接使用仓库根目录命令：

```bash
make install
```

如需重新抓取数据：

```bash
python -m data_pipeline
```

或：

```bash
make crawl
```

原生安装并启动 Neo4j：

```bash
brew install neo4j
neo4j-admin dbms set-initial-password <your-password>
bash scripts/install_neo4j_launchd.sh
```

配置连接、导入图谱并启动 API：

```bash
cp .env.example .env
# 编辑 .env，把 NEO4J_PASSWORD 改成你设置的密码
python scripts/import_neo4j.py
uvicorn job_kg.api:app --reload
```

或使用：

```bash
make import-graph
make run-api
```

浏览器访问：`http://127.0.0.1:8000/`。Neo4j 浏览器地址：`http://localhost:7474`。如果已经设置过初始密码，跳过 `neo4j-admin dbms set-initial-password <your-password>`。

## 输出字段一览

| 字段                      | 说明                   |
| ------------------------- | ---------------------- |
| `jobName`                 | 职位名称                             |
| `companyName`             | 公司名称                             |
| `jobAreaString`           | 工作地点                             |
| `degreeString`            | 学历要求                             |
| `workYearString`          | 工作经验                             |
| `jobTags`                 | 岗位标签（技能 / 方向 / 福利混合）   |
| `jobDescribe`             | 完整岗位描述                         |
| `companyTypeString`       | 公司类型（国企 / 民营等）            |
| `companySizeString`       | 公司规模                             |
| `industryType1Str`        | 所属行业                             |
| `salaryMin` / `salaryMax` | 薪资范围（k/月）                     |

## 下一步

- [x] 基于图谱的职位推荐算法
- [x] FastAPI 接口
- [x] ECharts 知识图谱可视化界面

## API 示例

查询系统统计：

```bash
curl http://127.0.0.1:8000/stats
```

按条件查询岗位：

```bash
curl "http://127.0.0.1:8000/jobs?city=上海&skills=机器学习&min_salary=10"
```

基于用户画像推荐岗位：

```bash
curl -X POST http://127.0.0.1:8000/recommend/profile \
  -H "Content-Type: application/json" \
  -d '{
    "skills": ["Python", "PyTorch", "机器学习"],
    "desired_city": "上海",
    "min_salary": 10,
    "top_k": 5
  }'
```

查询某个岗位的一跳知识图谱：

```bash
curl http://127.0.0.1:8000/jobs/171714274/graph
```

## 图谱建模

- `Job`：职位节点，包含薪资、学历、经验、来源等属性。
- `Company`：公司节点，与职位通过 `POSTED_BY` 关联。
- `Skill`：技能节点，与职位通过 `REQUIRES_SKILL` 关联。
- `City`：城市节点，与职位通过 `LOCATED_IN` 关联。
- `Industry`：行业节点，与职位通过 `IN_INDUSTRY` 关联。
- `Degree` / `Experience`：学历与经验要求节点。
- `Benefit` / `Keyword`：从混合标签中拆出的福利与补充关键词。

推荐算法通过 Neo4j Cypher 在图数据库内计算：技能匹配优先，其次叠加城市、行业和薪资条件；相似岗位推荐基于共享技能、同城、同行业、同公司关系计算。
