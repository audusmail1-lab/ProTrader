# PROTrader → MT5 bridge

Sends orders from the PROTrader ticket (including "Apply ARIA to Trade") to your
own Deriv MT5 account.

Deriv has no API for placing MT5 orders, so the route is:

    PROTrader app  →  relay (/api/bridge on the PROTrader server)  →  PROTraderBridge EA inside your MT5

MT5 must be **open on a computer, logged in, with the EA attached** for orders to
go through. If the computer sleeps or MT5 closes, the app shows the bridge as
offline and refuses to send — it never falls back to paper silently. Stop losses
and take profits already placed live on Deriv's server and keep working.

## One-time setup (about 10 minutes)

1. **Get a key.** In PROTrader tap the **balance ($) button → Trade live on my MT5**. The
   MT5 Live panel appears in the Trade tab; tap **New**, then **Copy**.
   The key stays on your device; treat it like a password.
2. **Install the EA.** In MT5 desktop: **File → Open Data Folder → MQL5 → Experts**,
   copy `PROTraderBridge.mq5` there. Open it in MetaEditor (double-click) and press
   **F7 (Compile)**. It should report 0 errors.
3. **Allow the relay address.** MT5 → **Tools → Options → Expert Advisors** → tick
   **Allow WebRequest for listed URL** and add:
   `https://app.protraderacademy.company`
4. **Attach it.** Drag **PROTraderBridge** from the Navigator onto any ONE chart.
   In the dialog: tick **Allow Algo Trading**; on the **Inputs** tab paste the key
   into **BridgeKey**. Press OK, and make sure the **Algo Trading** toolbar button
   is green.
5. The chart's top-left corner should read `Relay: Connected`, and the MT5 Live
   panel in PROTrader turns green and shows your balance.
6. Tick **Send my orders to MT5** (or tap the **$ button → Trade live on my MT5** again).
   This switch is off again every time the app reloads, on purpose. To go back to
   paper trading, tap the **$ button → Demo account**; that also hides the MT5 panel.

## Start on demo

Log MT5 into a **Deriv demo** account first. The EA input **AllowRealAccount** is
`false` by default, so it refuses every entry on a real account until you change
it yourself. Run demo until fills, stops, partial losses and the daily lock all
behave the way you expect.

## Safety limits (EA inputs — the EA enforces these, not the app)

| Input | Default | Meaning |
|---|---|---|
| AllowRealAccount | false | Must be true before any entry is accepted on a real account |
| RequireStopLoss | true | Entries without a stop loss are rejected |
| MaxRiskPerTrade | 25 | Max loss at the stop, in account currency, priced by MT5 |
| MaxMarginPctPerTrade | 25 | Max margin per trade as % of equity |
| MaxOpenPositions | 3 | Counts every position on the account, manual ones included |
| DailyLossLimit | 75 | Today's closed + floating loss at which new entries lock until tomorrow |

Closing positions is never blocked by these limits. **Close all MT5 positions** in
the app flattens the whole account, including trades opened by hand.

## Things to know

* **Symbol names.** The app guesses the MT5 name (`Vol 25 (1s)` → `Volatility 25 (1s) Index`)
  and checks it with MT5. If MT5 uses a different name, type it in the MT5 Live
  panel. The app blocks the order if MT5's price is more than 1% away from the
  chart price, which catches a wrong mapping.
* **Lot sizes differ per symbol** on MT5 (0.05 on one index, 50+ on another). While
  orders are routed to MT5 the ticket uses MT5's own min/max/step.
* **Delay** is about 1–2 seconds. An order that MT5 has not collected within 15
  seconds is dropped, never executed late.
* **"No confirmation from MT5"** means the result is unknown. Check MT5 before
  sending again — the app deliberately does not retry.
* **Mac:** MT5 for macOS runs under a compatibility layer. WebRequest normally
  works there, but this has not been verified on your machine — step 5 is the test.
  Keep the Mac from sleeping (System Settings → Lock Screen / Energy).
* **New key** in the app disconnects the EA until you paste the new key into it.
