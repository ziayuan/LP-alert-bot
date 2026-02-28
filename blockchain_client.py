import math
import logging
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from abis.constants import ERC20_ABI, POOL_ABI, POSITION_MANAGER_ABI, FACTORY_ABI
from config import PositionConfig
from v3_math import tick_to_price, get_fee_growth_inside, calculate_pending_fees, get_amounts_for_liquidity, Q96

logger = logging.getLogger(__name__)


def tick_to_sqrt_price_x96(tick: int) -> int:
    """Convert a tick to sqrtPriceX96 (integer)."""
    return int(math.sqrt(1.0001 ** tick) * Q96)


class BlockchainClient:
    """
    A blockchain client instance for a single LP position.
    Each position gets its own Web3 connection, contract references, and cached state.
    """

    def __init__(self, pos_config: PositionConfig):
        self.config = pos_config
        self.chain = pos_config.chain
        self.position_id = pos_config.position_id

        self.w3 = Web3(Web3.HTTPProvider(
            pos_config.rpc_url,
            request_kwargs={"timeout": 30}
        ))

        if pos_config.use_poa_middleware:
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise ConnectionError(f"[{self.chain}] Failed to connect to RPC: {pos_config.rpc_url}")

        nft_manager_addr = Web3.to_checksum_address(pos_config.position_manager)
        self.position_manager = self.w3.eth.contract(address=nft_manager_addr, abi=POSITION_MANAGER_ABI)
        self.factory_address = Web3.to_checksum_address(pos_config.factory)

        self.pool_contract = None
        self.token0 = None
        self.token1 = None
        self.token0_decimals = 18
        self.token1_decimals = 18
        self.token0_symbol = ""
        self.token1_symbol = ""
        self.pool_address = None
        self.fee_tier = 0

        # Cache for initial deposit
        self.initial_deposit_token0 = 0.0
        self.initial_deposit_token1 = 0.0
        self.position_open_timestamp = 0  # Unix timestamp of initial deposit
        self.is_initialized = False

    def initialize_position(self):
        """Fetches the static info about the position and the initial deposit."""
        logger.info(f"[{self.chain}] Initializing Position #{self.position_id}")
        pos = self.position_manager.functions.positions(self.position_id).call()

        self.token0 = pos[2]
        self.token1 = pos[3]
        self.fee_tier = pos[4]

        t0_contract = self.w3.eth.contract(address=self.token0, abi=ERC20_ABI)
        t1_contract = self.w3.eth.contract(address=self.token1, abi=ERC20_ABI)

        self.token0_symbol = t0_contract.functions.symbol().call()
        self.token0_decimals = t0_contract.functions.decimals().call()

        self.token1_symbol = t1_contract.functions.symbol().call()
        self.token1_decimals = t1_contract.functions.decimals().call()

        factory = self.w3.eth.contract(address=self.factory_address, abi=FACTORY_ABI)
        self.pool_address = factory.functions.getPool(self.token0, self.token1, self.fee_tier).call()
        self.pool_contract = self.w3.eth.contract(address=self.pool_address, abi=POOL_ABI)

        logger.info(f"[{self.chain}] Pool: {self.token0_symbol}/{self.token1_symbol} "
                     f"(Fee: {self.fee_tier}) at {self.pool_address}")

        self._parse_initial_deposit_tx()
        self.is_initialized = True

    def reinitialize(self):
        """Reset and re-initialize after a position update (new ID / tx hash)."""
        self.position_id = self.config.position_id
        self.initial_deposit_token0 = 0.0
        self.initial_deposit_token1 = 0.0
        self.position_open_timestamp = 0
        self.is_initialized = False
        self.initialize_position()

    def _parse_initial_deposit_tx(self):
        """Parses the TX Hash to find the exact amounts deposited."""
        tx_hash = self.config.initial_tx_hash
        if not tx_hash or len(tx_hash) < 66:
            logger.warning(f"[{self.chain}] No valid initial deposit TX Hash. IL calculation will be skipped.")
            return

        logger.info(f"[{self.chain}] Parsing initial deposit tx: {tx_hash}")
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)

            # Get block timestamp for APR calculation
            block = self.w3.eth.get_block(receipt.blockNumber)
            self.position_open_timestamp = block.timestamp
            logger.info(f"[{self.chain}] Position opened at block {receipt.blockNumber}, timestamp {self.position_open_timestamp}")
            nft_manager_addr = Web3.to_checksum_address(self.config.position_manager)

            INCREASE_LIQ_TOPIC = self.w3.keccak(
                text="IncreaseLiquidity(uint256,uint128,uint256,uint256)"
            ).hex()

            for log in receipt.logs:
                if (log.address == nft_manager_addr
                        and len(log.topics) > 0
                        and log.topics[0].hex() == INCREASE_LIQ_TOPIC):
                    token_id_in_log = int(log.topics[1].hex(), 16)
                    if token_id_in_log == self.position_id:
                        data = log.data.hex().replace("0x", "")
                        if len(data) >= 192:
                            amount0 = int(data[64:128], 16)
                            amount1 = int(data[128:192], 16)

                            self.initial_deposit_token0 = amount0 / (10 ** self.token0_decimals)
                            self.initial_deposit_token1 = amount1 / (10 ** self.token1_decimals)
                            logger.info(
                                f"[{self.chain}] Initial Deposit: "
                                f"{self.initial_deposit_token0} {self.token0_symbol}, "
                                f"{self.initial_deposit_token1} {self.token1_symbol}"
                            )
                            return

            logger.warning(f"[{self.chain}] IncreaseLiquidity event not found in tx for Position #{self.position_id}.")

        except Exception as e:
            logger.error(f"[{self.chain}] Error parsing tx {tx_hash}: {e}")

    def get_current_state(self):
        """Fetches real-time state of the pool and position."""
        if not self.is_initialized:
            self.initialize_position()

        # 1. Pool state
        slot0 = self.pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]
        current_tick = slot0[1]
        current_price = tick_to_price(current_tick, self.token0_decimals, self.token1_decimals)

        fee_growth_global_0 = self.pool_contract.functions.feeGrowthGlobal0X128().call()
        fee_growth_global_1 = self.pool_contract.functions.feeGrowthGlobal1X128().call()

        # 2. Position state
        pos = self.position_manager.functions.positions(self.position_id).call()
        tick_lower = pos[5]
        tick_upper = pos[6]
        liquidity = pos[7]
        fee_growth_inside_0_last = pos[8]
        fee_growth_inside_1_last = pos[9]
        tokens_owed0 = pos[10]
        tokens_owed1 = pos[11]

        # 3. Tick state for fee calculation
        tick_lower_state = self.pool_contract.functions.ticks(tick_lower).call()
        tick_upper_state = self.pool_contract.functions.ticks(tick_upper).call()

        fee_inside_0, fee_inside_1 = get_fee_growth_inside(
            tick_lower, tick_upper, current_tick,
            fee_growth_global_0, fee_growth_global_1,
            tick_lower_state[2], tick_lower_state[3],
            tick_upper_state[2], tick_upper_state[3]
        )

        uncollected_0, uncollected_1 = calculate_pending_fees(
            liquidity,
            fee_inside_0, fee_inside_1,
            fee_growth_inside_0_last, fee_growth_inside_1_last
        )

        earned_0 = (tokens_owed0 + uncollected_0) / (10 ** self.token0_decimals)
        earned_1 = (tokens_owed1 + uncollected_1) / (10 ** self.token1_decimals)

        price_lower = tick_to_price(tick_lower, self.token0_decimals, self.token1_decimals)
        price_upper = tick_to_price(tick_upper, self.token0_decimals, self.token1_decimals)
        bounds = sorted([price_lower, price_upper])

        # 4. Current token amounts in the position
        sqrt_price_a = tick_to_sqrt_price_x96(tick_lower)
        sqrt_price_b = tick_to_sqrt_price_x96(tick_upper)
        amount0_raw, amount1_raw = get_amounts_for_liquidity(
            sqrt_price_x96, sqrt_price_a, sqrt_price_b, liquidity
        )
        current_amount0 = amount0_raw / (10 ** self.token0_decimals)
        current_amount1 = amount1_raw / (10 ** self.token1_decimals)

        return {
            "chain": self.chain,
            "position_id": self.position_id,
            "pair": f"{self.token0_symbol}/{self.token1_symbol}",
            "token0_symbol": self.token0_symbol,
            "token1_symbol": self.token1_symbol,
            "token0_address": self.token0,
            "token1_address": self.token1,
            "current_tick": current_tick,
            "current_price": current_price,
            "sqrt_price_x96": sqrt_price_x96,
            "tick_lower": tick_lower,
            "tick_upper": tick_upper,
            "price_lower": bounds[0],
            "price_upper": bounds[1],
            "liquidity": liquidity,
            "earned_fees": {
                self.token0_symbol: earned_0,
                self.token1_symbol: earned_1
            },
            "initial_deposit": {
                self.token0_symbol: self.initial_deposit_token0,
                self.token1_symbol: self.initial_deposit_token1
            },
            "current_amounts": {
                self.token0_symbol: current_amount0,
                self.token1_symbol: current_amount1
            },
            "position_open_timestamp": self.position_open_timestamp,
        }
