# PROTrader redesign — reference

Approved September 2026. `design/prototype.html` is the interactive sample the
redesign was approved from (open it in a browser; example prices, nothing live).
This file is the spec the app is built to. When in doubt, the prototype shows
the intent and this file gives the rule.

## The one decision everything follows from

The screen is for deciding whether to take this trade, at what size, and then
managing it. Chart → check → ticket → position. Everything else (MTF, Laws,
ARIA and Oracle detail, drawing tools, voice) is a tool one tap away, never part
of the primary hierarchy.

## Tokens (`:root` in `protrader_mobile.html`)

| token | value | job |
|---|---|---|
| `--bg-1` … `--bg-5` | `#070B14 #0D1320 #131B2B #1A2436 #212D42` | page → surfaces, deeper = nearer |
| `--tx-1 / -2 / -3` | `#EEF2F7 #A9B6C8 #7D8CA3` | text, secondary, muted (7.5:1 on bg-1) |
| `--green` | `#2FBF9B` | **up / buy / profit only** |
| `--red` | `#F0564F` | **down / sell / loss only**, and the real-money account state |
| `--blue` | `#4F8CFF` | **the one interactive colour**: active tab, links, Review button |
| `--amber` | `#F2B33D` | paper account, warnings, limits approaching |
| `--purple`, `--cyan`, `--yellow` | aliased to blue / green / amber | legacy names, no separate meaning |
| `--font-display` | IBM Plex Sans | UI text |
| `--font-mono` | IBM Plex Mono, `tabular-nums` | every number that lines up |

Glows and inset highlights are off (`--glow-*: none`). Depth comes from surface
steps and a single border, not shadows.

## Type scale

`--fs-1..5` = 12 / 14 / 16 / 20 / 28 px. Base is 14px. **Nothing that carries
information is below 12px.** (The build enforces this with a one-off pass that
raised every `font-size` under 12px; keep it that way — density reads as
"unfinished", not "pro".)

## Layout

Desktop ≥ 960: watchlist 224 · chart (min 0, flexible) · panel 320.
Phone ≤ 820: chart full-screen; the panel is a slide-up sheet; five-item bottom
nav **Chart · Markets · Check · Trade · Port** with thin-stroke SVG icons (no
emoji anywhere in chrome; flags on instruments are content, not chrome).

## Header

Brand · symbol · price · **feed status** (SIM / LIVE — this is the price feed,
never the account) · **account chip** · voice · theme · help.

The account chip is the only place that says where trades go, and it is always
visible: `Paper` (amber) · `MT5 demo` (blue) · `MT5 real` (red fill). It shows
the balance of *that* account. Tapping it opens the Paper / Trade-live chooser.

## Right panel tabs

**Check · Trade · Port · MTF · ARIA · Oracle · Laws**. Check is first and default.
Impact Garden is removed (it donated nothing; the app never claims what it
doesn't do).

### Check (Setup Check) — `renderCheck()`

One verdict, one vocabulary. Fed by `ariaGates()` / `ariaVerdict()` /
`ariaEntry()` and Oracle's confidence (`score/9`), so the engines are unchanged.

1. `SYMBOL · TF · session` + time
2. Verdict: **Leaning BUY/SELL** (≥ 7 of 9), **Wait** (5–6), **Stand aside**
   (< 5, or MCC dead-zone / fake-break, or the NAS100 news-week block) + `n of 9`
3. Nine-segment bar (green pass, red fail)
4. One sentence: what agrees, what is against you
5. **ARIA n/9 gates · verdict** and **Oracle n% confidence** — tappable, open
   the engine detail tabs
6. Checks, passes first, five shown then "Show 4 more". Each row = plain-language
   name, the engine's detail, Lesson n. Tapping opens the explainer sheet
   (`CHECK_TERMS`). Only checks with a real Academy lesson show a number;
   `CHECK_LESSON_URL` is null until the Academy publishes per-lesson links.
7. Context line: MCC · Wyckoff phase · scanner pattern
8. Entry / Stop / Target (TP2, 1:2.5) / **Risk = riskPct% of balance in $** / Size
9. **Review this trade** — neutral blue, never "Buy"/"Sell"; fills the ticket via
   `applyARIA()` and sizes the lot with `OT.sizeToRisk(true)`; nothing is placed.

### Trade — two stages

`Before the trade` (default) and `Open · n` (segmented control, `OT.setStage`).

Before: paper/MT5 mode line → MT5 bridge card (only after "Trade live") → quotes
→ Sell/Buy → order type → **Risk this trade** ($, −/+ in 0.25% steps, capped at
1%) and **Size from risk** (lots derived from stop distance, `riskLots()`) →
lot → SL/TP → metrics → summary → submit.

Open: **Your limits** meters (risk per trade 1%, open risk of 2%, daily loss of
3% of start-of-day, losing trades of 3 — from the EA when routing to MT5,
computed locally on paper) → MT5 book → paper positions (**BE · SL·TP · ½ ·
Close**) → pending orders.

`S.riskPct` (default 1) drives ARIA's entry architecture, Oracle's suggested
lot, the Check panel and the ticket. 2% is a later, data-justified escalation —
raise the cap in `OT.stepRisk` when the journal earns it.

## Copy rules

Name things by what the trader recognises: "Stop clears the noise", not
"ATR gate". Controls say what happens ("Review this trade", "Close now").
Empty states say what will appear and how to make it appear. No theatre:
nothing the app cannot do is on screen.

## Build order that was followed

1. Tokens, type floor, colour roles, icons, account chip, Impact Garden out
2. Setup Check panel
3. Trade split, risk-first sizing, limits meters, breakeven on paper
4. (next) Port and journal restyle, first-run card, Academy lesson links
