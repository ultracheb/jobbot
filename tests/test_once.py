import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from telegram import Update
from telegram.ext import ExtBot

import bot, engine, run_once, sources
from sources import Job
from storage import Store


def make_update(uid, text, chat=42):
    cmd_len = len(text.split()[0])
    return {"update_id": uid, "message": {
        "message_id": uid, "date": 1700000000,
        "chat": {"id": chat, "type": "private"},
        "from": {"id": chat, "is_bot": False, "first_name": "T"},
        "text": text, "entities": [{"type": "bot_command", "offset": 0, "length": cmd_len}]}}


def test_run_once_processes_commands_and_digest(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "t.db"))
    monkeypatch.setattr(bot, "store", store)
    monkeypatch.setattr(bot, "TOKEN", "123:abc")
    monkeypatch.setattr(bot, "ALLOWED", set())
    sent, calls = [], {"get_updates": []}

    from telegram import User
    async def noop(self, *a, **k): return None
    async def fake_init(self, *a, **k):
        self._bot_user = User(id=1, first_name="jobbot", is_bot=True, username="jobbot")
    async def fake_send(self, chat_id, text, **k): sent.append((chat_id, text))
    pending = [make_update(10, "/keywords produkce, booking"), make_update(11, "/limit 2")]

    async def fake_get_updates(self, offset=None, **k):
        calls["get_updates"].append(offset)
        return [Update.de_json(u, self) for u in pending if offset is None or u["update_id"] >= offset]

    monkeypatch.setattr(ExtBot, "initialize", fake_init)
    monkeypatch.setattr(ExtBot, "shutdown", noop)
    monkeypatch.setattr(ExtBot, "send_message", fake_send)
    monkeypatch.setattr(ExtBot, "get_updates", fake_get_updates)
    monkeypatch.setattr(sources, "jobscz_search",
                        lambda kw, loc: [Job(f"{kw}{i}", f"{kw} job {i}", f"http://x/{kw}{i}") for i in range(3)])

    asyncio.run(run_once.run())

    s = store.get(42)
    assert s["keywords"] == ["produkce", "booking"] and s["limit"] == 2
    assert store.get_meta("offset") == "12"
    texts = [t for _, t in sent]
    assert any("Словы" in t for t in texts)
    digest = [t for t in texts if "Новыя вакансіі" in t]
    assert len(digest) == 1 and digest[0].count("<a href") == 2 and "яшчэ 4" in digest[0]

    # second run: no new commands, interval not elapsed -> nothing new is sent
    n = len(sent)
    asyncio.run(run_once.run())
    assert len(sent) == n and calls["get_updates"][-1] == 12


def test_due_slack(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "t.db"))
    monkeypatch.setattr(bot, "store", store)
    import time
    store.update(1, keywords=["a"], interval_min=30, last_run=int(time.time()) - (30 * 60 - 60))
    ran = []
    async def fake_check(app, cid, manual=False): ran.append(cid)
    monkeypatch.setattr(bot, "run_check", fake_check)
    monkeypatch.setattr(bot, "in_quiet", lambda q, now=None: False)
    asyncio.run(bot.run_due(None))
    assert ran == [1]   # 29 min elapsed is close enough for a 30 min interval
