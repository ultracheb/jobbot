"""SQLite storage: per-chat settings and the set of already-sent jobs."""
import json
import sqlite3
import threading

DEFAULTS = {
    "keywords": [            # starter set: music / events / production (Czech)
        "produkce", "asistent produkce", "koordinátor akcí", "event manager",
        "festival", "koncerty", "booking", "hudební", "kulturní", "promotion",
        "tatér", "tetovací studio", "ateliér", "galerie", "dílna", "lektor workshopů",
    ],
    "exclude": ["office manager"],           # drop jobs whose title/company contain any of these
    "interval_min": 180,    # how often to check
    "limit": 15,             # max jobs per digest
    "location": "praha",     # jobs.cz slug / Jooble location
    "sources": ["jobscz"],   # jobscz, jooble
    "feeds": [],             # RSS/Atom urls
    "pages": [],             # career pages to watch for new links
    "paused": False,
    "quiet": "22-8",         # quiet hours "from-to" (Prague time) or ""
    "last_run": 0,
}


class Store:
    def __init__(self, path="jobbot.db"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS settings (chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, key TEXT, PRIMARY KEY (chat_id, key))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
        )
        self.db.commit()

    def get_meta(self, key, default=None):
        with self._lock:
            row = self.db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        with self._lock:
            self.db.execute(
                "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, str(value)),
            )
            self.db.commit()

    def get(self, chat_id):
        with self._lock:
            row = self.db.execute(
                "SELECT data FROM settings WHERE chat_id=?", (chat_id,)
            ).fetchone()
        data = json.loads(row[0]) if row else {}
        merged = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
        merged.update(data)
        return merged

    def save(self, chat_id, settings):
        # store only what differs from DEFAULTS, so untouched settings follow future defaults
        diff = {k: v for k, v in settings.items() if k not in DEFAULTS or v != DEFAULTS[k]}
        with self._lock:
            self.db.execute(
                "INSERT INTO settings (chat_id, data) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data",
                (chat_id, json.dumps(diff, ensure_ascii=False)),
            )
            self.db.commit()

    def update(self, chat_id, **changes):
        s = self.get(chat_id)
        s.update(changes)
        self.save(chat_id, s)
        return s

    def all_chats(self):
        with self._lock:
            rows = self.db.execute("SELECT chat_id FROM settings").fetchall()
        return [r[0] for r in rows]

    def is_seen(self, chat_id, key):
        with self._lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM seen WHERE chat_id=? AND key=?", (chat_id, key)
                ).fetchone()
                is not None
            )

    def mark_seen(self, chat_id, keys):
        with self._lock:
            self.db.executemany(
                "INSERT OR IGNORE INTO seen (chat_id, key) VALUES (?, ?)",
                [(chat_id, k) for k in keys],
            )
            self.db.commit()

    def has_prefix(self, chat_id, prefix):
        with self._lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM seen WHERE chat_id=? AND key LIKE ? LIMIT 1",
                    (chat_id, prefix + "%"),
                ).fetchone()
                is not None
            )

    def clear_seen(self, chat_id):
        with self._lock:
            self.db.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
            self.db.commit()
