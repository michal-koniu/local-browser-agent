# Design

## Intent

A **general-purpose browser agent for local models**: you give it an instruction in plain words, and a model
running on your own hardware operates a real Chrome to carry it out. It clicks, types on the keyboard, presses keys,
drags, uploads, and reads the page. It is meant for long, multi-step work across sites, such as signing up, confirming
an e-mail, filling in an address, choosing products, paying (with your approval), testing a UI like a human tester,
posting where automation is allowed, or playing a board game in a web app. At the end it reports what it did, or
where and why it got stuck.

It is also meant to be **studied**. Every layer is a small module with one job, so you can follow an instruction
down to the individual click, change one layer and measure the effect.

## Goals

- Work well with local, open-weight models served through any OpenAI-compatible endpoint (llama.cpp, vLLM,
  llama-swap and others).
- Be precise on long tasks: keep the model's context small and current, give it a plan it can rewrite, and verify
  every action.
- Act like a person: real mouse and keyboard events, typing key by key, using the screen when the page structure
  is not enough.
- Keep secrets out of the model: the model names a secret, and the harness types the value.
- Ask a human for exactly the things a human must do or approve: CAPTCHAs, payments, signatures, posts.
- Record everything, so that every run can be replayed and debugged: a step log, a Playwright trace, a video and
  screenshots.
- Measure, don't guess: a set of local test sites with deterministic checks scores every change.

## Non-goals

- Bypassing bot detection, CAPTCHAs or rate limits. The agent asks you to solve a CAPTCHA, and it never tries to look
  less like a bot.
- Mass or multi-account automation, such as sybil wallets, fake engagement or account farms.
- Signing or paying without a human or a deterministic policy in the loop.
- Playing rated games against people with engine help. Play against the user, the site's computer, or through
  official bot APIs.
- Becoming a full assistant (chat channels, cron, memory). Other agents can call this one as a tool.

## Architecture

```
 instruction ─▶ agent.py (the loop) ─────────────────────────────▶ report.md / report.json
                 │  ▲
     chat with   │  │ tool results (page state, screenshots)
     tools       ▼  │
              llm.py ── OpenAI-compatible endpoint (your local model)
                 │
     tool calls  ▼
              tools.py ── harness tools: update_plan, click_at, drag_at, type_keys, type_secret,
                 │                       ask_human, finish
                 │        policy.py  ── risky-action gate (ask / allow / deny)
                 │        secrets.py ── placeholders in, values typed, values redacted out
                 │        human.py   ── terminal or file answers, optional notify command
                 ▼
              browser.py ── Playwright MCP client (stdio): browser tools, snapshot inlining,
                 │          [new] markers, console errors, screenshots
                 ▼
              Playwright MCP ─▶ Chrome (isolated, a saved profile, or your own Chrome over CDP)
```

Supporting modules: `history.py` (keeps the context small), `config.py` (TOML plus CLI flags), `report.py`.

## Decisions and why

| Decision | Why |
|---|---|
| Browser control through **Playwright MCP** (pinned version), not our own CDP code | It is mature and maintained, and handles accessibility snapshots with refs, waiting, dialogs, tabs, uploads, tracing and video. Our code only adds what a local model needs on top. |
| The model sees an **accessibility snapshot after every action**, inlined by the harness | Playwright MCP writes snapshots to files after actions. A model that has to ask for the page wastes a turn, and it often acts on a stale picture. |
| **`[new]` marks** on elements that appeared since the last snapshot (an idea from OpenClaw) | The model notices menus, errors and dialogs without having to diff a long tree. |
| **Screenshots and coordinate clicks only as a fallback** | Refs are exact, while coordinates depend on the model's visual grounding. Coordinates are converted from the model's convention (0–1000 grid or pixels), which `calibrate` measures per model. |
| **Old snapshots and screenshots removed from history**, while the plan stays | Long tasks fail when the context fills with stale pages. The plan, written by the model with `update_plan`, is its memory. |
| **Secrets as `{{secret:NAME}}` placeholders** | The value goes from the store (environment, a dotenv file or 1Password) straight into the browser field. Every text sent back to the model is scanned and the value is replaced with `[secret:NAME]`. |
| **Risky actions are gated in code**, not by asking the model to be careful | Page text can steer a model, and code cannot be steered by text. Paying, signing, sending and posting go through `policy.py`. |
| **A human channel** for CAPTCHAs, 2FA and approvals | Some steps need a person. The run pauses, notifies you, and continues when you answer in the terminal or write an answer file. |
| **A local test set with deterministic checks** (`evals/`) | Changes to prompts, history or tools are judged by numbers, not by impressions. |

## What is left open (extension points)

- Approval through chat apps: `human.notify_command` already runs any command (for example a Telegram bot script),
  but there is no two-way chat bridge.
- A vision side-model for text-only main models: today, screenshots go only to models marked `vision = true`.
- Sub-tasks and parallel agents: one run means one browser and one model. You can run several runs at once.
- Turning a successful run into a deterministic Playwright script (see `docs/improving-accuracy.md`).
