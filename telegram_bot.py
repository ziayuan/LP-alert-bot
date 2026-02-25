import logging
from typing import List
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from blockchain_client import BlockchainClient

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, clients: List[BlockchainClient]):
        self.clients = clients
        self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("help", self.cmd_help))

    async def _check_auth(self, update: Update) -> bool:
        user_id = update.effective_user.id
        if Config.ALLOWED_USER_IDS and user_id not in Config.ALLOWED_USER_IDS:
            await update.message.reply_text("Unauthorized user.")
            logger.warning(f"Unauthorized access attempt by user: {user_id}")
            return False
        return True

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        positions_list = "\n".join(
            f"• [{c.chain}] #{c.position_id}" for c in self.clients
        )
        welcome_msg = (
            "🚀 *V3 LP Monitor Bot*\n\n"
            f"Monitoring {len(self.clients)} position(s):\n{positions_list}\n\n"
            "Use /status to get real-time data for all positions."
        )
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        help_text = (
            "🤖 *Available Commands:*\n"
            "/status — View all positions (price, range, fees, initial deposit)\n"
            "/start — Re-display welcome message"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        await update.message.reply_text(f"⏳ Fetching live data for {len(self.clients)} position(s)...")

        for client in self.clients:
            try:
                state = client.get_current_state()
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

        in_range = p_low <= p_cur <= p_up
        status_emoji = "✅ IN RANGE" if in_range else "❌ OUT OF BOUNDS"

        dist_lower = (p_cur - p_low) / p_cur * 100 if p_cur > p_low else 0
        dist_upper = (p_up - p_cur) / p_cur * 100 if p_up > p_cur else 0

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

        msg += "*💰 Earned Fees*\n"
        for token, amount in state["earned_fees"].items():
            msg += f"• {amount:.8f} {token}\n"

        msg += "\n*📥 Initial Deposit*\n"
        for token, amount in state["initial_deposit"].items():
            msg += f"• {amount:.6f} {token}\n"

        return msg

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
