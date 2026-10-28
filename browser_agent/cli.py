"""Command line: python -m browser_agent <command> ...

  run        carry out an instruction in the browser
  calibrate  measure the model's screenshot coordinate convention
  answer     answer a waiting run (approval, CAPTCHA done, a question) from any shell
  secrets    list the secret names the model may use (never the values)
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import config as config_mod


def main(argv=None):
    p = argparse.ArgumentParser(prog="browser_agent", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="TOML file (default: config.toml, else config.example.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="carry out an instruction")
    r.add_argument("instruction", nargs="?", help="what to do, in plain words")
    r.add_argument("--file", help="read the instruction from a file")
    r.add_argument("--url", help="open this page before the model starts")
    r.add_argument("--mode", choices=["task", "test"], default="task", help="test = QA tester that reports bugs")
    r.add_argument("--model", help="a [models.NAME] table from the config")
    r.add_argument("--browser-mode", choices=["isolated", "profile", "cdp"], help="override [browser] mode")
    r.add_argument("--profile", help="profile name for --browser-mode profile (keeps logins)")
    r.add_argument("--cdp", help="CDP endpoint of your own Chrome, e.g. http://127.0.0.1:9222 (implies cdp mode)")
    r.add_argument("--headed", action="store_true", help="show the browser window (needs a desktop session)")
    r.add_argument("--human", choices=["terminal", "file", "auto"], help="override [human] mode")
    r.add_argument("--auto-answer", choices=["approve", "deny"], help="answer for --human auto")
    r.add_argument("--max-steps", type=int)
    r.add_argument("--out", help="directory for run folders (default ./runs)")
    r.add_argument("--quiet", action="store_true")

    c = sub.add_parser("calibrate", help="measure the coordinate convention of a vision model")
    c.add_argument("--model")

    a = sub.add_parser("answer", help="answer a run that waits for a human")
    a.add_argument("run_dir")
    a.add_argument("text", help="yes / no / done / any text")

    sub.add_parser("secrets", help="list secret names available to the model")

    args = p.parse_args(argv)
    cfg = config_mod.load(args.config)

    if args.cmd == "answer":
        run = Path(args.run_dir)
        pending = run / "pending.json"
        if pending.exists():
            print("answering:", json.loads(pending.read_text()).get("question"))
        (run / "answer.txt").write_text(args.text)
        return 0
    if args.cmd == "secrets":
        from .secrets import Secrets
        print("\n".join(Secrets(cfg["secrets"]).names()) or "(none)")
        return 0
    if args.cmd == "calibrate":
        from . import calibrate
        asyncio.run(calibrate.run(cfg, args.model))
        return 0

    instruction = Path(args.file).read_text() if args.file else args.instruction
    if not instruction:
        p.error("give an instruction or --file")
    b = cfg["browser"]
    if args.cdp:
        b["mode"], b["cdp_endpoint"] = "cdp", args.cdp
    if args.browser_mode:
        b["mode"] = args.browser_mode
    if args.profile:
        b["profile"] = args.profile
    if args.human:
        cfg["human"]["mode"] = args.human
    if args.auto_answer:
        cfg["human"]["auto_answer"] = args.auto_answer
    from .agent import Agent
    agent = Agent(cfg, args.model, args.mode, args.headed, args.out, args.max_steps, args.quiet)
    result = asyncio.run(agent.run(instruction, args.url))
    return 0 if result and result.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
