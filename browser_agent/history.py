"""Keeping the model's context small and current on long tasks.

Every action returns a full page snapshot, and a long task has hundreds of them. Only the newest few matter:
older snapshots and screenshots are replaced by a one-line stub. The model's plan (update_plan calls) and
its reasoning about what happened stay - that is its memory of the task.
"""
import re

SNAP_BLOCK = re.compile(r"```yaml\n.*?```", re.S)
SNAP_STUB = "[older page snapshot removed - the current page is in a later message, or call browser_snapshot]"


def compact(messages, keep_snapshots, keep_images, drop_reasoning=False):
    snaps = imgs = 0
    for m in reversed(messages):
        if m["role"] == "tool" and isinstance(m.get("content"), str) and SNAP_BLOCK.search(m["content"]):
            snaps += 1
            if snaps > keep_snapshots:
                m["content"] = SNAP_BLOCK.sub(SNAP_STUB, m["content"])
        elif m["role"] == "user" and isinstance(m.get("content"), list):
            imgs += 1
            if imgs > keep_images:
                m["content"] = m["content"][0]["text"] + " [image removed from history]"
        elif m["role"] == "assistant" and drop_reasoning:
            m.pop("reasoning_content", None)


def mark_new(snapshot, previous):
    """Append [new] to elements that were not in the previous snapshot of the same page (idea from OpenClaw).
    A completely different page gets no marks - everything would be new."""
    if not previous:
        return snapshot
    key = lambda ln: re.sub(r"\s*\[ref=e\d+\]", "", ln).strip()
    before = {key(ln) for ln in previous.splitlines()}
    lines = snapshot.splitlines()
    fresh = [i for i, ln in enumerate(lines) if "[ref=" in ln and key(ln) not in before]
    with_refs = sum(1 for ln in lines if "[ref=" in ln) or 1
    if not fresh or len(fresh) / with_refs > 0.6:
        return snapshot
    for i in fresh:
        lines[i] = re.sub(r"(\[ref=e\d+\])", r"\1 [new]", lines[i], count=1)
    return "\n".join(lines)
