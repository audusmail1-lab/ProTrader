//+------------------------------------------------------------------+
//|                                              PROTraderBridge.mq5 |
//|  Executes orders sent from the PROTrader web app on this MT5      |
//|  account. Once a second it posts an account snapshot to the       |
//|  PROTrader relay and collects any commands queued for it.         |
//|                                                                  |
//|  THIS EA IS THE AUTHORITY ON RISK. Every limit below is enforced  |
//|  here, inside your terminal, no matter what the app sends.        |
//|                                                                  |
//|  Setup: Tools > Options > Expert Advisors > tick "Allow WebRequest |
//|  for listed URL" and add the BridgeUrl. Then attach this EA to    |
//|  any one chart, paste your Bridge Key, and turn on Algo Trading.  |
//+------------------------------------------------------------------+
#property copyright "PROTrader"
#property version   "1.10"
#property description "Bridge between the PROTrader web app and this MT5 account."

#include <Trade\Trade.mqh>

input group "Connection"
input string BridgeUrl            = "https://app.protraderacademy.company"; // Relay address (no trailing slash)
input string BridgeKey            = "";      // Bridge Key (copy from PROTrader > Trade > MT5 Live)

input group "Safety limits (enforced here, not in the app)"
input bool   AllowRealAccount     = false;   // Allow trading on a REAL account (leave false while testing on demo)
input bool   RequireStopLoss      = true;    // Reject any entry that has no stop loss
input double MaxRiskPctPerTrade   = 1.0;     // Max loss at the stop, % of CURRENT equity (0 = no cap)
input double MaxOpenRiskPct       = 2.0;     // Max combined risk of all open trades + pending orders, % of current equity (0 = no cap)
input double DailyLossLimitPct    = 3.0;     // Hard daily loss limit, % of START-OF-DAY equity (0 = off)
input int    MaxLosingTradesPerDay = 3;      // Stop for the day after this many losing trades (0 = off)
input double MaxMarginPctPerTrade = 25.0;    // Max margin one trade may use, % of equity (0 = no cap)
input int    MaxOpenPositions     = 3;       // Max open positions on the account (0 = no cap)

input group "Execution"
input int    SlippagePoints       = 200;     // Max slippage in points
input long   MagicNumber          = 770077;  // Tag for orders placed by this EA

#define EA_VERSION     "1.10"
#define POLL_MS        1000
#define HISTORY_EVERY  15        // seconds between history uploads
#define HISTORY_DAYS   14
#define HISTORY_MAX    60
#define MAX_PENDING_RESULTS 20

CTrade   trade;
string   g_results[];            // JSON result objects waiting to be uploaded
datetime g_lastHistory   = 0;
bool     g_forceHistory  = true;
int      g_failStreak    = 0;
int      g_skip          = 0;
string   g_status        = "Starting...";
string   g_lastAction    = "-";

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringLen(BridgeKey) < 24)
     {
      Alert("PROTrader Bridge: paste your Bridge Key into the EA inputs (PROTrader > Trade > MT5 Live).");
      return(INIT_PARAMETERS_INCORRECT);
     }
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints((ulong)SlippagePoints);
   trade.SetAsyncMode(false);
   trade.LogLevel(LOG_LEVEL_ERRORS);
   EventSetMillisecondTimer(POLL_MS);
   ShowStatus();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

void OnTick() { }

void OnTimer()
  {
   if(g_skip > 0) { g_skip--; return; }     // back off while the relay is unreachable
   Sync();
   ShowStatus();
  }

//+------------------------------------------------------------------+
//| JSON helpers (MQL5 has no JSON library; output only)              |
//+------------------------------------------------------------------+
string JStr(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   StringReplace(s, "\t", " ");
   return("\"" + s + "\"");
  }

string JNum(const double v, const int digits = 8)
  {
   if(!MathIsValidNumber(v)) return("null");
   return(DoubleToString(v, digits));
  }

string JBool(const bool b) { return(b ? "true" : "false"); }

void PushResult(const string id, const bool ok, const string msg, const string extra = "")
  {
   string j = "{\"id\":" + JStr(id) + ",\"ok\":" + JBool(ok) + ",\"msg\":" + JStr(msg);
   if(extra != "") j += "," + extra;
   j += "}";
   int n = ArraySize(g_results);
   if(n >= MAX_PENDING_RESULTS)
     {
      for(int i = 1; i < n; i++) g_results[i - 1] = g_results[i];
      n--;
     }
   ArrayResize(g_results, n + 1);
   g_results[n] = j;
   g_lastAction = (ok ? "OK  " : "FAIL ") + msg;
   Print("PROTrader Bridge [", id, "] ", (ok ? "OK: " : "REJECTED: "), msg);
  }

//+------------------------------------------------------------------+
//| Account state                                                     |
//+------------------------------------------------------------------+
string AccountModeText()
  {
   long m = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(m == ACCOUNT_TRADE_MODE_DEMO)    return("demo");
   if(m == ACCOUNT_TRADE_MODE_CONTEST) return("contest");
   return("real");
  }

bool TradingSwitchedOn()
  {
   return(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0 &&
          MQLInfoInteger(MQL_TRADE_ALLOWED) != 0 &&
          AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) != 0 &&
          AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0);
  }

datetime DayStart()
  {
   return(StringToTime(TimeToString(TimeCurrent(), TIME_DATE)));
  }

//+------------------------------------------------------------------+
//| Risk framework                                                    |
//|   1. per trade   : risk at stop <= MaxRiskPctPerTrade of equity    |
//|   2. open risk   : all open + pending risk <= MaxOpenRiskPct       |
//|   3. daily loss  : (start-of-day equity - equity) can never exceed |
//|                    DailyLossLimitPct. New risk is only allowed out |
//|                    of what is left of that budget, so the limit    |
//|                    holds even if every open stop is hit.           |
//|   4. loss count  : no entries after MaxLosingTradesPerDay losers   |
//+------------------------------------------------------------------+
struct RiskState
  {
   double startEquity;    // equity at the start of the trading day
   double equity;
   double dayPnl;         // equity - startEquity (closed + floating)
   double openRisk;       // money lost if every open stop / pending stop is hit
   int    unprotected;    // open positions with no stop loss (risk cannot be bounded)
   int    lossesToday;    // closed losing positions today
   double perTradeCap;    // money
   double openRiskCap;    // money
   double dailyCap;       // money
   double budget;         // most a NEW trade may risk right now (money); <0 means unlimited
  };

string DayKey() { return("PTB_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "_" + TimeToString(DayStart(), TIME_DATE)); }

// Net result of today's closed trades and today's deposits/withdrawals.
void TodayClosed(double &tradePnl, double &balanceOps, int &losers)
  {
   tradePnl = 0.0; balanceOps = 0.0; losers = 0;
   if(!HistorySelect(DayStart(), TimeCurrent() + 86400)) return;
   int n = HistoryDealsTotal();
   long   ids[];  double sums[];  bool closed[];
   for(int i = 0; i < n; i++)
     {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      long type = HistoryDealGetInteger(t, DEAL_TYPE);
      double v = HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_SWAP) + HistoryDealGetDouble(t, DEAL_COMMISSION);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL) { balanceOps += v; continue; }
      tradePnl += v;
      // group by position so partial closes of one trade count as one result
      long pid = HistoryDealGetInteger(t, DEAL_POSITION_ID);
      long entry = HistoryDealGetInteger(t, DEAL_ENTRY);
      int k = -1;
      for(int j = 0; j < ArraySize(ids); j++) if(ids[j] == pid) { k = j; break; }
      if(k < 0)
        {
         k = ArraySize(ids);
         ArrayResize(ids, k + 1); ArrayResize(sums, k + 1); ArrayResize(closed, k + 1);
         ids[k] = pid; sums[k] = 0.0; closed[k] = false;
        }
      sums[k] += v;
      if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT) closed[k] = true;
     }
   for(int j = 0; j < ArraySize(ids); j++)
     {
      if(!closed[j] || sums[j] >= 0.0) continue;
      if(PositionSelectByTicket((ulong)ids[j])) continue;      // still partly open: not a finished loss yet
      losers++;
     }
  }

// Equity at the start of the trading day (server midnight). Stored in a
// terminal global variable the first time it is seen each day so it
// survives EA restarts; if the EA was not running at midnight it is rebuilt
// from the balance minus everything that has happened today.
double StartOfDayEquity(const double tradePnl, const double balanceOps)
  {
   string key = DayKey();
   if(GlobalVariableCheck(key)) return(GlobalVariableGet(key) + balanceOps);   // deposits/withdrawals are not P&L
   double floating = AccountInfoDouble(ACCOUNT_EQUITY) - AccountInfoDouble(ACCOUNT_BALANCE);
   double start = AccountInfoDouble(ACCOUNT_BALANCE) - tradePnl - balanceOps;
   // Positions carried in from yesterday: their float at midnight is unknown, so
   // count today's float against today only if nothing was carried over.
   bool carried = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) != 0 && (datetime)PositionGetInteger(POSITION_TIME) < DayStart()) { carried = true; break; }
   if(carried) start += floating;
   GlobalVariableSet(key, start);
   return(start + balanceOps);
  }

// Money lost if this position/order is stopped out. 0 when the stop locks in a profit.
double RiskAtStop(const string sym, const bool isBuy, const double vol, const double entry, const double sl)
  {
   double pl = 0.0;
   if(!OrderCalcProfit(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, vol, entry, sl, pl)) return(-1.0);
   return(pl < 0.0 ? -pl : 0.0);
  }

void ReadRisk(RiskState &r)
  {
   double tradePnl, balanceOps; int losers;
   TodayClosed(tradePnl, balanceOps, losers);
   r.equity      = AccountInfoDouble(ACCOUNT_EQUITY);
   r.startEquity = StartOfDayEquity(tradePnl, balanceOps);
   r.dayPnl      = r.equity - r.startEquity;
   r.lossesToday = losers;
   r.openRisk = 0.0; r.unprotected = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0) continue;
      double sl = PositionGetDouble(POSITION_SL);
      if(sl <= 0.0) { r.unprotected++; continue; }
      double x = RiskAtStop(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY,
                            PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), sl);
      if(x < 0.0) r.unprotected++; else r.openRisk += x;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(OrderGetTicket(i) == 0) continue;
      double sl = OrderGetDouble(ORDER_SL);
      long ot = OrderGetInteger(ORDER_TYPE);
      bool isBuy = (ot == ORDER_TYPE_BUY_LIMIT || ot == ORDER_TYPE_BUY_STOP || ot == ORDER_TYPE_BUY_STOP_LIMIT);
      if(sl <= 0.0) { r.unprotected++; continue; }
      double x = RiskAtStop(OrderGetString(ORDER_SYMBOL), isBuy, OrderGetDouble(ORDER_VOLUME_CURRENT), OrderGetDouble(ORDER_PRICE_OPEN), sl);
      if(x < 0.0) r.unprotected++; else r.openRisk += x;
     }
   r.perTradeCap = MaxRiskPctPerTrade > 0.0 ? r.equity * MaxRiskPctPerTrade / 100.0 : -1.0;
   r.openRiskCap = MaxOpenRiskPct     > 0.0 ? r.equity * MaxOpenRiskPct / 100.0 : -1.0;
   r.dailyCap    = DailyLossLimitPct  > 0.0 ? r.startEquity * DailyLossLimitPct / 100.0 : -1.0;
   // what a new trade may still risk: the tightest of the three
   r.budget = -1.0;
   if(r.perTradeCap >= 0.0) r.budget = r.perTradeCap;
   if(r.openRiskCap >= 0.0)
     { double left = r.openRiskCap - r.openRisk; if(r.budget < 0.0 || left < r.budget) r.budget = left; }
   if(r.dailyCap >= 0.0)
     { double left = r.dailyCap + r.dayPnl - r.openRisk; if(r.budget < 0.0 || left < r.budget) r.budget = left; }   // dayPnl is negative on a losing day
   if(r.budget < 0.0 && (r.perTradeCap >= 0.0 || r.openRiskCap >= 0.0 || r.dailyCap >= 0.0)) r.budget = 0.0;
  }

double DayPnl() { RiskState r; ReadRisk(r); return(r.dayPnl); }

// Returns "" when new entries are allowed, otherwise the reason they are not.
string EntryBlockReasonFor(const RiskState &r)
  {
   if(!TradingSwitchedOn())
      return("Algo Trading is off in MT5 (toolbar button, and 'Allow Algo Trading' in the EA settings)");
   if(AccountModeText() == "real" && !AllowRealAccount)
      return("This is a REAL account and AllowRealAccount is false in the EA inputs");
   if(r.dailyCap >= 0.0 && -r.dayPnl >= r.dailyCap)
      return("Daily loss limit reached: down " + DoubleToString(-r.dayPnl, 2) + " of " + DoubleToString(r.dailyCap, 2) +
             " (" + DoubleToString(DailyLossLimitPct, 1) + "% of start-of-day equity) - locked until tomorrow");
   if(MaxLosingTradesPerDay > 0 && r.lossesToday >= MaxLosingTradesPerDay)
      return(IntegerToString(r.lossesToday) + " losing trades today - daily stop reached, locked until tomorrow");
   if(MaxOpenPositions > 0 && PositionsTotal() >= MaxOpenPositions)
      return("Max open positions reached (" + IntegerToString(MaxOpenPositions) + ")");
   if(r.unprotected > 0 && (r.openRiskCap >= 0.0 || r.dailyCap >= 0.0))
      return(IntegerToString(r.unprotected) + " open position/order has no stop loss, so open risk cannot be bounded - add a stop or close it first");
   if((r.perTradeCap >= 0.0 || r.openRiskCap >= 0.0 || r.dailyCap >= 0.0) && r.budget <= 0.005)
      return("No risk budget left: open risk " + DoubleToString(r.openRisk, 2) + ", today " + DoubleToString(r.dayPnl, 2));
   return("");
  }

string EntryBlockReason() { RiskState r; ReadRisk(r); return(EntryBlockReasonFor(r)); }

//+------------------------------------------------------------------+
//| Symbols                                                           |
//+------------------------------------------------------------------+
string Squash(string s)
  {
   StringToLower(s);
   StringReplace(s, " ", "");
   StringReplace(s, "/", "");
   StringReplace(s, "_", "");
   StringReplace(s, ".", "");
   return(s);
  }

// Exact name first; otherwise a case/space-insensitive match across the
// broker's symbol list. Returns "" when nothing matches.
string ResolveSymbol(const string want)
  {
   bool custom = false;
   if(SymbolExist(want, custom))
     {
      SymbolSelect(want, true);
      return(want);
     }
   string target = Squash(want);
   int n = SymbolsTotal(false);
   for(int i = 0; i < n; i++)
     {
      string name = SymbolName(i, false);
      if(Squash(name) == target)
        {
         SymbolSelect(name, true);
         return(name);
        }
     }
   return("");
  }

double NormVolume(const string sym, const double vol)
  {
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) return(vol);
   double v = MathFloor(vol / step + 1e-9) * step;
   return(NormalizeDouble(v, 8));
  }

double NormPrice(const string sym, const double px)
  {
   return(NormalizeDouble(px, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)));
  }

string SpecJson(const string sym)
  {
   MqlTick tk;
   double bid = 0.0, ask = 0.0;
   if(SymbolInfoTick(sym, tk)) { bid = tk.bid; ask = tk.ask; }
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   return("\"spec\":{\"symbol\":" + JStr(sym) +
          ",\"digits\":" + IntegerToString(digits) +
          ",\"point\":" + JNum(point, 10) +
          ",\"tickSize\":" + JNum(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE), 10) +
          ",\"tickValue\":" + JNum(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE), 10) +
          ",\"contractSize\":" + JNum(SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE), 4) +
          ",\"volMin\":" + JNum(SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), 4) +
          ",\"volMax\":" + JNum(SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX), 4) +
          ",\"volStep\":" + JNum(SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), 4) +
          ",\"stopsDist\":" + JNum((double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * point, 10) +
          ",\"bid\":" + JNum(bid, digits) + ",\"ask\":" + JNum(ask, digits) + "}");
  }

//+------------------------------------------------------------------+
//| Entries                                                           |
//+------------------------------------------------------------------+
void ExecEntry(const string id, const string kind, const string wantSym, const string side,
               double vol, const bool hasPrice, double price,
               const bool hasSl, double sl, const bool hasTp, double tp)
  {
   RiskState rs; ReadRisk(rs);
   string block = EntryBlockReasonFor(rs);
   if(block != "") { PushResult(id, false, block); return; }

   string sym = ResolveSymbol(wantSym);
   if(sym == "") { PushResult(id, false, "MT5 has no symbol called '" + wantSym + "' - set the MT5 symbol name in the app"); return; }

   long tmode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(tmode == SYMBOL_TRADE_MODE_DISABLED || tmode == SYMBOL_TRADE_MODE_CLOSEONLY)
     { PushResult(id, false, sym + " is not open for new trades on this account"); return; }

   bool isBuy = (side == "buy");
   if(!isBuy && side != "sell") { PushResult(id, false, "Side must be buy or sell"); return; }

   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   vol = NormVolume(sym, vol);
   if(vol < vmin - 1e-9) { PushResult(id, false, "Lot size is below the MT5 minimum for " + sym + " (" + DoubleToString(vmin, 2) + ")"); return; }
   if(vol > vmax + 1e-9) { PushResult(id, false, "Lot size is above the MT5 maximum for " + sym + " (" + DoubleToString(vmax, 2) + ")"); return; }

   MqlTick tk;
   if(!SymbolInfoTick(sym, tk) || tk.bid <= 0.0 || tk.ask <= 0.0)
     { PushResult(id, false, "No live MT5 price for " + sym); return; }

   bool   isMarket = (kind == "market");
   double entry    = isMarket ? (isBuy ? tk.ask : tk.bid) : NormPrice(sym, price);
   if(!isMarket && (!hasPrice || entry <= 0.0)) { PushResult(id, false, "Pending order needs a price"); return; }

   if(!hasSl || sl <= 0.0)
     {
      if(RequireStopLoss) { PushResult(id, false, "No stop loss - the EA is set to reject entries without one"); return; }
      sl = 0.0;
     }
   else sl = NormPrice(sym, sl);
   if(!hasTp || tp <= 0.0) tp = 0.0; else tp = NormPrice(sym, tp);

   // stops must be on the correct side, and outside the broker's minimum distance
   double minDist = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(sym, SYMBOL_POINT);
   int    dg      = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(sl > 0.0)
     {
      if(isBuy  && sl >= entry - minDist) { PushResult(id, false, "Stop loss must be below " + DoubleToString(entry - minDist, dg) + " for this buy"); return; }
      if(!isBuy && sl <= entry + minDist) { PushResult(id, false, "Stop loss must be above " + DoubleToString(entry + minDist, dg) + " for this sell"); return; }
     }
   if(tp > 0.0)
     {
      if(isBuy  && tp <= entry + minDist) { PushResult(id, false, "Take profit must be above " + DoubleToString(entry + minDist, dg) + " for this buy"); return; }
      if(!isBuy && tp >= entry - minDist) { PushResult(id, false, "Take profit must be below " + DoubleToString(entry - minDist, dg) + " for this sell"); return; }
     }

   ENUM_ORDER_TYPE calcType = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   // risk at the stop, priced by MT5 itself, against the three money limits
   bool anyRiskCap = (rs.perTradeCap >= 0.0 || rs.openRiskCap >= 0.0 || rs.dailyCap >= 0.0);
   if(sl <= 0.0 && anyRiskCap)
     { PushResult(id, false, "No stop loss - risk limits are on, so every entry needs one"); return; }
   if(sl > 0.0 && anyRiskCap)
     {
      double risk = RiskAtStop(sym, isBuy, vol, entry, sl);
      if(risk < 0.0) { PushResult(id, false, "MT5 could not price the risk on this trade - not sent"); return; }
      if(rs.perTradeCap >= 0.0 && risk > rs.perTradeCap + 0.005)
        {
         PushResult(id, false, "Risk at stop is " + DoubleToString(risk, 2) + ", above " + DoubleToString(MaxRiskPctPerTrade, 1) +
                    "% of equity (" + DoubleToString(rs.perTradeCap, 2) + ") - reduce the lot size or tighten the stop");
         return;
        }
      if(rs.openRiskCap >= 0.0 && rs.openRisk + risk > rs.openRiskCap + 0.005)
        {
         PushResult(id, false, "Combined open risk would be " + DoubleToString(rs.openRisk + risk, 2) + ", above " +
                    DoubleToString(MaxOpenRiskPct, 1) + "% of equity (" + DoubleToString(rs.openRiskCap, 2) + ") - " +
                    DoubleToString(MathMax(0.0, rs.openRiskCap - rs.openRisk), 2) + " is available");
         return;
        }
      if(rs.dailyCap >= 0.0 && risk > rs.dailyCap + rs.dayPnl - rs.openRisk + 0.005)
        {
         PushResult(id, false, "This trade could take today's loss past the " + DoubleToString(DailyLossLimitPct, 1) + "% daily limit (" +
                    DoubleToString(rs.dailyCap, 2) + "): only " + DoubleToString(MathMax(0.0, rs.dailyCap + rs.dayPnl - rs.openRisk), 2) + " of risk is left today");
         return;
        }
     }

   double margin = 0.0;
   if(!OrderCalcMargin(calcType, sym, vol, entry, margin))
     { PushResult(id, false, "MT5 could not calculate margin for this trade - not sent"); return; }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     { PushResult(id, false, "Not enough free margin: needs " + DoubleToString(margin, 2)); return; }
   if(MaxMarginPctPerTrade > 0.0 && equity > 0.0 && margin > equity * MaxMarginPctPerTrade / 100.0)
     {
      PushResult(id, false, "Margin " + DoubleToString(margin, 2) + " is more than " +
                 DoubleToString(MaxMarginPctPerTrade, 0) + "% of equity - EA cap");
      return;
     }

   trade.SetTypeFillingBySymbol(sym);
   bool sent = false;
   if(isMarket)
      sent = isBuy ? trade.Buy(vol, sym, 0.0, sl, tp, "PROTrader")
                   : trade.Sell(vol, sym, 0.0, sl, tp, "PROTrader");
   else if(kind == "limit")
      sent = isBuy ? trade.BuyLimit(vol, entry, sym, sl, tp, ORDER_TIME_GTC, 0, "PROTrader")
                   : trade.SellLimit(vol, entry, sym, sl, tp, ORDER_TIME_GTC, 0, "PROTrader");
   else if(kind == "stop")
      sent = isBuy ? trade.BuyStop(vol, entry, sym, sl, tp, ORDER_TIME_GTC, 0, "PROTrader")
                   : trade.SellStop(vol, entry, sym, sl, tp, ORDER_TIME_GTC, 0, "PROTrader");

   uint rc = trade.ResultRetcode();
   bool ok = sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL || rc == TRADE_RETCODE_PLACED);
   if(!ok)
     {
      PushResult(id, false, "MT5 rejected the order: " + trade.ResultRetcodeDescription() + " (" + IntegerToString((int)rc) + ")");
      return;
     }
   double fill = trade.ResultPrice();
   if(fill <= 0.0) fill = entry;
   string extra = "\"symbol\":" + JStr(sym) + ",\"side\":" + JStr(side) + ",\"kind\":" + JStr(kind) +
                  ",\"volume\":" + JNum(trade.ResultVolume() > 0.0 ? trade.ResultVolume() : vol, 4) +
                  ",\"price\":" + JNum(fill, dg) +
                  ",\"ticket\":" + JStr(IntegerToString((long)trade.ResultOrder()));
   PushResult(id, true, (isMarket ? "Filled " : "Placed ") + side + " " + DoubleToString(vol, 2) + " " + sym +
              " @ " + DoubleToString(fill, dg), extra);
   g_forceHistory = true;
  }

//+------------------------------------------------------------------+
//| Position / order management                                       |
//+------------------------------------------------------------------+
void ExecClose(const string id, const ulong ticket, const bool hasVol, double vol)
  {
   if(!TradingSwitchedOn()) { PushResult(id, false, "Algo Trading is off in MT5 - close it in MT5 directly"); return; }
   if(!PositionSelectByTicket(ticket)) { PushResult(id, false, "Position #" + IntegerToString((long)ticket) + " is not open"); return; }
   string sym  = PositionGetString(POSITION_SYMBOL);
   double have = PositionGetDouble(POSITION_VOLUME);
   trade.SetTypeFillingBySymbol(sym);
   bool sent;
   if(hasVol && vol > 0.0 && vol < have - 1e-9)
     {
      vol = NormVolume(sym, vol);
      if(vol < SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN) - 1e-9) { PushResult(id, false, "Partial close is below the minimum lot"); return; }
      sent = trade.PositionClosePartial(ticket, vol, (ulong)SlippagePoints);
     }
   else
      sent = trade.PositionClose(ticket, (ulong)SlippagePoints);
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL))
     {
      int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      PushResult(id, true, "Closed #" + IntegerToString((long)ticket) + " " + sym + " @ " + DoubleToString(trade.ResultPrice(), dg),
                 "\"ticket\":" + JStr(IntegerToString((long)ticket)) + ",\"price\":" + JNum(trade.ResultPrice(), dg));
      g_forceHistory = true;
     }
   else
      PushResult(id, false, "MT5 could not close #" + IntegerToString((long)ticket) + ": " + trade.ResultRetcodeDescription());
  }

void ExecModify(const string id, const ulong ticket, const bool hasSl, double sl, const bool hasTp, double tp)
  {
   if(!TradingSwitchedOn()) { PushResult(id, false, "Algo Trading is off in MT5"); return; }
   if(!PositionSelectByTicket(ticket)) { PushResult(id, false, "Position #" + IntegerToString((long)ticket) + " is not open"); return; }
   string sym = PositionGetString(POSITION_SYMBOL);
   double newSl = hasSl ? NormPrice(sym, sl) : PositionGetDouble(POSITION_SL);   // "-" keeps the current level, 0 removes it
   double newTp = hasTp ? NormPrice(sym, tp) : PositionGetDouble(POSITION_TP);
   if(newSl <= 0.0 && (RequireStopLoss || MaxRiskPctPerTrade > 0.0 || MaxOpenRiskPct > 0.0 || DailyLossLimitPct > 0.0))
     { PushResult(id, false, "The EA will not remove a stop loss while risk limits are on"); return; }
   if(trade.PositionModify(ticket, newSl, newTp) && trade.ResultRetcode() == TRADE_RETCODE_DONE)
      PushResult(id, true, "Updated SL/TP on #" + IntegerToString((long)ticket), "\"ticket\":" + JStr(IntegerToString((long)ticket)));
   else
      PushResult(id, false, "MT5 could not modify #" + IntegerToString((long)ticket) + ": " + trade.ResultRetcodeDescription());
  }

void ExecCancel(const string id, const ulong ticket)
  {
   if(!TradingSwitchedOn()) { PushResult(id, false, "Algo Trading is off in MT5"); return; }
   if(trade.OrderDelete(ticket) && trade.ResultRetcode() == TRADE_RETCODE_DONE)
      PushResult(id, true, "Cancelled order #" + IntegerToString((long)ticket), "\"ticket\":" + JStr(IntegerToString((long)ticket)));
   else
      PushResult(id, false, "MT5 could not cancel #" + IntegerToString((long)ticket) + ": " + trade.ResultRetcodeDescription());
  }

// Kill switch: flatten every position and delete every pending order.
void ExecCloseAll(const string id)
  {
   if(!TradingSwitchedOn()) { PushResult(id, false, "Algo Trading is off in MT5 - close positions in MT5 directly"); return; }
   int closed = 0, failed = 0, cancelled = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      trade.SetTypeFillingBySymbol(PositionGetString(POSITION_SYMBOL));
      if(trade.PositionClose(t, (ulong)SlippagePoints) &&
         (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_DONE_PARTIAL)) closed++;
      else failed++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(trade.OrderDelete(t)) cancelled++; else failed++;
     }
   g_forceHistory = true;
   PushResult(id, failed == 0, "Close all: " + IntegerToString(closed) + " closed, " + IntegerToString(cancelled) +
              " cancelled, " + IntegerToString(failed) + " failed");
  }

void ExecSpec(const string id, const string wantSym)
  {
   string sym = ResolveSymbol(wantSym);
   if(sym == "") { PushResult(id, false, "MT5 has no symbol called '" + wantSym + "'"); return; }
   PushResult(id, true, "Spec " + sym, SpecJson(sym));
  }

//+------------------------------------------------------------------+
//| Command line:  CMD|id|type|symbol|side|volume|price|sl|tp|ticket  |
//| A lone "-" means the field is empty.                              |
//+------------------------------------------------------------------+
bool Has(const string f) { return(f != "-" && f != ""); }

void HandleLine(const string line)
  {
   string f[];
   int n = StringSplit(line, '|', f);
   if(n < 10 || f[0] != "CMD") return;
   string id = f[1], type = f[2];
   double vol   = Has(f[5]) ? StringToDouble(f[5]) : 0.0;
   double price = Has(f[6]) ? StringToDouble(f[6]) : 0.0;
   double sl    = Has(f[7]) ? StringToDouble(f[7]) : 0.0;
   double tp    = Has(f[8]) ? StringToDouble(f[8]) : 0.0;
   ulong ticket = Has(f[9]) ? (ulong)StringToInteger(f[9]) : 0;

   Print("PROTrader Bridge received: ", line);
   if(type == "market" || type == "limit" || type == "stop")
      ExecEntry(id, type, f[3], f[4], vol, Has(f[6]), price, Has(f[7]), sl, Has(f[8]), tp);
   else if(type == "close")    ExecClose(id, ticket, Has(f[5]), vol);
   else if(type == "modify")   ExecModify(id, ticket, Has(f[7]), sl, Has(f[8]), tp);
   else if(type == "cancel")   ExecCancel(id, ticket);
   else if(type == "closeall") ExecCloseAll(id);
   else if(type == "spec")     ExecSpec(id, f[3]);
   else PushResult(id, false, "Unknown command '" + type + "'");
  }

//+------------------------------------------------------------------+
//| Snapshot                                                          |
//+------------------------------------------------------------------+
string PositionsJson()
  {
   string out = "[";
   bool first = true;
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      if(!first) out += ",";
      first = false;
      out += "{\"ticket\":" + JStr(IntegerToString((long)t)) +
             ",\"symbol\":" + JStr(sym) +
             ",\"side\":" + JStr(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell") +
             ",\"volume\":" + JNum(PositionGetDouble(POSITION_VOLUME), 4) +
             ",\"entry\":" + JNum(PositionGetDouble(POSITION_PRICE_OPEN), dg) +
             ",\"price\":" + JNum(PositionGetDouble(POSITION_PRICE_CURRENT), dg) +
             ",\"sl\":" + JNum(PositionGetDouble(POSITION_SL), dg) +
             ",\"tp\":" + JNum(PositionGetDouble(POSITION_TP), dg) +
             ",\"profit\":" + JNum(PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP), 2) +
             ",\"time\":" + IntegerToString((long)PositionGetInteger(POSITION_TIME)) +
             ",\"digits\":" + IntegerToString(dg) +
             ",\"mine\":" + JBool(PositionGetInteger(POSITION_MAGIC) == MagicNumber) + "}";
     }
   return(out + "]");
  }

string OrdersJson()
  {
   string out = "[";
   bool first = true;
   for(int i = 0; i < OrdersTotal(); i++)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      string sym = OrderGetString(ORDER_SYMBOL);
      int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      long ot = OrderGetInteger(ORDER_TYPE);
      string side = (ot == ORDER_TYPE_BUY_LIMIT || ot == ORDER_TYPE_BUY_STOP || ot == ORDER_TYPE_BUY_STOP_LIMIT) ? "buy" : "sell";
      string kind = (ot == ORDER_TYPE_BUY_LIMIT || ot == ORDER_TYPE_SELL_LIMIT) ? "limit" : "stop";
      if(!first) out += ",";
      first = false;
      out += "{\"ticket\":" + JStr(IntegerToString((long)t)) +
             ",\"symbol\":" + JStr(sym) + ",\"side\":" + JStr(side) + ",\"kind\":" + JStr(kind) +
             ",\"volume\":" + JNum(OrderGetDouble(ORDER_VOLUME_CURRENT), 4) +
             ",\"price\":" + JNum(OrderGetDouble(ORDER_PRICE_OPEN), dg) +
             ",\"sl\":" + JNum(OrderGetDouble(ORDER_SL), dg) +
             ",\"tp\":" + JNum(OrderGetDouble(ORDER_TP), dg) +
             ",\"time\":" + IntegerToString((long)OrderGetInteger(ORDER_TIME_SETUP)) +
             ",\"digits\":" + IntegerToString(dg) + "}";
     }
   return(out + "]");
  }

// Closed trades and balance operations, newest first - the same list MT5
// shows under History.
string HistoryJson()
  {
   if(!HistorySelect(TimeCurrent() - HISTORY_DAYS * 86400, TimeCurrent() + 86400)) return("[]");
   int total = HistoryDealsTotal();
   string out = "[";
   int count = 0;
   for(int i = total - 1; i >= 0 && count < HISTORY_MAX; i--)
     {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      long type  = HistoryDealGetInteger(t, DEAL_TYPE);
      long entry = HistoryDealGetInteger(t, DEAL_ENTRY);
      long when  = (long)HistoryDealGetInteger(t, DEAL_TIME);
      string row = "";
      if(type == DEAL_TYPE_BALANCE)
        {
         row = "{\"kind\":\"balance\",\"ticket\":" + JStr(IntegerToString((long)t)) +
               ",\"amount\":" + JNum(HistoryDealGetDouble(t, DEAL_PROFIT), 2) +
               ",\"note\":" + JStr(HistoryDealGetString(t, DEAL_COMMENT)) +
               ",\"time\":" + IntegerToString(when) + "}";
        }
      else if((type == DEAL_TYPE_BUY || type == DEAL_TYPE_SELL) &&
              (entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT))
        {
         string sym = HistoryDealGetString(t, DEAL_SYMBOL);
         int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         long posId = HistoryDealGetInteger(t, DEAL_POSITION_ID);
         double openPx = 0.0; long openTime = 0;
         for(int k = 0; k < total; k++)          // find the deal that opened this position
           {
            ulong t2 = HistoryDealGetTicket(k);
            if(t2 == 0) continue;
            if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId && HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
              {
               openPx   = HistoryDealGetDouble(t2, DEAL_PRICE);
               openTime = (long)HistoryDealGetInteger(t2, DEAL_TIME);
               break;
              }
           }
         long reason = HistoryDealGetInteger(t, DEAL_REASON);
         string why = (reason == DEAL_REASON_SL) ? "Stop loss" : (reason == DEAL_REASON_TP) ? "Take profit" :
                      (reason == DEAL_REASON_SO) ? "Stop out" : (reason == DEAL_REASON_EXPERT) ? "PROTrader / EA" : "Manual";
         // the closing deal is the opposite direction to the position it closes
         row = "{\"kind\":\"trade\",\"ticket\":" + JStr(IntegerToString(posId)) +
               ",\"symbol\":" + JStr(sym) +
               ",\"side\":" + JStr(type == DEAL_TYPE_SELL ? "buy" : "sell") +
               ",\"volume\":" + JNum(HistoryDealGetDouble(t, DEAL_VOLUME), 4) +
               ",\"entry\":" + JNum(openPx, dg) +
               ",\"exit\":" + JNum(HistoryDealGetDouble(t, DEAL_PRICE), dg) +
               ",\"profit\":" + JNum(HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_SWAP) +
                                     HistoryDealGetDouble(t, DEAL_COMMISSION), 2) +
               ",\"openTime\":" + IntegerToString(openTime) +
               ",\"time\":" + IntegerToString(when) +
               ",\"digits\":" + IntegerToString(dg) +
               ",\"reason\":" + JStr(why) + "}";
        }
      if(row == "") continue;
      if(count > 0) out += ",";
      out += row;
      count++;
     }
   return(out + "]");
  }

string SnapshotJson(const bool withHistory)
  {
   RiskState rs; ReadRisk(rs);               // selects today's history; HistoryJson re-selects below
   double dayPnl = rs.dayPnl;
   string block  = EntryBlockReasonFor(rs);
   string j = "{\"ea\":{\"version\":" + JStr(EA_VERSION) +
              ",\"time\":" + IntegerToString((long)TimeCurrent()) +
              ",\"gmtOffset\":" + IntegerToString((long)(TimeCurrent() - TimeGMT())) + "}";
   j += ",\"account\":{\"login\":" + JStr(IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))) +
        ",\"server\":" + JStr(AccountInfoString(ACCOUNT_SERVER)) +
        ",\"currency\":" + JStr(AccountInfoString(ACCOUNT_CURRENCY)) +
        ",\"mode\":" + JStr(AccountModeText()) +
        ",\"balance\":" + JNum(AccountInfoDouble(ACCOUNT_BALANCE), 2) +
        ",\"equity\":" + JNum(AccountInfoDouble(ACCOUNT_EQUITY), 2) +
        ",\"margin\":" + JNum(AccountInfoDouble(ACCOUNT_MARGIN), 2) +
        ",\"free\":" + JNum(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) +
        ",\"dayPnl\":" + JNum(dayPnl, 2) +
        ",\"canEnter\":" + JBool(block == "") +
        ",\"blockReason\":" + JStr(block) + "}";
   j += ",\"limits\":{\"allowReal\":" + JBool(AllowRealAccount) +
        ",\"requireSl\":" + JBool(RequireStopLoss) +
        ",\"maxRisk\":" + JNum(rs.perTradeCap < 0.0 ? 0.0 : rs.perTradeCap, 2) +
        ",\"maxRiskPct\":" + JNum(MaxRiskPctPerTrade, 2) +
        ",\"openRisk\":" + JNum(rs.openRisk, 2) +
        ",\"openRiskCap\":" + JNum(rs.openRiskCap < 0.0 ? 0.0 : rs.openRiskCap, 2) +
        ",\"openRiskPct\":" + JNum(MaxOpenRiskPct, 2) +
        ",\"dailyLoss\":" + JNum(rs.dailyCap < 0.0 ? 0.0 : rs.dailyCap, 2) +
        ",\"dailyLossPct\":" + JNum(DailyLossLimitPct, 2) +
        ",\"startEquity\":" + JNum(rs.startEquity, 2) +
        ",\"lossesToday\":" + IntegerToString(rs.lossesToday) +
        ",\"maxLosses\":" + IntegerToString(MaxLosingTradesPerDay) +
        ",\"riskBudget\":" + JNum(rs.budget, 2) +
        ",\"unprotected\":" + IntegerToString(rs.unprotected) +
        ",\"maxMarginPct\":" + JNum(MaxMarginPctPerTrade, 2) +
        ",\"maxPositions\":" + IntegerToString(MaxOpenPositions) + "}";
   j += ",\"positions\":" + PositionsJson();
   j += ",\"orders\":" + OrdersJson();
   if(withHistory) j += ",\"history\":" + HistoryJson();
   j += ",\"results\":[";
   for(int i = 0; i < ArraySize(g_results); i++) { if(i > 0) j += ","; j += g_results[i]; }
   j += "]}";
   return(j);
  }

//+------------------------------------------------------------------+
//| One round trip with the relay                                     |
//+------------------------------------------------------------------+
void Sync()
  {
   bool withHistory = g_forceHistory || (TimeLocal() - g_lastHistory >= HISTORY_EVERY);
   string body = SnapshotJson(withHistory);

   char data[], reply[];
   string replyHeaders;
   int len = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 0) ArrayResize(data, len - 1);          // drop the trailing \0
   string headers = "Content-Type: application/json\r\nX-Bridge-Key: " + BridgeKey + "\r\n";

   ResetLastError();
   int code = WebRequest("POST", BridgeUrl + "/api/bridge/ea", headers, 5000, data, reply, replyHeaders);
   if(code != 200)
     {
      int err = GetLastError();
      g_failStreak++;
      g_skip = MathMin(g_failStreak, 10);           // back off, up to ~10 s
      if(code == -1 && err == 4014)
         g_status = "BLOCKED - add " + BridgeUrl + " under Tools > Options > Expert Advisors > Allow WebRequest";
      else if(code == -1)
         g_status = "Relay unreachable (error " + IntegerToString(err) + ") - retrying";
      else if(code == 401)
         g_status = "Relay refused the Bridge Key - check it matches the app";
      else
         g_status = "Relay answered HTTP " + IntegerToString(code) + " - retrying";
      return;
     }

   g_failStreak = 0;
   ArrayResize(g_results, 0);                        // delivered
   if(withHistory) { g_lastHistory = TimeLocal(); g_forceHistory = false; }
   g_status = "Connected";

   string text = CharArrayToString(reply, 0, WHOLE_ARRAY, CP_UTF8);
   string lines[];
   int n = StringSplit(text, '\n', lines);
   for(int i = 0; i < n; i++)
     {
      string ln = lines[i];
      StringReplace(ln, "\r", "");
      if(StringFind(ln, "CMD|") == 0) HandleLine(ln);
     }
  }

void ShowStatus()
  {
   RiskState r; ReadRisk(r);
   string block = EntryBlockReasonFor(r);
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   Comment("PROTrader Bridge v", EA_VERSION, "\n",
           "Relay:     ", g_status, "\n",
           "Account:   ", IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)), "  (", AccountModeText(), ")\n",
           "Entries:   ", (block == "" ? "ALLOWED" : "BLOCKED - " + block), "\n",
           "Today:     ", DoubleToString(r.dayPnl, 2), " ", cur,
           (r.dailyCap >= 0.0 ? "   (hard limit -" + DoubleToString(r.dailyCap, 2) + " = " + DoubleToString(DailyLossLimitPct, 1) + "% of " + DoubleToString(r.startEquity, 2) + ")" : ""), "\n",
           "Losses:    ", IntegerToString(r.lossesToday), (MaxLosingTradesPerDay > 0 ? " of " + IntegerToString(MaxLosingTradesPerDay) : ""), "\n",
           "Open risk: ", DoubleToString(r.openRisk, 2), (r.openRiskCap >= 0.0 ? " of " + DoubleToString(r.openRiskCap, 2) : ""),
           "   Next trade may risk: ", (r.budget < 0.0 ? "no cap" : DoubleToString(MathMax(0.0, r.budget), 2)), "\n",
           "Last:      ", g_lastAction);
  }
//+------------------------------------------------------------------+
