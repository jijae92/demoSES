"""DynamoDB access helpers for tracking seen papers."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from util import PaperItem

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SeenRepository:
    """Repository abstraction for the DynamoDB table."""

    table_name: str

    def __post_init__(self) -> None:
        self._client = boto3.client("dynamodb")

    def is_seen(self, paper_id: str) -> bool:
        """Return True if the paper has already been observed."""
        try:
            response = self._client.get_item(
                TableName=self.table_name,
                Key={"paper_id": {"S": paper_id}},
                ProjectionExpression="paper_id",
                ConsistentRead=False,
            )
        except (ClientError, BotoCoreError):
            LOGGER.exception("DynamoDB get_item failed for %s", paper_id)
            raise
        return "Item" in response

    def mark_seen(self, items: Sequence[PaperItem]) -> None:
        """Persist the provided items as seen using batch_write_item."""
        if not items:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        requests = [
            {
                "PutRequest": {
                    "Item": {
                        "paper_id": {"S": item.paper_id},
                        "source": {"S": item.source},
                        "title": {"S": item.title[:400]},
                        "created_at": {"S": now_iso},
                    }
                }
            }
            for item in items
        ]
        chunks = [requests[i : i + 25] for i in range(0, len(requests), 25)]
        for chunk in chunks:
            try:
                response = self._client.batch_write_item(RequestItems={self.table_name: chunk})
            except (ClientError, BotoCoreError):
                LOGGER.exception("DynamoDB batch_write_item failed")
                raise
            unprocessed = response.get("UnprocessedItems", {})
            if unprocessed:
                LOGGER.warning("Some DynamoDB items were unprocessed: %s", unprocessed)