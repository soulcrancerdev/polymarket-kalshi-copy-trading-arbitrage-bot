"""Hedgehog Markets connector."""

from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger
import httpx

from ..core.interfaces import (
    PredictionMarketConnector,
    Market,
    Position,
    PositionSide,
    MarketStatus
)
from ..blockchains.ethereum import EthereumConnector


class HedgehogMarketsConnector(PredictionMarketConnector):
    """Hedgehog Markets connector."""
    
    def __init__(self, blockchain_connector: EthereumConnector, api_url: str = "https://api.hedgehog.markets"):
        """
        Initialize Hedgehog Markets connector.
        
        Args:
            blockchain_connector: Ethereum blockchain connector instance
            api_url: Hedgehog Markets API URL
        """
        self.blockchain = blockchain_connector
        self.api_url = api_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make GET request to API."""
        try:
            response = await self.client.get(
                f"{self.api_url}/{endpoint}",
                params=params or {}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            raise
    
    def get_markets(
        self,
        category: Optional[str] = None,
        status: Optional[MarketStatus] = None,
        limit: int = 100
    ) -> List[Market]:
        """Get list of available markets."""
        import asyncio
        
        params = {"limit": limit}
        if category:
            params["category"] = category
            
        try:
            data = asyncio.run(self._get("markets", params))
            markets = []
            
            for item in data.get("markets", []):
                market_status = MarketStatus.OPEN
                if item.get("closed"):
                    market_status = MarketStatus.CLOSED
                if item.get("resolved"):
                    market_status = MarketStatus.RESOLVED
                    
                markets.append(Market(
                    market_id=item.get("id", ""),
                    question=item.get("question", ""),
                    description=item.get("description"),
                    outcomes=item.get("outcomes", ["YES", "NO"]),
                    status=market_status,
                    end_date=datetime.fromisoformat(item["endDate"]) if item.get("endDate") else None,
                    volume=Decimal(str(item.get("volume", 0))),
                    liquidity=Decimal(str(item.get("liquidity", 0))),
                    platform="hedgehog",
                    blockchain="ethereum",
                    metadata=item
                ))
                
            return markets
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []
    
    def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ID."""
        import asyncio
        
        try:
            data = asyncio.run(self._get(f"markets/{market_id}"))
            item = data.get("market", {})
            
            market_status = MarketStatus.OPEN
            if item.get("closed"):
                market_status = MarketStatus.CLOSED
            if item.get("resolved"):
                market_status = MarketStatus.RESOLVED
                
            return Market(
                market_id=item.get("id", market_id),
                question=item.get("question", ""),
                description=item.get("description"),
                outcomes=item.get("outcomes", ["YES", "NO"]),
                status=market_status,
                end_date=datetime.fromisoformat(item["endDate"]) if item.get("endDate") else None,
                volume=Decimal(str(item.get("volume", 0))),
                liquidity=Decimal(str(item.get("liquidity", 0))),
                platform="hedgehog",
                blockchain="ethereum",
                metadata=item
            )
        except Exception as e:
            logger.error(f"Error fetching market {market_id}: {e}")
            return None
    
    def get_positions(self, user_address: str) -> List[Position]:
        """Get user's positions."""
        import asyncio
        
        try:
            data = asyncio.run(self._get(f"users/{user_address}/positions"))
            positions = []
            
            for item in data.get("positions", []):
                positions.append(Position(
                    position_id=item.get("id", ""),
                    market_id=item.get("marketId", ""),
                    side=PositionSide.YES if item.get("side") == "YES" else PositionSide.NO,
                    shares=Decimal(str(item.get("shares", 0))),
                    cost_basis=Decimal(str(item.get("costBasis", 0))),
                    current_value=Decimal(str(item.get("currentValue", 0))),
                    platform="hedgehog",
                    blockchain="ethereum"
                ))
                
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def create_position(
        self,
        market_id: str,
        side: PositionSide,
        amount: Decimal,
        max_price: Optional[Decimal] = None
    ) -> str:
        """Create a new position. Returns transaction hash."""
        logger.warning("create_position not fully implemented - requires contract integration")
        raise NotImplementedError("Contract integration required")
    
    def close_position(
        self,
        position_id: str,
        shares: Optional[Decimal] = None
    ) -> str:
        """Close a position (full or partial). Returns transaction hash."""
        logger.warning("close_position not fully implemented - requires contract integration")
        raise NotImplementedError("Contract integration required")
    
    def get_price(self, market_id: str, side: PositionSide) -> Decimal:
        """Get current price for a market side."""
        import asyncio
        
        try:
            data = asyncio.run(self._get(f"markets/{market_id}/price"))
            prices = data.get("data", {})
            side_str = "YES" if side == PositionSide.YES else "NO"
            return Decimal(str(prices.get(side_str, 0)))
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return Decimal(0)
    
    def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """Get orderbook for a market."""
        import asyncio
        
        try:
            data = asyncio.run(self._get(f"markets/{market_id}/orderbook"))
            return data.get("data", {})
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return {}
