import json
import unittest
from types import SimpleNamespace

from analyzer.enricher import enrich_item, enrich_items


class FakeCompletions:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = json.dumps(self.payload, ensure_ascii=False)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        )


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.completions = FakeCompletions(payload=payload, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


def make_item(native_title=False):
    return {
        "id": "x:1",
        "platform": "x",
        "title": "平台原始标题" if native_title else "原始正文第一行",
        "content": (
            "OpenReasoner 发布了新的推理模型和评测结果。"
            "项目代码已经公开。第三句不应进入摘要。"
        ),
        "quoted_content": "",
        "referenced_urls": [
            {
                "url": "https://github.com/example/OpenReasoner",
                "label": "example/OpenReasoner",
                "domain": "github.com",
            }
        ],
        "platform_metadata": {
            "has_native_title": native_title,
        },
        "filter_metadata": {
            "stages": [
                {
                    "stage": "embedding",
                    "matched_topics": ["reasoning-model"],
                }
            ],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
    }


class EnricherTest(unittest.TestCase):
    def test_generates_concise_fields_and_validates_tags(self):
        item = make_item()
        client = FakeClient(
            {
                "title": "OpenReasoner 推理模型发布" * 4,
                "abstract": "发布新的推理模型。公开项目代码。额外评价。",
                "tag_ids": ["ai-agent", "unknown-tag"],
                "entities": ["OpenReasoner", "原文不存在的模型"],
            }
        )

        result = enrich_item(item, client)

        self.assertLessEqual(len(result["title"]), 48)
        self.assertEqual(result["abstract"], "发布新的推理模型。 公开项目代码。")
        tag_ids = [tag["id"] for tag in result["tags"]]
        self.assertIn("ai", tag_ids)
        self.assertIn("reasoning-model", tag_ids)
        self.assertIn("ai-agent", tag_ids)
        self.assertIn("content-form", tag_ids)
        self.assertIn("project-release", tag_ids)
        self.assertNotIn("unknown-tag", tag_ids)
        self.assertEqual(result["entities"], ["OpenReasoner"])
        entity_tags = [tag for tag in result["tags"] if tag["level"] == 3]
        self.assertEqual(entity_tags[0]["label"], "OpenReasoner")
        self.assertEqual(result["enrichment_metadata"]["status"], "generated")
        self.assertEqual(len(client.completions.calls), 1)

    def test_native_title_is_preserved(self):
        item = make_item(native_title=True)
        client = FakeClient(
            {
                "title": "模型生成标题",
                "abstract": "内容摘要。",
                "tag_ids": [],
                "entities": [],
            }
        )

        result = enrich_item(item, client)

        self.assertEqual(result["title"], "平台原始标题")

    def test_dynamic_entity_must_exist_in_source_text(self):
        item = make_item()
        client = FakeClient(
            {
                "title": "推理模型发布",
                "abstract": "OpenReasoner 发布推理模型。",
                "tag_ids": ["reasoning-model"],
                "entities": ["OpenReasoner", "ImaginaryModel"],
            }
        )

        result = enrich_item(item, client)

        self.assertEqual(result["entities"], ["OpenReasoner"])
        self.assertNotIn(
            "ImaginaryModel",
            [tag["label"] for tag in result["tags"]],
        )

    def test_model_failure_uses_local_fallback(self):
        item = make_item()
        client = FakeClient(error=RuntimeError("secret"))

        result = enrich_item(item, client)

        self.assertTrue(result["title"].startswith("OpenReasoner"))
        self.assertEqual(
            result["abstract"],
            "OpenReasoner 发布了新的推理模型和评测结果。",
        )
        self.assertEqual(result["enrichment_metadata"]["status"], "fallback")
        self.assertEqual(
            result["enrichment_metadata"]["error_type"],
            "RuntimeError",
        )
        self.assertNotIn("secret", str(result["enrichment_metadata"]))
        tag_ids = [tag["id"] for tag in result["tags"]]
        self.assertIn("reasoning-model", tag_ids)
        self.assertIn("project-release", tag_ids)

    def test_empty_input_does_not_create_client_or_call_model(self):
        client = FakeClient({})

        result = enrich_items([], client=client)

        self.assertEqual(result, [])
        self.assertEqual(client.completions.calls, [])


if __name__ == "__main__":
    unittest.main()
