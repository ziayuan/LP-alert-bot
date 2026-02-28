# V3 多链 LP 仓位监控助手 🥞

这是一个基于 Python 和 Telegram Bot 的多链 Uniswap V3（及 PancakeSwap V3）流动性仓位监控工具。它能同时监控多个区块链（如 BSC, HyperEVM, Base, Arbitrum 等）上的仓位状态。

主要功能包括精确计算实时未提取手续费、监控价格区间并在超出范围时自动预警、利用交易哈希追踪初始入金，以及**实时 USD 价值估算**与**无偿损失 (IL) 监控**。

## 主要特性
- **多链多仓位支持**：支持在一个 Bot 实例中同时监控多个不同 EVM 链上的流动性仓位。
- **实时 USD 估值**：集成 CoinGecko API，自动计算 Earned Fees、Initial Deposit 和当前仓位的 USD 价值。
- **合约地址精准对齐**：优先通过代币合约地址查询价格，确保数据的准确性。
- **无偿损失 (IL) 追踪**：对比初始入金与当前价值，实时反馈 IL 情况（vs. 拿住不动的策略）。
- **动态仓位管理**：直接通过 Telegram 命令添加、移除或更新正在监控的仓位，无需重启 Bot。
- **实时区间预警**：当价格接近或超出设定的 `tickLower` 和 `tickUpper` 范围时，立即发送预警。
- **智能防抖逻辑**：每个仓位拥有独立的状态机，防止价格在边界附近震荡时产生海量重复警报。

## 快速开始

### 1. 下载仓库
```bash
git clone https://github.com/ziayuan/LP-alert-bot.git
cd LP-alert-bot
```

### 2. 安装依赖
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置参数
将 `.env.example` 重命名为 `.env` 并填写相关信息。重点是配置 `TELEGRAM_BOT_TOKEN` 和 `ALLOWED_USER_IDS`。

### 4. 运行程序
```bash
# 前台运行
python3 main.py

# 后台运行
./run.sh

# 停止后台程序
./stop.sh
```

## Telegram Bot 指令
在 Telegram 中与你的 Bot 对话，可以使用以下指令：

- `/status` - **核心指令**。获取所有仓位的实时状态、USD 估值及 IL 情况。
- `/add <chain> <id> <tx>` - 动态添加新仓位。目前支持 `BSC` 和 `HyperEVM`。
- `/update <old_id> <new_id> <new_tx>` - 更新现有仓位的 ID 或初始交易哈希。
- `/remove <id>` - 停止监控指定的仓位。
- `/start` - 显示欢迎信息、指令列表及当前监控的所有仓位。
- `/help` - 显示指令手册。

## 日志记录
程序会自动将日志保存在根目录下的 `bot.log` 中。日志采用滚动备份机制（单个文件最大 5MB，保留最新 3 个备份）。

