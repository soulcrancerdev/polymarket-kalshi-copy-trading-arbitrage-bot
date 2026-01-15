# Features Overview

This document explains what the Polymarket Copy Trading Bot does and how it works.

## Table of Contents

1. [Overview](#1-overview)
2. [Core Features](#2-core-features)
3. [Trading Flow](#3-trading-flow-step-by-step)
4. [Performance Characteristics](#4-performance-characteristics)
5. [Limitations](#5-limitations)
6. [Safety Features](#6-safety-features-summary)
7. [Understanding Output](#7-understanding-the-output)
8. [Next Steps](#8-next-steps)

## 1. Overview

### 1.1 What This Bot Does

The bot monitors blockchain events for trades made by a specific "whale" (successful trader) on Polymarket and automatically copies those trades with scaled-down position sizes.

**Key Strategy Points:**
- **2% Position Scaling:** Copies trades at 2% of whale's size (configurable)
- **Tiered Execution:** Different strategies based on trade size (4000+, 2000+, 1000+, <1000)
- **Risk Guards:** Multi-layer safety system prevents dangerous trades
- **Intelligent Pricing:** Price buffers optimize fill rates while minimizing slippage
- **Automatic Retries:** Resubmission logic maximizes fill rates

For complete strategy details, see [Trading Strategy Guide](05_STRATEGY.md).

## 2. Core Features

### 2.1 Real-Time Trade Detection

- **WebSocket Connection:** Connects to Polygon blockchain via WebSocket for real-time event monitoring
- **Event Filtering:** Only processes trades from your target whale address
- **Blockchain Events:** Monitors `OrdersFilled` events from Polymarket's order book contracts

**How it works:**
1. Bot subscribes to blockchain logs
2. Filters for trades from target whale address
3. Parses trade details (token, size, price, side)
4. Queues trade for processing

---

### 2.2 Intelligent Position Sizing

The bot doesn't copy trades at 1:1 size. Instead, it uses scaled positions:

- **Default Scaling:** 2% of whale's position size
- **Minimum Size:** Orders below $1.01 USD are skipped (prevents dust)
- **Probabilistic Sizing:** Very small positions may be probabilistically executed or skipped

**Example:**
- Whale buys 10,000 shares at $0.50 = $5,000
- Bot buys 200 shares at $0.50 = $100 (2% of $5,000)

**Why scaling:**
- Reduces risk exposure
- Allows copying whales with larger accounts
- Prevents position size issues if whale uses full account

---

### 2.3 Tiered Execution Strategy

Different trade sizes get different execution strategies:

| Trade Size (Shares) | Price Buffer | Size Multiplier | Strategy |
|---------------------|--------------|-----------------|----------|
| 4000+ (Large)       | +0.01        | 1.25x           | Aggressive |
| 2000-3999 (Medium)  | +0.01        | 1.0x            | Standard |
| 1000-1999 (Small)   | +0.00        | 1.0x            | Conservative |
| <1000 (Very Small)  | +0.00        | 1.0x            | Conservative |

**Price Buffer:** Additional amount paid above whale's price (improves fill rate)  
**Size Multiplier:** Your position size relative to whale (1.25x = 25% larger than normal scaling)

**Large trades (4000+ shares):**
- More aggressive (higher buffer, larger size)
- More resubmit attempts if order fails
- Price chasing on first retry

**Small trades (<1000 shares):**
- More conservative (no buffer)
- Fewer resubmit attempts
- No price chasing

---

### 2.4 Order Types

The bot uses different order types based on trade characteristics:

**FAK (Fill and Kill):**
- Executes immediately or cancels
- Used for buy orders (most trades)
- Fast execution, no order book placement

**GTD (Good Till Date):**
- Places order on book with expiration
- Used for:
  - Sell orders (all sells)
  - Final retry attempt on failed buys
- Expires after:
  - 61 seconds for live markets
  - 1800 seconds (30 min) for non-live markets

---

### 2.5 Automatic Order Resubmission

If an order fails to fill completely:

**Retry Logic:**
- Up to 4-5 attempts (depending on trade size)
- Price escalation on first retry for large trades
- Exponential backoff delays for small trades

**Example Flow:**
1. Initial order fails (FAK)
2. Retry #1: Same price or +0.01 (if large trade)
3. Retry #2-4: Same price (flat retries)
4. Final attempt: GTD order (stays on book)

**Why this helps:**
- Market conditions change quickly
- Improves fill rate on volatile markets
- Balances speed vs. execution quality

---

### 2.6 Risk Management (Circuit Breaker Protection)

Protects you from copying trades in dangerous conditions:

**Triggers:**
- Multiple large trades in short time window
- Low order book depth (thin liquidity)
- Rapid-fire trading patterns

**Actions:**
- Blocks trades for specified duration (default: 2 minutes)
- Checks order book depth before allowing trades
- Prevents copying during potential manipulation

**Configuration:**
- `CB_LARGE_TRADE_SHARES`: Minimum size to trigger (default: 1500)
- `CB_CONSECUTIVE_TRIGGER`: Number of trades to trigger (default: 2)
- `CB_SEQUENCE_WINDOW_SECS`: Time window (default: 30 seconds)
- `CB_MIN_DEPTH_USD`: Minimum liquidity required (default: $200)
- `CB_TRIP_DURATION_SECS`: Block duration (default: 120 seconds)

---

### 2.7 Market Cache System

**Purpose:** Fast lookups without API delays

**Cached Data:**
- Market information (token IDs, slugs)
- Live/non-live status
- Sport-specific market data (ATP, Ligue 1)

**Refresh:** Automatically updated in background (periodic refresh)

**Benefits:**
- Faster execution (no API wait times)
- Reduces API rate limits
- More reliable (less dependent on external APIs)

---

### 2.8 Sport-Specific Optimizations

**ATP Markets:**
- Additional +0.01 price buffer
- Optimized for tennis market characteristics

**Ligue 1 Markets:**
- Additional +0.01 price buffer
- Optimized for soccer market characteristics

**Other Markets:**
- Standard execution strategy
- No additional buffers

**Automatic Detection:** Bot automatically detects market type and applies appropriate strategy.

---

### 2.9 Comprehensive Logging

**Console Output:**
- Real-time trade information
- Color-coded status messages
- Fill percentages
- Market conditions

**CSV Logging:**
- File: `matches_optimized.csv`
- All trades logged with timestamps
- Includes: block number, token ID, USD value, shares, price, direction, status, order book data, transaction hash, live status

**Use Cases:**
- Performance analysis
- Debugging
- Audit trail
- Post-trade analysis

---

### 2.10 Live Market Detection

**Automatic Detection:**
- Checks if market is "live" (event currently happening)
- Different expiration times for live vs. non-live markets
- Faster execution for live markets

**Impact:**
- Live markets: 61-second GTD expiration (faster)
- Non-live: 30-minute GTD expiration (more patient)

---

## 3. Trading Flow (Step-by-Step)

This is a simplified overview. For complete detailed logic, see [Strategy Guide](05_STRATEGY.md).

1. **Detection:** Whale makes trade on Polymarket
2. **Event Received:** Bot receives blockchain event via WebSocket (<1 second latency)
3. **Parsing:** Bot extracts trade details (token, size, price, side)
4. **Filtering:** 
   - Check if trade is from target whale (skip if not)
   - Check if trade size is large enough (skip if too small, <10 shares)
5. **Risk Guard Check:** Multi-layer safety system checks:
   - Layer 1: Fast check (trade size, sequence detection)
   - Layer 2: Order book depth analysis (if triggered)
   - Layer 3: Trip status check
   - Result: Block trade if dangerous conditions detected
6. **Position Sizing:** Calculate your order size:
   - Base: 2% of whale's size
   - Apply tier multiplier (1.25x for 4000+, 1.0x otherwise)
   - Check minimum size ($1.01 requirement)
   - Probabilistic execution for very small positions
7. **Price Calculation:** Determine limit price:
   - Get base buffer from tier (0.01 for large, 0.00 for small)
   - Add sport-specific buffers (tennis/soccer: +0.01)
   - Calculate: whale_price + total_buffer
   - Clamp to valid range (0.01-0.99)
8. **Order Type Selection:** 
   - SELL orders: Always GTD
   - BUY orders: FAK initially, GTD on final retry
9. **Order Creation:** Create signed order with calculated parameters
10. **Submission:** Submit order to Polymarket API
11. **Result Handling:**
    - Success: Check fill amount, resubmit if partial
    - Failure: Enter resubmission loop (4-5 attempts)
    - Final attempt: Switch to GTD order if still not filled
12. **Logging:** Record all details to CSV and console with color-coded status

---

## 4. Performance Characteristics

**Latency:**
- Event detection: <1 second (blockchain dependent)
- Order processing: <100ms
- Total time to order: <2 seconds from whale trade

**Throughput:**
- Handles multiple concurrent trades
- Queued processing for high-frequency scenarios
- Automatic backpressure handling

**Reliability:**
- Automatic reconnection on WebSocket failures
- Retry logic for failed orders
- Circuit breakers prevent bad trades
- Error handling throughout

---

## 5. Limitations

**What the bot does NOT do:**
- ❌ Market analysis or prediction
- ❌ Stop-loss or take-profit orders
- ❌ Portfolio management
- ❌ Position monitoring after fill
- ❌ Exit strategy (you manage closing positions)
- ❌ Multiple whale copying (one whale at a time)

**What you need to do manually:**
- Monitor your positions
- Close positions when appropriate
- Manage your portfolio
- Adjust risk parameters
- Find good whales to copy

---

## 6. Safety Features Summary

✅ Scaled position sizes (2% default)  
✅ Circuit breakers for dangerous conditions  
✅ Minimum trade size filters  
✅ Order book depth checks  
✅ Automatic retry with limits  
✅ Comprehensive error handling  
✅ Mock trading mode for testing  
✅ Extensive logging for audit  

---

## 7. Understanding the Output

**Console Messages:**

```
⚡ [B:12345] BUY_FILL | $100 | 200 OK | ...
```

- `[B:12345]`: Block number
- `BUY_FILL`: Trade direction and type
- `$100`: USD value of whale's trade
- `200 OK`: HTTP status (200 = success)
- Following numbers: Your fill details, prices, sizes

**Color Coding:**
- 🟢 Green: Successful fills (high percentage)
- 🟡 Yellow: Partial fills (medium percentage)
- 🔴 Red: Failed or low fills (low percentage)
- 🔵 Blue: Live market indicator

**CSV Format:**
All trades are logged with: timestamp, block, token_id, usd_value, shares, price, direction, status, order_book_data, tx_hash, is_live

---

## 8. Next Steps

- Read [Configuration Guide](03_CONFIGURATION.md) to adjust settings
- Review [Trading Strategy Guide](05_STRATEGY.md) for detailed strategy logic
- Check [Setup Guide](02_SETUP_GUIDE.md) if you haven't set up yet
- Review [Troubleshooting](06_TROUBLESHOOTING.md) if you have issues

