import unittest

from analyzer.filter import (
    AUTHOR_SCORE_MAX,
    COMMENT_SCORE_MAX,
    DISPLAY_SCORE_MAX,
    DISPLAY_SCORE_NEUTRAL,
    FilterResult,
    RULE_SCORE_MAX,
)


class FilterResultScoreTest(unittest.TestCase):
    def test_neutral_four_stage_score_maps_to_existing_threshold(self):
        result = FilterResult()

        self.assertEqual(result.raw_score(), 1.0)
        self.assertEqual(result.total_score(), DISPLAY_SCORE_NEUTRAL)

    def test_maximum_four_stage_score_maps_to_ten(self):
        result = FilterResult(
            rule_score=RULE_SCORE_MAX,
            semantic_score=1.0,
            comment_score=COMMENT_SCORE_MAX,
            author_score=AUTHOR_SCORE_MAX,
        )

        self.assertEqual(result.total_score(), DISPLAY_SCORE_MAX)

    def test_below_neutral_score_remains_below_report_threshold(self):
        result = FilterResult(rule_score=0.5)

        self.assertEqual(result.raw_score(), 0.5)
        self.assertEqual(result.total_score(), 3.0)
        self.assertEqual(result.to_dict()["raw_score"], 0.5)


if __name__ == "__main__":
    unittest.main()
