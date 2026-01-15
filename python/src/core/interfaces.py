"""Core interfaces for prediction market trading."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class MarketStatus(Enum):
    """Market status enumeration."""
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class PositionSide(Enum):
    """Position side enumeration."""
    YES = "yes"
    NO = "no"


@dataclass
class Market:
    """Represents a prediction market."""
    market_id: str
    question: str
    description: Optional[str]
    outcomes: List[str]
    status: MarketStatus
    end_date: Optional[datetime]
    volume: Optional[Decimal]
    liquidity: Optional[Decimal]
    platform: str
    blockchain: str
    metadata: Dict[str, Any]


@dataclass
class Position:
    """Represents a trading position."""
    position_id: str
    market_id: str
    side: PositionSide
    shares: Decimal
    cost_basis: Decimal
    current_value: Decimal
    platform: str
    blockchain: str


@dataclass
class Order:
    """Represents a trading order."""
    order_id: str
    market_id: str
    side: PositionSide
    shares: Decimal
    price: Decimal
    status: str
    platform: str
    timestamp: datetime


class BlockchainConnector(ABC):
    """Abstract base class for blockchain connectors."""
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to the blockchain."""
        pass
    
    @abstractmethod
    def get_balance(self, address: str, token: Optional[str] = None) -> Decimal:
        """Get balance for an address."""
        pass
    
    @abstractmethod
    def send_transaction(self, tx_data: Dict[str, Any]) -> str:
        """Send a transaction and return tx hash."""
        pass
    
    @abstractmethod
    def wait_for_confirmation(self, tx_hash: str, timeout: int = 300) -> bool:
        """Wait for transaction confirmation."""
        pass


class PredictionMarketConnector(ABC):
    """Abstract base class for prediction market platform connectors."""
    
    @abstractmethod
    def get_markets(
        self,
        category: Optional[str] = None,
        status: Optional[MarketStatus] = None,
        limit: int = 100
    ) -> List[Market]:
        """Get list of available markets."""
        pass
    
    @abstractmethod
    def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ID."""
        pass
    
    @abstractmethod
    def get_positions(self, user_address: str) -> List[Position]:
        """Get user's positions."""
        pass
    
    @abstractmethod
    def create_position(
        self,
        market_id: str,
        side: PositionSide,
        amount: Decimal,
        max_price: Optional[Decimal] = None
    ) -> str:
        """Create a new position. Returns transaction hash."""
        pass
    
    @abstractmethod
    def close_position(
        self,
        position_id: str,
        shares: Optional[Decimal] = None
    ) -> str:
        """Close a position (full or partial). Returns transaction hash."""
        pass
    
    @abstractmethod
    def get_price(self, market_id: str, side: PositionSide) -> Decimal:
        """Get current price for a market side."""
        pass
    
    @abstractmethod
    def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """Get orderbook for a market."""
        pass
