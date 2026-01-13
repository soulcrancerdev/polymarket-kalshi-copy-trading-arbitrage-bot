# Polymarket Copy Trading Bot & Polymarket Arbitrage Bot

A Python bot for automated copy trading on Polymarket (on Polygon blockchain). This tool allows you to mirror trades from successful traders, implementing popular strategies discussed on X (formerly Twitter). Focus on high-edge traders, customizable parameters, and risk management to maximize profits.

## Contact Information

For questions, issues, collaboration, or custom development:
- Telegram: [@soulcrancerdev](https://t.me/soulcrancerdev)
- GitHub: [Polymarket Copy Trading Bot Repository](https://github.com/soulcrancerdev/polymarket-copy-trading-bot)

## Features

- **Polymarket Focus**: Trade exclusively on Polymarket via Polygon blockchain.
- **Copy Trading Automation**: Mirror trades from selected wallets with proportional sizing, filters, and custom rules.
- **Customizable Strategies**: Implement popular X-discussed tactics like portfolio of traders, sentiment bot copying, mean reversion, and undervaluation plays.
- **Core Functionality**:
  - Fetch trader wallets and market data.
  - Monitor orderbooks, prices, and trader activity.
  - Automate entries/exits with size multipliers, retries, and market skips.
  - Balance checking and position monitoring.
  - Dashboard for stats: fill rates, PNL tracking, slippage analysis.
- **Risk Management**: Set min/max trade sizes, % portfolio allocation, liquid market filters (e.g., min $1M volume).

## Popular Copy Trading Strategies

Based on trending discussions on X in 2025-2026, here are key strategies for successful Polymarket copy trading. These emphasize selecting consistent traders and avoiding common pitfalls (e.g., blind copying leading to losses in 90% of cases).

1. **Build a Portfolio of Traders**
   - Diversify across 3-5 traders with expertise in specific markets (e.g., sports, politics, crypto).
   - Analyze wallet history: P&L curve, win rate, risk-reward, max drawdown.
   - Use "Copy Score" (e.g., R² * win rate * profit factor) to rank traders.
   - Avoid loud whales; target small quants with steady profits.

2. **Proportional Sizing and Risk Limits**
   - Mirror trades proportionally (e.g., if whale risks 5% of $1M, you risk 5% of your portfolio).
   - Cap risk at 7% per trade, max 3 open positions.
   - Start small (0.1% allocation) for testing.

3. **Custom Bot Parameters**
   - Skip certain markets or categories.
   - Set size multipliers based on trade size/category (e.g., chase spreads for high-volume trades).
   - Use retries with FAK/GTD orders; adjust for live vs. non-live markets.
   - Copy % (e.g., 50-100% of trader's size).

4. **Target Specific Trader Types**
   - **AI Sentiment Bots**: Copy bots that profit from news reactions (5-20 min window).
   - **Mean Reversion Bots**: Follow bots snapping up panic dumps.
   - **Undervaluation Traders**: Mirror those betting on low-attention, mispriced markets (e.g., lower leagues).
   - **Low/High Price Specialists**: Copy low-entry (0.1¢) high-frequency or high-entry (99¢) near-resolution plays.

5. **Wallet Baskets Approach**
   - Group 5-10 similar wallets; enter only when 80%+ align on the same outcome within a tight price range.

6. **Pre-Copy Checklist**
   - Trade manually first (10-20 trades) to understand risk.
   - Observe 5-10 trades before automating.
   - Match trader expertise to your interests (e.g., skip NHL if unfamiliar).
   - Ensure liquid markets (min $1M volume) to avoid moving prices.

7. **Advanced Tips**
   - Combine with domain specialization (10-20% allocation).
   - Monitor for adverse selection: Ensure your slippage + fees < trader's edge per share.
   - Learn from failures: Avoid being exit liquidity or news traps.

## Installation

1. **Clone the repository**:
```bash
git clone https://github.com/soulcrancerdev/polymarket-copy-trading-bot
cd polymarket-copy-trading-bot
```

2. **Create a virtual environment** (recommended):
```bash
python -m venv venv

# On Windows
venv\Scripts\activate

# On Linux/Mac
source venv/bin/activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Set up environment variables**:
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your RPC URLs and private keys
```

## Configuration

Create a `.env` file in the project root with the following variables:

```env
# Polygon Configuration
POLYGON_RPC_URL=https://polygon-rpc.com
POLYGON_PRIVATE_KEY=your_polygon_private_key_here
```

**Security Note**: Never commit your `.env` file or private keys to version control. The `.gitignore` file is configured to exclude `.env` files.

### Getting RPC URLs

- **Polygon**: Use Polygon RPC endpoints or Alchemy.

## 🤝 Support & Community

Fork, star, and contribute to the project on GitHub: [Polymarket Copy Trading Bot](https://github.com/soulcrancerdev/polymarket-copy-trading-bot)

Reach out via Telegram: [@soulcrancerdev](https://t.me/soulcrancerdev)
