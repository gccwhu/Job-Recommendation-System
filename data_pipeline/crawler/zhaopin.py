"""智联招聘爬虫（Selenium 版）"""
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


class ZhaopinCrawler:
    """智联招聘爬虫"""

    BASE_URL = "https://sou.zhaopin.com/"

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
        options.add_argument("--window-size=1366,768")
        
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
            try:
                return self._driver.find_element(By.CLASS_NAME, "joblist-box__item").is_displayed()
            except:
                return False

        # 如果没看到职位列表，则可能被拦截
        if not is_job_list_visible():
            current_url = self._driver.current_url
            # 智联常见的拦截标识：包含 passport、login、verify 的 URL
            if "passport" in current_url or "login" in current_url or "verify" in current_url:
                logger.warning(f"检测到智联招聘拦截/登录页 (URL: {current_url})，请在浏览器中完成操作...")
                
                deadline = time.time() + 3600  # 最多等 1 小时
                while time.time() < deadline:
                    time.sleep(3)
                    # 只要看到了职位列表项，就说明通过了
                    if is_job_list_visible():
                        logger.success("检测到职位列表已出现，继续抓取！")
                        return
                    
                    # 打印一下当前在哪，方便用户调试
                    if int(time.time()) % 15 == 0:
                        logger.info(f"仍在等待中... 当前页面: {self._driver.current_url}")

    def fetch_jobs(self, keyword: str, city_code: str = "489", page_num: int = 1) -> List[Dict[str, Any]]:
        """抓取职位列表"""
        self._ensure_driver()
        
        # 智联 URL 格式: https://sou.zhaopin.com/?jl=530&kw=python&p=1
        url = f"{self.BASE_URL}?jl={city_code}&kw={keyword}&p={page_num}"
        
        try:
            self._driver.get(url)
            time.sleep(3)
            
            # 检查登录/验证码拦截
            self._check_interruption()
            
            # 等待列表加载 (时间拉长到 30 秒)
            WebDriverWait(self._driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "joblist-box__item"))
            )
            
            return self._extract_list()
        except Exception as e:
            logger.error(f"[智联] 抓取列表失败: {e}")
            return []

    def _extract_list(self) -> List[Dict[str, Any]]:
        """从列表页提取数据"""
        jobs = []
        try:
            # 尝试多种卡片选择器
            item_selectors = [
                ".joblist-box__item",
                "[class*='joblist-box__item']",
                ".job-card-pc-container",
                "[class*='job-card']"
            ]
            
            items = []
            for sel in item_selectors:
                items = self._driver.find_elements(By.CSS_SELECTOR, sel)
                if items:
                    break
            
            logger.info(f"[智联] 发现 {len(items)} 个职位卡片")
            
            for item in items:
                try:
                    def find_text(container, selectors):
                        for s in selectors:
                            try:
                                el = container.find_element(By.CSS_SELECTOR, s)
                                if el and el.text.strip():
                                    return el.text.strip()
                            except:
                                continue
                        return ""

                    def find_attr(container, selectors, attr):
                        for s in selectors:
                            try:
                                el = container.find_element(By.CSS_SELECTOR, s)
                                val = el.get_attribute(attr)
                                if val:
                                    return val
                            except:
                                continue
                        return ""

                    job_name = find_text(item, [".jobinfo__name", "[class*='jobinfo__name']", "a[title]"])
                    company_name = find_text(item, [".companyinfo__name", "[class*='companyinfo__name']", ".company-name"])
                    salary = find_text(item, [".jobinfo__salary", "[class*='jobinfo__salary']", ".salary"])
                    area = find_text(item, [".jobinfo__other-item", "[class*='jobinfo__other-item']", ".area"])
                    link = find_attr(item, ["a", "[class*='jobinfo__name']", "h2 a"], "href")

                    if not job_name or not company_name:
                        continue
                    
                    job = {
                        "jobName": job_name,
                        "companyName": company_name,
                        "salaryText": salary,
                        "jobAreaString": area,
                        "_detail_link": link,
                        "source": "zhaopin"
                    }
                    jobs.append(job)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[智联] 解析列表异常: {e}")
        return jobs

    def fetch_detail(self, url: str) -> str:
        """抓取详情页描述"""
        self._ensure_driver()
        try:
            self._driver.get(url)
            time.sleep(2)
            
            # 检查登录/验证码拦截
            self._check_interruption()
            
            # 智联详情页选择器
            selectors = [
                ".job-detail",
                ".descript__detail",
                ".pos-info-tit",
                "[class*=job-desc]",
                "[class*=job-detail]",
                ".job-description",
                ".pos-info-content"
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
            logger.error(f"[智联] 抓取详情失败: {url}, {e}")
            return ""

    def parse_job(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """格式化数据"""
        salary_text = raw.get("salaryText", "")
        mn, mx = self._parse_salary(salary_text)
        
        return {
            "jobName": raw.get("jobName", ""),
            "companyName": raw.get("companyName", ""),
            "jobAreaString": raw.get("jobAreaString", ""),
            "degreeString": "",
            "workYearString": "",
            "jobTags": "",
            "jobDescribe": raw.get("jobDescribe", ""),
            "companyTypeString": "",
            "companySizeString": "",
            "industryType1Str": "",
            "salaryMin": mn,
            "salaryMax": mx,
            "source": "zhaopin",
            "_detail_link": raw.get("_detail_link", ""),
        }

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资范围 示例: 15k-30k, 2万-4万"""
        text = text.lower()
        match = re.search(r"(\d+)-(\d+)", text)
        if match:
            mn, mx = int(match.group(1)), int(match.group(2))
            if "万" in text:
                mn *= 10
                mx *= 10
            return mn, mx
        return 0, 0

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
