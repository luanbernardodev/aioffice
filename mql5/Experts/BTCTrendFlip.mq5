//+------------------------------------------------------------------+
//| BTCTrendFlip.mq5 — tendência em BTCUSD H4 (7º agente)            |
//| SuperTrend(10,3) + filtro EMA200 + stop inicial 2xATR(14) +      |
//| trailing chandelier 3xATR(14). Igual a backtest/btc_research.py  |
//| (variante "H4 SUPERTREND long+short").                           |
//|                                                                  |
//|  - Entrada: no fechamento da H4, virada da SuperTrend a favor da |
//|    EMA200 (compra: vira p/ alta e fecha acima; venda: espelho).  |
//|  - Saída: stop na corretora (inicial 2xATR, arrastado 3xATR do   |
//|    extremo) ou virada contrária válida (fecha e inverte).        |
//|  - Controle: btcflip_control.json do supervisor Python (enabled, |
//|    max_spread, direction, trail_atr). Sem controle válido ->     |
//|    não abre (posição aberta segue protegida pelo SL).            |
//|  - Só opera em conta DEMO; recusa duas cópias.                   |
//+------------------------------------------------------------------+
#property copyright "quant-office-ai"
#property version   "1.00"
#property strict

#define GF_CONTROL_FILE "btcflip_control.json"
#define GF_STATUS_FILE  "btcflip_status.json"
#define GF_STATUS_TMP   "btcflip_status.tmp"
#include <Trade\Trade.mqh>
#include <GoldFlipControl.mqh>

input long   InpMagic        = 20261109;   // Magic (nenhum outro agente toca)
input double InpLot          = 0.01;       // Lote fixo
input int    InpSTPeriod     = 10;         // SuperTrend: período do ATR
input double InpSTMult       = 3.0;        // SuperTrend: multiplicador
input int    InpEMAPeriod    = 200;        // Filtro de tendência (EMA)
input int    InpATRPeriod    = 14;         // ATR dos stops
input double InpInitStopATR  = 2.0;        // Stop inicial (x ATR)
input double InpTrailFallback= 3.0;        // Trailing (x ATR) se o controle não carregou
input int    InpBars         = 1500;       // Barras H4 para os cálculos
input int    InpDeviation    = 500;        // Desvio máximo (pontos)
input bool   InpAllowReal    = false;      // Conta REAL bloqueada

CTrade   g_trade;
datetime g_last_bar = 0;
double   g_ext  = 0.0;     // extremo desde a entrada (chandelier)
double   g_stop = 0.0;     // stop atual
string   g_gv;
string   g_lock;

struct Sig
  {
   int    flip;            // +1 compra, -1 venda, 0 nada (barra fechada mais recente)
   double atr;             // ATR(14) Wilder
   double high1, low1, close1;
  };

//--- SuperTrend + EMA + ATR (Wilder) sobre as barras H4 fechadas, mais antiga primeiro
bool Compute(Sig &s)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_H4, 1, InpBars, r);
   if(n < InpEMAPeriod + 50)
      return false;
   double atrST[], atrN[], ema[], fub[], flb[];
   int    dir[];
   ArrayResize(atrST, n); ArrayResize(atrN, n); ArrayResize(ema, n);
   ArrayResize(fub, n);   ArrayResize(flb, n);  ArrayResize(dir, n);
   double kE = 2.0 / (InpEMAPeriod + 1.0);
   for(int i = 0; i < n; i++)
     {
      double tr = r[i].high - r[i].low;
      if(i > 0)
         tr = MathMax(tr, MathMax(MathAbs(r[i].high - r[i - 1].close), MathAbs(r[i].low - r[i - 1].close)));
      atrST[i] = (i == 0) ? tr : atrST[i - 1] + (tr - atrST[i - 1]) / InpSTPeriod;
      atrN[i]  = (i == 0) ? tr : atrN[i - 1] + (tr - atrN[i - 1]) / InpATRPeriod;
      ema[i]   = (i == 0) ? r[i].close : ema[i - 1] + kE * (r[i].close - ema[i - 1]);
      double hl2 = (r[i].high + r[i].low) / 2.0;
      double ub = hl2 + InpSTMult * atrST[i], lb = hl2 - InpSTMult * atrST[i];
      dir[i] = 0;
      if(i < InpSTPeriod - 1)          // ATR ainda não válido (min_periods)
        {
         fub[i] = 0; flb[i] = 0;
         continue;
        }
      if(i == InpSTPeriod - 1)
        {
         fub[i] = ub; flb[i] = lb; dir[i] = 1;
         continue;
        }
      fub[i] = (ub < fub[i - 1] || r[i - 1].close > fub[i - 1]) ? ub : fub[i - 1];
      flb[i] = (lb > flb[i - 1] || r[i - 1].close < flb[i - 1]) ? lb : flb[i - 1];
      int prev = (dir[i - 1] != 0) ? dir[i - 1] : 1;
      dir[i] = (r[i].close > fub[i - 1]) ? 1 : ((r[i].close < flb[i - 1]) ? -1 : prev);
     }
   int k = n - 1;
   s.flip = 0;
   if(dir[k] == 1 && dir[k - 1] == -1 && r[k].close > ema[k])
      s.flip = 1;
   if(dir[k] == -1 && dir[k - 1] == 1 && r[k].close < ema[k])
      s.flip = -1;
   s.atr = atrN[k];
   s.high1 = r[k].high; s.low1 = r[k].low; s.close1 = r[k].close;
   return true;
  }

bool OwnPosition(ulong &ticket, int &side)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      ticket = t;
      side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      return true;
     }
   return false;
  }

void Save() { GlobalVariableSet(g_gv + "ext", g_ext); GlobalVariableSet(g_gv + "stop", g_stop); }

double TrailMult() { return (g_gf_ctl.loaded && g_gf_ctl.trail_atr > 0) ? g_gf_ctl.trail_atr : InpTrailFallback; }

bool Allowed(const int side, const double atr)
  {
   if(g_gf_ctl.flatten || !GF_CanOpen(_Symbol, atr))
      return false;
   if(g_gf_ctl.direction != 0 && side != g_gf_ctl.direction)
      return false;
   return true;
  }

void Open(const int side, const double atr, const string why)
  {
   double price = (side == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = NormalizeDouble(price - side * InpInitStopATR * atr, _Digits);
   bool ok = (side == 1) ? g_trade.Buy(InpLot, _Symbol, 0.0, sl, 0.0, "BTF|" + why)
                         : g_trade.Sell(InpLot, _Symbol, 0.0, sl, 0.0, "BTF|" + why);
   if(ok)
     {
      g_ext = price;
      g_stop = sl;
      Save();
     }
   PrintFormat("[BTCTrendFlip] %s %.2f @%.2f sl=%.2f (%s) -> %s (%d)", side == 1 ? "BUY" : "SELL", InpLot, price, sl,
               why, ok ? "OK" : "FALHOU", g_trade.ResultRetcode());
  }

void CloseOwn(const string why)
  {
   ulong t; int s;
   while(OwnPosition(t, s))
     {
      if(!g_trade.PositionClose(t))
        {
         PrintFormat("[BTCTrendFlip] falha ao fechar #%I64u (%s): %d", t, why, g_trade.ResultRetcode());
         return;
        }
      PrintFormat("[BTCTrendFlip] posição #%I64u fechada: %s", t, why);
     }
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !InpAllowReal)
     {
      Print("[BTCTrendFlip] conta NÃO é DEMO -> EA bloqueado");
      return INIT_FAILED;
     }
   g_gv = StringFormat("BTF_%I64d_%s_", InpMagic, _Symbol);
   g_lock = g_gv + "lock";
   if(GlobalVariableCheck(g_lock))
     {
      long other = (long)GlobalVariableGet(g_lock);
      if(other != ChartID() && ChartSymbol(other) != "")
        {
         PrintFormat("[BTCTrendFlip] já existe uma cópia no gráfico %I64d -> esta não inicia", other);
         return INIT_FAILED;
        }
     }
   GlobalVariableSet(g_lock, (double)ChartID());
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDeviation);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   ulong t; int s;
   if(OwnPosition(t, s))
     {
      if(GlobalVariableCheck(g_gv + "stop"))
        {
         g_ext = GlobalVariableGet(g_gv + "ext");
         g_stop = GlobalVariableGet(g_gv + "stop");
        }
      else
        {
         g_ext = PositionGetDouble(POSITION_PRICE_OPEN);
         g_stop = PositionGetDouble(POSITION_SL);
        }
      PrintFormat("[BTCTrendFlip] posição existente #%I64u retomada: ext=%.2f stop=%.2f", t, g_ext, g_stop);
     }
   g_last_bar = iTime(_Symbol, PERIOD_H4, 0);      // só age na PRÓXIMA H4 fechada (sem sinal velho na partida)
   EventSetTimer(60);
   GF_Timer(_Symbol, InpMagic);
   PrintFormat("[BTCTrendFlip] iniciado | %s H4 magic=%I64d lote=%.2f ST(%d,%.1f) EMA%d stop %.1f/%.1fxATR",
               _Symbol, InpMagic, InpLot, InpSTPeriod, InpSTMult, InpEMAPeriod, InpInitStopATR, InpTrailFallback);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Save();
   if(GlobalVariableCheck(g_lock) && (long)GlobalVariableGet(g_lock) == ChartID())
      GlobalVariableDel(g_lock);
  }

void OnTimer()
  {
   GF_Timer(_Symbol, InpMagic);
   if(g_gf_ctl.loaded && g_gf_ctl.flatten && (long)TimeGMT() <= g_gf_ctl.valid_until)
      CloseOwn("flatten: " + g_gf_ctl.reason);
  }

void OnTick()
  {
   GF_SampleSpread(_Symbol);
   datetime bar = iTime(_Symbol, PERIOD_H4, 0);
   if(bar == g_last_bar)
      return;
   g_last_bar = bar;

   Sig s;
   if(!Compute(s) || s.atr <= 0)
      return;
   ulong t; int side;
   bool has = OwnPosition(t, side);

   if(has)
     {
      // trailing chandelier no fechamento da H4
      double k = TrailMult();
      if(side == 1)
        {
         g_ext = MathMax(g_ext, s.high1);
         g_stop = MathMax(g_stop, g_ext - k * s.atr);
        }
      else
        {
         g_ext = (g_ext > 0) ? MathMin(g_ext, s.low1) : s.low1;
         g_stop = (g_stop > 0) ? MathMin(g_stop, g_ext + k * s.atr) : g_ext + k * s.atr;
        }
      Save();
      double sl = NormalizeDouble(g_stop, _Digits), cur = PositionGetDouble(POSITION_SL);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      bool better = (side == 1) ? (cur == 0 || sl > cur + _Point) : (cur == 0 || sl < cur - _Point);
      bool valid  = (side == 1) ? (sl < bid) : (sl > ask);
      if(better && valid && !g_trade.PositionModify(t, sl, 0.0))
         PrintFormat("[BTCTrendFlip] falha ao mover SL -> %.2f: %d", sl, g_trade.ResultRetcode());
      // virada contrária válida: fecha e inverte
      if(s.flip == -side)
        {
         CloseOwn("virada contrária da SuperTrend");
         if(Allowed(s.flip, s.atr))
            Open(s.flip, s.atr, "FLIP");
        }
      return;
     }

   if(s.flip != 0)
     {
      if(Allowed(s.flip, s.atr))
         Open(s.flip, s.atr, "ENTRY");
      else
         PrintFormat("[BTCTrendFlip] sinal %s ignorado: controle (enabled=%s regime=%s) | %s",
                     s.flip == 1 ? "COMPRA" : "VENDA", g_gf_ctl.enabled ? "true" : "false", g_gf_ctl.regime,
                     g_gf_ctl.reason);
     }
  }
//+------------------------------------------------------------------+
