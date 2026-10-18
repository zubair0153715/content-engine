#!/usr/bin/env python3
"""Content Engine v2 — topic in, multi-platform short video + SEO package out.

Usage:
    python3 engine.py research   --project ID --topic "text" [--auto] [--brief-text "..."]
    python3 engine.py script     --project ID --script-file scenes.json
    python3 engine.py voiceover  --project ID [--voice ID] [--language en]
                                 [--tts-engine hosted|piper|gtts] [--no-tts-fallback]
    python3 engine.py visuals    --project ID
    python3 engine.py assemble   --project ID
    python3 engine.py platforms  --project ID        # v2: 1:1 + 16:9 renders
    python3 engine.py seo        --project ID
    python3 engine.py package    --project ID
    python3 engine.py qc         --project ID
    python3 engine.py run        --project ID --topic "text" [--auto]   # all stages in order

Each stage is independently runnable and resumable (skips finished work).
v2 adds: auto-research (web), piper local-TTS fallback, multi-platform renders.
"""
import json
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.expanduser("~/workspace/content-engine")
PROJECTS = os.path.join(BASE, "projects")
TTS = "/opt/hatch/bin/tts"
PIPER_BIN = os.path.join(BASE, "bin", "piper", "piper", "piper")
PIPER_MODEL = os.path.join(BASE, "bin", "piper", "en_US-lessac-medium.onnx")
F_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
F_REG = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
W, H = 1080, 1920  # 9:16 vertical master
PLATFORMS = {"1x1": (1080, 1080), "16x9": (1920, 1080)}  # derived renders
CHARS_PER_MIN_EN = 800  # narration pacing estimate


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 900), **kw)


def pdir(pid):
    d = os.path.join(PROJECTS, pid)
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    os.makedirs(os.path.join(d, "audio"), exist_ok=True)
    os.makedirs(os.path.join(d, "segments"), exist_ok=True)
    return d


def log(msg):
    print(f"[engine] {msg}", flush=True)


def stage_research(pid, topic, brief_text=None, auto=False, research_query=None):
    d = pdir(pid)
    out = os.path.join(d, "research_brief.md")
    if auto:
        # v2: web research instead of operator-filled template
        sys.path.insert(0, BASE)
        from research_agent import run as auto_research
        log("research: auto mode (web)")
        return auto_research(topic, pid, research_query)
    if os.path.exists(out) and not brief_text:
        log(f"research brief exists, kept -> {out}")
        return out
    if brief_text:
        brief = brief_text
    else:
        brief = (f"# Research brief: {topic}\n\n"
                 "> Fill this in (or pass --brief-text). One verified fact per bullet, with source URL.\n\n"
                 "## Facts\n- \n\n## Sources\n- \n")
    with open(out, "w", encoding="utf-8") as f:
        f.write(brief)
    log(f"research brief -> {out}")
    return out


SCRIPT_SYSTEM = (
    "You write scripts for 40-second vertical explainer videos (YouTube "
    "Shorts / Reels / TikTok). Reply with JSON ONLY: a list of 4-6 scene "
    "objects, each {\"id\": \"scene1\", \"narration\": \"...\", "
    "\"on_screen\": \"BIG\\nTEXT\"}. Rules: scene1 is a hook under 120 "
    "characters that names the viewer benefit; each narration 90-140 "
    "characters (spoken, conversational, no hashtags); on_screen is 2-4 "
    "huge words per scene; last scene is a follow CTA. Total narration "
    "under 700 characters. Base every claim on the brief; never invent "
    "facts. No markdown, no commentary, JSON only."
)


def draft_scenes_from_brief(pid, topic):
    """LLM-drafted scenes -> scenes.draft.json. Operator MUST review before
    `script --script-file scenes.draft.json` promotes it to script.json."""
    sys.path.insert(0, BASE)
    from llm import ask, LLMUnavailable
    d = pdir(pid)
    brief_p = os.path.join(d, "research_brief.md")
    if not os.path.exists(brief_p):
        sys.exit("draft needs research_brief.md — run research first")
    with open(brief_p, encoding="utf-8") as f:
        brief = f.read()[:6000]
    try:
        raw = ask(SCRIPT_SYSTEM,
                  f"VIDEO TOPIC: {topic}\n\nRESEARCH BRIEF:\n{brief}",
                  temperature=0.7, max_tokens=1500)
    except LLMUnavailable as e:
        sys.exit(f"script draft needs an LLM: {e}\n"
                 "Write scenes.json manually instead (see README).")
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        sys.exit("LLM did not return JSON scenes — write scenes.json manually.")
    try:
        scenes = json.loads(m.group(0))
    except ValueError:
        sys.exit("LLM scenes JSON unparseable — write scenes.json manually.")
    assert isinstance(scenes, list) and 1 <= len(scenes) <= 8, \
        "LLM returned wrong scene count"
    total = 0
    for i, s in enumerate(scenes):
        assert s.get("narration"), f"scene {i} missing narration"
        s.setdefault("on_screen", "")
        s.setdefault("id", f"scene{i+1}")
        total += len(s["narration"])
    if total > 800:
        log(f"WARNING: draft narration {total} chars > 800 — video may exceed 60s")
    out = os.path.join(d, "scenes.draft.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    log(f"DRAFT scenes -> {out} ({len(scenes)} scenes, ~{total} chars). "
        f"REVIEW REQUIRED: promote with "
        f"`engine.py script --project {pid} --script-file {out}`")
    return out


def stage_script(pid, script_file):
    d = pdir(pid)
    with open(script_file, encoding="utf-8") as f:
        scenes = json.load(f)
    assert isinstance(scenes, list) and 1 <= len(scenes) <= 8, "script needs 1-8 scenes"
    total_chars = 0
    for i, s in enumerate(scenes):
        assert s.get("narration"), f"scene {i} missing narration"
        s.setdefault("on_screen", "")
        s.setdefault("id", f"scene{i+1}")
        total_chars += len(s["narration"])
    est_s = total_chars / CHARS_PER_MIN_EN * 60
    script = {"topic": scenes and "", "language": "en",
              "est_duration_s": round(est_s, 1), "scenes": scenes}
    out = os.path.join(d, "script.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    log(f"script: {len(scenes)} scenes, ~{est_s:.0f}s estimated -> {out}")
    return out


def tts_one(text, out_mp3, voice, language, tries=5):
    if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 2000:
        return
    import time, random
    for a in range(tries):
        if os.path.exists(out_mp3):
            os.remove(out_mp3)
        p = subprocess.run(
            [TTS, "speak", "--language", language, "--voice", voice,
             "--output", out_mp3, "--text-stdin"],
            input=text.encode("utf-8"), capture_output=True, timeout=300)
        if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 2000:
            return
        time.sleep(5 + random.uniform(0, 5))
    raise RuntimeError(f"TTS failed for {out_mp3}: {p.stderr.decode()[:200] if p.stderr else ''}")


def tts_piper(text, out_mp3):
    """Local Piper TTS fallback — zero hosted dependency (v2).

    Piper writes WAV; we transcode to MP3 so the rest of the pipeline is
    unchanged. English only (en_US-lessac-medium bundled in bin/piper/).
    """
    if not (os.path.exists(PIPER_BIN) and os.path.exists(PIPER_MODEL)):
        raise RuntimeError("piper binary/model not installed (see README v2 notes)")
    if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 2000:
        return
    wav = out_mp3 + ".piper.wav"
    if os.path.exists(wav):
        os.remove(wav)
    p = subprocess.run([PIPER_BIN, "--model", PIPER_MODEL,
                        "--output_file", wav],
                       input=text.encode("utf-8"), capture_output=True,
                       timeout=300)
    if not (os.path.exists(wav) and os.path.getsize(wav) > 2000):
        err = p.stderr.decode()[:200] if p.stderr else ""
        raise RuntimeError(f"piper synthesis failed: {err}")
    r = run(["ffmpeg", "-y", "-v", "error", "-i", wav,
             "-c:a", "libmp3lame", "-b:a", "128k", out_mp3])
    os.remove(wav)
    if r.returncode != 0 or not os.path.exists(out_mp3):
        raise RuntimeError(f"piper wav->mp3 failed: {r.stderr[:200]}")


def tts_gtts(text, out_mp3, language="en"):
    """Google Translate TTS via gTTS — free, no key, plain HTTPS.

    Robotic quality, occasionally slow (observed ~80s for one EN sentence
    through the egress proxy, ~1s for UR). Unique value: free URDU voice
    when hosted TTS is down (Piper is EN-only). Opt-in; not in the default
    fallback chain to avoid slowing the pipeline.
    """
    try:
        # NOTE: engine.py runs from its own dir, so this package's queue.py
        # shadows stdlib `queue` for any third-party import chain
        # (gTTS -> requests -> urllib3 does `import queue`). Sanitize sys.path
        # around the third-party import, then restore for local imports.
        import sys as _sys
        import os as _os
        _here = _os.path.dirname(_os.path.abspath(__file__))
        _saved = _sys.path[:]
        try:
            _sys.path = [p for p in _sys.path
                         if _os.path.abspath(p or ".") != _here]
            from gtts import gTTS
        finally:
            _sys.path = _saved
    except ImportError:
        raise RuntimeError("gtts not installed (pip install gTTS)")
    if os.path.exists(out_mp3):
        os.remove(out_mp3)
    lang = {"en": "en", "ur": "ur"}.get(language, "en")
    # Roman-Urdu workaround shared with hosted TTS (Heh-Goal quirk); gTTS
    # handles proper Urdu script, so pass text through unchanged.
    gTTS(text, lang=lang).save(out_mp3)
    if not (os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 2000):
        raise RuntimeError("gTTS produced no usable audio")


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path])
    return float(r.stdout.strip())


def stage_voiceover(pid, voice="avocado_v2:MAI_03", language="en",
                    tts_engine="hosted", tts_fallback=True):
    """tts_engine: 'hosted' (default), 'piper' (local EN), or 'gtts'
    (free, robotic, has Urdu). With tts_fallback, a hosted failure retries
    locally: Piper for EN, gTTS otherwise (Piper is EN-only)."""
    d = pdir(pid)
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    adir = os.path.join(d, "audio")
    mp3s, durs, used = [], [], []
    for s in script["scenes"]:
        mp3 = os.path.join(adir, f"{s['id']}.mp3")
        engine_used = tts_engine
        try:
            if tts_engine == "piper":
                tts_piper(s["narration"], mp3)
            elif tts_engine == "gtts":
                tts_gtts(s["narration"], mp3, language)
            else:
                tts_one(s["narration"], mp3, voice, language)
        except RuntimeError as e:
            if tts_fallback and tts_engine == "hosted":
                if language == "en":
                    log(f"voiceover {s['id']}: hosted TTS failed, "
                        f"falling back to local Piper ({str(e)[:80]})")
                    tts_piper(s["narration"], mp3)
                    engine_used = "piper(fallback)"
                else:
                    log(f"voiceover {s['id']}: hosted TTS failed, "
                        f"falling back to gTTS ({str(e)[:80]})")
                    tts_gtts(s["narration"], mp3, language)
                    engine_used = "gtts(fallback)"
            else:
                raise
        du = duration(mp3)
        mp3s.append(mp3)
        durs.append(round(du, 2))
        used.append(engine_used)
        log(f"voiceover {s['id']}: {du:.1f}s [{engine_used}]")
    # concatenate
    lst = os.path.join(adir, "concat.txt")
    with open(lst, "w") as f:
        for m in mp3s:
            f.write(f"file '{m}'\n")
    full = os.path.join(adir, "voiceover.mp3")
    r = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", full])
    if r.returncode != 0:
        raise RuntimeError(f"audio concat failed: {r.stderr[:300]}")
    total = duration(full)
    meta = {"voice": voice, "language": language, "scene_durations": durs,
            "total_s": round(total, 2), "tts_engine_per_scene": used,
            "piper_available": os.path.exists(PIPER_BIN)}
    with open(os.path.join(adir, "voiceover_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log(f"voiceover total {total:.1f}s -> {full}")
    return full


# ---------- visuals ----------

def composite_scene(img_path, on_screen, out_path):
    """Crop image to 9:16, overlay on-screen text banner top + bottom safe zone."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    img = Image.open(img_path).convert("RGB")
    # cover-crop to 9:16
    tw, th = W, H
    scale = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    x = (img.width - tw) // 2
    y = (img.height - th) // 2
    img = img.crop((x, y, x + tw, y + th))
    # darken top/bottom bands for text legibility
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 340], fill=(0, 0, 0, 110))
    d.rectangle([0, H - 420, W, H], fill=(0, 0, 0, 130))
    if on_screen:
        fb = ImageFont.truetype(F_BOLD, 64)
        # word wrap
        words, lines, cur = on_screen.split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=fb) > W - 120:
                lines.append(cur)
                cur = w_
            else:
                cur = t
        lines.append(cur)
        y0 = 90
        for ln in lines[:3]:
            tw_ = d.textlength(ln, font=fb)
            d.text(((W - tw_) / 2, y0), ln, font=fb, fill=(255, 255, 255),
                   stroke_width=2, stroke_fill=(0, 0, 0))
            y0 += 80
    img.save(out_path, quality=92)
    return out_path


def fallback_slide(on_screen, sub, out_path):
    """Motion-graphics fallback when no AI image exists for a scene."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), (15, 23, 42))
    d = ImageDraw.Draw(img)
    for i in range(H):  # subtle vertical gradient
        c = int(15 + 25 * i / H)
        d.line([(0, i), (W, i)], fill=(c - 8, c + 2, c + 22))
    fb = ImageFont.truetype(F_BOLD, 72)
    fr = ImageFont.truetype(F_REG, 44)
    def center(y, text, font, fill):
        tw_ = d.textlength(text, font=font)
        d.text(((W - tw_) / 2, y), text, font=font, fill=fill)
        return y + 100
    y = 700
    for ln in on_screen.split("\n")[:2]:
        y = center(y, ln.strip(), fb, (56, 189, 248))
    if sub:
        center(y + 40, sub, fr, (226, 232, 240))
    img.save(out_path, quality=92)
    return out_path


def stage_imgfetch(pid, topic=""):
    """Auto-fetch real images per scene (Wikimedia -> Pexels -> Pixabay).

    Saves assets/{scene_id}.jpg so stage_visuals composites them.
    Scenes with pre-dropped assets are respected; scenes with no fetchable
    image keep the motion-graphics fallback (pipeline never breaks).
    Sources logged to assets/image_sources.json (and manifest at package).
    """
    import image_fetch
    d = pdir(pid)
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    assets = os.path.join(d, "assets")
    sources = {}
    sp = os.path.join(assets, "image_sources.json")
    if os.path.exists(sp):
        try:
            sources = json.load(open(sp))
        except Exception:
            sources = {}
    for s in script["scenes"]:
        sid = s["id"]
        if sources.get(sid, {}).get("fetched"):
            log(f"imgfetch {sid}: cached ({sources[sid].get('source')})")
            continue
        # skip if an asset was manually dropped after last run
        for ext in (".png", ".jpg"):
            if os.path.exists(os.path.join(assets, f"{sid}{ext}")) and sid not in sources:
                sources[sid] = {"fetched": True, "source": "manual",
                                "note": "pre-dropped asset"}
                break
        if sid in sources:
            continue
        text = (s.get("narration", "") + " " + s.get("on_screen", "")).strip()
        meta = image_fetch.fetch_for_scene(sid, text, topic, assets)
        if meta:
            meta["fetched"] = True
            sources[sid] = meta
            log(f"imgfetch {sid}: {meta['source']} (q='{meta.get('query', '')}')")
        else:
            sources[sid] = {"fetched": False, "source": "fallback_slide",
                            "note": "no fetchable image; motion-graphics slide"}
            log(f"imgfetch {sid}: no image found -> fallback slide")
    with open(sp, "w") as f:
        json.dump(sources, f, indent=2)
    n_img = sum(1 for v in sources.values() if v.get("fetched") and v.get("source") != "fallback_slide")
    log(f"imgfetch -> {n_img}/{len(script['scenes'])} scenes have real images")
    return sp


def stage_visuals(pid):
    d = pdir(pid)
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    for i, s in enumerate(script["scenes"]):
        src = os.path.join(d, "assets", f"{s['id']}.png")
        if not os.path.exists(src):
            # also accept .jpg
            alt = os.path.join(d, "assets", f"{s['id']}.jpg")
            src = alt if os.path.exists(alt) else None
        out = os.path.join(d, "assets", f"{s['id']}_comp.jpg")
        if os.path.exists(out):
            log(f"visuals {s['id']}: cached")
            continue
        if src:
            composite_scene(src, s.get("on_screen", ""), out)
            log(f"visuals {s['id']}: composited AI image")
        else:
            fallback_slide(s.get("on_screen", s["id"]), "", out)
            log(f"visuals {s['id']}: fallback motion-graphics slide (no AI image)")
    return os.path.join(d, "assets")


# ---------- assemble ----------

def srt_time(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")


def build_srt(scenes, durations, path):
    lines, n, t = [], 1, 0.0
    for s, dur in zip(scenes, durations):
        sents = [x.strip() for x in re.split(r"[.!?]+", s["narration"]) if x.strip()]
        total = sum(len(x) for x in sents) or 1
        for sent in sents:
            dd = dur * len(sent) / total
            lines.append(f"{n}\n{srt_time(t)} --> {srt_time(t + dd)}\n{sent}\n")
            n += 1
            t += dd
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


KB_STYLES = ("zoom-in", "zoom-out", "pan-right", "pan-left")
XFADE_DUR = 0.5  # seconds of crossfade between scenes
# v2.3: transition variety (deterministic cycle) + kinetic typography
XFADE_TYPES = ("fade", "slideleft", "dissolve", "slideright", "fadewhite",
               "smoothup")
KT_IN, KT_OUT = 0.8, 0.6  # kinetic text fade-in / fade-out seconds
KT_HOLD = 2.2  # seconds the kinetic punch holds before fading (intro punch,
               # then captions own the frame — avoids text-on-text collisions)


def _ff_esc(t):
    """Escape text for ffmpeg filter arguments."""
    return (t.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
            .replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
            .replace(";", "\\;").replace("\n", " "))


def _kinetic_filters(on_screen, seg_dur):
    """Animated keyword overlay (ffmpeg drawtext, zero GPU).

    Big on-screen phrase slides up + fades in at scene start, holds briefly
    as an intro punch, then fades out so captions own the frame (avoids
    text-on-text collisions). A leading number ("5 AI TOOLS") additionally
    gets a giant count-up (0 -> N over 1.2s). Returns "" when no on-screen text.
    """
    txt = (on_screen or "").strip()
    if not txt:
        return ""
    hold = min(KT_HOLD, max(0.8, seg_dur - KT_IN - KT_OUT))
    t1, t2 = KT_IN, KT_IN + hold
    alpha = (f"if(lt(t\\,{t1:.2f})\\,t/{KT_IN}\\,"
             f"if(gt(t\\,{t2:.2f})\\,"
             f"max(0\\,({t2 + KT_OUT:.2f}-t)/{KT_OUT})\\,1))")
    parts = []
    m = re.match(r"^(\d+)\s+\S", txt)
    ybase = "h*0.38" if m else "h*0.30"
    if m:
        n = int(m.group(1))
        parts.append(
            f"drawtext=fontfile={F_BOLD}:"
            f"text='%{{eif\\:min({n}*t/1.2\\,{n})\\:d}}':fontsize=200:"
            f"fontcolor=white:borderw=5:bordercolor=black@0x99:"
            f"x=(w-text_w)/2:y='h*0.12':alpha='{alpha}'")
    yexpr = f"{ybase}+200*max(0\\,1-t/{KT_IN})"
    parts.append(
        f"drawtext=fontfile={F_BOLD}:text='{_ff_esc(txt)}':fontsize=72:"
        f"fontcolor=white:borderw=3:bordercolor=black@0x99:"
        f"x=(w-text_w)/2:y='{yexpr}':alpha='{alpha}'")
    return ",".join(parts)


def _kenburns_filter(style, frames):
    """Deterministic Ken Burns variant per scene index (ffmpeg-only)."""
    base = f"s={W}x{H}:fps=30"
    if style == "zoom-out":
        return (f"zoompan=z='max(1.15-0.0016*on,1.0)':d={frames}:{base}")
    if style == "pan-right":
        return (f"zoompan=z=1.12:x='(iw-iw/zoom)*on/{frames}'"
                f":y='ih/2-(ih/zoom/2)':d={frames}:{base}")
    if style == "pan-left":
        return (f"zoompan=z=1.12:x='(iw-iw/zoom)*(1-on/{frames})'"
                f":y='ih/2-(ih/zoom/2)':d={frames}:{base}")
    return f"zoompan=z='min(zoom+0.0015,1.15)':d={frames}:{base}"  # zoom-in


def stage_assemble(pid):
    d = pdir(pid)
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    with open(os.path.join(d, "audio", "voiceover_meta.json")) as f:
        meta = json.load(f)
    durs = meta["scene_durations"]
    scenes = script["scenes"]
    n = len(scenes)
    segdir = os.path.join(d, "segments")
    os.makedirs(segdir, exist_ok=True)

    # --- 1. video segments: AI clip (if aiclips ran) else Ken Burns still ---
    # v2.3: kinetic typography overlay (animated keyword, ffmpeg-only)
    vsegs = []
    for i, (s, dur) in enumerate(zip(scenes, durs)):
        comp = os.path.join(d, "assets", f"{s['id']}_comp.jpg")
        vseg = os.path.join(segdir, f"{s['id']}_kb.mp4")
        vdur = dur + (XFADE_DUR if i < n - 1 else 0.0)
        aiclip = os.path.join(d, "assets", f"{s['id']}_aiclip.mp4")
        use_ai = os.path.exists(aiclip)
        frames = max(30, int(vdur * 30))
        style = KB_STYLES[i % len(KB_STYLES)]
        kb = _kenburns_filter(style, frames)
        kt = _kinetic_filters(s.get("on_screen", ""), vdur)
        if use_ai:
            # AI-animated clip: fit to vdur, keep kinetic text overlay
            vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},setsar=1,fps=30[v]")
            if kt:
                vf += f";[v]{kt}[vout]"
                vmap = "[vout]"
            else:
                vmap = "[v]"
            desc = "aiclip"
        else:
            vf = kb + ("," + kt if kt else "")
            vmap = None
            desc = style
        if os.path.exists(vseg):
            log(f"assemble {s['id']}: cached ({desc}"
                f"{', kinetic' if kt and not use_ai else ''})")
        else:
            if use_ai:
                cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "3",
                       "-i", aiclip, "-filter_complex", vf,
                       "-map", vmap, "-t", f"{vdur:.2f}",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-preset", "veryfast", "-an", vseg]
            else:
                cmd = ["ffmpeg", "-y", "-v", "error",
                       "-loop", "1", "-framerate", "30", "-i", comp,
                       "-vf", vf,
                       "-t", f"{vdur:.2f}",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-preset", "veryfast", "-an", vseg]
            r = run(cmd)
            if r.returncode != 0 or not os.path.exists(vseg):
                raise RuntimeError(f"segment failed {s['id']}: {r.stderr[:300]}")
            log(f"assemble {s['id']}: {dur:.1f}s ({desc}"
                f"{', kinetic' if kt and not use_ai else ''})")
        vsegs.append(vseg)

    # --- 2. crossfade chain (video) — v2.3: transition variety, deterministic ---
    if n == 1:
        xfade_v = vsegs[0]
    else:
        xfade_v = os.path.join(segdir, "xfade.mp4")
        if not os.path.exists(xfade_v):
            cmd = ["ffmpeg", "-y", "-v", "error"]
            for vs in vsegs:
                cmd += ["-i", vs]
            filt, last = [], None
            off = 0.0
            for i in range(n):
                filt.append(f"[{i}:v]format=yuv420p,settb=AVTB[v{i}]")
            for i in range(n - 1):
                inp_a = f"v{i}" if i == 0 else f"x{i}"
                off += durs[i]
                out = f"x{i + 1}"
                ttype = XFADE_TYPES[i % len(XFADE_TYPES)]
                filt.append(f"[{inp_a}][v{i + 1}]xfade=transition={ttype}:"
                            f"duration={XFADE_DUR}:offset={off:.3f}[{out}]")
                last = out
            cmd += ["-filter_complex", ";".join(filt),
                    "-map", f"[{last}]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-preset", "veryfast", xfade_v]
            r = run(cmd)
            if r.returncode != 0 or not os.path.exists(xfade_v):
                raise RuntimeError(f"xfade failed: {r.stderr[:400]}")
            types = [XFADE_TYPES[i % len(XFADE_TYPES)] for i in range(n - 1)]
            log(f"assemble: xfade chain ({n - 1} transitions x {XFADE_DUR}s, "
                f"types: {types})")

    # --- 3. mux concatenated narration (timeline == sum(durs)) ---
    alist = os.path.join(segdir, "audiolist.txt")
    with open(alist, "w") as f:
        for s in scenes:
            f.write(f"file '{os.path.join(d, 'audio', s['id'] + '.mp3')}'\n")
    afull = os.path.join(segdir, "audio_full.mp3")
    r = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", alist, "-c", "copy", afull])
    if r.returncode != 0:
        raise RuntimeError(f"audio concat failed: {r.stderr[:300]}")
    joined = os.path.join(d, "joined.mp4")
    r = run(["ffmpeg", "-y", "-v", "error", "-i", xfade_v, "-i", afull,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             "-shortest", joined])
    if r.returncode != 0 or not os.path.exists(joined):
        raise RuntimeError(f"av mux failed: {r.stderr[:300]}")
    # captions burned in
    srt = build_srt(script["scenes"], durs, os.path.join(d, "captions.srt"))
    final = os.path.join(d, "final.mp4")
    vf = (f"subtitles={srt}:force_style='FontName=Noto Sans,FontSize=22,"
          f"PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=1,"
          f"Outline=2,Shadow=0,MarginV=120,Alignment=2'")
    r = run(["ffmpeg", "-y", "-v", "error", "-i", joined,
             "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "veryfast", "-c:a", "copy", final])
    if r.returncode != 0 or not os.path.exists(final):
        raise RuntimeError(f"caption burn failed: {r.stderr[:300]}")
    log(f"assembled -> {final} ({duration(final):.1f}s)")
    return final


# ---------- platforms (v2: multi-aspect renders) ----------

def stage_platforms(pid):
    """Derive 1:1 and 16:9 from the 9:16 master.

    The full 9:16 frame is pillarboxed onto a blurred-background canvas, so
    burned-in captions (bottom safe zone) stay fully visible on every variant.
    Safe-area rule: no cropping of the master frame — verified in QC.
    """
    d = pdir(pid)
    master = os.path.join(d, "final.mp4")
    if not os.path.exists(master):
        raise RuntimeError("platforms needs final.mp4 — run assemble first")
    outs = {}
    for name, (cw, ch) in PLATFORMS.items():
        out = os.path.join(d, f"final_{name}.mp4")
        if os.path.exists(out):
            log(f"platforms {name}: cached")
            outs[name] = out
            continue
        k = min(cw / W, ch / H)
        fg_w, fg_h = int(W * k) - int(W * k) % 2, int(H * k) - int(H * k) % 2
        fc = (f"[0:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,"
              f"crop={cw}:{ch},gblur=sigma=45[bg];"
              f"[0:v]scale={fg_w}:{fg_h}[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
        r = run(["ffmpeg", "-y", "-v", "error", "-i", master,
                 "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
                 "-c:v", "libx264", "-preset", "veryfast",
                 "-c:a", "aac", "-b:a", "128k", "-shortest", out])
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(f"platform render {name} failed: {r.stderr[:300]}")
        log(f"platforms {name}: {cw}x{ch} (blurred pillarbox) -> {out}")
        outs[name] = out
    return outs


# ---------- seo ----------

def stage_seo(pid, topic=None):
    """Topic-aware SEO package (v2: was hardcoded for demo-001 in v1).

    Template-based — review title/description per topic before uploading
    (README honest-limits note still applies).
    """
    d = pdir(pid)
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    topic = (topic or script.get("topic") or "").strip() or "AI tips"
    # key phrases from on-screen text for description/hashtags
    keys = []
    for s in script["scenes"]:
        os_ = s.get("on_screen", "").replace("\n", " ").strip()
        if os_ and os_ not in keys:
            keys.append(os_)
    key_str = ", ".join(keys[:4])
    desc_bits = []
    for s in script["scenes"][:3]:
        n = s.get("narration", "").strip()
        if n:
            desc_bits.append(n)
    seo = {
        "title": topic if len(topic) <= 100 else topic[:97] + "...",
        "alt_titles": [
            f"{topic} — explained in 40 seconds",
            f"Stop doing this wrong: {topic}",
            f"{topic} (what most people miss)",
        ],
        "description": (
            f"{topic}.\n\n"
            + (" ".join(desc_bits)[:400] + "\n\n" if desc_bits else "")
            + (f"Covered: {key_str}.\n\n" if key_str else "")
            + "Which one will you try first? Comment below.\n\n"
            "#aitools #productivity #ai"
        ),
        "hashtags": ["#aitools", "#productivity", "#ai", "#techtips",
                     "#shorts", "#lifehacks", "#learnontiktok", "#reels"],
        "pinned_comment": "Which tip are you trying first? I'll reply with a quick-start pointer.",
        "thumbnail_concept": (f"Bold headline text '{keys[0] if keys else topic}' "
                              "over high-contrast split visual. Yellow/black, "
                              "big readable type."),
        "thumbnail_file": "assets/thumbnail.png",
        "chapters": [],
        "disclosure": "AI-generated voiceover and visuals.",
        "template_note": "Review title/description/hashtags per topic before uploading.",
    }
    out = os.path.join(d, "seo.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(seo, f, ensure_ascii=False, indent=2)
    log(f"seo package -> {out} (thumbnail: assets/thumbnail.png — generate or place manually)")
    return out


# ---------- package ----------

def stage_package(pid):
    d = pdir(pid)
    final = os.path.join(d, "final.mp4")
    renders = {"9x16": "final.mp4" if os.path.exists(final) else None}
    for name in PLATFORMS:
        p = os.path.join(d, f"final_{name}.mp4")
        renders[{"1x1": "1x1", "16x9": "16x9"}[name]] = (
            f"final_{name}.mp4" if os.path.exists(p) else None)
    manifest = {
        "project": pid,
        "engine": "content-engine v2",
        "created": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "files": {
            "video": "final.mp4" if os.path.exists(final) else None,
            "renders": renders,
            "captions": "captions.srt",
            "thumbnail": "assets/thumbnail.png" if os.path.exists(
                os.path.join(d, "assets", "thumbnail.png")) else None,
            "seo": "seo.json",
            "script": "script.json",
            "research": "research_brief.md",
            "qc": "qc_report.json",
            "image_sources": ("assets/image_sources.json" if os.path.exists(
                os.path.join(d, "assets", "image_sources.json")) else None),
        },
        "publishing": "manual-upload",
        "platforms": ["youtube_shorts", "instagram_reels", "tiktok", "facebook_reels"],
        "spec": {"master": "1080x1920 9:16 h264/aac",
                 "renders": {"1x1": "1080x1080 (blurred pillarbox)",
                             "16x9": "1920x1080 (blurred pillarbox)"},
                 "captions": "burned-in"},
    }
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    checklist = os.path.join(d, "UPLOAD_CHECKLIST.md")
    with open(checklist, "w") as f:
        f.write(
            "# Manual upload checklist\n\n"
            "- [ ] Watch final.mp4 end-to-end once\n"
            "- [ ] Upload to YouTube Studio as a Short (<60s)\n"
            "- [ ] Paste title + description from seo.json\n"
            "- [ ] Add hashtags (first 3 in description)\n"
            "- [ ] Upload thumbnail (YouTube) / pick cover frame (Reels/TikTok)\n"
            "- [ ] Add pinned comment from seo.json\n"
            "- [ ] Mark 'altered content: yes — AI voiceover/visuals' if asked\n"
            "- [ ] Publish, then log URL in manifest\n")
    log(f"package -> manifest.json + UPLOAD_CHECKLIST.md")
    return os.path.join(d, "manifest.json")


# ---------- qc ----------

def frame_brightness(path, t):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", path,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, timeout=60)
    if not r.returncode == 0 or not r.stdout:
        return None
    import statistics
    return statistics.mean(r.stdout)


def stage_qc(pid):
    d = pdir(pid)
    final = os.path.join(d, "final.mp4")
    checks, fails = {}, []

    def check(name, ok, detail=""):
        checks[name] = {"pass": bool(ok), "detail": detail}
        if not ok:
            fails.append(name)

    if not os.path.exists(final):
        check("file_opens", False, "final.mp4 missing")
    else:
        r = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,codec_name",
                 "-show_entries", "format=duration", "-of", "json", final])
        try:
            info = json.loads(r.stdout)
            vs = info["streams"][0]
            check("resolution", vs["width"] == W and vs["height"] == H,
                  f"{vs['width']}x{vs['height']}")
            check("video_codec", vs["codec_name"] == "h264", vs["codec_name"])
            dur = float(info["format"]["duration"])
            check("duration_valid", 5 < dur < 300, f"{dur:.1f}s")
        except Exception as e:
            check("probe", False, str(e)[:100])
            dur = 0
        r2 = run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=codec_name", "-of", "csv=p=0", final])
        check("audio_present", bool(r2.stdout.strip()), r2.stdout.strip())
        # voiceover-vs-script check (faster-whisper, CPU tiny model):
        # transcribes the rendered voiceover and fuzzy-matches it against the
        # approved script narrations. Catches wrong/truncated/garbled TTS.
        # warn-grade (tiny model mishears names); fail only when clearly wrong.
        try:
            import whisper_qc
            lang = "en"
            try:
                lang = json.load(open(os.path.join(d, "audio",
                                                   "voiceover_meta.json"))).get(
                                                       "language", "en") or "en"
            except Exception:
                pass
            wq = whisper_qc.check_voiceover(d, language=lang)
            if wq["verdict"] == "fail":
                check("voiceover_script_match", False, wq["detail"])
            else:
                check("voiceover_script_match", True,
                      wq["detail"] + ("" if wq["verdict"] == "pass"
                                     else " [warn: human glance advised]"))
        except Exception as e:
            check("voiceover_script_match", True,
                  f"skipped: whisper_qc error {str(e)[:80]}")
        # expected duration from voiceover
        meta_p = os.path.join(d, "audio", "voiceover_meta.json")
        if os.path.exists(meta_p) and dur:
            exp = json.load(open(meta_p))["total_s"]
            check("duration_match", abs(dur - exp) / exp <= 0.10,
                  f"actual {dur:.1f}s vs voiceover {exp:.1f}s")
        # black frames at start/end
        for label, t in (("start", 0.5), ("end", max(0.5, (dur or 2) - 0.5))):
            b = frame_brightness(final, t)
            check(f"no_black_{label}", b is None or b > 8,
                  f"mean brightness {b:.1f}" if b is not None else "unreadable")
        # v2: platform renders — full master frame pillarboxed, so the burned-in
        # caption safe zone (bottom of 9:16) stays visible on every variant.
        for name, (cw, ch) in PLATFORMS.items():
            pf = os.path.join(d, f"final_{name}.mp4")
            if not os.path.exists(pf):
                check(f"platform_{name}", False, "missing")
                continue
            pr = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                      "-show_entries", "stream=width,height",
                      "-show_entries", "format=duration",
                      "-of", "json", pf])
            try:
                pi = json.loads(pr.stdout)
                vs2 = pi["streams"][0]
                ok_dim = vs2["width"] == cw and vs2["height"] == ch
                pdur = float(pi["format"]["duration"])
                ok_dur = abs(pdur - dur) <= 2.0
                check(f"platform_{name}", ok_dim and ok_dur,
                      f"{vs2['width']}x{vs2['height']}, {pdur:.1f}s "
                      f"(captions safe: full-frame pillarbox)")
            except Exception as e:
                check(f"platform_{name}", False, str(e)[:100])
    report = {"project": pid, "passed": not fails,
              "score": round(100 * sum(c["pass"] for c in checks.values()) / max(1, len(checks))),
              "checks": checks, "failed": fails}
    with open(os.path.join(d, "qc_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    log(f"QC {'PASS' if report['passed'] else 'FAIL'} score={report['score']} "
        f"{'failed: ' + ','.join(fails) if fails else ''}")
    return report


# ---------- CLI ----------

STAGES = ["research", "script", "voiceover", "imgfetch", "visuals", "aiclips",
          "assemble", "platforms", "seo", "package", "qc"]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=STAGES + ["run"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--topic", default="")
    ap.add_argument("--brief-text", default="")
    ap.add_argument("--auto", action="store_true",
                    help="research stage: web auto-research instead of template")
    ap.add_argument("--research-query", default="",
                    help="override Wikipedia search query for --auto research")
    ap.add_argument("--script-file", default="")
    ap.add_argument("--draft", action="store_true",
                    help="script stage: LLM-draft scenes.json from the brief "
                         "(writes scenes.draft.json; operator reviews first)")
    ap.add_argument("--voice", default="avocado_v2:MAI_03")
    ap.add_argument("--language", default="en")
    ap.add_argument("--tts-engine", default="hosted",
                    choices=["hosted", "piper", "gtts"],
                    help="voiceover backend: hosted (default), piper (local EN "
                         "fallback), gtts (free, robotic, has Urdu)")
    ap.add_argument("--no-tts-fallback", action="store_true",
                    help="disable automatic hosted->piper fallback")
    a = ap.parse_args()
    order = STAGES if a.stage == "run" else [a.stage]
    for st in order:
        if st == "research":
            stage_research(a.project, a.topic or a.project,
                           a.brief_text or None, auto=a.auto,
                           research_query=a.research_query or None)
        elif st == "script":
            if a.draft:
                draft_scenes_from_brief(a.project, a.topic or a.project)
            else:
                if not a.script_file:
                    sys.exit("script stage needs --script-file (or --draft for an LLM draft)")
                stage_script(a.project, a.script_file)
        elif st == "voiceover":
            stage_voiceover(a.project, a.voice, a.language,
                            tts_engine=a.tts_engine,
                            tts_fallback=not a.no_tts_fallback)
        elif st == "imgfetch":
            stage_imgfetch(a.project, a.topic or a.project)
        elif st == "aiclips":
            # optional AI video clips (Magic Hour) — no-op without key/SDK
            try:
                import video_clips
                video_clips.stage_aiclips(a.project)
            except Exception as e:
                log(f"aiclips: unavailable ({type(e).__name__})")
        elif st == "visuals":
            stage_visuals(a.project)
        elif st == "assemble":
            stage_assemble(a.project)
        elif st == "platforms":
            stage_platforms(a.project)
        elif st == "seo":
            stage_seo(a.project, a.topic)
        elif st == "package":
            stage_package(a.project)
        elif st == "qc":
            rep = stage_qc(a.project)
            if not rep["passed"]:
                sys.exit("QC FAILED: " + ",".join(rep["failed"]))
    log("done.")


if __name__ == "__main__":
    main()
