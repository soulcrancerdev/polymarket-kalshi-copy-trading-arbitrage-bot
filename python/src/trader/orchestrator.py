"""Unified trading orchestrator for all prediction markets."""

from typing import Dict, List, Optional, Any
from decimal import Decimal
from loguru import logger

from ..core.interfaces import (
    Market,
    Position,
    PositionSide,
    MarketStatus,
    PredictionMarketConnector
)
from ..blockchains.ethereum import EthereumConnector
from ..blockchains.polygon import PolygonConnector
from ..blockchains.solana import SolanaConnector
from ..blockchains.bnb_chain import BNBChainConnector
from ..markets.polymarket import PolymarketConnector
from ..markets.augur import AugurConnector
from ..markets.moonopol import MoonopolConnector
from ..markets.myriad import MyriadMarketsConnector
from ..markets.drift import DriftBETConnector
from ..markets.olab import OLABConnector
from ..markets.polkamarkets import PolkamarketsConnector
from ..markets.hedgehog import HedgehogMarketsConnector


class PredictionMarketTrader:
    """Unified trading interface for all prediction markets."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the trader with configuration.
        
        Args:
            config: Configuration dictionary with blockchain RPCs and private keys
        """
        self.config = config
        self.connectors: Dict[str, PredictionMarketConnector] = {}
        self._initialize_connectors()
        
    def _initialize_connectors(self):
        """Initialize all market connectors."""
        # Initialize blockchain connectors
        eth_connector = None
        polygon_connector = None
        solana_connector = None
        bnb_connector = None
        
        # Ethereum
        if "ethereum" in self.config.get("blockchains", {}):
            eth_config = self.config["blockchains"]["ethereum"]
            eth_connector = EthereumConnector(
                rpc_url=eth_config.get("rpc_url", "https://eth.llamarpc.com"),
                private_key=eth_config.get("private_key")
            )
            if eth_connector.connect():
                self.connectors["augur"] = AugurConnector(eth_connector)
                self.connectors["hedgehog"] = HedgehogMarketsConnector(eth_connector)
                logger.info("Initialized Ethereum-based markets")
        
        # Polygon
        if "polygon" in self.config.get("blockchains", {}):
            polygon_config = self.config["blockchains"]["polygon"]
            polygon_connector = PolygonConnector(
                rpc_url=polygon_config.get("rpc_url"),
                private_key=polygon_config.get("private_key")
            )
            if polygon_connector.connect():
                self.connectors["polymarket"] = PolymarketConnector(polygon_connector)
                self.connectors["polkamarkets"] = PolkamarketsConnector(polygon_connector)
                # Myriad can use Polygon
                if not eth_connector:
                    self.connectors["myriad"] = MyriadMarketsConnector(polygon_connector)
                logger.info("Initialized Polygon-based markets")
        
        # Solana
        if "solana" in self.config.get("blockchains", {}):
            solana_config = self.config["blockchains"]["solana"]
            solana_connector = SolanaConnector(
                rpc_url=solana_config.get("rpc_url", "https://api.mainnet-beta.solana.com"),
                private_key=solana_config.get("private_key")
            )
            if solana_connector.connect():
                self.connectors["moonopol"] = MoonopolConnector(solana_connector)
                self.connectors["drift"] = DriftBETConnector(solana_connector)
                logger.info("Initialized Solana-based markets")
        
        # BNB Chain
        if "bnb" in self.config.get("blockchains", {}):
            bnb_config = self.config["blockchains"]["bnb"]
            bnb_connector = BNBChainConnector(
                rpc_url=bnb_config.get("rpc_url"),
                private_key=bnb_config.get("private_key")
            )
            if bnb_connector.connect():
                self.connectors["olab"] = OLABConnector(bnb_connector)
                logger.info("Initialized BNB Chain-based markets")
        
        # Myriad (multi-chain) - prefer Ethereum if available
        if "myriad" not in self.connectors and eth_connector:
            self.connectors["myriad"] = MyriadMarketsConnector(eth_connector)
        
        logger.info(f"Initialized {len(self.connectors)} market connectors")
    
    def get_all_markets(
        self,
        platform: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[MarketStatus] = None,
        limit: int = 100
    ) -> List[Market]:
        """
        Get markets from all or a specific platform.
        
        Args:
            platform: Optional platform name to filter by
            category: Optional category filter
            status: Optional status filter
            limit: Maximum number of markets per platform
            
        Returns:
            List of markets
        """
        all_markets = []
        
        connectors_to_query = [self.connectors[platform]] if platform and platform in self.connectors else self.connectors.values()
        
        for connector in connectors_to_query:
            try:
                markets = connector.get_markets(category=category, status=status, limit=limit)
                all_markets.extend(markets)
                logger.debug(f"Fetched {len(markets)} markets from {connector.__class__.__name__}")
            except Exception as e:
                logger.error(f"Error fetching markets from {connector.__class__.__name__}: {e}")
        
        return all_markets
    
    def get_market(self, market_id: str, platform: str) -> Optional[Market]:
        """
        Get a specific market.
        
        Args:
            market_id: Market identifier
            platform: Platform name
            
        Returns:
            Market object or None
        """
        if platform not in self.connectors:
            logger.error(f"Platform {platform} not available")
            return None
        
        try:
            return self.connectors[platform].get_market(market_id)
        except Exception as e:
            logger.error(f"Error fetching market {market_id} from {platform}: {e}")
            return None
    
    def get_all_positions(self, user_address: str, platform: Optional[str] = None) -> List[Position]:
        """
        Get all positions across platforms.
        
        Args:
            user_address: User wallet address
            platform: Optional platform name to filter by
            
        Returns:
            List of positions
        """
        all_positions = []
        
        connectors_to_query = [self.connectors[platform]] if platform and platform in self.connectors else self.connectors.values()
        
        for connector in connectors_to_query:
            try:
                positions = connector.get_positions(user_address)
                all_positions.extend(positions)
                logger.debug(f"Fetched {len(positions)} positions from {connector.__class__.__name__}")
            except Exception as e:
                logger.error(f"Error fetching positions from {connector.__class__.__name__}: {e}")
        
        return all_positions
    
    def create_position(
        self,
        platform: str,
        market_id: str,
        side: PositionSide,
        amount: Decimal,
        max_price: Optional[Decimal] = None
    ) -> str:
        """
        Create a position on a specific platform.
        
        Args:
            platform: Platform name
            market_id: Market identifier
            side: Position side (YES/NO)
            amount: Amount to invest
            max_price: Optional maximum price
            
        Returns:
            Transaction hash
        """
        if platform not in self.connectors:
            raise ValueError(f"Platform {platform} not available")
        
        logger.info(f"Creating {side.value} position on {platform} market {market_id} with amount {amount}")
        return self.connectors[platform].create_position(
            market_id=market_id,
            side=side,
            amount=amount,
            max_price=max_price
        )
    
    def close_position(
        self,
        platform: str,
        position_id: str,
        shares: Optional[Decimal] = None
    ) -> str:
        """
        Close a position on a specific platform.
        
        Args:
            platform: Platform name
            position_id: Position identifier
            shares: Optional number of shares to close (None = close all)
            
        Returns:
            Transaction hash
        """
        if platform not in self.connectors:
            raise ValueError(f"Platform {platform} not available")
        
        logger.info(f"Closing position {position_id} on {platform}")
        return self.connectors[platform].close_position(
            position_id=position_id,
            shares=shares
        )
    
    def get_price(self, platform: str, market_id: str, side: PositionSide) -> Decimal:
        """
        Get current price for a market side.
        
        Args:
            platform: Platform name
            market_id: Market identifier
            side: Position side (YES/NO)
            
        Returns:
            Current price
        """
        if platform not in self.connectors:
            raise ValueError(f"Platform {platform} not available")
        
        return self.connectors[platform].get_price(market_id=market_id, side=side)
    
    def get_orderbook(self, platform: str, market_id: str) -> Dict[str, Any]:
        """
        Get orderbook for a market.
        
        Args:
            platform: Platform name
            market_id: Market identifier
            
        Returns:
            Orderbook data
        """
        if platform not in self.connectors:
            raise ValueError(f"Platform {platform} not available")
        
        return self.connectors[platform].get_orderbook(market_id=market_id)
    
    def list_platforms(self) -> List[str]:
        """Get list of available platforms."""
        return list(self.connectors.keys())
