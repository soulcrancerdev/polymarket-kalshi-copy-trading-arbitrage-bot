#!/usr/bin/env python3
"""
Fetch Ligue 1 market tokens for buffer chasing

CRONTAB ENTRY (add to crontab -e):
# Update Ligue 1 markets cache every 30 minutes
*/30 * * * * cd <PROJECT_ROOT>/rust_clob_client && python3 scripts/fetch_ligue1.py > /tmp/ligue1_cache_update.log 2>&1
"""

import json
import urllib.request
from datetime import datetime

def fetch_ligue1_tokens():
    """Fetch all Ligue 1 market tokens"""

    url = "https://gamma-api.polymarket.com/events?tag_id=102070&active=true&closed=false&limit=100"

    print("Fetching Ligue 1 markets from Polymarket...")

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    })

    with urllib.request.urlopen(req) as response:
        events = json.loads(response.read().decode('utf-8'))

    print(f"Found {len(events)} Ligue 1 events")

    all_tokens = set()

    for event in events:
        markets = event.get('markets', [])

        for market in markets:
            if market.get('active'):
                clob_tokens_str = market.get('clobTokenIds', '[]')

                try:
                    tokens = json.loads(clob_tokens_str)
                    for token in tokens:
                        if isinstance(token, str) and len(token) > 20:
                            all_tokens.add(token)
                except:
                    pass

    # Save as simple list for Rust to load
    token_list = sorted(list(all_tokens))

    with open('.ligue1_tokens.json', 'w') as f:
        json.dump(token_list, f, indent=2)

    print(f"Saved {len(token_list)} tokens to .ligue1_tokens.json")
    print(f"Updated: {datetime.now().isoformat()}")

    return token_list

if __name__ == "__main__":
    tokens = fetch_ligue1_tokens()
    print(f"\nLigue 1 cache ready with {len(tokens)} tokens")
