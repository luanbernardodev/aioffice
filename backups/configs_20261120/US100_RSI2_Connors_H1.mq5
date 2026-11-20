//+------------------------------------------------------------------+
//| US100_RSI2_Connors_H1.mq5                                         |
//| Validação no Strategy Tester do RSI(2) Connors H1 (somente compra)|
//| Mesma lógica do bt2 (backtest/claude_code/us100/grid_wr.py):      |
//|  - no fechamento H1: RSI(2) < 5 e close > SMA(100) -> compra a     |
//|    mercado (= open da barra seguinte); SL = entrada - 3*ATR(sinal)|
//|  - fechamento com RSI(5) > 60 -> fecha no open seguinte           |
//|  - máxima desde a entrada >= entrada + 1.5*ATR(sinal) ->          |
//|    stop = máxima - 1.5*ATR(14) atual, a cada fechamento, só sobe  |
//| RSI e ATR de Wilder calculados aqui (iATR do MT5 usa média simples)|
//| Magic próprio do EA (o agente Python US100_RSI2_H1 usa 20261115). |
//+------------------------------------------------------------------+
#property copyright "aioffice"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

input double InpLots        = 0.0;     // 0 = volume mínimo do símbolo
input int    InpRsiN        = 2;
input double InpRsiTh       = 5.0;
input int    InpMaN         = 100;
input int    InpExitRsiN    = 5;
input double InpExitRsi     = 60.0;
input int    InpAtrN        = 14;
input double InpSlAtr       = 3.0;
input double InpTrailActAtr = 1.5;
input double InpTrailAtr    = 1.5;
input int    InpWarmBars    = 600;     // barras para o RSI/ATR de Wilder convergirem
input long   InpMagic       = 20261116;

CTrade   trade;
datetime g_lastBar = 0;
double   g_a0 = 0.0;                   // ATR da barra do sinal da posição aberta
datetime g_entryBar = 0;

//--- RSI de Wilder igual ao Python: ewm(alpha=1/n, adjust=False) desde a 1ª barra, diff(prepend=c0)
double WilderRsi(const double &c[], int n, int k)       // c em ordem cronológica, valor no índice k
  {
   double au = 0.0, ad = 0.0, a = 1.0 / n;
   for(int i = 0; i <= k; i++)
     {
      double d = (i == 0) ? 0.0 : c[i] - c[i - 1];
      double up = d > 0 ? d : 0.0, dn = d < 0 ? -d : 0.0;
      if(i == 0) { au = up; ad = dn; }
      else { au += a * (up - au); ad += a * (dn - ad); }
     }
   return 100.0 - 100.0 / (1.0 + au / MathMax(ad, 1e-9));
  }

//--- ATR de Wilder igual ao Python (TR da 1ª barra = high-low)
void WilderAtr(const double &h[], const double &l[], const double &c[], int n, double &out[])
  {
   int sz = ArraySize(c);
   ArrayResize(out, sz);
   double a = 1.0 / n, v = 0.0;
   for(int i = 0; i < sz; i++)
     {
      double pc = (i == 0) ? c[0] : c[i - 1];
      double tr = MathMax(h[i] - l[i], MathMax(MathAbs(h[i] - pc), MathAbs(l[i] - pc)));
      v = (i == 0) ? tr : v + a * (tr - v);
      out[i] = v;
     }
  }

bool LoadClosed(double &o[], double &h[], double &l[], double &c[], datetime &t[])
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(_Symbol, PERIOD_H1, 1, InpWarmBars, r);   // pos 1 = só barras fechadas
   if(got < InpMaN + 50) return false;
   ArrayResize(o, got); ArrayResize(h, got); ArrayResize(l, got); ArrayResize(c, got); ArrayResize(t, got);
   for(int i = 0; i < got; i++) { o[i] = r[i].open; h[i] = r[i].high; l[i] = r[i].low; c[i] = r[i].close; t[i] = r[i].time; }
   return true;
  }

bool MyPosition(ulong &ticket)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
        { ticket = tk; return true; }
     }
   return false;
  }

double Lots()
  {
   double v = InpLots > 0 ? InpLots : SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   return MathMax(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), MathFloor(v / st + 1e-9) * st);
  }

int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(500);
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
   datetime bar = iTime(_Symbol, PERIOD_H1, 0);
   if(bar == g_lastBar) return;
   g_lastBar = bar;

   double o[], h[], l[], c[], A[];
   datetime t[];
   if(!LoadClosed(o, h, l, c, t)) return;
   int k = ArraySize(c) - 1;                                  // última barra fechada
   WilderAtr(h, l, c, InpAtrN, A);
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   ulong tk;
   if(MyPosition(tk))
     {
      double entry = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL);
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      datetime ebar = opened - opened % 3600;
      if(g_a0 <= 0.0 || g_entryBar != ebar)                   // reinício: ATR da barra anterior à entrada
        {
         g_entryBar = ebar;
         for(int i = k; i >= 0; i--) if(t[i] < ebar) { g_a0 = A[i]; break; }
        }
      if(WilderRsi(c, InpExitRsiN, k) > InpExitRsi)           // saída por sinal no open desta barra
        {
         trade.PositionClose(tk);
         return;
        }
      double mx = entry;
      for(int i = 0; i <= k; i++) if(t[i] >= ebar) mx = MathMax(mx, h[i]);
      if(g_a0 > 0 && mx - entry >= InpTrailActAtr * g_a0)
        {
         double ns = NormalizeDouble(mx - InpTrailAtr * A[k], dg);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(ns > sl && ns < bid) trade.PositionModify(tk, ns, PositionGetDouble(POSITION_TP));
        }
      return;
     }

   // sem posição: sinal no fechamento da barra k
   double ma = 0.0;
   for(int i = k - InpMaN + 1; i <= k; i++) ma += c[i];
   ma /= InpMaN;
   if(WilderRsi(c, InpRsiN, k) < InpRsiTh && c[k] > ma && A[k] > 0)
     {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl = NormalizeDouble(ask - InpSlAtr * A[k], dg);
      if(trade.Buy(Lots(), _Symbol, ask, sl, 0.0, "US100_RSI2_TESTER"))
        { g_a0 = A[k]; g_entryBar = bar; }
     }
  }
//+------------------------------------------------------------------+
