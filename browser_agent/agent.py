"""The agent loop: ask the model, run its tool calls, give it the results, repeat until it calls finish.

One run = one browser + one model + one instruction. Everything goes to <run dir>/log.jsonl.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from . import config as config_mod
from . import history, prompts, report
from .browser import Browser
from .human import Human
from .llm import LLM
from .policy import Policy
from .secrets import SecretError, Secrets
from .tools import browser_tools, harness_tools

TEXT_ARGS = {"browser_type", "browser_fill_form", "type_keys"}  # where {{secret:NAME}} may appear


def normalize_finish(args):
    """Local models sometimes send findings as a JSON string or as plain strings; accept every shape."""
    f = args.get("findings")
    if isinstance(f, str):
        try:
            f = json.loads(f)
        except json.JSONDecodeError:
            f = [f]
    if isinstance(f, dict):
        f = [f]
    out = []
    for item in f or []:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                item = {"title": item, "severity": "", "steps": "", "expected": "", "actual": item}
        if isinstance(item, dict):
            out.append(item)
    args["findings"] = out
    args.setdefault("status", "done")
    args.setdefault("summary", "")
    return args


class Agent:
    def __init__(self, cfg, model_name=None, mode="task", headed=False, out_dir=None, max_steps=None, quiet=False):
        self.cfg, self.mode, self.quiet = cfg, mode, quiet
        self.a = cfg["agent"]
        self.model = config_mod.model(cfg, model_name)
        self.max_steps = max_steps or self.a["max_steps"]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        self.dir = Path(out_dir or config_mod.ROOT / "runs") / f"{stamp}-{self.model['name']}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.logf = open(self.dir / "log.jsonl", "a")
        self.secrets = Secrets(cfg["secrets"])
        self.policy = Policy(cfg["policy"])
        self.human = Human(cfg["human"], self.dir, self.log)
        self.headed = headed or not cfg["browser"].get("headless", True)
        self.browser = Browser(cfg["browser"], self.dir, config_mod.ROOT, headed)
        self.browser.mark_new = self.a["mark_new"]
        self.llm = LLM(cfg["base_url"], cfg["api_key"], self.model, on_error=lambda **kw: self.log("model_error", **kw))
        self.steps = self.tool_calls = 0
        self.result, self.messages, self.human_events = None, [], []

    # ---- logging ---------------------------------------------------------------------------------
    def log(self, kind, **data):
        data.update(t=round(time.time(), 3), step=self.steps, kind=kind)
        line = json.dumps(data, ensure_ascii=False, default=str)
        self.logf.write(self.secrets.redact(line) + "\n")
        self.logf.flush()

    def say(self, text):
        if not self.quiet:
            print(f"[{self.steps:>3}] {self.secrets.redact(text)}", flush=True)

    # ---- tools -----------------------------------------------------------------------------------
    async def gate(self, name, args):
        """The risky-action gate. Returns None to proceed, or an error text for the model."""
        if not self.policy.needs_check(name, args):
            return None
        if name == "click_at":
            x, y = self.browser.to_px(args["x"], args["y"], self.model["coords"])
            role, label = await self.browser.element_at(x, y)
        elif name == "browser_fill_form" or (name == "browser_press_key" and not args.get("target")):
            role, label = "", args.get("element", "") or "the focused element / form submit"
        else:
            role, label = self.browser.lookup_ref(args.get("target", ""))
        verdict = self.policy.judge(label, self.browser.url, role)
        if verdict.action == "allow":
            return None
        if verdict.action == "ask":
            ok, answer = await self.human.ask(
                "approval", f"Allow the agent to {name} {verdict.target} ({verdict.category})?",
                f"page: {verdict.url}\non screen:\n{self.secrets.redact(self.screen_text())}")
            self.human_events.append({"kind": "approval", "category": verdict.category, "target": verdict.target,
                                      "url": verdict.url, "approved": ok})
            if ok:
                return None
        self.log("blocked", tool=name, category=verdict.category, target=verdict.target, url=verdict.url)
        return (f"### Error\nBlocked: {verdict.category} action on {verdict.target} was not approved. Do not retry "
                "it; continue another way or finish with status blocked.")

    def screen_text(self, limit=1500):
        """The visible text of the latest snapshot, without refs - what a human needs to judge an approval
        (amount, recipient, spender, network)."""
        import re as _re
        out = []
        for ln in self.browser.snapshot.splitlines():
            ln = _re.sub(r"\s*\[(ref|cursor|new|level|active|checked|disabled)[^\]]*\]", "", ln).strip(" -:")
            if ln and not ln.startswith("/url"):
                out.append(ln)
        text = " | ".join(out)
        return text[:limit] + (" ..." if len(text) > limit else "")

    async def run_tool(self, name, args):
        blocked = await self.gate(name, args)
        if blocked:
            return blocked, [], True
        if name in TEXT_ARGS and self.secrets.uses(args):
            try:
                args = self.secrets.fill(args)
            except SecretError as e:
                return f"### Error\n{e}", [], True
        if name == "click_at":
            x, y = self.browser.to_px(args["x"], args["y"], self.model["coords"])
            await self.browser.call("browser_mouse_move_xy", {"x": x, "y": y})
            return await self.browser.call("browser_mouse_click_xy", {
                "x": x, "y": y, "button": args.get("button", "left"), "clickCount": 2 if args.get("double") else 1,
                "delay": 60})
        if name == "drag_at":
            x1, y1 = self.browser.to_px(args["x1"], args["y1"], self.model["coords"])
            x2, y2 = self.browser.to_px(args["x2"], args["y2"], self.model["coords"])
            return await self.browser.call("browser_mouse_drag_xy", {"startX": x1, "startY": y1, "endX": x2, "endY": y2})
        if name == "type_keys":
            code = (f"async (page) => {{ await page.keyboard.type({json.dumps(args['text'])}, "
                    f"{{ delay: {int(args.get('delay_ms', 40))} }}); return 'typed'; }}")
            text, imgs, err = await self.browser.call("browser_run_code_unsafe", {"code": code})
            snap, _, _ = await self.browser.call("browser_snapshot", {})
            return ("Typed." if not err else text) + "\n" + snap, imgs, err
        if name == "ask_human":
            ok, answer = await self.human.ask(args.get("kind", "question"), args.get("question", ""),
                                              f"page: {self.browser.url}")
            self.human_events.append({"kind": args.get("kind"), "question": args.get("question"), "answer": answer})
            snap, _, _ = await self.browser.call("browser_snapshot", {})
            return f"The human answered: {answer or '(no answer - timed out)'}\nCurrent page:\n{snap}", [], False
        if name == "update_plan":
            return "Plan saved.", [], False
        if name == "browser_take_screenshot":
            args = {"type": "png", **args}
        if name == "browser_file_upload" and args.get("paths"):
            resolved = [self.browser.resolve_upload(x) for x in args["paths"]]
            if None in resolved:
                bad = [x for x, r in zip(args["paths"], resolved) if r is None]
                allowed = ", ".join(str(d) for d in self.browser.upload_dirs[1:]) or "none configured"
                return (f"### Error\nCannot upload {bad}: not found in the allowed upload folders ({allowed}). "
                        "Use a file name from those folders."), [], True
            args = {**args, "paths": resolved}
        if name == "browser_navigate" and str(args.get("url", "")).startswith("view-source:") \
                and not self.a["allow_view_source"]:
            return ("### Error\nview-source: is disabled. Work through the page like a user does; use "
                    "browser_snapshot, browser_find or a screenshot to see it."), [], True
        text, imgs, err = await self.browser.call(name, args)
        if name == "browser_resize" and not err:  # click_at converts against the real viewport
            self.browser.vw, self.browser.vh = int(args["width"]), int(args["height"])
        return text, imgs, err

    # ---- the loop --------------------------------------------------------------------------------
    async def run(self, task, url=None):
        self.task, self.t0 = task, time.time()
        try:
            mcp_tools = await self.browser.start()
            tools = browser_tools(mcp_tools, set(self.cfg["browser"]["hidden_tools"]), self.model["vision"])
            tools += harness_tools(self.model["coords"], self.model["vision"])
            if self.cfg["browser"]["record_trace"]:
                await self.browser.call("browser_start_tracing", {})
            if self.cfg["browser"]["record_video"]:
                await self.browser.call("browser_start_video", {"filename": "video.webm"})
            if self.cfg["browser"].get("show_actions") and self.headed:  # label each action on the page
                await self.browser.call("browser_video_show_actions", {})
            first = f"INSTRUCTION:\n{task}"
            if url:
                text, _, _ = await self.browser.call("browser_navigate", {"url": url})
                first += f"\n\nThe browser is open at {url}. Current page:\n{self.secrets.redact(text)}"
            system = prompts.TEST if self.mode == "test" else prompts.TASK
            names = ", ".join(self.secrets.names()) if self.cfg["secrets"]["provider"] != "none" else "none configured"
            self.messages = [{"role": "system", "content": system.replace("{secret_names}", names)},
                             {"role": "user", "content": first}]
            self.log("start", task=task, url=url, model=self.model["id"], mode=self.mode,
                     tools=[t["function"]["name"] for t in tools])
            await self.loop(tools)
        except Exception as e:
            self.log("crash", error=f"{type(e).__name__}: {e}")
            self.result = {"status": "error", "summary": f"The harness stopped with {type(e).__name__}: {e}"}
            raise
        finally:
            await self.wrap_up()
        return self.result

    async def loop(self, tools):
        idle, recent = 0, []
        while self.steps < self.max_steps:
            self.steps += 1
            over = self.llm.usage["last_prompt"] > self.a["context_budget"]
            history.compact(self.messages, 1 if over else self.a["keep_snapshots"],
                            0 if over else self.a["keep_screenshots"], drop_reasoning=over)
            t0 = time.time()
            msg, finish_reason, usage = await self.llm.chat(self.messages, tools)
            calls = msg.get("tool_calls") or []
            reasoning = msg.get("reasoning_content") or msg.get("reasoning")
            self.log("model", secs=round(time.time() - t0, 1), usage=usage, finish_reason=finish_reason,
                     content=msg.get("content"), reasoning=reasoning, tool_calls=calls)
            am = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                am["tool_calls"] = calls
            if reasoning and self.a["keep_reasoning"]:
                am["reasoning_content"] = reasoning
            self.messages.append(am)
            if not calls:
                idle += 1
                if idle >= 3:
                    self.result = {"status": "failed", "summary": "The model stopped calling tools.",
                                   "answer": msg.get("content") or ""}
                    return
                self.messages.append({"role": "user", "content":
                                      "Continue with the tools. When the instruction is done or blocked, call finish."})
                continue
            idle, images = 0, []
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError as e:
                    self.messages.append({"role": "tool", "tool_call_id": c["id"],
                                          "content": f"### Error\nArguments were not valid JSON: {e}"})
                    continue
                if name == "finish":
                    self.result = args = normalize_finish(args)
                    self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": "Run finished."})
                    self.log("finish", **args)
                    self.say(f"finish: {args.get('status')} - {args.get('summary', '')[:200]}")
                    return
                self.tool_calls += 1
                self.say(f"{name} {json.dumps(args, ensure_ascii=False)[:160]}")
                t0 = time.time()
                out, imgs, err = await self.run_tool(name, args)
                out = self.secrets.redact(out)
                self.log("tool", name=name, args=args, secs=round(time.time() - t0, 2), error=err,
                         result=out[:4000], images=len(imgs))
                recent = (recent + [(name, json.dumps(args, sort_keys=True))])[-self.a["repeat_limit"]:]
                if len(recent) == self.a["repeat_limit"] and len(set(recent)) == 1 and name != "browser_snapshot":
                    out += (f"\n\nNOTE: you made the same call {len(recent)} times in a row. It is not working. Stop, "
                            "look at the page (take a screenshot) and try a different approach.")
                cap = self.a["max_tool_chars"]
                if len(out) > cap:
                    out = out[:cap] + f"\n[... cut at {cap} characters; use browser_find to search the page]"
                left = self.max_steps - self.steps
                if left <= max(3, self.max_steps // 10):  # long tasks: warn before the budget runs out
                    out += (f"\n\nBUDGET: {left} model turns left. Wrap up: finish the current step, then call "
                            "finish with everything you found so far.")
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                images += [(name, i) for i in imgs]
            if images and self.model["vision"]:
                name, (mime, data) = images[-1]
                self.messages.append({"role": "user", "content": [
                    {"type": "text", "text": f"Image returned by {name} (viewport {self.browser.vw}x{self.browser.vh}):"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]})
        await self.forced_finish(tools)

    async def forced_finish(self, tools):
        """Out of steps: one last call that can only finish, so the work done so far is reported, not lost."""
        self.messages.append({"role": "user", "content": "The step budget is used up. Call finish now: status "
                              "failed unless the instruction is fully done, a summary of what you did and found, "
                              "and all findings so far."})
        finish_only = [t for t in tools if t["function"]["name"] == "finish"]
        try:
            msg, _, _ = await self.llm.chat(self.messages, finish_only)
            for c in msg.get("tool_calls") or []:
                if c["function"]["name"] == "finish":
                    args = normalize_finish(json.loads(c["function"].get("arguments") or "{}"))
                    args["summary"] = f"[step limit reached] {args.get('summary', '')}"
                    self.result = args
                    self.log("finish", forced=True, **args)
                    return
        except Exception as e:
            self.log("forced_finish_error", error=str(e))
        self.result = {"status": "step-limit", "summary": f"Stopped after {self.max_steps} model turns."}

    async def wrap_up(self):
        evidence = {}
        try:
            for name, args in (("browser_console_messages", {"level": "error"}),
                               ("browser_network_requests", {"static": False})):
                text, _, _ = await self.browser.call(name, args)
                evidence[name] = self.secrets.redact(text)[:6000]
            if self.cfg["browser"]["record_video"]:
                await self.browser.call("browser_stop_video", {})
            if self.cfg["browser"]["record_trace"]:
                await self.browser.call("browser_stop_tracing", {})
        except Exception as e:  # the browser may be gone already
            evidence["error"] = str(e)
        finally:
            try:
                await self.browser.close()
            except Exception:
                pass
            await self.llm.close()
        scrubbed = self.secrets.scrub_dir(self.dir)  # Playwright's own snapshots/trace record typed values
        removed = []
        if self.secrets.used() and not self.cfg["browser"].get("keep_media_with_secrets", True):
            for p in list(self.dir.rglob("*.png")) + list(self.dir.rglob("*.webm")):
                p.unlink()
                removed.append(p.name)
        if scrubbed or removed:
            self.log("scrubbed", text_files=scrubbed, media_removed=len(removed))
        res = self.result or {"status": "error", "summary": "The run ended without a result (see log.jsonl)."}
        rep = {"task": self.task, "mode": self.mode, "model": self.model["id"], "steps": self.steps,
               "tool_calls": self.tool_calls, "seconds": round(time.time() - self.t0), "tokens": self.llm.usage,
               "human": self.human_events, "result": res, "evidence": evidence, "run_dir": str(self.dir)}
        rep = json.loads(self.secrets.redact(json.dumps(rep, ensure_ascii=False)))
        (self.dir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
        (self.dir / "report.md").write_text(report.render(rep))
        self.log("end", status=res.get("status"), steps=self.steps, seconds=rep["seconds"])
        self.say(f"status: {res.get('status')}  steps: {self.steps}  time: {rep['seconds']} s  "
                 f"report: {self.dir / 'report.md'}")
        self.report = rep
