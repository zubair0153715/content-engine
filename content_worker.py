#!/usr/bin/env python3
"""Content Engine app VM worker — bridges the FastAPI container and the local engine.

The container (FastAPI Cloud) and this VM do NOT share a filesystem, so this
worker talks to the container over HTTPS using the worker bridge endpoints.

Usage:
    content_worker.py autoqueue   # ask container to queue weekly auto-videos
    content_worker.py poll        # claim oldest queued video, render it, upload results

Only ONE render runs at a time (lock file) — the VM has ~834MB free RAM.

Worker key lives in ~/workspace/content-engine/.worker_key (0600) and must
match the CONTENT_WORKER_KEY secret env var on the FastAPI app.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Belt-and-braces: never route container traffic through the egress proxy.
for _v in ("NO_PROXY", "no_proxy"):
    _cur = os.environ.get(_v, "")
    _need = "localhost,127.0.0.1"
    if _need not in _cur:
        os.environ[_v] = (_cur + "," + _need).strip(",")

BASE = os.path.expanduser("~/workspace/content-engine")
WORK = os.path.join(BASE, "saas_work")
KEY_FILE = os.path.join(BASE, ".content_worker_key")
LOCK_FILE = os.path.join(BASE, ".content_worker.lock")
LIVE = "https://clinic-demo.fastapicloud.dev"

STAGE_TIMEOUTS = {
    "research": 180, "script": 120, "voiceover": 900, "visuals": 300,
    "assemble": 900, "platforms": 600, "seo": 120, "package": 120, "qc": 180,
}

UPLOAD_FILES = ["final.mp4", "final_1x1.mp4", "final_16x9.mp4", "seo.json",
                "manifest.json", "qc_report.json", "thumbnail.png", "captions.srt",
                "UPLOAD_CHECKLIST.md"]


def key():
    with open(KEY_FILE) as f:
        return f.read().strip()


def api(method, path, data=None, headers=None, timeout=120, retries=3):
    last = None
    for i in range(retries):
        req = urllib.request.Request(
            LIVE + path, data=data,
            headers={"X-Worker-Key": key(),
                     "User-Agent": "ContentWorker/1.0 (urllib)",
                     **(headers or {})},
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and i < retries - 1:
                last = e
                time.sleep(3 * (i + 1))
                continue
            raise RuntimeError(f"bridge {method} {path} -> HTTP {e.code}")
        except Exception as e:
            # transient urllib quirk on container wake (RemoteDisconnected etc.)
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"bridge {method} {path} failed after {retries} tries: {last}")


def mark(vid, status, stage="", error=""):
    api("POST", f"/content/api/worker/jobs/{vid}/status",
        data=json.dumps({"status": status, "stage": stage, "error": error}).encode(),
        headers={"Content-Type": "application/json"})


def run_stage(pid, stage, args=()):
    cmd = [sys.executable, "engine.py", stage, "--project", pid, *args]
    print(f"[stage:{stage}] {' '.join(cmd)}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                           timeout=STAGE_TIMEOUTS.get(stage, 300))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"stage {stage} timed out after {STAGE_TIMEOUTS.get(stage, 300)}s")
    tail = (p.stdout + p.stderr)[-1500:]
    print(tail, flush=True)
    if p.returncode != 0:
        raise RuntimeError(f"stage {stage} failed (exit {p.returncode}): {tail[-500:]}")
    return tail


def build_scenes_from_brief(pid, topic, brand):
    """Template scriptwriter (no LLM on the VM): hook + 3 facts + CTA."""
    brief_p = os.path.join(BASE, "projects", pid, "research_brief.md")
    with open(brief_p, encoding="utf-8") as f:
        text = f.read()
    facts = []
    in_facts = False
    for line in text.splitlines():
        if line.startswith("## Facts"):
            in_facts = True
            continue
        if in_facts:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                fact = re.sub(r"\s*\[Source:.*?\]\s*$", "", line[2:]).strip()
                if len(fact) > 40:
                    facts.append(fact)
    topic_cap = topic[:1].upper() + topic[1:] if topic else "This"
    scenes = []
    scenes.append({
        "id": "scene1",
        "narration": f"Stop scrolling. {topic_cap} — here are the facts that actually matter.",
        "on_screen": " ".join(topic.split()[:3]).upper() or "WATCH THIS",
    })
    for i, fact in enumerate(facts[:3]):
        nar = fact if len(fact) <= 220 else fact[:217].rsplit(" ", 1)[0] + "..."
        words = re.sub(r"[^A-Za-z0-9 ]", "", fact).split()
        scenes.append({
            "id": f"scene{i + 2}",
            "narration": nar,
            "on_screen": " ".join(words[:4]).upper(),
        })
    cta = f"Follow {brand} for more." if brand else "Follow for more breakdowns like this."
    scenes.append({"id": f"scene{len(scenes) + 1}", "narration": cta, "on_screen": "FOLLOW"})
    out = os.path.join(BASE, "projects", pid, "scenes.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    total = sum(len(s["narration"]) for s in scenes)
    print(f"[script] template scenes -> {out} ({len(scenes)} scenes, ~{total} chars)")
    return out


def upload_results(vid, pid):
    """Multipart upload of result files to the container."""
    pdir = os.path.join(BASE, "projects", pid)
    candidates = []
    for name in UPLOAD_FILES:
        p = os.path.join(pdir, name)
        if not os.path.exists(p) and name == "thumbnail.png":
            p = os.path.join(pdir, "assets", name)
        if os.path.exists(p):
            candidates.append((name, p))
    boundary = "----SaaSWorkerBoundary1234"
    body = b""
    for name, path in candidates:
        with open(path, "rb") as f:
            data = f.read()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        body += data + b"\r\n"
    meta = json.dumps({"files": [n for n, _ in candidates], "uploaded_at": time.time()})
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"meta\"\r\n\r\n"
             f"{meta}\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        LIVE + f"/content/api/worker/result/{vid}", data=body,
        headers={"X-Worker-Key": key(),
                 "User-Agent": "ContentWorker/1.0 (urllib)",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"result upload -> HTTP {e.code}")


def cmd_autoqueue():
    r = api("POST", "/content/api/worker/autoqueue", data=b"",
            headers={"Content-Type": "application/json"})
    print(json.dumps(r))
    return 0


def script_has_urdu(pid):
    """True when the script actually contains Urdu-script text.

    Honest v1 limit: the template script writer produces ENGLISH narration.
    Passing --language ur on English text makes the Urdu TTS mangle it, and
    the whisper QC (rightly) fails the voiceover/script match. So Urdu
    narration is only requested when the script really is Urdu-script
    (e.g. an LLM-drafted script), otherwise English narration is used.
    """
    try:
        with open(os.path.join(BASE, "projects", pid, "scenes.json"),
                  encoding="utf-8") as f:
            txt = f.read()
        return any("\u0600" <= ch <= "\u06FF" for ch in txt)
    except Exception:
        return False


def _locked():
    try:
        with open(LOCK_FILE) as f:
            ts = float(f.read().strip().split()[0])
        if time.time() - ts < 50 * 60:
            return True
    except Exception:
        pass
    with open(LOCK_FILE, "w") as f:
        f.write(f"{time.time()} {os.getpid()}")
    return False


def _unlock():
    try:
        os.unlink(LOCK_FILE)
    except Exception:
        pass


def cmd_poll():
    if _locked():
        print(json.dumps({"skipped": "another render in progress"}))
        return 0
    try:
        r = api("GET", "/content/api/worker/next")
        job = r.get("job")
        if not job:
            print(json.dumps({"none": True}))
            return 0
        vid = job["id"]
        topic = job.get("topic") or ""
        s = job.get("settings") or {}
        niche = s.get("niche") or job.get("niche") or ""
        language = s.get("language") or "en"
        voice = s.get("voice") or ""
        brand = ""
        eff_topic = topic if topic and topic != "auto" else (niche or "AI tools")
        pid = "saas_" + vid[:8]
        os.makedirs(os.path.join(WORK, vid), exist_ok=True)
        try:
            mark(vid, "working", "research")
            # Research the TOPIC itself; the niche only feeds auto-picks at
            # queue time. (Passing the niche as research-query once made the
            # engine research "dental clicks" instead of "dental implants".)
            run_stage(pid, "research", ["--topic", eff_topic, "--auto"])

            mark(vid, "working", "script")
            scenes = build_scenes_from_brief(pid, eff_topic, brand)
            run_stage(pid, "script", ["--script-file", scenes])

            # narration language follows the SCRIPT, not the setting alone
            want_lang = language
            if not script_has_urdu(pid):
                if want_lang != "en":
                    print(f"[lang] script is English — using English narration "
                          f"(setting was {want_lang})", flush=True)
                language = "en"

            mark(vid, "working", "voiceover")
            vargs = []
            if language:
                vargs += ["--language", language]
            if voice:
                vargs += ["--voice", voice]
            run_stage(pid, "voiceover", vargs)

            for st in ("imgfetch", "visuals", "aiclips", "assemble", "platforms"):
                mark(vid, "working", st)
                run_stage(pid, st)

            mark(vid, "working", "seo")
            run_stage(pid, "seo", ["--topic", eff_topic])
            mark(vid, "working", "package")
            run_stage(pid, "package")
            mark(vid, "working", "qc")
            run_stage(pid, "qc")

            qc_p = os.path.join(BASE, "projects", pid, "qc_report.json")
            score = None
            try:
                score = json.load(open(qc_p)).get("score")
            except Exception:
                pass
            print(json.dumps({"jobid": vid, "qc_score": score}))

            mark(vid, "working", "upload")
            up = upload_results(vid, pid)
            print(json.dumps({"uploaded": up}))
            # container marks ready_for_approval on result receipt
            return 0
        except Exception as e:
            err = str(e)[:1000]
            print(f"[failed] {err}", flush=True)
            try:
                mark(vid, "failed", "render", err)
            except Exception:
                pass
            return 1
    finally:
        _unlock()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("autoqueue", "poll"):
        print("usage: content_worker.py [autoqueue|poll]")
        return 2
    if not os.path.exists(KEY_FILE):
        print("missing worker key:", KEY_FILE)
        return 2
    return cmd_autoqueue() if sys.argv[1] == "autoqueue" else cmd_poll()


if __name__ == "__main__":
    sys.exit(main())
