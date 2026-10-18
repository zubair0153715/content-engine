#!/usr/bin/env python3
"""Web dashboard — Content Engine v2. Stdlib only, no pip dependencies.

Pages:
  /                 content library (all projects: topic, date, QC, status)
  /project/<id>     detail: video preview, QC, SEO, approve/reject, downloads
  /new              new-project form (topic -> task queue)
  /queue            task queue states
  /analytics        honest analytics report
  /files/<id>/<p>   project file downloads (MP4 served with Range support)

Run:  python3 dashboard.py [--port 8099]
Demo: curl http://localhost:8099/   (verify 200 + project rows)
"""
import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.expanduser("~/workspace/content-engine")
PROJECTS = os.path.join(BASE, "projects")
CSS = ("body{font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto;"
       "padding:0 16px;color:#1a1a1a}table{border-collapse:collapse;width:100%}"
       "th,td{border:1px solid #ddd;padding:8px;text-align:left;font-size:14px}"
       "th{background:#f4f4f4}.ok{color:#0a7d2c;font-weight:bold}"
       ".bad{color:#b00020;font-weight:bold}.nav{margin-bottom:16px}"
       ".nav a{margin-right:14px}video{max-width:100%;background:#000}"
       ".card{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0}"
       "pre{background:#f6f6f6;padding:12px;overflow:auto;font-size:13px}"
       "input[type=text]{width:70%;padding:8px}button{padding:8px 16px}")


def esc(s):
    return html.escape(str(s if s is not None else ""))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def project_ids():
    return sorted(d for d in os.listdir(PROJECTS)
                  if os.path.isdir(os.path.join(PROJECTS, d)))


def project_row(pid):
    d = os.path.join(PROJECTS, pid)
    man = read_json(os.path.join(d, "manifest.json"), {})
    qc = read_json(os.path.join(d, "qc_report.json"), {})
    status = read_json(os.path.join(d, "status.json"), {})
    script = read_json(os.path.join(d, "script.json"), {})
    topic = ""
    rb = os.path.join(d, "research_brief.md")
    if os.path.exists(rb):
        with open(rb, encoding="utf-8") as f:
            m = re.match(r"# Research brief:\s*(.+)", f.readline())
            if m:
                topic = m.group(1).strip()
    if not topic:
        topic = script.get("topic") or pid
    created = (man.get("created") or "")[:10]
    return {"id": pid, "topic": topic, "created": created,
            "qc": qc.get("score"), "qc_pass": qc.get("passed"),
            "decision": status.get("decision"),
            "has_video": os.path.exists(os.path.join(d, "final.mp4"))}


def queue_tasks():
    qp = os.path.join(BASE, "queue.json")
    return read_json(qp, {"tasks": []})["tasks"]


def page(title, body):
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"
            "<div class='nav'><a href='/'>Library</a><a href='/queue'>Queue</a>"
            "<a href='/analytics'>Analytics</a><a href='/new'>+ New video</a></div>"
            f"<h1>{esc(title)}</h1>{body}</div></body></html>")


def library_html():
    rows = [project_row(pid) for pid in project_ids()]
    trs = []
    for r in rows:
        qc = (f"<span class='ok'>{r['qc']}</span>" if r["qc_pass"]
              else f"<span class='bad'>{r['qc']}</span>" if r["qc"] is not None
              else "—")
        dec = r["decision"] or "—"
        trs.append(
            f"<tr><td><a href='/project/{esc(r['id'])}'>{esc(r['id'])}</a></td>"
            f"<td>{esc(r['topic'][:60])}</td><td>{esc(r['created'])}</td>"
            f"<td>{qc}</td><td>{esc(dec)}</td>"
            f"<td>{'🎬' if r['has_video'] else '—'}</td></tr>")
    return page("Content Library", (
        f"<p>{len(rows)} projects. QC ≥ pass required before publishing.</p>"
        "<table><tr><th>Project</th><th>Topic</th><th>Created</th>"
        "<th>QC</th><th>Decision</th><th>Video</th></tr>"
        + "".join(trs) + "</table>"))


def project_html(pid):
    d = os.path.join(PROJECTS, pid)
    if not os.path.isdir(d):
        return None
    r = project_row(pid)
    man = read_json(os.path.join(d, "manifest.json"), {})
    qc = read_json(os.path.join(d, "qc_report.json"), {})
    seo = read_json(os.path.join(d, "seo.json"), {})
    files = man.get("files", {})
    renders = files.get("renders", {}) if isinstance(files, dict) else {}

    vids = ""
    for label, fn in [("9:16 master", "final.mp4"),
                      ("1:1", "final_1x1.mp4"), ("16:9", "final_16x9.mp4")]:
        if fn and os.path.exists(os.path.join(d, fn)):
            vids += (f"<div class='card'><h3>{label}</h3>"
                     f"<video controls preload='metadata' style='max-height:480px' "
                     f"src='/files/{esc(pid)}/{fn}'></video><br>"
                     f"<a href='/files/{esc(pid)}/{fn}' download>Download {fn}</a>"
                     f" ({os.path.getsize(os.path.join(d, fn)) // 1024} KB)</div>")

    qc_rows = "".join(
        f"<tr><td>{esc(k)}</td>"
        f"<td class='{'ok' if v.get('pass') else 'bad'}'>"
        f"{'PASS' if v.get('pass') else 'FAIL'}</td>"
        f"<td>{esc(v.get('detail', ''))}</td></tr>"
        for k, v in qc.get("checks", {}).items())

    dl = ""
    for label, fn in [("SEO package", "seo.json"), ("Captions", "captions.srt"),
                      ("Upload checklist", "UPLOAD_CHECKLIST.md"),
                      ("Manifest", "manifest.json"),
                      ("Research brief", "research_brief.md"),
                      ("QC report", "qc_report.json")]:
        if fn and os.path.exists(os.path.join(d, fn)):
            dl += f"<a href='/files/{esc(pid)}/{fn}' download>{label}</a> · "
    return page(f"Project {pid}", (
        f"<p><b>Topic:</b> {esc(r['topic'])}</p>"
        f"<p><b>QC:</b> {r['qc']} ({'PASS' if r['qc_pass'] else 'FAIL'}) · "
        f"<b>Decision:</b> {esc(r['decision'] or 'pending')}</p>"
        "<form method='POST' action='/project/" + esc(pid) + "/decision' "
        "style='display:inline'>"
        "<button name='decision' value='approved'>✓ Approve</button> "
        "<button name='decision' value='rejected'>✗ Reject</button></form>"
        f"<h2>Videos</h2>{vids or '<p>No renders yet.</p>'}"
        f"<h2>QC checks</h2><table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>"
        f"{qc_rows}</table>"
        f"<h2>SEO</h2><pre>{esc(json.dumps(seo, indent=2, ensure_ascii=False)[:2000])}</pre>"
        f"<h2>Downloads</h2><p>{dl}</p>"))


def new_form_html(msg=""):
    return page("New video", (
        f"<p>{esc(msg)}</p>" if msg else ""
        + "<form method='POST' action='/new'>"
        "<label>Topic (one instruction):</label><br>"
        "<input type='text' name='topic' required "
        "placeholder='e.g. 3 ChatGPT prompt tricks most people miss'><br><br>"
        "<label>Priority 1–5:</label> "
        "<input type='text' name='priority' value='3' size='3'><br><br>"
        "<button type='submit'>Add to queue</button></form>"
        "<p>The queue runs research automatically; you approve the script "
        "before rendering (master doc: publishing stays human-approved).</p>"))


def queue_html():
    ts = queue_tasks()
    trs = "".join(
        f"<tr><td>{esc(t['id'])}</td><td>{esc(t['topic'][:55])}</td>"
        f"<td>{t['priority']}</td><td>{esc(t['state'])}</td>"
        f"<td>{'✓' if t.get('approved') else '—'}</td>"
        f"<td>{esc((t.get('error') or '')[:60])}</td></tr>" for t in ts)
    return page("Task Queue", (
        f"<p>{len(ts)} tasks. Process with: "
        "<code>python3 queue.py run-once</code> (or cron).</p>"
        "<table><tr><th>ID</th><th>Topic</th><th>Pri</th><th>State</th>"
        "<th>Approved</th><th>Error</th></tr>" + trs + "</table>"))


def analytics_html():
    p = subprocess.run([sys.executable, os.path.join(BASE, "analytics.py"),
                        "report"], capture_output=True, text=True, timeout=60)
    try:
        rep = json.loads(p.stdout)
    except Exception:
        rep = {"status": "error", "raw": p.stdout[-500:]}
    recs = "".join(f"<li>{esc(x)}</li>" for x in rep.get("recommendations", []))
    plats = "".join(
        f"<tr><td>{esc(k)}</td><td>{v.get('avg_views')}</td>"
        f"<td>{v.get('avg_retention_pct')}</td><td>{v.get('n')}</td></tr>"
        for k, v in rep.get("by_platform", {}).items())
    return page("Analytics", (
        f"<p>Status: <b>{esc(rep.get('status'))}</b> · "
        f"videos with data: {rep.get('videos_with_data')} · "
        f"entries: {rep.get('total_entries')}</p>"
        "<h2>Recommendations</h2><ol>" + recs + "</ol>"
        "<h2>By platform</h2><table><tr><th>Platform</th><th>Avg views</th>"
        "<th>Avg retention</th><th>n</th></tr>" + plats + "</table>"
        "<p>Log performance manually: "
        "<code>python3 analytics.py add --project ID --platform youtube_shorts "
        "--views 1200 --retention 38</code></p>"))


class Handler(BaseHTTPRequestHandler):
    server_version = "ContentEngine/2.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self._send(200, library_html())
        elif path == "/new":
            self._send(200, new_form_html())
        elif path == "/queue":
            self._send(200, queue_html())
        elif path == "/analytics":
            self._send(200, analytics_html())
        elif path.startswith("/project/"):
            parts = path.strip("/").split("/")
            if len(parts) == 2:
                body = project_html(parts[1])
                self._send(200 if body else 404, body or "not found")
            else:
                self._send(404, "not found")
        elif path.startswith("/files/"):
            self.serve_file(path[len("/files/"):])
        else:
            self._send(404, "not found")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        fields = urllib.parse.parse_qs(
            self.rfile.read(length).decode("utf-8", "ignore"))
        get = lambda k, d="": fields.get(k, [d])[0]

        if path == "/new":
            topic = get("topic").strip()
            if not topic:
                self._send(200, new_form_html("Topic is required."))
                return
            try:
                pri = max(1, min(5, int(get("priority", "3"))))
            except ValueError:
                pri = 3
            p = subprocess.run(
                [sys.executable, os.path.join(BASE, "queue.py"), "add",
                 "--topic", topic, "--priority", str(pri)],
                capture_output=True, text=True, timeout=60, cwd=BASE)
            msg = ("Queued ✓" if p.returncode == 0
                   else f"Queue error: {(p.stderr or p.stdout)[-200:]}")
            self._send(200, new_form_html(msg))
        elif path.startswith("/project/") and path.endswith("/decision"):
            pid = path.strip("/").split("/")[1]
            d = os.path.join(PROJECTS, pid)
            if not os.path.isdir(d):
                self._send(404, "not found")
                return
            dec = get("decision")
            if dec in ("approved", "rejected"):
                with open(os.path.join(d, "status.json"), "w") as f:
                    json.dump({"decision": dec,
                               "at": datetime.datetime.now(
                                   datetime.timezone.utc).isoformat(),
                               "by": "dashboard operator"}, f, indent=2)
            self.send_response(303)
            self.send_header("Location", f"/project/{pid}")
            self.end_headers()
        else:
            self._send(404, "not found")

    def serve_file(self, rel):
        # confine to projects dir; block traversal
        target = os.path.normpath(os.path.join(PROJECTS, rel))
        if not target.startswith(PROJECTS + os.sep) or not os.path.isfile(target):
            self._send(404, "not found")
            return
        size = os.path.getsize(target)
        ctype = "video/mp4" if target.endswith(".mp4") else \
                "application/json" if target.endswith(".json") else \
                "image/png" if target.endswith(".png") else \
                "text/plain; charset=utf-8"
        rng = self.headers.get("Range")
        if rng and target.endswith(".mp4"):
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                start = int(m.group(1)) if m.group(1) else 0
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start >= size:
                    self.send_response(416)
                    self.end_headers()
                    return
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range",
                                 f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(target, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(target, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    srv = HTTPServer(("127.0.0.1", a.port), Handler)
    print(f"[dashboard] http://127.0.0.1:{a.port}/ (Ctrl-C to stop)",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
