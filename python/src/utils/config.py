"""Configuration management utilities."""

import os
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class BlockchainConfig(BaseSettings):
    """Blockchain configuration."""
    rpc_url: Optional[str] = None
    private_key: Optional[str] = None
    
    class Config:
        env_prefix = "BLOCKCHAIN_"


class TraderConfig(BaseSettings):
    """Trader configuration."""
    blockchains: Dict[str, Dict[str, str]] = {}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load from environment variables if not provided
        self._load_from_env()
    
    def _load_from_env(self):
        """Load configuration from environment variables."""
        # Ethereum
        if os.getenv("ETHEREUM_RPC_URL"):
            self.blockchains["ethereum"] = {
                "rpc_url": os.getenv("ETHEREUM_RPC_URL"),
                "private_key": os.getenv("ETHEREUM_PRIVATE_KEY")
            }
        
        # Polygon
        if os.getenv("POLYGON_RPC_URL"):
            self.blockchains["polygon"] = {
                "rpc_url": os.getenv("POLYGON_RPC_URL"),
                "private_key": os.getenv("POLYGON_PRIVATE_KEY")
            }
        
        # Solana
        if os.getenv("SOLANA_RPC_URL"):
            self.blockchains["solana"] = {
                "rpc_url": os.getenv("SOLANA_RPC_URL"),
                "private_key": os.getenv("SOLANA_PRIVATE_KEY")
            }
        
        # BNB Chain
        if os.getenv("BNB_RPC_URL"):
            self.blockchains["bnb"] = {
                "rpc_url": os.getenv("BNB_RPC_URL"),
                "private_key": os.getenv("BNB_PRIVATE_KEY")
            }


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from file or environment.
    
    Args:
        config_path: Optional path to config file
        
    Returns:
        Configuration dictionary
    """
    # Load .env file if it exists
    env_path = Path(config_path) if config_path else Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    
    config = TraderConfig()
    return {"blockchains": config.blockchains}
