//+------------------------------------------------------------------+
//| GoldFlipControl.mqh — ponte EA GoldFlipTrail <-> quant-office-ai |
//|                                                                  |
//| Python (agents/goldflip_supervisor.py) escreve, a cada 5 min:    |
//|   MQL5/Files/goldflip_control.json                               |
//|   {enabled, trail_atr, min_atr, max_spread, regime, valid_until} |
//| O EA lê a cada 60s e escreve MQL5/Files/goldflip_status.json     |
//|   {position, volume, day_pnl, trades_last_hour, avg_spread...}   |
//|                                                                  |
//| Integração no GoldFlipTrail.mq5 (copiar este arquivo p/ MQL5/Include):
//|   #include <GoldFlipControl.mqh>                                 |
//|   OnInit():   EventSetTimer(60); GF_Timer(_Symbol, InpMagic);     |
//|   OnDeinit(): EventKillTimer();                                  |
//|   OnTimer():  GF_Timer(_Symbol, InpMagic);                       |
//|   OnTick():   GF_SampleSpread(_Symbol);                          |
//|               antes de ABRIR ou FLIPAR: if(!GF_CanOpen(_Symbol, atr)) return-sem-abrir;
//|               distância do trailing: g_gf_ctl.trail_atr * atr    |
//|   Posições já abertas continuam sendo geridas pelo trailing do EA.
//+------------------------------------------------------------------+
#property strict

// Outros EAs podem definir estes nomes ANTES do #include (ex.: BTCTrendFlip usa btcflip_*.json)
#ifndef GF_CONTROL_FILE
#define GF_CONTROL_FILE "goldflip_control.json"
#endif
#ifndef GF_STATUS_FILE
#define GF_STATUS_FILE  "goldflip_status.json"
#endif
#ifndef GF_STATUS_TMP
#define GF_STATUS_TMP   "goldflip_status.tmp"
#endif

struct GFControl
  {
   bool              loaded;
   bool              enabled;
   bool              flatten;      // true = zerar posição (fora de sessão, notícia, kill switch)
   int               direction;    // +1/-1 tendência do supervisor, 0 = sem tendência
   double            trail_atr;
   double            min_atr;
   int               max_spread;   // pontos
   long              valid_until;  // epoch UTC
   long              updated_at;   // epoch UTC
   string            regime;
   string            reason;
  };

GFControl g_gf_ctl;
double    g_gf_spread_sum = 0.0;
long      g_gf_spread_n   = 0;

//--- lê o arquivo inteiro (JSON em uma linha, ASCII)
string GF_ReadAll(const string name)
  {
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return "";
   string s = "";
   while(!FileIsEnding(h))
      s += FileReadString(h);
   FileClose(h);
   return s;
  }

//--- valor bruto de "key": em JSON plano (sem objetos aninhados)
string GF_JsonRaw(const string json, const string key)
  {
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0)
      return "";
   p += StringLen(pat);
   int n = StringLen(json);
   while(p < n && StringGetCharacter(json, p) == ' ')
      p++;
   if(p < n && StringGetCharacter(json, p) == '"')
     {
      int e = StringFind(json, "\"", p + 1);
      return (e > p) ? StringSubstr(json, p + 1, e - p - 1) : "";
     }
   int e = p;
   while(e < n)
     {
      ushort c = StringGetCharacter(json, e);
      if(c == ',' || c == '}')
         break;
      e++;
     }
   string v = StringSubstr(json, p, e - p);
   StringTrimLeft(v);
   StringTrimRight(v);
   return v;
  }

//--- carrega o controle; arquivo ausente/ilegível/vencido => desligado (fail-safe)
bool GF_ReadControl(GFControl &c)
  {
   string js = GF_ReadAll(GF_CONTROL_FILE);
   if(js == "" || StringFind(js, "\"enabled\"") < 0)
     {
      c.loaded  = false;
      c.enabled = false;
      c.flatten = false;
      PrintFormat("[GoldFlipControl] %s ausente/ilegível -> entradas bloqueadas", GF_CONTROL_FILE);
      return false;
     }
   bool was = c.enabled;
   c.enabled     = (GF_JsonRaw(js, "enabled") == "true");
   c.flatten     = (GF_JsonRaw(js, "flatten") == "true");
   c.direction   = (int)StringToInteger(GF_JsonRaw(js, "direction"));
   c.trail_atr   = StringToDouble(GF_JsonRaw(js, "trail_atr"));
   c.min_atr     = StringToDouble(GF_JsonRaw(js, "min_atr"));
   c.max_spread  = (int)StringToInteger(GF_JsonRaw(js, "max_spread"));
   c.valid_until = StringToInteger(GF_JsonRaw(js, "valid_until"));
   c.updated_at  = StringToInteger(GF_JsonRaw(js, "updated_at"));
   c.regime      = GF_JsonRaw(js, "regime");
   c.reason      = GF_JsonRaw(js, "reason");
   c.loaded      = true;
   if((long)TimeGMT() > c.valid_until)
     {
      c.enabled = false;
      PrintFormat("[GoldFlipControl] controle vencido há %I64ds (supervisor parado?) -> entradas bloqueadas",
                  (long)TimeGMT() - c.valid_until);
     }
   if(was != c.enabled)
      PrintFormat("[GoldFlipControl] enabled=%s flatten=%s dir=%d regime=%s trail=%.2fxATR min_atr=%.2f max_spread=%d | %s",
                  c.enabled ? "true" : "false", c.flatten ? "true" : "false", c.direction, c.regime, c.trail_atr, c.min_atr, c.max_spread, c.reason);
   return true;
  }

//--- pode abrir/flipar agora? (spread e ATR mínimos do supervisor)
bool GF_CanOpen(const string sym, const double atr)
  {
   if(!g_gf_ctl.loaded || !g_gf_ctl.enabled)
      return false;
   if((long)TimeGMT() > g_gf_ctl.valid_until)
      return false;
   long spread = SymbolInfoInteger(sym, SYMBOL_SPREAD);
   if(g_gf_ctl.max_spread > 0 && spread > g_gf_ctl.max_spread)
      return false;
   if(g_gf_ctl.min_atr > 0 && atr < g_gf_ctl.min_atr)
      return false;
   return true;
  }

//--- trailing em múltiplos de ATR vindo do supervisor (fallback se ainda não carregou)
double GF_TrailDistance(const double atr, const double fallback_mult)
  {
   double m = (g_gf_ctl.loaded && g_gf_ctl.trail_atr > 0) ? g_gf_ctl.trail_atr : fallback_mult;
   return m * atr;
  }

void GF_SampleSpread(const string sym)
  {
   g_gf_spread_sum += (double)SymbolInfoInteger(sym, SYMBOL_SPREAD);
   g_gf_spread_n++;
  }

//--- status: posição, PnL do dia (UTC), trades/hora, spread médio desde o último status
void GF_WriteStatus(const string sym, const long magic)
  {
   double net = 0, vol = 0, flt = 0;
   int    cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != magic || PositionGetString(POSITION_SYMBOL) != sym)
         continue;
      double v = PositionGetDouble(POSITION_VOLUME);
      net += (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? v : -v;
      vol += v;
      flt += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      cnt++;
     }

   datetime srv = TimeCurrent();
   datetime gmt = TimeGMT();
   long     off = (long)srv - (long)gmt;                       // servidor - UTC
   datetime day_start_srv = (datetime)(((long)gmt / 86400) * 86400 + off);
   double   day_pnl  = 0;
   int      trades_h = 0;
   if(HistorySelect(day_start_srv - 3600, srv + 60))
     {
      for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0 || HistoryDealGetInteger(d, DEAL_MAGIC) != magic)
            continue;
         datetime dt    = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
         long     entry = HistoryDealGetInteger(d, DEAL_ENTRY);
         if(dt >= day_start_srv)
            day_pnl += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP)
                       + HistoryDealGetDouble(d, DEAL_COMMISSION);
         if((entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT) && dt >= srv - 3600)
            trades_h++;
        }
     }

   double avg_sp = (g_gf_spread_n > 0) ? g_gf_spread_sum / g_gf_spread_n : (double)SymbolInfoInteger(sym, SYMBOL_SPREAD);
   g_gf_spread_sum = 0;
   g_gf_spread_n   = 0;
   string pos = (cnt == 0) ? "FLAT" : (net > 0 ? "LONG" : (net < 0 ? "SHORT" : "HEDGED"));
   bool   eff = g_gf_ctl.loaded && g_gf_ctl.enabled && (long)gmt <= g_gf_ctl.valid_until;

   string js = StringFormat("{\"updated_at\":%I64d,\"symbol\":\"%s\",\"magic\":%I64d,\"position\":\"%s\","
                            "\"volume\":%.2f,\"net_lots\":%.2f,\"positions\":%d,\"floating_pnl\":%.2f,"
                            "\"day_pnl\":%.2f,\"trades_last_hour\":%d,\"avg_spread_points\":%.1f,"
                            "\"control_enabled\":%s,\"control_regime\":\"%s\",\"control_age_s\":%I64d}",
                            (long)gmt, sym, magic, pos, vol, net, cnt, flt, day_pnl, trades_h, avg_sp,
                            eff ? "true" : "false", g_gf_ctl.regime,
                            g_gf_ctl.loaded ? (long)gmt - g_gf_ctl.updated_at : -1);
   int h = FileOpen(GF_STATUS_TMP, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, js);
   FileClose(h);
   if(!FileMove(GF_STATUS_TMP, 0, GF_STATUS_FILE, FILE_REWRITE))
      PrintFormat("[GoldFlipControl] falha ao gravar status: %d", GetLastError());
  }

//--- chamar no OnTimer (60s) e no OnInit
void GF_Timer(const string sym, const long magic)
  {
   GF_ReadControl(g_gf_ctl);
   GF_WriteStatus(sym, magic);
  }
//+------------------------------------------------------------------+
