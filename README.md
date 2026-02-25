# V3 多链 LP 仓位监控助手 🥞

这是一个基于 Python 和 Telegram Bot 的多链 Uniswap V3（及 PancakeSwap V3）流动性仓位监控工具。它能同时监控多个区块链（如 BSC, HyperEVM, Base, Arbitrum 等）上的仓位状态。

主要功能包括精确计算实时未提取手续费、监控价格区间并在超出范围时自动预警、以及通过交易哈希追踪初始入金金额。

## 主要特性
- **多链多仓位支持**：可以在一个 `.env` 配置文件中通过 JSON 数组同时追踪多个不同 EVM 链上的流动性仓位。
- **实时价格区间监控**：当价格接近或超出你设置的 `tickLower` 和 `tickUpper` 范围时，立即发送 Telegram 警报。
- **智能防抖逻辑**：每个仓位拥有独立的状态机，防止价格在边界附近震荡时产生海量重复警报。
- **实时收益统计**：利用 `feeGrowthGlobal` 数学模型，实时精确计算你当前赚取但未提取的 Pending Fees。
- **初始入金追踪**：只需提供建仓时的交易哈希（Transaction Hash），Bot 会自动解析当时投入的原始代币数量。

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
将 `.env.example` 重命名为 `.env` 并填写相关信息。重点是配置 `POSITIONS` JSON 数组，每个对象代表一个要监控的仓位。

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

- `/status` - **核心指令**。立即获取所有已配置仓位的实时状态，包括：
  - 当前价格与该仓位设定的价格上下限。
  - 距离上下限的百分比距离（如果在区间内）。
  - 精确计算的所有未提取手续费 (Pending Fees)。
  - 初始建仓时的代币数量。
- `/start` - 显示欢迎信息并列出当前正在监控的所有仓位 ID。
- `/help` - 显示指令帮助列表。

## 日志记录
程序会自动将日志保存在根目录下的 `bot.log` 中。日志采用滚动备份机制（单个文件最大 5MB，保留最新 3 个备份）。
