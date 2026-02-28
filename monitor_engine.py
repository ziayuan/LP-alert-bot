import asyncio
import logging
from typing import Dict, List
from blockchain_client import BlockchainClient
from telegram_bot import TelegramController
from config import Config, PositionConfig

logger = logging.getLogger(__name__)


class MonitorEngine:
    """
    Monitors multiple positions across multiple chains.
    Each position has its own state machine to prevent alert spam.
    Supports dynamic add/remove/update of clients at runtime.
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

        # List of initialized clients that are actively being monitored
        self._active_clients: List[BlockchainClient] = []

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

        self._active_clients = [c for c in self.clients if c.is_initialized]
        if not self._active_clients:
            await self.tg_controller.send_alert("🔴 *No positions initialized. Bot cannot start.*")
            return

        summary = "\n".join(
            f"• [{c.chain}] #{c.position_id} ({c.token0_symbol}/{c.token1_symbol})"
            for c in self._active_clients
        )
        await self.tg_controller.send_alert(
            f"🟢 *Monitor Started*\n\n"
            f"Tracking {len(self._active_clients)} position(s):\n{summary}\n"
            f"Interval: `{Config.CHECK_INTERVAL_SECONDS}s`"
        )

        while self.is_running:
            for client in list(self._active_clients):  # copy to avoid mutation during iteration
                await self._check_position(client)
            await asyncio.sleep(Config.CHECK_INTERVAL_SECONDS)

    async def stop(self):
        self.is_running = False
        logger.info("Stopping Monitor Engine...")

    # ── Dynamic client management ─────────────────────────────────

    def add_client(self, client: BlockchainClient) -> str:
        """
        Add a new client to the monitor at runtime.
        Initializes the position and adds it to the active list.
        Returns a status message.
        """
        try:
            client.initialize_position()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize position: {e}")

        self.clients.append(client)
        self._active_clients.append(client)
        self.states[f"{client.chain}:{client.position_id}"] = 0
        return (f"[{client.chain}] #{client.position_id} "
                f"({client.token0_symbol}/{client.token1_symbol}) added to monitoring.")

    def remove_client(self, position_id: int) -> str:
        """Remove a client from monitoring by position ID."""
        target = None
        for c in self.clients:
            if c.position_id == position_id:
                target = c
                break

        if not target:
            raise ValueError(f"Position #{position_id} not found in active monitors.")

        key = f"{target.chain}:{target.position_id}"
        self.clients.remove(target)
        if target in self._active_clients:
            self._active_clients.remove(target)
        self.states.pop(key, None)

        return f"[{target.chain}] #{position_id} removed from monitoring."

    def update_client(self, old_id: int) -> str:
        """
        Re-initialize an existing client after its config has been updated.
        The Config.update_position() should have been called before this.
        """
        target = None
        for c in self.clients:
            if c.config.position_id != c.position_id:
                # Config was updated but client hasn't re-initialized yet
                target = c
                break
            if c.position_id == old_id:
                target = c
                break

        if not target:
            raise ValueError(f"Position #{old_id} not found in active monitors.")

        old_key = f"{target.chain}:{old_id}"
        self.states.pop(old_key, None)

        try:
            target.reinitialize()
        except Exception as e:
            raise RuntimeError(f"Failed to reinitialize position: {e}")

        new_key = f"{target.chain}:{target.position_id}"
        self.states[new_key] = 0

        return (f"[{target.chain}] #{target.position_id} "
                f"({target.token0_symbol}/{target.token1_symbol}) updated and re-initialized.")

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
