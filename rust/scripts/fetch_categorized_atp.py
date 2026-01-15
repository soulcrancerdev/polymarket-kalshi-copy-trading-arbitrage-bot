#!/usr/bin/env python3
"""
Fetch and categorize ATP markets by type

CRONTAB ENTRY (add to crontab -e):
# Update ATP markets cache every 4 hours
0 */4 * * * cd <PROJECT_ROOT>/rust_clob_client && python3 scripts/fetch_categorized_atp.py > /tmp/atp_cache_update.log 2>&1
"""

import json
import urllib.request
import re
from datetime import datetime

def categorize_market(question, slug):
    """Categorize market based on question text"""
    q_lower = question.lower()
    
    # Tournament winner markets
    if 'winner' in q_lower and 'finals' in q_lower:
        return 'tournament_winner'
    
    # Set handicap markets
    if 'set handicap' in q_lower or ('handicap:' in q_lower and '(' in question):
        return 'set_handicap'
    
    # Game totals (Match O/U)
    if 'match o/u' in q_lower or ('o/u' in q_lower and any(x in question for x in ['36.5', '37.5', '38.5', '39.5', '40.5'])):
        return 'game_totals'
    
    # Set totals
    if 'total sets' in q_lower or ('set' in q_lower and 'o/u' in q_lower):
        return 'set_totals'
    
    # Moneyline (main match winner)
    if (' vs ' in question or ' vs. ' in question) and 'handicap' not in q_lower and 'o/u' not in q_lower:
        return 'moneyline'
    
    return 'other'

def fetch_categorized_atp():
    """Fetch and categorize all ATP markets"""
    
    url = "https://gamma-api.polymarket.com/events?tag_id=864&active=true&closed=false&limit=100"
    
    print("Fetching ATP markets from Polymarket...")
    
    # Add headers to avoid 403 error
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    })
    
    with urllib.request.urlopen(req) as response:
        events = json.loads(response.read().decode('utf-8'))
    
    print(f"Found {len(events)} ATP events")
    
    # Categorized structure
    categorized = {
        'moneyline': [],
        'set_handicap': [],
        'game_totals': [],
        'set_totals': [],
        'tournament_winner': [],
        'other': []
    }
    
    all_tokens = set()
    
    for event in events:
        slug = event.get('slug', '')
        title = event.get('title', '')
        markets = event.get('markets', [])
        
        for market in markets:
            if market.get('active'):
                question = market.get('question', '')
                clob_tokens_str = market.get('clobTokenIds', '[]')
                
                try:
                    tokens = json.loads(clob_tokens_str)
                    category = categorize_market(question, slug)
                    
                    for token in tokens:
                        if isinstance(token, str) and len(token) > 20:
                            all_tokens.add(token)
                            categorized[category].append(token)
                except:
                    pass
    
    # Print summary
    print("\nMarket Type Distribution:")
    print("=" * 60)
    for cat, tokens in categorized.items():
        if tokens:
            print(f"{cat:20} : {len(tokens):4} tokens")
    
    # Save categorized cache
    cache_data = {
        'total_tokens': len(all_tokens),
        'updated': datetime.now().isoformat(),
        'source': 'gamma-api tag_id=864 (ATP)',
        'categories': {
            cat: sorted(list(set(tokens)))  # Remove duplicates and sort
            for cat, tokens in categorized.items()
        },
        'category_counts': {
            cat: len(set(tokens))
            for cat, tokens in categorized.items()
        },
        'note': 'ATP markets categorized by type for different buffer strategies'
    }
    
    with open('.atp_markets_categorized.json', 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    print(f"\nSaved to .atp_markets_categorized.json")
    print(f"Total unique tokens: {len(all_tokens)}")
    
    # Also create a simple mapping file for Rust
    token_to_category = {}
    for cat, tokens in categorized.items():
        for token in tokens:
            token_to_category[token] = cat
    
    with open('.atp_token_categories.json', 'w') as f:
        json.dump(token_to_category, f, indent=2)
    
    return cache_data

if __name__ == "__main__":
    cache = fetch_categorized_atp()
    
    print("\n" + "=" * 60)
    print("ATP MARKETS CATEGORIZATION COMPLETE")
    print("=" * 60)
    print("\nYou can now apply different buffers per category:")
    print("  moneyline        : +$0.02 buffer")
    print("  set_handicap     : +$0.03 buffer")
    print("  game_totals      : +$0.02 buffer")
    print("  set_totals       : +$0.025 buffer")
    print("  tournament_winner: +$0.01 buffer")