"""Ethereum blockchain connector."""

from decimal import Decimal
from typing import Dict, Any, Optional
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account
from loguru import logger

from ..core.interfaces import BlockchainConnector


class EthereumConnector(BlockchainConnector):
    """Ethereum blockchain connector."""
    
    def __init__(self, rpc_url: str, private_key: Optional[str] = None):
        """
        Initialize Ethereum connector.
        
        Args:
            rpc_url: RPC endpoint URL
            private_key: Optional private key for signing transactions
        """
        self.rpc_url = rpc_url
        self.private_key = private_key
        self.w3 = None
        self.account = None
        
    def connect(self) -> bool:
        """Connect to Ethereum network."""
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            
            # Add PoA middleware for networks like Polygon
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            
            if not self.w3.is_connected():
                logger.error("Failed to connect to Ethereum network")
                return False
                
            if self.private_key:
                self.account = Account.from_key(self.private_key)
                logger.info(f"Connected with address: {self.account.address}")
            else:
                logger.info("Connected without account (read-only mode)")
                
            return True
        except Exception as e:
            logger.error(f"Error connecting to Ethereum: {e}")
            return False
    
    def get_balance(self, address: str, token: Optional[str] = None) -> Decimal:
        """Get balance for an address."""
        if not self.w3:
            raise RuntimeError("Not connected to blockchain")
            
        if token:
            # ERC-20 token balance
            # This is a simplified version - full implementation would use contract ABI
            logger.warning("ERC-20 token balance not fully implemented")
            return Decimal(0)
        else:
            # Native ETH balance
            balance_wei = self.w3.eth.get_balance(address)
            balance_eth = self.w3.from_wei(balance_wei, 'ether')
            return Decimal(str(balance_eth))
    
    def send_transaction(self, tx_data: Dict[str, Any]) -> str:
        """Send a transaction and return tx hash."""
        if not self.w3 or not self.account:
            raise RuntimeError("Not connected or no account configured")
            
        # Prepare transaction
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        tx = {
            'nonce': nonce,
            'to': tx_data.get('to'),
            'value': tx_data.get('value', 0),
            'gas': tx_data.get('gas', 21000),
            'gasPrice': tx_data.get('gasPrice') or self.w3.eth.gas_price,
            'data': tx_data.get('data', b''),
        }
        
        # Sign and send
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        return tx_hash.hex()
    
    def wait_for_confirmation(self, tx_hash: str, timeout: int = 300) -> bool:
        """Wait for transaction confirmation."""
        if not self.w3:
            raise RuntimeError("Not connected to blockchain")
            
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return receipt.status == 1
        except Exception as e:
            logger.error(f"Error waiting for confirmation: {e}")
            return False
