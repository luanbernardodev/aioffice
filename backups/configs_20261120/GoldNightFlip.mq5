//+------------------------------------------------------------------+
//| GoldNightFlip.mq5 — madrugada: stop-and-reverse com trailing ATR em GOLD    |
//| 6º agente do quant-office-ai. Controlado pelo supervisor Python  |
//| (agents/goldflip_supervisor.py) via MQL5/Files/goldflip_control.json
//|                                                                  |
//| Lógica (igual ao backtest backtest/goldflip_bt.py):              |
//|  - SAR virtual sempre ativo no M5: comprado -> stop = max(stop,  |
//|    maior fechamento desde a virada - k*ATR); vendido -> espelho. |
//|  - Toque no stop -> vira de lado; abre a nova perna se permitido.|
//|  - Permitido = controle enabled e válido, spread <= max_spread,  |
//|    ATR >= min_atr, e (Modo B) só a favor da direção do supervisor.
//|  - flatten=true (fora de sessão / notícia / kill switch) -> zera.|
//|  - Stop SEMPRE registrado na corretora (posição protegida mesmo  |
//|    se o EA/terminal cair).                                       |
//|  - Só opera em conta DEMO (trava).                               |
//+------------------------------------------------------------------+
#property copyright "quant-office-ai"
#property version   "1.00"
#property strict

#define GF_CONTROL_FILE "goldnight_control.json"
#define GF_STATUS_FILE  "goldnight_status.json"
#define GF_STATUS_TMP   "goldnight_status.tmp"
#include <Trade\Trade.mqh>
#include <GoldFlipControl.mqh>

enum ENUM_GF_MODE { GF_MODE_ALL_LEGS = 0, GF_MODE_TREND_ONLY = 1 };

input long         InpMagic          = 20261113;          // Magic (nenhum outro agente toca)
input double       InpLot            = 0.01;              // Lote fixo
input ENUM_GF_MODE InpMode           = GF_MODE_TREND_ONLY;// A = todas as pernas / B = só a favor da tendência
input int          InpATRPeriod      = 14;                // ATR (M5)
input double       InpTrailFallback  = 3.0;               // Trailing (x ATR) se o controle não carregou
input int          InpDeviation      = 30;                // Desvio máximo (pontos)
input bool         InpAllowReal      = false;             // Conta REAL bloqueada

CTrade   g_trade;
int      g_atr_handle = INVALID_HANDLE;
datetime g_last_bar   = 0;
int      g_sar        = 0;       // +1 comprado / -1 vendido (virtual)
double   g_ext        = 0.0;     // extremo de fechamento desde a virada
double   g_stop       = 0.0;     // stop do SAR
string   g_gv_prefix;
string   g_lock_name;

//--- persistência do SAR (sobrevive a restart do terminal)
void SaveState()
  {
   GlobalVariableSet(g_gv_prefix + "sar", g_sar);
   GlobalVariableSet(g_gv_prefix + "ext", g_ext);
   GlobalVariableSet(g_gv_prefix + "stop", g_stop);
  }

void LoadState()
  {
   if(GlobalVariableCheck(g_gv_prefix + "sar"))
     {
      g_sar  = (int)GlobalVariableGet(g_gv_prefix + "sar");
      g_ext  = GlobalVariableGet(g_gv_prefix + "ext");
      g_stop = GlobalVariableGet(g_gv_prefix + "stop");
      PrintFormat("[GoldNightFlip] estado restaurado: sar=%d ext=%.2f stop=%.2f", g_sar, g_ext, g_stop);
     }
  }

double ATR(const int shift)
  {
   double buf[];
   if(CopyBuffer(g_atr_handle, 0, shift, 1, buf) != 1)
      return 0.0;
   return buf[0];
  }

double TrailMult() { return (g_gf_ctl.loaded && g_gf_ctl.trail_atr > 0) ? g_gf_ctl.trail_atr : InpTrailFallback; }

//--- posição deste EA (uma por vez)
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

void CloseOwn(const string why)
  {
   ulong t; int s;
   while(OwnPosition(t, s))
     {
      if(!g_trade.PositionClose(t))
        {
         PrintFormat("[GoldNightFlip] falha ao fechar #%I64u (%s): %d", t, why, g_trade.ResultRetcode());
         return;
        }
      PrintFormat("[GoldNightFlip] posição #%I64u fechada: %s", t, why);
     }
  }

bool Allowed(const int side)
  {
   if(g_gf_ctl.flatten)
      return false;
   if(!GF_CanOpen(_Symbol, ATR(1)))
      return false;
   if(InpMode == GF_MODE_TREND_ONLY && side != g_gf_ctl.direction)
      return false;
   return true;
  }

void Open(const int side, const string why)
  {
   double sl = NormalizeDouble(g_stop, _Digits);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if((side == 1 && sl >= bid) || (side == -1 && sl <= ask))
      return;                                        // stop já do lado errado: espera a próxima barra
   bool ok = (side == 1) ? g_trade.Buy(InpLot, _Symbol, 0.0, sl, 0.0, "GFT|" + why)
                         : g_trade.Sell(InpLot, _Symbol, 0.0, sl, 0.0, "GFT|" + why);
   PrintFormat("[GoldNightFlip] %s %s %.2f sl=%.2f regime=%s -> %s (%d)", side == 1 ? "BUY" : "SELL", why, InpLot, sl,
               g_gf_ctl.regime, ok ? "OK" : "FALHOU", g_trade.ResultRetcode());
  }

//--- ajusta o SL da posição na corretora para o stop do SAR (só a favor)
void SyncBrokerStop()
  {
   ulong t; int s;
   if(!OwnPosition(t, s) || s != g_sar)
      return;
   double sl = NormalizeDouble(g_stop, _Digits);
   double cur = PositionGetDouble(POSITION_SL);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool better = (s == 1) ? (cur == 0.0 || sl > cur + _Point) : (cur == 0.0 || sl < cur - _Point);
   bool valid  = (s == 1) ? (sl < bid) : (sl > ask);
   if(better && valid && !g_trade.PositionModify(t, sl, 0.0))
      PrintFormat("[GoldNightFlip] falha ao mover SL #%I64u -> %.2f: %d", t, sl, g_trade.ResultRetcode());
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !InpAllowReal)
     {
      Print("[GoldNightFlip] conta NÃO é DEMO -> EA bloqueado");
      return INIT_FAILED;
     }
   g_gv_prefix = StringFormat("GNF_%I64d_%s_", InpMagic, _Symbol);
   g_lock_name = g_gv_prefix + "lock";
   // trava contra duas cópias do EA (dois gráficos) na mesma conta/símbolo/magic
   if(GlobalVariableCheck(g_lock_name))
     {
      long other = (long)GlobalVariableGet(g_lock_name);
      if(other != ChartID() && ChartSymbol(other) != "")
        {
         PrintFormat("[GoldNightFlip] já existe uma cópia rodando no gráfico %I64d -> esta não inicia", other);
         return INIT_FAILED;
        }
     }
   GlobalVariableSet(g_lock_name, (double)ChartID());

   g_atr_handle = iATR(_Symbol, PERIOD_M5, InpATRPeriod);
   if(g_atr_handle == INVALID_HANDLE)
      return INIT_FAILED;
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDeviation);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   LoadState();
   EventSetTimer(60);
   GF_Timer(_Symbol, InpMagic);
   PrintFormat("[GoldNightFlip] iniciado | %s magic=%I64d lote=%.2f modo=%s", _Symbol, InpMagic, InpLot,
               InpMode == GF_MODE_TREND_ONLY ? "B (só tendência)" : "A (todas as pernas)");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   SaveState();
   if(GlobalVariableCheck(g_lock_name) && (long)GlobalVariableGet(g_lock_name) == ChartID())
      GlobalVariableDel(g_lock_name);
   if(g_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_atr_handle);
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
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // 1) nova barra M5 fechada: inicializa/arrasta o SAR
   datetime bar = iTime(_Symbol, PERIOD_M5, 0);
   if(bar != g_last_bar)
     {
      g_last_bar = bar;
      double atr = ATR(1), c1 = iClose(_Symbol, PERIOD_M5, 1);
      if(atr <= 0 || c1 <= 0)
         return;
      double k = TrailMult();
      if(g_sar == 0)
        {
         g_sar  = (c1 >= iClose(_Symbol, PERIOD_M5, 21)) ? 1 : -1;
         g_ext  = c1;
         g_stop = g_ext - g_sar * k * atr;
        }
      else if(g_sar == 1)
        {
         g_ext  = MathMax(g_ext, c1);
         g_stop = MathMax(g_stop, g_ext - k * atr);
        }
      else
        {
         g_ext  = MathMin(g_ext, c1);
         g_stop = MathMin(g_stop, g_ext + k * atr);
        }
      SaveState();
      SyncBrokerStop();
      ulong t; int s;
      if(!OwnPosition(t, s) && Allowed(g_sar))
         Open(g_sar, "ENTRY");
     }

   // 2) toque no stop do SAR (intrabar): vira de lado
   bool hit = (g_sar == 1 && bid <= g_stop) || (g_sar == -1 && ask >= g_stop);
   if(hit && g_sar != 0)
     {
      ulong t; int s;
      if(OwnPosition(t, s) && s == g_sar)
         CloseOwn("stop do SAR");                    // caso o SL da corretora ainda não tenha executado
      double atr = ATR(1);
      g_sar  = -g_sar;
      g_ext  = (g_sar == 1) ? ask : bid;
      g_stop = g_ext - g_sar * TrailMult() * atr;
      SaveState();
      PrintFormat("[GoldNightFlip] FLIP -> %s | novo stop %.2f", g_sar == 1 ? "COMPRADO" : "VENDIDO", g_stop);
      if(Allowed(g_sar))
         Open(g_sar, "FLIP");
     }
  }
//+------------------------------------------------------------------+
