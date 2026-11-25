"""Telegram job-alert bot. Run: python bot.py"""
import asyncio
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import engine
from storage import Store

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jobbot")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ALLOWED = {int(x) for x in os.environ.get("ALLOWED_USERS", "").replace(" ", "").split(",") if x}
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Prague"))
store = Store(os.environ.get("DB_PATH", "jobbot.db"))
KNOWN_SOURCES = {"jobscz", "jooble"}

HELP = """<b>Каманды</b>
/keywords produkce, koordinátor festivalu, booking  – што шукаць (праз коску)
/add слова  /remove слова  – дадаць або прыбраць адно слова
/exclude senior, řidič  – выключыць вакансіі з гэтымі словамі ў назве/кампаніі
/interval 120  – як часта правяраць, у хвілінах (мін. 15)
/limit 10  – колькі вакансій максімум за адзін дайджэст
/location praha  – горад (для jobs.cz: praha, brno, ostrava...). Пуста: /location -
/sources jobscz jooble  – якія крыніцы ўключыць
/addfeed URL  /delfeed URL  – свой RSS
/watch URL  /unwatch URL  – сачыць за старонкай «kariéra»: напіша, калі з'явяцца новыя спасылкі
/quiet 22-8  – ціхія гадзіны (па Празе). /quiet off  – выключыць
/check  – праверыць цяпер
/pause  /resume  – паўза
/resetseen  – забыць, што ўжо дасылалася
/status  – бягучыя налады"""


def allowed(update: Update):
    uid = update.effective_user.id if update.effective_user else 0
    return not ALLOWED or uid in ALLOWED


def split_list(args):
    text = " ".join(args)
    return [w.strip() for w in text.replace("\n", ",").split(",") if w.strip()]


def in_quiet(quiet, now=None):
    if not quiet or quiet == "off":
        return False
    try:
        a, b = (int(x) for x in quiet.split("-"))
    except ValueError:
        return False
    h = (now or datetime.now(TZ)).hour
    return (a <= h < b) if a < b else (h >= a or h < b)


def fmt_status(s):
    on = lambda x: ", ".join(x) if x else "—"
    return (
        f"<b>Налады</b>\n"
        f"Словы: {on(s['keywords'])}\n"
        f"Выключыць: {on(s['exclude'])}\n"
        f"Інтэрвал: {s['interval_min']} хв · ліміт: {s['limit']}\n"
        f"Горад: {s['location'] or '—'}\n"
        f"Крыніцы: {on(s['sources'])}\n"
        f"RSS: {on(s['feeds'])}\n"
        f"Старонкі: {on(s['pages'])}\n"
        f"Ціхія гадзіны: {s['quiet'] or '—'}\n"
        f"Стан: {'⏸ паўза' if s['paused'] else '▶️ працуе'}"
    )


async def reply(update, text):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


def guard(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            return
        store.update(update.effective_chat.id)  # make sure the chat exists
        await fn(update, context)
    return wrapper


@guard
async def start(update, context):
    await reply(update, "Прывітанне! Я буду шукаць вакансіі і дасылаць новыя.\n"
                        "Пачні з /keywords, потым /check.\n\n" + HELP)


@guard
async def help_cmd(update, context):
    await reply(update, HELP)


@guard
async def status(update, context):
    await reply(update, fmt_status(store.get(update.effective_chat.id)))


@guard
async def keywords(update, context):
    cid = update.effective_chat.id
    words = split_list(context.args)
    if not words:
        return await reply(update, "Напішы словы праз коску: /keywords produkce, booking")
    store.update(cid, keywords=words)
    await reply(update, f"Словы: {', '.join(words)}")


@guard
async def add_kw(update, context):
    cid = update.effective_chat.id
    s = store.get(cid)
    for w in split_list(context.args):
        if w not in s["keywords"]:
            s["keywords"].append(w)
    store.save(cid, s)
    await reply(update, f"Словы: {', '.join(s['keywords'])}")


@guard
async def remove_kw(update, context):
    cid = update.effective_chat.id
    s = store.get(cid)
    drop = {w.lower() for w in split_list(context.args)}
    s["keywords"] = [w for w in s["keywords"] if w.lower() not in drop]
    store.save(cid, s)
    await reply(update, f"Словы: {', '.join(s['keywords']) or '—'}")


@guard
async def exclude(update, context):
    cid = update.effective_chat.id
    words = split_list(context.args)
    if words == ["-"]:
        words = []
    store.update(cid, exclude=words)
    await reply(update, f"Выключаю: {', '.join(words) or '—'}")


def int_cmd(name, lo, hi, field):
    @guard
    async def handler(update, context):
        try:
            v = int(context.args[0])
        except (IndexError, ValueError):
            return await reply(update, f"Напішы лік: /{name} {lo}..{hi}")
        v = max(lo, min(hi, v))
        store.update(update.effective_chat.id, **{field: v})
        await reply(update, f"{field}: {v}")
    return handler


@guard
async def location(update, context):
    v = " ".join(context.args).strip()
    store.update(update.effective_chat.id, location="" if v == "-" else v.lower())
    await reply(update, f"Горад: {v or '—'}")


@guard
async def sources_cmd(update, context):
    chosen = [a.lower() for a in context.args if a.lower() in KNOWN_SOURCES]
    if not chosen:
        return await reply(update, f"Выберы з: {', '.join(sorted(KNOWN_SOURCES))}. Прыклад: /sources jobscz jooble")
    store.update(update.effective_chat.id, sources=chosen)
    await reply(update, f"Крыніцы: {', '.join(chosen)}")


def list_cmd(field, add, check_url=True):
    @guard
    async def handler(update, context):
        cid = update.effective_chat.id
        if not context.args:
            return await reply(update, "Дай URL.")
        url = context.args[0]
        if check_url and not url.startswith(("http://", "https://")):
            return await reply(update, "URL мусіць пачынацца з http:// або https://")
        s = store.get(cid)
        if add and url not in s[field]:
            s[field].append(url)
        if not add and url in s[field]:
            s[field].remove(url)
        store.save(cid, s)
        await reply(update, f"{field}: {', '.join(s[field]) or '—'}")
    return handler


@guard
async def quiet(update, context):
    v = (context.args[0] if context.args else "").lower()
    if v in ("off", "-", ""):
        v = ""
    elif not (len(v.split("-")) == 2 and all(p.isdigit() and 0 <= int(p) <= 24 for p in v.split("-"))):
        return await reply(update, "Прыклад: /quiet 22-8  або  /quiet off")
    store.update(update.effective_chat.id, quiet=v)
    await reply(update, f"Ціхія гадзіны: {v or 'выключаны'}")


@guard
async def pause(update, context):
    store.update(update.effective_chat.id, paused=True)
    await reply(update, "⏸ Паўза. /resume каб працягнуць.")


@guard
async def resume(update, context):
    store.update(update.effective_chat.id, paused=False)
    await reply(update, "▶️ Працуе.")


@guard
async def reset_seen(update, context):
    store.clear_seen(update.effective_chat.id)
    await reply(update, "Забыў усё, што дасылаў. Наступны дайджэст пакажа ўсё зноў.")


async def run_check(app, chat_id, manual=False):
    s = store.get(chat_id)
    if not s["keywords"] and not s["feeds"] and not s["pages"]:
        if manual:
            await app.bot.send_message(chat_id, "Спачатку /keywords.")
        return
    jobs, errors = await asyncio.to_thread(engine.fetch_all, store, chat_id, s)
    to_send, remaining = engine.select_new(store, chat_id, jobs, s["exclude"], s["limit"])
    store.update(chat_id, last_run=int(time.time()))
    if to_send:
        text = engine.format_digest(to_send, remaining)
        for part in engine.chunk(text):
            await app.bot.send_message(chat_id, part, parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)
        store.mark_seen(chat_id, [j.key for j in to_send])
    elif manual:
        await app.bot.send_message(chat_id, "Нічога новага.")
    if errors:
        log.warning("chat %s errors: %s", chat_id, errors)
        if manual:
            await app.bot.send_message(chat_id, "⚠️ Праблемы:\n" + "\n".join(errors[:5]))


@guard
async def check(update, context):
    await update.message.reply_text("Правяраю...")
    await run_check(context.application, update.effective_chat.id, manual=True)


SLACK = 150  # seconds; cron jitter must not push a run to the next slot


async def run_due(app):
    """Check every chat whose interval has elapsed."""
    now = time.time()
    for cid in store.all_chats():
        s = store.get(cid)
        if s["paused"] or in_quiet(s["quiet"]):
            continue
        if now - s["last_run"] < s["interval_min"] * 60 - SLACK:
            continue
        try:
            await run_check(app, cid)
        except Exception:
            log.exception("check failed for %s", cid)


async def tick(context: ContextTypes.DEFAULT_TYPE):
    await run_due(context.application)


async def post_init(app):
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("check", "праверыць цяпер"), BotCommand("status", "налады"),
        BotCommand("keywords", "што шукаць"), BotCommand("interval", "як часта"),
        BotCommand("limit", "колькі за раз"), BotCommand("help", "усе каманды"),
    ])


def build_app():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    handlers = {
        "start": start, "help": help_cmd, "status": status, "keywords": keywords,
        "add": add_kw, "remove": remove_kw, "exclude": exclude, "location": location,
        "sources": sources_cmd, "quiet": quiet, "pause": pause, "resume": resume,
        "resetseen": reset_seen, "check": check,
        "interval": int_cmd("interval", 15, 1440, "interval_min"),
        "limit": int_cmd("limit", 1, 30, "limit"),
        "addfeed": list_cmd("feeds", True), "delfeed": list_cmd("feeds", False),
        "watch": list_cmd("pages", True), "unwatch": list_cmd("pages", False),
    }
    for name, fn in handlers.items():
        app.add_handler(CommandHandler(name, fn))
    return app


def main():
    if not TOKEN:
        raise SystemExit("Няма TELEGRAM_TOKEN у .env")
    app = build_app()
    app.job_queue.run_repeating(tick, interval=60, first=15)
    app.run_polling()


if __name__ == "__main__":
    main()
