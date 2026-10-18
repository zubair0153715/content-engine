"""Auto image-fetch for Content Engine scenes.

For each scene, derive 2-3 keyword queries from narration/on-screen text and
fetch a topically-relevant REAL image, free, in this order:
  1. Wikimedia Commons API (no key, always available — all media freely licensed)
  2. Pexels API (if PEXELS_API_KEY set — free 2-min signup at pexels.com/api)
  3. Pixabay API (if PIXABAY_API_KEY set — free signup at pixabay.com/api)
  4. Hugging Face Inference (if HF_TOKEN set — FLUX.1-schnell text-to-image;
     free accounts get ~$0.10/mo credits ≈ 10 images/mo, so this is a bonus
     source, not production capacity. Tested 2026-10-17: unauthenticated
     requests now 401 — the old free anon tier is dead.)
If nothing found -> return None and the engine keeps its motion-graphics
fallback slide (pipeline never breaks).

Pollinations.ai was re-tested 2026-10-17: even with nologo=true the free tier
stamps a visible "pollinations.ai" watermark on every image -> REJECTED.
"""
import json
import os
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "ContentEngine/2.1 (educational short-video pipeline)"}
TIMEOUT = 25

STOPWORDS = set("""
a an the and or of to in on for with as at by from is are was were be been
it its this that these those we you they he she him her them our your their
my me us do does did done have has had having will would can could should
not no yes so if but then than too very just about into over after before
between through during each other some such only own same also how what
when where which who whom why because while until than more most less many much other same every all any few several
new old first last one two three four five six seven eight nine ten
day days time times year years people person things thing way ways
get gets make makes use uses using used help helps save saves
daily everyday today tonight morning evening home work life lives
best top free easy simple quick fast better good great big small
look looks like look like really actually ever never always often here there
study studies student students school learn learning tool tools
app apps ai artificial intelligence video videos photo photos
catch catches take takes give gives show shows tell tells find finds
keep keeps put puts set sets run runs turn turns start starts stop stops
work works play plays read reads write writes say says come comes go goes
know knows think thinks see sees want wants need needs try tries
""".split())


def derive_queries(text, topic="", n=3):
    """2-3 keyword queries from scene text.

    Prefers adjacent word-pairs from the original text ("drug interaction")
    over bag-of-words joins ("checkers combinations dangerous") — pairs keep
    the phrase meaning that Commons search needs.
    """
    toks = [w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text or "")]
    kept = [(i, w) for i, w in enumerate(toks) if w not in STOPWORDS]
    pairs = []
    for (i1, w1), (i2, w2) in zip(kept, kept[1:]):
        if i2 == i1 + 1 and w1 != w2:
            pairs.append(f"{w1} {w2}")
    queries = []
    for p in pairs[:2]:
        queries.append(p)
    if topic and pairs:
        queries.append(f"{topic} {pairs[0].split()[0]}")
    if kept:
        queries.append(kept[0][1])
    seen, out = set(), []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:n]


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    if len(data) < 8000:
        raise ValueError(f"suspiciously small image ({len(data)}b)")
    with open(dest, "wb") as f:
        f.write(data)
    # fail fast if it isn't a real image
    from PIL import Image
    with Image.open(dest) as im:
        im.verify()
    return dest


def _wikimedia_candidates(query):
    """Return scored candidate list for a query (no downloads)."""
    q = urllib.parse.quote(query + " filetype:bitmap")
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrsearch=" + q + "&gsrnamespace=6&gsrlimit=12"
           "&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=1080")
    try:
        data = _get_json(url)
    except Exception:
        return []
    pages = (data.get("query") or {}).get("pages") or {}
    qwords = set(query.lower().split())
    cands = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        thumb = ii.get("thumburl") or ii.get("url")
        if not thumb:
            continue
        title = p.get("title", "")
        tw = set(re.findall(r"[a-z]+", title.lower()))
        rel = len(qwords & tw)  # query words appearing in the file title
        em = ii.get("extmetadata") or {}
        lic = (em.get("LicenseShortName") or {}).get("value", "")
        cands.append({
            "thumb": thumb, "title": title, "license": lic,
            "page": ii.get("descriptionurl", ""),
            "_rel": rel,
            "score": rel * 10 + (5 if (ii.get("width") or 0) >= 600 else 0),
        })
    cands.sort(key=lambda c: -c["score"])
    return cands


def fetch_wikimedia(query, dest, min_rel=1):
    """Commons API search -> best thumbnail. Returns (dest, meta) or None.

    min_rel: candidate must share >=min_rel query words with the file title,
    otherwise we keep looking (avoids semantically-wrong matches).
    """
    for c in _wikimedia_candidates(query):
        if c["_rel"] < min_rel:
            continue
        try:
            _download(c["thumb"], dest)
            return dest, {"source": "wikimedia_commons", "title": c["title"],
                          "license": c["license"] or "freely licensed (Commons)",
                          "page": c["page"]}
        except Exception:
            continue
    return None


def fetch_pexels(query, dest):
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return None
    q = urllib.parse.quote(query)
    url = (f"https://api.pexels.com/v1/search?query={q}&per_page=3"
           "&orientation=portrait")
    try:
        data = _get_json(url, {"Authorization": key})
    except Exception:
        return None
    for ph in data.get("photos", []):
        src = (ph.get("src") or {}).get("large2x") or (ph.get("src") or {}).get("large")
        if not src:
            continue
        try:
            _download(src, dest)
            return dest, {"source": "pexels",
                          "photographer": ph.get("photographer", ""),
                          "page": ph.get("url", ""),
                          "license": "Pexels License (free use)"}
        except Exception:
            continue
    return None


def fetch_pixabay(query, dest):
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None
    q = urllib.parse.quote(query)
    url = (f"https://pixabay.com/api/?key={key}&q={q}&image_type=photo"
           "&orientation=vertical&per_page=3&safesearch=true")
    try:
        data = _get_json(url)
    except Exception:
        return None
    for h in data.get("hits", []):
        src = h.get("largeImageURL") or h.get("webformatURL")
        if not src:
            continue
        try:
            _download(src, dest)
            return dest, {"source": "pixabay",
                          "photographer": h.get("user", ""),
                          "page": h.get("pageURL", ""),
                          "license": "Pixabay Content License (free use)"}
        except Exception:
            continue
    return None


def fetch_hf(query, dest):
    """Hugging Face Inference Providers text-to-image (FLUX.1-schnell).

    Optional HF_TOKEN (free signup at huggingface.co). Free accounts get
    ~$0.10/month provider credits (~10 FLUX images) — a bonus source for
    scenes nothing else covers, not production capacity. PRO ($9/mo) gives
    $2/mo credits (~200 images) which makes this a real source.
    Tested 2026-10-17: unauthenticated -> HTTP 401, so no-token = skip.
    """
    tok = os.environ.get("HF_TOKEN", "").strip()
    if not tok:
        return None
    model = os.environ.get("HF_IMAGE_MODEL",
                           "black-forest-labs/FLUX.1-schnell")
    url = f"https://router.huggingface.co/hf-inference/models/{model}"
    body = json.dumps({
        "inputs": (f"cinematic vertical smartphone photo, {query}, "
                   "sharp, well lit, no text, no watermark, no logo"),
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={**UA, "Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            ctype = r.headers.get("Content-Type", "")
            data = r.read()
    except Exception:
        return None
    if len(data) < 8000 or "image" not in ctype:
        return None
    with open(dest, "wb") as f:
        f.write(data)
    try:
        from PIL import Image
        with Image.open(dest) as im:
            im.verify()
    except Exception:
        return None
    return dest, {"source": "huggingface_inference", "model": model,
                  "query": query,
                  "license": "AI-generated (FLUX.1-schnell: Apache-2.0)"}


def fetch_for_scene(scene_id, text, topic, assets_dir):
    """Try sources in order; save assets/{scene_id}.jpg. Returns meta or None."""
    dest = os.path.join(assets_dir, f"{scene_id}.jpg")
    # respect manually dropped assets
    for ext in (".png", ".jpg"):
        p = os.path.join(assets_dir, f"{scene_id}{ext}")
        if os.path.exists(p) and p != dest:
            return {"source": "manual", "note": "pre-dropped asset used"}
    queries = derive_queries(text, topic)
    # generic CTA words ("follow", "facts") match semantically-wrong images
    # (concert photos, birds) — drop them and let the topic queries win.
    WEAK = {"follow", "follows", "following", "more", "facts", "fact",
            "hello", "welcome", "thanks", "thank", "please", "like", "likes",
            "share", "shares", "subscribe", "subscribes", "comment", "comments"}
    queries = [q for q in queries
               if not all(w in WEAK for w in q.lower().split())]
    # topic-anchored queries interleaved: generic scenes (hook/CTA) get
    # on-topic images instead of whatever their weak words match.
    tqs = [q for q in derive_queries(topic or "", "") if q not in queries]
    mixed = []
    for a, b in zip(queries, tqs):
        mixed += [a, b]
    mixed += queries[len(tqs):] + tqs[len(queries):]
    queries = mixed[:5]
    fetchers = [fetch_wikimedia, fetch_pexels, fetch_pixabay, fetch_hf]
    for q in queries:
        for fn in fetchers:
            try:
                got = fn(q, dest)
            except Exception:
                got = None
            if got:
                _, meta = got
                meta["query"] = q
                return meta
    return None
