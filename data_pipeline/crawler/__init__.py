"""爬虫包"""
from .jobsdb import JobsdbCrawler
from .liepin import LiepinCrawler
from .zhaopin import ZhaopinCrawler

__all__ = ["JobsdbCrawler", "LiepinCrawler", "ZhaopinCrawler"]
