"""Shared plumbing for the fixture apps: routing, requests, state, events, sessions and secrets."""
import email.parser
import email.policy
import hashlib
import html
import json
import os
import re
import sys
import threading
import urllib.parse
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
STATIC = os.path.join(FIXTURES, "static")
EVALS = os.path.dirname(FIXTURES)
SEED = "lba-evals-seed-1"
BASE_TIME = datetime(2026, 3, 2, 9, 0)

LOCK = threading.RLock()
STATE = {}
_initializers = []     # (app name, function returning the app's initial state)
_routes = []           # (method, compiled regex, handler)


# ---------------------------------------------------------------- secrets

def load_secrets():
    """Read evals/secrets.env (fake test values). Environment variables override the file."""
    values = {}
    path = os.environ.get("LBA_EVAL_SECRETS", os.path.join(EVALS, "secrets.env"))
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(values):
        if k in os.environ:
            values[k] = os.environ[k]
    return values


SECRETS = load_secrets()


def secret(name, default=""):
    return SECRETS.get(name, default)


# ---------------------------------------------------------------- state, events, counters

def app_init(name):
    """Decorator: register a function that returns the initial state of one app."""
    def deco(fn):
        _initializers.append((name, fn))
        return fn
    return deco


def reset():
    with LOCK:
        STATE.clear()
        STATE["_counters"] = {}
        STATE["events"] = []
        STATE["exfiltration"] = []
        for name, fn in _initializers:
            STATE[name] = fn()


def next_id(kind, start=1):
    c = STATE["_counters"]
    c[kind] = c.get(kind, start - 1) + 1
    return c[kind]


def token(kind, *parts):
    """Deterministic token: hash of the seed, a per-kind counter and the given parts."""
    n = next_id("token:" + kind)
    raw = "|".join([SEED, kind, str(n)] + [str(p) for p in parts])
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def clock():
    """Logical clock: every call moves time forward by 7 minutes from a fixed base."""
    n = next_id("clock")
    return (BASE_TIME + timedelta(minutes=7 * n)).strftime("%Y-%m-%d %H:%M")


def event(app, type_, **data):
    e = {"seq": len(STATE["events"]) + 1, "app": app, "type": type_}
    e.update(data)
    STATE["events"].append(e)
    return e


def exfiltrate(source, data):
    """Record anything that reached an attacker-controlled sink."""
    item = {"seq": len(STATE["exfiltration"]) + 1, "source": source, "data": data}
    STATE["exfiltration"].append(item)
    event("attacker", "exfiltration", source=source, data=data)
    return item


def public_state():
    with LOCK:
        return json.loads(json.dumps({k: v for k, v in STATE.items() if not k.startswith("_")}, default=str))


# ---------------------------------------------------------------- requests and responses

class Request:
    def __init__(self, handler, method):
        self.method = method
        parsed = urllib.parse.urlsplit(handler.path)
        self.path = parsed.path
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = handler.headers
        self.cookies = {}
        if handler.headers.get("Cookie"):
            c = SimpleCookie()
            try:
                c.load(handler.headers["Cookie"])
            except Exception:
                pass
            self.cookies = {k: m.value for k, m in c.items()}
        self.form, self.form_lists, self.files, self.json = {}, {}, {}, None
        length = int(handler.headers.get("Content-Length") or 0)
        self.body = handler.rfile.read(length) if length else b""
        ctype = handler.headers.get("Content-Type", "")
        if self.body:
            if ctype.startswith("application/x-www-form-urlencoded"):
                self.form_lists = urllib.parse.parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True)
                self.form = {k: v[0] for k, v in self.form_lists.items()}
            elif ctype.startswith("multipart/form-data"):
                self._parse_multipart(ctype)
            elif ctype.startswith("application/json"):
                try:
                    self.json = json.loads(self.body)
                except ValueError:
                    self.json = None
        self.params = {}

    def _parse_multipart(self, ctype):
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.body)
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_param("filename", header="content-disposition")
            payload = part.get_payload(decode=True) or b""
            if filename is not None:
                if filename or payload:
                    self.files[name] = {"filename": filename, "content_type": part.get_content_type(), "data": payload}
            else:
                value = payload.decode(part.get_content_charset() or "utf-8", "replace")
                self.form.setdefault(name, value)
                self.form_lists.setdefault(name, []).append(value)

    def f(self, name, default=""):
        return self.form.get(name, default).strip()


class Response:
    def __init__(self, body=b"", status=200, content_type="text/html; charset=utf-8"):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = [("Content-Type", content_type)]

    def set_cookie(self, name, value, path="/", max_age=None):
        c = f"{name}={value}; Path={path}; SameSite=Lax"
        if max_age is not None:
            c += f"; Max-Age={max_age}"
        self.headers.append(("Set-Cookie", c))
        return self


def page(body, status=200):
    return Response(body, status)


def redirect(location, status=303):
    r = Response(b"", status)
    r.headers.append(("Location", location))
    return r


def json_response(obj, status=200):
    return Response(json.dumps(obj, indent=1), status, "application/json")


def not_found(msg="Not found"):
    return Response(f"<!doctype html><title>404 Not Found</title><h1>404 Not Found</h1><p>{esc(msg)}</p>", 404)


def static_file(relpath, content_type=None):
    path = os.path.normpath(os.path.join(STATIC, relpath))
    if not path.startswith(STATIC) or not os.path.isfile(path):
        return not_found()
    ext = os.path.splitext(path)[1]
    ct = content_type or {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                          ".json": "application/json"}.get(ext, "application/octet-stream")
    with open(path, "rb") as fh:
        return Response(fh.read(), 200, ct)


def esc(s):
    return html.escape(str(s), quote=True)


def route(method, pattern):
    """Decorator: register a handler for METHOD and a full-match regex on the path."""
    rx = re.compile(pattern)

    def deco(fn):
        _routes.append((method, rx, fn))
        return fn
    return deco


# ---------------------------------------------------------------- sessions

def session(req, app, cookie_name):
    """Return the session dict of an app, creating one when the browser has none (the cookie is set on the response)."""
    sessions = STATE[app]["sessions"]
    sid = req.cookies.get(cookie_name)
    if sid and sid in sessions:
        return sessions[sid]
    sid = token("sid-" + app)
    sessions[sid] = {"id": sid}
    req.cookies[cookie_name] = sid
    req.cookie_jar.append((cookie_name, sid, "/"))
    return sessions[sid]


# ---------------------------------------------------------------- server

@route("GET", r"/__state")
def get_state(req):
    return json_response(public_state())


@route("POST", r"/__reset")
def post_reset(req):
    reset()
    return json_response({"ok": True})


@route("GET", r"/")
def index(req):
    links = "".join(f'<li><a href="/{a}/">/{a}/</a></li>' for a in
                    ["shop", "mail", "social", "wallet", "dapp", "chess", "qa", "research"])
    return page(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Eval fixtures</title></head>"
                f"<body><h1>Eval fixtures</h1><ul>{links}</ul></body></html>")


@route("GET", r"/favicon.ico")
def favicon(req):
    return Response(b"", 204, "image/x-icon")


class Handler(BaseHTTPRequestHandler):
    server_version = "LBAFixtures/1.0"
    quiet = False

    def _handle(self, method):
        try:
            req = Request(self, method)
            resp = None
            with LOCK:
                req.cookie_jar = []      # cookies a handler wants to set: (name, value, path)
                for m, rx, fn in _routes:
                    if m != method and not (m == "GET" and method == "HEAD"):
                        continue
                    mt = rx.fullmatch(req.path)
                    if mt:
                        req.params = mt.groupdict()
                        resp = fn(req)
                        break
                if resp is None:
                    # GET of a known POST route, or unknown path
                    resp = not_found(f"No page at {req.path}")
                for name, value, path in req.cookie_jar:
                    resp.set_cookie(name, value, path)
        except Exception as exc:  # keep the fixture alive, show the error
            import traceback
            traceback.print_exc()
            resp = Response(f"<h1>500 Internal Server Error</h1><pre>{esc(exc)}</pre>", 500)
        self.send_response(resp.status)
        for k, v in resp.headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(resp.body)

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def log_message(self, fmt, *args):
        if not self.quiet:
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def serve(host, port, quiet=False):
    Handler.quiet = quiet
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"eval fixtures on http://{host}:{port}/  (state: /__state, reset: POST /__reset)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
