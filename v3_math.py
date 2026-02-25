import math
from typing import Tuple

# The base for calculating tick prices
Q96 = 2**96
Q128 = 2**128
MAX_UINT256 = 2**256 - 1

def tick_to_price(tick: int, token0_decimals: int, token1_decimals: int) -> float:
    """
    Converts a PancakeSwap V3 tick into a human-readable price.
    Returns the price of token0 in terms of token1.
    """
    sqrt_price_x96 = math.sqrt(1.0001 ** tick) * Q96
    return sqrt_price_x96_to_price(sqrt_price_x96, token0_decimals, token1_decimals)

def sqrt_price_x96_to_price(sqrt_price_x96: float, token0_decimals: int, token1_decimals: int) -> float:
    """
    Converts internal sqrtPriceX96 to float price.
    """
    price = (sqrt_price_x96 / Q96) ** 2
    # Adjust for decimals
    return price / (10 ** (token1_decimals - token0_decimals))

def get_price_range_from_ticks(tick_lower: int, tick_upper: int, token0_decimals: int, token1_decimals: int) -> Tuple[float, float]:
    """
    Converts tick boundary to price boundary.
    Note: if token0 is not the base currency you expect, the price needs to be inverted (1/price).
    """
    price_lower = tick_to_price(tick_lower, token0_decimals, token1_decimals)
    price_upper = tick_to_price(tick_upper, token0_decimals, token1_decimals)
    
    # Ensure lower is indeed lower
    if price_lower > price_upper:
        price_lower, price_upper = price_upper, price_lower
        
    return price_lower, price_upper

def calculate_impermanent_loss(initial_value_usd: float, current_value_usd: float) -> float:
    """
    Calculates the impermanent loss percentage.
    This is a simplified abstraction. In real usage, you compare the HODL value vs Current LP value.
    IL = (Current LP Value - HODL Value) / HODL Value
    """
    if initial_value_usd == 0:
        return 0.0
    # Note: actual IL requires checking the value if held vs value if LP'd.
    # This function placeholder is to be replaced by precise token-amount calculations
    pass

def get_fee_growth_inside(
    tick_lower: int,
    tick_upper: int,
    tick_current: int,
    fee_growth_global_0: int,
    fee_growth_global_1: int,
    lower_outside_0: int,
    lower_outside_1: int,
    upper_outside_0: int,
    upper_outside_1: int
) -> Tuple[int, int]:
    # Calculate fee growth below
    if tick_current >= tick_lower:
        fee_growth_below_0 = lower_outside_0
        fee_growth_below_1 = lower_outside_1
    else:
        fee_growth_below_0 = (fee_growth_global_0 - lower_outside_0) % (MAX_UINT256 + 1)
        fee_growth_below_1 = (fee_growth_global_1 - lower_outside_1) % (MAX_UINT256 + 1)

    # Calculate fee growth above
    if tick_current < tick_upper:
        fee_growth_above_0 = upper_outside_0
        fee_growth_above_1 = upper_outside_1
    else:
        fee_growth_above_0 = (fee_growth_global_0 - upper_outside_0) % (MAX_UINT256 + 1)
        fee_growth_above_1 = (fee_growth_global_1 - upper_outside_1) % (MAX_UINT256 + 1)

    fee_growth_inside_0 = (fee_growth_global_0 - fee_growth_below_0 - fee_growth_above_0) % (MAX_UINT256 + 1)
    fee_growth_inside_1 = (fee_growth_global_1 - fee_growth_below_1 - fee_growth_above_1) % (MAX_UINT256 + 1)

    return fee_growth_inside_0, fee_growth_inside_1

def calculate_pending_fees(
    liquidity: int,
    fee_growth_inside_0: int,
    fee_growth_inside_1: int,
    fee_growth_inside_last_0: int,
    fee_growth_inside_last_1: int
) -> Tuple[int, int]:
    
    uncollected_fees_0 = (liquidity * ((fee_growth_inside_0 - fee_growth_inside_last_0) % (MAX_UINT256 + 1))) // Q128
    uncollected_fees_1 = (liquidity * ((fee_growth_inside_1 - fee_growth_inside_last_1) % (MAX_UINT256 + 1))) // Q128

    return uncollected_fees_0, uncollected_fees_1

def get_amounts_for_liquidity(
    sqrt_price_x96: int,
    sqrt_price_a_x96: int,
    sqrt_price_b_x96: int,
    liquidity: int
) -> Tuple[int, int]:
    """
    Calculates token0 and token1 amounts for a given liquidity and price range.
    """
    if sqrt_price_a_x96 > sqrt_price_b_x96:
        sqrt_price_a_x96, sqrt_price_b_x96 = sqrt_price_b_x96, sqrt_price_a_x96

    amount0 = 0
    amount1 = 0

    if sqrt_price_x96 <= sqrt_price_a_x96:
        amount0 = get_amount0_for_liquidity(sqrt_price_a_x96, sqrt_price_b_x96, liquidity)
    elif sqrt_price_x96 < sqrt_price_b_x96:
        amount0 = get_amount0_for_liquidity(sqrt_price_x96, sqrt_price_b_x96, liquidity)
        amount1 = get_amount1_for_liquidity(sqrt_price_a_x96, sqrt_price_x96, liquidity)
    else:
        amount1 = get_amount1_for_liquidity(sqrt_price_a_x96, sqrt_price_b_x96, liquidity)

    return amount0, amount1


def get_amount0_for_liquidity(sqrt_ratio_a_x96: int, sqrt_ratio_b_x96: int, liquidity: int) -> int:
    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96
    
    return int((liquidity << 96) * (sqrt_ratio_b_x96 - sqrt_ratio_a_x96) / sqrt_ratio_b_x96 / sqrt_ratio_a_x96)

def get_amount1_for_liquidity(sqrt_ratio_a_x96: int, sqrt_ratio_b_x96: int, liquidity: int) -> int:
    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96
        
    return int(liquidity * (sqrt_ratio_b_x96 - sqrt_ratio_a_x96) / Q96)

