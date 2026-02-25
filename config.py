import os
import json
import logging
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class PositionConfig:
    """Configuration for a single LP position on any Uni V3 compatible chain."""
    chain: str
    rpc_url: str
    position_manager: str
    factory: str
    position_id: int
    initial_tx_hash: str
    use_poa_middleware: bool = True  # BSC needs it, HyperEVM doesn't

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Parse allowed user IDs into a list of integers
    _allowed_ids_str = os.getenv("ALLOWED_USER_IDS", "")
    ALLOWED_USER_IDS = [int(x.strip()) for x in _allowed_ids_str.split(',') if x.strip().isdigit()]

    # Monitor
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    WARNING_THRESHOLD_PERCENT = float(os.getenv("WARNING_THRESHOLD_PERCENT", "0.05"))

    # Positions (parsed from JSON)
    POSITIONS: List[PositionConfig] = []

    @classmethod
    def _load_positions(cls):
        """Parse POSITIONS JSON from env into PositionConfig objects."""
        raw = os.getenv("POSITIONS", "[]")
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse POSITIONS JSON: {e}")
        
        for item in items:
            cls.POSITIONS.append(PositionConfig(
                chain=item["chain"],
                rpc_url=item["rpc_url"],
                position_manager=item["position_manager"],
                factory=item["factory"],
                position_id=int(item["position_id"]),
                initial_tx_hash=item.get("initial_tx_hash", ""),
                use_poa_middleware=item.get("use_poa_middleware", False),
            ))

    @classmethod
    def validate(cls):
        """Validate that all required configuration variables are set."""
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN")
        if not cls.POSITIONS:
            errors.append("POSITIONS (no positions configured)")
            
        if errors:
            raise ValueError(f"Configuration error: {', '.join(errors)}\n"
                             f"Please check your .env file. See .env.example for reference.")
        
        for p in cls.POSITIONS:
            logger.info(f"Configured: [{p.chain}] Position #{p.position_id}")

# Load and validate on import
Config._load_positions()
Config.validate()
