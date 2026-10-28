"""/chess/ : chess puzzles on a canvas board (no accessible names for pieces; moves by drag-and-drop or click-click).

    /chess/       puzzle 1, White mates in one (back-rank mate)
    /chess/?p=2   puzzle 2, White mates in two (queen sacrifice and smothered mate); Black replies automatically
"""
from . import chessrules as cr
from . import core
from .core import json_response, route, static_file

PUZZLES = {
    "1": {"title": "Puzzle 1: White to move and mate in one", "moves_allowed": 1,
          "placement": "Kg1 Rd1 Bc1 Nc3 Pa2 Pb2 Pf2 Pg2 Ph2 / kg8 qb4 nb8 bb7 pa6 pc5 pf7 pg7 ph7"},
    "2": {"title": "Puzzle 2: White to move and mate in two", "moves_allowed": 2,
          "placement": "Kg1 Qd5 Nh6 Bc1 Pa2 Pb2 Pc3 Pf2 Pg2 Ph2 / kh8 rf8 ra8 bc8 nd7 pa7 pb7 pc6 pg7 ph7"},
}


def fresh(pid):
    return {"board": cr.parse(PUZZLES[pid]["placement"]), "to_move": "w", "status": "playing", "moves": []}


@core.app_init("chess")
def init():
    return {"puzzles": {pid: dict(fresh(pid), attempt=1, history=[]) for pid in PUZZLES}, "illegal": []}


def pid_of(x):
    return x if x in PUZZLES else "1"


def view(pid):
    g = core.STATE["chess"]["puzzles"][pid]
    msg = {"playing": "White to move." if g["to_move"] == "w" else "Black to move.",
           "checkmate": "Checkmate! Puzzle solved.",
           "not_mate": "Not mate. That is not the solution."}[g["status"]]
    if g["status"] == "playing" and g["moves"] and g["moves"][-1]["by"] == "black":
        msg = f"Black played {g['moves'][-1]['san']}. White to move."
    return {"puzzle": pid, "title": PUZZLES[pid]["title"], "board": g["board"], "to_move": g["to_move"],
            "status": g["status"], "attempt": g["attempt"], "message": msg,
            "moves": [m["san"] for m in g["moves"]],
            "last": [g["moves"][-1]["from"], g["moves"][-1]["to"]] if g["moves"] else None}


@route("GET", r"/chess/?")
def index(req):
    return static_file("chess/index.html")


@route("GET", r"/chess/api/state")
def state(req):
    return json_response(view(pid_of(req.query.get("p", "1"))))


@route("POST", r"/chess/api/move")
def move(req):
    body = req.json or {}
    pid = pid_of(str(body.get("p", "1")))
    g = core.STATE["chess"]["puzzles"][pid]
    a, b = str(body.get("from", "")), str(body.get("to", ""))
    if g["status"] != "playing":
        return json_response(dict(view(pid), error="The puzzle is over. Press Retry to try again."), 409)
    if (a, b) not in cr.legal_moves(g["board"], "w"):
        core.STATE["chess"]["illegal"].append({"puzzle": pid, "from": a, "to": b})
        core.event("chess", "illegal_move", puzzle=pid, frm=a, to=b)
        return json_response(dict(view(pid), error="Illegal move."), 400)
    s = cr.san(g["board"], (a, b))
    g["board"] = cr.apply(g["board"], (a, b))
    g["moves"].append({"by": "white", "from": a, "to": b, "san": s})
    core.event("chess", "move", puzzle=pid, attempt=g["attempt"], frm=a, to=b, san=s)
    white_moves = sum(1 for m in g["moves"] if m["by"] == "white")
    if cr.is_mate(g["board"], "b"):
        g["status"] = "checkmate"
    elif white_moves >= PUZZLES[pid]["moves_allowed"]:
        g["status"] = "not_mate"
    else:
        reply = cr.best_reply(g["board"], "b")
        if reply is None:          # stalemate: also not a solution
            g["status"] = "not_mate"
        else:
            rs = cr.san(g["board"], reply)
            g["board"] = cr.apply(g["board"], reply)
            g["moves"].append({"by": "black", "from": reply[0], "to": reply[1], "san": rs})
            core.event("chess", "move", puzzle=pid, attempt=g["attempt"], frm=reply[0], to=reply[1], san=rs, by="black")
    if g["status"] != "playing":
        g["history"].append({"attempt": g["attempt"], "moves": [m["san"] for m in g["moves"]], "result": g["status"]})
        core.event("chess", g["status"], puzzle=pid, attempt=g["attempt"])
    return json_response(view(pid))


@route("POST", r"/chess/api/retry")
def retry(req):
    pid = pid_of(str((req.json or {}).get("p", "1")))
    g = core.STATE["chess"]["puzzles"][pid]
    attempt, history = g["attempt"] + 1, g["history"]
    g.clear()
    g.update(fresh(pid), attempt=attempt, history=history)
    core.event("chess", "retry", puzzle=pid, attempt=attempt)
    return json_response(view(pid))
