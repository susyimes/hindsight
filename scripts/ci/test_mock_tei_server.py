from __future__ import annotations

import math
import unittest

from mock_tei_server import embed_text


class MockTEIEmbeddingTests(unittest.TestCase):
    def test_embeddings_are_deterministic_and_normalized(self) -> None:
        first = embed_text("Alice builds distributed systems")
        second = embed_text("Alice builds distributed systems")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0)

    def test_shared_terms_have_higher_similarity(self) -> None:
        document = embed_text("Alice is a software engineer")
        related = embed_text("What work does Alice do as an engineer?")
        unrelated = embed_text("Bananas grow in tropical climates")

        related_score = sum(left * right for left, right in zip(document, related, strict=True))
        unrelated_score = sum(left * right for left, right in zip(document, unrelated, strict=True))
        self.assertGreater(related_score, unrelated_score)


if __name__ == "__main__":
    unittest.main()
