"""
Explore / topics feed for SCALABLE

Backs the frontend's Explore menu (Discover / Finance / Academic / Health).
Deliberately does NOT add a new search provider — it reuses
RealtimeGroqService.search_tavily(), the exact same Tavily client
realtime_service.py already uses for live chat search. One search
integration, two entry points.
"""

import logging
from typing import Optional

logger = logging.getLogger("SCALABLE")

TOPIC_QUERIES = {
    "discover": "trending news and interesting stories today",
    "finance": "top financial market and economic news today",
    "academic": "recent notable research and academic discoveries",
    "health": "latest health and medical news today",
}


class ExploreError(Exception):
    pass


class ExploreService:

    def __init__(self, realtime_service):
        self.realtime_service = realtime_service

    def get_topic_feed(self, topic: str) -> dict:
        topic_key = (topic or "").strip().lower()

        if topic_key not in TOPIC_QUERIES:
            raise ExploreError(
                f"Unknown topic '{topic}'. Available: {', '.join(TOPIC_QUERIES.keys())}"
            )

        if not self.realtime_service or not self.realtime_service.tavily_client:
            raise ExploreError("Web search is not configured (TAVILY_API_KEY missing).")

        query = TOPIC_QUERIES[topic_key]
        logger.info("[EXPLORE] Fetching topic feed: %s -> %s", topic_key, query)

        _, payload = self.realtime_service.search_tavily(query, num_results=8)

        if not payload:
            raise ExploreError("No results found for this topic right now. Try again shortly.")

        payload["topic"] = topic_key
        return payload

    