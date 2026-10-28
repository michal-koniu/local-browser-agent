# Safety

A browser agent reads untrusted text (every page, every e-mail), holds private data (your accounts, your card), and
can act outward (pay, post, sign). That combination is called the **lethal trifecta**: one malicious page can try to
make the model send your data elsewhere or act for someone else. The model cannot reliably tell instructions from
data. So the protections here live **in code around the model**, not in the prompt.

| Risk | What the harness does | What you should do |
|---|---|---|
| A page or e-mail tells the model to do something else (prompt injection) | The prompt says page text is data. Risky actions are gated in code, judged from the *real* element and URL. Secrets are never in the model's context, so it cannot leak them | Use `allowed_origins` for task-specific runs. Read the summary: the model is told to report injection attempts |
| Paying, signing, posting or deleting by mistake | `policy.py` default rules (payment, signature on wallet pages, publish, destructive) ask a human. Unanswered requests are denied | Add your own rules. Use `deny` for anything an agent must never do |
| Secrets leaking | Placeholders: the value is typed by the harness and redacted from results, logs and reports. When a run ends, every text file in the run folder (Playwright's page snapshots, trace and console logs, which record typed values) is scrubbed too. `keep_media_with_secrets = false` deletes screenshots and video from runs that used a secret | Give the agent only the secrets it needs: a Bitwarden folder limited with `folders`, a Secrets Manager project, or a 1Password vault for the agent, and cards with low limits. Remember that **video, trace and screenshots** show what was on screen: keep `runs/` private, or turn recording off for sensitive runs |
| Wallets and signatures | Signature buttons on wallet pages always ask, and the approval request shows the on-screen text (spender, amount, network). The prompt tells the model to refuse unlimited allowances, unknown spenders and amounts beyond the task. In the benchmark both engines signed an unlimited "bonus" approval before this rule existed | Use a separate wallet with small funds and develop on a testnet. Prefer a hardware wallet, where *you* confirm on the device. Never give the agent a seed phrase |
| The agent uses your real logged-in browser | `isolated` mode by default. `profile` keeps only the logins you created for it. `cdp` attaches to a Chrome *you* started for it | Do not attach to your everyday browser profile |
| A page tricks the agent into uploading a private file | Uploads come only from `[browser] upload_dirs`. The file is copied into the run folder, and anything else is refused | List only the folders that hold files meant for upload |
| Runaway loops | `max_steps`, repeat detection, `context_budget`, human timeouts | Watch the first runs of a new kind of task |

## What this project will not help with

- **Getting around bot detection, CAPTCHAs or rate limits.** The agent asks you to solve a CAPTCHA. It does not
  pretend to be more human than it is.
- **Many accounts or wallets that pose as different people** (sybil farming, fake engagement).
- **Paying or signing without a human or an explicit rule you wrote.**
- **Engine help in games against people.** Play against yourself, the site's computer, or through official bot
  accounts and APIs.
- **Sites whose terms forbid automation.** Check them first. Many social networks allow posting only through their
  official API.

## Limits of the gate

The gate checks clicks, Enter and submitting typing. A page can still do things on its own, such as scripts that run
on load. Coordinate clicks are checked through `elementFromPoint`, which sees the main frame only, not iframes. The
patterns are English-centric. `allowed_origins` is not a security boundary (see the Playwright MCP docs). Treat the
gate as a strong seatbelt, not a sandbox. For real isolation, run the browser in a container or a separate user
account.
