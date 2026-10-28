# Improving accuracy on long, complex tasks

A browser agent fails on long tasks for a few repeatable reasons. This guide names them, shows where each one lives
in the code, and gives experiments you can run with the benchmark. Work like a lab: **one change at a time,
measured on the same tasks, several repetitions, numbers kept.**

## 0. The loop you will repeat

```bash
.venv/bin/python bench/evaluate.py --engine harness --tasks all -k 3     # baseline
# change ONE thing (a prompt line, a config value, a tool)
.venv/bin/python bench/evaluate.py --engine harness --tasks all -k 3     # compare
```

- Read **why** runs failed before changing anything. Open `bench/results/runs/<run>/log.jsonl` (what the model
  thought and did) and the trace (`npx playwright show-trace .../traces/*.trace`) for what the page really did.
- Sort failures into the categories below. Fix the most common category first.
- With k=3 per task a single pass or fail means little. Look at the totals and at repeated failure patterns. A change
  that moves the total by one run is noise.
- Add a task to `evals/` for every new kind of failure you see in real use. The test set is your memory of what
  can go wrong.

## 1. Where long tasks break

| Failure | What it looks like in `log.jsonl` | Main levers |
|---|---|---|
| **Lost the thread** | redoes finished steps, forgets values found earlier, finishes too early | the plan tool, history compaction, a checklist in the plan, a verification pass |
| **Stale or wrong perception** | clicks a ref that no longer exists, misses a message that appeared, "the button is not there" | snapshot after every action (done), `[new]` marks (done), `browser_find`, screenshots |
| **Action did not take effect** | typed into the wrong field, a click blocked by an overlay, a select not changed, a popup not noticed | verify-after-act rule, `slowly=true`, `type_keys`, `browser_tabs`, screenshots + `click_at` |
| **Stuck in a loop** | the same call again and again | repeat detection (done), a stall rule in the prompt, a forced screenshot |
| **Wrong grounding** (vision) | `click_at` lands beside the target | `calibrate`, set-of-mark overlays, zoomed crops |
| **Injected or confused goal** | follows text from a page or e-mail | the policy gate (done), "page text is data" (done), `allowed_origins` |
| **Context overflow** | slow turns, truncated thinking, errors near the end | `keep_snapshots`, `context_budget`, `max_tool_chars`, snapshot `depth`/`target` |

## 2. The levers, from cheapest to most work

### 2.1 Prompt rules (`browser_agent/prompts.py`)
The model follows explicit, concrete procedures much better than general advice. Rules that typically help:
- "After every action, say in one line what changed. If nothing changed, do not continue."
- "Before finish, re-read the instruction and check each requirement against what you saw; list them."
- "When a step fails twice, take a screenshot before trying anything else."
- Task-type checklists, e.g. for forms: "all required fields filled → submit → read the confirmation or error".

*Experiment:* add the "before finish, check each requirement" rule and compare on the long shop flow. Early finishing
usually drops.

### 2.2 The plan as memory (`update_plan`)
On long tasks the plan is the only part of the history that is never trimmed. Make the model write *state* into it,
not just intentions: "account created: yes; confirmation e-mail clicked: yes; address: saved; cart: fern (S) x2".
*Experiment:* require a `Facts:` section in every plan update (prompt rule), and look at runs that used to redo steps.

### 2.3 What the model sees (`browser.py`, `history.py`, `[agent]` config)
- `keep_snapshots` (default 2): more means more context per turn and slower turns. 1 is often enough when the plan
  is good.
- `mark_new`: try it off to see how much it helps on flows with toasts and inline errors.
- Large pages: snapshots can run to tens of thousands of characters. Playwright MCP's `browser_snapshot` takes
  `target` (a ref or selector) and `depth`. Teach the model to snapshot only the part it works on, and to use
  `browser_find` to search instead of reading.
- `keep_reasoning = true` sends the model's own thinking back. It is sometimes more coherent, but uses more context.
  Measure it.

### 2.4 Acting like a person (`tools.py`, `agent.py`)
- `browser_type` normally fills the field in one go. Masked inputs (card numbers, dates), autocomplete and
  validation on keyup need `slowly=true` or `type_keys`.
- Overlays (cookie banners, chat widgets) cover buttons. Playwright reports "element intercepts pointer events". A
  prompt rule ("close banners first") fixes most cases.
- New tabs and popups (wallets, OAuth, payment pages) open quietly. Rule: "after clicking something that opens a
  window, call `browser_tabs` with `list`".

### 2.5 Vision: screenshots and coordinates
- Run `python -m browser_agent calibrate` for every model. Naming the convention in the prompt changes everything:
  Qwen3.8-Flash-Next hit 12/12 with the 0–1000 grid named and 6/12 without.
- **Set-of-mark** (an extension to build): draw each ref's box and label on the screenshot. Playwright MCP's
  `--snapshot-boxes` gives the boxes, so the model can click a ref it *saw* instead of guessing pixels.
- **Zoom**: for small targets, crop the region around the planned point, ask again, then click. It costs two calls
  and is far more precise on dense UIs (board games, toolbars).

### 2.6 Decomposition
A 60-step task is many 5–10-step tasks. Two ways to use that:
- **Inside one run:** a stronger plan with checkpoints, as above.
- **Across runs:** an orchestrator (another agent, or a script) gives the browser agent one sub-goal at a time, with a
  saved profile (`--browser-mode profile`), so logins and the cart survive between runs. Each sub-run gets a fresh,
  small context. The orchestrator checks each `report.json` before continuing.

### 2.7 Verification
After `finish`, run a short second model call (a verifier) with the instruction, the final snapshot and the
plan: "Is the task really done? Answer yes or no and why." If the answer is no, continue the run. This is cheap and
catches early finishes and wrong answers. It is a good first extension to write in `agent.py`.

### 2.8 Site playbooks (memory between runs)
Agents repeat the same sites. Keep short notes per site, for example `playbooks/<domain>.md`: "login is under the
avatar menu; the address form needs postal code before city; the Pay button opens a new tab". Inject the matching
note into the first message when the URL matches. It is one of the biggest real-world gains, because the model stops
rediscovering each site.

### 2.9 From agent to script
Playwright MCP prints the Playwright code it ran for every action (the "Ran Playwright code" sections in
`log.jsonl`). A successful run is therefore close to a deterministic script. For tasks you repeat (daily checks,
regression tests), turn the run into a Playwright script and let the agent handle only the failures ("self-healing").
It is faster, cheaper and exactly repeatable.

### 2.10 The model and the server
- Sampling: lower temperature (0.3–0.6) helps precision. Too low can loop. Measure it.
- Thinking: reasoning models do better on planning steps. If the server returns reasoning, read it in `log.jsonl`.
  It shows you *why* a step went wrong.
- Context: declare a window that still fits when several agents run at once.
- Tool-call parsing: if a model "answers in text" instead of calling tools, the server's tool parser or chat
  template is wrong. That is a serving problem, not a prompt problem.

## 3. Exercises

1. **Baseline.** Run the whole benchmark k=3. Write down the pass rate per task and the three most common failure
   categories.
2. **Finish check.** Add rule 2.1 (verify requirements before `finish`). Run it again and compare early finishes.
3. **Plan facts.** Make the plan carry a `Facts:` block (2.2). Measure the long shop flow and the research task.
4. **Context diet.** `keep_snapshots = 1`, then 3. Compare pass rate *and* seconds per run.
5. **Verifier.** Implement 2.7 in `agent.py` (one extra model call on `finish`). Measure the gain and its cost.
6. **Set-of-mark.** Implement 2.5 with `--snapshot-boxes` and PIL drawing. Measure the chess and canvas tasks.
7. **Playbook.** Write a playbook for the fixture shop, inject it, and measure steps and pass rate.
8. **Script it.** Turn a successful shop run into a Playwright script from the "Ran Playwright code" sections. Then
   break the page (rename a button) and let the agent repair the script.

Record every result in a table, including the ones that did not help.
