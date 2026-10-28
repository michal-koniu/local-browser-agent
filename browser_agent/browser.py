"""The browser: a Playwright MCP server (stdio) driving Chrome, plus what a local model needs on top of it.

Playwright MCP does the hard browser work (accessibility snapshots with element refs, clicking, typing, waiting,
dialogs, tabs, uploads, traces, video). This module starts it, calls its tools and post-processes the results:
- puts the page snapshot into every action result (Playwright MCP only links to a file after actions),
- marks elements that appeared since the previous snapshot with [new],
- keeps only important console lines (errors, warnings),
- remembers the latest snapshot so refs can be looked up (for the risky-action gate).
"""
import glob
import json
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path

import shutil

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import history

SNAP_LINK = re.compile(r"- \[Snapshot\]\((?:\./)?([^)]+\.yml)\)")
CONSOLE_LINK = re.compile(r"- New console entries: (?:\./)?(\S+\.log)#L(\d+)-L(\d+)")
URL_LINE = re.compile(r"- Page URL: (\S+)")
YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.S)
RESULT = re.compile(r"### Result\n(.*?)(?:\n###|\Z)", re.S)


def desktop_env():
    """Display variables of the logged-in desktop, so a browser started from a plain shell (ssh, a service,
    another agent) opens its window on your monitor. Empty when they are already set or there is no desktop."""
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return {}
    run = f"/run/user/{os.getuid()}"
    env = {}
    if os.path.exists(f"{run}/wayland-0"):
        env.update(XDG_RUNTIME_DIR=run, WAYLAND_DISPLAY="wayland-0")
    if os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"
        auth = sorted(glob.glob(f"{run}/.mutter-Xwaylandauth.*")) or sorted(glob.glob(f"{run}/gdm/Xauthority"))
        if auth:
            env["XAUTHORITY"] = auth[-1]
    return env


class Browser:
    def __init__(self, cfg, run_dir, root, headed=False):
        self.cfg, self.dir, self.root, self.headed = cfg, Path(run_dir), Path(root), headed
        self.vw, self.vh = (int(v) for v in cfg["viewport"].split("x"))
        self.snapshot, self.url = "", ""
        self.mark_new = True
        # Folders the browser may upload files from: the run folder plus [browser] upload_dirs. Nothing else - a
        # page that talks the model into "uploading" ~/.ssh/id_rsa must fail.
        self.upload_dirs = [self.dir.resolve()] + [Path(os.path.expanduser(d)).resolve()
                                                   for d in cfg.get("upload_dirs") or []]
        self._stack = AsyncExitStack()

    def params(self):
        c = self.cfg
        mcp_bin = Path(c["mcp_bin"])
        mcp_bin = mcp_bin if mcp_bin.is_absolute() else self.root / mcp_bin
        args = ["--browser", c["browser"], "--viewport-size", c["viewport"], "--caps", c["caps"],
                "--output-dir", str(self.dir), "--console-level", "info"]
        if c["mode"] == "cdp":
            args += ["--cdp-endpoint", c["cdp_endpoint"]]
        elif c["mode"] == "profile":
            profile = (self.root / "profiles" / c["profile"]).resolve()
            profile.mkdir(parents=True, exist_ok=True)
            args += ["--user-data-dir", str(profile)]
        else:
            args.append("--isolated")
        headless = c["mode"] != "cdp" and c.get("headless", True) and not self.headed
        if headless:
            args.append("--headless")
        if c.get("slow_mo_ms") and not headless:  # watchable speed when headed: a pause before each action
            cfg_file = self.dir / "playwright-mcp.json"
            cfg_file.write_text(json.dumps({"browser": {"launchOptions": {"slowMo": int(c["slow_mo_ms"])}}}))
            args += ["--config", str(cfg_file)]
        for flag in ("allowed_origins", "blocked_origins"):
            if c.get(flag):
                args += ["--" + flag.replace("_", "-"), c[flag]]
        env = dict(os.environ)
        if not headless:
            env.update(desktop_env())
        return StdioServerParameters(command=str(mcp_bin), args=args, cwd=str(self.dir), env=env)

    async def start(self):
        read, write = await self._stack.enter_async_context(stdio_client(self.params()))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return (await self.session.list_tools()).tools

    async def close(self):
        await self._stack.aclose()

    async def call(self, name, args):
        """Call a Playwright MCP tool. Returns (text, images, is_error); images are (mime, base64)."""
        try:
            res = await self.session.call_tool(name, args)
        except Exception as e:  # a failing tool must not end a long run
            return f"### Error\n{type(e).__name__}: {e}", [], True
        texts, images = [], []
        for c in res.content:
            if c.type == "text":
                texts.append(c.text)
            elif c.type == "image":
                images.append((c.mimeType, c.data))
        return self._post(("\n".join(texts))), images, bool(res.isError)

    def _post(self, text):
        m = URL_LINE.search(text)
        if m:
            self.url = m.group(1)

        def snap(m):
            p = self.dir / m.group(1)
            if not p.exists():
                return m.group(0)
            return "```yaml\n" + self._remember(p.read_text()) + "\n```"

        def cons(m):
            p = self.dir / m.group(1)
            if not p.exists():
                return m.group(0)
            lines = p.read_text().splitlines()[int(m.group(2)) - 1:int(m.group(3))]
            keep = [ln.strip() for ln in lines if "[ERROR]" in ln or "[WARNING]" in ln]
            return "- New console errors/warnings:\n" + "\n".join(keep) if keep else "- New console messages: none important"

        text = SNAP_LINK.sub(snap, text)
        if "```yaml" in text and not SNAP_LINK.search(text):  # browser_snapshot returns the yaml inline
            text = YAML_BLOCK.sub(lambda m: "```yaml\n" + self._remember(m.group(1).rstrip("\n")) + "\n```", text, 1)
        return CONSOLE_LINK.sub(cons, text)

    def _remember(self, snap):
        marked = history.mark_new(snap, self.snapshot) if self.mark_new else snap
        self.snapshot = snap
        return marked

    # ---- what is this element? (for the risky-action gate) -----------------------------------------
    def lookup_ref(self, ref):
        """Role and name of an element ref in the latest snapshot, e.g. ('button', 'Place order')."""
        for line in self.snapshot.splitlines():
            if f"[ref={ref}]" in line:
                m = re.match(r'\s*-\s*([\w-]+)(?:\s+"((?:[^"\\]|\\.)*)")?', line)
                if m:
                    return m.group(1), (m.group(2) or line.split(f"[ref={ref}]")[-1]).strip(' :"')
        return "", str(ref)

    async def element_at(self, x, y):
        """Role and visible name of the element at viewport pixel (x, y) - what a coordinate click will hit."""
        code = ("async (page) => await page.evaluate(([x, y]) => { const e = document.elementFromPoint(x, y);"
                " if (!e) return null; const t = e.closest('button,a,input,select,textarea,[role],label') || e;"
                " return { role: t.getAttribute('role') || t.tagName.toLowerCase(),"
                " name: (t.getAttribute('aria-label') || t.innerText || t.value || t.title || '').trim().slice(0, 160) };"
                f" }}, [{int(x)}, {int(y)}])")
        text, _, err = await self.call("browser_run_code_unsafe", {"code": code})
        m = RESULT.search(text)
        try:
            data = json.loads(m.group(1).strip()) if m and not err else None
        except json.JSONDecodeError:
            data = None
        return (data["role"], data["name"]) if data else ("", "")

    def resolve_upload(self, path):
        """An upload path from the model -> a copy in <run>/uploads/ of a file inside an allowed folder, or None.
        Playwright MCP only reads files under its own run folder, so allowed files are copied there; the copy is
        also a record of exactly what the agent uploaded."""
        p = Path(os.path.expanduser(path))
        candidates = [p] if p.is_absolute() else [d / p for d in self.upload_dirs] + [d / p.name for d in self.upload_dirs]
        for c in candidates:
            c = c.resolve()
            if c.is_file() and any(c.is_relative_to(d) for d in self.upload_dirs):
                if c.is_relative_to(self.dir.resolve()):
                    return str(c)
                dest = self.dir / "uploads" / c.name
                dest.parent.mkdir(exist_ok=True)
                shutil.copy2(c, dest)
                return str(dest.resolve())
        return None

    def to_px(self, x, y, coords):
        """Convert model coordinates to viewport pixels: 'norm1000' (0..1000 grid) or 'pixels'."""
        if coords == "norm1000":
            return round(x / 1000 * self.vw), round(y / 1000 * self.vh)
        return round(x), round(y)
