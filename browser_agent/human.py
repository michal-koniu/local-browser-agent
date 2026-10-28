"""The human channel: approvals (pay, sign, post) and help requests (CAPTCHA, 2FA, a login, a question).

Modes (config [human] mode):
  terminal     ask on the terminal the run was started from
  file         write <run>/pending.json, run notify_command, then wait for an answer: the file <run>/answer.txt
               (or `python -m browser_agent answer <run> yes|no|<text>` from any shell)
  auto         answer automatically with auto_answer ("approve" or "deny") - for tests and evaluations only
  auto-detect  terminal when stdin is a terminal, otherwise file
Unanswered requests are denied after timeout_s - nothing waits forever and nothing is approved by silence.
"""
import asyncio
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

YES = {"y", "yes", "approve", "approved", "allow", "ok", "done"}


class Human:
    def __init__(self, cfg, run_dir, log):
        mode = cfg.get("mode", "auto-detect")
        if mode == "auto-detect":
            mode = "terminal" if sys.stdin.isatty() else "file"
        self.mode, self.cfg, self.dir, self.log = mode, cfg, Path(run_dir), log
        self.timeout = cfg.get("timeout_s", 900)

    def notify(self, title, body):
        cmd = self.cfg.get("notify_command")
        if cmd:  # e.g. notify-send, a curl to ntfy / a chat bot; {title} and {body} are shell-quoted
            subprocess.run(cmd.format(title=shlex.quote(title), body=shlex.quote(body)), shell=True, timeout=30)

    async def ask(self, kind, question, details=""):
        """kind: approval | captcha | login | 2fa | question. Returns (approved: bool, answer_text)."""
        self.log("human_request", request=kind, question=question, details=details, mode=self.mode)
        if self.mode == "auto":
            answer = self.cfg.get("auto_answer", "deny")
        elif self.mode == "terminal":
            print(f"\n=== The agent needs you ({kind}) ===\n{question}\n{details}".rstrip(), flush=True)
            hint = "[y/N]" if kind == "approval" else "(type your answer, or 'done' when finished)"
            try:
                answer = await asyncio.wait_for(asyncio.to_thread(input, f"{hint} > "), self.timeout)
            except asyncio.TimeoutError:
                answer = ""
        else:
            answer = await self._ask_file(kind, question, details)
        approved = answer.strip().lower() in YES
        self.log("human_answer", request=kind, answer=answer, approved=approved)
        return approved, answer

    async def _ask_file(self, kind, question, details):
        pending, answer_file = self.dir / "pending.json", self.dir / "answer.txt"
        answer_file.unlink(missing_ok=True)
        pending.write_text(json.dumps({"kind": kind, "question": question, "details": details,
                                       "asked_at": time.time(), "answer_file": str(answer_file)}, indent=2))
        self.notify(f"Browser agent needs you: {kind}",
                    f"{question}\n{details}\nAnswer: python -m browser_agent answer {self.dir} yes|no|<text>")
        print(f"[waiting for a human: {kind}] answer with: python -m browser_agent answer {self.dir} ...", flush=True)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if answer_file.exists():
                text = answer_file.read_text().strip()
                answer_file.unlink()
                pending.unlink(missing_ok=True)
                return text
            await asyncio.sleep(2)
        pending.unlink(missing_ok=True)
        return ""
