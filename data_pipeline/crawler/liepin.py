"""猎聘爬虫（Selenium 版）"""
import time
import json
import re
from typing import List, Dict, Any

from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


class LiepinCrawler:
    """猎聘招聘爬虫"""

    BASE_URL = "https://www.liepin.com/zhaopin/"

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._driver = None

    def _init_driver(self):
        if self._driver is not None:
            return

        options = Options()
        if self._headless:
            options.add_argument("--headless=new")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--lang=zh-CN")
        options.add_argument("--window-size=1366,768")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        options.add_argument(f"--user-agent={ua}")

        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        
        self._driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => false})"
        })

    def _ensure_driver(self):
        if self._driver is None:
            self._init_driver()

    def _check_interruption(self):
        """检查是否被登录拦截或验证码拦截"""
        if self._headless:
            return

        # 检查是否出现了职位列表的特征元素
        def is_job_list_visible():
            selectors = [
                ".job-list-box",
                "[class*='job-list-box']",
                ".job-card-pc-container",
                "[class*='job-card']"
            ]
            for sel in selectors:
                try:
                    if self._driver.find_element(By.CSS_SELECTOR, sel).is_displayed():
                        return True
                except:
                    continue
            return False

        # 如果没看到职位列表，则可能被拦截
        if not is_job_list_visible():
            current_url = self._driver.current_url
            # 只有确实在登录/验证页，或者页面明显不对时才进入死等
            if "passport" in current_url or "login" in current_url or "captcha" in current_url:
                logger.warning(f"检测到拦截/登录页 (URL: {current_url})，请在浏览器中完成操作...")
                
                deadline = time.time() + 3600  # 最多等 1 小时
                while time.time() < deadline:
                    time.sleep(3)
                    # 只要看到了职位列表，就说明通过了
                    if is_job_list_visible():
                        logger.success("检测到职位列表已出现，继续抓取！")
                        return
                    
                    # 打印一下当前在哪，方便用户调试
                    if int(time.time()) % 15 == 0:
                        logger.info(f"仍在等待中... 当前页面: {self._driver.current_url}")

    def fetch_jobs(self, keyword: str, city: str = "", page_num: int = 0) -> List[Dict[str, Any]]:
        """抓取职位列表"""
        self._ensure_driver()
        
        # 猎聘 URL 示例: https://www.liepin.com/zhaopin/?key=python&city=010&currentPage=0
        url = f"{self.BASE_URL}?key={keyword}&currentPage={page_num}"
        if city:
            url += f"&city={city}"
            
        try:
            self._driver.get(url)
            time.sleep(5) # 增加初始等待
            
            # 检查登录/验证码拦截
            self._check_interruption()
            
            # 等待列表加载 - 尝试多个可能的选择器
            list_selectors = [
                (By.CLASS_NAME, "job-list-box"),
                (By.CSS_SELECTOR, "[class*='job-list-box']"),
                (By.CSS_SELECTOR, ".job-card-pc-container"),
                (By.CSS_SELECTOR, "[class*='job-card']")
            ]
            
            found = False
            for by, sel in list_selectors:
                try:
                    WebDriverWait(self._driver, 10).until(
                        EC.presence_of_element_located((by, sel))
                    )
                    found = True
                    break
                except:
                    continue
            
            if not found:
                logger.warning(f"[猎聘] 页面加载超时，未发现职位列表特征元素")
                return []
            
            time.sleep(2) # 额外等待渲染
            return self._extract_list()
        except Exception as e:
            logger.error(f"[猎聘] 抓取列表失败: {e}")
            return []

    def _extract_list(self) -> List[Dict[str, Any]]:
        """从列表页提取数据 - 根据最新的 DOM 结构重写"""
        jobs = []
        try:
            # 根据截图，最稳妥的卡片定位是 job-detail-box 的父级
            cards = self._driver.find_elements(By.CSS_SELECTOR, "div[class*='job-detail-box']")
            # 如果没找到，尝试更外层的容器
            if not cards:
                cards = self._driver.find_elements(By.CSS_SELECTOR, "div[class^='_40108']")

            logger.info(f"[猎聘] 发现 {len(cards)} 个职位卡片")
            
            for card in cards:
                try:
                    # 1. 职位信息区域 (左侧)
                    job_info_area = card.find_element(By.CSS_SELECTOR, "a[data-nick='job-detail-job-info']")
                    job_name = job_info_area.find_element(By.CSS_SELECTOR, ".ellipsis-1").get_attribute("title") or job_info_area.find_element(By.CSS_SELECTOR, ".ellipsis-1").text
                    detail_link = job_info_area.get_attribute("href")
                    
                    # 薪资通常是 a 标签下特定的 span
                    salary = ""
                    try:
                        # 根据截图，薪资在一个特定的 span 中，通常紧跟在地区后面
                        salary_el = job_info_area.find_element(By.CSS_SELECTOR, "span[class*='E8PWS'], span[class*='salary']")
                        salary = salary_el.text.strip()
                    except:
                        pass

                    # 地区
                    area = ""
                    try:
                        area_el = job_info_area.find_element(By.CSS_SELECTOR, "div[class*='__9nJ'] .ellipsis-1")
                        area = area_el.text.strip()
                    except:
                        pass

                    # 2. 公司信息区域 (右侧)
                    company_name = ""
                    try:
                        comp_area = card.find_element(By.CSS_SELECTOR, "div[data-nick='job-detail-company-info']")
                        company_name = comp_area.find_element(By.CSS_SELECTOR, "span[class*='K6Y1c'], .ellipsis-1").text.strip()
                    except:
                        pass

                    # 3. 标签 (经验、学历)
                    tags = []
                    try:
                        # 经验和学历通常在 job-detail-box 内部的一个特定 div 下
                        tag_els = job_info_area.find_elements(By.CSS_SELECTOR, "div[class*='KeJJy'] span")
                        tags = [t.text.strip() for t in tag_els if t.text.strip()]
                    except:
                        pass

                    if not job_name or not company_name:
                        continue

                    job = {
                        "jobName": job_name,
                        "companyName": company_name,
                        "salaryText": salary,
                        "jobAreaString": area,
                        "jobTags": ",".join(tags),
                        "_detail_link": detail_link,
                        "source": "liepin"
                    }
                    jobs.append(job)
                except Exception as e:
                    continue
        except Exception as e:
            logger.error(f"[猎聘] 解析列表异常: {e}")
        return jobs

    def fetch_detail(self, url: str) -> str:
        """抓取详情页描述"""
        self._ensure_driver()
        try:
            self._driver.get(url)
            time.sleep(2)
            
            # 检查登录/验证码拦截
            self._check_interruption()
            
            # 尝试不同的选择器获取职位描述
            selectors = [
                ".job-description-box .content",
                ".job-intro-container",
                ".main-description",
                "section.job-description",
                "[class*='job-description']",
                "[class*='job-intro']",
                ".job-detail-content"
            ]
            
            for sel in selectors:
                try:
                    el = self._driver.find_element(By.CSS_SELECTOR, sel)
                    if el:
                        return el.text.strip()
                except Exception:
                    continue
            return ""
        except Exception as e:
            logger.error(f"[猎聘] 抓取详情失败: {url}, {e}")
            return ""

    def parse_job(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """格式化数据"""
        salary_text = raw.get("salaryText", "")
        mn, mx = self._parse_salary(salary_text)
        
        return {
            "jobName": raw.get("jobName", ""),
            "companyName": raw.get("companyName", ""),
            "jobAreaString": raw.get("jobAreaString", ""),
            "degreeString": raw.get("degreeString", ""),
            "workYearString": raw.get("workYearString", ""),
            "jobTags": raw.get("jobTags", ""),
            "jobDescribe": raw.get("jobDescribe", ""),
            "companyTypeString": raw.get("companyTypeString", ""),
            "companySizeString": raw.get("companySizeString", ""),
            "industryType1Str": raw.get("industryType1Str", ""),
            "salaryMin": mn,
            "salaryMax": mx,
            "source": "liepin",
            "_detail_link": raw.get("_detail_link", ""),
        }

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资范围"""
        # 示例: 20-40k·14薪, 30-50万
        text = text.lower()
        match = re.search(r"(\d+)-(\d+)", text)
        if match:
            mn, mx = int(match.group(1)), int(match.group(2))
            if "万" in text:
                # 转换为 k
                mn = int(mn * 10 / 12) 
                mx = int(mx * 10 / 12)
            return mn, mx
        return 0, 0

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
