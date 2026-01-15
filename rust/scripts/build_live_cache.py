#!/usr/bin/env python3
"""
Fetch live status for all active sports markets from Gamma API.

CRONTAB ENTRY (add to crontab -e):
# Update live cache every 2 minutes
*/2 * * * * cd <PROJECT_ROOT>/rust_clob_client && python3 scripts/build_live_cache.py >> /tmp/live_cache.log 2>&1
"""
import json
import urllib.request
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"

def fetch_all_events():
    """Fetch ALL sports events with pagination"""
    all_events = []
    offset = 0
    limit = 500

    while True:
        url = f"{GAMMA_API}/events?tag_id=1&active=true&closed=false&limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                events = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"Error fetching events at offset {offset}: {e}")
            break

        if not events:
            break

        all_events.extend(events)

        if len(events) < limit:
            break
        offset += limit

    return all_events

def main():
    events = fetch_all_events()

    if not events:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: No events fetched")
        return

    live_map = {}
    live_count = 0
    not_live_count = 0

    for event in events:
        is_live = event.get("live", False)

        for market in event.get("markets", []):
            if not market.get("active"):
                continue
            clob_tokens_str = market.get("clobTokenIds", "[]")
            try:
                tokens = json.loads(clob_tokens_str) if isinstance(clob_tokens_str, str) else clob_tokens_str
                for token in tokens:
                    if isinstance(token, str) and len(token) > 20:
                        live_map[token] = is_live
                        if is_live:
                            live_count += 1
                        else:
                            not_live_count += 1
            except:
                pass

    # Save the cache
    with open(".live_cache.json", "w") as f:
        json.dump(live_map, f)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Events: {len(events)} | Live: {live_count} | Not live: {not_live_count} | Total tokens: {len(live_map)}")

if __name__ == "__main__":
    main()
