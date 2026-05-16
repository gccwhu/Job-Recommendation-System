# 数据目录

本目录只存放数据产物，不存放业务代码。

- `raw/jobs_raw.json`：原始抓取数据
- `interim/jobs_cleaned.json`：清洗后的中间数据
- `processed/jobs.json`：知识图谱与推荐系统使用的最终数据

默认 API 和导入脚本读取 `processed/jobs.json`。
