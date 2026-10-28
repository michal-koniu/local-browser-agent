# local-browser-agent

A **browser agent for local models**. You give it an instruction in plain words, and a model on your own hardware
drives a real Chrome to carry it out. It clicks, types key by key, presses keys, drags, uploads, switches tabs and
popups, and finishes with a report: what it did and what it found, or where and why it got stuck.

```bash
python -m browser_agent run --url https://shop.example.com \
  "Create an account, confirm it from the e-mail, set my delivery address, put the two cheapest
   ferns in the cart and pay with my card. Report the order number."
```

It is built to be **understood and improved**. The harness is about 1,300 lines of Python in small modules. The
browser work is done by [Playwright MCP](https://github.com/microsoft/playwright-mcp), and everything a local model
needs on top of that is visible code:

| Layer | File | What it does |
|---|---|---|
| Loop | `browser_agent/agent.py` | ask the model → run its tool calls → return results, until `finish` |
| Model | `browser_agent/llm.py` | any OpenAI-compatible endpoint (llama.cpp, vLLM, llama-swap, Ollama…) |
| Browser | `browser_agent/browser.py` | Playwright MCP client; puts the page snapshot into every result, marks `[new]` elements |
| Context | `browser_agent/history.py` | removes old snapshots and screenshots, so long tasks stay sharp |
| Tools | `browser_agent/tools.py` | browser tools plus `update_plan`, `click_at`, `drag_at`, `type_keys`, `ask_human`, `finish` |
| Secrets | `browser_agent/secrets.py` | `{{secret:NAME}}` placeholders; values come from env, a dotenv file or 1Password, and are never shown to the model |
| Safety | `browser_agent/policy.py` | paying, signing, posting and deleting need approval; decided in code from the real element |
| Human | `browser_agent/human.py` | CAPTCHA, 2FA and approvals: terminal, answer file plus notify command, or auto (tests) |
| Prompts | `browser_agent/prompts.py` | how the model is told to work |
| Measuring | `evals/`, `bench/evaluate.py` | local test sites with deterministic checks, and a benchmark runner |

Read [docs/design.md](docs/design.md) for the why, [docs/how-it-works.md](docs/how-it-works.md) for one step
traced end to end, and [docs/improving-accuracy.md](docs/improving-accuracy.md) for how to make it better at long,
complex tasks.

## Install

Requirements: Python 3.11+, Node.js 20+, Google Chrome (or run `npx playwright install chromium` and set
`browser = "chromium"`), and a local model server with tool calling. A vision model is recommended, because it can
see screenshots and click by coordinates.

```bash
git clone <this repo> && cd local-browser-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install                      # pinned @playwright/mcp
node_modules/.bin/playwright-core install ffmpeg   # needed for the screen recording (video.webm)
cp config.example.toml config.toml   # set base_url and [models.<name>] id
.venv/bin/python -m unittest discover tests
.venv/bin/python -m browser_agent calibrate   # vision models: which coordinate convention?
```

## Use

```bash
# a task, fresh browser profile, headless, approvals on the terminal
.venv/bin/python -m browser_agent run --url https://example.com "Find ... and tell me ..."

# QA mode: explore an app like a human tester and report bugs with steps to reproduce
.venv/bin/python -m browser_agent run --mode test --url http://localhost:3000 "Test the sign-up and checkout flows."

# WATCH it work: a real Chrome window on your desktop, slowed down, each action labelled on the page.
# Works from ssh or another agent too - the harness finds your logged-in desktop session (X11 or Wayland).
.venv/bin/python -m browser_agent run --headed "..."      # set slow_mo_ms = 300 in config.toml to follow by eye

# keep logins between runs (log in once by hand with --headed, then reuse the profile)
.venv/bin/python -m browser_agent run --browser-mode profile --profile social --headed "..."

# drive YOUR Chrome, which you can watch and take over (CAPTCHAs, 2FA):
google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/.agent-chrome &
.venv/bin/python -m browser_agent run --cdp http://127.0.0.1:9222 "..."

# unattended: requests wait for an answer file; get notified by any command
.venv/bin/python -m browser_agent run --human file "..."
.venv/bin/python -m browser_agent answer runs/<run-folder> yes
```

Every run leaves `runs/<time>-<model>/` containing `report.md`, `report.json`, `log.jsonl` (every model turn and tool
call), `video.webm`, a Playwright trace and the screenshots.

## Secrets

The model never sees a secret. It writes `{{secret:CARD_NUMBER}}` where the value belongs. The harness types the
real value into the browser and replaces the value with `[secret:CARD_NUMBER]` in everything the model reads.
Configure the store in `[secrets]`:

```toml
[secrets]
provider = "1password"                      # or env / dotenv
token_file = "~/.config/op/agent.token"     # a 1Password service account limited to one vault
[secrets.map]
CARD_NUMBER = "op://agent/Card/number"
SHOP_PASSWORD = "op://agent/Shop login/password"
```

Providers: `env`, `dotenv`, `bitwarden` (the password-manager vault through the `bw` CLI; every item in the allowed
folders becomes usable as `{{secret:item#field}}` with no mapping), `bitwarden-sm` (Secrets Manager machine
account) and `1password`. Screen recordings and traces show whatever was on screen, so keep `runs/` private.

## What it will not do

It does not get around bot detection or solve CAPTCHAs: it asks you. It does not run many accounts or wallets. It
does not pay, sign, post or delete without a human or your own explicit policy rule. It does not play rated games
against people with engine help. See [docs/safety.md](docs/safety.md).

## Results

See [bench/RESULTS.md](bench/RESULTS.md) for the comparison against browser-use on the same local model and tasks.

## License

MIT
