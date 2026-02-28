import asyncio
import logging
from typing import List, TYPE_CHECKING
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from blockchain_client import BlockchainClient
from price_service import price_service

if TYPE_CHECKING:
    from monitor_engine import MonitorEngine

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, clients: List[BlockchainClient], monitor_engine: "MonitorEngine" = None):
        self.clients = clients
        self.monitor_engine = monitor_engine
        self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        self._setup_handlers()

    def set_monitor_engine(self, engine: "MonitorEngine"):
        """Set the monitor engine reference (for deferred initialization)."""
        self.monitor_engine = engine

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("add", self.cmd_add))
        self.application.add_handler(CommandHandler("update", self.cmd_update))
        self.application.add_handler(CommandHandler("remove", self.cmd_remove))

    async def _check_auth(self, update: Update) -> bool:
        user_id = update.effective_user.id
        if Config.ALLOWED_USER_IDS and user_id not in Config.ALLOWED_USER_IDS:
            await update.message.reply_text("Unauthorized user.")
            logger.warning(f"Unauthorized access attempt by user: {user_id}")
            return False
        return True

    # ── /start ────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        positions_list = "\n".join(
            f"• [{c.chain}] #{c.position_id}" for c in self.clients
        )
        welcome_msg = (
            "🚀 *V3 LP Monitor Bot*\n\n"
            f"Monitoring {len(self.clients)} position(s):\n{positions_list}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📖 *Available Commands:*\n\n"
            "🔍 `/status`\n"
            "  View all positions (price, range, fees, USD values, IL)\n\n"
            "➕ `/add <chain> <position_id> <tx_hash>`\n"
            "  Add a new position\n"
            "  chain: `BSC` or `HyperEVM`\n"
            "  Example: `/add HyperEVM 12345 0xabc...`\n\n"
            "🔄 `/update <old_id> <new_id> <new_tx_hash>`\n"
            "  Update a position's ID and TX hash\n"
            "  Example: `/update 12345 67890 0xdef...`\n\n"
            "🗑 `/remove <position_id>`\n"
            "  Remove a position from monitoring\n"
            "  Example: `/remove 12345`\n\n"
            "❓ `/help` — Show this command reference"
        )
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')

    # ── /help ─────────────────────────────────────────────────────

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        # Same content as /start command reference section
        help_text = (
            "🤖 *Command Reference:*\n\n"
            "🔍 `/status` — View all positions with USD values\n"
            "➕ `/add <chain> <position_id> <tx_hash>` — Add position\n"
            "🔄 `/update <old_id> <new_id> <new_tx_hash>` — Update position\n"
            "🗑 `/remove <position_id>` — Remove position\n"
            "🚀 `/start` — Show full command guide"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    # ── /status ───────────────────────────────────────────────────

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        await update.message.reply_text(f"⏳ Fetching live data for {len(self.clients)} position(s)...")

        for client in self.clients:
            try:
                state = await asyncio.to_thread(client.get_current_state)
                msg = self._format_status(state)
                await update.message.reply_text(msg, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"[{client.chain}] Error in /status for #{client.position_id}: {e}", exc_info=True)
                await update.message.reply_text(
                    f"⚠️ [{client.chain}] Position #{client.position_id}: Error fetching data."
                )

    @staticmethod
    def _format_status(state: dict) -> str:
        p_cur = state["current_price"]
        p_low = state["price_lower"]
        p_up = state["price_upper"]
        t0 = state["token0_symbol"]
        t1 = state["token1_symbol"]

        in_range = p_low <= p_cur <= p_up
        status_emoji = "✅ IN RANGE" if in_range else "❌ OUT OF BOUNDS"

        dist_lower = (p_cur - p_low) / p_cur * 100 if p_cur > p_low else 0
        dist_upper = (p_up - p_cur) / p_cur * 100 if p_up > p_cur else 0

        # Fetch USD prices for both tokens (contract address lookup, symbol fallback)
        prices = price_service.get_token_prices(
            chain=state["chain"],
            tokens=[
                {"symbol": t0, "address": state["token0_address"]},
                {"symbol": t1, "address": state["token1_address"]},
            ],
        )

        def usd_str(amount: float, price_usd: float | None) -> str:
            """Format a USD value string, or '?' if price unavailable."""
            if price_usd is None:
                return ""
            return f" (~${amount * price_usd:,.2f})"

        msg = (
            f"📊 *[{state['chain']}] {state['pair']} #{state['position_id']}*\n"
            f"Status: {status_emoji}\n\n"
            f"💰 *Price*\n"
            f"Current: `{p_cur:.6f}`\n"
            f"Lower: `{p_low:.6f}`\n"
            f"Upper: `{p_up:.6f}`\n\n"
        )

        if in_range:
            msg += f"⬇️ Dist Lower: `{dist_lower:.2f}%`\n"
            msg += f"⬆️ Dist Upper: `{dist_upper:.2f}%`\n\n"

        # Earned Fees with USD
        msg += "*💰 Earned Fees*\n"
        total_fees_usd = 0.0
        fees_usd_available = True
        for token, amount in state["earned_fees"].items():
            token_price = prices.get(token.upper())
            msg += f"• {amount:.8f} {token}{usd_str(amount, token_price)}\n"
            if token_price is not None:
                total_fees_usd += amount * token_price
            else:
                fees_usd_available = False
        if fees_usd_available:
            msg += f"💵 Total Fees: ~${total_fees_usd:,.2f}\n"

        # Initial Deposit with USD
        msg += "\n*📥 Initial Deposit*\n"
        total_deposit_usd = 0.0
        deposit_usd_available = True
        for token, amount in state["initial_deposit"].items():
            token_price = prices.get(token.upper())
            msg += f"• {amount:.6f} {token}{usd_str(amount, token_price)}\n"
            if token_price is not None:
                total_deposit_usd += amount * token_price
            else:
                deposit_usd_available = False
        if deposit_usd_available:
            msg += f"💵 Total: ~${total_deposit_usd:,.2f}\n"

        # Current Position with USD
        msg += "\n*📦 Current Position*\n"
        total_position_usd = 0.0
        position_usd_available = True
        for token, amount in state["current_amounts"].items():
            token_price = prices.get(token.upper())
            msg += f"• {amount:.6f} {token}{usd_str(amount, token_price)}\n"
            if token_price is not None:
                total_position_usd += amount * token_price
            else:
                position_usd_available = False
        if position_usd_available:
            msg += f"💵 Total: ~${total_position_usd:,.2f}\n"

        # Impermanent Loss
        if deposit_usd_available and position_usd_available and total_deposit_usd > 0:
            il_usd = total_position_usd - total_deposit_usd
            il_pct = (il_usd / total_deposit_usd) * 100
            il_sign = "+" if il_usd >= 0 else ""
            il_emoji = "📈" if il_usd >= 0 else "📉"
            msg += f"\n{il_emoji} *IL (vs. holding):* {il_sign}${il_usd:,.2f} ({il_sign}{il_pct:.2f}%)\n"

        return msg

    # ── /add ──────────────────────────────────────────────────────

    async def cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        args = context.args
        if not args or len(args) < 3:
            await update.message.reply_text(
                "❌ Usage: `/add <chain> <position_id> <tx_hash>`\n"
                "Example: `/add HyperEVM 12345 0xabc...`\n\n"
                "Supported chains: `BSC`, `HyperEVM`",
                parse_mode='Markdown'
            )
            return

        chain = args[0]
        try:
            position_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ position\\_id must be a number.")
            return
        tx_hash = args[2]

        await update.message.reply_text(f"⏳ Adding [{chain}] Position #{position_id}...")

        try:
            # 1. Add to config (validates chain, saves to .env)
            pos_config = Config.add_position(chain, position_id, tx_hash)

            # 2. Create client and add to monitor
            client = BlockchainClient(pos_config)
            result = self.monitor_engine.add_client(client)

            # 3. Also add to our local clients list
            self.clients.append(client)

            await update.message.reply_text(f"✅ {result}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in /add: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Failed: {e}")

    # ── /update ───────────────────────────────────────────────────

    async def cmd_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        args = context.args
        if not args or len(args) < 3:
            await update.message.reply_text(
                "❌ Usage: `/update <old_position_id> <new_position_id> <new_tx_hash>`\n"
                "Example: `/update 12345 67890 0xdef...`",
                parse_mode='Markdown'
            )
            return

        try:
            old_id = int(args[0])
            new_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ position\\_id must be a number.")
            return
        new_tx_hash = args[2]

        await update.message.reply_text(f"⏳ Updating Position #{old_id} → #{new_id}...")

        try:
            # 1. Update config (saves to .env)
            Config.update_position(old_id, new_id, new_tx_hash)

            # 2. Re-initialize the client in monitor engine
            result = self.monitor_engine.update_client(old_id)

            await update.message.reply_text(f"✅ {result}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in /update: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Failed: {e}")

    # ── /remove ───────────────────────────────────────────────────

    async def cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        args = context.args
        if not args or len(args) < 1:
            await update.message.reply_text(
                "❌ Usage: `/remove <position_id>`\n"
                "Example: `/remove 12345`",
                parse_mode='Markdown'
            )
            return

        try:
            position_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ position\\_id must be a number.")
            return

        try:
            # 1. Remove from monitor engine
            result = self.monitor_engine.remove_client(position_id)

            # 2. Remove from our local clients list
            self.clients = [c for c in self.clients if c.position_id != position_id]

            # 3. Remove from config (saves to .env)
            Config.remove_position(position_id)

            await update.message.reply_text(f"✅ {result}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in /remove: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Failed: {e}")

    # ── Alert sending ─────────────────────────────────────────────

    async def send_alert(self, message: str):
        """Send an alert message to all allowed user IDs."""
        for user_id in Config.ALLOWED_USER_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send alert to {user_id}: {e}")
