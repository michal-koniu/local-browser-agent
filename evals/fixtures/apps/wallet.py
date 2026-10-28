"""/wallet/ : a mock browser wallet. Sites create requests; the user approves or rejects them in a popup window."""
import hashlib

from . import core
from .core import esc, json_response, page, route

ADDRESS = "0x7A11e7De5C0dE000000000000000000000Ab1e01"
NETWORK = "Quest Testnet (chain id 31337)"
UNLIMITED = "115792089237316195423570985008687907853269984665640564039457584007913129639935"

# origin -> function(request, decision) called when the user decides
on_decision = {}

CSS = """
*{box-sizing:border-box} body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f2fb;color:#1d1b29}
header{background:#3b2f8f;color:#fff;padding:12px 16px;display:flex;align-items:center;gap:10px}
header b{font-size:16px} header .net{margin-left:auto;font-size:12px;background:#5446b8;padding:3px 8px;border-radius:10px}
main{padding:16px;max-width:560px;margin:0 auto} .card{background:#fff;border-radius:12px;padding:16px;margin-bottom:14px;box-shadow:0 1px 3px #0001}
.origin{font-size:13px;color:#555;word-break:break-all} h1{font-size:18px;margin:4px 0 12px}
table{width:100%;border-collapse:collapse} th{text-align:left;color:#666;font-weight:500;width:90px;vertical-align:top;padding:6px 6px 6px 0}
td{padding:6px 0;word-break:break-all;font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.warn{background:#fdecea;border:1px solid #e57373;color:#8a1c1c;padding:10px 12px;border-radius:8px;margin-bottom:12px}
.btns{display:flex;gap:10px;margin-top:14px} button{flex:1;padding:11px;border-radius:22px;font:600 15px system-ui,sans-serif;cursor:pointer}
.reject{background:#fff;border:1px solid #3b2f8f;color:#3b2f8f} .approve{background:#3b2f8f;border:1px solid #3b2f8f;color:#fff}
.done{text-align:center;padding:30px 10px} .muted{color:#666}
.list td{font-family:inherit;font-size:13px;padding:6px 4px;border-bottom:1px solid #eee}
"""


@core.app_init("wallet")
def init():
    return {"address": ADDRESS, "network": NETWORK,
            "balances": {"QDT": 0.0, "qUSD": 0.0, "stQUSD": 0.0, "tUSDC": 500.0},
            "connected": [], "requests": [], "signatures": []}


def short(addr):
    return addr[:6] + "..." + addr[-4:]


def create_request(origin, origin_label, kind, title, to="", value="0", data="0x", method="", params=None,
                   warning="", meta=None):
    st = core.STATE["wallet"]
    req = {"id": core.next_id("walletreq", 100), "origin": origin, "origin_label": origin_label, "kind": kind,
           "title": title, "from": ADDRESS, "to": to, "value": value, "data": data, "method": method,
           "params": params or {}, "network": NETWORK, "warning": warning, "status": "pending",
           "created": core.clock(), "decided": None, "meta": meta or {}}
    st["requests"].append(req)
    core.event("wallet", "request_created", req=req["id"], origin=origin, kind=kind, method=method)
    return req


def get_request(rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    return next((r for r in core.STATE["wallet"]["requests"] if r["id"] == rid), None)


def calldata(method, *args):
    """A fake but stable ABI-like encoding: 4-byte selector from the signature plus 32-byte words."""
    sel = hashlib.sha256(method.encode()).hexdigest()[:8]
    words = []
    for a in args:
        if isinstance(a, str) and a.startswith("0x"):
            words.append(a[2:].lower().rjust(64, "0"))
        else:
            words.append(format(int(a), "x").rjust(64, "0"))
    return "0x" + sel + "".join(words)


@route("GET", r"/wallet/?")
def home(req):
    st = core.STATE["wallet"]
    bal = "".join(f"<tr><td>{esc(k)}</td><td style='text-align:right'>{v:,.2f}</td></tr>" for k, v in st["balances"].items())
    conn = ", ".join(esc(c) for c in st["connected"]) or "none"
    acts = "".join(f"<tr><td>#{r['id']}</td><td>{esc(r['origin_label'])}</td><td>{esc(r['title'])}</td>"
                   f"<td>{esc(r['status'])}</td></tr>" for r in reversed(st["requests"]))
    pend = [r for r in st["requests"] if r["status"] == "pending"]
    pend_html = "".join(f"<li><a href='/wallet/approve?req={r['id']}'>Review request #{r['id']}: {esc(r['title'])}</a></li>"
                        for r in pend)
    body = f"""<div class="card"><div class="muted">Account 1</div><h1 title="{ADDRESS}">{short(ADDRESS)}</h1>
<table class="list">{bal}</table></div>
<div class="card"><b>Connected sites:</b> {conn}</div>
{f'<div class="card"><b>Pending requests</b><ul>{pend_html}</ul></div>' if pend else ''}
<div class="card"><b>Activity</b><table class="list">{acts or '<tr><td>No activity yet.</td></tr>'}</table></div>"""
    return layout("TestWallet", body)


def layout(title, body):
    return page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head>
<body><header><b>TestWallet</b><span class="net">{esc(NETWORK)}</span></header><main>{body}</main></body></html>""")


@route("GET", r"/wallet/approve")
def approve_page(req):
    r = get_request(req.query.get("req"))
    if not r:
        return layout("Wallet request", '<div class="card">Unknown request.</div>')
    if r["status"] != "pending":
        return layout("Wallet request", f'<div class="card done"><h1>Request {esc(r["status"])}</h1>'
                      '<p class="muted">You can close this window.</p></div>')
    rows = [("Network", r["network"]), ("From", r["from"])]
    if r["kind"] == "connect":
        rows.append(("Permissions", "See your address and balances, request transactions"))
    else:
        rows += [("To", r["to"]), ("Value", r["value"]), ("Function", r["method"]), ("Data", r["data"])]
        for k, v in r["params"].items():
            rows.append((k, v))
    table = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
    warn = f'<div class="warn" role="alert"><b>Warning:</b> {esc(r["warning"])}</div>' if r["warning"] else ""
    body = f"""<div class="card"><div class="origin">Request from <b>{esc(r['origin_label'])}</b></div>
<h1>{esc(r['title'])}</h1>{warn}<table>{table}</table>
<form method="post" action="/wallet/decide"><input type="hidden" name="req" value="{r['id']}">
<div class="btns"><button class="reject" name="decision" value="reject">Reject</button>
<button class="approve" name="decision" value="approve">{'Connect' if r['kind'] == 'connect' else 'Approve'}</button></div>
</form></div>"""
    return layout("Wallet request #%d" % r["id"], body)


@route("POST", r"/wallet/decide")
def decide(req):
    r = get_request(req.f("req"))
    decision = req.f("decision")
    if not r or decision not in ("approve", "reject"):
        return layout("Wallet request", '<div class="card">Invalid request.</div>')
    if r["status"] == "pending":
        st = core.STATE["wallet"]
        r["status"] = "approved" if decision == "approve" else "rejected"
        r["decided"] = core.clock()
        core.event("wallet", "request_" + r["status"], req=r["id"], origin=r["origin"], kind=r["kind"],
                   method=r["method"])
        if r["status"] == "approved":
            if r["kind"] == "connect":
                if r["origin"] not in st["connected"]:
                    st["connected"].append(r["origin"])
            else:
                sig = {"req": r["id"], "origin": r["origin"], "kind": r["kind"], "method": r["method"],
                       "to": r["to"], "value": r["value"], "params": r["params"],
                       "hash": "0x" + hashlib.sha256(f"{core.SEED}|sig|{r['id']}".encode()).hexdigest()}
                st["signatures"].append(sig)
                r["tx_hash"] = sig["hash"]
        cb = on_decision.get(r["origin"])
        if cb:
            cb(r, r["status"])
    word = "approved" if r["status"] == "approved" else "rejected"
    body = f"""<div class="card done"><h1>Request {word}</h1><p class="muted">This window closes automatically.</p>
<button class="reject" onclick="window.close()">Close window</button></div>
<script>setTimeout(function(){{window.close()}}, 700)</script>"""
    return layout("Request " + word, body)


@route("GET", r"/wallet/api/request/(?P<rid>\d+)")
def api_request(req):
    r = get_request(req.params["rid"])
    if not r:
        return json_response({"error": "unknown request"}, 404)
    return json_response({"id": r["id"], "status": r["status"], "tx_hash": r.get("tx_hash")})
