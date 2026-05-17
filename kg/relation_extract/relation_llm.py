import json
import re
from time import sleep
from openai import OpenAI

client = OpenAI(
    api_key=" ", 
    base_url=" " # 如果用OpenAI官方则不需要这行
)

def extract_relations(job_description, entities):
    # 提取实体列表中的词，缩减Token，避免大模型被干扰
    entity_words = [item["word"] for item in entities]
    
    prompt = f"""
你是一个专业的知识图谱关系抽取专家。请根据提供的【职位描述】和【实体列表】，抽取实体之间的关系。

【关系定义】（只能抽取以下三种）：
1. Include (包含): 实体A包含实体B，或者实体B属于实体A的一部分。
2. Apply_To (应用于): 实体A被应用于实体B，或者使用实体A来完成实体B。
3. Co_Occurrence (共现/相关): 实体A和实体B在上下文中紧密相关、并列出现或经常一起使用。

【严格约束】
1. 你的输出只能是 JSON 格式的数组，绝对不要输出任何解释性的废话！
2. 提取的 subject 和 object **必须100%原封不动地来源于【实体列表】**，绝对不能自己捏造！
3. relation 只能是 Include, Apply_To, Co_Occurrence 中的一个。

【输入数据】
职位描述：
{job_description}

实体列表：
{json.dumps(entity_words, ensure_ascii=False)}

【输出格式要求】
[
  {{"subject": "实体A", "relation": "Include", "object": "实体B"}},
  {{"subject": "实体C", "relation": "Apply_To", "object": "实体D"}}
]
"""
    
    try:
        # 调用大模型
        response = client.chat.completions.create(
            model="", # 例如 "gpt-3.5-turbo", "deepseek-chat", "qwen-turbo" 等
            messages=[
                {"role": "system", "content": "你是一个严格输出JSON的助手。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1 # 温度调低，减少幻觉
        )
        
        result_text = response.choices[0].message.content
        
        # 清理大模型可能带有的 ```json ``` markdown 标记
        result_text = re.sub(r"```json", "", result_text)
        result_text = re.sub(r"```", "", result_text)
        
        # 解析为Python List
        triplets = json.loads(result_text.strip())
        return triplets
        
    except Exception as e:
        print(f"抽取失败: {e}")
        return []

def process_single_data(data):
    """处理单条数据"""
    print(f"正在处理职位: {data.get('jobName')}")
    
    # 获取需要的字段
    job_desc = data.get("jobDescription", "")
    entities = data.get("namedEntity", [])
    
    if not job_desc or not entities:
        data["relations"] = []
        return data
        
    # 调用LLM进行抽取
    relations = extract_relations(job_desc, entities)
    
    # 将抽取结果加回原数据
    data["relations"] = relations
    
    return data

# ================= 测试运行 =================

# 你的原始数据 (在此省略长文本，使用你提供的JSON)
with open("llm_direct_result.json", "r", encoding="utf-8") as f:
    jobs_data = json.load(f)

# 运行处理
for idx, job in enumerate(jobs_data):
    print(f"\n=== 处理第 {idx+1} 条数据 ===")
    processed_job = process_single_data(job)
    jobs_data[idx] = processed_job # 更新原列表中的数据
    with open("llm_results.json", "w", encoding="utf-8") as f:
        json.dump(jobs_data, f, ensure_ascii=False, indent=2) # 实时保存，防止中断
    sleep(30) 
