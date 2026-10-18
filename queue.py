#!/usr/bin/env python3
"""Task queue + scheduler — Content Engine v2 (master doc stages J/N).

Doc states: received → planning → researching → scriptwriting →
awaiting_approval → generating_media → editing → quality_checking →
ready_for_publishing → (scheduled) → published. Terminal: failed, cancelled.

The queue automates what it can. Script authoring stays human: a task that
reaches scriptwriting without a scenes.json parks at awaiting_approval until
an operator runs `queue.py approve <id> --script-file ...`. Engine stages are
cached/resumable, so retries never redo finished work.

Retry: stage failure → attempts++, exponential backoff
(30s * 2^attempts, capped 10 min) via next_retry_at; failed after 3.

Usage:
    python3 queue.py add --topic "text" [--priority 1-5] [--voice ID] [--language en]
    python3 queue.py list [--state X]
    python3 queue.py show <id>
    python3 queue.py approve <id> [--script-file scenes.json]
    python3 queue.py run-once            # process one actionable task
    python3 queue.py retry <id>
    python3 queue.py cancel <id>
    python3 queue.py mark-published <id> --url https://...
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

BASE = os.path.expanduser("~/workspace/content-engine")
PROJECTS = os.path.join(BASE, "projects")
QPATH = os.path.join(BASE, "queue.json")
ENGINE = os.path.join(BASE, "engine.py")
MAX_ATTEMPTS = 3

STATES = ["received", "planning", "researching", "scriptwriting",
          "awaiting_approval", "generating_media", "editing",
          "quality_checking", "ready_for_publishing", "scheduled",
          "published", "failed", "cancelled"]
TERMINAL = {"published", "failed", "cancelled"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load():
    if os.path.exists(QPATH):
        with open(QPATH, encoding="utf-8") as f:
            return json.load(f)
    return {"tasks": []}


def save(q):
    tmp = QPATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2)
    os.replace(tmp, QPATH)


def get(q, tid):
    for t in q["tasks"]:
        if t["id"] == tid:
            return t
    sys.exit(f"no task {tid}")


def new_id(q):
    n = len(q["tasks"]) + 1
    return f"T{n:03d}"


def add_task(topic, priority=3, voice="avocado_v2:MAI_03", language="en",
             tts_engine="hosted", research_query="", script_file=""):
    q = load()
    tid = new_id(q)
    project = "q-" + "".join(c if c.isalnum() else "-" for c in topic.lower())[:30].strip("-") or tid.lower()
    # avoid collisions
    existing = {t["project"] for t in q["tasks"]}
    suffix, base = 2, project
    while project in existing:
        project = f"{base}-{suffix}"
        suffix += 1
    if script_file and not os.path.exists(script_file):
        sys.exit(f"script file not found: {script_file}")
    q["tasks"].append({
        "id": tid, "topic": topic, "project": project,
        "priority": max(1, min(5, priority)),
        "state": "received", "approved": False,
        "script_file": os.path.abspath(script_file) if script_file else None,
        "attempts": 0, "max_attempts": MAX_ATTEMPTS, "next_retry_at": None,
        "error": None, "published_url": None,
        "config": {"voice": voice, "language": language,
                   "tts_engine": tts_engine, "research_query": research_query},
        "history": [{"at": now(), "state": "received"}],
        "created": now(), "updated": now(),
    })
    save(q)
    print(f"[queue] added {tid} (project {project}, priority {priority})")
    return tid


def set_state(t, state, note=""):
    t["state"] = state
    t["updated"] = now()
    t["history"].append({"at": now(), "state": state, "note": note})


def engine_run(project, stage_args):
    """Run engine.py stages; returns (ok, stderr_tail)."""
    cmd = [sys.executable, ENGINE] + stage_args
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                       cwd=BASE)
    tail = (p.stderr or p.stdout or "")[-500:]
    return p.returncode == 0, tail


def actionable(q):
    ts = [t for t in q["tasks"]
          if t["state"] not in TERMINAL
          and (not t["next_retry_at"] or t["next_retry_at"] <= now())]
    # priority desc, then oldest first
    ts.sort(key=lambda t: (-t["priority"], t["created"]))
    return ts


def process(t):
    """Advance one task as far as possible. Returns True if it moved."""
    cfg = t["config"]
    proj, topic = t["project"], t["topic"]
    moved = False

    def stage(name, args):
        ok, tail = engine_run(proj, args)
        if not ok:
            raise RuntimeError(f"engine {name} failed: {tail[-200:]}")
        return True

    try:
        if t["state"] == "received":
            set_state(t, "planning", "topic validated")
            moved = True
        if t["state"] == "planning":
            set_state(t, "researching")
            rargs = ["research", "--project", proj, "--topic", topic, "--auto"]
            if cfg.get("research_query"):
                rargs += ["--research-query", cfg["research_query"]]
            stage("research", rargs)
            set_state(t, "scriptwriting", "brief ready")
            moved = True
        if t["state"] == "scriptwriting":
            if not t["script_file"] or not os.path.exists(t["script_file"]):
                # v2: LLM-draft scenes, then park for operator approval
                ok, tail = engine_run(
                    proj, ["script", "--project", proj, "--topic", topic,
                           "--draft"])
                draft = os.path.join(PROJECTS, proj, "scenes.draft.json")
                if ok and os.path.exists(draft):
                    set_state(t, "awaiting_approval",
                              f"LLM draft ready: {draft} — review, then: "
                              f"queue.py approve {t['id']} --script-file {draft}")
                else:
                    set_state(t, "awaiting_approval",
                              "LLM draft unavailable "
                              f"({tail[-120:]}); write scenes.json manually, then: "
                              f"queue.py approve {t['id']} --script-file <path>")
                return True  # parked, not an error
            stage("script", ["script", "--project", proj,
                             "--script-file", t["script_file"]])
            set_state(t, "awaiting_approval", "script validated — awaiting operator approval")
            moved = True
        if t["state"] == "awaiting_approval":
            if not t["approved"]:
                return moved  # still parked
            set_state(t, "generating_media")
            moved = True
        if t["state"] == "generating_media":
            stage("voiceover", ["voiceover", "--project", proj,
                                "--voice", cfg["voice"],
                                "--language", cfg["language"],
                                "--tts-engine", cfg.get("tts_engine", "hosted")])
            stage("visuals", ["visuals", "--project", proj])
            set_state(t, "editing")
            moved = True
        if t["state"] == "editing":
            stage("assemble", ["assemble", "--project", proj])
            stage("platforms", ["platforms", "--project", proj])
            stage("seo", ["seo", "--project", proj, "--topic", topic])
            stage("package", ["package", "--project", proj])
            set_state(t, "quality_checking")
            moved = True
        if t["state"] == "quality_checking":
            ok, _ = engine_run(proj, ["qc", "--project", proj])
            if not ok:
                raise RuntimeError("QC failed — see qc_report.json")
            set_state(t, "ready_for_publishing", "QC passed")
            moved = True
        t["attempts"] = 0
        t["next_retry_at"] = None
        t["error"] = None
    except RuntimeError as e:
        t["attempts"] += 1
        t["error"] = str(e)[:300]
        if t["attempts"] >= t["max_attempts"]:
            set_state(t, "failed", t["error"])
        else:
            wait = min(600, 30 * (2 ** t["attempts"]))
            nxt = (datetime.datetime.now(datetime.timezone.utc)
                   + datetime.timedelta(seconds=wait)).isoformat()
            t["next_retry_at"] = nxt
            set_state(t, t["state"], f"attempt {t['attempts']} failed; retry at {nxt}")
        moved = True
    return moved


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add")
    p.add_argument("--topic", required=True)
    p.add_argument("--priority", type=int, default=3)
    p.add_argument("--voice", default="avocado_v2:MAI_03")
    p.add_argument("--language", default="en")
    p.add_argument("--tts-engine", default="hosted",
                    choices=["hosted", "piper", "gtts"])
    p.add_argument("--research-query", default="",
                   help="override Wikipedia search query for auto-research")
    p.add_argument("--script-file", default="",
                   help="pre-written scenes.json: skips the LLM draft, parks "
                        "at awaiting_approval for operator review (NOT auto-approved)")

    p = sub.add_parser("list")
    p.add_argument("--state", default="")

    p = sub.add_parser("show")
    p.add_argument("id")

    p = sub.add_parser("approve")
    p.add_argument("id")
    p.add_argument("--script-file", default="")

    p = sub.add_parser("run-once")

    p = sub.add_parser("retry")
    p.add_argument("id")

    p = sub.add_parser("cancel")
    p.add_argument("id")

    p = sub.add_parser("mark-published")
    p.add_argument("id")
    p.add_argument("--url", required=True)

    a = ap.parse_args()
    q = load()

    if a.cmd == "add":
        add_task(a.topic, a.priority, a.voice, a.language, a.tts_engine,
                 a.research_query, a.script_file)
    elif a.cmd == "list":
        rows = q["tasks"]
        if a.state:
            rows = [t for t in rows if t["state"] == a.state]
        for t in rows:
            flag = f" retry@{t['next_retry_at'][:16]}" if t.get("next_retry_at") else ""
            print(f"{t['id']} p{t['priority']} [{t['state']}] {t['topic'][:50]}{flag}")
        if not rows:
            print("(empty)")
    elif a.cmd == "show":
        t = get(q, a.id)
        print(json.dumps(t, indent=2, ensure_ascii=False))
    elif a.cmd == "approve":
        t = get(q, a.id)
        if a.script_file:
            if not os.path.exists(a.script_file):
                sys.exit(f"script file not found: {a.script_file}")
            t["script_file"] = os.path.abspath(a.script_file)
        t["approved"] = True
        if t["state"] == "awaiting_approval":
            pass  # run-once will continue
        elif t["state"] == "scriptwriting":
            pass
        else:
            print(f"[queue] note: task is in {t['state']}; approval recorded")
        set_state(t, t["state"], "operator approved" +
                  (f" with {t['script_file']}" if t.get("script_file") else ""))
        save(q)
        print(f"[queue] {t['id']} approved")
    elif a.cmd == "run-once":
        ts = actionable(q)
        if not ts:
            print("[queue] nothing actionable")
            return
        t = ts[0]
        print(f"[queue] processing {t['id']} [{t['state']}] {t['topic'][:60]}")
        t0 = time.time()
        process(t)
        save(q)
        print(f"[queue] {t['id']} -> {t['state']} ({time.time()-t0:.0f}s)"
              + (f" | {t['error'][:120]}" if t.get("error") else ""))
    elif a.cmd == "retry":
        t = get(q, a.id)
        t["attempts"] = 0
        t["next_retry_at"] = None
        t["error"] = None
        if t["state"] == "failed":
            # rewind to last productive state from history
            for h in reversed(t["history"]):
                if h["state"] not in ("failed",):
                    set_state(t, h["state"], "manual retry")
                    break
        save(q)
        print(f"[queue] {t['id']} reset for retry")
    elif a.cmd == "cancel":
        t = get(q, a.id)
        set_state(t, "cancelled", "operator cancelled")
        save(q)
        print(f"[queue] {t['id']} cancelled")
    elif a.cmd == "mark-published":
        t = get(q, a.id)
        t["published_url"] = a.url
        set_state(t, "published", a.url)
        save(q)
        print(f"[queue] {t['id']} published: {a.url}")


if __name__ == "__main__":
    main()
