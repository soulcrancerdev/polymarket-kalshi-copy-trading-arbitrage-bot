"""Solana blockchain connector."""

from decimal import Decimal
from typing import Dict, Any, Optional
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from loguru import logger
import base58

from ..core.interfaces import BlockchainConnector


class SolanaConnector(BlockchainConnector):
    """Solana blockchain connector."""
    
    def __init__(self, rpc_url: str, private_key: Optional[str] = None):
        """
        Initialize Solana connector.
        
        Args:
            rpc_url: RPC endpoint URL
            private_key: Optional base58-encoded private key for signing transactions
        """
        self.rpc_url = rpc_url
        self.private_key = private_key
        self.client = None
        self.keypair = None
        
    def connect(self) -> bool:
        """Connect to Solana network."""
        try:
            self.client = Client(self.rpc_url)
            
            # Test connection
            version = self.client.get_version()
            if not version:
                logger.error("Failed to connect to Solana network")
                return False
                
            if self.private_key:
                try:
                    key_bytes = base58.b58decode(self.private_key)
                    self.keypair = Keypair.from_bytes(key_bytes)
                    logger.info(f"Connected with address: {self.keypair.pubkey()}")
                except Exception as e:
                    logger.error(f"Error loading keypair: {e}")
                    return False
            else:
                logger.info("Connected without keypair (read-only mode)")
                
            return True
        except Exception as e:
            logger.error(f"Error connecting to Solana: {e}")
            return False
    
    def get_balance(self, address: str, token: Optional[str] = None) -> Decimal:
        """Get balance for an address."""
        if not self.client:
            raise RuntimeError("Not connected to blockchain")
            
        if token:
            # SPL token balance
            logger.warning("SPL token balance not fully implemented")
            return Decimal(0)
        else:
            # Native SOL balance
            pubkey = Pubkey.from_string(address)
            response = self.client.get_balance(pubkey)
            if response.value is None:
                return Decimal(0)
            # Convert lamports to SOL (1 SOL = 1e9 lamports)
            balance_sol = Decimal(response.value) / Decimal(1e9)
            return balance_sol
    
    def send_transaction(self, tx_data: Dict[str, Any]) -> str:
        """Send a transaction and return tx signature."""
        if not self.client or not self.keypair:
            raise RuntimeError("Not connected or no keypair configured")
            
        # Create transaction
        transaction = Transaction()
        
        # Add instructions (simplified - full implementation would handle various instruction types)
        if 'to' in tx_data and 'amount' in tx_data:
            to_pubkey = Pubkey.from_string(tx_data['to'])
            lamports = int(tx_data['amount'] * 1e9)  # Convert SOL to lamports
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=self.keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            transaction.add(transfer_ix)
        
        # Sign and send
        response = self.client.send_transaction(transaction, self.keypair)
        return response.value
    
    def wait_for_confirmation(self, tx_signature: str, timeout: int = 300) -> bool:
        """Wait for transaction confirmation."""
        if not self.client:
            raise RuntimeError("Not connected to blockchain")
            
        try:
            import time
            start_time = time.time()
            while time.time() - start_time < timeout:
                response = self.client.get_signature_statuses([tx_signature])
                if response.value and response.value[0]:
                    status = response.value[0]
                    if status.confirmation_status == Confirmed:
                        return True
                time.sleep(1)
            return False
        except Exception as e:
            logger.error(f"Error waiting for confirmation: {e}")
            return False
