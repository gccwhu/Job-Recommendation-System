"""
岗位数据爬虫入口脚本（自动模式）

支持自动检测滑动验证码（可见模式）：
  - 检测到验证码时暂停，等待用户在浏览器窗口手动滑动
  - 滑动完成后自动继续抓取

输出三个文件：
  - datasets/raw/jobs_raw.json           原始数据（含 sensorsdata JSON 和详情链接）
  - datasets/interim/jobs_cleaned.json   清洗后数据（统一字段格式）
  - datasets/processed/jobs.json         最终去重数据（最多 200 条）
"""
import json
import sys
import time
from pathlib import Path

from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format="{time:HH:mm:ss} | {level} | {message}",
    level="INFO",
    colorize=False,
)

from .crawler import JobsdbCrawler, LiepinCrawler, ZhaopinCrawler
from .processor import JobProcessor
from .config import KEYWORDS, CITIES, PAGE_SIZE, MAX_PAGES, MAX_RECORDS


ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_OUTPUT = ROOT_DIR / "datasets/raw/jobs_raw.json"
INTERIM_OUTPUT = ROOT_DIR / "datasets/interim/jobs_cleaned.json"
PROCESSED_OUTPUT = ROOT_DIR / "datasets/processed/jobs.json"


def crawl_source(crawler, keywords, locations, max_records_per_source):
    """通用爬取逻辑"""
    source_results = []
    
    for keyword in keywords:
        if len(source_results) >= max_records_per_source:
            break
            
        for loc_info in locations:
            loc_name, loc_51, loc_lp, loc_zp = loc_info
            if len(source_results) >= max_records_per_source:
                break
            
            for page in range(MAX_PAGES):
                if len(source_results) >= max_records_per_source:
                    break
                    
                page_to_show = page + 1 if not isinstance(crawler, LiepinCrawler) else page
                logger.info(f"正在爬取 {crawler.__class__.__name__}: 关键词={keyword}, 地区={loc_name}, 第 {page_to_show} 页")
                
                # 兼容不同爬虫的参数名
                try:
                    if isinstance(crawler, JobsdbCrawler):
                        raw_jobs = crawler.fetch_jobs(keyword, loc_51, page + 1, PAGE_SIZE)
                    elif isinstance(crawler, LiepinCrawler):
                        raw_jobs = crawler.fetch_jobs(keyword, loc_lp, page)
                    elif isinstance(crawler, ZhaopinCrawler):
                        raw_jobs = crawler.fetch_jobs(keyword, loc_zp, page + 1)
                        
                    if not raw_jobs:
                        logger.info(f"  -> 该页无数据，跳过当前地区")
                        break
                        
                    for raw in raw_jobs:
                        if len(source_results) >= max_records_per_source:
                            break
                            
                        # 抓取详情描述
                        detail_link = raw.get("_detail_link")
                        if detail_link:
                            logger.info(f"  -> 抓取详情: {raw.get('jobName')} @ {raw.get('companyName')}")
                            # 51job 使用 jobId, 其他使用 link
                            desc_param = raw.get("_job_id") if isinstance(crawler, JobsdbCrawler) else detail_link
                            desc = crawler.fetch_detail(desc_param)
                            raw["jobDescribe"] = desc
                        
                        job = crawler.parse_job(raw)
                        if job.get("jobName"):
                            source_results.append(job)
                except Exception as e:
                    logger.error(f"抓取页面出错: {e}")
                    break
                    
    return source_results


def main():
    start = time.time()
    logger.info("=" * 50)
    logger.info("开始多源抓取 AI 相关岗位...")
    logger.info(f"关键词={KEYWORDS}")
    logger.info("=" * 50)

    all_jobs = []
    per_source_limit = MAX_RECORDS // 3
    
    # 2. 猎聘
    try:
        crawler_lp = LiepinCrawler(headless=False)
        jobs_lp = crawl_source(crawler_lp, KEYWORDS, CITIES, per_source_limit)
        all_jobs.extend(jobs_lp)
        crawler_lp.close()
    except Exception as e:
        logger.error(f"猎聘爬取失败: {e}")


    # 1. 前程无忧
    try:
        crawler_51 = JobsdbCrawler(headless=False)
        jobs_51 = crawl_source(crawler_51, KEYWORDS, CITIES, per_source_limit)
        all_jobs.extend(jobs_51)
        crawler_51.close()
    except Exception as e:
        logger.error(f"前程无忧爬取失败: {e}")

    

    # 3. 智联招聘
    try:
        crawler_zp = ZhaopinCrawler(headless=False)
        jobs_zp = crawl_source(crawler_zp, KEYWORDS, CITIES, per_source_limit)
        all_jobs.extend(jobs_zp)
        crawler_zp.close()
    except Exception as e:
        logger.error(f"智联招聘爬取失败: {e}")

    # ========== 输出与处理 ==========
    processor = JobProcessor()
    RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    INTERIM_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # 保存清洗后的中间数据
    with INTERIM_OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)
    logger.info(f"[1/2] 清洗后数据已保存: {INTERIM_OUTPUT} ({len(all_jobs)} 条)")

    # 去重与最终限制
    final_jobs = processor.process(all_jobs)
    final_jobs = final_jobs[:MAX_RECORDS]

    with PROCESSED_OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(final_jobs, f, ensure_ascii=False, indent=2)

    has_desc = sum(1 for j in final_jobs if j.get("jobDescribe"))
    elapsed = time.time() - start
    logger.success(
        f"[2/2] 完成！共 {len(final_jobs)} 条（含 {has_desc} 条完整描述），"
        f"耗时 {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
