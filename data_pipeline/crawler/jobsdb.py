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
        """初始化 Chrome WebDriver，配置反爬与自动化屏蔽参数"""
        # 避免重复初始化
        if self._driver is not None:
            return

        options = Options()
        # headless=new 模式使用新版无头实现，更接近真实浏览器行为
        if self._headless:
            options.add_argument("--headless=new")

        # ===== 反反爬配置 =====
        # 移除 AutomationControlled 特征，防止被前端检测为自动化工具
        options.add_argument("--disable-blink-features=AutomationControlled")
        # 关闭 "Chrome 正受到自动测试软件的控制" 提示条
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        # 禁用自动化扩展，减少被检测的风险
        options.add_experimental_option("useAutomationExtension", False)
        # 中文语言环境，避免触发反爬的区域判断
        options.add_argument("--lang=zh-CN")
        # 固定窗口尺寸，避免因窗口大小不一致导致元素定位失败
        options.add_argument("--window-size=1366,768")
        # 禁用 /dev/shm（共享内存），在 Docker/低内存环境中防止崩溃
        options.add_argument("--disable-dev-shm-usage")
        # 禁用沙箱，部分 Linux 环境中需要
        options.add_argument("--no-sandbox")
        # 禁用 GPU 硬件加速，减少资源占用
        options.add_argument("--disable-gpu")
        # 伪装常见浏览器 UA
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_argument(f"--user-agent={ua}")

        # 自动下载并匹配 ChromeDriver 版本
        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)

        # ===== 注入 JS 隐藏 webdriver 标志 =====
        # 通过 CDP 在页面加载前注入脚本，覆盖 navigator 属性，
        # 使前端检测脚本无法识别为自动化浏览器
        self._driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = { runtime: {} };
            """
        })

        # 页面加载超时 60 秒，避免无限等待
        self._driver.set_page_load_timeout(60)
        # 隐式等待 10 秒，查找元素时自动重试
        self._driver.implicitly_wait(10)

    def _wait_page_ready(self, timeout: int = 20):
        """等待搜索结果列表加载完毕（.joblist-item-job 为每条职位卡片）"""
        try:
            WebDriverWait(self._driver, timeout).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".joblist-item-job"))
            )
        except Exception:
            # 超时或页面异常不阻塞主流程，后续提取会返回空列表
            pass

    def _is_captcha_page(self) -> bool:
        """检测页面是否弹出滑动验证码，遍历常见验证码 DOM 选择器逐一匹配"""
        try:
            # 阿里巴巴系 / 腾讯系等多种验证码组件的选择器
            selectors = [
                "#nc_1_n1z",          # 阿里滑动验证码的滑块元素
                ".nc_wrapper",         # 阿里验证码容器
                "[class*=slider-module]",
                "[class*=tcaptcha]",   # 腾讯验证码
                ".tcaptcha",           # 腾讯验证码（类名匹配）
            ]
            for sel in selectors:
                try:
                    el = self._driver.find_element(By.CSS_SELECTOR, sel)
                    # 元素必须可见才是弹出的验证码，而非隐藏的预加载 DOM
                    if el.is_displayed():
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _wait_captcha_manual(self):
        """检测到验证码时等待用户手动完成（仅可见模式生效，headless 模式直接跳过）"""
        # 无头模式下无法人工介入，直接跳过
        if self._headless:
            return

        if not self._is_captcha_page():
            return

        logger.info("检测到滑动验证码，请在浏览器窗口中手动完成滑动...")
        # 最多等待 5 分钟（300 秒），每 2 秒检查一次验证码是否已通过
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
        """按关键词和城市搜索职位，返回结构化结果列表

        Args:
            keyword:  搜索关键词（如 "Python"）
            city:     城市编码，默认 "010000" 为北京
            page_num: 页码，从 1 开始
            page_size: 每页条数，默认 50
        """
        self._ensure_driver()

        # 构建带时间戳的搜索 URL，避免缓存
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

        # 可见模式下等待人工过验证码
        self._wait_captcha_manual()
        # 额外等待 2 秒确保 DOM 完全渲染
        time.sleep(2)

        # JS 提取原始岗位数据
        jobs = self._extract_from_dom()
        # 统计 DOM 中实际存在的职位卡片数用于日志比对
        try:
            dom_count = len(self._driver.find_elements(By.CSS_SELECTOR, ".joblist-item-job"))
        except Exception:
            dom_count = 0

        logger.info(
            f"[前程无忧] 关键词={keyword} 城市码={city} 页={page_num} 抓到{len(jobs)}条 / DOM总数={dom_count}"
        )

        # 逐条解析为统一格式
        parsed_jobs = []
        for j in jobs:
            parsed = self.parse_job(j)
            logger.info(f"  -> 抓到岗位: {parsed['jobName']} @ {parsed['companyName']}")
            parsed_jobs.append(parsed)

        return parsed_jobs

    def fetch_detail(self, job_id: str) -> str:
        """抓取指定岗位的详情页描述文本

        按优先级尝试多个选择器定位描述区域，
        返回首次匹配到且长度 > 50 的有效内容。
        """
        self._ensure_driver()
        try:
            url = f"https://jobs.51job.com/detail/{job_id}.html"
            self._driver.get(url)
            # 等待页面 body 加载完成即继续，不强制等描述内容出现
            WebDriverWait(self._driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
            )
            time.sleep(2)

            self._wait_captcha_manual()

            # 按常见度从高到低遍历描述区域选择器，找到即返回
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
                    # 长度阈值 50 用于过滤空占位或简短摘要
                    if len(text) > 50:
                        return text
                except Exception:
                    pass
            return ""
        except Exception as e:
            logger.warning(f"[前程无忧-详情] 抓取失败 {job_id}: {e}")
            return ""

    def _extract_from_dom(self) -> List[Dict[str, Any]]:
        """用 JavaScript 从 DOM 直接提取岗位数据

        通过 selenium execute_script 在浏览器中运行 JS，
        遍历所有 .joblist-item-job 卡片，从 sensorsdata 属性
        和 DOM 子元素中提取岗位字段。JS 端直接返回 JSON，
        Python 端只需 json.loads 即可，避免多次 Selenium 通信开销。
        """
        try:
            raw = self._driver.execute_script("""
                try {
                    const items = document.querySelectorAll('.joblist-item-job');
                    const results = [];
                    for (let i = 0; i < items.length; i++) {
                        const el = items[i];
                        try {
                            // 前程无忧将大量结构化数据编码在 sensorsdata 自定义属性中
                            const sd_raw = el.getAttribute('sensorsdata');
                            let data = {};
                            if (sd_raw) {
                                // 优先直接 JSON.parse；失败则尝试 HTML 实体解码后再解析
                                try { data = JSON.parse(sd_raw); } catch(e1) {
                                    try {
                                        // textarea.innerHTML 可自动解码 &quot; &amp; 等 HTML 实体
                                        const textarea = document.createElement('textarea');
                                        textarea.innerHTML = sd_raw;
                                        data = JSON.parse(textarea.value);
                                    } catch(e2) {}
                                }
                            }
                            // 薪资：优先从 .sal 元素文本取，其次用 sensorsdata
                            const salEl = el.querySelector('.sal');
                            const sal = salEl ? salEl.textContent.trim() : (data.jobSalary || '');
                            // 公司名
                            const compEl = el.querySelector('.cname');
                            const comp = compEl ? compEl.textContent.trim() : (data.companyName || '');
                            // 工作地点
                            const areaEl = el.querySelector('.area .shrink-0');
                            const area = areaEl ? areaEl.textContent.trim() : (data.jobArea || '');
                            // 职位标签（如 "五险一金"、"双休" 等）
                            const tags = [];
                            el.querySelectorAll('.tag').forEach(t => { const txt = t.textContent.trim(); if (txt) tags.push(txt); });
                            // .bc 下的 .dc 元素依次为：行业、公司类型、公司规模
                            const bcEls = el.querySelectorAll('.bc .dc');
                            const industry = bcEls[0] ? bcEls[0].textContent.trim() : '';
                            const compType = bcEls[1] ? bcEls[1].textContent.trim() : '';
                            const compSize = bcEls[2] ? bcEls[2].textContent.trim() : '';
                            // 职位详情链接：分开查询避免逗号选择器在 el.querySelector 中报错
                            let link = '';
                            try { link = (el.querySelector('.jobinfo a.jname') || {href: ''}).href; } catch(e) {}
                            if (!link) try { link = (el.querySelector('a[href*=51job]') || {href: ''}).href; } catch(e) {}
                            const jobId = data.jobId || '';
                            const jobTitle = data.jobTitle || '';
                            // 跳过无标题且无公司的无效卡片
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
        """将前端提取的原始字段映射为统一格式

        处理逻辑：
        - 薪资文本 -> 解析为 min/max 数值
        - 地区字符串 -> 提取城市名（按 ·/空格/- 分割取第一段）
        - 标签 -> 统一转为逗号分隔的字符串
        """
        # 薪资：兼容 provideSalaryString / salaryText / jobSalary 多种字段名
        salary_text = (
            raw.get("provideSalaryString", "")
            or raw.get("salaryText", "")
            or raw.get("jobSalary", "")
        )
        mn, mx = self._parse_salary(salary_text)

        # 城市：从如 "北京·朝阳区" 中提取 "北京"
        area_str = raw.get("jobAreaString", "") or raw.get("jobArea", "")
        city = re.split(r"[·\s/]", area_str)[0].strip() if area_str else ""

        # 标签：兼容 list / str / 其他类型，统一为逗号分隔字符串
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
            "source": "51job",          # 数据来源标识
            "_job_id": raw.get("_job_id", ""),
            "_detail_link": raw.get("_detail_link", ""),
        }

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资文本为 (min, max) 数值

        示例:
            "15-20K"   -> (15, 20)
            "1.5-2万"  -> (15, 20)  万被移除，值 < 10 时自动 ×10
            "面议"     -> (0, 0)
        """
        # 预处理：去除逗号、空格、万字，统一为纯数字+范围符的格式
        text = text.lower().replace(",", "").replace(" ", "").replace("万", "")
        # 匹配 "数字-数字" 格式，容许多种分隔符（- – ~）
        match = re.search(r"(\d+)\s*[-–~]\s*(\d+)\s*[k万]?", text)
        if match:
            mn, mx = int(match.group(1)), int(match.group(2))
            # 若数值偏小（如 "1-2" 实际是 "1万-2万"），放大 10 倍
            if mn < 10:
                mn *= 10
                mx *= 10
            # 保证 min <= max
            if mn > mx:
                mn, mx = mx, mn
            return mn, mx
        return 0, 0

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
