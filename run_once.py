"""One-shot mode for GitHub Actions: handle queued commands, run due checks, exit."""
import asyncio
import logging

import bot

log = logging.getLogger("jobbot.once")


async def run(app=None):
    app = app or bot.build_app()
    await app.initialize()
    try:
        me = await app.bot.get_me()
        await bot.post_init(app)
        offset = int(bot.store.get_meta("offset", "0"))
        updates = await app.bot.get_updates(
            offset=offset or None, timeout=0, allowed_updates=["message", "callback_query"]
        )
        log.info("bot=@%s offset=%s pending_updates=%d chats=%d",
                 me.username, offset, len(updates), len(bot.store.all_chats()))
        for u in updates:
            try:
                await app.process_update(u)
            except Exception:
                log.exception("update %s failed", u.update_id)
            bot.store.set_meta("offset", u.update_id + 1)
        await bot.run_due(app)
    finally:
        await app.shutdown()


if __name__ == "__main__":
    if not bot.TOKEN:
        raise SystemExit("Няма TELEGRAM_TOKEN")
    asyncio.run(run())
