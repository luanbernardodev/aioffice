'use client';

import React, { useState, useMemo } from 'react';
import { 
  Wallet, 
  TrendingUp, 
  TrendingDown, 
  Target, 
  Shield, 
  Activity, 
  X, 
  ExternalLink,
  Zap,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  Filter,
  CheckCircle2,
  DollarSign
} from 'lucide-react';
import { MT5AccountStatus, Trade } from '@/types';

interface MT5AccountPanelProps {
  account: MT5AccountStatus | null;
  trades: Trade[];
  isOpen?: boolean;
  onClose?: () => void;
  showFloatingBar?: boolean;
}

export const MT5AccountPanel: React.FC<MT5AccountPanelProps> = ({
  account,
  trades = [],
  isOpen,
  onClose,
  showFloatingBar = false,
}) => {
  const [internalIsOpenModal, setInternalIsOpenModal] = useState(false);
  const isOpenModal = isOpen !== undefined ? isOpen : internalIsOpenModal;
  
  const handleClose = () => {
    if (onClose) onClose();
    else setInternalIsOpenModal(false);
  };
  const handleOpen = () => {
    setInternalIsOpenModal(true);
  };

  const [activeTab, setActiveTab] = useState<'OPEN' | 'CLOSED'>('OPEN');
  const [symbolFilter, setSymbolFilter] = useState<string>('ALL');

  // Garante array de trades seguro
  const safeTrades = useMemo(() => (Array.isArray(trades) ? trades : []), [trades]);

  // Separação estrita de ordens abertas e fechadas
  const openTrades = useMemo(() => {
    return safeTrades.filter((t) => String(t.status || '').trim().toUpperCase() === 'OPEN');
  }, [safeTrades]);

  const closedTrades = useMemo(() => {
    return safeTrades.filter((t) => String(t.status || '').trim().toUpperCase() === 'CLOSED');
  }, [safeTrades]);

  // Valores reais da conta com fallback para $0.00 se vazio (100% confiável no Supabase)
  const balance = Number(account?.balance ?? 0.0);
  const equity = Number(account?.equity ?? balance);
  const floatingPnl = Number(account?.floating_pnl ?? 0.0);
  const freeMargin = Number(account?.free_margin ?? balance);
  const isConnected = Boolean(account?.is_connected);

  // Deriva métricas de TP / SL a partir do histórico de trades se a linha de status estiver com 0
  const { totalTpGain, totalSlLoss, winCount, lossCount, winRate, profitFactor } = useMemo(() => {
    let tpGain = Number(account?.total_tp_gain ?? 0.0);
    let slLoss = Number(account?.total_sl_loss ?? 0.0);
    let wCount = Number(account?.win_count ?? 0);
    let lCount = Number(account?.loss_count ?? 0);

    // Se o backend ainda não computou no account, calcula dinamicamente das trades fechadas
    if (wCount === 0 && lCount === 0 && closedTrades.length > 0) {
      tpGain = 0;
      slLoss = 0;
      closedTrades.forEach((t) => {
        const p = Number(t.profit_usd) || 0;
        if (p > 0) {
          wCount++;
          tpGain += p;
        } else if (p < 0) {
          lCount++;
          slLoss += p;
        }
      });
    }

    const totalDecided = wCount + lCount;
    const wr = totalDecided > 0 ? Math.round((wCount / totalDecided) * 100) : 0;
    const pf = Math.abs(slLoss) > 0 ? (tpGain / Math.abs(slLoss)).toFixed(2) : (tpGain > 0 ? '99.9' : '0.00');

    return {
      totalTpGain: Math.round(tpGain * 100) / 100,
      totalSlLoss: Math.round(slLoss * 100) / 100,
      winCount: wCount,
      lossCount: lCount,
      winRate: wr,
      profitFactor: pf,
    };
  }, [account, closedTrades]);

  const displayedTrades = useMemo(() => {
    const list = activeTab === 'OPEN' ? openTrades : closedTrades;
    return list.filter((t) => {
      if (symbolFilter === 'ALL') return true;
      return t.symbol === symbolFilter;
    });
  }, [activeTab, openTrades, closedTrades, symbolFilter]);

  // Cálculo visual de progresso de preço entre SL e TP
  const calculateProgress = (trade: Trade) => {
    const entry = Number(trade.entry_price) || 0;
    const isClosed = String(trade.status || '').trim().toUpperCase() === 'CLOSED';
    const current = Number((isClosed ? trade.close_price : trade.current_price) ?? entry);
    const sl = Number(trade.sl) || 0;
    const tp = Number(trade.tp) || 0;
    const isBuy = trade.order_type === 'BUY';

    let progress = 50;
    if (isClosed) {
      progress = (Number(trade.profit_usd) || 0) >= 0 ? 100 : 0;
    } else if (sl > 0 && tp > 0 && sl !== tp) {
      if (isBuy && tp > sl) {
        progress = ((current - sl) / (tp - sl)) * 100;
      } else if (!isBuy && sl > tp) {
        progress = ((sl - current) / (sl - tp)) * 100;
      }
    }
    progress = Math.max(0, Math.min(100, Math.round(progress)));

    // Estimativa de impacto financeiro em $
    const volume = Number(trade.volume) || 0.01;
    const contract = trade.symbol === 'XAUUSD' ? 100 : 1;
    const expectedTpGain = trade.risk_amount && sl > 0 && sl !== entry
      ? Math.abs((tp - entry) / (entry - sl)) * trade.risk_amount
      : tp > 0 ? Math.abs(tp - entry) * volume * contract : 0;
    const expectedSlLoss = trade.risk_amount
      ? trade.risk_amount
      : sl > 0 ? Math.abs(entry - sl) * volume * contract : 0;

    return { progress, current, expectedTpGain, expectedSlLoss };
  };

  return (
    <>
      {/* ========================================================= */}
      {/* 1. BARRA FINANCEIRA FLUTUANTE OPCIONAL                    */}
      {/* ========================================================= */}
      {showFloatingBar && (
        <div className="fixed top-3 left-1/2 -translate-x-1/2 z-50 pointer-events-auto">
          <div className="flex items-center gap-2.5 bg-slate-950/85 backdrop-blur-md border border-slate-800/80 rounded-full px-3.5 py-1.5 shadow-xl text-xs font-mono select-none">
            {/* MT5 Saldo */}
            <div className="flex items-center gap-1.5">
              <Wallet className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-slate-400 text-[10px]">SALDO:</span>
              <span className="font-bold text-slate-100">
                ${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>

            <span className="text-slate-700">|</span>

            {/* MT5 Equity + Floating PnL */}
            <div className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-yellow-400 fill-yellow-400" />
              <span className="text-slate-400 text-[10px]">EQUITY:</span>
              <span className="font-bold text-slate-100">
                ${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                floatingPnl >= 0 ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-500/40' : 'bg-rose-950/60 text-rose-400 border border-rose-500/40'
              }`}>
                {floatingPnl >= 0 ? `+$${floatingPnl.toFixed(2)}` : `-$${Math.abs(floatingPnl).toFixed(2)}`}
              </span>
            </div>

            <span className="hidden md:inline text-slate-700">|</span>

            {/* Margem Livre */}
            <div className="hidden md:flex items-center gap-1.5">
              <DollarSign className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-slate-400 text-[10px]">LIVRE:</span>
              <span className="font-bold text-cyan-300">
                ${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>

            <span className="text-slate-700">|</span>

            {/* Action Button: Abre Modal MT5 */}
            <button
              onClick={handleOpen}
              className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 hover:bg-cyan-900/70 border border-cyan-500/50 text-cyan-300 text-xs font-bold transition hover:scale-105 active:scale-95 cursor-pointer shadow-[0_0_10px_rgba(6,182,212,0.25)]"
            >
              <span>💹 Ordens (TP/SL)</span>
              {openTrades.length > 0 && (
                <span className="w-4 h-4 rounded-full bg-emerald-500 text-slate-950 text-[9px] font-bold flex items-center justify-center animate-pulse">
                  {openTrades.length}
                </span>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 2. RAIO-X DE TP & SL: MODAL DETALHADO COMPLETO (XM MT5)   */}
      {/* ========================================================= */}
      {isOpenModal && (
        <div className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-md pointer-events-auto animate-in fade-in duration-150">
          <div className="w-full max-w-5xl max-h-[88vh] bg-slate-950/95 border border-cyan-500/40 rounded-3xl p-5 shadow-2xl flex flex-col font-mono text-slate-100 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-700 flex items-center justify-center border border-cyan-300 shadow-[0_0_15px_#00f0ff]">
                  <Wallet className="w-5 h-5 text-slate-950 font-bold" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-slate-100">
                      CARTEIRA MT5 & TELEMETRIA FINANCEIRA (XM)
                    </h2>
                    <span className="px-2 py-0.5 rounded bg-emerald-950/70 text-emerald-400 border border-emerald-500/40 text-[10px] font-bold flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      {isConnected ? 'MT5 CONECTADO (XM)' : 'SISTEMA ONLINE (SUPABASE)'}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-sans">
                    Saldo, patrimônio líquido e posições reais sincronizadas em tempo real via Supabase.
                  </p>
                </div>
              </div>

              <button
                onClick={handleClose}
                className="p-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-400 hover:text-slate-200 transition cursor-pointer"
                title="Fechar Modal"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Top 6 Metrics Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 my-3.5">
              {/* Saldo */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                  <span>SALDO (BALANCE)</span>
                  <Wallet className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-slate-100">
                  ${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

              {/* Equity */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                  <span>PATRIMÔNIO (EQUITY)</span>
                  <Zap className="w-3.5 h-3.5 text-yellow-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-slate-100 flex items-center gap-1">
                  ${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  {floatingPnl !== 0 && (
                    <span className={`text-[10px] ${floatingPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {floatingPnl >= 0 ? `+$${floatingPnl.toFixed(1)}` : `-$${Math.abs(floatingPnl).toFixed(1)}`}
                    </span>
                  )}
                </div>
              </div>

              {/* Margem Livre */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                  <span>MARGEM LIVRE</span>
                  <DollarSign className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-cyan-300">
                  ${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

              {/* Ganhos TP */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-emerald-500/30">
                <div className="flex items-center justify-between text-[10px] text-emerald-400 mb-1">
                  <span>GANHOS NO TP</span>
                  <Target className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-emerald-400">
                  +${totalTpGain.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="text-[9px] text-emerald-400/80 mt-0.5">
                  {winCount} operações lucrativas
                </div>
              </div>

              {/* Perdas SL */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-rose-500/30">
                <div className="flex items-center justify-between text-[10px] text-rose-400 mb-1">
                  <span>PERDAS NO SL</span>
                  <Shield className="w-3.5 h-3.5 text-rose-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-rose-400">
                  -${Math.abs(totalSlLoss).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="text-[9px] text-rose-400/80 mt-0.5">
                  {lossCount} operações no stop
                </div>
              </div>

              {/* Win Rate & PF */}
              <div className="p-3 rounded-xl bg-slate-900/80 border border-cyan-500/30">
                <div className="flex items-center justify-between text-[10px] text-cyan-400 mb-1">
                  <span>WIN RATE & PF</span>
                  <Activity className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div className="text-sm sm:text-base font-bold text-cyan-300">
                  {winRate}%
                </div>
                <div className="text-[9px] text-slate-400 mt-0.5">
                  PF: <b className="text-slate-200">{profitFactor}</b>
                </div>
              </div>
            </div>

            {/* Filter & Tab Switcher */}
            <div className="flex flex-wrap items-center justify-between gap-3 pb-2.5 mb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActiveTab('OPEN')}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition cursor-pointer flex items-center gap-1.5 ${
                    activeTab === 'OPEN'
                      ? 'bg-cyan-500 text-slate-950 shadow-[0_0_12px_#00f0ff]'
                      : 'bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Activity className="w-3.5 h-3.5" />
                  <span>Posições Abertas ({openTrades.length})</span>
                </button>

                <button
                  onClick={() => setActiveTab('CLOSED')}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition cursor-pointer flex items-center gap-1.5 ${
                    activeTab === 'CLOSED'
                      ? 'bg-cyan-500 text-slate-950 shadow-[0_0_12px_#00f0ff]'
                      : 'bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Clock className="w-3.5 h-3.5" />
                  <span>Histórico de Ordens Fechadas ({closedTrades.length})</span>
                </button>
              </div>

              <div className="flex items-center gap-2">
                <Filter className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-[10px] text-slate-400">Ativo:</span>
                <select
                  value={symbolFilter}
                  onChange={(e) => setSymbolFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-200 cursor-pointer focus:outline-none focus:border-cyan-500"
                >
                  <option value="ALL">Todos os Ativos</option>
                  <option value="BTCUSD">BTCUSD</option>
                  <option value="ETHUSD">ETHUSD</option>
                  <option value="SOLUSD">SOLUSD</option>
                  <option value="XAUUSD">XAUUSD</option>
                </select>
              </div>
            </div>

            {/* Operations Table */}
            <div className="flex-1 overflow-y-auto pr-1">
              {displayedTrades.length === 0 ? (
                <div className="py-12 px-4 rounded-2xl bg-slate-900/40 border border-slate-800/80 text-center flex flex-col items-center justify-center gap-2.5">
                  <div className="w-10 h-10 rounded-full bg-slate-800/80 flex items-center justify-center text-slate-400">
                    {activeTab === 'OPEN' ? <Activity className="w-5 h-5" /> : <Clock className="w-5 h-5" />}
                  </div>
                  <span className="text-xs text-slate-300 font-bold">
                    {activeTab === 'OPEN'
                      ? 'Nenhuma posição aberta no momento no MT5 (XM).'
                      : 'Nenhuma ordem fechada encontrada com os filtros selecionados.'}
                  </span>
                  <p className="text-[11px] text-slate-500 max-w-md">
                    {activeTab === 'OPEN'
                      ? 'Os 5 operadores quantitativos estão monitorando o mercado. Quando um sinal técnico for confirmado, a ordem aparecerá aqui automaticamente.'
                      : 'O histórico exibirá todas as ordens finalizadas pelo Take Profit ou Stop Loss.'}
                  </p>
                  {activeTab === 'OPEN' && closedTrades.length > 0 && (
                    <button
                      onClick={() => setActiveTab('CLOSED')}
                      className="mt-1 px-3 py-1 rounded-lg bg-cyan-950 border border-cyan-500/40 text-cyan-300 text-xs font-bold hover:bg-cyan-900 transition"
                    >
                      Ver Histórico Fechado ({closedTrades.length} ordens)
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {displayedTrades.map((trade) => {
                    const isBuy = trade.order_type === 'BUY';
                    const pnl = Number(trade.profit_usd) || 0;
                    const { progress, current, expectedTpGain, expectedSlLoss } = calculateProgress(trade);
                    const isClosed = String(trade.status || '').trim().toUpperCase() === 'CLOSED';
                    const exitReason = trade.exit_reason || (pnl >= 0 ? 'TP_HIT' : 'SL_HIT');
                    const entryPrice = Number(trade.entry_price) || 0;
                    const slPrice = Number(trade.sl) || 0;
                    const tpPrice = Number(trade.tp) || 0;

                    return (
                      <div
                        key={trade.ticket_mt5}
                        className="p-3 rounded-2xl bg-slate-900/60 border border-slate-800/80 hover:border-cyan-500/40 transition flex flex-col md:flex-row md:items-center justify-between gap-3"
                      >
                        {/* 1. Ticket & Agente */}
                        <div className="min-w-[140px]">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-bold text-slate-200">
                              #{trade.ticket_mt5}
                            </span>
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 border border-slate-700">
                              {trade.agent_id}
                            </span>
                            {trade.execution_account === 'DEMO' ? (
                              <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-500/25 text-amber-300 border border-amber-500/50 font-bold flex items-center gap-0.5" title="Ordem executada na conta Demo (Laboratório de Quarentena)">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                                DEMO
                              </span>
                            ) : (
                              <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold flex items-center gap-0.5" title="Ordem executada na conta Real">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                REAL
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-400 block mt-0.5">
                            {trade.opened_at ? new Date(trade.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'} • {trade.dry_run ? 'Simulado' : (trade.execution_account === 'DEMO' ? 'Demo Lab' : 'Live XM')}
                          </span>
                        </div>

                        {/* 2. Ativo & Lado */}
                        <div className="min-w-[110px]">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-bold text-cyan-300">
                              {trade.symbol}
                            </span>
                            <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold flex items-center gap-0.5 ${
                              isBuy ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/40' : 'bg-rose-950 text-rose-400 border border-rose-500/40'
                            }`}>
                              {isBuy ? <ArrowUpRight className="w-2.5 h-2.5" /> : <ArrowDownRight className="w-2.5 h-2.5" />}
                              {trade.order_type}
                            </span>
                          </div>
                          <span className="text-[10px] text-slate-400 block mt-0.5">
                            Lote: <b className="text-slate-200">{trade.volume}</b>
                          </span>
                        </div>

                        {/* 3. Preço Entrada vs. Atual */}
                        <div className="min-w-[130px]">
                          <div className="text-[10px] text-slate-400">
                            Entrada: <span className="text-slate-200 font-bold">${entryPrice.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5">
                            {isClosed ? 'Fechado:' : 'Atual:'}{' '}
                            <span className={`font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              ${Number(current).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                        </div>

                        {/* 4. BARRA DE PROGRESSO VISUAL (SL <---> TP) */}
                        <div className="flex-1 max-w-sm px-2">
                          <div className="flex items-center justify-between text-[9px] mb-1">
                            {/* SL side */}
                            <span className="text-rose-400 font-bold flex items-center gap-0.5">
                              SL: {slPrice > 0 ? `$${slPrice.toLocaleString()}` : 'N/A'}{' '}
                              {expectedSlLoss > 0 && <span className="text-rose-500/80 font-normal">(-${expectedSlLoss.toFixed(0)})</span>}
                            </span>
                            {/* TP side */}
                            <span className="text-emerald-400 font-bold flex items-center gap-0.5">
                              TP: {tpPrice > 0 ? `$${tpPrice.toLocaleString()}` : 'N/A'}{' '}
                              {expectedTpGain > 0 && <span className="text-emerald-500/80 font-normal">(+${expectedTpGain.toFixed(0)})</span>}
                            </span>
                          </div>

                          {/* Progress track */}
                          <div className="relative w-full h-2.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                            <div
                              className="h-full bg-gradient-to-r from-rose-500 via-yellow-400 to-emerald-400 transition-all duration-300"
                              style={{ width: `${progress}%` }}
                            />
                          </div>

                          <div className="flex justify-between items-center text-[8px] text-slate-500 mt-0.5">
                            <span>0% (Stop)</span>
                            <span className="text-slate-400 font-bold">
                              {isClosed ? (exitReason === 'TP_HIT' || pnl >= 0 ? 'Alvo TP Atingido' : 'Stop Loss Executado') : `Posição: ${progress}%`}
                            </span>
                            <span>100% (Alvo)</span>
                          </div>
                        </div>

                        {/* 5. Status / Resultado */}
                        <div className="min-w-[130px] text-right">
                          {isClosed ? (
                            exitReason === 'TP_HIT' || pnl >= 0 ? (
                              <div className="inline-flex flex-col items-end">
                                <span className="px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-500 text-emerald-300 text-[10px] font-bold flex items-center gap-1 shadow-sm">
                                  🟢 TAKE PROFIT
                                </span>
                                <span className="text-xs font-bold text-emerald-400 mt-0.5">
                                  +${pnl.toFixed(2)}
                                </span>
                              </div>
                            ) : (
                              <div className="inline-flex flex-col items-end">
                                <span className="px-2 py-0.5 rounded bg-rose-950/80 border border-rose-500 text-rose-300 text-[10px] font-bold flex items-center gap-1 shadow-sm">
                                  🔴 STOP LOSS
                                </span>
                                <span className="text-xs font-bold text-rose-400 mt-0.5">
                                  -${Math.abs(pnl).toFixed(2)}
                                </span>
                              </div>
                            )
                          ) : (
                            <div className="inline-flex flex-col items-end">
                              <span className="px-2 py-0.5 rounded bg-amber-950/60 border border-amber-500/40 text-amber-300 text-[10px] font-bold flex items-center gap-1 animate-pulse">
                                ⚡ EM ANDAMENTO
                              </span>
                              <span className={`text-xs font-bold mt-0.5 ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default MT5AccountPanel;
