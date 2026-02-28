import asyncio
import logging
import logging.handlers
import signal
import sys
from blockchain_client import BlockchainClient
from telegram_bot import TelegramController
from monitor_engine import MonitorEngine
from config import Config

# Configure logging with rotation (5MB max, 3 backups)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "bot.log", maxBytes=5*1024*1024, backupCount=3
        )
    ]
)
logger = logging.getLogger(__name__)

# Suppress noisy repeated conflict logs from the telegram library
logging.getLogger("telegram.ext.Updater").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main():
    logger.info("Initializing components...")

    # 1. Create a BlockchainClient for each configured position
    clients = []
    for pos_cfg in Config.POSITIONS:
        try:
            client = BlockchainClient(pos_cfg)
            clients.append(client)
            logger.info(f"[{pos_cfg.chain}] Client created for Position #{pos_cfg.position_id}")
        except Exception as e:
            logger.error(f"[{pos_cfg.chain}] Failed to create client for #{pos_cfg.position_id}: {e}")

    if not clients:
        logger.critical("No blockchain clients could be created. Exiting.")
        return

    # 2. Initialize Telegram Controller with all clients
    tg_controller = TelegramController(clients)

    # 3. Initialize Monitor Engine with all clients
    monitor = MonitorEngine(clients, tg_controller)

    # 4. Wire monitor engine reference back to TG controller (deferred to avoid circular init)
    tg_controller.set_monitor_engine(monitor)

    # Start Telegram Bot polling
    # drop_pending_updates=True: clears any stale server-side getUpdates connections
    # from previous instances that didn't shut down cleanly, preventing 409 Conflict errors.
    app = tg_controller.application
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Graceful shutdown with guard against double-invocation
    shutting_down = False

    async def shutdown(sig):
        nonlocal shutting_down
        if shutting_down:
            return  # Prevent duplicate shutdown from rapid Ctrl+C
        shutting_down = True
        logger.info(f"Received exit signal {sig.name}, shutting down...")
        await monitor.stop()
        try:
            await app.updater.stop()
        except RuntimeError:
            pass  # Already stopped
        await app.stop()
        await app.shutdown()
        logger.info("Shutdown complete.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    # Start the Monitor loop (runs until shutdown signal)
    try:
        await monitor.start()
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except SystemExit:
        pass
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
