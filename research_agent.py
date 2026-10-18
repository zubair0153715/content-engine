#!/usr/bin/env python3
"""Auto-research agent — Content Engine v2.

Given a topic, fetches verifiable facts (Wikipedia API: reliable, dated),
attempts a DDG-lite news sweep (usually bot-walled — failure is logged, not
hidden), ranks 3-5 content angles heuristically, and writes research_brief.md
in the exact v1 format (Facts + Sources) plus ranked Angles and verification
notes.

Honesty rules:
- Every fact carries its source title + URL + retrieval date.
- Claims from a single non-authoritative source are tagged [UNVERIFIED].
- Angle scores are a documented heuristic, not a prediction of virality.

Usage:
    python3 research_agent.py --topic "3 ChatGPT prompt tricks" --project demo-002
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.path.expanduser("~/workspace/content-engine")
UA = {"User-Agent": "content-engine-research/2.0 (contact: local build)"}


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def wiki_search(topic, limit=6):
    q = urllib.parse.quote(topic)
    url = (f"https://en.wikipedia.org/w/api.php?action=opensearch&search={q}"
           f"&limit={limit}&namespace=0&format=json")
    try:
        data = json.loads(fetch(url))
        return list(zip(data[1], data[3]))  # (title, url)
    except Exception as e:
        print(f"[research] wikipedia opensearch failed: {e}", file=sys.stderr)
        return []


def wiki_extract(title, sentences=8):
    t = urllib.parse.quote(title)
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
           f"&exintro=1&explaintext=1&exsentences={sentences}&titles={t}&format=json")
    try:
        data = json.loads(fetch(url))
        pages = data["query"]["pages"]
        page = next(iter(pages.values()))
        return page.get("extract", "")
    except Exception as e:
        print(f"[research] wikipedia extract failed for {title}: {e}", file=sys.stderr)
        return ""


def ddg_lite(query):
    """Best-effort news-style sweep. Often bot-walled; failure is normal."""
    q = urllib.parse.quote(query)
    url = f"https://lite.duckduckgo.com/lite/?q={q}"
    try:
        html = fetch(url, timeout=20)
        links = re.findall(r'href="(https?://[^"]+)"[^>]*class="result-link"',
                           html)
        if not links:
            return [], "no parseable results (likely bot-walled)"
        return links[:8], ""
    except Exception as e:
        return [], f"fetch failed: {type(e).__name__}"


def split_facts(text, source_title, source_url, date):
    facts = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        s = sent.strip()
        if len(s) > 60 and len(s) < 400:
            facts.append({"fact": s, "source": source_title,
                          "url": source_url, "date": date})
    return facts


ANGLE_TEMPLATES = [
    ("mistakes", "{t} — 3 mistakes almost everyone makes (and the fix)",
     "Negativity-bias hook; works when the topic has common pitfalls.", ["mistake", "wrong", "avoid", "error"]),
    ("hidden", "{t} — what most people miss",
     "Curiosity gap; works when facts contain non-obvious details.", ["most people", "hidden", "secret", "few know"]),
    ("beginner", "{t} explained in 40 seconds",
     "Beginner-friendly explainer; broadest audience.", ["basic", "introduction", "overview"]),
    ("versus", "{t}: what actually works in 2026",
     "Recency + comparison angle; needs dated sources.", ["2026", "2025", "new", "update"]),
    ("myths", "{t} — myths vs reality",
     "Myth-busting; works when sources contradict popular belief.", ["myth", "actually", "contrary", "despite"]),
]


def rank_angles(topic, facts, top_n=5):
    corpus = " ".join(f["fact"] for f in facts).lower()
    scored = []
    for key, title, why, keywords in ANGLE_TEMPLATES:
        hits = sum(1 for k in keywords if k in corpus)
        # recency bonus
        recency = 1 if re.search(r"202[56]", corpus) else 0
        score = round(0.5 + 0.15 * hits + 0.2 * recency, 2)
        scored.append({"key": key,
                       "title": title.format(t=topic),
                       "why": why,
                       "score": min(score, 1.0),
                       "keyword_hits": hits,
                       "source": "heuristic"})
    scored.sort(key=lambda a: -a["score"])
    return scored[:top_n]


def llm_rank_angles(topic, facts, top_n=5):
    """Ask the LLM to rank angles from the evidence. Falls back to the
    keyword heuristic when no LLM is available — never blocks research."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from llm import ask, LLMUnavailable
    except Exception as e:
        print(f"[research] llm module not importable ({e}) — heuristic angles",
              file=sys.stderr)
        return rank_angles(topic, facts, top_n)
    evidence = "\n".join(f"- {f['fact']} [{f['source']}]" for f in facts[:18])
    system = ("You rank short-form video angles for a 40-second explainer. "
              "Reply with JSON ONLY: a list of 3-5 objects "
              '{"title": "...", "score": 0.0-1.0, "why": "one line"}. '
              "Base scores on the evidence: timeliness, curiosity gap, and "
              "clear viewer benefit. No markdown, no commentary.")
    try:
        raw = ask(system, f"TOPIC: {topic}\nEVIDENCE:\n{evidence}",
                  temperature=0.5, max_tokens=800)
    except LLMUnavailable as e:
        print(f"[research] LLM unavailable ({str(e)[:80]}) — heuristic angles",
              file=sys.stderr)
        return rank_angles(topic, facts, top_n)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        print("[research] LLM angle reply not JSON — heuristic angles",
              file=sys.stderr)
        return rank_angles(topic, facts, top_n)
    try:
        items = json.loads(m.group(0))
        out = []
        for it in items[:top_n]:
            out.append({"key": "llm", "title": str(it.get("title", ""))[:120],
                        "why": str(it.get("why", ""))[:200],
                        "score": round(max(0.0, min(1.0,
                                                   float(it.get("score", 0.5)))), 2),
                        "source": "llm"})
        out.sort(key=lambda a: -a["score"])
        print(f"[research] angles ranked by LLM ({len(out)})", file=sys.stderr)
        return out
    except (ValueError, TypeError, KeyError) as e:
        print(f"[research] LLM angle JSON unparseable ({e}) — heuristic angles",
              file=sys.stderr)
        return rank_angles(topic, facts, top_n)


def write_brief(project_dir, topic, facts, angles, notes):
    today = datetime.date.today().isoformat()
    lines = [f"# Research brief: {topic}\n",
             f"> Auto-generated {today} by research_agent v2 (Content Engine). "
             "Facts carry source + retrieval date. [UNVERIFIED] = single "
             "non-authoritative source — verify before scripting claims as fact.\n",
             "## Facts"]
    for f in facts[:25]:
        tag = " [UNVERIFIED]" if f.get("unverified") else ""
        lines.append(f"- {f['fact']}{tag} [Source: {f['source']}]({f['url']})")
    lines.append("\n## Content angles (ranked)")
    for i, a in enumerate(angles, 1):
        src = f" [{a.get('source', 'heuristic')}]" if a.get("source") else ""
        lines.append(f"{i}. **{a['title']}** — score {a['score']:.2f}{src}. {a['why']}")
    lines.append("\n## Sources")
    seen = set()
    for f in facts:
        if f["url"] not in seen:
            seen.add(f["url"])
            lines.append(f"- {f['source']} — {f['url']} (retrieved {f['date']})")
    lines.append("\n## Verification notes")
    lines += [f"- {n}" for n in notes] or ["- none"]
    out = os.path.join(project_dir, "research_brief.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[research] brief -> {out} ({len(facts)} facts, {len(angles)} angles)")
    return out


def run(topic, project, research_query=None):
    pdir = os.path.join(BASE, "projects", project)
    os.makedirs(os.path.join(pdir, "assets"), exist_ok=True)
    today = datetime.date.today().isoformat()
    notes, facts = [], []

    query = research_query or topic
    results = wiki_search(query)
    tried = [query]
    # fallback: longest significant single words, accepted only if the top
    # hit shares a word with the topic (avoids generic drift)
    if not results:
        topic_words = {w.lower() for w in topic.split()}
        for w in sorted(set(query.split()), key=len, reverse=True):
            if len(w) > 4:
                r = wiki_search(w)
                tried.append(w)
                if r and (topic_words & set(r[0][0].lower().split())):
                    results = r
                    break
    if len(tried) > 1:
        notes.append("opensearch queries tried: " + " -> ".join(tried))
    if not results:
        notes.append("Wikipedia opensearch returned nothing — topic may need "
                     "rephrasing; brief will be thin.")
    for title, url in results[:4]:
        ext = wiki_extract(title)
        if ext:
            facts.extend(split_facts(ext, title, url, today))
    print(f"[research] wikipedia: {len(results)} pages, {len(facts)} facts")

    ddg_links, ddg_note = ddg_lite(topic + " 2026")
    if ddg_links:
        for link in ddg_links[:5]:
            facts.append({"fact": f"Related coverage: {link}",
                          "source": "DuckDuckGo lite sweep",
                          "url": link, "date": today, "unverified": True})
        print(f"[research] ddg-lite: {len(ddg_links)} links")
    else:
        notes.append(f"DDG-lite sweep unavailable ({ddg_note}) — news angles "
                     "rely on operator-supplied sources.")
        print(f"[research] ddg-lite unavailable: {ddg_note}")

    angles = llm_rank_angles(topic, facts)
    notes.append("Angle scores: 'llm' = ranked from evidence by the LLM; "
                 "'heuristic' = keyword/recency fallback (not a virality "
                 "prediction either way).")
    return write_brief(pdir, topic, facts, angles, notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--research-query", default="",
                    help="override the Wikipedia search query (default: topic)")
    a = ap.parse_args()
    run(a.topic, a.project, a.research_query or None)


if __name__ == "__main__":
    main()
