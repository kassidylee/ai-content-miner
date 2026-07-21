# analyzer/scorer.py
import json
import re
import time
from openai import OpenAI
import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


def score_and_classify(article: Dict, max_retries: int = 3) -> Dict:
    """
    根据内容长度动态选择评分维度
    - 短内容 (< 500字): 四维（洞察深度、时效性、启发性、可追溯性）
    - 长内容 (>= 500字): 五维（相关性、创新性、可复现性、声誉、社区热度）
    """
    title = article.get("title", "无标题")
    content = article.get("content", "")
    source = article.get("source", "")
    word_count = len(content)

    # 判断内容类型
    if word_count < config.SHORT_CONTENT_LIMIT:
        dimensions = ["洞察深度", "时效性", "启发性", "可追溯性"]
        weights = [0.30, 0.25, 0.25, 0.20]
        dim_prompt = """
        1. 洞察深度（0-2）：是否提出独特见解或反思
        2. 时效性（0-2）：内容是否紧跟当前技术热点
        3. 启发性（0-2）：能否引发读者的深入思考
        4. 可追溯性（0-2）：是否提供可验证的引用或线索
        """
    else:
        dimensions = ["相关性", "创新性", "可复现性", "声誉", "社区热度"]
        weights = [0.30, 0.25, 0.20, 0.15, 0.10]
        dim_prompt = """
        1. 相关性（0-2）：与 AI Agent 的相关程度
        2. 创新性（0-2）：是否有新观点或方法
        3. 可复现性（0-2）：是否有可操作的技术细节
        4. 声誉（0-2）：作者/机构的可信度
        5. 社区热度（0-2）：内容的传播力
        """

    prompt = f"""你是一个专业的内容分析专家。请对以下文章进行评分。

标题：{title}
来源：{source}
字数：{word_count}

文章内容：
{content}

评分维度（每项 0-2 分）：
{dim_prompt}

分类：访谈/论文解读/新思想/行业分析/产品评测/教程/其他

请返回 JSON：
{{
  "scores": [分值列表],
  "reasons": ["理由1", "理由2", ...],
  "category": "分类",
  "summary": "一句话核心价值（20字内）",
  "is_short": {str(word_count < config.SHORT_CONTENT_LIMIT).lower()}
}}"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是严格的分析专家，只返回合法 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=800
            )
            raw = response.choices[0].message.content.strip()
            result = json.loads(re.search(r'\{[\s\S]*\}', raw).group())

            # 计算加权总分
            total = sum(s * w for s, w in zip(result.get("scores", [0]*len(dimensions)), weights))
            result["total_score"] = round(min(10.0, total * 5), 1)
            result["dimensions"] = dimensions
            result["article"] = article
            result["word_count"] = word_count
            return result

        except Exception as e:
            print(f"   ⚠️ 评分重试 {attempt+1}/{max_retries}: {e}")
            time.sleep((attempt+1) * 3)

    return {
        "article": article,
        "total_score": 0.0,
        "dimensions": dimensions,
        "scores": [0] * len(dimensions),
        "category": "其他",
        "summary": "分析失败",
        "is_short": word_count < config.SHORT_CONTENT_LIMIT,
        "word_count": word_count
    }