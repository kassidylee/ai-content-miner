# config.py
# AI Content Miner 配置文件
# 使用前请填写所有必要的 API 密钥和路径

import os
from pathlib import Path

# ============================================================
# 1. LLM API 配置
# ============================================================

# OpenAI API 配置（兼容 OpenAI 接口的都可以）
API_KEY = "your-api-key-here"           # 你的 API Key
BASE_URL = "https://api.openai.com/v1"  # API 地址，可替换为代理地址
MODEL_NAME = "gpt-4"                    # 模型名称，如 gpt-4, gpt-3.5-turbo, deepseek-chat 等

# ============================================================
# 2. 评分与过滤阈值
# ============================================================

SCORE_THRESHOLD = 6          # 评分阈值，≥6 分才生成研报并推送
SHORT_CONTENT_LIMIT = 500    # 短内容字数限制（<500字生成卡片）
MEDIUM_CONTENT_LIMIT = 1500  # 中等内容字数限制（500-1500字生成简报）
MIN_CONTENT_LENGTH = 100     # 最小内容长度，低于此值直接过滤

# 低质量关键词列表（标题或前200字包含则过滤）
LOW_QUALITY_KEYWORDS = [
    "求助", "求推荐", "有人知道吗", "想问一下", 
    "萌新", "求问", "有没有人", "在线等", "急求"
]

# ============================================================
# 3. 博主白名单（给优质博主加权）
# ============================================================

BLOGGER_WHITELIST = {
    # 格式："博主名": {"source": "平台", "weight": 权重系数}
    # 权重系数 1.0 为基准，1.3 表示评分 ×1.3
    "大神A": {"source": "小红书", "weight": 1.3},
    "量化小咖": {"source": "微信公众号", "weight": 1.2},
    "AI研究员B": {"source": "知乎", "weight": 1.4},
    # 继续添加你信任的博主...
}

# ============================================================
# 4. MediaCrawler 爬虫配置
# ============================================================

# MediaCrawler 项目路径（建议放在同目录下）
MEDIACRAWLER_PATH = "./MediaCrawler"

# 爬取平台：xiaohongshu / zhihu / douyin / bilibili / weibo / tieba / kuaishou
CRAWL_PLATFORM = "xiaohongshu"

# 爬取类型：search（搜索）/ detail（详情）/ creator（创作者主页）
CRAWL_TYPE = "search"

# 搜索关键词列表（支持多个，会依次爬取）
SEARCH_KEYWORDS = [
    "AI Agent",
    "大模型", 
    "量化投资",
    "LLM",
    "强化学习"
]

# 爬取数量限制（每轮爬取的文章数量，0 表示不限制）
CRAWL_LIMIT = 20

# 数据保存目录（MediaCrawler 输出目录）
DATA_DIR = "./data"

# ============================================================
# 5. 企业微信推送配置
# ============================================================

# 企业微信机器人 Webhook 地址
# 格式：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-webhook-key"

# 报告文件的基础 URL（用于生成在线阅读链接）
# 如果使用 python server.py 本地预览：http://127.0.0.1:8000/reports
# 如果部署到服务器：https://your-domain.com/reports
REPORT_BASE_URL = "http://127.0.0.1:8000/reports"

# ============================================================
# 6. RAL 溯源增强配置
# ============================================================

# 是否启用 RAL（Retrieval-Augmented Loop）溯源增强
ENABLE_RETRIEVAL = True

# 溯源时是否自动抓取原始页面内容（需开启，可能增加耗时）
FETCH_ORIGINAL_CONTENT = True

# 原始内容缓存过期时间（秒），避免重复抓取
CACHE_EXPIRE_SECONDS = 86400  # 24小时

# ============================================================
# 7. 日志与输出配置
# ============================================================

# 日志目录
LOG_DIR = "./logs"

# RadIter 决策日志文件
RADITER_LOG_FILE = os.path.join(LOG_DIR, "raditer.log")

# 报告输出目录
REPORT_DIR = "./reports"

# 日志级别：DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = "INFO"

# ============================================================
# 8. 高级配置（可选）
# ============================================================

# 评分时的温度参数（0-1，越低越稳定）
SCORE_TEMPERATURE = 0.2

# 生成研报时的温度参数
REPORT_TEMPERATURE = 0.25

# 最大重试次数（API 请求失败时）
MAX_RETRIES = 3

# 每次请求间隔（秒，避免速率限制）
REQUEST_INTERVAL = 2

# 是否启用 lingzao-skill 风格分析
ENABLE_LINGZAO_ANALYSIS = True

# ============================================================
# 9. 路径自动创建
# ============================================================

def init_directories():
    """自动创建必要的目录"""
    dirs = [DATA_DIR, REPORT_DIR, LOG_DIR, "./articles"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

# 自动初始化目录
init_directories()