# V3 多链 LP 仓位监控助手 🥞

这是一个基于 Python 和 Telegram Bot 的多链 Uniswap V3（及 PancakeSwap V3）流动性仓位监控工具。它能同时监控多个区块链（如 BSC, HyperEVM, Base, Arbitrum 等）上的仓位状态。

主要功能包括精确计算实时未提取手续费、监控价格区间并在超出范围时自动预警、以及通过交易哈希追踪初始入金金额。

## 主要特性
- **多链多仓位支持**：可以在一个 `.env` 配置文件中通过 JSON 数组同时追踪多个不同 EVM 链上的流动性仓位。
- **实时价格区间监控**：当价格接近或超出你设置的 `tickLower` 和 `tickUpper` 范围时，立即发送 Telegram 警报。
- **智能防抖逻辑**：每个仓位拥有独立的状态机，防止价格在边界附近震荡时产生海量重复警报。
- **实时收益统计**：利用 `feeGrowthGlobal` 数学模型，实时精确计算你当前赚取但未提取的 Pending Fees（而非仅显示合约中的 `tokensOwed` 静态数值）。
- **初始入金追踪**：只需提供建仓时的交易哈希（Transaction Hash），Bot 会自动解析当时投入的原始代币数量。
- **/status 指令**：一键查询所有仓位的实时价格、距离边界波动百分比、累计手续费收益等。

## 环境搭建

1. **安装依赖**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **配置参数**
将 `.env.example` 重命名为 `.env` 并填写以下信息：
- `TELEGRAM_BOT_TOKEN`: 从 @BotFather 获取的 Bot Token。
- `ALLOWED_USER_IDS`: 你的 Telegram 用户 ID。
- `POSITIONS`: 一个 JSON 数组，包含每个仓位的链名称、RPC、Manager 地址、Factory 地址、Position ID 以及初始交易哈希。

*具体 JSON 格式请参考 `.env.example`。*

3. **运行程序**
```bash
# 前台运行（测试用）
python3 main.py

# 后台运行
./run.sh

# 停止后台程序
./stop.sh
```

## 日志记录
程序会自动将日志保存在根目录下的 `bot.log` 中。日志采用滚动备份机制（单个文件最大 5MB，保留最新 3 个备份），不会因文件过大占用磁盘空间。
