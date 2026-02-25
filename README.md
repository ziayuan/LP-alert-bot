# V3 Multi-Chain LP Position Monitor 🥞

A robust Python + Telegram Bot for monitoring your Uniswap V3 compatible Liquidity Positions across multiple chains (like BSC, HyperEVM, Base, Arbitrum). 
Specifically designed to accurately calculate Uncollected Fees, monitor Price Boundaries, and track your Initial Deposits via Transaction Hashes.

## Features
- **Multi-Chain & Multi-Position**: Track an unlimited number of LP positions across different EVM chains simultaneously.
- **Real-Time Boundary Monitoring**: Get Telegram alerts instantly if the pool price exits your `tickLower` and `tickUpper` ranges.
- **Smart Debouncing**: Independent state machine logic for each position prevents alert spamming when prices hover around boundaries.
- **Accurate Pending Fees**: Mathematically calculates real-time uncollected fees using `feeGrowthGlobal` and `feeGrowthInside` from the pool state.
- **Initial Deposit Tracking**: Provide the original `Transaction Hash` where you added liquidity, and the bot parses exact Token0 / Token1 deposited amounts.
- **/status Command**: Instantly check current price, distance to both bounds, and uncollected fees for all configured positions in the Telegram chat.

## Setup Instructions

1. **Install Requirements**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Configuration**
Rename `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN`: From your @BotFather.
- `ALLOWED_USER_IDS`: Your Telegram User ID.
- `POSITIONS`: A JSON array where you configure each position's chain, RPC URL, Manager contract, Factory contract, Position ID, and Initial TX Hash.

*See `.env.example` for the exact JSON format.*

3. **Running the Bot**
```bash
# Foreground / Testing
python3 main.py

# Background
./run.sh

# Stop Background Bot
./stop.sh
```

## Logs
The bot uses rotating file logs (5MB max per file, up to 3 backups) saved to `bot.log` in the project root.
