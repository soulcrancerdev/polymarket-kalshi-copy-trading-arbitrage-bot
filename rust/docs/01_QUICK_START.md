# Quick Start Guide

The fastest way to get the bot running (5 minutes).

## Table of Contents

1. [Prerequisites Checklist](#1-prerequisites-checklist)
2. [5-Minute Setup](#2-5-minute-setup)
3. [Windows Users](#3-windows-users)
4. [Common First-Time Issues](#4-common-first-time-issues)
5. [Need More Help?](#5-need-more-help)
6. [Safety Reminders](#6-safety-reminders)

---

## 1. Prerequisites Checklist

- [ ] Rust installed (https://rustup.rs/)
- [ ] Polymarket account created
- [ ] MetaMask wallet with USDC on Polygon
- [ ] Alchemy account (free) - https://www.alchemy.com/

## 2. 5-Minute Setup

### 2.1 Step 1: Setup Environment (1 minute)

```bash
# Copy example config
cp .env.example .env  # Linux/macOS
# OR
copy .env.example .env  # Windows

# Edit .env file - fill in these 4 values:
# - PRIVATE_KEY (from MetaMask: Account Details → Export Private Key)
# - FUNDER_ADDRESS (your wallet address)
# - TARGET_WHALE_ADDRESS (whale to copy - from Polymarket leaderboard)
# - ALCHEMY_API_KEY (from https://www.alchemy.com/)
```

### 2.2 Step 2: Validate Config (30 seconds)

```bash
cargo run --release --bin validate_setup
```

Fix any errors it reports.

### 2.3 Step 3: Test in Mock Mode (1 minute)

```bash
# In .env, set:
# ENABLE_TRADING=false
# MOCK_TRADING=true

cargo run --release
```

Watch for connection and trade simulation messages.

### 2.4 Step 4: Run for Real (when ready)

```bash
# In .env, set:
# ENABLE_TRADING=true
# MOCK_TRADING=false

cargo run --release
# OR double-click run.bat (Windows)
```

## 3. Windows Users

Just double-click `run.bat` after setting up `.env`!

## 4. Common First-Time Issues

**"rustc not found"** → Install Rust from https://rustup.rs/ and restart terminal

**".env file not found"** → Copy `.env.example` to `.env`

**"PRIVATE_KEY required"** → Open `.env`, fill in your private key (remove `0x` if present)

**"API key required"** → Get free key from https://www.alchemy.com/, add to `.env`

## 5. Need More Help?

- **Detailed Setup:** See [02_SETUP_GUIDE.md](02_SETUP_GUIDE.md)
- **Configuration Options:** See [03_CONFIGURATION.md](03_CONFIGURATION.md)
- **Problems?** See [06_TROUBLESHOOTING.md](06_TROUBLESHOOTING.md)
- **How It Works:** See [04_FEATURES.md](04_FEATURES.md)
- **Strategy Logic:** See [05_STRATEGY.md](05_STRATEGY.md)

## 6. Safety Reminders

⚠️ **Before running with real money:**
- Test in mock mode first (`MOCK_TRADING=true`)
- Start with small amounts
- Monitor your positions
- Understand the risks

✅ **Your `.env` file contains secrets** - never share it or commit to git!

