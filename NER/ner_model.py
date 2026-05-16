import json
import os
import asyncio
import aiohttp
from tqdm import tqdm

# ==================== 配置 ====================
INPUT_FILE = r"D:\work\Job-Recommendation-System\NER\jobs_align.json"
OUTPUT_FILE = r"D:\work\Job-Recommendation-System\NER\ner_model_result.json"

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
API_BASE = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

SCHEMA = ["SKILL", "DEGREE", "MAJOR", "RESPONSIBILITY", "COMPANY", "LOCATION", "BENEFIT", "WORKTIME"]

MAX_CONCURRENT = 10
RETRY_TIMES = 3

SYSTEM_PROMPT = f"""你是一个命名实体识别专家。请从给定的职位信息中提取以下类型的实体：
{", ".join(SCHEMA)}。
要求：
1. 输出一个 JSON 数组，每个元素为 {{"entity": "实体类型", "word": "实体词"}}。
2. 实体词必须原样来自原文，不要修改或缩写。
3. 输入可能包含中文和英文。
4. 不要输出任何解释或代码块标记，只输出纯 JSON 字符串。
"""

# ==================== 工具函数 ====================
async def call_deepseek(session, semaphore, text, retry=RETRY_TIMES):
    """异步调用 DeepSeek API，返回实体列表"""
    url = f"{API_BASE}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"职位信息：\n{text}"}
        ],
        "temperature": 0.0,
        "max_tokens": 2048
    }

    for attempt in range(1, retry + 1):
        async with semaphore:
            try:
                async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"].strip()
                        # 尝试解析 JSON，失败则返回空
                        try:
                            entities = json.loads(content)
                            if isinstance(entities, list):
                                return entities
                        except json.JSONDecodeError:
                            print(f"JSON 解析失败，原始内容: {content[:200]}")
                        return []
                    elif resp.status == 429:
                        print("速率限制，等待 10 秒...")
                        await asyncio.sleep(10)
                        continue
                    else:
                        error_text = await resp.text()
                        print(f"API 错误 {resp.status}: {error_text[:200]}")
            except Exception as e:
                print(f"请求异常 (尝试 {attempt}): {e}")
            if attempt < retry:
                await asyncio.sleep(2 ** attempt)
    return []


async def process_jobs(jobs):
    """异步处理所有职位，保持原始索引"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT)

    async with aiohttp.ClientSession(connector=connector) as session:
        # 创建任务列表，并记录每个任务的原始索引
        tasks = []
        for idx, job in enumerate(jobs):
            jd = job.get("jobDescription", "").strip()
            tags = job.get("jobTags", "").strip()

            if not jd and not tags:
                # 直接赋予空列表，不发起 API 请求
                tasks.append((idx, asyncio.sleep(0)))  # 占位任务
            else:
                combined_text = ""
                if tags:
                    combined_text += f"职位标签：{tags}\n"
                if jd:
                    combined_text += f"职位描述：{jd}"
                tasks.append((idx, call_deepseek(session, semaphore, combined_text)))

        # 执行任务并收集结果
        for idx, coro in tqdm(tasks, desc="实体抽取中"):
            if coro is asyncio.sleep(0):  # 占位任务
                jobs[idx]["namedEntity"] = []
            else:
                entities = await asyncio.create_task(coro)
                jobs[idx]["namedEntity"] = entities

    return jobs


# ==================== 主流程 ====================
async def main():
    if not API_KEY:
        raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")

    print("正在加载数据...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"共 {len(jobs)} 条数据，开始抽取...")
    jobs = await process_jobs(jobs)

    print("正在保存结果...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"完成！结果已保存至 {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())