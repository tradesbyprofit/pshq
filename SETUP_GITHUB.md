# Setup: run the bot 24/7 on GitHub Actions (free, no computer needed)

Your bot runs on GitHub's cloud — every 15 min it wakes up, scans the forex pairs, and goes back to sleep. You don't leave any computer on. It auto-skips weekends and pings your Telegram only on a real A+ setup.

⏱️ ~15 minutes total. All free.

---

## Step 0 — Rotate your OANDA token (security)
Your demo token was shared in chat, so make a fresh one:
1. OANDA Practice → **Manage API Access** → **Revoke** the old token → **Generate** a new one. Copy it.
2. Keep your **Account ID** handy (`101-001-27939410-002`).

## Step 1 — Create a free GitHub account (skip if you have one)
Go to **github.com** → Sign up.

## Step 2 — Create a PRIVATE repository
1. Click **+** (top-right) → **New repository**.
2. Name it `icc-bot`. Choose **Private**. ⚠️ Do **not** tick "Add a README". Click **Create repository**.

## Step 3 — Upload the bot files
**Easiest way (web):**
1. In your new repo, click **Add file → Upload files**.
2. Drag in **all the files** from this `trading_bot` folder EXCEPT the `.github` folder (the `.py`, `.md`, `.sh`, `.pine`, `requirements.txt`, `.gitignore`, `scanner_state.json`).
3. Click **Commit changes**.
4. Now create the schedule file: **Add file → Create new file**.
5. In the filename box type exactly:  `.github/workflows/scan.yml`
6. Paste the contents of this repo's `.github/workflows/scan.yml` into the editor → **Commit**.

*(If you have git installed, it's faster: `git init && git add . && git commit -m "icc bot" && git branch -M main && git remote add origin https://github.com/YOUR_USERNAME/icc-bot.git && git push -u origin main`)*

## Step 4 — Add your secrets (stored securely, never in code)
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add these 4 (use your **new** OANDA token):

| Name | Value |
|---|---|
| `OANDA_API_TOKEN` | your new practice token |
| `OANDA_ACCOUNT_ID` | `101-001-27939410-002` |
| `TG_BOT_TOKEN` | `8697964218:AAHb0rnWLDqr3D1sh981eNqI6gpUceZbGBs` |
| `TG_CHAT_ID` | `5438406477` |

## Step 5 — Test it manually
Repo → **Actions** tab → click **ICC Scan** (left sidebar) → **Run workflow → Run workflow**.
Click into the run → watch it. You should see it scan EUR/USD, GBP/USD, USD/JPY, GBP/JPY and (this weekend) report "Forex closed — skipping." ✅

## Step 6 — Done. It runs itself now
GitHub runs it every 15 minutes automatically during market hours. You'll get a **Telegram message only when a real setup forms**. (Scheduled runs can be delayed a few minutes — that's fine for this method.)

---

## Good to know
- **First real trades:** forex reopens Sun ~22:00 UTC (Sun ~5 PM Dallas time). Watch for the first setup.
- **Track record:** every paper trade the bot takes auto-commits an update to `scanner_state.json` — your run history is in the **Actions** tab and the commit log.
- **Free limits:** private repos get 2,000 Actions-min/month — this bot uses a tiny fraction. A public repo is unlimited.
- **Tuning:** edit `WATCH`, `target_per_week`, `max_per_week`, or `min_rr` in `scanner.py` and push the change.
- **Adding gold/BTC later:** we enable Metals on the account (gold) and/or add a crypto testnet (BTC) — feeds are already built.
