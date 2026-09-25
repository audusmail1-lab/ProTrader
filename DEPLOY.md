# Deploying PROTrader

Three ways to run it, from quickest to most shareable. Pick the one that
matches what you need today; they don't conflict.

| | Where it runs | Who can reach it | Laptop must be on? |
|---|---|---|---|
| **A. Home Wi-Fi** | your Mac | your phone/laptop on the same Wi-Fi | yes |
| **B. Tunnel** | your Mac | anyone with the link, anywhere | yes |
| **C. Cloud host** | Render / Fly.io | anyone, anywhere, always | **no** |

Everyone who opens it can also **install it as an app** (section D).

---

## A. Phone on your Wi-Fi — works right now

```bash
./server.sh start
```

The start banner prints a `from phone` line, e.g.

```
from phone  : http://192.168.100.8:8000/   (same Wi-Fi)
```

Open that address in Safari or Chrome on the phone. `server.sh` already
binds to `0.0.0.0`, so nothing else to configure. If it doesn't load, macOS
Firewall may be asking — allow incoming connections for Python.

The address can change when your router hands out a new IP; run
`./server.sh status` to see the current one.

---

## B. Share a link with others (laptop stays the server)

A tunnel gives your local server a public https URL. Good for showing
someone today; not for leaving up permanently, because it dies when the
laptop sleeps.

**Cloudflare Tunnel** (free, no account needed for a quick tunnel):

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

It prints something like `https://random-words.trycloudflare.com` — send
`https://random-words.trycloudflare.com` to whoever you like. Ctrl+C
ends it.

**ngrok** works the same way (`brew install ngrok && ngrok http 8000`),
but needs a free account.

---

## C. Cloud host — always on, real URL, no laptop needed

This is the right answer for "deploy on my phone and share it". The app
lives on a server that never sleeps; you and everyone else just open a URL.

### Step 1 — put the code on GitHub (once)

```bash
cd "/Users/joelaudu/Trading bot"
git init
git add .
git commit -m "PROTrader trading terminal"
```

Create an empty repository at github.com (say `protrader`), then:

```bash
git remote add origin https://github.com/YOUR-USERNAME/protrader.git
git branch -M main
git push -u origin main
```

`.gitignore` already keeps your venv, logs and pid file out.

### Step 2a — Render (easiest, no CLI)

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New → Blueprint** → choose the `protrader` repo.
3. Render reads `render.yaml`, builds the `Dockerfile`, and gives you
   `https://protrader.onrender.com`.

That's it. Every `git push` redeploys automatically.

*Free tier note:* the free instance sleeps after ~15 minutes idle and takes
about 30 s to wake on the next visit. Change `plan: free` to
`plan: starter` in `render.yaml` (≈ $7/month) to keep it always on.

### Step 2b — Fly.io (better free allowance, no sleep)

```bash
brew install flyctl
fly auth login
fly launch --no-deploy        # accepts fly.toml; change the app name if taken
fly deploy
```

URL is `https://protrader.fly.dev` (or whatever name you chose).

### Step 2c — any Docker host / VPS

```bash
docker build -t protrader .
docker run -d --restart unless-stopped -p 8000:8000 protrader
```

Put it behind Caddy or nginx for https. Works on a $5 VPS, a Raspberry Pi,
or a NAS.

---

## D. Install it as an app (phone and laptop)

Once the app is reachable over **https** (options B or C — or `localhost`
on the laptop), it's a Progressive Web App and installs like a native one:
full screen, own icon, no browser chrome, opens instantly.

- **iPhone / iPad (Safari):** open the URL → Share button → **Add to Home Screen**.
- **Android (Chrome):** open the URL → tap the **⬇ Install app** chip the
  app shows, or menu ⋮ → **Install app**.
- **Mac / Windows (Chrome / Edge):** the install icon appears at the right
  end of the address bar, or use the in-app **⬇ Install app** chip.

The shell (page + chart library) is cached, so it opens even with poor
signal; live prices always come from the network.

---

## Things to know before sharing widely

**Everyone shares one paper account.** Balance, positions and orders are
stored per *browser* (localStorage), so each person gets their own paper
account on their own device — nothing is shared server-side, and nobody
can see anyone else's trades. Drawings work the same way.

**There is no login.** Anyone with the URL can use it. That's fine for a
paper-trading terminal; if you later connect a real broker, add
authentication *first*.

**Data limits are the feed's, not the host's.** Yahoo caps intraday history
(15m ≈ 60 days, 1h ≈ 2 years) and Deriv streams live quotes; both work
identically from the cloud.

**Free tiers.** Render free sleeps when idle; Fly free is generous but
capped. If several people use it daily, a starter plan on either is the
right call.

**Updating.** Change code → `git push` → the host redeploys. The service
worker picks up the new shell on the next open; bump `CACHE_VERSION` in
`static/sw.js` if you want to force every device to refresh at once.

---

## E. ElevenLabs voice + text support assistant

Create an ElevenLabs Agent and enable both voice and text in **Channels → Widget → Interface**. Add your Pro Trader help content to its knowledge base, and keep its role limited to product education and support rather than financial advice or trade execution.

Set these server-side environment variables:

```text
ELEVENLABS_AGENT_ID=agent_4801m3by5dhceh5rwx83ynt33ra3
ELEVENLABS_API_KEY=...
```

On Render, add them under the service's **Environment** page (the Blueprint marks both as secret values). On Fly.io, run:

```bash
fly secrets set ELEVENLABS_AGENT_ID=agent_... ELEVENLABS_API_KEY=...
```

The supplied public agent `agent_4801m3by5dhceh5rwx83ynt33ra3` is built in as the default, so the widget works without additional configuration. The browser never receives the API key when one is configured: it requests a short-lived signed conversation URL from `/api/support/elevenlabs`. Set both variables when moving the agent to private authenticated sessions.
