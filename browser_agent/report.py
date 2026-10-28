"""report.md: what a person reads after a run."""


def render(r):
    res = r["result"]
    t = r["tokens"]
    out = [f"# Browser agent run: {res.get('status')}", "",
           f"- Instruction: {r['task']}", f"- Mode: {r['mode']}, model: {r['model']}",
           f"- Steps: {r['steps']}, tool calls: {r['tool_calls']}, time: {r['seconds']} s, "
           f"tokens: {t['prompt']} prompt / {t['completion']} completion in {t['calls']} model calls",
           "", "## Summary", "", res.get("summary", "")]
    if res.get("answer"):
        out += ["", "## Answer", "", res["answer"]]
    for i, f in enumerate(res.get("findings") or [], 1):
        out += ["", f"## Finding {i}: {f.get('title')} ({f.get('severity')})", "",
                f"**Steps:** {f.get('steps')}", "", f"**Expected:** {f.get('expected')}", "",
                f"**Actual:** {f.get('actual')}", "", f"**Evidence:** {f.get('evidence', '')}"]
    if r.get("human"):
        out += ["", "## Human decisions", ""] + [f"- {h}" for h in r["human"]]
    out += ["", "## Evidence collected by the harness", ""]
    for k, v in r["evidence"].items():
        out += [f"### {k}", "", "```", v, "```", ""]
    out += ["## Files in this folder", "",
            "- `log.jsonl`: every model turn and tool call (secret values redacted)",
            "- `video.webm`: the screen recording",
            "- `traces/`: the Playwright trace (`npx playwright show-trace traces/<file>.trace`)",
            "- `page-*.yml`, `page-*.png`: snapshots and screenshots",
            "", "Text files here (snapshots, trace, logs) are scrubbed of secret values when the run ends. The video "
            "and screenshots show the screen as it was, including typed secrets that were visible - treat run "
            "folders as sensitive, or set keep_media_with_secrets = false."]
    return "\n".join(out) + "\n"
