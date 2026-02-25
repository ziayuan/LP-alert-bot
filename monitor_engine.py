import asyncio
import logging
from typing import Dict, List
from blockchain_client import BlockchainClient
from telegram_bot import TelegramController
from config import Config

logger = logging.getLogger(__name__)


class MonitorEngine:
    """
    Monitors multiple positions across multiple chains.
    Each position has its own state machine to prevent alert spam.
    """

    def __init__(self, clients: List[BlockchainClient], tg_controller: TelegramController):
        self.clients = clients
        self.tg_controller = tg_controller
        self.is_running = False

        # Independent state machine per position: key = "chain:position_id"
        # 0=Init, 1=InRange, 2=WarnLower, 3=WarnUpper, 4=OutLower, 5=OutUpper
        self.states: Dict[str, int] = {}
        for c in clients:
            self.states[f"{c.chain}:{c.position_id}"] = 0

    async def start(self):
        self.is_running = True
        logger.info("Starting Monitor Engine Loop...")

        # Initialize all blockchain clients
        failed = []
        for client in self.clients:
            try:
                client.initialize_position()
            except Exception as e:
                logger.error(f"[{client.chain}] Failed to init Position #{client.position_id}: {e}")
                failed.append(f"[{client.chain}] #{client.position_id}: {e}")

        if failed:
            await self.tg_controller.send_alert(
                "🔴 *Some positions failed to initialize:*\n" + "\n".join(failed)
            )

        ready = [c for c in self.clients if c.is_initialized]
        if not ready:
            await self.tg_controller.send_alert("🔴 *No positions initialized. Bot cannot start.*")
            return

        summary = "\n".join(
            f"• [{c.chain}] #{c.position_id} ({c.token0_symbol}/{c.token1_symbol})"
            for c in ready
        )
        await self.tg_controller.send_alert(
            f"🟢 *Monitor Started*\n\n"
            f"Tracking {len(ready)} position(s):\n{summary}\n"
            f"Interval: `{Config.CHECK_INTERVAL_SECONDS}s`"
        )

        while self.is_running:
            for client in ready:
                await self._check_position(client)
            await asyncio.sleep(Config.CHECK_INTERVAL_SECONDS)

    async def stop(self):
        self.is_running = False
        logger.info("Stopping Monitor Engine...")

    async def _check_position(self, client: BlockchainClient):
        key = f"{client.chain}:{client.position_id}"
        try:
            state = await asyncio.to_thread(client.get_current_state)

            p_cur = state["current_price"]
            p_low = state["price_lower"]
            p_up = state["price_upper"]
            pair = state["pair"]
            threshold = Config.WARNING_THRESHOLD_PERCENT

            dist_lower_pct = (p_cur - p_low) / p_cur if p_cur > p_low else 0
            dist_upper_pct = (p_up - p_cur) / p_cur if p_up > p_cur else 0

            new_state = 1
            if p_cur < p_low:
                new_state = 4
            elif p_cur > p_up:
                new_state = 5
            elif dist_lower_pct <= threshold:
                new_state = 2
            elif dist_upper_pct <= threshold:
                new_state = 3

            old_state = self.states[key]
            if new_state != old_state:
                logger.info(f"[{key}] State transition: {old_state} -> {new_state}")
                prefix = f"*[{client.chain}] {pair} #{client.position_id}*\n"
                alert_msg = None

                if new_state == 4:
                    alert_msg = (
                        f"🚨 {prefix}OUT OF BOUNDS (LOWER) 🚨\n\n"
                        f"Current: `{p_cur:.6f}` | Lower: `{p_low:.6f}`\n"
                        "Earning 0 fees."
                    )
                elif new_state == 5:
                    alert_msg = (
                        f"🚨 {prefix}OUT OF BOUNDS (UPPER) 🚨\n\n"
                        f"Current: `{p_cur:.6f}` | Upper: `{p_up:.6f}`\n"
                        "Earning 0 fees."
                    )
                elif new_state == 2 and old_state in [0, 1, 3]:
                    alert_msg = (
                        f"⚠️ {prefix}APPROACHING LOWER BOUND\n\n"
                        f"Current: `{p_cur:.6f}` | Lower: `{p_low:.6f}`\n"
                        f"Distance: `{(dist_lower_pct * 100):.2f}%`"
                    )
                elif new_state == 3 and old_state in [0, 1, 2]:
                    alert_msg = (
                        f"⚠️ {prefix}APPROACHING UPPER BOUND\n\n"
                        f"Current: `{p_cur:.6f}` | Upper: `{p_up:.6f}`\n"
                        f"Distance: `{(dist_upper_pct * 100):.2f}%`"
                    )
                elif new_state == 1 and old_state in [4, 5]:
                    alert_msg = (
                        f"✅ {prefix}RECOVERED (IN RANGE)\n\n"
                        f"Current: `{p_cur:.6f}`\n"
                        f"Range: `{p_low:.6f}` - `{p_up:.6f}`\n"
                        "Earning fees again."
                    )

                if alert_msg:
                    await self.tg_controller.send_alert(alert_msg)

                self.states[key] = new_state

        except Exception as e:
            logger.error(f"[{key}] Error checking position: {e}")
