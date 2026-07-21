# analyzer/ral.py
import re
import config


def ral_pipeline(item: Dict) -> Dict:
    """
    RAL (Retrieval-Augmented Loop) 溯源增强
    检测二手信息并尝试查找原始出处
    """
    if not config.ENABLE_RETRIEVAL:
        return item

    article = item.get("article", {})
    content = article.get("content", "")
    url = article.get("url", "")

    # 1. 检测 arXiv ID
    arxiv_match = re.search(r'arxiv\.org/abs/(\d+\.\d+)', content)
    if arxiv_match:
        item["original_source"] = f"https://arxiv.org/abs/{arxiv_match.group(1)}"
        item["source_type"] = "arXiv论文"
        return item

    # 2. 检测 GitHub 链接
    github_match = re.search(r'github\.com/[^\s/]+/[^\s/]+', content)
    if github_match:
        item["original_source"] = f"https://{github_match.group()}"
        item["source_type"] = "GitHub仓库"
        return item

    # 3. 检测转载声明
    if "转载" in content or "本文来自" in content or "来源：" in content:
        # 用 LLM 提取原始来源（这里简化处理）
        item["is_second_hand"] = True
        item["original_source"] = "待溯源（建议人工核查）"
        item["source_type"] = "疑似转载"

    # 4. 如果已有 URL 且不是社媒短链，可能本身就是原始来源
    if url and ("zhuanlan.zhihu.com" in url or "mp.weixin.qq.com" in url):
        item["original_source"] = url
        item["source_type"] = "原始文章"

    return item