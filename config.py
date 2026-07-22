# config.py
# AI Content Miner 配置文件
# 使用前请填写所有必要的 API 密钥和路径

import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

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
# 4. 内容采集配置
# ============================================================

# 支持平台：xhs（小红书）/ zhihu / x（X，通过 Twikit）
# xhs、zhihu 使用 MediaCrawler；x 使用独立的 Twikit 采集器。
CRAWL_PLATFORM = "xhs"

# 搜索关键词列表
SEARCH_KEYWORDS = [
    "AI Agent",
    "大模型",
    "量化投资",
    "LLM",
    "强化学习"
]

# 本次运行进入下游流程的总数量上限。
CRAWL_LIMIT = 20
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
ARTICLES_DIR = os.path.join(PROJECT_ROOT, "articles")

# ============================================================
# 4.1 MediaCrawler（小红书、知乎）
# ============================================================

MEDIACRAWLER_PATH = os.path.join(PROJECT_ROOT, "MediaCrawler")

# 本项目桥接器已按该 commit 的 CLI 与 JSONL 输出格式完成对齐。
MEDIACRAWLER_COMMIT = "c9a111be73586bdf6fc44536f088e4db6ed86d64"

# 默认使用 MediaCrawler 官方推荐的 uv。仅在未安装 uv 时填写一个
# Python >= 3.11 且已安装 MediaCrawler 依赖的解释器路径。
MEDIACRAWLER_PYTHON = ""
MEDIACRAWLER_LOGIN_TYPE = "qrcode"
MEDIACRAWLER_TIMEOUT_SECONDS = 900

# 爬取类型：search / detail / creator
CRAWL_TYPE = "search"

# ============================================================
# 4.2 Twikit（X）
# ============================================================

# 本项目直接对齐 PyPI twikit 2.3.3 的公开接口。
TWIKIT_EXPECTED_VERSION = "2.3.3"
TWIKIT_LANGUAGE = "en-US"
TWIKIT_SEARCH_PRODUCT = "Latest"

# Twikit 单次请求最多 20 条；超过 20 时通过 Result.next() 分页。
TWIKIT_RESULTS_PER_QUERY = 20
TWIKIT_MAX_PAGES_PER_QUERY = 5
TWIKIT_TIMEOUT_SECONDS = 120
TWIKIT_LOOKBACK_HOURS = 168

# Cookie 和已处理状态只保存在本机，不得提交 Git。
TWIKIT_COOKIE_FILE = os.environ.get(
    "TWIKIT_COOKIE_FILE",
    os.path.join(PROJECT_ROOT, ".local", "x", "cookies.json"),
)
TWIKIT_STATE_FILE = os.path.join(DATA_DIR, "state", "twikit_seen_ids.json")
TWIKIT_SEEN_ID_LIMIT = 5000

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

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
RADITER_LOG_FILE = os.path.join(LOG_DIR, "raditer.log")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports")
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
    dirs = [DATA_DIR, REPORT_DIR, LOG_DIR, ARTICLES_DIR]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

init_directories()
