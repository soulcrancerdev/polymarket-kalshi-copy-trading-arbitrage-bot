"""Polygon blockchain connector (EVM-compatible)."""

from decimal import Decimal
from typing import Dict, Any, Optional
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account
from loguru import logger

from .ethereum import EthereumConnector


class PolygonConnector(EthereumConnector):
    """Polygon blockchain connector (EVM-compatible with Ethereum)."""
    
    def __init__(self, rpc_url: Optional[str] = None, private_key: Optional[str] = None):
        """
        Initialize Polygon connector.
        
        Args:
            rpc_url: RPC endpoint URL (defaults to public RPC)
            private_key: Optional private key for signing transactions
        """
        rpc_url = rpc_url or "https://polygon-rpc.com"
        super().__init__(rpc_url, private_key)
        self.chain_id = 137
        
    def connect(self) -> bool:
        """Connect to Polygon network."""
        result = super().connect()
        if result:
            logger.info("Connected to Polygon network")
        return result
