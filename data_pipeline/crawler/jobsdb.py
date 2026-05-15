"""前程无忧爬虫（Selenium + PyQuery，支持可见模式手动过验证码）"""
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


class JobsdbCrawler:
    """前程无忧爬虫（Selenium 版）

    headless=False 时会自动等待用户手动滑动验证码，
    用户在浏览器窗口完成验证后程序自动继续。
    """

    BASE_URL = "https://we.51job.com/pc/search"

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._driver = None

    def _init_driver(self):
        if self._driver is not None:
            return

        options = Options()
        if self._headless:
            options.add_argument("--headless=new")

        # 反反爬配置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--lang=zh-CN")
        options.add_argument("--window-size=1366,768")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_argument(f"--user-agent={ua}")

        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)

        # 注入 JS 隐藏 webdriver 标志
        self._driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = { runtime: {} };
            """
        })

        self._driver.set_page_load_timeout(60)
        self._driver.implicitly_wait(10)

    def _wait_page_ready(self, timeout: int = 20):
        """等待 .joblist-item-job 列表加载完毕"""
        try:
            WebDriverWait(self._driver, timeout).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".joblist-item-job"))
            )
        except Exception:
            pass

    def _is_captcha_page(self) -> bool:
        """通过检测滑动验证码 DOM 元素来判断是否有验证码"""
        try:
            selectors = [
                "#nc_1_n1z",          # 滑动块
                ".nc_wrapper",         # 验证容器
                "[class*=slider-module]",
                "[class*=tcaptcha]",
                ".tcaptcha",
            ]
            for sel in selectors:
                try:
                    el = self._driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _wait_captcha_manual(self):
        """检测到验证码时等待用户手动完成（仅可见模式生效）"""
        if self._headless:
            return

        if not self._is_captcha_page():
            return

        logger.info("检测到滑动验证码，请在浏览器窗口中手动完成滑动...")
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(2)
            if not self._is_captcha_page():
                logger.info("验证已通过，继续抓取！")
                return
            logger.info("仍在等待验证码完成...")
        logger.warning("验证码等待超时（5分钟），强制继续...")

    def _ensure_driver(self):
        if self._driver is None:
            self._init_driver()

    def fetch_jobs(
        self, keyword: str, city: str = "010000", page_num: int = 1, page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """从页面 DOM 提取岗位数据"""
        self._ensure_driver()

        ts = int(time.time())
        url = (
            f"{self.BASE_URL}?api_key=51job&timestamp={ts}&searchType=2"
            f"&keyword={keyword}&jobArea={city}&pageNum={page_num}"
            f"&pageSize={page_size}&ord_field=2&fromType=pc&dibiaId=0"
        )

        try:
            self._driver.get(url)
            self._wait_page_ready()
        except Exception as e:
            logger.warning(f"[前程无忧] 页面加载失败: {e}")
            return []

        # 有验证码则等待用户手动滑动
        self._wait_captcha_manual()
        time.sleep(2)

        jobs = self._extract_from_dom()
        try:
            dom_count = len(self._driver.find_elements(By.CSS_SELECTOR, ".joblist-item-job"))
        except Exception:
            dom_count = 0

        logger.info(
            f"[前程无忧] 关键词={keyword} 城市码={city} 页={page_num} 抓到{len(jobs)}条 / DOM总数={dom_count}"
        )
        
        parsed_jobs = []
        for j in jobs:
            parsed = self.parse_job(j)
            logger.info(f"  -> 抓到岗位: {parsed['jobName']} @ {parsed['companyName']}")
            parsed_jobs.append(parsed)
            
        return parsed_jobs

    def fetch_detail(self, job_id: str) -> str:
        """抓取岗位详情页描述"""
        self._ensure_driver()
        try:
            url = f"https://jobs.51job.com/detail/{job_id}.html"
            self._driver.get(url)
            WebDriverWait(self._driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
            )
            time.sleep(2)

            self._wait_captcha_manual()

            for sel in [
                ".jobDescribe",
                ".job_msg",
                ".job-detail",
                "[class*=describe]",
                "[class*=detail]",
                ".intro-content",
            ]:
                try:
                    el = self._driver.find_element(By.CSS_SELECTOR, sel)
                    text = el.text.strip() if el else ""
                    if len(text) > 50:
                        return text
                except Exception:
                    pass
            return ""
        except Exception as e:
            logger.warning(f"[前程无忧-详情] 抓取失败 {job_id}: {e}")
            return ""

    def _extract_from_dom(self) -> List[Dict[str, Any]]:
        """用 JavaScript 从 DOM 直接提取岗位数据"""
        try:
            raw = self._driver.execute_script("""
                try {
                    const items = document.querySelectorAll('.joblist-item-job');
                    const results = [];
                    for (let i = 0; i < items.length; i++) {
                        const el = items[i];
                        try {
                            const sd_raw = el.getAttribute('sensorsdata');
                            let data = {};
                            if (sd_raw) {
                                try { data = JSON.parse(sd_raw); } catch(e1) {
                                    try {
                                        const textarea = document.createElement('textarea');
                                        textarea.innerHTML = sd_raw;
                                        data = JSON.parse(textarea.value);
                                    } catch(e2) {}
                                }
                            }
                            const salEl = el.querySelector('.sal');
                            const sal = salEl ? salEl.textContent.trim() : (data.jobSalary || '');
                            const compEl = el.querySelector('.cname');
                            const comp = compEl ? compEl.textContent.trim() : (data.companyName || '');
                            const areaEl = el.querySelector('.area .shrink-0');
                            const area = areaEl ? areaEl.textContent.trim() : (data.jobArea || '');
                            const tags = [];
                            el.querySelectorAll('.tag').forEach(t => { const txt = t.textContent.trim(); if (txt) tags.push(txt); });
                            const bcEls = el.querySelectorAll('.bc .dc');
                            const industry = bcEls[0] ? bcEls[0].textContent.trim() : '';
                            const compType = bcEls[1] ? bcEls[1].textContent.trim() : '';
                            const compSize = bcEls[2] ? bcEls[2].textContent.trim() : '';
                            // 分开查询，避免逗号选择器在 el.querySelector 中报错
                            let link = '';
                            try { link = (el.querySelector('.jobinfo a.jname') || {href: ''}).href; } catch(e) {}
                            if (!link) try { link = (el.querySelector('a[href*=51job]') || {href: ''}).href; } catch(e) {}
                            const jobId = data.jobId || '';
                            const jobTitle = data.jobTitle || '';
                            if (!jobTitle && !comp) continue;
                            results.push({
                                _job_id: jobId,
                                jobName: jobTitle || comp || 'unknown',
                                companyName: comp,
                                jobAreaString: area,
                                degreeString: data.jobDegree || '',
                                workYearString: data.jobYear || '',
                                jobTags: tags.join(','),
                                companyTypeString: compType,
                                companySizeString: compSize,
                                industryType1Str: industry,
                                salaryText: sal,
                                _detail_link: link,
                                _sensorsdata: data,
                            });
                        } catch(e) {}
                    }
                    return JSON.stringify({ok: true, results: results, count: results.length});
                } catch(e) {
                    return JSON.stringify({ok: false, error: e.message});
                }
            """)
            parsed = json.loads(raw)
            if parsed.get("ok"):
                results = parsed["results"]
                return results if results else []
            else:
                logger.warning(f"[前程无忧-DOM] JS异常: {parsed.get('error')}")
                return []
        except Exception as e:
            logger.warning(f"[前程无忧-DOM] 提取失败: {e}")
            return []

    def parse_job(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """统一字段映射"""
        salary_text = (
            raw.get("provideSalaryString", "")
            or raw.get("salaryText", "")
            or raw.get("jobSalary", "")
        )
        mn, mx = self._parse_salary(salary_text)

        area_str = raw.get("jobAreaString", "") or raw.get("jobArea", "")
        city = re.split(r"[·\s/]", area_str)[0].strip() if area_str else ""

        tags = raw.get("jobTags", "")
        if isinstance(tags, list):
            tags = ",".join([str(t) for t in tags if t])
        elif not isinstance(tags, str):
            tags = str(tags) if tags else ""

        return {
            "jobName": raw.get("jobName", "").strip(),
            "companyName": raw.get("companyName", "").strip(),
            "jobAreaString": city,
            "degreeString": raw.get("degreeString", "").strip(),
            "workYearString": raw.get("workYearString", "").strip(),
            "jobTags": tags,
            "jobDescribe": raw.get("jobDescribe", "").strip(),
            "companyTypeString": raw.get("companyTypeString", "").strip(),
            "companySizeString": raw.get("companySizeString", "").strip(),
            "industryType1Str": raw.get("industryType1Str", "").strip(),
            "salaryMin": mn,
            "salaryMax": mx,
            "source": "51job",
            "_job_id": raw.get("_job_id", ""),
            "_detail_link": raw.get("_detail_link", ""),
        }

    def _parse_salary(self, text: str) -> tuple:
        text = text.lower().replace(",", "").replace(" ", "").replace("万", "")
        match = re.search(r"(\d+)\s*[-–~]\s*(\d+)\s*[k万]?", text)
        if match:
            mn, mx = int(match.group(1)), int(match.group(2))
            if mn < 10:
                mn *= 10
                mx *= 10
            if mn > mx:
                mn, mx = mx, mn
            return mn, mx
        return 0, 0

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
