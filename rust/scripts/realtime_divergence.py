#!/usr/bin/env python3
"""
Real-Time PNL & Portfolio Value Divergence Tracker

Compares two Polymarket users in real-time and calculates divergence
from EXPECTED values based on the SCALING_RATIO (copy trading ratio).

Users:
- User 1 (Copier): <YOUR_ADDRESS>
- User 2 (Whale): <TARGET_ADDRESS>

Expected Relationship:
  User1_PNL ≈ User2_PNL * SCALING_RATIO (0.08 = 8%)
  User1_Value ≈ User2_Value * SCALING_RATIO (approximately, depends on base capital)

Fetches from:
- https://data-api.polymarket.com/value?user={address}
- https://user-pnl-api.polymarket.com/user-pnl?user_address={address}&interval=1d&fidelity=1h
  (Rolling 24-hour PNL calculated from hourly data points)

Usage:
    python realtime_divergence.py
    python realtime_divergence.py --interval 30  # Update every 30 seconds
    python realtime_divergence.py --duration 3600  # Run for 1 hour
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import json

import aiohttp

# =============================================================================
# CONFIGURATION
# =============================================================================
USER_1_ADDRESS = ""  # Copier (You) - Set your address here
USER_2_ADDRESS = ""  # Whale to copy - Set target address here

USER_1_LABEL = "You"
USER_2_LABEL = "swisstony"

# From a_poly_trade_optimized/rust_clob_client/src/config.rs
# pub const SCALING_RATIO: f64 = 0.08;
SCALING_RATIO = 0.08  # 8% - User 1 copies User 2 at this ratio

DATA_API_BASE = "https://data-api.polymarket.com"
USER_PNL_API = "https://user-pnl-api.polymarket.com/user-pnl"


@dataclass
class UserSnapshot:
    """Snapshot of a user's portfolio at a point in time."""
    address: str
    label: str
    timestamp: datetime
    portfolio_value: Optional[float] = None
    day_pnl: Optional[float] = None
    day_volume: Optional[float] = None
    rank: Optional[int] = None
    error: Optional[str] = None


@dataclass
class DivergenceSnapshot:
    """Divergence between two users at a point in time."""
    timestamp: datetime
    user1: UserSnapshot
    user2: UserSnapshot
    scaling_ratio: float = SCALING_RATIO

    # === RAW DIFFERENCES ===

    @property
    def value_divergence(self) -> Optional[float]:
        """Absolute difference in portfolio value."""
        if self.user1.portfolio_value is not None and self.user2.portfolio_value is not None:
            return self.user1.portfolio_value - self.user2.portfolio_value
        return None

    @property
    def pnl_divergence(self) -> Optional[float]:
        """Difference in day PNL."""
        if self.user1.day_pnl is not None and self.user2.day_pnl is not None:
            return self.user1.day_pnl - self.user2.day_pnl
        return None

    @property
    def value_ratio(self) -> Optional[float]:
        """Ratio of user1 value to user2 value."""
        if (self.user1.portfolio_value is not None and
            self.user2.portfolio_value is not None and
            self.user2.portfolio_value > 0):
            return self.user1.portfolio_value / self.user2.portfolio_value
        return None

    # === EXPECTED VALUES (based on SCALING_RATIO) ===

    @property
    def expected_pnl(self) -> Optional[float]:
        """Expected User1 PNL = User2 PNL * SCALING_RATIO."""
        if self.user2.day_pnl is not None:
            return self.user2.day_pnl * self.scaling_ratio
        return None

    @property
    def pnl_vs_expected(self) -> Optional[float]:
        """
        Divergence from expected PNL.
        Positive = User1 is OUTPERFORMING expected
        Negative = User1 is UNDERPERFORMING expected
        """
        if self.user1.day_pnl is not None and self.expected_pnl is not None:
            return self.user1.day_pnl - self.expected_pnl
        return None

    @property
    def pnl_vs_expected_pct(self) -> Optional[float]:
        """Percentage deviation from expected PNL."""
        if self.expected_pnl is not None and self.expected_pnl != 0 and self.pnl_vs_expected is not None:
            return (self.pnl_vs_expected / abs(self.expected_pnl)) * 100
        return None

    @property
    def actual_pnl_ratio(self) -> Optional[float]:
        """Actual ratio of User1 PNL to User2 PNL."""
        if (self.user1.day_pnl is not None and
            self.user2.day_pnl is not None and
            self.user2.day_pnl != 0):
            return self.user1.day_pnl / self.user2.day_pnl
        return None

    @property
    def pnl_ratio_efficiency(self) -> Optional[float]:
        """
        How well are we tracking the whale's PNL at our target ratio?
        100% = perfect tracking
        >100% = outperforming (getting more than expected share of PNL)
        <100% = underperforming (getting less than expected share)
        """
        if self.actual_pnl_ratio is not None and self.scaling_ratio != 0:
            return (self.actual_pnl_ratio / self.scaling_ratio) * 100
        return None


class DivergenceTracker:
    """Tracks divergence between two users over time."""

    def __init__(self, user1_address: str, user2_address: str,
                 user1_label: str = "User 1", user2_label: str = "User 2"):
        self.user1_address = user1_address.lower()
        self.user2_address = user2_address.lower()
        self.user1_label = user1_label
        self.user2_label = user2_label
        self.history: List[DivergenceSnapshot] = []

    async def fetch_user_value(self, session: aiohttp.ClientSession,
                                address: str) -> Optional[float]:
        """Fetch portfolio value for a user."""
        url = f"{DATA_API_BASE}/value"
        params = {"user": address}
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return float(data[0].get("value", 0))
        except Exception as e:
            print(f"    Error fetching value for {address[:10]}...: {e}")
        return None

    async def fetch_user_rolling_pnl(self, session: aiohttp.ClientSession,
                                      address: str) -> dict:
        """Fetch rolling 24-hour PNL from user-pnl-api (matches frontend display)."""
        params = {
            "user_address": address,
            "interval": "1d",   # 1 day of data
            "fidelity": "1h"    # hourly data points
        }
        try:
            async with session.get(USER_PNL_API, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Data is array of {"t": timestamp, "p": cumulative_pnl}
                    # Rolling 24h PNL = latest p - earliest p
                    if data and len(data) >= 2:
                        # Sort by timestamp to ensure correct order
                        sorted_data = sorted(data, key=lambda x: x.get("t", 0))
                        earliest_pnl = float(sorted_data[0].get("p", 0))
                        latest_pnl = float(sorted_data[-1].get("p", 0))
                        rolling_24h_pnl = latest_pnl - earliest_pnl
                        return {
                            "pnl": rolling_24h_pnl,
                            "cumulative_pnl": latest_pnl,
                            "data_points": len(data),
                        }
                    elif data and len(data) == 1:
                        # Only one data point, PNL change is 0
                        return {
                            "pnl": 0.0,
                            "cumulative_pnl": float(data[0].get("p", 0)),
                            "data_points": 1,
                        }
        except Exception as e:
            print(f"    Error fetching rolling PNL for {address[:10]}...: {e}")
        return {}

    async def fetch_snapshot(self, session: aiohttp.ClientSession,
                              address: str, label: str) -> UserSnapshot:
        """Fetch complete snapshot for a user."""
        now = datetime.now()

        # Fetch value and rolling 24h PNL in parallel
        value_task = self.fetch_user_value(session, address)
        pnl_task = self.fetch_user_rolling_pnl(session, address)

        value, pnl_data = await asyncio.gather(value_task, pnl_task)

        return UserSnapshot(
            address=address,
            label=label,
            timestamp=now,
            portfolio_value=value,
            day_pnl=pnl_data.get("pnl"),
            day_volume=None,  # Not available from this API
            rank=None,        # Not available from this API
        )

    async def update(self) -> DivergenceSnapshot:
        """Fetch new snapshots for both users and calculate divergence."""
        async with aiohttp.ClientSession() as session:
            user1_snap, user2_snap = await asyncio.gather(
                self.fetch_snapshot(session, self.user1_address, self.user1_label),
                self.fetch_snapshot(session, self.user2_address, self.user2_label)
            )

        snapshot = DivergenceSnapshot(
            timestamp=datetime.now(),
            user1=user1_snap,
            user2=user2_snap
        )

        self.history.append(snapshot)
        return snapshot

    def print_snapshot(self, snap: DivergenceSnapshot, show_change: bool = True):
        """Print a formatted snapshot."""
        ts = snap.timestamp.strftime("%H:%M:%S")

        # Build output
        lines = []
        lines.append("")
        lines.append(f"{'='*80}")
        lines.append(f" DIVERGENCE TRACKER | {ts} | SCALING_RATIO = {SCALING_RATIO:.0%}")
        lines.append(f"{'='*80}")

        # User comparison table
        lines.append(f"\n{'Metric':<25} {self.user1_label:>20} {self.user2_label:>20} {'Raw Diff':>15}")
        lines.append("-" * 80)

        # Portfolio Value
        v1 = f"${snap.user1.portfolio_value:,.2f}" if snap.user1.portfolio_value else "N/A"
        v2 = f"${snap.user2.portfolio_value:,.2f}" if snap.user2.portfolio_value else "N/A"
        diff_v = f"${snap.value_divergence:+,.2f}" if snap.value_divergence is not None else "N/A"
        lines.append(f"{'Portfolio Value':<25} {v1:>20} {v2:>20} {diff_v:>15}")

        # Rolling 24h PNL
        p1 = f"${snap.user1.day_pnl:+,.2f}" if snap.user1.day_pnl is not None else "N/A"
        p2 = f"${snap.user2.day_pnl:+,.2f}" if snap.user2.day_pnl is not None else "N/A"
        diff_p = f"${snap.pnl_divergence:+,.2f}" if snap.pnl_divergence is not None else "N/A"
        lines.append(f"{'Rolling 24h PNL':<25} {p1:>20} {p2:>20} {diff_p:>15}")

        # =======================================================================
        # EXPECTED vs ACTUAL ANALYSIS (KEY SECTION)
        # =======================================================================
        lines.append(f"\n{'─'*80}")
        lines.append(f" COPY TRADING EFFICIENCY (Target Ratio: {SCALING_RATIO:.0%})")
        lines.append(f"{'─'*80}")

        # Expected PNL calculation
        if snap.expected_pnl is not None:
            lines.append(f"\n  Expected {self.user1_label} PNL:")
            lines.append(f"    = {self.user2_label} PNL × {SCALING_RATIO:.0%}")
            lines.append(f"    = ${snap.user2.day_pnl:+,.2f} × {SCALING_RATIO}")
            lines.append(f"    = ${snap.expected_pnl:+,.2f}")

        # Actual vs Expected
        if snap.pnl_vs_expected is not None:
            lines.append(f"\n  Actual {self.user1_label} PNL:    ${snap.user1.day_pnl:+,.2f}")
            lines.append(f"  Expected {self.user1_label} PNL:  ${snap.expected_pnl:+,.2f}")
            lines.append(f"  {'─'*40}")
            lines.append(f"  PNL vs Expected:        ${snap.pnl_vs_expected:+,.2f}")

            if snap.pnl_vs_expected_pct is not None:
                lines.append(f"  Deviation:              {snap.pnl_vs_expected_pct:+.1f}%")

            # Interpretation
            if snap.pnl_vs_expected > 0:
                lines.append(f"\n  >>> OUTPERFORMING expected by ${snap.pnl_vs_expected:,.2f}")
            elif snap.pnl_vs_expected < 0:
                lines.append(f"\n  <<< UNDERPERFORMING expected by ${-snap.pnl_vs_expected:,.2f}")
            else:
                lines.append(f"\n  === TRACKING PERFECTLY")

        # PNL Ratio Analysis
        if snap.actual_pnl_ratio is not None:
            lines.append(f"\n  Actual PNL Ratio:       {snap.actual_pnl_ratio:.4f} ({snap.actual_pnl_ratio*100:.2f}%)")
            lines.append(f"  Target PNL Ratio:       {SCALING_RATIO:.4f} ({SCALING_RATIO*100:.2f}%)")

            if snap.pnl_ratio_efficiency is not None:
                eff = snap.pnl_ratio_efficiency
                lines.append(f"  Copy Efficiency:        {eff:.1f}%")

                if eff >= 100:
                    lines.append(f"    (Getting {eff:.0f}% of expected PNL share)")
                else:
                    lines.append(f"    (Only getting {eff:.0f}% of expected PNL share)")

        # Value ratio comparison
        if snap.value_ratio is not None:
            pct = snap.value_ratio * 100
            lines.append(f"\n  Portfolio Value Ratio:  {snap.value_ratio:.4f} ({pct:.2f}%)")
            lines.append(f"  (Note: Value ratio ≠ scaling ratio due to different base capital)")

        # Change from previous snapshot
        if show_change and len(self.history) >= 2:
            prev = self.history[-2]
            lines.append(f"\n  {'─'*60}")
            lines.append(f"  CHANGE SINCE LAST UPDATE:")

            if snap.user1.portfolio_value and prev.user1.portfolio_value:
                chg1 = snap.user1.portfolio_value - prev.user1.portfolio_value
                lines.append(f"    {self.user1_label} Value: ${chg1:+,.2f}")

            if snap.user2.portfolio_value and prev.user2.portfolio_value:
                chg2 = snap.user2.portfolio_value - prev.user2.portfolio_value
                lines.append(f"    {self.user2_label} Value: ${chg2:+,.2f}")

            if snap.value_divergence is not None and prev.value_divergence is not None:
                div_chg = snap.value_divergence - prev.value_divergence
                lines.append(f"    Divergence Change: ${div_chg:+,.2f}")

        # Session summary
        if len(self.history) > 1:
            first = self.history[0]
            lines.append(f"\n  {'─'*60}")
            lines.append(f"  SESSION SUMMARY (since {first.timestamp.strftime('%H:%M:%S')}):")

            if snap.user1.portfolio_value and first.user1.portfolio_value:
                total_chg1 = snap.user1.portfolio_value - first.user1.portfolio_value
                lines.append(f"    {self.user1_label} Total Change: ${total_chg1:+,.2f}")

            if snap.user2.portfolio_value and first.user2.portfolio_value:
                total_chg2 = snap.user2.portfolio_value - first.user2.portfolio_value
                lines.append(f"    {self.user2_label} Total Change: ${total_chg2:+,.2f}")

            if snap.value_divergence is not None and first.value_divergence is not None:
                total_div_chg = snap.value_divergence - first.value_divergence
                lines.append(f"    Divergence Total Change: ${total_div_chg:+,.2f}")

        lines.append("")
        print("\n".join(lines))

    def print_ascii_chart(self, metric: str = "pnl_vs_expected", width: int = 60):
        """Print ASCII chart of divergence over time."""
        if len(self.history) < 2:
            return

        # Get values based on metric
        if metric == "pnl_vs_expected":
            values = [s.pnl_vs_expected for s in self.history if s.pnl_vs_expected is not None]
            title = "PNL vs Expected (+ = outperform, - = underperform)"
        elif metric == "divergence":
            values = [s.value_divergence for s in self.history if s.value_divergence is not None]
            title = "Portfolio Value Divergence"
        elif metric == "pnl_divergence":
            values = [s.pnl_divergence for s in self.history if s.pnl_divergence is not None]
            title = "Day PNL Divergence"
        elif metric == "efficiency":
            values = [s.pnl_ratio_efficiency for s in self.history if s.pnl_ratio_efficiency is not None]
            title = "Copy Efficiency % (100% = perfect tracking)"
        else:
            values = [s.user1.portfolio_value for s in self.history if s.user1.portfolio_value is not None]
            title = f"{self.user1_label} Portfolio Value"

        if len(values) < 2:
            return

        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val

        if range_val == 0:
            range_val = 1  # Avoid division by zero

        height = 10
        chart_width = min(len(values), width)

        # Sample values if too many
        if len(values) > chart_width:
            step = len(values) / chart_width
            sampled = [values[int(i * step)] for i in range(chart_width)]
        else:
            sampled = values

        print(f"\n  {title} (last {len(sampled)} points)")
        print(f"  Max: ${max_val:+,.0f}" if "efficiency" not in metric else f"  Max: {max_val:+,.1f}%")

        # Build chart
        for row in range(height, 0, -1):
            threshold = min_val + (row / height) * range_val
            line = "  "
            for val in sampled:
                if val >= threshold:
                    line += "█"
                else:
                    line += " "
            if row == height:
                line += f" ${max_val:+,.0f}" if "efficiency" not in metric else f" {max_val:+,.1f}%"
            elif row == 1:
                line += f" ${min_val:+,.0f}" if "efficiency" not in metric else f" {min_val:+,.1f}%"
            print(line)

        print(f"  {'─' * len(sampled)}")
        print(f"  Min: ${min_val:+,.0f}" if "efficiency" not in metric else f"  Min: {min_val:+,.1f}%")

    def save_history(self, filepath: str = "divergence_history.json"):
        """Save history to JSON file."""
        data = []
        for snap in self.history:
            data.append({
                "timestamp": snap.timestamp.isoformat(),
                "scaling_ratio": snap.scaling_ratio,
                "user1": {
                    "address": snap.user1.address,
                    "label": snap.user1.label,
                    "portfolio_value": snap.user1.portfolio_value,
                    "day_pnl": snap.user1.day_pnl,
                    "day_volume": snap.user1.day_volume,
                    "rank": snap.user1.rank,
                },
                "user2": {
                    "address": snap.user2.address,
                    "label": snap.user2.label,
                    "portfolio_value": snap.user2.portfolio_value,
                    "day_pnl": snap.user2.day_pnl,
                    "day_volume": snap.user2.day_volume,
                    "rank": snap.user2.rank,
                },
                "raw_metrics": {
                    "value_divergence": snap.value_divergence,
                    "pnl_divergence": snap.pnl_divergence,
                    "value_ratio": snap.value_ratio,
                },
                "expected_metrics": {
                    "expected_pnl": snap.expected_pnl,
                    "pnl_vs_expected": snap.pnl_vs_expected,
                    "pnl_vs_expected_pct": snap.pnl_vs_expected_pct,
                    "actual_pnl_ratio": snap.actual_pnl_ratio,
                    "pnl_ratio_efficiency": snap.pnl_ratio_efficiency,
                },
            })

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  Saved {len(data)} snapshots to {filepath}")


async def run_tracker(interval: int = 60, duration: Optional[int] = None,
                       show_chart: bool = True):
    """Run the divergence tracker."""
    tracker = DivergenceTracker(
        user1_address=USER_1_ADDRESS,
        user2_address=USER_2_ADDRESS,
        user1_label=USER_1_LABEL,
        user2_label=USER_2_LABEL,
    )

    print(f"\nStarting Divergence Tracker")
    print(f"  User 1 (Copier): {USER_1_LABEL} ({USER_1_ADDRESS[:10]}...)")
    print(f"  User 2 (Whale):  {USER_2_LABEL} ({USER_2_ADDRESS[:10]}...)")
    print(f"  Scaling Ratio:   {SCALING_RATIO:.0%} (User1 should be {SCALING_RATIO:.0%} of User2)")
    print(f"  Interval: {interval}s")
    if duration:
        print(f"  Duration: {duration}s")
    print(f"\nPress Ctrl+C to stop\n")

    start_time = datetime.now()
    update_count = 0

    try:
        while True:
            # Check duration
            if duration:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration:
                    print(f"\nDuration reached ({duration}s). Stopping.")
                    break

            # Fetch and display
            print(f"Fetching data... (update #{update_count + 1})")
            snapshot = await tracker.update()
            tracker.print_snapshot(snapshot)

            if show_chart and len(tracker.history) > 2:
                tracker.print_ascii_chart("pnl_vs_expected")

            update_count += 1

            # Wait for next interval
            print(f"\nNext update in {interval}s...")
            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    finally:
        # Save history
        if tracker.history:
            tracker.save_history()

            # Final summary
            print(f"\n{'='*80}")
            print(f" FINAL SESSION SUMMARY")
            print(f"{'='*80}")
            print(f"  Updates: {len(tracker.history)}")
            print(f"  Duration: {(datetime.now() - start_time).total_seconds():.0f}s")
            print(f"  Scaling Ratio: {SCALING_RATIO:.0%}")

            if len(tracker.history) >= 2:
                first = tracker.history[0]
                last = tracker.history[-1]

                print(f"\n  --- VALUE CHANGES ---")
                if first.user1.portfolio_value and last.user1.portfolio_value:
                    u1_change = last.user1.portfolio_value - first.user1.portfolio_value
                    print(f"  {tracker.user1_label} Value Change: ${u1_change:+,.2f}")

                if first.user2.portfolio_value and last.user2.portfolio_value:
                    u2_change = last.user2.portfolio_value - first.user2.portfolio_value
                    print(f"  {tracker.user2_label} Value Change: ${u2_change:+,.2f}")

                print(f"\n  --- PNL vs EXPECTED ---")
                if last.pnl_vs_expected is not None:
                    print(f"  Final PNL vs Expected: ${last.pnl_vs_expected:+,.2f}")
                if last.pnl_ratio_efficiency is not None:
                    print(f"  Final Copy Efficiency: {last.pnl_ratio_efficiency:.1f}%")

                if first.pnl_vs_expected is not None and last.pnl_vs_expected is not None:
                    div_change = last.pnl_vs_expected - first.pnl_vs_expected
                    print(f"  PNL vs Expected Change: ${div_change:+,.2f}")


async def run_once():
    """Run a single update and exit."""
    tracker = DivergenceTracker(
        user1_address=USER_1_ADDRESS,
        user2_address=USER_2_ADDRESS,
        user1_label=USER_1_LABEL,
        user2_label=USER_2_LABEL,
    )

    print(f"\nFetching divergence data...")
    snapshot = await tracker.update()
    tracker.print_snapshot(snapshot, show_change=False)
    return snapshot


def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-time PNL & Portfolio Value Divergence Tracker"
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=10,
        help="Update interval in seconds (default: 10)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=None,
        help="Total duration to run in seconds (default: unlimited)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit"
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Don't show ASCII chart"
    )
    parser.add_argument(
        "--user1",
        type=str,
        default=USER_1_ADDRESS,
        help=f"User 1 address (default: {USER_1_ADDRESS[:10]}...)"
    )
    parser.add_argument(
        "--user2",
        type=str,
        default=USER_2_ADDRESS,
        help=f"User 2 address (default: {USER_2_ADDRESS[:10]}...)"
    )
    parser.add_argument(
        "--label1",
        type=str,
        default=USER_1_LABEL,
        help=f"User 1 label (default: {USER_1_LABEL})"
    )
    parser.add_argument(
        "--label2",
        type=str,
        default=USER_2_LABEL,
        help=f"User 2 label (default: {USER_2_LABEL})"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Update global config if custom addresses provided
    global USER_1_ADDRESS, USER_2_ADDRESS, USER_1_LABEL, USER_2_LABEL
    USER_1_ADDRESS = args.user1
    USER_2_ADDRESS = args.user2
    USER_1_LABEL = args.label1
    USER_2_LABEL = args.label2

    if args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_tracker(
            interval=args.interval,
            duration=args.duration,
            show_chart=not args.no_chart
        ))


if __name__ == "__main__":
    main()
