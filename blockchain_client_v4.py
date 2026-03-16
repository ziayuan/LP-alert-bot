import math
import logging
import json
import os
import eth_abi
from web3 import Web3
from web3.exceptions import ContractLogicError

from config import PositionConfig
from v3_math import tick_to_price, get_amounts_for_liquidity, Q96
from abis.constants import ERC20_ABI
from blockchain_client import BlockchainClient, tick_to_sqrt_price_x96

logger = logging.getLogger(__name__)

def load_abi(filename):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "abis", filename)
    with open(path) as f:
        return json.load(f)

V4_POSITION_MANAGER_ABI = load_abi("uniswap_v4_position_manager.json")
V4_POOL_MANAGER_ABI = load_abi("uniswap_v4_pool_manager.json")
V4_STATEVIEW_ABI = load_abi("uniswap_v4_stateview.json")

# StateView address on Base
STATEVIEW_ADDRESS = "0xa3C0c9b65baD0b08107AA264b0f3Db444b867A71"

class BlockchainClientV4(BlockchainClient):
    """
    A blockchain client instance for a single Uniswap V4 LP position.
    Overrides V3 specifics to interact with the PoolManager singleton and StateView.
    """

    def __init__(self, pos_config: PositionConfig):
        # Initialize base client (we skip pool init for V4 until initialize_position)
        super().__init__(pos_config)
        
        # Override manager ABI
        nft_manager_addr = Web3.to_checksum_address(pos_config.position_manager)
        self.position_manager = self.w3.eth.contract(address=nft_manager_addr, abi=V4_POSITION_MANAGER_ABI)
        
        self.pool_manager_addr = Web3.to_checksum_address(pos_config.factory) # In V4, factory config stores PoolManager
        self.pool_manager = self.w3.eth.contract(address=self.pool_manager_addr, abi=V4_POOL_MANAGER_ABI)
        
        state_view_addr = Web3.to_checksum_address(STATEVIEW_ADDRESS)
        self.state_view = self.w3.eth.contract(address=state_view_addr, abi=V4_STATEVIEW_ABI)
        
        self.pool_id = None
        self.tick_lower = None
        self.tick_upper = None

    def initialize_position(self):
        """Fetches the static info about the position and the initial deposit using V4 methods."""
        logger.info(f"[{self.chain}] Initializing V4 Position #{self.position_id}")
        
        pool_key, info = self.position_manager.functions.getPoolAndPositionInfo(self.position_id).call()
        
        self.token0 = pool_key[0]
        self.token1 = pool_key[1]
        self.fee_tier = pool_key[2]
        tick_spacing = pool_key[3]
        hooks = pool_key[4]
        
        self.pool_id = self.w3.keccak(eth_abi.encode(["address", "address", "uint24", "int24", "address"], pool_key))

        # PositionInfo in V4 is a packed uint256. 
        # Layout: feeGrowthInside0LastX128 (128 bits) | tickUpper (24 bits) | tickLower (24 bits) | liquidity (128 bits)
        # Wait, the event or getLiquidity gives us exact liquidity, but we only need tick bounds here.
        # Actually we don't need bounds here for initial deposit, we can get them dynamically.

        # Handle native currency
        if self.token0 == "0x0000000000000000000000000000000000000000":
            self.token0_symbol = "ETH"
            self.token0_decimals = 18
        else:
            t0_contract = self.w3.eth.contract(address=self.token0, abi=ERC20_ABI)
            self.token0_symbol = t0_contract.functions.symbol().call()
            self.token0_decimals = t0_contract.functions.decimals().call()

        if self.token1 == "0x0000000000000000000000000000000000000000":
            self.token1_symbol = "ETH"
            self.token1_decimals = 18
        else:
            t1_contract = self.w3.eth.contract(address=self.token1, abi=ERC20_ABI)
            self.token1_symbol = t1_contract.functions.symbol().call()
            self.token1_decimals = t1_contract.functions.decimals().call()

        logger.info(f"[{self.chain}] V4 Pool: {self.token0_symbol}/{self.token1_symbol} "
                     f"(Fee: {self.fee_tier}) at PoolManager {self.pool_manager_addr}")

        self._parse_initial_deposit_tx()
        self.is_initialized = True

    def _parse_initial_deposit_tx(self):
        tx_hash = self.config.initial_tx_hash
        if not tx_hash or len(tx_hash) < 66:
            logger.warning(f"[{self.chain}] No valid initial deposit TX Hash.")
            return

        logger.info(f"[{self.chain}] Parsing initial deposit tx: {tx_hash}")
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            block = self.w3.eth.get_block(receipt.blockNumber)
            self.position_open_timestamp = block.timestamp
            
            MODIFY_LIQ_TOPIC = self.w3.keccak(text="ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)").hex()
            
            liq_delta = 0
            for log in receipt.logs:
                if len(log.topics) > 1:
                    topic0 = log.topics[0].hex()
                    if topic0 == MODIFY_LIQ_TOPIC:
                        poolId_log = log.topics[1]
                        if poolId_log == self.pool_id:
                            data = log.data.hex().replace("0x", "")
                            if len(data) >= 256:
                                tickL = int(data[0:64], 16)
                                if tickL & (1<<255): tickL -= (1<<256)
                                self.tick_lower = tickL
                                
                                tickU = int(data[64:128], 16)
                                if tickU & (1<<255): tickU -= (1<<256)
                                self.tick_upper = tickU
                                
                                ld = int(data[128:192], 16)
                                if ld & (1<<255): ld -= (1<<256)
                                liq_delta += ld

            if liq_delta > 0:
                # Get the pool price at that block perfectly using state_view!
                sqrt_price, tick, _, _ = self.state_view.functions.getSlot0(self.pool_id).call(block_identifier=receipt.blockNumber)
                
                sqrtL = tick_to_sqrt_price_x96(self.tick_lower)
                sqrtU = tick_to_sqrt_price_x96(self.tick_upper)
                
                amt0, amt1 = get_amounts_for_liquidity(sqrt_price, sqrtL, sqrtU, liq_delta)
                
                self.initial_deposit_token0 = amt0 / (10 ** self.token0_decimals)
                self.initial_deposit_token1 = amt1 / (10 ** self.token1_decimals)
                logger.info(f"[{self.chain}] Initial Deposit: {self.initial_deposit_token0:.6f} {self.token0_symbol}, {self.initial_deposit_token1:.6f} {self.token1_symbol}")
            else:
                logger.warning(f"[{self.chain}] ModifyLiquidity event not found in tx.")

        except Exception as e:
            logger.error(f"[{self.chain}] Error parsing V4 tx {tx_hash}: {e}")

    def get_current_state(self):
        """Returns the current V4 position state, prices, and bounds using StateView."""
        if not self.is_initialized:
            self.initialize_position()

        # 1. Fetch current price/tick from StateView
        sqrt_price_x96, current_tick, _, _ = self.state_view.functions.getSlot0(self.pool_id).call()
        current_price = tick_to_price(current_tick, self.token0_decimals, self.token1_decimals)
        
        # Calculate Pending Fees
        pos_id = None
        uncollected_fees_0 = 0
        uncollected_fees_1 = 0
        try:
            # 1. Calculate salt and position id
            salt = self.position_id.to_bytes(32, 'big')
            buf = bytearray()
            # owner of the Position in PoolManager is the PositionManager NFT contract
            pm_addr = Web3.to_checksum_address(self.config.position_manager)
            buf.extend(bytes.fromhex(pm_addr[2:]))
            buf.extend(self.tick_lower.to_bytes(3, 'big', signed=True))
            buf.extend(self.tick_upper.to_bytes(3, 'big', signed=True))
            buf.extend(salt)
            pos_id = self.w3.keccak(bytes(buf))

            # 2. Get liquidity and feeGrowthLast from StateView
            liq, fgInside0Last, fgInside1Last = self.state_view.functions.getPositionInfo(self.pool_id, pos_id).call()
            
            # 3. Get current feeGrowthInside from StateView
            fgInside0, fgInside1 = self.state_view.functions.getFeeGrowthInside(self.pool_id, self.tick_lower, self.tick_upper).call()
            
            # 4. Calculate pending fees
            Q128 = 2**128
            MAX_UINT256 = 2**256 - 1
            uncollected_fees_0 = (liq * ((fgInside0 - fgInside0Last) % (MAX_UINT256 + 1))) // Q128
            uncollected_fees_1 = (liq * ((fgInside1 - fgInside1Last) % (MAX_UINT256 + 1))) // Q128
        except Exception as e:
            logger.warning(f"[{self.chain}] Failed to fetch V4 pending fees: {e}")

        earned_0 = uncollected_fees_0 / (10 ** self.token0_decimals)
        earned_1 = uncollected_fees_1 / (10 ** self.token1_decimals)

        liquidity = self.position_manager.functions.getPositionLiquidity(self.position_id).call()
        
        # For this minimal implementation, if we failed to parse tick_lower/upper from the TX, we can't fully calculate current position precisely.
        # We will assume bounds from TX for now.
        if self.tick_lower is None:
            self.tick_lower = current_tick - 10 # Fallback fake bounds
            self.tick_upper = current_tick + 10

        sqrtL = tick_to_sqrt_price_x96(self.tick_lower)
        sqrtU = tick_to_sqrt_price_x96(self.tick_upper)

        amt0, amt1 = get_amounts_for_liquidity(sqrt_price_x96, sqrtL, sqrtU, liquidity)
        bal0 = amt0 / (10 ** self.token0_decimals)
        bal1 = amt1 / (10 ** self.token1_decimals)

        price_lower = tick_to_price(self.tick_lower, self.token0_decimals, self.token1_decimals)
        price_upper = tick_to_price(self.tick_upper, self.token0_decimals, self.token1_decimals)

        bounds = sorted([price_lower, price_upper])

        current_state = {
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
            "tick_lower": self.tick_lower,
            "tick_upper": self.tick_upper,
            "price_lower": bounds[0],
            "price_upper": bounds[1],
            "liquidity": liquidity,
            "earned_fees": {
                self.token0_symbol: earned_0,
                self.token1_symbol: earned_1
            },
            "claimed_fees": {
                self.token0_symbol: self.config.claimed_fees.get(self.token0_symbol, 0.0),
                self.token1_symbol: self.config.claimed_fees.get(self.token1_symbol, 0.0)
            },
            "initial_deposit": {
                self.token0_symbol: self.initial_deposit_token0,
                self.token1_symbol: self.initial_deposit_token1
            },
            "extra_deposits": {
                self.token0_symbol: self.config.extra_deposits.get(self.token0_symbol, 0.0),
                self.token1_symbol: self.config.extra_deposits.get(self.token1_symbol, 0.0)
            },
            "current_amounts": {
                self.token0_symbol: bal0,
                self.token1_symbol: bal1
            },
            "position_open_timestamp": self.position_open_timestamp,
            "is_in_range": (self.tick_lower <= current_tick <= self.tick_upper)
        }
        return current_state

    def parse_claim_tx(self, tx_hash: str):
        # Implement later or map generically
        return {"token0": 0.0, "token1": 0.0}

    def parse_increase_liq_tx(self, tx_hash: str):
        # Implement later or map generically
        return {"token0": 0.0, "token1": 0.0}
