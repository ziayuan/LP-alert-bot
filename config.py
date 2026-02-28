import os
import re
import json
import logging
from dotenv import load_dotenv
from dataclasses import dataclass, asdict
from typing import List, Optional

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Pre-configured chain settings — contract addresses are fixed per chain
CHAIN_PRESETS = {
    "BSC": {
        "rpc_url": "https://bsc-dataseed1.defibit.io/",
        "position_manager": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
        "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
        "use_poa_middleware": True,
    },
    "HyperEVM": {
        "rpc_url": "https://rpc.hyperliquid.xyz/evm",
        "position_manager": "0xeaD19AE861c29bBb2101E834922B2FEee69B9091",
        "factory": "0xFf7B3e8C00e57ea31477c32A5B52a58Eea47b072",
        "use_poa_middleware": False,
    },
}


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

    def to_dict(self) -> dict:
        return asdict(self)


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

    # Path to .env file for persistence
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

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

    # ── Dynamic position management ──────────────────────────────

    @classmethod
    def find_position(cls, position_id: int) -> Optional[PositionConfig]:
        """Find a position config by its ID."""
        for p in cls.POSITIONS:
            if p.position_id == position_id:
                return p
        return None

    @classmethod
    def add_position(cls, chain: str, position_id: int, initial_tx_hash: str) -> PositionConfig:
        """Add a new position using chain presets. Returns the new PositionConfig."""
        chain_upper = chain.upper()
        # Normalize common variations
        if chain_upper in ("HYPEREVM", "HYPER", "HL"):
            chain_upper = "HyperEVM"
        elif chain_upper == "BSC":
            chain_upper = "BSC"

        preset = CHAIN_PRESETS.get(chain_upper)
        if not preset:
            raise ValueError(f"Unknown chain: {chain}. Supported: {', '.join(CHAIN_PRESETS.keys())}")

        if cls.find_position(position_id):
            raise ValueError(f"Position #{position_id} already exists.")

        pos = PositionConfig(
            chain=chain_upper,
            position_id=position_id,
            initial_tx_hash=initial_tx_hash,
            **preset,
        )
        cls.POSITIONS.append(pos)
        cls._save_positions()
        return pos

    @classmethod
    def remove_position(cls, position_id: int) -> PositionConfig:
        """Remove a position by ID. Returns the removed config."""
        pos = cls.find_position(position_id)
        if not pos:
            raise ValueError(f"Position #{position_id} not found.")
        cls.POSITIONS.remove(pos)
        cls._save_positions()
        return pos

    @classmethod
    def update_position(cls, old_id: int, new_id: int, new_tx_hash: str) -> PositionConfig:
        """Update position ID and tx hash in-place. Returns the updated config."""
        pos = cls.find_position(old_id)
        if not pos:
            raise ValueError(f"Position #{old_id} not found.")
        if old_id != new_id and cls.find_position(new_id):
            raise ValueError(f"Position #{new_id} already exists.")
        pos.position_id = new_id
        pos.initial_tx_hash = new_tx_hash
        cls._save_positions()
        return pos

    @classmethod
    def _save_positions(cls):
        """Persist current POSITIONS list back to the .env file."""
        positions_json = json.dumps(
            [p.to_dict() for p in cls.POSITIONS],
            indent=2,
        )
        # Wrap in single quotes for .env
        new_value = f"POSITIONS='{positions_json}'"

        try:
            with open(cls._ENV_PATH, "r") as f:
                content = f.read()

            # Replace the existing POSITIONS= block (handles multi-line JSON)
            pattern = r"POSITIONS='.*?'"
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(pattern, new_value, content, flags=re.DOTALL)
            else:
                content = content.rstrip() + "\n" + new_value + "\n"

            with open(cls._ENV_PATH, "w") as f:
                f.write(content)

            logger.info("Positions saved to .env")
        except Exception as e:
            logger.error(f"Failed to save positions to .env: {e}")


# Load and validate on import
Config._load_positions()
Config.validate()
