"""Job sources. Each function returns a list of Job."""
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; JobBot/1.0; personal job alerts)"
TIMEOUT = 20


@dataclass
class Job:
    key: str
    title: str
    url: str
    company: str = ""
    location: str = ""
    source: str = ""
    salary: str = ""
    posted: str = ""
    tags: tuple = ()
    rating: str = ""


def norm(s):
    """Lowercase and strip diacritics so 'koordinátor' matches 'Koordinator'."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _get(url, **kw):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "cs,en;q=0.8"},
                     timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


# ---------- jobs.cz ----------

_DATE_RE = re.compile(r"^(Aktualizováno|Přidáno|Končí|Dnes|Včera|\d{1,2}\. ?\w+)", re.I)


def _clean(t):
    """Drop zero-width joiners, turn nbsp/thin spaces into normal ones."""
    t = re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", t)
    t = re.sub("[\u00a0\u2009\u202f]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_TAG_RE = re.compile(r"^(Odpověď|Odpovězte|Možnost|Práce|Pouze|Hybridní|Home ?office|Bez |Nabízíme)", re.I)
_LOC_RE = re.compile(r"^[^\W\d_][\w .]{1,30}\s[–-]\s\S")


def parse_jobscz(html):
    soup = BeautifulSoup(html, "html.parser")
    ids_in = lambda node: {m.group(1) for a in node.find_all("a", href=True)
                           for m in [re.search(r"/rpd/(\d+)", a["href"])] if m}
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"/rpd/(\d+)", a["href"])
        title = a.get_text(" ", strip=True)
        if not m or not title or m.group(1) in seen:
            continue
        jid = m.group(1)
        seen.add(jid)
        # climb to the smallest ancestor that still contains only this one job
        node = a
        while node.parent is not None and len(ids_in(node.parent)) <= 1:
            node = node.parent
        texts = [_clean(t) for t in node.stripped_strings if t != title]
        texts = [t for t in texts if t and t != title]
        salary = posted = rating = location = company = ""
        rest = []
        for t in texts:
            if "Kč" in t and any(c.isdigit() for c in t):
                salary = salary or t
            elif _DATE_RE.match(t):
                posted = posted or t
            elif "hodnocení" in t:
                rating = rating or t
            else:
                rest.append(t)
        tags = [t for t in rest if _TAG_RE.match(t)]
        rest = [t for t in rest if t not in tags]
        li = next((i for i, t in enumerate(rest) if _LOC_RE.match(t) or "lokalit" in t), None)
        if li is not None:
            location = rest[li]
            company = rest[li - 1] if li > 0 else ""
        elif len(rest) >= 2:
            company, location = rest[0], rest[-1]
        elif rest:
            company = rest[0]
        jobs.append(Job(key=f"jobscz:{jid}", title=title, url=f"https://www.jobs.cz/rpd/{jid}/",
                        company=company, location=location, source="jobs.cz",
                        salary=salary, posted=posted, tags=tuple(tags[:3]), rating=rating))
    return jobs


def jobscz_search(keyword, location="praha"):
    base = "https://www.jobs.cz/prace/" + (f"{location}/" if location else "")
    r = _get(base, params={"q[]": keyword})
    time.sleep(1)  # be polite
    return parse_jobscz(r.text)


# ---------- Jooble (free API key: https://jooble.org/api/about) ----------

def jooble_search(keyword, location="Praha"):
    key = os.environ.get("JOOBLE_KEY", "")
    if not key:
        raise RuntimeError("няма JOOBLE_KEY у .env")
    r = requests.post(f"https://jooble.org/api/{key}",
                      json={"keywords": keyword, "location": location},
                      headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        link = j.get("link") or ""
        if not link:
            continue
        out.append(Job(key=f"jooble:{j.get('id') or link}", title=j.get("title", "").strip(),
                       url=link, company=j.get("company", ""), location=j.get("location", ""),
                       source="Jooble"))
    return out


# ---------- RSS / Atom ----------

def feed_items(url):
    d = feedparser.parse(url, agent=UA)
    if d.bozo and not d.entries:
        raise RuntimeError(f"не атрымалася прачытаць feed: {d.bozo_exception}")
    host = urlparse(url).netloc
    out = []
    for e in d.entries:
        link = e.get("link")
        if not link:
            continue
        text = f"{e.get('title', '')} {e.get('summary', '')}"
        out.append((Job(key=f"rss:{link}", title=e.get("title", link), url=link,
                        company=host, source="RSS"), text))
    return out


# ---------- page watcher (career pages) ----------

def page_links(url):
    r = _get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    host = urlparse(url).netloc
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(url, a["href"]).split("#")[0]
        if len(text) < 4 or not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        out.append(Job(key=f"page:{url}|{href}", title=text, url=href, company=host, source="старонка"))
    return out
