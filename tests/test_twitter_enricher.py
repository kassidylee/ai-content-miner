import json
import unittest
from types import SimpleNamespace

from analyzer.twitter_enricher import enrich_twitter_items


class FakeCompletions:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            self.payload,
                            ensure_ascii=False,
                        )
                    )
                )
            ]
        )


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.completions = FakeCompletions(payload, error)
        self.chat = SimpleNamespace(completions=self.completions)


def make_item():
    return {
        "id": "x:1",
        "platform": "x",
        "title": "first line",
        "content": (
            "OpenReasoner 发布了新的推理模型和评测结果。"
            "项目代码已经公开。"
        ),
        "quoted_content": "",
        "referenced_urls": [
            {
                "url": "https://github.com/example/OpenReasoner",
                "label": "example/OpenReasoner",
                "domain": "github.com",
            }
        ],
        "filter_metadata": {
            "stages": [
                {
                    "stage": "embedding",
                    "matched_topics": ["reasoning-model"],
                }
            ],
        },
    }


class TwitterEnricherTest(unittest.TestCase):
    def test_rejects_unknown_tags_and_entities_absent_from_source(self):
        item = make_item()
        client = FakeClient(
            {
                "title": "OpenReasoner 推理模型发布",
                "abstract": "发布新的推理模型。项目代码已经公开。",
                "tag_ids": ["ai-agent", "unknown-tag"],
                "entities": ["OpenReasoner", "ImaginaryModel"],
            }
        )

        result = enrich_twitter_items([item], client=client)[0]

        tag_ids = [tag["id"] for tag in result["tags"]]
        self.assertIn("reasoning-model", tag_ids)
        self.assertIn("project-release", tag_ids)
        self.assertIn("ai-agent", tag_ids)
        self.assertNotIn("unknown-tag", tag_ids)
        self.assertEqual(result["entities"], ["OpenReasoner"])
        self.assertEqual(
            result["enrichment_metadata"]["status"],
            "generated",
        )

    def test_model_failure_uses_local_fallback(self):
        item = make_item()
        client = FakeClient(error=RuntimeError("secret"))

        result = enrich_twitter_items([item], client=client)[0]

        self.assertTrue(result["title"].startswith("OpenReasoner"))
        self.assertEqual(
            result["abstract"],
            "OpenReasoner 发布了新的推理模型和评测结果。",
        )
        self.assertEqual(
            result["enrichment_metadata"],
            {"status": "fallback", "error_type": "RuntimeError"},
        )
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
