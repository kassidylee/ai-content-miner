import unittest
from types import SimpleNamespace

from analyzer.reddit_enricher import enrich_reddit_items


class Client:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


class RedditEnricherTest(unittest.TestCase):
    def test_generates_short_chinese_title_and_abstract(self):
        item = {
            "title": "Agent runtime benchmark",
            "content": "A detailed benchmark with reproducible results.",
        }
        client = Client(
            '{"title":"Agent 运行时基准",'
            '"abstract":"项目公布了可复现的 Agent 运行时基准。"}'
        )

        result = enrich_reddit_items([item], client=client)

        self.assertEqual(result[0]["feed_title"], "Agent 运行时基准")
        self.assertEqual(
            result[0]["abstract"],
            "项目公布了可复现的 Agent 运行时基准。",
        )
        self.assertEqual(
            result[0]["reddit_enrichment_metadata"]["status"],
            "generated",
        )
        self.assertEqual(client.calls[0]["max_tokens"], 300)

    def test_api_failure_falls_back_without_failing_workflow(self):
        item = {
            "title": "Agent runtime benchmark",
            "content": (
                "First factual sentence. "
                "Second factual sentence. Third sentence."
            ),
        }

        result = enrich_reddit_items(
            [item],
            client=Client(error=RuntimeError("temporary failure")),
        )

        self.assertEqual(
            result[0]["feed_title"],
            "Agent runtime benchmark",
        )
        self.assertEqual(
            result[0]["abstract"],
            "First factual sentence. Second factual sentence.",
        )
        self.assertEqual(
            result[0]["reddit_enrichment_metadata"]["status"],
            "fallback",
        )


if __name__ == "__main__":
    unittest.main()
