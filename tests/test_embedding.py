import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.embedding import EmbeddingError, encode


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.embeddings = self

    def create(self, model, input):
        self.calls.append((model, list(input)))
        return SimpleNamespace(data=self.data)


class EmbeddingUtilityTest(unittest.TestCase):
    def test_encode_batches_and_restores_api_order(self):
        client = FakeClient([
            SimpleNamespace(index=1, embedding=[2.0, 0.0]),
            SimpleNamespace(index=0, embedding=[1.0, 0.0]),
        ])
        with patch("utils.embedding.config.EMBEDDING_MODEL", "fake-model"):
            vectors = encode(["first", "second"], client=client, batch_size=2)
        self.assertEqual(vectors, [[1.0, 0.0], [2.0, 0.0]])
        self.assertEqual(client.calls, [("fake-model", ["first", "second"])])

    def test_encode_rejects_empty_text_without_shifting_results(self):
        with self.assertRaises(EmbeddingError):
            encode(["valid", "  "], client=FakeClient([]))

    def test_encode_reports_response_count_errors(self):
        client = FakeClient([SimpleNamespace(index=0, embedding=[1.0])])
        with self.assertRaisesRegex(EmbeddingError, "返回数量"):
            encode(["first", "second"], client=client)


if __name__ == "__main__":
    unittest.main()
