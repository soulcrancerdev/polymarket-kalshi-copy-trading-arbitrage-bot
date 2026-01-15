#!/usr/bin/env python3
"""
Sports neg_risk and slug cache warmer (async version).

Run manually:
    cd <PROJECT_ROOT>/rust_clob_client
    python3 scripts/build_sports_cache.py

Cronjob (every 30 minutes):
    */30 * * * * cd <PROJECT_ROOT>/rust_clob_client && python3 scripts/build_sports_cache.py >> /tmp/cache_warmer.log 2>&1

Edit crontab with: crontab -e
"""

import asyncio
import json
from pathlib import Path
import aiohttp

GAMMA_API = "https://gamma-api.polymarket.com"
GAMES_TAG = "100639"
CACHE_FILE = ".clob_market_cache.json"
SLUG_CACHE_FILE = ".clob_slug_cache.json"
CONCURRENT_REQUESTS = 5  # tune based on rate limits


async def fetch_page(session: aiohttp.ClientSession, offset: int) -> list:
    async with session.get(
        f"{GAMMA_API}/events",
        params={"tag_id": GAMES_TAG, "active": "true", "closed": "false", "limit": 100, "offset": offset},
        timeout=aiohttp.ClientTimeout(total=30)
    ) as resp:
        return await resp.json()


async def main():
    neg_risk_map = {}
    slug_map = {}
    
    async with aiohttp.ClientSession() as session:
        # First request to estimate total pages
        first_page = await fetch_page(session, 0)
        if not first_page:
            return
        
        # Process first page
        all_events = first_page
        
        # Fetch remaining pages concurrently
        if len(first_page) == 100:
            # Optimistically fetch next several pages in parallel
            offsets = list(range(100, 2000, 100))  # adjust max based on typical event count
            
            sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
            
            async def bounded_fetch(offset):
                async with sem:
                    return await fetch_page(session, offset)
            
            tasks = [bounded_fetch(o) for o in offsets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list) and result:
                    all_events.extend(result)
                elif isinstance(result, list) and not result:
                    break  # empty page, we're done
        
        # Process all events
        for event in all_events:
            neg_risk = event.get("negRisk", False)
            slug = event.get("slug", "")
            for market in event.get("markets", []):
                token_ids = json.loads(market.get("clobTokenIds", "[]"))
                for tid in token_ids:
                    if tid:
                        neg_risk_map[tid] = neg_risk
                        if slug:
                            slug_map[tid] = slug

    Path(CACHE_FILE).write_text(json.dumps(neg_risk_map))
    Path(SLUG_CACHE_FILE).write_text(json.dumps(slug_map))

    print(f"Cached {len(neg_risk_map)} tokens, {len(slug_map)} slugs")


if __name__ == "__main__":
    asyncio.run(main())