import json
from neo4j import GraphDatabase

class KnowledgeGraphBuilder:
    def __init__(self, uri, user, password):
        # 初始化 Neo4j 驱动
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
    def close(self):
        self.driver.close()

    def init_database(self):
        """初始化数据库：创建唯一性约束，防止节点重复创建，极大提升插入速度"""
        with self.driver.session() as session:
            # 保证实体的 name 是唯一的
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
            # 保证职位的 detailLink 是唯一的 (因为 jobId 为空，这里用 link 作为唯一标识)
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (j:Job) REQUIRE j.link IS UNIQUE")
            print("数据库约束初始化完成。")

    def build_graph(self, json_data):
        """主函数：解析 JSON 并导入图谱"""
        with self.driver.session() as session:
            for idx, job in enumerate(json_data):
                print(f"正在导入第 {idx+1} 个职位: {job.get('jobName')}")
                
                # 1. 创建职位节点
                session.execute_write(self._create_job_node, job)
                
                # 2. 创建实体节点，并与职位建立 REQUIRE 关系
                for entity in job.get("namedEntity", []):
                    session.execute_write(self._create_entity_and_link_job, job.get("detailLink"), entity)
                
                # 3. 创建实体之间的关系 (大模型提取的三元组)
                for relation in job.get("relations", []):
                    session.execute_write(self._create_entity_relation, relation)

    @staticmethod
    def _create_job_node(tx, job):
        """Cypher: 创建 Job 节点"""
        query = """
        MERGE (j:Job {link: $link})
        SET j.name = $name,
            j.company = $company,
            j.area = $area,
            j.degree = $degree,
            j.experience = $experience,
            j.salaryMin = $salaryMin,
            j.salaryMax = $salaryMax
        """
        tx.run(query, 
               link=job.get("detailLink"),
               name=job.get("jobName"),
               company=job.get("companyName"),
               area=job.get("jobArea"),
               degree=job.get("degree"),
               experience=job.get("experience"),
               salaryMin=job.get("salaryMin"),
               salaryMax=job.get("salaryMax"))

    @staticmethod
    def _create_entity_and_link_job(tx, job_link, entity):
        """Cypher: 创建实体节点，并将 Job 指向 Entity"""
        label = entity.get("entity", "UNKNOWN")  # 例如 SKILL, MAJOR
        word = entity.get("word", "")
        
        if not word:
            return

        # 注意：Cypher 语言中 Label 不能作为参数($label)传入，必须用字符串拼接
        # 使用 :Entity:{label} 让节点同时拥有基类标签 Entity 和具体标签(如 SKILL)
        query = f"""
        // 1. 创建或找到实体节点
        MERGE (e:Entity {{name: $word}})
        SET e:{label} 
        
        // 2. 找到对应的职位节点
        WITH e
        MATCH (j:Job {{link: $link}})
        
        // 3. 建立关系：职位 -[包含/要求]-> 实体
        MERGE (j)-[:REQUIRE]->(e)
        """
        tx.run(query, word=word, link=job_link)

    @staticmethod
    def _create_entity_and_link_job(tx, job_link, entity):
        """Cypher: 创建实体节点，并根据实体类型动态创建恰当的关系"""
        label = entity.get("entity", "UNKNOWN")  
        word = entity.get("word", "")
        
        if not word:
            return

        # ==========================================
        # 核心修改：建立实体类型到图谱关系类型的映射表
        # ==========================================
        relation_mapping = {
            'COMPANY': 'BELONGS_TO_COMPANY',
            'DEPARTMENT': 'BELONGS_TO_DEPT',
            'LOCATION': 'LOCATED_IN',
            'BENEFIT': 'PROVIDES_BENEFIT',
            'RESPONSIBILITY': 'HAS_RESPONSIBILITY',
            'SKILL': 'REQUIRE_SKILL',
            'MAJOR': 'REQUIRE_MAJOR',
            'DEGREE': 'REQUIRE_DEGREE',
            'WORKTIME': 'REQUIRE_WORKTIME'
        }
        
        # 获取对应的关系名称，如果没有匹配到，兜底使用 RELATED_TO
        rel_type = relation_mapping.get(label, 'RELATED_TO')

        # Cypher 动态拼接：同时注入 Label 变量和 Relation 变量
        query = f"""
        // 1. 创建或找到实体节点
        MERGE (e:Entity {{name: $word}})
        SET e:{label} 
        
        // 2. 找到对应的职位节点
        WITH e
        MATCH (j:Job {{link: $link}})
        
        // 3. 建立语义化关系
        MERGE (j)-[:{rel_type}]->(e)
        """
        tx.run(query, word=word, link=job_link)


if __name__ == "__main__":
    # 1. 读取你的 JSON 数据
    with open("llm_results.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. 连接 Neo4j (请替换为你的实际密码)
    URI = "neo4j+s://a25e42b3.databases.neo4j.io"
    AUTH = ("a25e42b3", "thsCz6IGG9-PxVVDsfvc6Sn-DAavCk8v7bIwhueQSIs")

    # 3. 执行导入
    builder = KnowledgeGraphBuilder(URI, AUTH[0], AUTH[1])
    try:
        builder.init_database()
        builder.build_graph(data)
        print("✅ 知识图谱构建完成！")
    finally:
        builder.close()