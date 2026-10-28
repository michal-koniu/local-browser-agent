"""The tool list the model sees: Playwright MCP's browser tools (minus hidden ones) plus the harness's own tools."""
from .prompts import COORDS

# Never shown to the model: the harness drives tracing/video itself, raw *_xy mouse tools are replaced by
# click_at/drag_at (coordinate conversion + the risky-action gate), the rest run arbitrary code or need a human.
ALWAYS_HIDDEN = {
    "browser_run_code_unsafe", "browser_evaluate", "browser_annotate", "browser_resume",
    "browser_start_recording", "browser_stop_recording", "browser_start_tracing", "browser_stop_tracing",
    "browser_start_video", "browser_stop_video", "browser_video_chapter", "browser_video_show_actions",
    "browser_video_hide_actions", "browser_highlight", "browser_hide_highlight",
    "browser_mouse_move_xy", "browser_mouse_click_xy", "browser_mouse_drag_xy", "browser_mouse_down",
    "browser_mouse_up",
}

DESCRIPTIONS = {
    "browser_take_screenshot": "Take a screenshot of the current viewport to SEE the page: layout, visual bugs, "
                               "canvas, game boards, icons, elements missing from the snapshot. Read click_at / "
                               "drag_at coordinates from it (use a viewport screenshot, not fullPage, for that).",
}


def fn(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


def harness_tools(coords, vision):
    where = COORDS[coords]
    tools = [
        fn("update_plan", "Write or replace your plan and progress notes: numbered steps, done ones marked, values "
           "you found. Kept in full while older page states are removed.", {"plan": {"type": "string"}}, ["plan"]),
        fn("type_keys", "Type text key by key into the element that has focus, like a person (click the field "
           "first). May contain {{secret:NAME}}. For special keys use browser_press_key.",
           {"text": {"type": "string"}, "delay_ms": {"type": "number", "description": "pause between keys, default 40"}},
           ["text"]),
        fn("ask_human", "Ask the human for something only they can do or decide: solve a CAPTCHA in the browser, "
           "enter a 2FA code, log in, approve, answer a question. Waits for the answer.",
           {"kind": {"type": "string", "enum": ["captcha", "2fa", "login", "approval", "question"]},
            "question": {"type": "string", "description": "What you need, in one or two sentences"}},
           ["kind", "question"]),
        fn("finish", "End the run. status: done (completed), failed (could not complete), blocked (needs a human or "
           "a permission you do not have).", {
               "status": {"type": "string", "enum": ["done", "failed", "blocked"]},
               "summary": {"type": "string", "description": "What you did, what you saw, anything suspicious"},
               "answer": {"type": "string", "description": "The answer or the result values (e.g. order number)"},
               "findings": {"type": "array", "description": "Bugs found (test mode)", "items": {
                   "type": "object", "properties": {
                       "title": {"type": "string"}, "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                       "steps": {"type": "string"}, "expected": {"type": "string"}, "actual": {"type": "string"},
                       "evidence": {"type": "string"}},
                   "required": ["title", "severity", "steps", "expected", "actual"]}}},
           ["status", "summary"]),
    ]
    if vision:
        tools += [
            fn("click_at", f"Move the mouse to a point and click, like a person. Coordinates: {where}, read from the "
               "LATEST viewport screenshot.", {
                   "x": {"type": "number"}, "y": {"type": "number"},
                   "label": {"type": "string", "description": "What you are clicking, as seen on screen"},
                   "button": {"type": "string", "enum": ["left", "right", "middle"]},
                   "double": {"type": "boolean"}}, ["x", "y", "label"]),
            fn("drag_at", f"Press the mouse at (x1,y1), move to (x2,y2) and release - drag and drop, sliders, game "
               f"pieces. Coordinates: {where}.", {
                   "x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"},
                   "y2": {"type": "number"}, "label": {"type": "string"}}, ["x1", "y1", "x2", "y2", "label"]),
        ]
    return tools


def browser_tools(mcp_tools, hidden, vision):
    out = []
    for t in mcp_tools:
        if t.name in ALWAYS_HIDDEN or t.name in hidden:
            continue
        if t.name == "browser_take_screenshot" and not vision:
            continue
        out.append({"type": "function", "function": {
            "name": t.name, "description": DESCRIPTIONS.get(t.name, t.description or ""), "parameters": t.inputSchema}})
    return out
