"""Pure logic: gather jobs for one chat, filter, pick what to send."""
import html

import sources
from sources import Job, norm


def _hits(text, words):
    t = norm(text)
    return any(norm(w) in t for w in words)


def fetch_all(store, chat_id, s):
    """Returns (jobs, errors) for all enabled sources of this chat."""
    jobs, errors = [], []
    kws = s["keywords"]

    for kw in kws:
        if "jobscz" in s["sources"]:
            try:
                jobs += sources.jobscz_search(kw, s["location"])
            except Exception as e:
                errors.append(f"jobs.cz «{kw}»: {e}")
        if "jooble" in s["sources"]:
            try:
                jobs += sources.jooble_search(kw, s["location"] or "Praha")
            except Exception as e:
                errors.append(f"Jooble «{kw}»: {e}")

    for url in s["feeds"]:
        try:
            for job, text in sources.feed_items(url):
                if not kws or _hits(text, kws):
                    jobs.append(job)
        except Exception as e:
            errors.append(f"RSS {url}: {e}")

    for url in s["pages"]:
        try:
            links = sources.page_links(url)
            base_key = f"base|{url}"
            if not store.has_prefix(chat_id, base_key):
                # first visit: remember everything silently, notify only about new links later
                store.mark_seen(chat_id, [base_key] + [j.key for j in links])
            else:
                jobs += links
        except Exception as e:
            errors.append(f"старонка {url}: {e}")

    return jobs, errors


def select_new(store, chat_id, jobs, exclude, limit):
    """Dedupe, drop seen + excluded. Returns (to_send, remaining_count)."""
    uniq, keys = [], set()
    for j in jobs:
        if j.key in keys or store.is_seen(chat_id, j.key):
            continue
        keys.add(j.key)
        if exclude and _hits(f"{j.title} {j.company}", exclude):
            continue
        uniq.append(j)
    return uniq[:limit], max(0, len(uniq) - limit)


def format_digest(jobs, remaining=0):
    lines = [f"🔎 <b>Новыя вакансіі: {len(jobs)}</b>\n"]
    for j in jobs:
        meta = " · ".join(x for x in (j.company, j.location, j.source) if x)
        lines.append(f'• <a href="{html.escape(j.url, quote=True)}">{html.escape(j.title)}</a>\n'
                     f'  <i>{html.escape(meta)}</i>')
    if remaining:
        lines.append(f"\nЁсць яшчэ {remaining}, прыйдуць у наступным дайджэсце.")
    return "\n".join(lines)


def chunk(text, size=3800):
    """Split on blank-ish boundaries to stay under Telegram's 4096 limit."""
    parts, cur = [], ""
    for block in text.split("\n• "):
        piece = block if not cur else "• " + block
        if len(cur) + len(piece) + 1 > size and cur:
            parts.append(cur)
            cur = "• " + block
        else:
            cur = cur + ("\n" if cur else "") + piece
    if cur:
        parts.append(cur)
    return parts
