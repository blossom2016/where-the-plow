# src/where_the_plow/collector.py
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from where_the_plow.client import fetch_vehicles, parse_avl_response
from where_the_plow.db import Database
from where_the_plow.config import settings

logger = logging.getLogger(__name__)


def process_poll(db: Database, response: dict) -> int:
    now = datetime.now(timezone.utc)
    vehicles, positions = parse_avl_response(response)
    db.upsert_vehicles(vehicles, now)
    inserted = db.insert_positions(positions, now)
    return inserted


async def run(db: Database):
    logger.info("Collector starting — polling every %ds", settings.poll_interval)

    stats = db.get_stats()
    logger.info(
        "DB stats: %d positions, %d vehicles",
        stats["total_positions"],
        stats["total_vehicles"],
    )

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await fetch_vehicles(client)
                features = response.get("features", [])
                inserted = process_poll(db, response)
                logger.info(
                    "Poll: %d vehicles seen, %d new positions",
                    len(features),
                    inserted,
                )
            except asyncio.CancelledError:
                logger.info("Collector shutting down")
                raise
            except Exception:
                logger.exception("Poll failed")

            await asyncio.sleep(settings.poll_interval)
