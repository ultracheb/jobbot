import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from zoneinfo import ZoneInfo

import engine, sources
from sources import Job, norm
from storage import Store, DEFAULTS
from bot import in_quiet, split_list

HTML = """
<div class="list">
 <article><h2><a href="/rpd/111/?searchId=x&rps=1">Asistent produkce festivalu</a></h2>
   <ul><li>Festival s.r.o.</li><li>Praha – Karlín</li></ul><span>Přidáno včera</span></article>
 <article><a href="/rpd/222/"><img></a><h2><a href="/rpd/222/">Senior booking manager</a></h2>
   <span>40 000 Kč</span><ul><li>Agency a.s.</li><li>Praha – Vysočany</li></ul></article>
 <article><h2><a href="/rpd/333/">Koordinátor akcí</a></h2><ul><li>Praha</li></ul></article>
</div>"""


def test_parse_jobscz():
    jobs = sources.parse_jobscz(HTML)
    assert [j.key for j in jobs] == ["jobscz:111", "jobscz:222", "jobscz:333"]
    assert jobs[0].url == "https://www.jobs.cz/rpd/111/"
    assert jobs[0].company == "Festival s.r.o." and jobs[0].location == "Praha – Karlín"
    assert jobs[1].company == "Agency a.s."


def test_norm_diacritics():
    assert norm("Koordinátor") == "koordinator"


def test_select_new_filters(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    jobs = sources.parse_jobscz(HTML)
    st.mark_seen(1, ["jobscz:111"])
    send, rest = engine.select_new(st, 1, jobs + jobs, ["SENIOR"], 10)
    assert [j.key for j in send] == ["jobscz:333"] and rest == 0


def test_limit_and_remaining(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    jobs = [Job(f"k{i}", f"t{i}", f"http://x/{i}") for i in range(7)]
    send, rest = engine.select_new(st, 1, jobs, [], 3)
    assert len(send) == 3 and rest == 4
    st.mark_seen(1, [j.key for j in send])
    send2, rest2 = engine.select_new(st, 1, jobs, [], 3)
    assert [j.key for j in send2] == ["k3", "k4", "k5"] and rest2 == 1


def test_settings_roundtrip_and_isolation(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    st.update(1, keywords=["a"], interval_min=30)
    assert st.get(1)["keywords"] == ["a"] and st.get(2)["keywords"] == DEFAULTS["keywords"]
    st.get(2)["keywords"].append("zzz")
    assert "zzz" not in DEFAULTS["keywords"]
    # only non-default values are persisted; resetting to defaults clears them
    import json
    st.save(1, dict(DEFAULTS))
    assert json.loads(st.db.execute("SELECT data FROM settings WHERE chat_id=1").fetchone()[0]) == {}
    assert len(DEFAULTS["keywords"]) >= 5 and st.get(1)["interval_min"] == 60


def test_fetch_all_with_fake_sources(tmp_path, monkeypatch):
    st = Store(str(tmp_path / "t.db"))
    calls = []
    monkeypatch.setattr(sources, "jobscz_search",
                        lambda kw, loc: calls.append((kw, loc)) or [Job(f"j:{kw}", kw, "http://x")])
    monkeypatch.setattr(sources, "feed_items", lambda url: [
        (Job("r1", "Hudební produkce", "http://r1"), "Hudební produkce"),
        (Job("r2", "Účetní", "http://r2"), "Účetní")])
    pages = {"n": 0}
    def fake_links(url):
        pages["n"] += 1
        base = [Job("p1", "Stará pozice", "http://p1")]
        return base if pages["n"] == 1 else base + [Job("p2", "Nová pozice", "http://p2")]
    monkeypatch.setattr(sources, "page_links", fake_links)
    s = st.update(1, keywords=["produkce", "booking"], feeds=["http://feed"], pages=["http://career"])
    jobs, errs = engine.fetch_all(st, 1, s)
    assert calls == [("produkce", "praha"), ("booking", "praha")] and not errs
    assert {j.key for j in jobs} == {"j:produkce", "j:booking", "r1"}   # r2 filtered, page baseline silent
    jobs2, _ = engine.fetch_all(st, 1, s)
    assert "p2" in {j.key for j in jobs2} and "p1" in {j.key for j in jobs2}
    send, _ = engine.select_new(st, 1, jobs2, [], 50)
    assert "p1" not in {j.key for j in send} and "p2" in {j.key for j in send}


def test_source_error_is_reported_not_raised(tmp_path, monkeypatch):
    st = Store(str(tmp_path / "t.db"))
    def boom(*a): raise RuntimeError("down")
    monkeypatch.setattr(sources, "jobscz_search", boom)
    s = st.update(1, keywords=["x"])
    jobs, errs = engine.fetch_all(st, 1, s)
    assert jobs == [] and "down" in errs[0]


def test_format_and_chunk():
    jobs = [Job(str(i), f"T<{i}>", "http://x/?a=1&b=2", "Co", "Praha", "jobs.cz") for i in range(60)]
    text = engine.format_digest(jobs, 5)
    assert "T&lt;0&gt;" in text and "a=1&amp;b=2" in text
    parts = engine.chunk(text)
    assert all(len(p) <= 4096 for p in parts) and len(parts) > 1


def test_quiet_hours():
    z = ZoneInfo("Europe/Prague")
    assert in_quiet("22-8", datetime(2026, 1, 1, 23, tzinfo=z))
    assert in_quiet("22-8", datetime(2026, 1, 1, 3, tzinfo=z))
    assert not in_quiet("22-8", datetime(2026, 1, 1, 12, tzinfo=z))
    assert not in_quiet("", datetime(2026, 1, 1, 3, tzinfo=z))
    assert in_quiet("1-5", datetime(2026, 1, 1, 2, tzinfo=z))


def test_split_list():
    assert split_list(["produkce,", "festival", "koordinátor,", "booking"]) == \
        ["produkce", "festival koordinátor", "booking"]


def test_jobscz_card_salary_and_meta():
    from sources import parse_jobscz
    from engine import format_digest
    html = """<div><div><a href="/rpd/111/">EVENT &amp; OPERATIONS MANAGER/KA</a>
    <span>Aktualizováno dnes</span><span>45 000 ‍–‍ 55 000 Kč</span>
    <span>Možnost občasné práce z domova</span><span>BB Sport s.r.o.</span>
    <span>Praha – Nové Město</span></div>
    <div><a href="/rpd/222/">Event Project Manager</a><span>23. listopadu</span>
    <span>TV Prima</span><span>Praha – Strašnice</span><span>172 hodnocení na Atmoskopu</span></div></div>"""
    a, b = parse_jobscz(html)
    assert a.salary == "45 000 – 55 000 Kč" and a.company == "BB Sport s.r.o."
    assert a.posted == "Aktualizováno dnes" and a.tags == ("Možnost občasné práce z domova",)
    assert b.salary == "" and b.company == "TV Prima" and b.rating.startswith("172")
    out = format_digest([a, b])
    assert "45 000 – 55 000 Kč" in out and "не ўказана" in out


def test_relevance_filter():
    from engine import relevant
    from sources import Job
    J = lambda t, c="": Job(key=t, title=t, url="u", company=c)
    assert relevant(J("Produkční festivalu"), "produkce")
    assert relevant(J("Event & Operations Manager/ka"), "event manager")
    assert relevant(J("Tatér/ka do studia"), "tatér")
    assert not relevant(J("AI produktový manažer"), "produkce")
    assert not relevant(J("Platform Engineer"), "festival")
    assert not relevant(J("Project Manager"), "PR")
    assert relevant(J("PR Specialist"), "PR")


def test_card_tags_before_company():
    from sources import parse_jobscz
    html = """<div><a href="/rpd/9/">AI produktový manažer</a><span>20. listopadu</span>
    <span>Odpověď do 2 týdnů</span><span>Seznam.cz, a.s.</span><span>Praha</span></div>"""
    j = parse_jobscz(html)[0]
    assert j.company == "Seznam.cz, a.s." and j.location == "Praha" and j.tags == ("Odpověď do 2 týdnů",)
