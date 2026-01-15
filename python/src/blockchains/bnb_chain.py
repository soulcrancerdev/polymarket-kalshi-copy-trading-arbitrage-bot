"""BNB Chain connector (EVM-compatible)."""

from decimal import Decimal
from typing import Dict, Any, Optional
from web3 import Web3
from web3.middleware import geth_poa_middleware
from loguru import logger

from .ethereum import EthereumConnector


class BNBChainConnector(EthereumConnector):
    """BNB Chain connector (EVM-compatible with Ethereum)."""
    
    def __init__(self, rpc_url: Optional[str] = None, private_key: Optional[str] = None):
        """
        Initialize BNB Chain connector.
        
        Args:
            rpc_url: RPC endpoint URL (defaults to public RPC)
            private_key: Optional private key for signing transactions
        """
        rpc_url = rpc_url or "https://bsc-dataseed1.binance.org"
        super().__init__(rpc_url, private_key)
        self.chain_id = 56
        
    def connect(self) -> bool:
        """Connect to BNB Chain network."""
        result = super().connect()
        if result:
            logger.info("Connected to BNB Chain network")
        return result
