# analyzer/lingzao_adapter.py
"""
lingzao-skill 适配器
"""
import json
import re
from typing import Dict, List
from openai import OpenAI

import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


class LingzaoAnalyzer:
    def __init__(self):
        self.system_prompt = """你是一个专业的小红书/社媒内容分析师（灵造 Skill 风格）。
你的任务是对社媒内容进行深度分析，包括：
1. 账号诊断：判断该账号的定位、专业度、影响力
2. 爆款拆解：分析内容为什么可能成为爆款
3. 对标分析：与同领域优质内容对比
4. 内容质量评估：信息密度、原创性、实用性

请输出结构化分析结果。"""

    def analyze(self, article: Dict) -> Dict:
        if not config.ENABLE_LINGZAO_ANALYSIS:
            return {"error": "lingzao analysis disabled"}

        title = article.get("title", "无标题")
        content = article.get("content", "")[:2000]
        author = article.get("author", "未知作者")
        source = article.get("source", "小红书")
        likes = article.get("likes", 0)
        comments = article.get("comments", 0)

        prompt = f"""请对以下社媒内容进行 lingzao-skill 风格的分析：

【基本信息】
- 标题：{title}
- 作者：{author}
- 平台：{source}
- 点赞：{likes}
- 评论：{comments}

【内容】
{content}

请输出 JSON 格式：
{{
  "account_diagnosis": {{
    "定位": "账号的领域定位",
    "专业度": "高/中/低",
    "影响力": "高/中/低"
  }},
  "content_analysis": {{
    "信息密度": "高/中/低",
    "原创性": "高/中/低",
    "实用性": "高/中/低",
    "爆款潜力": "高/中/低"
  }},
  "keywords": ["关键词1", "关键词2"],
  "summary": "一句话总结（20字内）",
  "quality_score": 0.0
}}"""

        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=config.SCORE_TEMPERATURE,
                max_tokens=800
            )
            raw = response.choices[0].message.content.strip()
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                return json.loads(json_match.group())
            return {"error": "解析失败", "raw": raw}
        except Exception as e:
            return {"error": str(e)}

    def find_benchmark_accounts(self, niche: str) -> List[Dict]:
        return []

    def diagnose_account(self, author: str, articles: List[Dict]) -> Dict:
        return {}