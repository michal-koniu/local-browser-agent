# How it works: one step, end to end

This page follows one instruction through the code. Read it with the files open.

## 0. Start (`cli.py` → `agent.py: Agent.run`)

`python -m browser_agent run --url https://shop.example "Buy a fern with my card"`

1. `config.load()` merges `config.toml` over the defaults in `config.py`.
2. `Agent.__init__` creates the run folder `runs/<time>-<model>/` and builds the parts:
   `Secrets`, `Policy`, `Human`, `Browser` and `LLM`.
3. `Browser.start()` launches **Playwright MCP** as a child process over stdio
   (`node_modules/.bin/playwright-mcp --browser chrome --isolated --headless --caps vision,pdf,devtools
   --output-dir runs/... --viewport-size 1440x900`). It returns its tool list: `browser_navigate`, `browser_click`,
   `browser_type`, `browser_press_key`, `browser_snapshot`, `browser_take_screenshot`, about 40 in all.
4. `tools.browser_tools()` drops the tools the model must not have, such as arbitrary JavaScript, raw mouse
   coordinates and recording control. `tools.harness_tools()` adds our own: `update_plan`, `type_keys`, `ask_human`,
   `finish`, and for vision models `click_at` and `drag_at`.
5. The harness starts the trace and the video, opens `--url`, and builds the first two messages:
   - **system**: `prompts.TASK`, with the secret *names* filled in (never the values);
   - **user**: the instruction plus the current page state.

## 1. The model decides (`agent.py: loop` → `llm.py: chat`)

The whole message list and the tool list go to `POST {base_url}/chat/completions`. A typical first answer is a
tool call:

```json
{"name": "update_plan", "arguments": "{\"plan\": \"1. Find ferns 2. Add cheapest 3. Checkout 4. Pay with card\"}"}
```

Before each call, `history.compact()` replaces all but the newest 2 page snapshots and the newest screenshot with
a one-line stub. This is the most important thing for long tasks: the model always sees the current page and its
own plan, never 80 old pages.

## 2. The harness acts (`agent.py: run_tool`)

Say the model calls `browser_click {"element": "Pay now button", "target": "e47"}`.

1. **Gate** (`gate()` → `policy.py`): `browser_click` is a gated tool. The harness looks up what `e47` *really* is in
   the latest snapshot (`Browser.lookup_ref("e47")` → `("button", "Pay now")`). The model's own label is ignored,
   because injected page text could make the model call it "Continue". The rule `payment` matches, so the action
   is `ask`.
2. **Human** (`human.py`): on a terminal you see `Allow the agent to browser_click button "Pay now" (payment)?` and
   answer y or N. In `file` mode the harness writes `pending.json`, runs your `notify_command`, and waits for
   `answer.txt`. Silence means no.
3. **Secrets** (`secrets.py`): if the tool is `browser_type`, `browser_fill_form` or `type_keys` and its arguments
   contain `{{secret:NAME}}`, the value is filled in now. This happens on a copy, so the model's own message keeps
   the placeholder.
4. **Browser** (`browser.py: call`): the tool goes to Playwright MCP, which finds the element, scrolls to it, waits
   until it can be clicked, and clicks with real mouse events.

## 3. The result goes back (`browser.py: _post`)

Playwright MCP answers with Markdown: the code it ran, the page URL and title, and a **link** to a snapshot file. The
harness:
- reads the snapshot file and puts it inline as a ```` ```yaml ```` block, so the model sees the page after every
  action without spending a turn on it;
- marks elements that were not in the previous snapshot with `[new]` (`history.mark_new`). These are usually the
  message, error or dialog the action produced;
- replaces console links with the error and warning lines;
- stores the snapshot (for the next ref lookup) and the URL (for policy rules).

Then `secrets.redact()` replaces any secret value in the text, including card numbers written with spaces or dashes,
with `[secret:NAME]`. The text is capped at `max_tool_chars` and appended as a `tool` message. If the tool returned a
screenshot and the model has vision, the image goes in a `user` message right after it.

## 4. Guards on the loop

- **No tool call:** the model is reminded to use tools or finish. After 3 replies in a row without a tool call, the
  run fails.
- **The same call 3 times:** the result gets a note telling the model to stop and try another way.
- **Context over budget** (`context_budget`): the history is compacted harder, keeping 1 snapshot, no images and no
  reasoning.
- **`max_steps`:** the run ends with status `step-limit`.

## 5. The end (`wrap_up`)

When the model calls `finish`, or something stops the run, the harness collects console errors and network
requests, stops the video and trace, closes the browser, and writes `report.json` and `report.md`. Every model turn
and tool call is already in `log.jsonl`, with secrets redacted.

## Coordinates (vision fallback)

`click_at {"x": 412, "y": 655, "label": "Fern"}` is read in the model's convention. `coords = "norm1000"` means a
0–1000 grid, which Qwen-family vision models use. `Browser.to_px` converts it to viewport pixels. The gate asks the
page what is there (`document.elementFromPoint`) before clicking. Then the mouse moves to the point and clicks with a
60 ms press, the way a person does. Run `python -m browser_agent calibrate` for each new model to measure its
convention.

## Where to read the trace

`npx playwright show-trace runs/<run>/traces/<file>.trace` shows every action with before and after DOM snapshots,
console and network. It is the fastest way to see *why* a step failed. `log.jsonl` shows what the model *thought*:
its reasoning, if the server returns it, and its tool calls.
