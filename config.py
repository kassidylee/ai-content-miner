# config.py
# AI Content Miner 配置文件
# 使用前请填写所有必要的 API 密钥和路径

import os

# ============================================================
# 1. LLM API 配置
# ============================================================

API_KEY = "your-api-key-here"
BASE_URL = "https://api.openai.com/v1"
MODEL_NAME = "gpt-4"

# ============================================================
# 2. 评分与过滤阈值
# ============================================================

SCORE_THRESHOLD = 6
SHORT_CONTENT_LIMIT = 500
MEDIUM_CONTENT_LIMIT = 1500
MIN_CONTENT_LENGTH = 100

LOW_QUALITY_KEYWORDS = [
    "求助", "求推荐", "有人知道吗", "想问一下",
    "萌新", "求问", "有没有人", "在线等", "急求"
]

# ============================================================
# 3. 博主白名单
# ============================================================

BLOGGER_WHITELIST = {
    "大神A": {"source": "小红书", "weight": 1.3},
    "量化小咖": {"source": "知乎", "weight": 1.2},
    "AI研究员B": {"source": "知乎", "weight": 1.4},
}

# ============================================================
# 4. MediaCrawler 爬虫配置
# ============================================================

MEDIACRAWLER_PATH = "./MediaCrawler"

# 支持平台：xhs（小红书）/ zhihu
CRAWL_PLATFORM = "xhs"

# 爬取类型：search / detail / creator
CRAWL_TYPE = "search"

# 搜索关键词列表（多个关键词依次爬取）
SEARCH_KEYWORDS = [
    "AI Agent",
    "大模型",
    "量化投资",
    "LLM",
    "强化学习"
]

CRAWL_LIMIT = 20
DATA_DIR = "./data"

# ============================================================
# 5. 企业微信推送配置
# ============================================================

WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-webhook-key"
REPORT_BASE_URL = "http://192.168.1.100:8000/reports"

# ============================================================
# 6. RAL 来源识别配置
# ============================================================

ENABLE_RETRIEVAL = True

# 以下为预留配置，暂未实现
# FETCH_ORIGINAL_CONTENT = True
# CACHE_EXPIRE_SECONDS = 86400

# ============================================================
# 7. 日志与输出配置
# ============================================================

LOG_DIR = "./logs"
RADITER_LOG_FILE = os.path.join(LOG_DIR, "raditer.log")
REPORT_DIR = "./reports"
LOG_LEVEL = "INFO"

# ============================================================
# 8. 高级配置
# ============================================================

SCORE_TEMPERATURE = 0.2
REPORT_TEMPERATURE = 0.25
MAX_RETRIES = 3
REQUEST_INTERVAL = 2
ENABLE_LINGZAO_ANALYSIS = True

# ============================================================
# 9. 路径自动创建
# ============================================================

def init_directories():
    dirs = [DATA_DIR, REPORT_DIR, LOG_DIR, "./articles"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

init_directories()