#!/usr/bin/env python3
"""
Divergence Monitor Server

Continuously monitors PNL divergence between copier and whale,
stores data in SQLite, and serves a web dashboard.

Run with: python divergence_server.py
Then open: http://localhost:8765

For background operation:
    screen -S divergence -dm python divergence_server.py
    # Or use the start script: ./start_divergence_monitor.sh
"""

import asyncio
import json
import sqlite3
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiohttp
from aiohttp import web
import logging

# =============================================================================
# CONFIGURATION
# =============================================================================
USER_1_ADDRESS = ""  # Copier (You) - Set your address here
USER_2_ADDRESS = ""  # Whale to copy - Set target address here

USER_1_LABEL = "You"
USER_2_LABEL = "swisstony"

# From a_poly_trade_optimized/rust_clob_client/src/config.rs
SCALING_RATIO = 0.08  # 8%

DATA_API_BASE = "https://data-api.polymarket.com"
USER_PNL_API = "https://user-pnl-api.polymarket.com/user-pnl"
DB_PATH = Path(__file__).parent / "divergence_data.db"
WEB_PORT = 8765
FETCH_INTERVAL = 60  # seconds

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE
# =============================================================================
def init_db():
    """Initialize SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user1_value REAL,
            user1_pnl REAL,
            user1_volume REAL,
            user1_rank INTEGER,
            user2_value REAL,
            user2_pnl REAL,
            user2_volume REAL,
            user2_rank INTEGER,
            expected_pnl REAL,
            pnl_vs_expected REAL,
            pnl_efficiency REAL,
            scaling_ratio REAL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON snapshots(timestamp)
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


def save_snapshot(data: Dict[str, Any]):
    """Save a snapshot to the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO snapshots (
            timestamp, user1_value, user1_pnl, user1_volume, user1_rank,
            user2_value, user2_pnl, user2_volume, user2_rank,
            expected_pnl, pnl_vs_expected, pnl_efficiency, scaling_ratio
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['timestamp'],
        data['user1_value'], data['user1_pnl'], data['user1_volume'], data['user1_rank'],
        data['user2_value'], data['user2_pnl'], data['user2_volume'], data['user2_rank'],
        data['expected_pnl'], data['pnl_vs_expected'], data['pnl_efficiency'], data['scaling_ratio']
    ))
    conn.commit()
    conn.close()


def get_snapshots(hours: int = 24) -> List[Dict]:
    """Get snapshots from the last N hours."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT * FROM snapshots WHERE timestamp > ? ORDER BY timestamp ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_latest_snapshot() -> Optional[Dict]:
    """Get the most recent snapshot."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# DATA FETCHING
# =============================================================================
async def fetch_user_data(session: aiohttp.ClientSession, address: str) -> Dict:
    """Fetch portfolio value and rolling 24-hour PNL for a user."""
    result = {
        'value': None,
        'pnl': None,
        'volume': None,
        'rank': None,
    }

    # Fetch value
    try:
        async with session.get(
            f"{DATA_API_BASE}/value",
            params={"user": address},
            timeout=15
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and len(data) > 0:
                    result['value'] = float(data[0].get("value", 0))
    except Exception as e:
        logger.error(f"Error fetching value for {address[:10]}: {e}")

    # Fetch rolling 24-hour PNL from user-pnl-api (matches frontend)
    try:
        async with session.get(
            USER_PNL_API,
            params={
                "user_address": address,
                "interval": "1d",   # 1 day of data
                "fidelity": "1h"    # hourly data points
            },
            timeout=15
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Data is array of {"t": timestamp, "p": cumulative_pnl}
                # Rolling 24h PNL = latest p - earliest p
                if data and len(data) >= 2:
                    sorted_data = sorted(data, key=lambda x: x.get("t", 0))
                    earliest_pnl = float(sorted_data[0].get("p", 0))
                    latest_pnl = float(sorted_data[-1].get("p", 0))
                    result['pnl'] = latest_pnl - earliest_pnl
                elif data and len(data) == 1:
                    result['pnl'] = 0.0
    except Exception as e:
        logger.error(f"Error fetching rolling PNL for {address[:10]}: {e}")

    return result


async def fetch_all_positions(session: aiohttp.ClientSession, address: str) -> List[Dict]:
    """Fetch ALL positions for a user (paginated)."""
    all_positions = []
    offset = 0
    limit = 100

    while True:
        try:
            async with session.get(
                f"{DATA_API_BASE}/positions",
                params={
                    "user": address,
                    "sizeThreshold": "0.1",
                    "limit": limit,
                    "offset": offset,
                },
                timeout=30
            ) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data:
                    break
                all_positions.extend(data)
                if len(data) < limit:
                    break
                offset += limit
        except Exception as e:
            logger.error(f"Error fetching positions for {address[:10]} at offset {offset}: {e}")
            break

    return all_positions


def is_market_active(end_date_str: Optional[str]) -> bool:
    """Check if a market is still active (end date hasn't passed)."""
    if not end_date_str:
        return True  # No end date means assume active
    try:
        # Parse ISO format date (e.g., "2024-12-20T00:00:00Z")
        end_date_str = end_date_str.replace('Z', '+00:00')
        end_date = datetime.fromisoformat(end_date_str)
        now = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.now()
        return end_date > now
    except (ValueError, TypeError):
        return True  # If we can't parse, assume active


async def compare_positions() -> Dict:
    """
    Compare positions between whale and copier.
    Returns positions ranked by fill rate deviation from expected.
    Only includes active markets (end date hasn't passed).
    """
    async with aiohttp.ClientSession() as session:
        # Fetch positions for both users in parallel
        whale_positions, copier_positions = await asyncio.gather(
            fetch_all_positions(session, USER_2_ADDRESS),
            fetch_all_positions(session, USER_1_ADDRESS)
        )

    # Index copier positions by asset (token ID)
    copier_by_asset = {p['asset']: p for p in copier_positions}

    # Compare each whale position to copier's (only active markets)
    comparisons = []

    for whale_pos in whale_positions:
        asset = whale_pos.get('asset')
        if not asset:
            continue

        # Skip closed/ended markets
        if not is_market_active(whale_pos.get('endDate')):
            continue

        whale_size = float(whale_pos.get('size', 0) or 0)
        if whale_size <= 0:
            continue

        expected_size = whale_size * SCALING_RATIO
        copier_pos = copier_by_asset.get(asset)

        if copier_pos:
            actual_size = float(copier_pos.get('size', 0) or 0)
            fill_rate = actual_size / whale_size if whale_size > 0 else 0
            expected_fill_rate = SCALING_RATIO
            fill_rate_deviation = fill_rate - expected_fill_rate
            size_deviation = actual_size - expected_size
            size_deviation_pct = (size_deviation / expected_size * 100) if expected_size > 0 else 0

            # Calculate PNL impact of deviation
            cur_price = float(whale_pos.get('curPrice', 0) or 0)
            avg_price = float(copier_pos.get('avgPrice', 0) or 0)
            pnl_per_share = cur_price - avg_price if avg_price > 0 else 0
            deviation_pnl_impact = size_deviation * pnl_per_share

            copier_data = {
                'size': actual_size,
                'avgPrice': float(copier_pos.get('avgPrice', 0) or 0),
                'currentValue': float(copier_pos.get('currentValue', 0) or 0),
                'cashPnl': float(copier_pos.get('cashPnl', 0) or 0),
            }
        else:
            # Copier doesn't have this position
            actual_size = 0
            fill_rate = 0
            fill_rate_deviation = -SCALING_RATIO  # Missed entirely
            size_deviation = -expected_size
            size_deviation_pct = -100
            deviation_pnl_impact = 0
            copier_data = None

        comparisons.append({
            'asset': asset,
            'title': whale_pos.get('title', 'Unknown'),
            'slug': whale_pos.get('slug', ''),
            'outcome': whale_pos.get('outcome', ''),
            'icon': whale_pos.get('icon', ''),
            'endDate': whale_pos.get('endDate'),
            'whale': {
                'size': whale_size,
                'avgPrice': float(whale_pos.get('avgPrice', 0) or 0),
                'curPrice': float(whale_pos.get('curPrice', 0) or 0),
                'currentValue': float(whale_pos.get('currentValue', 0) or 0),
                'cashPnl': float(whale_pos.get('cashPnl', 0) or 0),
            },
            'copier': copier_data,
            'expected_size': expected_size,
            'actual_size': actual_size,
            'fill_rate': fill_rate,
            'expected_fill_rate': SCALING_RATIO,
            'fill_rate_deviation': fill_rate_deviation,
            'size_deviation': size_deviation,
            'size_deviation_pct': size_deviation_pct,
            'deviation_pnl_impact': deviation_pnl_impact,
            'has_position': copier_pos is not None,
        })

    # Also find positions copier has that whale doesn't (shouldn't happen in pure copy)
    whale_assets = {p['asset'] for p in whale_positions if p.get('asset')}
    extra_positions = []
    for copier_pos in copier_positions:
        asset = copier_pos.get('asset')
        if asset and asset not in whale_assets:
            extra_positions.append({
                'asset': asset,
                'title': copier_pos.get('title', 'Unknown'),
                'slug': copier_pos.get('slug', ''),
                'outcome': copier_pos.get('outcome', ''),
                'icon': copier_pos.get('icon', ''),
                'size': float(copier_pos.get('size', 0) or 0),
                'currentValue': float(copier_pos.get('currentValue', 0) or 0),
                'cashPnl': float(copier_pos.get('cashPnl', 0) or 0),
            })

    # Sort by: 1) Whale size (descending), 2) Fill rate deviation (ascending, so most negative first)
    comparisons.sort(key=lambda x: (-x['whale']['size'], x['fill_rate_deviation']))

    # Calculate summary stats
    total_whale_positions = len(whale_positions)
    matched_positions = sum(1 for c in comparisons if c['has_position'])
    missed_positions = total_whale_positions - matched_positions

    avg_fill_rate = sum(c['fill_rate'] for c in comparisons) / len(comparisons) if comparisons else 0
    total_deviation_pnl = sum(c['deviation_pnl_impact'] for c in comparisons)

    # Categorize
    overfilled = [c for c in comparisons if c['fill_rate_deviation'] > 0.01]  # >1% over
    underfilled = [c for c in comparisons if c['fill_rate_deviation'] < -0.01 and c['has_position']]
    missed = [c for c in comparisons if not c['has_position']]
    on_target = [c for c in comparisons if abs(c['fill_rate_deviation']) <= 0.01]

    # =========================================================================
    # NEW ANALYTICS: PNL breakdown by fill status
    # =========================================================================
    def calc_pnl_stats(positions):
        """Calculate PNL stats for a group of positions."""
        if not positions:
            return {'count': 0, 'whale_pnl': 0, 'copier_pnl': 0, 'avg_whale_pnl': 0}
        whale_pnl = sum(p['whale']['cashPnl'] for p in positions)
        copier_pnl = sum(p['copier']['cashPnl'] for p in positions if p['copier'])
        return {
            'count': len(positions),
            'whale_pnl': whale_pnl,
            'copier_pnl': copier_pnl,
            'avg_whale_pnl': whale_pnl / len(positions) if positions else 0,
        }

    pnl_by_fill_status = {
        'overfilled': calc_pnl_stats(overfilled),
        'underfilled': calc_pnl_stats(underfilled),
        'on_target': calc_pnl_stats(on_target),
        'missed': calc_pnl_stats(missed),
    }

    # =========================================================================
    # NEW ANALYTICS: PNL and fill rate by size bucket
    # =========================================================================
    size_buckets = [500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 10000, float('inf')]
    bucket_labels = ['0-500', '500-1k', '1k-1.5k', '1.5k-2k', '2k-2.5k', '2.5k-3k', '3k-4k', '4k-5k', '5k-10k', '10k+']

    def get_bucket_idx(size):
        for i, threshold in enumerate(size_buckets):
            if size < threshold:
                return i
        return len(size_buckets) - 1

    # Initialize bucket stats
    bucket_stats = []
    for i, label in enumerate(bucket_labels):
        bucket_stats.append({
            'label': label,
            'min_size': 0 if i == 0 else size_buckets[i-1],
            'max_size': size_buckets[i],
            'positions': [],
        })

    # Assign positions to buckets
    for c in comparisons:
        idx = get_bucket_idx(c['whale']['size'])
        bucket_stats[idx]['positions'].append(c)

    # Calculate stats per bucket
    size_bucket_analysis = []
    for bucket in bucket_stats:
        positions = bucket['positions']
        if not positions:
            continue

        whale_pnl = sum(p['whale']['cashPnl'] for p in positions)
        copier_pnl = sum(p['copier']['cashPnl'] for p in positions if p['copier'])
        total_whale_size = sum(p['whale']['size'] for p in positions)
        total_copier_size = sum(p['actual_size'] for p in positions)
        avg_fill_rate = total_copier_size / total_whale_size if total_whale_size > 0 else 0

        # Count winners/losers for whale
        whale_winners = sum(1 for p in positions if p['whale']['cashPnl'] > 0)
        whale_losers = sum(1 for p in positions if p['whale']['cashPnl'] < 0)

        size_bucket_analysis.append({
            'label': bucket['label'],
            'count': len(positions),
            'whale_pnl': whale_pnl,
            'copier_pnl': copier_pnl,
            'avg_whale_pnl': whale_pnl / len(positions),
            'total_whale_size': total_whale_size,
            'total_copier_size': total_copier_size,
            'avg_fill_rate': avg_fill_rate,
            'fill_rate_vs_target': (avg_fill_rate / SCALING_RATIO * 100) if SCALING_RATIO > 0 else 0,
            'whale_winners': whale_winners,
            'whale_losers': whale_losers,
            'whale_win_rate': whale_winners / len(positions) * 100 if positions else 0,
        })

    return {
        'timestamp': datetime.now().isoformat(),
        'scaling_ratio': SCALING_RATIO,
        'summary': {
            'whale_positions': total_whale_positions,
            'copier_positions': len(copier_positions),
            'matched_positions': matched_positions,
            'missed_positions': missed_positions,
            'extra_positions': len(extra_positions),
            'avg_fill_rate': avg_fill_rate,
            'expected_fill_rate': SCALING_RATIO,
            'fill_rate_efficiency': (avg_fill_rate / SCALING_RATIO * 100) if SCALING_RATIO > 0 else 0,
            'total_deviation_pnl': total_deviation_pnl,
            'overfilled_count': len(overfilled),
            'underfilled_count': len(underfilled),
            'missed_count': len(missed),
            'on_target_count': len(on_target),
        },
        'comparisons': comparisons,
        'extra_positions': extra_positions,
        'user1_label': USER_1_LABEL,
        'user2_label': USER_2_LABEL,
        # New analytics
        'pnl_by_fill_status': pnl_by_fill_status,
        'size_bucket_analysis': size_bucket_analysis,
    }


async def fetch_and_store():
    """Fetch data for both users and store in database."""
    async with aiohttp.ClientSession() as session:
        user1_data, user2_data = await asyncio.gather(
            fetch_user_data(session, USER_1_ADDRESS),
            fetch_user_data(session, USER_2_ADDRESS)
        )

    now = datetime.now().isoformat()

    # Calculate expected metrics
    expected_pnl = None
    pnl_vs_expected = None
    pnl_efficiency = None

    if user2_data['pnl'] is not None:
        expected_pnl = user2_data['pnl'] * SCALING_RATIO

        if user1_data['pnl'] is not None:
            pnl_vs_expected = user1_data['pnl'] - expected_pnl

            if user2_data['pnl'] != 0:
                actual_ratio = user1_data['pnl'] / user2_data['pnl']
                pnl_efficiency = (actual_ratio / SCALING_RATIO) * 100

    snapshot = {
        'timestamp': now,
        'user1_value': user1_data['value'],
        'user1_pnl': user1_data['pnl'],
        'user1_volume': user1_data['volume'],
        'user1_rank': user1_data['rank'],
        'user2_value': user2_data['value'],
        'user2_pnl': user2_data['pnl'],
        'user2_volume': user2_data['volume'],
        'user2_rank': user2_data['rank'],
        'expected_pnl': expected_pnl,
        'pnl_vs_expected': pnl_vs_expected,
        'pnl_efficiency': pnl_efficiency,
        'scaling_ratio': SCALING_RATIO,
    }

    save_snapshot(snapshot)

    # Log summary
    if pnl_vs_expected is not None:
        status = "OUTPERFORM" if pnl_vs_expected > 0 else "UNDERPERFORM"
        logger.info(
            f"{USER_1_LABEL}: ${user1_data['pnl']:+,.2f} | "
            f"{USER_2_LABEL}: ${user2_data['pnl']:+,.2f} | "
            f"Expected: ${expected_pnl:+,.2f} | "
            f"vs Expected: ${pnl_vs_expected:+,.2f} ({status})"
        )
    else:
        logger.info(f"Snapshot saved (some data unavailable)")

    return snapshot


# =============================================================================
# BACKGROUND TASK
# =============================================================================
async def background_fetcher():
    """Continuously fetch data in the background."""
    logger.info(f"Starting background fetcher (interval: {FETCH_INTERVAL}s)")
    while True:
        try:
            await fetch_and_store()
        except Exception as e:
            logger.error(f"Error in background fetch: {e}")
        await asyncio.sleep(FETCH_INTERVAL)


# =============================================================================
# WEB SERVER
# =============================================================================
async def handle_index(request):
    """Serve the main dashboard page."""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')


async def handle_api_latest(request):
    """API endpoint for latest snapshot."""
    snapshot = get_latest_snapshot()
    return web.json_response(snapshot or {})


async def handle_api_history(request):
    """API endpoint for historical data."""
    hours = int(request.query.get('hours', 24))
    snapshots = get_snapshots(hours=hours)
    return web.json_response({
        'snapshots': snapshots,
        'scaling_ratio': SCALING_RATIO,
        'user1_label': USER_1_LABEL,
        'user2_label': USER_2_LABEL,
    })


async def handle_api_config(request):
    """API endpoint for configuration."""
    return web.json_response({
        'scaling_ratio': SCALING_RATIO,
        'user1_address': USER_1_ADDRESS,
        'user2_address': USER_2_ADDRESS,
        'user1_label': USER_1_LABEL,
        'user2_label': USER_2_LABEL,
        'fetch_interval': FETCH_INTERVAL,
    })


async def handle_api_positions(request):
    """API endpoint for position comparison."""
    try:
        data = await compare_positions()
        return web.json_response(data)
    except Exception as e:
        logger.error(f"Error comparing positions: {e}")
        return web.json_response({'error': str(e)}, status=500)


# =============================================================================
# HTML TEMPLATE
# =============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PNL Divergence Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 28px;
            color: #fff;
            margin-bottom: 5px;
        }
        .header .subtitle {
            color: #888;
            font-size: 14px;
        }
        .header .scaling {
            color: #4ade80;
            font-weight: bold;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a2a2a;
        }
        .card h3 {
            color: #888;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        .card .value {
            font-size: 32px;
            font-weight: bold;
            color: #fff;
        }
        .card .value.positive { color: #4ade80; }
        .card .value.negative { color: #f87171; }
        .card .subtext {
            color: #666;
            font-size: 12px;
            margin-top: 5px;
        }
        .comparison {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        .user-card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a2a2a;
        }
        .user-card h2 {
            font-size: 18px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .user-card.user1 h2 { color: #60a5fa; }
        .user-card.user2 h2 { color: #fbbf24; }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #2a2a2a;
        }
        .metric:last-child { border-bottom: none; }
        .metric .label { color: #888; }
        .metric .val { font-weight: 600; }
        .chart-container {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a2a2a;
            margin-bottom: 20px;
        }
        .chart-container h3 {
            color: #fff;
            margin-bottom: 15px;
            font-size: 16px;
        }
        .chart-wrapper {
            height: 300px;
        }
        .status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #1a1a1a;
            border-top: 1px solid #2a2a2a;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }
        .status-bar .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #4ade80;
            display: inline-block;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .time-selector {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            justify-content: center;
        }
        .time-selector button {
            background: #2a2a2a;
            border: none;
            color: #888;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .time-selector button:hover {
            background: #3a3a3a;
            color: #fff;
        }
        .time-selector button.active {
            background: #4ade80;
            color: #000;
        }
        .efficiency-bar {
            height: 20px;
            background: #2a2a2a;
            border-radius: 10px;
            overflow: hidden;
            margin-top: 10px;
        }
        .efficiency-fill {
            height: 100%;
            transition: width 0.3s;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>PNL Divergence Monitor</h1>
        <p class="subtitle">
            Copy Trading Efficiency | Target Ratio: <span class="scaling" id="scaling-ratio">8%</span>
        </p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>PNL vs Expected</h3>
            <div class="value" id="pnl-vs-expected">--</div>
            <div class="subtext">Actual - Expected PNL</div>
        </div>
        <div class="card">
            <h3>Copy Efficiency</h3>
            <div class="value" id="efficiency">--</div>
            <div class="efficiency-bar">
                <div class="efficiency-fill" id="efficiency-bar" style="width: 0%; background: #4ade80;"></div>
            </div>
        </div>
        <div class="card">
            <h3>Expected PNL</h3>
            <div class="value" id="expected-pnl">--</div>
            <div class="subtext">Whale PNL × Scaling Ratio</div>
        </div>
        <div class="card">
            <h3>Status</h3>
            <div class="value" id="status">--</div>
            <div class="subtext" id="status-detail"></div>
        </div>
    </div>

    <div class="comparison">
        <div class="user-card user1">
            <h2><span>●</span> <span id="user1-label">You</span> (Copier)</h2>
            <div class="metric">
                <span class="label">Portfolio Value</span>
                <span class="val" id="user1-value">--</span>
            </div>
            <div class="metric">
                <span class="label">Rolling 24h PNL</span>
                <span class="val" id="user1-pnl">--</span>
            </div>
        </div>
        <div class="user-card user2">
            <h2><span>●</span> <span id="user2-label">swisstony</span> (Whale)</h2>
            <div class="metric">
                <span class="label">Portfolio Value</span>
                <span class="val" id="user2-value">--</span>
            </div>
            <div class="metric">
                <span class="label">Rolling 24h PNL</span>
                <span class="val" id="user2-pnl">--</span>
            </div>
        </div>
    </div>

    <div class="time-selector">
        <button onclick="loadHistory(1)" id="btn-1h">1H</button>
        <button onclick="loadHistory(6)" id="btn-6h">6H</button>
        <button onclick="loadHistory(24)" class="active" id="btn-24h">24H</button>
        <button onclick="loadHistory(72)" id="btn-72h">3D</button>
        <button onclick="loadHistory(168)" id="btn-168h">7D</button>
    </div>

    <div class="chart-container">
        <h3>PNL vs Expected Over Time</h3>
        <div class="chart-wrapper">
            <canvas id="divergenceChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>Rolling 24h PNL Comparison</h3>
        <div class="chart-wrapper">
            <canvas id="pnlChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>Copy Efficiency Over Time</h3>
        <div class="chart-wrapper">
            <canvas id="efficiencyChart"></canvas>
        </div>
    </div>

    <!-- Position Fill Rate Comparison Section -->
    <div class="section-header" style="margin: 40px 0 20px 0;">
        <h2 style="color: #fff; font-size: 22px; text-align: center;">Position Fill Rate Analysis</h2>
        <p style="color: #888; text-align: center; font-size: 14px;">Comparing actual position sizes vs expected (Whale × 8%)</p>
        <div style="text-align: center; margin-top: 15px;">
            <button onclick="loadPositions()" class="refresh-btn" style="background: #3a3a3a; border: none; color: #fff; padding: 10px 20px; border-radius: 6px; cursor: pointer;">
                Refresh Position Data
            </button>
        </div>
    </div>

    <div class="grid" id="position-summary" style="margin-bottom: 20px;">
        <div class="card">
            <h3>Matched Positions</h3>
            <div class="value" id="matched-positions">--</div>
            <div class="subtext">Positions where you have a copy</div>
        </div>
        <div class="card">
            <h3>Avg Fill Rate</h3>
            <div class="value" id="avg-fill-rate">--</div>
            <div class="subtext">Expected: <span id="expected-fill-rate">8%</span></div>
        </div>
        <div class="card">
            <h3>Fill Rate Efficiency</h3>
            <div class="value" id="fill-efficiency">--</div>
            <div class="subtext">Actual / Expected fill rate</div>
        </div>
        <div class="card">
            <h3>Deviation PNL Impact</h3>
            <div class="value" id="deviation-pnl">--</div>
            <div class="subtext">PNL from over/under fills</div>
        </div>
    </div>

    <div class="grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 20px;">
        <div class="card" style="border-left: 3px solid #4ade80;">
            <h3>On Target (±1%)</h3>
            <div class="value" id="on-target-count" style="font-size: 24px;">--</div>
        </div>
        <div class="card" style="border-left: 3px solid #60a5fa;">
            <h3>Overfilled</h3>
            <div class="value" id="overfilled-count" style="font-size: 24px;">--</div>
        </div>
        <div class="card" style="border-left: 3px solid #fbbf24;">
            <h3>Underfilled</h3>
            <div class="value" id="underfilled-count" style="font-size: 24px;">--</div>
        </div>
        <div class="card" style="border-left: 3px solid #f87171;">
            <h3>Missed</h3>
            <div class="value" id="missed-count" style="font-size: 24px;">--</div>
        </div>
    </div>

    <div class="chart-container">
        <h3>Position Fill Rate Deviations <span id="positions-count" style="color: #888; font-size: 14px;"></span></h3>
        <div style="height: 500px; overflow-y: auto;" id="positions-table">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead style="position: sticky; top: 0; background: #1a1a1a; z-index: 10;">
                    <tr style="border-bottom: 1px solid #3a3a3a;">
                        <th style="text-align: left; padding: 10px; color: #888;">Market</th>
                        <th style="text-align: right; padding: 10px; color: #888; cursor: pointer; user-select: none;" onclick="toggleSort('whale_size')" id="th-whale-size">
                            Whale Size <span id="sort-whale-size">▼</span>
                        </th>
                        <th style="text-align: right; padding: 10px; color: #888;">Expected</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Actual</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Fill Rate</th>
                        <th style="text-align: right; padding: 10px; color: #888; cursor: pointer; user-select: none;" onclick="toggleSort('deviation')" id="th-deviation">
                            Deviation <span id="sort-deviation">▲</span>
                        </th>
                        <th style="text-align: right; padding: 10px; color: #888; cursor: pointer; user-select: none;" onclick="toggleSort('pnl_impact')" id="th-pnl-impact">
                            PNL Impact <span id="sort-pnl-impact">▼</span>
                        </th>
                    </tr>
                </thead>
                <tbody id="positions-tbody">
                    <tr><td colspan="7" style="text-align: center; padding: 40px; color: #666;">Click "Refresh Position Data" to load</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- NEW: Performance Analysis Section -->
    <div class="section-header" style="margin: 40px 0 20px 0;">
        <h2 style="color: #fff; font-size: 22px; text-align: center;">Performance Analysis</h2>
        <p style="color: #888; text-align: center; font-size: 14px;">Understanding why you underperform: PNL breakdown by fill status and position size</p>
    </div>

    <!-- PNL by Fill Status -->
    <div class="chart-container" style="margin-bottom: 20px;">
        <h3>Whale PNL by Your Fill Status</h3>
        <p style="color: #888; font-size: 12px; margin-bottom: 15px;">Are you overfilling winners or losers?</p>
        <div id="pnl-by-fill-status">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="border-bottom: 1px solid #3a3a3a;">
                        <th style="text-align: left; padding: 10px; color: #888;">Fill Status</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Count</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Whale PNL</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Avg Whale PNL</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Your PNL</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Verdict</th>
                    </tr>
                </thead>
                <tbody id="fill-status-tbody">
                    <tr><td colspan="6" style="text-align: center; padding: 20px; color: #666;">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- PNL by Size Bucket -->
    <div class="chart-container" style="margin-bottom: 20px;">
        <h3>Whale PNL & Your Fill Rate by Position Size</h3>
        <p style="color: #888; font-size: 12px; margin-bottom: 15px;">Is the whale winning on large or small trades? What's your fill rate at each size?</p>
        <div style="max-height: 400px; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead style="position: sticky; top: 0; background: #1a1a1a;">
                    <tr style="border-bottom: 1px solid #3a3a3a;">
                        <th style="text-align: left; padding: 10px; color: #888;">Size Bucket</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Positions</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Whale PNL</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Whale Win%</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Your Fill Rate</th>
                        <th style="text-align: right; padding: 10px; color: #888;">vs Target</th>
                        <th style="text-align: right; padding: 10px; color: #888;">Impact</th>
                    </tr>
                </thead>
                <tbody id="size-bucket-tbody">
                    <tr><td colspan="7" style="text-align: center; padding: 20px; color: #666;">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Summary Insight -->
    <div class="chart-container" style="margin-bottom: 20px;">
        <h3>Key Insight</h3>
        <div id="performance-insight" style="padding: 20px; background: #2a2a2a; border-radius: 8px; font-size: 14px; line-height: 1.6;">
            <p style="color: #888;">Loading analysis...</p>
        </div>
    </div>

    <div class="status-bar" style="padding-bottom: 60px;">
        <div>
            <span class="dot"></span>
            <span>Live monitoring</span>
        </div>
        <div>Last updated: <span id="last-update">--</span></div>
    </div>

    <script>
        let divergenceChart, pnlChart, efficiencyChart;
        let currentHours = 24;

        // Position data and sort state
        let positionsData = [];
        let sortConfig = {
            primary: 'whale_size',      // 'whale_size', 'deviation', or 'pnl_impact'
            whale_size_desc: true,      // true = descending (largest first)
            deviation_asc: true,        // true = ascending (most negative first)
            pnl_impact_desc: true       // true = descending (largest positive first)
        };

        function formatMoney(val, showSign = false) {
            if (val === null || val === undefined) return '--';
            const sign = showSign && val >= 0 ? '+' : '';
            return sign + '$' + val.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }

        function formatPercent(val) {
            if (val === null || val === undefined) return '--';
            return val.toFixed(1) + '%';
        }

        function updateLatest(data) {
            if (!data || !data.timestamp) return;

            // Update PNL vs Expected
            const pnlVsExpected = document.getElementById('pnl-vs-expected');
            pnlVsExpected.textContent = formatMoney(data.pnl_vs_expected, true);
            pnlVsExpected.className = 'value ' + (data.pnl_vs_expected >= 0 ? 'positive' : 'negative');

            // Update Efficiency
            const eff = data.pnl_efficiency;
            document.getElementById('efficiency').textContent = formatPercent(eff);
            const effBar = document.getElementById('efficiency-bar');
            if (eff !== null) {
                const width = Math.min(Math.max(eff, 0), 200);
                effBar.style.width = (width / 2) + '%';
                effBar.style.background = eff >= 100 ? '#4ade80' : '#f87171';
            }

            // Update Expected PNL
            document.getElementById('expected-pnl').textContent = formatMoney(data.expected_pnl, true);

            // Update Status
            const status = document.getElementById('status');
            const statusDetail = document.getElementById('status-detail');
            if (data.pnl_vs_expected > 0) {
                status.textContent = 'OUTPERFORM';
                status.className = 'value positive';
                statusDetail.textContent = 'Beating expected by ' + formatMoney(data.pnl_vs_expected);
            } else if (data.pnl_vs_expected < 0) {
                status.textContent = 'UNDERPERFORM';
                status.className = 'value negative';
                statusDetail.textContent = 'Behind expected by ' + formatMoney(-data.pnl_vs_expected);
            } else {
                status.textContent = 'TRACKING';
                status.className = 'value';
                statusDetail.textContent = 'On target';
            }

            // Update User 1
            document.getElementById('user1-value').textContent = formatMoney(data.user1_value);
            const u1pnl = document.getElementById('user1-pnl');
            u1pnl.textContent = formatMoney(data.user1_pnl, true);
            u1pnl.style.color = data.user1_pnl >= 0 ? '#4ade80' : '#f87171';

            // Update User 2
            document.getElementById('user2-value').textContent = formatMoney(data.user2_value);
            const u2pnl = document.getElementById('user2-pnl');
            u2pnl.textContent = formatMoney(data.user2_pnl, true);
            u2pnl.style.color = data.user2_pnl >= 0 ? '#4ade80' : '#f87171';

            // Update timestamp
            const ts = new Date(data.timestamp);
            document.getElementById('last-update').textContent = ts.toLocaleTimeString();
        }

        function updateCharts(snapshots, labels) {
            const timestamps = snapshots.map(s => new Date(s.timestamp));

            // PNL vs Expected chart
            const divergenceData = snapshots.map(s => s.pnl_vs_expected);
            if (divergenceChart) {
                divergenceChart.data.labels = timestamps;
                divergenceChart.data.datasets[0].data = divergenceData;
                divergenceChart.update('none');
            } else {
                divergenceChart = new Chart(document.getElementById('divergenceChart'), {
                    type: 'line',
                    data: {
                        labels: timestamps,
                        datasets: [{
                            label: 'PNL vs Expected',
                            data: divergenceData,
                            borderColor: '#4ade80',
                            backgroundColor: 'rgba(74, 222, 128, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: {
                                type: 'time',
                                grid: { color: '#2a2a2a' },
                                ticks: { color: '#888' }
                            },
                            y: {
                                grid: { color: '#2a2a2a' },
                                ticks: {
                                    color: '#888',
                                    callback: v => '$' + v.toLocaleString()
                                }
                            }
                        }
                    }
                });
            }

            // PNL Comparison chart
            const user1Pnl = snapshots.map(s => s.user1_pnl);
            const user2Pnl = snapshots.map(s => s.user2_pnl);
            const expectedPnl = snapshots.map(s => s.expected_pnl);

            if (pnlChart) {
                pnlChart.data.labels = timestamps;
                pnlChart.data.datasets[0].data = user1Pnl;
                pnlChart.data.datasets[1].data = expectedPnl;
                pnlChart.data.datasets[2].data = user2Pnl;
                pnlChart.update('none');
            } else {
                pnlChart = new Chart(document.getElementById('pnlChart'), {
                    type: 'line',
                    data: {
                        labels: timestamps,
                        datasets: [
                            {
                                label: labels.user1_label + ' (Actual)',
                                data: user1Pnl,
                                borderColor: '#60a5fa',
                                tension: 0.3,
                                pointRadius: 0,
                            },
                            {
                                label: 'Expected (' + (labels.scaling_ratio * 100) + '%)',
                                data: expectedPnl,
                                borderColor: '#a78bfa',
                                borderDash: [5, 5],
                                tension: 0.3,
                                pointRadius: 0,
                            },
                            {
                                label: labels.user2_label + ' (Whale)',
                                data: user2Pnl,
                                borderColor: '#fbbf24',
                                tension: 0.3,
                                pointRadius: 0,
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                labels: { color: '#888' }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                grid: { color: '#2a2a2a' },
                                ticks: { color: '#888' }
                            },
                            y: {
                                grid: { color: '#2a2a2a' },
                                ticks: {
                                    color: '#888',
                                    callback: v => '$' + v.toLocaleString()
                                }
                            }
                        }
                    }
                });
            }

            // Efficiency chart
            const efficiencyData = snapshots.map(s => s.pnl_efficiency);
            if (efficiencyChart) {
                efficiencyChart.data.labels = timestamps;
                efficiencyChart.data.datasets[0].data = efficiencyData;
                efficiencyChart.update('none');
            } else {
                efficiencyChart = new Chart(document.getElementById('efficiencyChart'), {
                    type: 'line',
                    data: {
                        labels: timestamps,
                        datasets: [{
                            label: 'Copy Efficiency %',
                            data: efficiencyData,
                            borderColor: '#f472b6',
                            tension: 0.3,
                            pointRadius: 0,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: {
                                type: 'time',
                                grid: { color: '#2a2a2a' },
                                ticks: { color: '#888' }
                            },
                            y: {
                                grid: { color: '#2a2a2a' },
                                ticks: {
                                    color: '#888',
                                    callback: v => v.toFixed(0) + '%'
                                }
                            }
                        },
                        annotations: {
                            line1: {
                                type: 'line',
                                yMin: 100,
                                yMax: 100,
                                borderColor: '#4ade80',
                                borderDash: [5, 5],
                            }
                        }
                    }
                });
            }
        }

        async function loadHistory(hours) {
            currentHours = hours;

            // Update button states
            document.querySelectorAll('.time-selector button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.getElementById('btn-' + hours + 'h').classList.add('active');

            try {
                const resp = await fetch('/api/history?hours=' + hours);
                const data = await resp.json();

                if (data.snapshots && data.snapshots.length > 0) {
                    updateCharts(data.snapshots, data);

                    // Update labels if provided
                    if (data.user1_label) {
                        document.getElementById('user1-label').textContent = data.user1_label;
                    }
                    if (data.user2_label) {
                        document.getElementById('user2-label').textContent = data.user2_label;
                    }
                    if (data.scaling_ratio) {
                        document.getElementById('scaling-ratio').textContent = (data.scaling_ratio * 100) + '%';
                    }
                }
            } catch (e) {
                console.error('Error loading history:', e);
            }
        }

        async function loadLatest() {
            try {
                const resp = await fetch('/api/latest');
                const data = await resp.json();
                updateLatest(data);
            } catch (e) {
                console.error('Error loading latest:', e);
            }
        }

        // Position comparison functions
        function toggleSort(column) {
            if (column === 'whale_size') {
                if (sortConfig.primary === 'whale_size') {
                    // Toggle direction
                    sortConfig.whale_size_desc = !sortConfig.whale_size_desc;
                } else {
                    // Switch to whale_size as primary
                    sortConfig.primary = 'whale_size';
                }
            } else if (column === 'deviation') {
                if (sortConfig.primary === 'deviation') {
                    // Toggle direction
                    sortConfig.deviation_asc = !sortConfig.deviation_asc;
                } else {
                    // Switch to deviation as primary
                    sortConfig.primary = 'deviation';
                }
            } else if (column === 'pnl_impact') {
                if (sortConfig.primary === 'pnl_impact') {
                    // Toggle direction
                    sortConfig.pnl_impact_desc = !sortConfig.pnl_impact_desc;
                } else {
                    // Switch to pnl_impact as primary
                    sortConfig.primary = 'pnl_impact';
                }
            }
            updateSortIndicators();
            renderPositionsTable();
        }

        function updateSortIndicators() {
            const whaleEl = document.getElementById('sort-whale-size');
            const devEl = document.getElementById('sort-deviation');
            const pnlEl = document.getElementById('sort-pnl-impact');
            const whaleThEl = document.getElementById('th-whale-size');
            const devThEl = document.getElementById('th-deviation');
            const pnlThEl = document.getElementById('th-pnl-impact');

            // Reset styles
            whaleThEl.style.color = '#888';
            devThEl.style.color = '#888';
            pnlThEl.style.color = '#888';

            // Update arrows based on current direction settings
            whaleEl.textContent = sortConfig.whale_size_desc ? '▼' : '▲';
            devEl.textContent = sortConfig.deviation_asc ? '▲' : '▼';
            pnlEl.textContent = sortConfig.pnl_impact_desc ? '▼' : '▲';

            // Highlight the active sort column
            if (sortConfig.primary === 'whale_size') {
                whaleThEl.style.color = '#4ade80';
            } else if (sortConfig.primary === 'deviation') {
                devThEl.style.color = '#4ade80';
            } else if (sortConfig.primary === 'pnl_impact') {
                pnlThEl.style.color = '#4ade80';
            }
        }

        function sortPositions(comparisons) {
            return [...comparisons].sort((a, b) => {
                if (sortConfig.primary === 'whale_size') {
                    // Primary: whale size
                    const whaleA = a.whale.size;
                    const whaleB = b.whale.size;
                    if (whaleA !== whaleB) {
                        return sortConfig.whale_size_desc ? (whaleB - whaleA) : (whaleA - whaleB);
                    }
                    // Secondary: deviation
                    return sortConfig.deviation_asc ? (a.fill_rate_deviation - b.fill_rate_deviation) : (b.fill_rate_deviation - a.fill_rate_deviation);
                } else if (sortConfig.primary === 'deviation') {
                    // Primary: deviation
                    const devA = a.fill_rate_deviation;
                    const devB = b.fill_rate_deviation;
                    if (devA !== devB) {
                        return sortConfig.deviation_asc ? (devA - devB) : (devB - devA);
                    }
                    // Secondary: whale size
                    return sortConfig.whale_size_desc ? (b.whale.size - a.whale.size) : (a.whale.size - b.whale.size);
                } else if (sortConfig.primary === 'pnl_impact') {
                    // Primary: pnl impact
                    const pnlA = a.deviation_pnl_impact;
                    const pnlB = b.deviation_pnl_impact;
                    if (pnlA !== pnlB) {
                        return sortConfig.pnl_impact_desc ? (pnlB - pnlA) : (pnlA - pnlB);
                    }
                    // Secondary: whale size
                    return sortConfig.whale_size_desc ? (b.whale.size - a.whale.size) : (a.whale.size - b.whale.size);
                }
            });
        }

        function renderPositionsTable() {
            const tbody = document.getElementById('positions-tbody');

            if (positionsData.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #666;">No positions found</td></tr>';
                return;
            }

            const sorted = sortPositions(positionsData);
            let html = '';

            for (const c of sorted) {
                const fillRatePct = (c.fill_rate * 100).toFixed(2);
                const deviationPct = (c.fill_rate_deviation * 100).toFixed(2);
                const devColor = c.fill_rate_deviation > 0.01 ? '#60a5fa' :
                                 c.fill_rate_deviation < -0.01 ? (c.has_position ? '#fbbf24' : '#f87171') :
                                 '#4ade80';

                const statusIcon = !c.has_position ? '❌' :
                                   c.fill_rate_deviation > 0.01 ? '📈' :
                                   c.fill_rate_deviation < -0.01 ? '📉' : '✅';

                const pnlColor = c.deviation_pnl_impact >= 0 ? '#4ade80' : '#f87171';

                // Truncate title
                const title = c.title.length > 50 ? c.title.substring(0, 47) + '...' : c.title;
                const polymarketUrl = c.slug ? 'https://polymarket.com/event/' + c.slug : '#';

                html += '<tr style="border-bottom: 1px solid #2a2a2a;">' +
                    '<td style="padding: 10px; max-width: 300px;">' +
                        '<a href="' + polymarketUrl + '" target="_blank" style="color: #60a5fa; text-decoration: none;">' +
                            statusIcon + ' ' + title +
                        '</a>' +
                        '<div style="color: #666; font-size: 11px;">' + c.outcome + '</div>' +
                    '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + c.whale.size.toLocaleString(undefined, {maximumFractionDigits: 0}) + '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + c.expected_size.toLocaleString(undefined, {maximumFractionDigits: 0}) + '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + c.actual_size.toLocaleString(undefined, {maximumFractionDigits: 0}) + '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + fillRatePct + '%</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + devColor + ';">' + (c.fill_rate_deviation >= 0 ? '+' : '') + deviationPct + '%</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + pnlColor + ';">' + formatMoney(c.deviation_pnl_impact, true) + '</td>' +
                '</tr>';
            }
            tbody.innerHTML = html;
        }

        async function loadPositions() {
            const tbody = document.getElementById('positions-tbody');
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #888;">Loading positions...</td></tr>';

            try {
                const resp = await fetch('/api/positions');
                const data = await resp.json();

                if (data.error) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #f87171;">Error: ' + data.error + '</td></tr>';
                    return;
                }

                // Update summary
                const s = data.summary;
                document.getElementById('matched-positions').textContent = s.matched_positions + ' / ' + s.whale_positions;
                document.getElementById('avg-fill-rate').textContent = (s.avg_fill_rate * 100).toFixed(2) + '%';
                document.getElementById('expected-fill-rate').textContent = (s.expected_fill_rate * 100) + '%';

                const fillEff = document.getElementById('fill-efficiency');
                fillEff.textContent = s.fill_rate_efficiency.toFixed(1) + '%';
                fillEff.className = 'value ' + (s.fill_rate_efficiency >= 100 ? 'positive' : 'negative');

                const devPnl = document.getElementById('deviation-pnl');
                devPnl.textContent = formatMoney(s.total_deviation_pnl, true);
                devPnl.className = 'value ' + (s.total_deviation_pnl >= 0 ? 'positive' : 'negative');

                document.getElementById('on-target-count').textContent = s.on_target_count;
                document.getElementById('overfilled-count').textContent = s.overfilled_count;
                document.getElementById('underfilled-count').textContent = s.underfilled_count;
                document.getElementById('missed-count').textContent = s.missed_count;

                // Store all positions (no limit)
                positionsData = data.comparisons;
                document.getElementById('positions-count').textContent = '(' + positionsData.length + ' positions)';

                // Update sort indicators and render
                updateSortIndicators();
                renderPositionsTable();

                // Render new Performance Analysis tables
                renderFillStatusTable(data.pnl_by_fill_status);
                renderSizeBucketTable(data.size_bucket_analysis);
                renderPerformanceInsight(data);

            } catch (e) {
                console.error('Error loading positions:', e);
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #f87171;">Error loading positions</td></tr>';
            }
        }

        function renderFillStatusTable(pnlByFillStatus) {
            const tbody = document.getElementById('fill-status-tbody');
            if (!pnlByFillStatus) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 20px; color: #666;">No data</td></tr>';
                return;
            }

            const statusConfig = {
                'overfilled': { label: 'Overfilled (>1% over)', color: '#60a5fa', icon: '📈' },
                'underfilled': { label: 'Underfilled (<1% under)', color: '#fbbf24', icon: '📉' },
                'on_target': { label: 'On Target (±1%)', color: '#4ade80', icon: '✅' },
                'missed': { label: 'Missed Entirely', color: '#f87171', icon: '❌' },
            };

            let html = '';
            for (const [status, stats] of Object.entries(pnlByFillStatus)) {
                const cfg = statusConfig[status] || { label: status, color: '#888', icon: '?' };
                const whalePnlColor = stats.whale_pnl >= 0 ? '#4ade80' : '#f87171';
                const copierPnlColor = stats.copier_pnl >= 0 ? '#4ade80' : '#f87171';

                // Determine verdict
                let verdict = '';
                let verdictColor = '#888';
                if (status === 'overfilled') {
                    if (stats.whale_pnl > 0) {
                        verdict = 'GOOD - Overfilled winners';
                        verdictColor = '#4ade80';
                    } else if (stats.whale_pnl < 0) {
                        verdict = 'BAD - Overfilled losers';
                        verdictColor = '#f87171';
                    }
                } else if (status === 'underfilled') {
                    if (stats.whale_pnl > 0) {
                        verdict = 'BAD - Underfilled winners';
                        verdictColor = '#f87171';
                    } else if (stats.whale_pnl < 0) {
                        verdict = 'GOOD - Underfilled losers';
                        verdictColor = '#4ade80';
                    }
                } else if (status === 'missed') {
                    if (stats.whale_pnl > 0) {
                        verdict = 'BAD - Missed winners';
                        verdictColor = '#f87171';
                    } else if (stats.whale_pnl < 0) {
                        verdict = 'GOOD - Dodged losers';
                        verdictColor = '#4ade80';
                    }
                } else {
                    verdict = 'Neutral';
                }

                html += '<tr style="border-bottom: 1px solid #2a2a2a;">' +
                    '<td style="padding: 10px; color: ' + cfg.color + ';">' + cfg.icon + ' ' + cfg.label + '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + stats.count + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + whalePnlColor + ';">' + formatMoney(stats.whale_pnl, true) + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + whalePnlColor + ';">' + formatMoney(stats.avg_whale_pnl, true) + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + copierPnlColor + ';">' + formatMoney(stats.copier_pnl, true) + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + verdictColor + '; font-weight: 600;">' + verdict + '</td>' +
                '</tr>';
            }
            tbody.innerHTML = html;
        }

        function renderSizeBucketTable(sizeBucketAnalysis) {
            const tbody = document.getElementById('size-bucket-tbody');
            if (!sizeBucketAnalysis || sizeBucketAnalysis.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px; color: #666;">No data</td></tr>';
                return;
            }

            let html = '';
            for (const bucket of sizeBucketAnalysis) {
                const whalePnlColor = bucket.whale_pnl >= 0 ? '#4ade80' : '#f87171';
                const winRateColor = bucket.whale_win_rate >= 50 ? '#4ade80' : '#f87171';
                const fillRatePct = (bucket.avg_fill_rate * 100).toFixed(2);
                const vsTargetPct = bucket.fill_rate_vs_target.toFixed(0);
                const vsTargetColor = bucket.fill_rate_vs_target >= 100 ? '#60a5fa' : '#fbbf24';

                // Impact analysis: are you overfilling winners or losers?
                let impact = '';
                let impactColor = '#888';
                const isOverfilling = bucket.fill_rate_vs_target > 105;
                const isUnderfilling = bucket.fill_rate_vs_target < 95;
                const isWinning = bucket.whale_pnl > 0;

                if (isOverfilling && isWinning) {
                    impact = 'GOOD';
                    impactColor = '#4ade80';
                } else if (isOverfilling && !isWinning) {
                    impact = 'BAD';
                    impactColor = '#f87171';
                } else if (isUnderfilling && isWinning) {
                    impact = 'BAD';
                    impactColor = '#f87171';
                } else if (isUnderfilling && !isWinning) {
                    impact = 'GOOD';
                    impactColor = '#4ade80';
                } else {
                    impact = 'OK';
                }

                html += '<tr style="border-bottom: 1px solid #2a2a2a;">' +
                    '<td style="padding: 10px; font-weight: 600;">' + bucket.label + '</td>' +
                    '<td style="text-align: right; padding: 10px;">' + bucket.count + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + whalePnlColor + ';">' + formatMoney(bucket.whale_pnl, true) + '</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + winRateColor + ';">' + bucket.whale_win_rate.toFixed(0) + '%</td>' +
                    '<td style="text-align: right; padding: 10px;">' + fillRatePct + '%</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + vsTargetColor + ';">' + vsTargetPct + '%</td>' +
                    '<td style="text-align: right; padding: 10px; color: ' + impactColor + '; font-weight: 600;">' + impact + '</td>' +
                '</tr>';
            }
            tbody.innerHTML = html;
        }

        function renderPerformanceInsight(data) {
            const container = document.getElementById('performance-insight');
            if (!data || !data.pnl_by_fill_status || !data.size_bucket_analysis) {
                container.innerHTML = '<p style="color: #888;">No data available for analysis</p>';
                return;
            }

            const fs = data.pnl_by_fill_status;
            const buckets = data.size_bucket_analysis;

            // Calculate key metrics
            const overfillWhalePnl = fs.overfilled?.whale_pnl || 0;
            const underfillWhalePnl = fs.underfilled?.whale_pnl || 0;
            const missedWhalePnl = fs.missed?.whale_pnl || 0;

            // Find large vs small bucket performance
            const largeBuckets = buckets.filter(b => b.label.includes('k') && !b.label.startsWith('0'));
            const smallBuckets = buckets.filter(b => b.label.startsWith('0') || b.label === '500-1k');

            const largePnl = largeBuckets.reduce((sum, b) => sum + b.whale_pnl, 0);
            const smallPnl = smallBuckets.reduce((sum, b) => sum + b.whale_pnl, 0);

            const largeAvgFillVsTarget = largeBuckets.length > 0 ?
                largeBuckets.reduce((sum, b) => sum + b.fill_rate_vs_target, 0) / largeBuckets.length : 100;
            const smallAvgFillVsTarget = smallBuckets.length > 0 ?
                smallBuckets.reduce((sum, b) => sum + b.fill_rate_vs_target, 0) / smallBuckets.length : 100;

            // Build insight
            let insights = [];

            // Pattern 1: Overfilling losers
            if (overfillWhalePnl < -50) {
                insights.push('<span style="color: #f87171;">You are OVERFILLING positions where the whale is LOSING.</span> This magnifies your losses beyond the expected 8%.');
            } else if (overfillWhalePnl > 50) {
                insights.push('<span style="color: #4ade80;">You are OVERFILLING positions where the whale is WINNING.</span> This helps your performance.');
            }

            // Pattern 2: Underfilling winners
            if (underfillWhalePnl > 100) {
                insights.push('<span style="color: #f87171;">You are UNDERFILLING positions where the whale is WINNING.</span> You are missing out on gains.');
            } else if (underfillWhalePnl < -100) {
                insights.push('<span style="color: #4ade80;">You are UNDERFILLING positions where the whale is LOSING.</span> This protects you from losses.');
            }

            // Pattern 3: Large vs small trade analysis
            if (largePnl < -100 && largeAvgFillVsTarget > 100) {
                insights.push('<span style="color: #f87171;">CRITICAL: Large trades (1k+ shares) are LOSING and you are filling MORE than 8% on them.</span> Your aggressive execution on big trades is hurting you because the whale loses on these.');
            } else if (largePnl > 100 && largeAvgFillVsTarget > 100) {
                insights.push('<span style="color: #4ade80;">Large trades are WINNING and you are filling more - this is working in your favor.</span>');
            }

            if (smallPnl > 100 && smallAvgFillVsTarget < 100) {
                insights.push('<span style="color: #f87171;">Small trades (under 1k shares) are WINNING but you are filling LESS than 8%.</span> You are missing gains on the whale\\'s winning small trades.');
            } else if (smallPnl < -100 && smallAvgFillVsTarget < 100) {
                insights.push('<span style="color: #4ade80;">Small trades are LOSING and you fill less - this is protecting you.</span>');
            }

            // Summary
            let summary = '';
            if (largePnl < 0 && largeAvgFillVsTarget > 100) {
                summary = '<div style="margin-top: 15px; padding: 15px; background: #3a1a1a; border-radius: 6px; border-left: 3px solid #f87171;">' +
                    '<strong style="color: #f87171;">ROOT CAUSE IDENTIFIED:</strong> The whale is losing on large positions, and your aggressive execution (higher buffers, IOC orders) causes you to fill MORE on these large losers. ' +
                    'Meanwhile, you fill less on small trades where the whale may be winning. This creates systematic underperformance.' +
                    '</div>';
            } else if (insights.length === 0) {
                summary = '<p style="color: #888;">Fill patterns appear balanced. Performance divergence may be due to timing differences or market conditions.</p>';
            }

            container.innerHTML = (insights.length > 0 ? '<ul style="margin: 0; padding-left: 20px;">' + insights.map(i => '<li style="margin-bottom: 10px;">' + i + '</li>').join('') + '</ul>' : '') + summary;
        }

        // Initial load
        loadLatest();
        loadHistory(24);
        loadPositions();  // Load positions on startup

        // Auto-refresh every 30 seconds
        setInterval(loadLatest, 30000);
        setInterval(() => loadHistory(currentHours), 60000);
        // Refresh positions every 5 minutes
        setInterval(loadPositions, 300000);
    </script>
</body>
</html>
"""


# =============================================================================
# MAIN
# =============================================================================
async def main():
    # Initialize database
    init_db()

    # Start background fetcher
    asyncio.create_task(background_fetcher())

    # Setup web server
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/latest', handle_api_latest)
    app.router.add_get('/api/history', handle_api_history)
    app.router.add_get('/api/config', handle_api_config)
    app.router.add_get('/api/positions', handle_api_positions)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    await site.start()

    logger.info(f"Web dashboard running at http://localhost:{WEB_PORT}")
    logger.info(f"Monitoring {USER_1_LABEL} vs {USER_2_LABEL} (scaling ratio: {SCALING_RATIO:.0%})")

    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
