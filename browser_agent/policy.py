"""Risky-action gate. Decided in code, from what the element really is, never from the model's own label.

Before a click, a submit or an Enter, the harness looks up the target element - in the latest snapshot for a
ref, or with document.elementFromPoint for a coordinate click - and matches its text and the page URL against
the rules in config [policy]. The first matching rule decides: allow, ask (a human approves) or deny.

A rule:  { category = "payment", pattern = "(?i)\\b(pay|place order)\\b", url = "", action = "ask" }
"""
import re
from dataclasses import dataclass

DEFAULT_RULES = [
    {"category": "payment", "action": "ask",
     "pattern": r"(?i)\b(pay|pay now|buy|buy now|purchase|place (your )?order|complete (the )?(order|purchase)|checkout and pay)\b"},
    {"category": "signature", "action": "ask",
     "pattern": r"(?i)\b(sign|approve|confirm (the )?transaction|confirm swap|send transaction)\b",
     "url": r"(?i)wallet|approve|sign|metamask|chrome-extension://"},
    {"category": "publish", "action": "ask",
     "pattern": r"(?i)^(post|publish|tweet|share|send|reply|submit post)\b"},
    {"category": "destructive", "action": "ask",
     "pattern": r"(?i)\b(delete (my )?account|close account|remove account|transfer funds|withdraw)\b"},
]

GATED_TOOLS = {"browser_click", "click_at", "browser_press_key", "browser_type", "browser_fill_form"}


@dataclass
class Verdict:
    action: str          # allow | ask | deny
    category: str = ""
    target: str = ""     # what the element really is, e.g. 'button "Place order"'
    url: str = ""


class Policy:
    def __init__(self, cfg):
        rules = cfg.get("rules") or []
        self.rules = [dict(r, _p=re.compile(r["pattern"]), _u=re.compile(r["url"]) if r.get("url") else None)
                      for r in (rules + DEFAULT_RULES if cfg.get("use_default_rules", True) else rules)]
        self.default = cfg.get("default", "ask")

    def needs_check(self, tool, args):
        if tool not in GATED_TOOLS:
            return False
        if tool == "browser_type":
            return bool(args.get("submit"))
        if tool == "browser_press_key":
            return args.get("key") in ("Enter", "NumpadEnter")
        return True

    def judge(self, name, url, role=""):
        """name: the element's accessible name or visible text (rules match this); url: the page it is on."""
        target = f'{role} "{name}"'.strip()
        for r in self.rules:
            if r["_p"].search((name or "").strip()) and (r["_u"] is None or r["_u"].search(url or "")):
                action = r["action"] if r["action"] in ("allow", "ask", "deny") else self.default
                return Verdict(action, r.get("category", ""), target, url)
        return Verdict("allow", "", target, url)
