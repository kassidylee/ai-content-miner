# config.py
# AI Content Miner 配置文件
# 敏感值从项目根目录的 .env 读取；可公开配置继续保留在本文件中。

import os

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# load_dotenv 默认不覆盖调用方已经导出的环境变量，便于部署环境注入配置。
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ============================================================
# 1. LLM API 配置
# ============================================================

API_KEY = os.environ.get("LLM_API_KEY", "").strip()
BASE_URL = os.environ.get(
    "LLM_BASE_URL", "https://api.openai.com/v1"
).strip()
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "").strip()

# ============================================================
# 2. 评分与过滤阈值
# ============================================================

# 四层筛选的原始乘积分数会映射到 0–10；各层均为中性评价时为 6 分。
SCORE_THRESHOLD = 6.0
SEMANTIC_DEDUP_THRESHOLD = 0.85
COMMENT_PASS_THRESHOLD = 0.5
AUTHOR_PROFILE_THRESHOLD = 0.9
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

# 支持平台：xhs（小红书）/ zhihu / x（X）/ reddit
# xhs、zhihu 使用 MediaCrawler；x、reddit 使用各自的独立采集器。
CRAWL_PLATFORM = "x"

# Twitter 使用带技术意图的组合查询；其他平台仍会把它们作为普通搜索词。
SEARCH_KEYWORDS = [
    '"AI Agent" (framework OR benchmark OR "tool calling" OR MCP OR GitHub)',
    '"LLM" (training OR inference OR benchmark OR architecture OR quantization)',
    '"reinforcement learning" (paper OR benchmark OR implementation OR code)',
    '("大模型" OR LLM) (训练 OR 推理 OR 架构 OR 评测 OR 量化 OR 微调 OR 开源)',
    '("AI Agent" OR 智能体) (框架 OR 工具调用 OR MCP OR 开源 OR 实现)',
]

# 本次运行进入下游流程的总数量上限。
CRAWL_LIMIT = 100
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
# 4.2 twscrape（X，实验接口）
# ============================================================

# 本项目直接对齐 PyPI twscrape 0.19.2 的异步 API。
TWSCRAPE_EXPECTED_VERSION = "0.19.2"
TWSCRAPE_SEARCH_PRODUCT = "Top"
TWSCRAPE_RESULTS_PER_QUERY = 50
TWSCRAPE_TIMEOUT_SECONDS = 120
TWSCRAPE_ACCOUNT_WAIT_SECONDS = 10
TWSCRAPE_LOOKBACK_HOURS = 168

# 会话数据库包含浏览器 Cookie，只能保存在本机，不得提交 Git。
TWSCRAPE_DB_FILE = os.environ.get(
    "TWSCRAPE_DB_FILE",
    os.path.join(PROJECT_ROOT, ".local", "x", "twscrape.db"),
)
TWSCRAPE_STATE_FILE = os.path.join(DATA_DIR, "state", "twscrape_seen_ids.json")
TWSCRAPE_SEEN_ID_LIMIT = 5000

# ============================================================
# 4.3 Reddit RSS（本地低频采集）
# ============================================================

# RSS 不提供帖子分数、点赞比例、评论数或 flair。采集器读取明确社区的
# new/.rss，再在本地按 SEARCH_KEYWORDS、时间窗口和帖子 ID 过滤。
REDDIT_RSS_SUBREDDITS = ["LocalLLaMA"]
REDDIT_RSS_RESULTS_PER_SUBREDDIT = 10
REDDIT_RSS_LOOKBACK_HOURS = 168
REDDIT_RSS_REQUEST_TIMEOUT_SECONDS = 30

# 2026-07-24 的真实响应显示当前出口约 30 秒恢复一次 RSS 请求额度。
# 多社区之间默认等待 31 秒；建议先只配置一个社区。
REDDIT_RSS_REQUEST_INTERVAL_SECONDS = 31
REDDIT_RSS_MAX_RESPONSE_BYTES = 2_000_000
REDDIT_RSS_BASE_URL = "https://www.reddit.com"
REDDIT_RSS_USER_AGENT = os.environ.get(
    "REDDIT_RSS_USER_AGENT",
    (
        "python:ai-content-miner:v0.1 "
        "(contact: https://github.com/kassidylee/ai-content-miner)"
    ),
)
REDDIT_RSS_STATE_FILE = os.path.join(
    DATA_DIR, "state", "reddit_rss_seen_ids.json"
)
REDDIT_RSS_SEEN_ID_LIMIT = 5000

# ============================================================
# 4.4 Twitter 专用结构化处理
# ============================================================

# 这些配置只由 Twitter 新流程读取，不影响小红书和知乎的旧筛选链路。
TWITTER_RULE_FILTER = {
    "allowed_languages": ["zh", "en"],
    "allow_replies": False,
    "allow_retweets": False,
    "allow_quotes": True,
    "drop_sensitive": True,
    "min_meaningful_chars": 40,
    # 浏览量或社交互动满足任一门槛即可通过质量检查。
    "min_view_count": 50,
    "min_social_engagement": 2,
    # 不信任 X 搜索结果的宽松匹配，正文必须再次命中至少一个主题词。
    "required_topic_keywords": [
        "AI Agent",
        "AI Agents",
        "Agentic AI",
        "智能体",
        "LLM",
        "Large Language Model",
        "Large Language Models",
        "大模型",
        "Reinforcement Learning",
        "强化学习",
        "Quantitative Trading",
        "Quant Trading",
        "Algorithmic Trading",
        "量化投资",
    ],
    "technical_keywords": [
        "architecture",
        "framework",
        "training",
        "inference",
        "fine-tuning",
        "finetuning",
        "quantization",
        "evaluation",
        "benchmark",
        "paper",
        "experiment",
        "code",
        "open source",
        "implementation",
        "tool calling",
        "dataset",
        "distillation",
        "deployment",
        "repository",
        "repo",
        "GitHub",
        "arXiv",
        "HuggingFace",
        "API",
        "MCP",
        "RAG",
        "架构",
        "框架",
        "训练",
        "推理",
        "微调",
        "量化",
        "评测",
        "基准",
        "论文",
        "实验",
        "代码",
        "开源",
        "实现",
        "工具调用",
        "数据集",
        "蒸馏",
        "部署",
    ],
    "technical_depth_keywords": [
        "architecture",
        "framework",
        "inference",
        "fine-tuning",
        "finetuning",
        "quantization",
        "evaluation",
        "benchmark",
        "paper",
        "experiment",
        "code",
        "implementation",
        "tool calling",
        "dataset",
        "distillation",
        "deployment",
        "MCP",
        "RAG",
        "架构",
        "框架",
        "推理",
        "微调",
        "量化",
        "评测",
        "基准",
        "论文",
        "实验",
        "代码",
        "实现",
        "工具调用",
        "数据集",
        "蒸馏",
        "部署",
    ],
    "business_penalty_keywords": [
        "acquisition",
        "acquire",
        "funding",
        "valuation",
        "revenue",
        "stock",
        "IPO",
        "commercialization",
        "market cap",
        "salary",
        "hiring",
        "startup",
        "industry",
        "geopolitical",
        "capital expenditure",
        "capex",
        "profit",
        "personnel",
        "appointed",
        "promotion",
        "收购",
        "融资",
        "估值",
        "财报",
        "股价",
        "股票",
        "上市",
        "商业化",
        "营收",
        "市值",
        "中美",
        "争霸",
        "军备竞赛",
        "薪资",
        "初创企业",
        "产业",
        "创业",
        "行业格局",
        "资本",
        "二级市场",
        "资本开支",
        "盈利",
        "利润",
        "升任",
        "任命",
        "人事",
        "部门合并",
        "内部通知",
        "掌舵",
    ],
    "promotion_penalty_keywords": [
        "course",
        "webinar",
        "conference",
        "event",
        "hackathon",
        "newsletter",
        "subscribe",
        "top 10",
        "list of",
        "recommended",
        "follow",
        "课程",
        "直播",
        "论坛",
        "大会",
        "峰会",
        "招聘",
        "offer",
        "推荐",
        "关注",
        "清单",
        "合集",
    ],
    "evidence_domains": [
        "github.com",
        "arxiv.org",
        "huggingface.co",
        "paperswithcode.com",
    ],
    "min_technical_score": 3,
    "exclude_keywords": [
        "airdrop",
        "giveaway",
        "casino",
        "betting",
        "sportsbook",
        "match winner",
        "handicap",
        "招聘",
        "返利",
        "空投",
        "博彩",
        "下注",
    ],
}

# Twitter 默认只运行本地筛选；仅在 API 服务商提供 Embedding 模型时再启用。
TWITTER_EMBEDDING_ENABLED = False
TWITTER_EMBEDDING_MODEL = os.environ.get(
    "TWITTER_EMBEDDING_MODEL",
    "text-embedding-3-small",
).strip()
TWITTER_EMBEDDING_BATCH_SIZE = 50
TWITTER_EMBEDDING_MAX_CHARS = 6000

# shadow 只记录低分项；enforce 会删除未达到最高相似主题阈值的内容。
TWITTER_EMBEDDING_FILTER_MODE = "shadow"

TWITTER_INTEREST_TOPICS = [
    {
        "id": "ai-agent",
        "label": "AI Agent",
        "description": (
            "AI Agent、智能体框架、工具调用、任务规划、"
            "多智能体协作、Agent 工作流和相关开源项目"
        ),
        "threshold": 0.35,
        "tag_id": "ai-agent",
    },
    {
        "id": "reasoning-model",
        "label": "推理模型",
        "description": (
            "大语言模型的复杂推理、思维链、test-time compute、"
            "数学推理、代码推理和推理模型训练"
        ),
        "threshold": 0.35,
        "tag_id": "reasoning-model",
    },
    {
        "id": "multimodal",
        "label": "多模态",
        "description": (
            "视觉语言模型、语音模型、图像生成、视频生成、"
            "多模态理解和跨模态推理"
        ),
        "threshold": 0.35,
        "tag_id": "multimodal",
    },
    {
        "id": "ai-infra",
        "label": "AI Infra",
        "description": (
            "大模型训练和推理基础设施、GPU、分布式训练、"
            "推理加速、模型部署、量化和服务框架"
        ),
        "threshold": 0.35,
        "tag_id": "ai-infra",
    },
]

TWITTER_COMMENT_FILTER = {
    "enabled": True,
    "max_replies": 20,
    "timeout_seconds": 30,
    "min_sample_size": 5,
    "min_critical_authors": 3,
    "critical_ratio_threshold": 0.4,
    "weighted_ratio_threshold": 0.6,
    "strong_critical_authors": 2,
    "strong_critical_min_likes": 5,
    "strong_weighted_ratio_threshold": 0.5,
    "critical_keywords": [
        "misleading",
        "incorrect",
        "fabricated",
        "fake",
        "clickbait",
        "no evidence",
        "not reproducible",
        "瞎说",
        "胡扯",
        "错误",
        "造假",
        "误导",
        "不可信",
        "标题党",
    ],
    "ignored_username_suffixes": ["bot"],
}

TWITTER_TITLE_MAX_CHARS = 48
TWITTER_ABSTRACT_MAX_CHARS = 180
TWITTER_ENRICHMENT_INPUT_MAX_CHARS = 6000
TWITTER_LONG_MESSAGE_CHARS = 500
TWITTER_ENTITY_LIMIT = 5
TWITTER_ENRICHMENT_TEMPERATURE = 0.1
TWITTER_ENRICHMENT_MAX_TOKENS = 600

TWITTER_TAG_TAXONOMY = [
    {"id": "ai", "label": "AI", "level": 1, "parent_id": None},
    {
        "id": "ai-agent",
        "label": "AI Agent",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "reasoning-model",
        "label": "推理模型",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "multimodal",
        "label": "多模态",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "ai-infra",
        "label": "AI Infra",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "content-form",
        "label": "内容形式",
        "level": 1,
        "parent_id": None,
    },
    {
        "id": "short-message",
        "label": "短消息",
        "level": 2,
        "parent_id": "content-form",
    },
    {
        "id": "long-message",
        "label": "长消息",
        "level": 2,
        "parent_id": "content-form",
    },
    {
        "id": "paper",
        "label": "论文",
        "level": 2,
        "parent_id": "content-form",
    },
    {
        "id": "project-release",
        "label": "项目发布",
        "level": 2,
        "parent_id": "content-form",
    },
]

TWITTER_PROCESSED_FILE = os.path.join(DATA_DIR, "processed", "x.jsonl")
TWITTER_REPORT_FILE = os.path.join(PROJECT_ROOT, "reports", "x.html")
TWITTER_FEED_RETENTION_DAYS = 30
TWITTER_FEED_MAX_ITEMS = 200
TWITTER_FEED_DEBUG_METADATA = False

# Twitter 通知独立开关；非 Twitter 流程继续使用下方企业微信配置。
TWITTER_ENABLE_WECOM = False

# ============================================================
# 5. 企业微信推送配置
# ============================================================

WECOM_WEBHOOK = os.environ.get(
    "WECOM_WEBHOOK",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-webhook-key",
).strip()
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

# ============================================================
# 10. 非 Twitter 路线的 Embedding 主题匹配配置
# ============================================================

# 该模型只供小红书、知乎等旧四层筛选使用，Twitter 使用上方独立开关和模型。
# 如果 API 服务商不支持默认模型，请在 .env 中填写其实际 Embedding 模型 ID。
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "text-embedding-3-small",
).strip()
EMBEDDING_BATCH_SIZE = 50
EMBEDDING_MAX_CHARS = 6000
# shadow 只记录低相似度结果；enforce 会直接淘汰低于阈值的内容。
EMBEDDING_FILTER_MODE = "shadow"

INTEREST_TOPICS = [
    {
        "id": "ai-agent",
        "label": "AI Agent",
        "description": "AI Agent、智能体框架、工具调用、任务规划、多智能体协作",
        "threshold": 0.35,
        "tag_id": "ai-agent",
    },
    {
        "id": "reasoning-model",
        "label": "推理模型",
        "description": "大语言模型的复杂推理、思维链、数学推理、代码推理",
        "threshold": 0.35,
        "tag_id": "reasoning-model",
    },
    # 根据小红书/知乎的内容特点补充...
]
