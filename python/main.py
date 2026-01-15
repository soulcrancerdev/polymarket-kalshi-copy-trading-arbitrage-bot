"""Main entry point for prediction market trading system."""

import asyncio
from decimal import Decimal
from loguru import logger
from src.trader.orchestrator import PredictionMarketTrader
from src.utils.config import load_config
from src.core.interfaces import PositionSide, MarketStatus


def main():
    """Main function demonstrating usage."""
    # Load configuration
    config = load_config()
    
    # Initialize trader
    trader = PredictionMarketTrader(config)
    
    # List available platforms
    platforms = trader.list_platforms()
    logger.info(f"Available platforms: {', '.join(platforms)}")
    
    # Example: Get all markets
    logger.info("Fetching markets from all platforms...")
    markets = trader.get_all_markets(limit=10)
    logger.info(f"Found {len(markets)} markets")
    
    # Display sample markets
    for market in markets[:5]:
        logger.info(f"\nPlatform: {market.platform}")
        logger.info(f"Question: {market.question}")
        logger.info(f"Status: {market.status.value}")
        logger.info(f"Volume: {market.volume}")
    
    # Example: Get positions (requires user address)
    # user_address = "0x..."  # Replace with actual address
    # positions = trader.get_all_positions(user_address)
    # logger.info(f"Found {len(positions)} positions")
    
    # Example: Create a position (requires proper setup)
    # tx_hash = trader.create_position(
    #     platform="polymarket",
    #     market_id="0x...",
    #     side=PositionSide.YES,
    #     amount=Decimal("100.0")
    # )
    # logger.info(f"Created position: {tx_hash}")


if __name__ == "__main__":
    logger.add("trading.log", rotation="10 MB", level="DEBUG")
    main()
