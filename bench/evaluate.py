#!/usr/bin/env python3
"""Run the evaluation tasks (evals/tasks.toml) against an engine and score them with evals/checks.py.

  .venv/bin/python bench/evaluate.py --engine harness --tasks all -k 2
  .venv-bu/bin/python bench/evaluate.py --engine browser-use --tasks shop_e2e_card,chess_p1 -k 2

For each task and repetition: reset the fixture server, run the engine with the task's instruction and start URL,
read the server state, run the check, and append a row to bench/results/<engine>-<time>.jsonl. A summary table
(pass rate, mean score, steps, time) is printed and written next to it as .md.

The fixture server is started automatically on --port unless --no-server is given. Secrets come from
evals/secrets.env (fake values). Approvals: the harness runs with --human auto and the task's auto_answer
(approve by default, deny for tasks that list "deny" in needs_human); browser-use has no approval gate.
"""
import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_checks():
    spec = importlib.util.spec_from_file_location("checks", ROOT / "evals" / "checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http(base, path, method="GET"):
    req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def dotenv(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---- engines -------------------------------------------------------------------------------------------
async def run_harness(task, url, out_dir, args):
    from browser_agent import config as config_mod
    from browser_agent.agent import Agent
    cfg = config_mod.load(args.config)
    if not args.secrets_from_config:  # default: the fake values in evals/secrets.env
        cfg["secrets"].update(provider="dotenv", dotenv_path=str(ROOT / "evals" / "secrets.env"))
    cfg["human"].update(mode="auto", auto_answer="deny" if "deny" in task.get("needs_human", []) else "approve")
    cfg["browser"]["mode"] = "isolated"
    cfg["browser"]["upload_dirs"] = [str(ROOT / "evals" / "fixtures" / "assets")]
    agent = Agent(cfg, args.model, task.get("mode", "task"), out_dir=out_dir,
                  max_steps=task.get("max_steps") or args.max_steps, quiet=True)
    try:
        await agent.run(task["instruction"], url)
    except Exception as e:  # the report is still written by wrap_up
        print(f"  harness error: {e}", flush=True)
    return agent.report


async def run_browser_use(task, url, out_dir, args):
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
    from browser_use import Agent, BrowserProfile, ChatOpenAI
    from browser_agent import config as config_mod
    cfg = config_mod.load(args.config)
    m = config_mod.model(cfg, args.model)
    run_dir = Path(out_dir) / f"{datetime.now():%Y%m%d-%H%M%S}-browser-use-{task['id']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    llm = ChatOpenAI(model=m["id"], base_url=cfg["base_url"], api_key=cfg["api_key"],
                     temperature=m.get("temperature", 0.6), top_p=m.get("top_p", 0.95),
                     max_completion_tokens=m["max_tokens"], timeout=900)
    profile = BrowserProfile(channel="chrome", headless=True, viewport={"width": 1440, "height": 900},
                             record_video_dir=str(run_dir), user_data_dir=None, keep_alive=False)
    secrets = dotenv(ROOT / "evals" / "secrets.env")
    instruction = (f"{task['instruction']}\n\nStart at {url}. Secrets are available by name: "
                   + ", ".join(secrets))
    agent = Agent(task=instruction, llm=llm, browser_profile=profile, sensitive_data=secrets,
                  use_vision=m.get("vision", False), max_failures=3,
                  save_conversation_path=str(run_dir / "conversation"), directly_open_url=True)
    t0 = time.time()
    status, answer, steps, err = "error", "", 0, ""
    try:
        hist = await agent.run(max_steps=task.get("max_steps") or args.max_steps)
        steps = hist.number_of_steps()
        answer = hist.final_result() or ""
        status = "done" if hist.is_done() and hist.is_successful() is not False else "failed"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    rep = {"task": task["instruction"], "mode": task.get("mode", "task"), "model": m["id"], "steps": steps,
           "seconds": round(time.time() - t0), "run_dir": str(run_dir),
           "result": {"status": status, "summary": err or answer[:2000], "answer": answer,
                      # browser-use returns free text; give it to the QA check as one finding
                      "findings": [{"title": answer, "severity": "major", "steps": "", "expected": "",
                                    "actual": answer}] if task.get("mode") == "test" else []}}
    (run_dir / "report.json").write_text(json.dumps(rep, indent=2))
    return rep


ENGINES = {"harness": run_harness, "browser-use": run_browser_use}


# ---- main ----------------------------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=list(ENGINES), default="harness")
    p.add_argument("--tasks", default="all", help="comma-separated task ids, or all")
    p.add_argument("-k", type=int, default=1, help="repetitions per task")
    p.add_argument("--port", type=int, default=18940)
    p.add_argument("--no-server", action="store_true", help="the fixture server is already running")
    p.add_argument("--model")
    p.add_argument("--config")
    p.add_argument("--max-steps", type=int, default=80)
    p.add_argument("--secrets-from-config", action="store_true",
                   help="harness: use the [secrets] store from the config (e.g. Bitwarden) instead of evals/secrets.env")
    args = p.parse_args()

    tasks = tomllib.loads((ROOT / "evals" / "tasks.toml").read_text())["task"]
    if args.tasks != "all":
        wanted = args.tasks.split(",")
        tasks = [t for t in tasks if t["id"] in wanted]
    checks = load_checks()
    base = f"http://127.0.0.1:{args.port}"
    server = None
    if not args.no_server:
        server = subprocess.Popen([sys.executable, str(ROOT / "evals/fixtures/server.py"), "--port", str(args.port)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / f"{args.engine}-{stamp}.jsonl"
    rows = []
    try:
        for task in tasks:
            for rep_i in range(args.k):
                http(base, "/__reset", "POST")
                t0 = time.time()
                report = asyncio.run(ENGINES[args.engine](task, base + task["start_path"], out / "runs", args))
                state = http(base, "/__state")
                verdict = getattr(checks, f"check_{task['id']}")(state, report or {})
                row = {"engine": args.engine, "task": task["id"], "rep": rep_i, "passed": verdict["passed"],
                       "score": verdict["score"], "notes": verdict.get("notes", []),
                       "status": (report or {}).get("result", {}).get("status"),
                       "steps": (report or {}).get("steps"), "seconds": round(time.time() - t0),
                       "run_dir": os.path.relpath((report or {}).get("run_dir") or ".", ROOT)}
                rows.append(row)
                with open(rows_path, "a") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{task['id']:28} rep {rep_i}  {'PASS' if row['passed'] else 'fail'}  score {row['score']:.2f}"
                      f"  status {row['status']}  steps {row['steps']}  {row['seconds']} s", flush=True)
    finally:
        if server:
            server.terminate()
    lines = [f"# {args.engine} - {stamp}", "", "| task | passed | mean score | mean steps | mean s |",
             "|---|---:|---:|---:|---:|"]
    for tid in dict.fromkeys(r["task"] for r in rows):
        rs = [r for r in rows if r["task"] == tid]
        mean = lambda key: sum((r[key] or 0) for r in rs) / len(rs)
        lines.append(f"| {tid} | {sum(r['passed'] for r in rs)}/{len(rs)} | {mean('score'):.2f} | "
                     f"{mean('steps'):.0f} | {mean('seconds'):.0f} |")
    if rows:
        lines += ["", f"**Total: {sum(r['passed'] for r in rows)}/{len(rows)} passed, mean score "
                      f"{sum(r['score'] for r in rows) / len(rows):.2f}**"]
    rows_path.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
