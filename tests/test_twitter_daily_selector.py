import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from analyzer.twitter_daily_selector import select_twitter_daily_items


NOW = datetime(2026, 7, 29, 1, tzinfo=timezone.utc)


def make_item(
    index,
    *,
    title=None,
    content=None,
    author=None,
    views=None,
    url=None,
):
    item_id = f"x:{index}"
    references = []
    if url:
        references.append(
            {
                "url": url,
                "label": url,
                "domain": "github.com",
            }
        )
    return {
        "id": item_id,
        "platform_item_id": str(index),
        "platform": "x",
        "title": title or f"Project{index} technical release",
        "content": content or f"Project{index} implementation details",
        "quoted_content": "",
        "source_url": f"https://x.com/user{index}/status/{index}",
        "referenced_urls": references,
        "published_at": NOW - timedelta(minutes=index),
        "author": author or f"Author {index}",
        "username": f"user{index}",
        "metrics": {
            "like_count": index,
            "reply_count": 1,
            "share_count": 1,
            "bookmark_count": 0,
            "quote_count": 0,
            "view_count": views if views is not None else 1000 + index,
        },
        "filter_metadata": {
            "stages": [
                {
                    "stage": "rules",
                    "decision": "pass",
                    "reason_codes": ["TWITTER_RULES_PASSED"],
                    "details": {
                        "technical_score": 6,
                        "evidence_domains": ["github.com"] if url else [],
                        "matched_topic_keywords": ["AI Agent"],
                        "promotion_penalties": [],
                    },
                },
                {
                    "stage": "embedding",
                    "decision": "pass",
                    "mode": "disabled",
                    "best_topic": "",
                    "best_score": 0.0,
                },
            ],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
    }


class FakeReplyProvider:
    def __init__(self, rejected_ids=()):
        self.rejected_ids = set(rejected_ids)
        self.calls = []

    def fetch_replies(self, items, limit, timeout_seconds):
        item = items[0]
        item_id = item["id"]
        self.calls.append(item_id)
        if item_id not in self.rejected_ids:
            comments = []
        else:
            comments = [
                {
                    "id": f"{item_id}:{index}",
                    "content": f"This is fake and incorrect evidence {index}",
                    "author_username": f"critic{index}",
                    "like_count": 10,
                }
                for index in range(5)
            ]
        return {
            item_id: {
                "available": True,
                "comments": comments,
                "error": "",
            }
        }


class TwitterDailySelectorTest(unittest.TestCase):
    def daily_limits(self):
        return patch.multiple(
            "analyzer.twitter_daily_selector.config",
            TWITTER_DAILY_PRIMARY_LIMIT=8,
            TWITTER_DAILY_MORE_LIMIT=4,
            TWITTER_DAILY_AUTHOR_LIMIT=1,
            TWITTER_DAILY_TOPIC_REPEAT_PENALTY=3.0,
            TWITTER_DAILY_HISTORY_DAYS=7,
            TWITTER_DAILY_EVENT_TOKEN_OVERLAP=0.4,
            TWITTER_DAILY_TIMEZONE="Asia/Hong_Kong",
            TWITTER_DAILY_STANDARD_MAX_AGE_HOURS=48,
            TWITTER_DAILY_FALLBACK_MAX_AGE_HOURS=168,
            TWITTER_DAILY_FALLBACK_MIN_SOCIAL_SCORE=0.85,
            TWITTER_DAILY_MIN_WEIGHTED_ENGAGEMENT=5.0,
        )

    def test_selects_at_most_eight_primary_and_four_more(self):
        items = [make_item(index) for index in range(1, 16)]

        with self.daily_limits():
            result = select_twitter_daily_items(items, now=NOW)

        self.assertEqual(len(result["primary"]), 8)
        self.assertEqual(len(result["more"]), 4)
        self.assertEqual(len(result["selected"]), 12)
        self.assertEqual(len(result["archived"]), 3)
        self.assertEqual(
            {
                item["publication_metadata"]["decision"]
                for item in result["primary"]
            },
            {"primary"},
        )
        self.assertEqual(
            {
                item["publication_metadata"]["decision"]
                for item in result["more"]
            },
            {"more"},
        )

    def test_clusters_different_posts_about_the_same_event(self):
        items = [
            make_item(
                1,
                title="Kimi K3 open source release",
                content="Kimi K3 architecture and weights",
            ),
            make_item(
                2,
                title="Kimi K3 releases its infrastructure stack",
                content="Kimi K3 kernels and MoE library",
            ),
            make_item(
                3,
                title="Independent Project3 release",
                content="Project3 implementation details",
            ),
        ]

        with self.daily_limits():
            result = select_twitter_daily_items(items, now=NOW)

        self.assertEqual(len(result["selected"]), 2)
        duplicates = [
            item
            for item in items
            if item["publication_metadata"]["decision"]
            == "cluster_duplicate"
        ]
        self.assertEqual(len(duplicates), 1)

    def test_checks_replies_lazily_and_backfills_rejected_item(self):
        items = [
            make_item(
                index,
                views=100_000 - index,
                url=f"https://github.com/example/project{index}",
            )
            for index in range(1, 15)
        ]
        provider = FakeReplyProvider(rejected_ids={"x:14"})

        with self.daily_limits():
            result = select_twitter_daily_items(
                items,
                reply_provider=provider,
                now=NOW,
            )

        self.assertEqual(len(result["selected"]), 12)
        self.assertEqual(len(result["comment_dropped"]), 1)
        self.assertEqual(provider.calls[0], "x:14")
        self.assertEqual(len(provider.calls), 13)

    def test_archives_event_seen_in_recent_digest(self):
        current = make_item(
            1,
            title="OpenMinis mobile agent release",
            content="OpenMinis runs agents on mobile devices",
        )
        history = make_item(
            99,
            title="OpenMinis is now open source",
            content="OpenMinis mobile agent source code",
        )
        history["publication_metadata"] = {
            "decision": "primary",
            "digest_date": "2026-07-28",
        }

        with self.daily_limits():
            result = select_twitter_daily_items(
                [current],
                recent_history=[history],
                now=NOW,
            )

        self.assertEqual(result["selected"], [])
        self.assertEqual(
            current["publication_metadata"]["reason_codes"],
            ["TWITTER_DAILY_RECENT_EVENT"],
        )

    def test_listicle_is_ranked_below_specific_technical_item(self):
        listicle = make_item(
            1,
            title="10 open-source GitHub repos for AI developers",
        )
        technical = make_item(
            2,
            title="Project2 inference cache implementation",
        )
        listicle["metrics"] = dict(technical["metrics"])

        with self.daily_limits():
            result = select_twitter_daily_items(
                [listicle, technical],
                now=NOW,
            )

        self.assertEqual(result["selected"][0]["id"], "x:2")

    def test_high_interaction_outranks_stronger_static_content_signals(self):
        popular = make_item(1, title="Project1 benchmark update")
        popular["metrics"].update(
            {
                "like_count": 800,
                "reply_count": 80,
                "share_count": 160,
                "bookmark_count": 300,
                "quote_count": 20,
                "view_count": 20_000,
            }
        )
        popular_rules = popular["filter_metadata"]["stages"][0]["details"]
        popular_rules["technical_score"] = 3
        popular_rules["evidence_domains"] = []

        static = make_item(
            2,
            title="Project2 implementation details",
            url="https://github.com/example/project2",
        )
        static["metrics"].update(
            {
                "like_count": 3,
                "reply_count": 0,
                "share_count": 0,
                "bookmark_count": 0,
                "quote_count": 0,
                "view_count": 2_000,
            }
        )

        with self.daily_limits():
            result = select_twitter_daily_items(
                [static, popular],
                now=NOW,
            )

        self.assertEqual(result["selected"][0]["id"], popular["id"])
        popular_score = popular["publication_metadata"]["score_breakdown"]
        self.assertGreater(
            popular_score["social_quality"],
            static["publication_metadata"]["score_breakdown"][
                "social_quality"
            ],
        )

    def test_old_content_requires_both_high_social_signal_and_evidence(self):
        strong = make_item(
            1,
            title="Project1 release with reproducible benchmark",
            url="https://github.com/example/project1",
        )
        strong["published_at"] = NOW - timedelta(hours=160)
        strong["metrics"].update(
            {
                "like_count": 1_000,
                "reply_count": 80,
                "share_count": 200,
                "bookmark_count": 400,
                "quote_count": 30,
                "view_count": 50_000,
            }
        )
        weak = make_item(2, title="Project2 architecture discussion")
        weak["published_at"] = NOW - timedelta(hours=80)
        weak["metrics"].update(
            {
                "like_count": 10,
                "reply_count": 0,
                "share_count": 0,
                "bookmark_count": 0,
                "quote_count": 0,
                "view_count": 500,
            }
        )

        with self.daily_limits():
            result = select_twitter_daily_items(
                [weak, strong],
                now=NOW,
            )

        self.assertEqual(result["selected"], [strong])
        self.assertEqual(
            weak["publication_metadata"]["reason_codes"],
            ["TWITTER_DAILY_STALE_LOW_SIGNAL"],
        )

    def test_zero_interaction_evidence_is_not_used_to_fill_capacity(self):
        item = make_item(
            1,
            title="Project1 open source release",
            url="https://github.com/example/project1",
        )
        item["metrics"] = {
            "like_count": 0,
            "reply_count": 0,
            "share_count": 0,
            "bookmark_count": 0,
            "quote_count": 0,
            "view_count": 1_000,
        }

        with self.daily_limits():
            result = select_twitter_daily_items([item], now=NOW)

        self.assertEqual(result["selected"], [])
        self.assertEqual(
            item["publication_metadata"]["reason_codes"],
            ["TWITTER_DAILY_LOW_SOCIAL_SIGNAL"],
        )

    def test_four_topic_catalog_can_fill_eight_plus_four_capacity(self):
        topics = ["ai-agent", "reasoning-model", "multimodal", "ai-infra"]
        items = [make_item(index) for index in range(1, 13)]
        for index, item in enumerate(items):
            embedding = item["filter_metadata"]["stages"][1]
            embedding["best_topic"] = topics[index % len(topics)]

        with self.daily_limits():
            result = select_twitter_daily_items(items, now=NOW)

        self.assertEqual(len(result["primary"]), 8)
        self.assertEqual(len(result["more"]), 4)


if __name__ == "__main__":
    unittest.main()
