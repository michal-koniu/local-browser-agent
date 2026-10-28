"""Settings: a TOML file (config.toml, or config.example.toml when there is none) plus command-line overrides."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "base_url": "http://127.0.0.1:8080/v1",
    "api_key": "local",
    "default_model": "local",
    "models": {},
    "agent": {
        "max_steps": 150,
        "keep_snapshots": 2,
        "keep_screenshots": 1,
        "context_budget": 150000,
        "keep_reasoning": False,
        "max_tool_chars": 40000,
        "repeat_limit": 3,
        "mark_new": True,
        "allow_view_source": False,
    },
    "browser": {
        "mode": "isolated",          # isolated | profile | cdp
        "profile": "default",        # mode=profile: profiles/<name> keeps logins between runs
        "cdp_endpoint": "",          # mode=cdp: attach to your own Chrome, e.g. http://127.0.0.1:9222
        "browser": "chrome",
        "viewport": "1440x900",
        "headless": True,
        "caps": "vision,pdf,devtools",
        "allowed_origins": "",
        "blocked_origins": "",
        "record_trace": True,
        "record_video": True,
        "slow_mo_ms": 0,
        "upload_dirs": [],
        "keep_media_with_secrets": True,
        "show_actions": True,
        "mcp_bin": "node_modules/.bin/playwright-mcp",
        "hidden_tools": [],
    },
    "secrets": {"provider": "none", "dotenv_path": "", "token_file": "", "map": {}},
    "policy": {"default": "ask", "rules": []},
    "human": {"mode": "auto-detect", "timeout_s": 900, "notify_command": "", "auto_answer": "deny"},
}


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path=None):
    if path is None:
        path = ROOT / "config.toml"
        if not path.exists():
            path = ROOT / "config.example.toml"
    with open(path, "rb") as f:
        cfg = _merge(DEFAULTS, tomllib.load(f))
    cfg["_path"] = str(path)
    return cfg


def model(cfg, name=None):
    name = name or cfg["default_model"]
    if name not in cfg["models"]:
        raise SystemExit(f"unknown model {name!r}; {cfg['_path']} defines: {', '.join(cfg['models']) or 'none'}")
    m = {"vision": False, "coords": "norm1000", "max_tokens": 16384, **cfg["models"][name]}
    m["name"] = name
    return m
