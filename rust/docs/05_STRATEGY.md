# Trading Strategy Logic

This document explains the complete trading strategy and decision-making logic used by the bot.

## Table of Contents

1. [Overview](#1-overview)
2. [Core Strategy Components](#2-core-strategy-components)
3. [Strategy Parameters Summary](#3-strategy-parameters-summary)
4. [Detailed Strategy Logic Deep Dive](#4-detailed-strategy-logic-deep-dive)
5. [Strategy Rationale](#5-strategy-rationale)
6. [Complete Strategy Logic Flow (Pseudo-Code)](#6-complete-strategy-logic-flow-pseudo-code)
7. [Performance Considerations](#7-performance-considerations)
8. [Strategy Limitations](#8-strategy-limitations)
9. [Optimization Tips](#9-optimization-tips)
10. [Strategy Monitoring and Metrics](#10-strategy-monitoring-and-metrics)
11. [Strategy Tuning Guide](#11-strategy-tuning-guide)
12. [Future Enhancements (Potential)](#12-future-enhancements-potential)

---

## 1. Overview

The bot implements a **whale copy trading strategy** with intelligent risk management, position sizing, and execution optimization. The strategy is designed to:

- Copy successful traders (whales) automatically
- Minimize risk through position scaling and safety checks
- Optimize execution through tiered strategies
- Protect capital through risk guards and market analysis

### 1.1 Strategy Summary at a Glance

| Component | Strategy | Default Value |
|-----------|----------|---------------|
| **Position Sizing** | 2% of whale size, tiered multipliers | 2% base, 1.25x for 4000+ |
| **Price Buffer** | Tiered by trade size | +0.01 for 2000+, 0.00 for <2000 |
| **Order Type** | FAK for buys, GTD for sells | FAK (initial), GTD (final retry) |
| **Risk Check** | Multi-layer safety system | 4 layers of protection |
| **Resubmission** | Tiered retry logic | 4-5 attempts depending on size |
| **Minimum Trade** | Skip trades below threshold | 10 shares minimum |
| **Probabilistic** | Random execution for small trades | Enabled by default |

### 1.2 Strategy Philosophy

**Core Principle:** Copy successful traders at reduced scale while maintaining strict risk management.

**Key Tenets:**
1. **Scale Down:** Never risk more than you can afford (2% default)
2. **Be Selective:** Skip trades that don't meet minimum quality thresholds
3. **Protect Capital:** Multiple layers of safety checks prevent dangerous trades
4. **Optimize Execution:** Different strategies for different trade sizes
5. **Persist:** Retry logic ensures maximum fill rates without overpaying

## 2. Core Strategy Components

### 2.1 Trade Detection and Filtering

**Step 1: Blockchain Monitoring**
- Bot connects to Polygon blockchain via WebSocket
- Subscribes to `OrdersFilled` events from Polymarket order book contracts
- Filters events by target whale address (only processes trades from your selected whale)

**Step 2: Trade Validation**
- Verifies trade is from target whale address
- Checks trade size meets minimum threshold (default: 10 shares)
- Validates trade data integrity (price, size, token ID)

**Step 3: Initial Filtering**
- **Skip Conditions:**
  - Trade size < minimum threshold (prevents dust orders)
  - Invalid token ID or price data
  - Duplicate trades (same transaction hash)

### 2.2 Position Sizing Strategy

**Base Scaling:**
- Default: **2% of whale's position size**
- Configurable via `SCALING_RATIO` constant (currently 0.02)

**Size Calculation Formula:**
```
target_size = whale_shares × SCALING_RATIO × size_multiplier
minimum_size = max(MIN_CASH_VALUE / price, MIN_SHARE_COUNT)

if target_size >= minimum_size:
    order_size = target_size
else if USE_PROBABILISTIC_SIZING:
    probability = target_size / minimum_size
    if random() < probability:
        order_size = minimum_size  # Execute with probability
    else:
        skip_order  # Skip probabilistically
else:
    order_size = minimum_size  # Always execute minimum
```

**Size Multipliers by Tier:**
- **Large trades (4000+ shares):** 1.25x multiplier
- **Medium trades (2000-3999 shares):** 1.0x multiplier
- **Small trades (1000-1999 shares):** 1.0x multiplier
- **Very small trades (<1000 shares):** 1.0x multiplier

**Example Calculation:**
```
Whale trade: 10,000 shares @ $0.50
Base scaling: 10,000 × 0.02 = 200 shares
Tier multiplier (4000+): 200 × 1.25 = 250 shares
Final order: 250 shares @ $0.50 = $125
```

### 2.3 Price Strategy

**Price Buffer Logic:**
The bot adds price buffers to improve fill rates, varying by trade size and market type:

| Trade Size | Base Buffer | Tennis Buffer | Soccer Buffer | Total Buffer |
|------------|-------------|---------------|---------------|--------------|
| 4000+      | +0.01       | +0.01 (if applicable) | +0.01 (if applicable) | Up to +0.03 |
| 2000-3999  | +0.01       | +0.01 (if applicable) | +0.01 (if applicable) | Up to +0.03 |
| 1000-1999  | +0.00       | +0.01 (if applicable) | +0.01 (if applicable) | Up to +0.02 |
| <1000      | +0.00       | +0.01 (if applicable) | +0.01 (if applicable) | Up to +0.02 |

**Price Calculation:**
```rust
if side == BUY:
    limit_price = min(whale_price + buffer, 0.99)
else:  // SELL
    limit_price = max(whale_price - buffer, 0.01)
```

**Why Price Buffers:**
- **Large trades:** Higher buffer improves fill probability for time-sensitive trades
- **Small trades:** No buffer minimizes slippage cost for less urgent trades
- **Special markets (Tennis/Soccer):** Additional buffer accounts for volatility

### 2.4 Execution Tier Strategy

The bot uses **tiered execution** based on trade size to optimize for different market conditions:

#### Tier 1: Large Trades (4000+ shares)
**Strategy:** Aggressive execution
- Price buffer: +0.01
- Size multiplier: 1.25x (25% larger position)
- Order type: FAK (Fill and Kill)
- Resubmit attempts: 5
- Price chasing: Yes (first retry only)
- Max resubmit buffer: +0.01

**Rationale:** Large trades indicate strong conviction. More aggressive execution maximizes exposure while buffer ensures fills.

#### Tier 2: Medium Trades (2000-3999 shares)
**Strategy:** Balanced execution
- Price buffer: +0.01
- Size multiplier: 1.0x (normal scaling)
- Order type: FAK
- Resubmit attempts: 4
- Price chasing: No
- Max resubmit buffer: 0.00

**Rationale:** Standard execution with moderate buffer. No price chasing prevents overpaying.

#### Tier 3: Small Trades (1000-1999 shares)
**Strategy:** Conservative execution
- Price buffer: 0.00
- Size multiplier: 1.0x
- Order type: FAK
- Resubmit attempts: 4
- Price chasing: No
- Max resubmit buffer: 0.00

**Rationale:** Small trades get conservative treatment. No buffer minimizes slippage.

#### Tier 4: Very Small Trades (<1000 shares)
**Strategy:** Minimal execution
- Price buffer: 0.00
- Size multiplier: 1.0x
- Order type: FAK
- Resubmit attempts: 4
- Price chasing: No
- Max resubmit buffer: 0.00

**Rationale:** Minimal exposure, minimal slippage. Probabilistic sizing may skip very small trades.

### 2.5 Order Type Selection

**FAK (Fill and Kill) Orders:**
- Used for: All buy orders, most retry attempts
- Behavior: Executes immediately or cancels (no order book placement)
- Advantage: Fast execution, no stale orders
- Use case: Time-sensitive trades where immediate execution is preferred

**GTD (Good Till Date) Orders:**
- Used for: All sell orders, final retry attempt on failed buys
- Behavior: Places order on book with expiration time
- Expiration:
  - **Live markets:** 61 seconds (faster expiration for active markets)
  - **Non-live markets:** 1800 seconds (30 minutes, more patient)
- Advantage: Allows market to come to your price
- Use case: Less urgent trades, final attempts after FAK failures

**Selection Logic:**
```rust
if side == SELL:
    order_type = GTD  // All sells use GTD
else:  // BUY
    if attempt == max_attempts:
        order_type = GTD  // Final attempt uses GTD
    else:
        order_type = FAK  // Earlier attempts use FAK
```

### 2.6 Risk Management (Circuit Breaker)

The bot implements a **multi-layer risk management system** to protect capital:

#### Layer 1: Trade Size Filtering
- **Minimum threshold:** 10 shares (configurable)
- **Purpose:** Filters out dust orders and very small trades
- **Skip reason:** Negative expected value after fees

#### Layer 2: Sequence Detection
- **Trigger:** Multiple large trades in short time window
- **Detection window:** 30 seconds (configurable)
- **Trigger threshold:** 2 consecutive large trades (configurable)
- **Large trade definition:** >1500 shares (configurable)

**Logic:**
```
if trade_size >= LARGE_TRADE_THRESHOLD:
    add_to_sequence_history(trade)
    
    if count_large_trades_in_window(30s) >= CONSECUTIVE_TRIGGER:
        trigger_book_depth_check()
```

#### Layer 3: Order Book Depth Analysis
- **Trigger:** After sequence detection or on demand
- **Requirement:** Minimum liquidity beyond whale's price
- **Default threshold:** $200 USD (configurable)
- **Check:** Analyzes order book to ensure sufficient depth

**Depth Calculation:**
```
if side == BUY:
    check_depth = sum(ask_price × ask_size) where ask_price <= (whale_price + buffer + 0.005)
else:  // SELL
    check_depth = sum(bid_price × bid_size) where bid_price >= (whale_price - buffer - 0.005)

if check_depth < MIN_DEPTH_USD:
    BLOCK_TRADE
```

#### Layer 4: Trip Mechanism
- **Trigger:** Book fetch failure or dangerous conditions detected
- **Action:** Block all trades for token for specified duration
- **Default duration:** 120 seconds (2 minutes, configurable)
- **Recovery:** Automatically resets after duration expires

**Trip Conditions:**
- Order book API call fails
- Detected manipulation patterns
- Multiple consecutive depth check failures

### 2.7 Resubmission Strategy

When an order fails to fill completely, the bot implements intelligent resubmission:

#### Retry Attempts by Tier

**Large Trades (4000+ shares):**
- Max attempts: **5**
- Attempt 1: Price +0.01 (chase)
- Attempts 2-5: Same price (flat retries)
- Delay: None (immediate retries)
- Final attempt: GTD order (places on book)

**Small/Medium Trades (<4000 shares):**
- Max attempts: **4**
- All attempts: Same price (no chasing)
- Delay: 50ms between attempts (for <1000 shares)
- Final attempt: GTD order (places on book)

#### Resubmission Flow

```
1. Initial order placed (FAK)
   ↓
2. Order response received
   ↓
3. Check fill status:
   - Fully filled → DONE
   - Partially filled → Continue with remaining size
   - Not filled → Retry
   ↓
4. Retry logic:
   - Calculate new price (with/without increment)
   - Check if price exceeds max buffer
   - Submit retry order
   ↓
5. Repeat until max attempts or fully filled
   ↓
6. Final attempt: GTD order (if not fully filled)
```

#### Price Escalation Rules

**Large Trades Only (4000+ shares):**
- **Attempt 1:** Chase price +0.01 (up to max buffer)
- **Attempts 2-5:** Flat retries at same price
- **Max total buffer:** +0.02 (initial +0.01 + resubmit +0.01)

**Small/Medium Trades:**
- **All attempts:** Flat retries (no price escalation)
- **Rationale:** Prevents overpaying on smaller trades

### 2.8 Market-Specific Adjustments

#### Tennis Markets (ATP)
- **Additional buffer:** +0.01
- **Detection:** Checks cached tennis token list
- **Rationale:** Tennis markets can have higher volatility
- **Applied to:** All tennis market trades regardless of size

#### Soccer Markets (Ligue 1)
- **Additional buffer:** +0.01
- **Detection:** Checks cached soccer token list
- **Rationale:** Soccer markets can have rapid price movements
- **Applied to:** All soccer market trades regardless of size

#### Live vs Non-Live Markets

**Live Markets:**
- **GTD expiration:** 61 seconds
- **Detection:** Checks market live status cache
- **Rationale:** Faster expiration for active markets prevents stale orders

**Non-Live Markets:**
- **GTD expiration:** 1800 seconds (30 minutes)
- **Rationale:** More patient approach for inactive markets

### 2.9 Execution Flow (Complete Decision Tree)

```
1. BLOCKCHAIN EVENT RECEIVED
   ↓
2. VALIDATE EVENT
   ├─ Is from target whale? → NO → SKIP
   ├─ Valid trade data? → NO → SKIP
   └─ Trade size >= minimum? → NO → SKIP
   ↓
3. RISK CHECK (Layer 1)
   ├─ Trade too small? → YES → SKIP (SKIPPED_SMALL)
   └─ Continue
   ↓
4. SEQUENCE CHECK (Layer 2)
   ├─ Large trade? → YES → Add to sequence
   ├─ Sequence triggered? → YES → Depth check required
   └─ Continue
   ↓
5. DEPTH CHECK (Layer 3, if triggered)
   ├─ Fetch order book
   ├─ Calculate depth beyond price
   ├─ Depth sufficient? → NO → BLOCK (RISK_BLOCKED)
   └─ Continue
   ↓
6. TRIP CHECK (Layer 4)
   ├─ Token tripped? → YES → BLOCK (RISK_BLOCKED: TRIPPED)
   └─ Continue
   ↓
7. POSITION SIZING
   ├─ Calculate base size (whale_size × 0.02)
   ├─ Apply tier multiplier
   ├─ Check minimum size requirement
   ├─ Probabilistic sizing? → Maybe skip
   └─ Final size determined
   ↓
8. PRICE CALCULATION
   ├─ Get base buffer from tier
   ├─ Add tennis buffer (if tennis market)
   ├─ Add soccer buffer (if soccer market)
   ├─ Calculate limit price
   └─ Clamp to valid range (0.01-0.99)
   ↓
9. ORDER TYPE SELECTION
   ├─ Side == SELL? → YES → GTD
   ├─ Side == BUY? → YES → FAK (initially)
   └─ Order type determined
   ↓
10. ORDER SUBMISSION
    ├─ Create signed order
    ├─ Submit to Polymarket API
    └─ Receive response
    ↓
11. RESPONSE HANDLING
    ├─ Success? → Check fill amount
    │   ├─ Fully filled → DONE
    │   ├─ Partially filled → Resubmit remaining
    │   └─ Not filled → Retry logic
    └─ Failure? → Retry logic
    ↓
12. RESUBMISSION (if needed)
    ├─ Calculate retry price
    ├─ Check max attempts
    ├─ Submit retry order
    └─ Repeat until filled or max attempts
    ↓
13. FINAL ATTEMPT (if not filled)
    ├─ Switch to GTD order
    ├─ Set appropriate expiration
    └─ Place on order book
    ↓
14. LOGGING
    ├─ Log to CSV file
    ├─ Print to console
    └─ Update statistics
```

## 3. Strategy Parameters Summary

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| `SCALING_RATIO` | 0.02 (2%) | Base position size relative to whale |
| `MIN_WHALE_SHARES_TO_COPY` | 10.0 | Minimum whale trade size to copy |
| `MIN_CASH_VALUE` | $1.01 | Minimum order value in USD |
| `MIN_SHARE_COUNT` | 0.0 | Minimum share count (usually overridden by cash value) |
| `USE_PROBABILISTIC_SIZING` | true | Enable probabilistic execution for small positions |
| `PRICE_BUFFER` (default) | 0.00 | Default price buffer |
| `CB_LARGE_TRADE_SHARES` | 1500.0 | Threshold for "large trade" detection |
| `CB_CONSECUTIVE_TRIGGER` | 2 | Number of large trades to trigger depth check |
| `CB_SEQUENCE_WINDOW_SECS` | 30 | Time window for sequence detection |
| `CB_MIN_DEPTH_USD` | $200.0 | Minimum order book depth required |
| `CB_TRIP_DURATION_SECS` | 120 | Duration to block trades after trip |
| `RESUBMIT_PRICE_INCREMENT` | 0.01 | Price increment for resubmission |
| Tennis buffer | +0.01 | Additional buffer for tennis markets |
| Soccer buffer | +0.01 | Additional buffer for soccer markets |

## 4. Detailed Strategy Logic Deep Dive

### 4.1 Position Sizing Algorithm (Step-by-Step)

**Step 1: Calculate Base Target Size**
```rust
// From: src/settings.rs
const SCALING_RATIO: f64 = 0.02;  // 2%

base_target = whale_shares × SCALING_RATIO
// Example: 10,000 shares × 0.02 = 200 shares
```

**Step 2: Apply Tier-Based Size Multiplier**
```rust
// From: src/settings.rs get_tier_params()
if whale_shares >= 4000.0:
    size_multiplier = 1.25  // Large trades get 25% boost
elif whale_shares >= 2000.0:
    size_multiplier = 1.0   // Medium trades: normal
elif whale_shares >= 1000.0:
    size_multiplier = 1.0   // Small trades: normal
else:
    size_multiplier = 1.0   // Very small: normal

scaled_target = base_target × size_multiplier
// Example: 200 shares × 1.25 = 250 shares (for 4000+ tier)
```

**Step 3: Calculate Minimum Required Size**
```rust
// From: src/main.rs calculate_safe_size()
const MIN_CASH_VALUE: f64 = 1.01;  // Minimum $1.01 order value
const MIN_SHARE_COUNT: f64 = 0.0;  // Usually overridden by cash value

minimum_size = max(MIN_CASH_VALUE / price, MIN_SHARE_COUNT)
// Example: max(1.01 / 0.50, 0.0) = max(2.02, 0.0) = 2.02 shares
```

**Step 4: Probabilistic Execution Check**
```rust
// From: src/main.rs calculate_safe_size()
const USE_PROBABILISTIC_SIZING: bool = true;

if scaled_target >= minimum_size:
    return (scaled_target, SizeType::Scaled)  // Full execution
    
else if USE_PROBABILISTIC_SIZING:
    probability = scaled_target / minimum_size
    // Example: 1.5 shares / 2.02 shares = 0.743 (74.3%)
    
    if random() < probability:
        return (minimum_size, SizeType::ProbHit(74))  // Execute
    else:
        return (0.0, SizeType::ProbSkip(74))  // Skip
        
else:
    return (minimum_size, SizeType::Scaled)  // Always execute minimum
```

**Complete Example 1 (Large Trade - Full Execution):**
```
Whale Trade: 10,000 shares @ $0.50

Step 1: base_target = 10,000 × 0.02 = 200 shares
Step 2: size_multiplier = 1.25 (4000+ tier)
        scaled_target = 200 × 1.25 = 250 shares
Step 3: minimum_size = max(1.01 / 0.50, 0.0) = 2.02 shares
Step 4: 250 >= 2.02 → Execute full size (SCALED)
        
Final Order: 250 shares @ $0.50 = $125 USD
```

**Complete Example 2 (Small Trade - Probabilistic Execution):**
```
Whale Trade: 50 shares @ $0.60

Step 1: base_target = 50 × 0.02 = 1.0 share
Step 2: size_multiplier = 1.0 (below 1000 tier)
        scaled_target = 1.0 × 1.0 = 1.0 share
Step 3: minimum_size = max(1.01 / 0.60, 0.0) = 1.68 shares
Step 4: 1.0 < 1.68 → Probabilistic sizing
        
        probability = 1.0 / 1.68 = 0.595 (59.5%)
        random_value = 0.42 (for example)
        
        Since 0.42 < 0.595:
        → Execute with minimum size
        
Final Order: 1.68 shares @ $0.60 = $1.01 USD (PROB_HIT 60%)
```

**Complete Example 3 (Very Small Trade - Probabilistic Skip):**
```
Whale Trade: 30 shares @ $0.70

Step 1: base_target = 30 × 0.02 = 0.6 shares
Step 2: size_multiplier = 1.0
        scaled_target = 0.6 × 1.0 = 0.6 shares
Step 3: minimum_size = max(1.01 / 0.70, 0.0) = 1.44 shares
Step 4: 0.6 < 1.44 → Probabilistic sizing
        
        probability = 0.6 / 1.44 = 0.417 (41.7%)
        random_value = 0.65 (for example)
        
        Since 0.65 >= 0.417:
        → Skip trade (PROB_SKIP 42%)
        
Result: No order placed (trade too small to justify minimum order cost)
```

**Why Probabilistic Sizing?**

The probabilistic sizing system prevents negative expected value trades while still allowing participation in very small whale trades occasionally. 

**Mathematical Rationale:**
- Very small positions (<$1.01) would cost more in fees than they're worth
- But completely skipping all small trades means missing some opportunities
- Solution: Execute small trades probabilistically based on their size relative to minimum

**Expected Value Calculation:**
```
EV = (probability × profit) - fees

Without probabilistic sizing:
- Always execute minimum: EV = profit - fees (often negative)
- Always skip: EV = 0 (miss opportunities)

With probabilistic sizing:
- Execute with probability: EV = (probability × profit) - (probability × fees)
- This ensures EV is non-negative on average
```

### 4.2 Price Calculation Logic (Detailed)

**Step 1: Determine Base Buffer from Tier**
```rust
// From: src/settings.rs get_tier_params()
if whale_shares >= 4000.0:
    base_buffer = 0.01  // Large: +0.01 buffer
elif whale_shares >= 2000.0:
    base_buffer = 0.01  // Medium: +0.01 buffer
elif whale_shares >= 1000.0:
    base_buffer = 0.00  // Small: no buffer
else:
    base_buffer = 0.00  // Very small: no buffer
```

**Step 2: Add Sport-Specific Buffers**
```rust
// From: src/settings.rs get_tier_params()
tennis_buffer = tennis_markets::get_tennis_token_buffer(token_id)  // +0.01 if tennis
soccer_buffer = soccer_markets::get_soccer_token_buffer(token_id)  // +0.01 if soccer

total_buffer = base_buffer + tennis_buffer + soccer_buffer
```

**Step 3: Calculate Limit Price**
```rust
// From: src/main.rs process_order()
if side_is_buy:
    limit_price = min(whale_price + total_buffer, 0.99)  // Cap at 0.99
else:  // SELL
    limit_price = max(whale_price - total_buffer, 0.01)  // Floor at 0.01
```

**Complete Example:**
```
Whale Trade: BUY 5,000 shares @ $0.55 (Tennis Market)

Step 1: base_buffer = 0.01 (4000+ tier)
Step 2: tennis_buffer = 0.01 (tennis market detected)
        total_buffer = 0.01 + 0.01 = 0.02
Step 3: limit_price = min(0.55 + 0.02, 0.99) = 0.57
        
Final Limit Price: $0.57 (0.02 above whale's $0.55)
```

### 4.3 Risk Guard (Circuit Breaker) Logic (Detailed)

**Layer 1: Fast Path Check**
```rust
// From: src/risk_guard.rs check_fast()
pub fn check_fast(&mut self, token_id: &str, shares: f64) -> SafetyEvaluation {
    // Check if token is currently tripped
    if let Some(tripped_until) = self.tokens.get(token_id)
        .and_then(|state| state.tripped_until) {
        if Instant::now() < tripped_until {
            return SafetyEvaluation {
                decision: SafetyDecision::Block,
                reason: SafetyReason::Tripped { secs_left: ... },
                consecutive_large: 0,
            };
        }
    }
    
    // Check if trade is large enough to trigger sequence check
    if shares < self.config.large_trade_shares {  // Default: 1500.0
        return SafetyEvaluation {
            decision: SafetyDecision::Allow,
            reason: SafetyReason::SmallTrade,
            consecutive_large: 0,
        };
    }
    
    // Add to sequence history
    self.add_to_sequence(token_id, shares);
    
    // Count consecutive large trades in window
    let count = self.count_in_window(token_id, self.config.sequence_window);  // 30s
    
    if count >= self.config.consecutive_trigger {  // Default: 2
        return SafetyEvaluation {
            decision: SafetyDecision::FetchBook,
            reason: SafetyReason::SeqNeedBook { count },
            consecutive_large: count,
        };
    }
    
    SafetyEvaluation {
        decision: SafetyDecision::Allow,
        reason: SafetyReason::SeqOk { count },
        consecutive_large: count,
    }
}
```

**Layer 2: Order Book Depth Check**
```rust
// From: src/risk_guard.rs check_with_book()
pub fn check_with_book(
    &mut self, 
    token_id: &str, 
    consecutive_count: u8, 
    depth_usd: f64
) -> SafetyEvaluation {
    if depth_usd < self.config.min_depth_beyond_usd {  // Default: $200
        // Trip the token (block for duration)
        self.trip(token_id);
        
        SafetyEvaluation {
            decision: SafetyDecision::Block,
            reason: SafetyReason::Trap { 
                seq: consecutive_count, 
                depth_usd: depth_usd as u16 
            },
            consecutive_large: consecutive_count,
        }
    } else {
        SafetyEvaluation {
            decision: SafetyDecision::Allow,
            reason: SafetyReason::DepthOk { 
                seq: consecutive_count, 
                depth_usd: depth_usd as u16 
            },
            consecutive_large: consecutive_count,
        }
    }
}
```

**Depth Calculation:**
```rust
// From: src/risk_guard.rs calc_liquidity_depth()
pub fn calc_liquidity_depth(
    side: TradeSide, 
    levels: &[(f64, f64)],  // (price, size) tuples
    threshold: f64
) -> f64 {
    // Adjust threshold by 0.5% for safety margin
    let threshold_adj = if side == TradeSide::Buy {
        threshold * 1.005  // Buy: check slightly above
    } else {
        threshold * 0.995  // Sell: check slightly below
    };
    
    let mut total_usd = 0.0;
    for &(price, size) in levels {
        let beyond = if side == TradeSide::Buy {
            price > threshold_adj  // Asks above threshold
        } else {
            price < threshold_adj  // Bids below threshold
        };
        
        if beyond {
            total_usd += price * size;  // Add USD value
        }
    }
    
    total_usd
}
```

**Example Risk Check Flow:**
```
Event: Whale buys 2,000 shares @ $0.50

Step 1: check_fast()
  - shares (2000) >= large_trade_threshold (1500) ✓
  - Add to sequence history
  - Count in 30s window: 2 trades
  - 2 >= consecutive_trigger (2) ✓
  → Decision: FetchBook (need depth check)
  
Step 2: Fetch order book
  - Get asks at prices > $0.50
  - Calculate depth: $450 USD
  
Step 3: check_with_book()
  - depth ($450) >= min_depth ($200) ✓
  → Decision: Allow (trade passes)
```

### 4.4 Resubmission Logic (Detailed Algorithm)

**Initial Order Submission:**
```rust
// From: src/main.rs process_order()
// First attempt: FAK order
let args = OrderArgs {
    token_id: token_id,
    price: limit_price,
    size: calculated_size,
    side: "BUY",
    order_type: Some("FAK".to_string()),
    ...
};

let response = client.post_order_fast(body, creds)?;

// Parse response
if response.status().is_success() {
    let order_resp: OrderResponse = serde_json::from_str(&response.text())?;
    let filled_shares: f64 = order_resp.taking_amount.parse().unwrap_or(0.0);
    
    if filled_shares < requested_size {
        // Partial fill → resubmit remaining
        let remaining = requested_size - filled_shares;
        if remaining >= minimum_threshold {
            send_resubmit_request(...);
        }
    }
}
```

**Resubmission Price Escalation:**
```rust
// From: src/main.rs resubmit_worker()
fn calculate_resubmit_price(
    whale_shares: f64,
    attempt: u8,
    current_price: f64,
    max_price: f64
) -> f64 {
    // Only large trades (4000+) chase on first attempt
    let should_chase = if whale_shares >= 4000.0 {
        attempt == 1  // Only attempt 1
    } else {
        false  // Never chase
    };
    
    let increment = if should_chase {
        RESUBMIT_PRICE_INCREMENT  // +0.01
    } else {
        0.0  // Flat retry
    };
    
    let new_price = current_price + increment;
    
    // Don't exceed max buffer
    if new_price > max_price {
        return max_price;  // Cap at max
    }
    
    new_price
}
```

**Resubmission Attempt Flow:**
```rust
// From: src/main.rs resubmit_worker()
let max_attempts = if whale_shares >= 4000.0 { 5 } else { 4 };

for attempt in 1..=max_attempts {
    let is_last = attempt == max_attempts;
    
    // Calculate price
    let price = calculate_resubmit_price(...);
    
    // Submit order
    let (success, body, filled) = submit_resubmit_order(...);
    
    if success {
        if is_last {
            // GTD order placed (may fill later)
            return "GTD_SUBMITTED";
        } else {
            // FAK order: check fill
            if filled >= remaining_size {
                return "FULLY_FILLED";
            } else {
                // Partial fill: continue with remaining
                remaining_size -= filled;
                continue;
            }
        }
    } else {
        // Failure: retry if not last attempt
        if !is_last {
            if whale_shares < 1000.0 {
                sleep(50ms);  // Small trades: delay
            }
            continue;
        } else {
            return "FAILED";
        }
    }
}
```

**Complete Resubmission Example:**
```
Initial Order: 250 shares @ $0.57 (FAK)
Result: Partially filled (150 shares filled, 100 remaining)

Attempt 1 (FAK, price +0.01):
  Price: $0.58 (chased +0.01 for 4000+ tier)
  Result: Failed (no fill)
  Delay: None (large trade)
  
Attempt 2 (FAK, same price):
  Price: $0.58 (flat retry)
  Result: Filled 50 shares
  Remaining: 50 shares
  
Attempt 3 (FAK, same price):
  Price: $0.58 (flat retry)
  Result: Filled 30 shares
  Remaining: 20 shares
  
Attempt 4 (FAK, same price):
  Price: $0.58 (flat retry)
  Result: Failed
  
Attempt 5 (GTD, same price):
  Price: $0.58
  Type: GTD (expires in 61s if live market)
  Result: Order placed on book (may fill later)
  
Total Filled: 230/250 shares (92%)
```

### 4.5 Market Detection and Cache System

**Cache Structure:**
```rust
// From: src/market_cache.rs
pub struct MarketCaches {
    pub neg_risk: RwLock<FxHashMap<String, bool>>,      // Token → neg_risk flag
    pub slugs: RwLock<FxHashMap<String, String>>,       // Token → market slug
    pub tennis_tokens: RwLock<FxHashMap<String, String>>, // Token → category
    pub soccer_tokens: RwLock<FxHashMap<String, ()>>,   // Token → marker
    pub live_status: RwLock<FxHashMap<String, bool>>,   // Token → is_live
}
```

**Cache Lookup Flow:**
```rust
// Step 1: Check if token is tennis market
pub fn get_tennis_token_buffer(token_id: &str) -> f64 {
    global_caches().tennis_tokens.read()
        .map(|cache| {
            if cache.contains_key(token_id) {
                0.01  // Tennis markets get +0.01 buffer
            } else {
                0.0   // Not a tennis market
            }
        })
        .unwrap_or(0.0)
}

// Step 2: Check live status for GTD expiration
pub fn get_is_live(token_id: &str) -> Option<bool> {
    global_caches().live_status.read()
        .ok()?
        .get(token_id)
        .copied()
}

// Step 3: Use live status to determine expiration
pub fn get_gtd_expiry_secs(is_live: bool) -> u64 {
    if is_live {
        61      // Live: fast expiration (1 minute)
    } else {
        1800    // Non-live: patient (30 minutes)
    }
}
```

## 5. Strategy Rationale

### 5.1 Why 2% Scaling?
- **Risk Management:** Limits exposure while maintaining meaningful position sizes
- **Capital Efficiency:** Allows copying whales with much larger accounts
- **Practical:** Most users can comfortably trade at 2% scale
- **Mathematical:** 2% provides good balance between participation and risk

### 5.2 Why Tiered Execution?
- **Size Matters:** Larger trades indicate stronger conviction → more aggressive
- **Cost Optimization:** Smaller trades don't need aggressive execution → save on slippage
- **Fill Rate Optimization:** Different strategies optimize for different trade sizes
- **Market Impact:** Tiered approach minimizes market impact while maximizing fills

### 5.3 Why Price Buffers?
- **Fill Rate:** Improves probability of order execution
- **Time Sensitivity:** Large trades are often time-sensitive → buffer worth it
- **Market Impact:** Small buffer minimizes market impact while ensuring fills
- **Statistical Edge:** Small premium paid is offset by higher fill probability

### 5.4 Why Risk Guard System?
- **Protection:** Prevents copying during manipulation or low liquidity
- **Automated:** No manual intervention needed
- **Adaptive:** Resets automatically after conditions normalize
- **Multi-Layer:** Multiple checks catch different types of risks

### 5.5 Why Resubmission?
- **Market Conditions:** Order book changes rapidly → retries catch better prices
- **Partial Fills:** Common in volatile markets → resubmit remaining size
- **Tiered Approach:** Different strategies for different trade sizes
- **Persistence:** Final GTD attempt allows market to come to your price

### 5.6 Probabilistic Sizing Explained

**Purpose:**
Prevents negative expected value trades when the calculated position size is below the minimum required order size ($1.01).

**When It Triggers:**
- When `scaled_target < minimum_size`
- Only if `USE_PROBABILISTIC_SIZING = true` (default: true)

**How It Works:**
1. Calculate probability: `p = scaled_target / minimum_size`
2. Generate random number: `r = random() ∈ [0, 1)`
3. If `r < p`: Execute with `minimum_size` (PROB_HIT)
4. If `r >= p`: Skip trade (PROB_SKIP)

**Example Scenarios:**

**Scenario A: 60% Probability**
```
scaled_target = 0.6 shares
minimum_size = 1.0 share
probability = 0.6 / 1.0 = 0.6 (60%)

Result: 60% chance to execute 1.0 share, 40% chance to skip
```

**Scenario B: 80% Probability**
```
scaled_target = 0.8 shares  
minimum_size = 1.0 share
probability = 0.8 / 1.0 = 0.8 (80%)

Result: 80% chance to execute 1.0 share, 20% chance to skip
```

**Scenario C: 20% Probability**
```
scaled_target = 0.2 shares
minimum_size = 1.0 share
probability = 0.2 / 1.0 = 0.2 (20%)

Result: 20% chance to execute 1.0 share, 80% chance to skip
```

**Why This Works:**
- Ensures expected order size = `scaled_target` over many trades
- Prevents consistently losing money on tiny trades
- Still allows occasional participation in small whale trades
- Maintains risk profile while avoiding dust orders

## 6. Complete Strategy Logic Flow (Pseudo-Code)

### 6.1 Main Execution Loop

```rust
// Main bot loop (simplified)
loop {
    // 1. Receive blockchain event via WebSocket
    event = receive_blockchain_event();
    
    // 2. Parse and validate event
    if !is_valid_event(event) { continue; }
    if !is_from_target_whale(event) { continue; }
    
    parsed_event = parse_event(event);
    
    // 3. Process order asynchronously
    spawn(handle_event(parsed_event));
}
```

### 6.2 Event Handling Flow

```rust
async fn handle_event(event: ParsedEvent) {
    // Step 1: Get market information
    is_live = market_cache::get_is_live(&event.token_id);
    
    // Step 2: Submit order
    status = order_engine.submit(event, is_live).await;
    
    // Step 3: Log result
    log_to_csv(event, status);
    print_console(event, status);
}
```

### 6.3 Order Processing Logic

```rust
fn process_order(order_info: &OrderInfo) -> String {
    // FILTER 1: Skip disabled trading
    if !enable_trading { return "SKIPPED_DISABLED"; }
    if mock_trading { return "MOCK_ONLY"; }
    
    // FILTER 2: Minimum trade size
    if order_info.shares < MIN_WHALE_SHARES_TO_COPY {
        return "SKIPPED_SMALL";
    }
    
    // RISK CHECK 1: Fast path (no book fetch)
    let eval = risk_guard.check_fast(&token_id, shares);
    
    match eval.decision {
        SafetyDecision::Block => return "RISK_BLOCKED";
        SafetyDecision::FetchBook => {
            // RISK CHECK 2: Fetch order book and check depth
            let depth = fetch_book_depth(...);
            let final_eval = risk_guard.check_with_book(...);
            if final_eval.decision == SafetyDecision::Block {
                return "RISK_BLOCKED";
            }
        }
        SafetyDecision::Allow => {}
    }
    
    // CALCULATE: Position size
    let (buffer, order_type, size_multiplier) = get_tier_params(shares, is_buy, token_id);
    let (my_shares, size_type) = calculate_safe_size(shares, price, size_multiplier);
    
    if my_shares == 0.0 {
        return "SKIPPED_PROBABILITY";
    }
    
    // CALCULATE: Limit price
    let limit_price = if is_buy {
        min(whale_price + buffer, 0.99)
    } else {
        max(whale_price - buffer, 0.01)
    };
    
    // SUBMIT: Create and submit order
    let order = create_order(token_id, limit_price, my_shares, order_type);
    let response = submit_order(order);
    
    // HANDLE: Process response
    if response.success {
        if response.filled < my_shares {
            // Partial fill → resubmit remaining
            schedule_resubmit(...);
        }
        return format!("SUCCESS: {} filled", response.filled);
    } else {
        // Failure → schedule resubmit
        schedule_resubmit(...);
        return "RESUBMITTING";
    }
}
```

### 6.4 Decision Tree Visualization

```
START: Blockchain Event Received
│
├─ [Is from target whale?]
│  ├─ NO → SKIP (ignore event)
│  └─ YES → Continue
│
├─ [Is valid trade data?]
│  ├─ NO → SKIP (invalid data)
│  └─ YES → Continue
│
├─ [Trade size >= minimum?]
│  ├─ NO → SKIP (SKIPPED_SMALL)
│  └─ YES → Continue
│
├─ RISK CHECK LAYER 1: Fast Check
│  ├─ Token tripped? → YES → BLOCK (RISK_BLOCKED: TRIPPED)
│  ├─ Trade too small? → YES → ALLOW (fast path)
│  └─ Large trade? → YES → Check sequence
│     │
│     ├─ [Sequence triggered? (2+ large trades in 30s)]
│     │  ├─ YES → Fetch book for depth check
│     │  └─ NO → ALLOW (continue)
│
├─ RISK CHECK LAYER 2: Depth Check (if triggered)
│  ├─ Fetch order book
│  ├─ Calculate liquidity depth
│  ├─ [Depth >= $200?]
│  │  ├─ NO → BLOCK (RISK_BLOCKED: INSUFFICIENT_DEPTH)
│  │  └─ YES → ALLOW (continue)
│
├─ POSITION SIZING
│  ├─ Calculate base: whale_shares × 0.02
│  ├─ Apply tier multiplier
│  ├─ Check minimum size requirement
│  ├─ [Probabilistic sizing needed?]
│  │  ├─ YES → Random decision (may skip)
│  │  └─ NO → Use calculated size
│
├─ PRICE CALCULATION
│  ├─ Get base buffer from tier
│  ├─ Add tennis buffer (if tennis market)
│  ├─ Add soccer buffer (if soccer market)
│  └─ Calculate limit price (clamp 0.01-0.99)
│
├─ ORDER TYPE SELECTION
│  ├─ [Is SELL?]
│  │  ├─ YES → GTD order
│  │  └─ NO → FAK order (for BUY)
│
├─ ORDER SUBMISSION
│  ├─ Create signed order
│  ├─ Submit to Polymarket API
│  └─ Receive response
│
├─ RESPONSE HANDLING
│  ├─ [Success?]
│  │  ├─ YES → Check fill amount
│  │  │  ├─ Fully filled → DONE ✅
│  │  │  ├─ Partially filled → Resubmit remaining
│  │  │  └─ Not filled → Schedule retry
│  │  └─ NO → Schedule retry
│
├─ RESUBMISSION LOOP (if needed)
│  ├─ Calculate retry price (with/without increment)
│  ├─ Check max attempts
│  ├─ Submit retry order
│  └─ Repeat until filled or max attempts
│
└─ FINAL ATTEMPT (if not filled)
   ├─ Switch to GTD order
   ├─ Set expiration (61s live / 1800s non-live)
   └─ Place on order book
```

### 6.5 Strategy Parameters and Their Impact

**Position Sizing Parameters:**

| Parameter | Value | Impact if Increased | Impact if Decreased |
|-----------|-------|---------------------|---------------------|
| `SCALING_RATIO` | 0.02 (2%) | More exposure, higher risk | Less exposure, lower risk |
| `MIN_WHALE_SHARES_TO_COPY` | 10.0 | Fewer trades, larger average size | More trades, smaller average size |
| `MIN_CASH_VALUE` | $1.01 | Filters more small trades | Allows more small trades |
| Size Multiplier (4000+ tier) | 1.25x | Larger positions on big trades | Smaller positions on big trades |

**Price Buffer Parameters:**

| Parameter | Value | Impact if Increased | Impact if Decreased |
|-----------|-------|---------------------|---------------------|
| Base Buffer (4000+ tier) | +0.01 | Higher fill rate, more slippage | Lower fill rate, less slippage |
| Base Buffer (2000-3999) | +0.01 | Higher fill rate, more slippage | Lower fill rate, less slippage |
| Tennis Buffer | +0.01 | Better fills on tennis, more cost | Worse fills on tennis, less cost |
| Soccer Buffer | +0.01 | Better fills on soccer, more cost | Worse fills on soccer, less cost |

**Risk Management Parameters:**

| Parameter | Value | Impact if Increased | Impact if Decreased |
|-----------|-------|---------------------|---------------------|
| `CB_LARGE_TRADE_SHARES` | 1500.0 | Fewer large trades detected | More large trades detected |
| `CB_CONSECUTIVE_TRIGGER` | 2 | Less sensitive (more trades pass) | More sensitive (fewer trades pass) |
| `CB_SEQUENCE_WINDOW_SECS` | 30 | Longer window (less sensitive) | Shorter window (more sensitive) |
| `CB_MIN_DEPTH_USD` | $200.0 | More conservative (fewer trades) | Less conservative (more trades) |
| `CB_TRIP_DURATION_SECS` | 120 | Longer block (more conservative) | Shorter block (less conservative) |

## 7. Performance Considerations

### 7.1 Latency Optimization

**WebSocket Connection:**
- Real-time event monitoring (sub-second detection)
- Automatic reconnection on failures
- Heartbeat/keepalive mechanism

**Parallel Processing:**
- Order submission doesn't block event monitoring
- Multiple orders can be processed concurrently
- Async/await architecture for non-blocking I/O

**Cache System:**
- Market data cached to avoid API delays
- Periodic refresh (every 30 minutes)
- Thread-local storage for zero-allocation lookups

### 7.2 Execution Speed

**Order Types:**
- **FAK Orders:** Immediate execution or cancellation (<100ms)
- **GTD Orders:** Placed on book (no immediate execution wait)

**Optimized Paths:**
- Different code paths for different scenarios
- Hot path optimizations (minimal allocations)
- Fast failure paths (skip checks when possible)

**Retry Delays:**
- Large trades: Immediate retries (no delay)
- Small trades (<1000 shares): 50ms delay between retries
- Rationale: Small trades benefit from order book refresh time

### 7.3 Resource Usage

**Memory:**
- Thread-local buffers (avoid heap allocations)
- Cached data structures (bounded size)
- Efficient data structures (FxHashMap for speed)

**CPU:**
- Minimal parsing overhead
- Efficient hex/JSON parsing
- Optimized hot paths

**Network:**
- Connection pooling (HTTP client)
- Cached API responses
- Minimized API calls

## 8. Strategy Limitations

### 8.1 What the Strategy Does NOT Do

- ❌ **Market Analysis:** No prediction or market research
- ❌ **Portfolio Management:** No position rebalancing
- ❌ **Stop-Loss/Take-Profit:** No automatic exit orders
- ❌ **Position Monitoring:** No tracking after fill
- ❌ **Exit Strategy:** You manage closing positions manually
- ❌ **Multi-Whale:** Only copies one whale at a time
- ❌ **Market Making:** Not a market maker strategy
- ❌ **Arbitrage:** No cross-market arbitrage

### 8.2 Known Limitations

**Whale Dependency:**
- Strategy effectiveness depends entirely on whale quality
- If whale stops trading or performs poorly, bot mirrors that
- No independent market analysis to verify trades

**Market Conditions:**
- May underperform in highly volatile conditions
- Copy trading inherently lags (always behind whale)
- May struggle in low-liquidity markets

**Execution Limitations:**
- Some slippage expected (especially large trades)
- Fill rates <100% on some orders
- Timing delay (always slightly behind whale)

**Capital Requirements:**
- Need sufficient capital for 2% scaled positions
- Must maintain gas fees (MATIC) balance
- Large whale trades may require significant capital

## 9. Optimization Tips

### 9.1 For Better Fill Rates

**Monitor and Adjust:**
- Track fill rates in CSV logs
- Monitor whale's typical trade sizes
- Adjust `SCALING_RATIO` if consistently missing fills
- Consider increasing price buffers for specific markets

**Whale Selection:**
- Choose whales with consistent trade sizes
- Avoid whales that trade very large positions (may exceed your capital)
- Monitor whale's success rate over time

### 9.2 For Lower Slippage

**Price Buffer Optimization:**
- Reduce price buffers for small trades if slippage is high
- Monitor execution quality in CSV logs
- Adjust tier thresholds if needed
- Consider reducing buffers in high-volume markets

**Tier Adjustment:**
- Fine-tune tier boundaries if needed
- Adjust size multipliers based on your risk tolerance
- Monitor average slippage by tier

### 9.3 For Risk Management

**Conservative Approach:**
- Increase circuit breaker thresholds
- Increase `CB_MIN_DEPTH_USD` for stricter liquidity requirements
- Increase `CB_CONSECUTIVE_TRIGGER` to be less sensitive
- Reduce `SCALING_RATIO` to lower exposure

**Monitoring:**
- Monitor circuit breaker triggers in logs
- Track reasons for blocked trades
- Adjust parameters based on your risk profile
- Review CSV logs regularly for patterns

## 10. Strategy Monitoring and Metrics

### 10.1 Key Metrics to Track

**Execution Metrics:**
- **Fill Rate:** Percentage of orders that fully fill
  - Target: >80% full fills
  - Track: Partial fills vs full fills
  
- **Average Slippage:** Difference between intended and actual fill price
  - Calculate: `(actual_price - limit_price) / limit_price`
  - Track by tier and market type

- **Execution Time:** Time from detection to fill
  - Measure: Event timestamp → Fill timestamp
  - Target: <2 seconds average

**Risk Metrics:**
- **Circuit Breaker Triggers:** Frequency and reasons
  - Track: How often and why trades are blocked
  - Monitor: TRIPPED, INSUFFICIENT_DEPTH, etc.

- **Resubmission Rate:** How often orders need retries
  - Track: Percentage of orders requiring resubmission
  - Monitor: Average number of attempts needed

**Performance Metrics:**
- **Total Trades Executed:** Count over time period
- **Total Volume:** USD value of all trades
- **Average Trade Size:** Mean position size
- **Success Rate:** Percentage of profitable trades (requires manual tracking)

### 10.2 Logging and Analysis

**CSV Log File (`matches_optimized.csv`):**
- All detected and executed trades
- Columns: timestamp, block, token_id, usd_value, shares, price, direction, status, order_book_data, tx_hash, is_live
- Use for: Performance analysis, debugging, audit trail

**Console Output:**
- Real-time execution status
- Color-coded fill percentages
- Market indicators (TENNIS, SOCCER, live status)
- Best prices and order book data

**Analysis Recommendations:**
- Review CSV logs weekly
- Track metrics over time (weekly/monthly)
- Compare performance across different whales
- Identify patterns (time of day, market types, etc.)

## 11. Strategy Tuning Guide

### 11.1 When to Adjust Scaling Ratio

**Increase Scaling (More Aggressive):**
- If you have excess capital
- If whale is consistently profitable
- If fill rates are high (>90%)
- If you want higher exposure

**Decrease Scaling (More Conservative):**
- If capital is limited
- If experiencing losses
- If fill rates are low (<70%)
- If you want to test with smaller amounts

### 11.2 When to Adjust Price Buffers

**Increase Buffers:**
- If fill rates are low
- If missing many trades
- If whale trades are time-sensitive
- In volatile market conditions

**Decrease Buffers:**
- If slippage is high
- If fill rates are already good (>85%)
- In stable market conditions
- To reduce costs

### 11.3 When to Adjust Risk Guard Settings

**More Conservative (Fewer Trades):**
- Increase `CB_MIN_DEPTH_USD` (e.g., $300-500)
- Increase `CB_CONSECUTIVE_TRIGGER` (e.g., 3-4)
- Increase `CB_TRIP_DURATION_SECS` (e.g., 300s)
- Decrease `CB_LARGE_TRADE_SHARES` (e.g., 1000.0)

**More Aggressive (More Trades):**
- Decrease `CB_MIN_DEPTH_USD` (e.g., $100-150)
- Decrease `CB_CONSECUTIVE_TRIGGER` (e.g., 1)
- Decrease `CB_TRIP_DURATION_SECS` (e.g., 60s)
- Increase `CB_LARGE_TRADE_SHARES` (e.g., 2000.0)

## 12. Future Enhancements (Potential)

### 12.1 Multi-Whale Strategy
- Copy multiple whales simultaneously
- Portfolio allocation across whales
- Risk diversification
- Performance comparison

### 12.2 Dynamic Scaling
- Adjust scaling based on market conditions
- Time-of-day adjustments
- Volatility-based scaling
- Performance-based scaling

### 12.3 Advanced Risk Management
- Position limits per market
- Daily loss limits
- Win rate filters
- Correlation analysis

### 12.4 Machine Learning Integration
- Whale selection optimization
- Trade prediction
- Optimal entry/exit timing
- Pattern recognition

### 12.5 Exit Strategies
- Automatic profit taking
- Stop-loss implementation
- Time-based exits
- Trailing stops

### 12.6 Analytics Dashboard
- Real-time performance metrics
- Visual trade analysis
- Historical performance charts
- Risk metrics visualization

