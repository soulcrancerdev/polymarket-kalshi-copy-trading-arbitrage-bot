# Configuration Guide

Complete reference for all bot configuration options.

## Table of Contents

1. [Required Settings](#1-required-settings)
2. [Trading Settings](#2-trading-settings)
3. [Risk Management Settings](#3-risk-management-settings-circuit-breaker)
4. [Advanced Settings](#4-advanced-settings)
5. [Configuration Examples](#5-configuration-examples)
6. [Validation](#6-validation)
7. [Troubleshooting Configuration](#7-troubleshooting-configuration)

---

## 1. Required Settings

These must be set for the bot to work. Without these, the bot will not start.

### 1.1 PRIVATE_KEY

**Type:** String (64 hex characters)  
**Format:** No `0x` prefix  
**Example:** `0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef`

Your wallet's private key. This is used to sign transactions.

**⚠️ Security Warning:**
- Never share this with anyone
- Never commit to git (`.env` is already in `.gitignore`)
- Store securely (password manager recommended)
- Use a separate wallet for bot trading (not your main wallet)

**How to get:**
- MetaMask: Account Details → Export Private Key
- Other wallets: Check wallet documentation for export method

---

### 1.2 FUNDER_ADDRESS

**Type:** String (40 hex characters)  
**Format:** Can include or exclude `0x` prefix  
**Example:** `0x1234567890123456789012345678901234567890` or `1234567890123456789012345678901234567890`

Your wallet address. Must match the wallet from `PRIVATE_KEY`.

**How to get:**
- MetaMask: Copy address from account (top of extension)
- Other wallets: Usually displayed prominently in wallet UI

**Important:** Make sure this wallet has:
- USDC or USDC.e tokens on Polygon
- Enough MATIC for gas fees (0.01-0.1 MATIC is usually enough)

---

### 1.3 TARGET_WHALE_ADDRESS

**Type:** String (40 hex characters)  
**Format:** No `0x` prefix  
**Example:** `204f72f35326db932158cba6adff0b9a1da95e14`

The wallet address of the trader you want to copy.

**Finding whales:**
- Polymarket leaderboards
- Recent winners on large markets
- Social media/communities

**Verification:**
- Check their trading history
- Look for consistent performance
- Start with small amounts to test

---

### 1.4 ALCHEMY_API_KEY (or CHAINSTACK_API_KEY)

**Type:** String  
**Example:** `abc123xyz789def456`

**Choose ONE provider:**

##### 1.4.1 Option 1: Alchemy (Recommended)

**Setting:** `ALCHEMY_API_KEY`

**Getting an API key:**
1. Sign up at https://www.alchemy.com/
2. Create app (Polygon Mainnet)
3. Copy API key from dashboard

**Free tier:** 300M compute units/month (sufficient for this bot)

##### 1.4.2 Option 2: Chainstack

**Setting:** `CHAINSTACK_API_KEY`

**Getting an API key:**
1. Sign up at https://chainstack.com/
2. Create project and Polygon node
3. Extract key from WebSocket URL

**Note:** If both are set, `ALCHEMY_API_KEY` takes priority.

---

## 2. Trading Settings

### 2.1 ENABLE_TRADING

**Type:** Boolean  
**Default:** `true`  
**Values:** `true`, `false`, `1`, `0` (case-insensitive)

Whether the bot should actually place trades.

- `true` / `1`: Bot places real orders
- `false` / `0`: Bot only monitors (no trades)

**Recommended:** Set to `false` for initial testing.

---

### 2.2 MOCK_TRADING

**Type:** Boolean  
**Default:** `false`  
**Values:** `true`, `false`, `1`, `0` (case-insensitive)

Simulates trades without actually executing them. Useful for testing.

- `true` / `1`: Shows what bot would do (no real orders)
- `false` / `0`: Real trading mode

**Recommended:** Set to `true` for first runs to verify everything works.

**Note:** If `ENABLE_TRADING=false`, `MOCK_TRADING` has no effect.

---

## 3. Risk Management Settings (Circuit Breaker)

Circuit breakers protect you from copying trades in dangerous market conditions (low liquidity, manipulation, etc.).

### 3.1 CB_LARGE_TRADE_SHARES

**Type:** Float  
**Default:** `1500.0`  
**Unit:** Shares

Minimum trade size that triggers circuit breaker analysis. Trades below this size skip circuit breaker checks (faster execution for small trades).

**Recommendation:** Default is usually fine. Increase if you want more protection, decrease if you want faster execution on medium trades.

---

### 3.2 CB_CONSECUTIVE_TRIGGER

**Type:** Integer  
**Default:** `2`  
**Range:** 1-10

Number of consecutive large trades (within the time window) that trigger a circuit breaker book depth check.

**Example:** With default `2`, if 2 or more large trades happen within `CB_SEQUENCE_WINDOW_SECS`, the bot checks order book depth before copying.

**Recommendation:** 
- `1` = Most conservative (checks on every large trade)
- `2` = Balanced (default)
- `3+` = More aggressive (only checks after multiple large trades)

---

### 3.3 CB_SEQUENCE_WINDOW_SECS

**Type:** Integer  
**Default:** `30`  
**Unit:** Seconds  
**Range:** 10-300

Time window to check for consecutive large trades.

**Example:** With default `30`, the bot looks back 30 seconds to count consecutive large trades.

**Recommendation:** 
- `10-20` = More sensitive (detects rapid sequences quickly)
- `30` = Balanced (default)
- `60+` = Less sensitive (only triggers on longer sequences)

---

### 3.4 CB_MIN_DEPTH_USD

**Type:** Float  
**Default:** `200.0`  
**Unit:** USD

Minimum order book depth (liquidity) required beyond the whale's price. If depth is lower, the circuit breaker blocks the trade.

**What it means:** When you want to buy at $0.50, this checks if there's at least $200 worth of sell orders available at prices up to $0.51 (whale price + buffer).

**Recommendation:**
- `100.0` = Less conservative (allows trades in thinner markets)
- `200.0` = Balanced (default)
- `500.0+` = Very conservative (only trades in liquid markets)

---

### 3.5 CB_TRIP_DURATION_SECS

**Type:** Integer  
**Default:** `120`  
**Unit:** Seconds  
**Range:** 30-600

How long to block trades after circuit breaker trips.

**What it means:** If circuit breaker detects dangerous conditions, it stops copying trades for this duration.

**Recommendation:**
- `60` = Quick recovery (resumes trading faster)
- `120` = Balanced (default, 2 minutes)
- `300+` = Very conservative (waits 5+ minutes after trip)

---

## 4. Advanced Settings

These are set in code but can be modified by editing `src/config.rs`. Only change if you understand what you're doing.

### Trading Parameters (in code)

**Location:** `src/config.rs`

- `SCALING_RATIO` (default: `0.02` = 2%)
  - Your position size as fraction of whale size
  - `0.01` = 1%, `0.05` = 5%, etc.

- `MIN_WHALE_SHARES_TO_COPY` (default: `10.0`)
  - Minimum whale trade size to copy
  - Trades below this are ignored

- `MIN_CASH_VALUE` (default: `1.01`)
  - Minimum USD value for your orders
  - Prevents dust orders

### Execution Tiers (in code)

The bot uses different strategies based on trade size:

| Whale Shares | Price Buffer | Size Multiplier | Order Type |
|--------------|--------------|-----------------|------------|
| 4000+        | 0.01         | 1.25x           | FAK        |
| 2000-3999    | 0.01         | 1.0x            | FAK        |
| 1000-1999    | 0.00         | 1.0x            | FAK        |
| <1000        | 0.00         | 1.0x            | FAK        |

**Modification:** Edit `EXECUTION_TIERS` in `src/config.rs` (requires recompiling).

---

## 5. Configuration Examples

### 5.1 Example 1: Beginner (Safe Testing)

```env
PRIVATE_KEY=your_key_here
FUNDER_ADDRESS=your_address_here
TARGET_WHALE_ADDRESS=whale_address_here
ALCHEMY_API_KEY=your_api_key_here

# Safety first
ENABLE_TRADING=false
MOCK_TRADING=true

# Default circuit breaker settings (already safe)
CB_LARGE_TRADE_SHARES=1500.0
CB_CONSECUTIVE_TRIGGER=2
CB_SEQUENCE_WINDOW_SECS=30
CB_MIN_DEPTH_USD=200.0
CB_TRIP_DURATION_SECS=120
```

### 5.2 Example 2: Conservative Trading

```env
PRIVATE_KEY=your_key_here
FUNDER_ADDRESS=your_address_here
TARGET_WHALE_ADDRESS=whale_address_here
ALCHEMY_API_KEY=your_api_key_here

ENABLE_TRADING=true
MOCK_TRADING=false

# More conservative circuit breaker
CB_LARGE_TRADE_SHARES=1000.0      # Check more trades
CB_CONSECUTIVE_TRIGGER=1          # Check every large trade
CB_SEQUENCE_WINDOW_SECS=20        # Faster detection
CB_MIN_DEPTH_USD=500.0            # Only liquid markets
CB_TRIP_DURATION_SECS=300         # Wait 5 minutes after trip
```

### 5.3 Example 3: Aggressive Trading

```env
PRIVATE_KEY=your_key_here
FUNDER_ADDRESS=your_address_here
TARGET_WHALE_ADDRESS=whale_address_here
ALCHEMY_API_KEY=your_api_key_here

ENABLE_TRADING=true
MOCK_TRADING=false

# Less conservative circuit breaker
CB_LARGE_TRADE_SHARES=2000.0      # Only check very large trades
CB_CONSECUTIVE_TRIGGER=3          # Only check after 3+ trades
CB_SEQUENCE_WINDOW_SECS=60        # Longer window
CB_MIN_DEPTH_USD=100.0            # Allow thinner markets
CB_TRIP_DURATION_SECS=60          # Quick recovery
```

---

## 6. Validation

After editing your `.env`, validate it:

```bash
cargo run --release --bin validate_setup
```

This checks:
- ✅ All required fields are set
- ✅ Address formats are correct
- ✅ Boolean values are valid
- ✅ Numeric values are valid numbers
- ✅ No obvious errors

---

## 7. Troubleshooting Configuration

**Problem:** Bot won't start, says "missing required env var"
- **Solution:** Check that all required fields in `.env` are filled (no "here" placeholders)

**Problem:** "Invalid address format" error
- **Solution:** 
  - Private key: Must be exactly 64 hex characters, no `0x`
  - Addresses: Must be exactly 40 hex characters (with or without `0x` for FUNDER_ADDRESS, no `0x` for TARGET_WHALE_ADDRESS)

**Problem:** "API key invalid" or connection errors
- **Solution:**
  - Verify API key is correct (copy-paste carefully)
  - Check if you're using free tier limits
  - Try regenerating API key

**Problem:** Circuit breaker blocks all trades
- **Solution:** Adjust `CB_MIN_DEPTH_USD` lower or `CB_CONSECUTIVE_TRIGGER` higher

For more help, see [Troubleshooting Guide](06_TROUBLESHOOTING.md).

