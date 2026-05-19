from kg.graph import build_knowledge_graph, normalize_jobs
from kg.repository import Neo4jGraphRepository


def test_normalize_jobs_and_similarity_rows():
    raw_jobs = [
        {
            "_job_id": "job-1",
            "jobName": "机器学习工程师",
            "companyName": "甲公司有限公司",
            "jobAreaString": "上海-浦东新区",
            "industryType1Str": "电子技术/半导体/集成电路",
            "degreeString": "本科",
            "workYearString": "3-5年",
            "salaryMin": 20,
            "salaryMax": 35,
            "jobDescribe": "负责 Python 与 PyTorch 模型训练",
            "jobTags": "python,pytorch,年终奖",
            "companyTypeString": "民营",
            "companySizeString": "150-500人",
        },
        {
            "_job_id": "job-2",
            "jobName": "AI算法工程师",
            "companyName": "乙公司有限责任公司",
            "jobAreaString": "上海市",
            "industryType1Str": "电子/半导体/集成电路",
            "degreeString": "硕士",
            "workYearString": "5年以上",
            "salaryMin": 30,
            "salaryMax": 45,
            "jobDescribe": "负责机器学习与深度学习",
            "jobTags": "机器学习,深度学习,弹性工作",
            "companyTypeString": "民营",
            "companySizeString": "500-1000人",
        },
    ]

    jobs = normalize_jobs(raw_jobs)
    graph = build_knowledge_graph(jobs)

    assert jobs[0].company_name == "甲公司"
    assert jobs[0].city_name == "上海"
    assert jobs[0].industry_name == "电子/半导体/集成电路"
    assert "年终奖金" in jobs[0].benefits
    assert graph.indexes["cities"]["上海"] == {"job-1", "job-2"}

    similarity_rows = Neo4jGraphRepository._similarity_rows(graph)

    assert similarity_rows
    assert similarity_rows[0]["same_city"] is True
    assert similarity_rows[0]["same_industry"] is True
