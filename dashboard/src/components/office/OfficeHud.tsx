'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, ChevronDown, Radio, ShieldAlert, Trophy, Wallet, X } from 'lucide-react';
import { AgentStatus, MarketContext, MT5AccountStatus, Trade } from '@/types';
import { CloseEvent, Competition } from '@/hooks/useOffice';
import { GROUP_STYLE, ZONES, fmtUsd, groupOf, shortName } from './layout';

interface HudProps {
  agents: AgentStatus[];
  trades: Trade[];
  account: MT5AccountStatus | null;
  competition: Competition | null;
  auditor: MarketContext | null;
  events: CloseEvent[];
  recentCloses: Trade[];
  connected: boolean;
  selected: AgentStatus | null;
  onSelect: (a: AgentStatus | null) => void;
}

const pnlClass = (v: number) => (v > 0 ? 'text-emerald-300' : v < 0 ? 'text-rose-300' : 'text-slate-400');
const zoneColor = (sector: number) => ZONES.find((z) => z.sector === Number(sector))?.color || '#94a3b8';
const card = 'rounded-2xl bg-slate-950/75 backdrop-blur-xl ring-1 ring-white/10 shadow-[0_20px_60px_rgba(0,0,0,0.45)]';

function daysLeft(fim?: string | null) {
  if (!fim) return null;
  const ms = new Date(fim.replace(' ', 'T') + 'Z').getTime() - Date.now();
  return ms > 0 ? Math.ceil(ms / 86400000) : 0;
}


type FoldKey = 'feed' | 'auditor' | 'placar';
const FOLD_KEY = 'quant-office:paineis-recolhidos';

/** Painéis recolhidos/expandidos, lembrados no navegador (falha silenciosa sem localStorage). */
function useFold(): [Record<FoldKey, boolean>, (k: FoldKey) => void] {
  const [fold, setFold] = useState<Record<FoldKey, boolean>>({ feed: false, auditor: false, placar: false });
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(FOLD_KEY);
      if (raw) setFold((f) => ({ ...f, ...JSON.parse(raw) }));
    } catch {
      /* sem armazenamento: segue expandido */
    }
  }, []);
  const toggle = useCallback((k: FoldKey) => {
    setFold((f) => {
      const next = { ...f, [k]: !f[k] };
      try {
        window.localStorage.setItem(FOLD_KEY, JSON.stringify(next));
      } catch {
        /* ignora */
      }
      return next;
    });
  }, []);
  return [fold, toggle];
}

function Chevron({ open }: { open: boolean }) {
  return <ChevronDown size={15} className={`shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />;
}

export function OfficeHud({ agents, trades, account, competition, auditor, events, recentCloses, connected, selected, onSelect }: HudProps) {
  const byId = useMemo(() => Object.fromEntries(agents.map((a) => [a.agent_id, a])), [agents]);
  const g = competition?.total_por_grupo;
  const left = daysLeft(competition?.fim_utc);
  const toast = events[0] && Date.now() - events[0].at < 6000 ? events[0] : null;
  const auditText = auditor?.key_driver || '';
  const status = /CRÍTICO/i.test(auditText) ? 'CRÍTICO' : /ATENÇÃO/i.test(auditText) ? 'ATENÇÃO' : auditText ? 'OK' : '—';
  const statusCls = status === 'CRÍTICO' ? 'bg-rose-500/20 text-rose-300 ring-rose-400/40' : status === 'ATENÇÃO'
    ? 'bg-amber-500/20 text-amber-200 ring-amber-400/40' : 'bg-emerald-500/20 text-emerald-200 ring-emerald-400/40';
  const liveIds = new Set(events.filter((e) => Date.now() - e.at < 60000).map((e) => e.id));
  const [fold, toggle] = useFold();

  return (
    <div className="pointer-events-none absolute inset-0 z-30 font-sans text-slate-100">
      {/* barra superior */}
      <header className={`pointer-events-auto absolute left-4 right-4 top-4 flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 ${card}`}>
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-sky-400 to-violet-500 grid place-items-center font-black text-slate-950">Q</div>
          <div>
            <div className="text-[15px] font-bold leading-tight">Quant Office</div>
            <div className="text-[11px] text-slate-400 leading-tight">mesa de operações · conta demo</div>
          </div>
        </div>
        <span className={`flex items-center gap-1.5 text-[11px] ${connected ? 'text-emerald-300' : 'text-amber-300'}`}>
          <Radio size={13} className={connected ? 'animate-pulse' : ''} /> {connected ? 'ao vivo' : 'reconectando'}
        </span>
        <div className="flex items-center gap-5 text-[12px]">
          <Wallet size={15} className="text-slate-400" />
          <span>Saldo <b className="font-mono text-[14px]">${(account?.balance ?? 0).toFixed(2)}</b></span>
          <span>Equity <b className="font-mono text-[14px]">${(account?.equity ?? 0).toFixed(2)}</b></span>
          <span>Flutuante <b className={`font-mono text-[14px] ${pnlClass(account?.floating_pnl ?? 0)}`}>{fmtUsd(account?.floating_pnl)}</b></span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[12px]">
          <Trophy size={15} className="text-amber-300" />
          <span className="text-slate-400">Antigos</span>
          <b className={`font-mono text-[15px] ${pnlClass(g?.antigo ?? 0)}`}>{fmtUsd(g?.antigo)}</b>
          <span className="text-slate-500">×</span>
          <b className={`font-mono text-[15px] ${pnlClass(g?.novo ?? 0)}`}>{fmtUsd(g?.novo)}</b>
          <span className="text-slate-400">Novos</span>
          {left !== null && <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-slate-300 ring-1 ring-white/10">{left} dia(s) restantes</span>}
        </div>
      </header>

      {/* aviso de posição fechada */}
      {toast && (
        <div key={toast.id + toast.at} className="absolute left-1/2 top-24 -translate-x-1/2 animate-[toast_6s_ease-out_forwards]">
          <div className={`flex items-center gap-3 rounded-2xl px-5 py-3 ring-1 backdrop-blur-xl shadow-2xl ${toast.profit >= 0 ? 'bg-emerald-950/85 ring-emerald-400/60' : 'bg-rose-950/85 ring-rose-400/60'}`}>
            <Activity size={18} className={toast.profit >= 0 ? 'text-emerald-300' : 'text-rose-300'} />
            <span className="text-[13px] text-slate-200">{shortName(toast.agentId)} fechou {toast.side} {toast.symbol}</span>
            <span className={`font-mono text-[18px] font-black ${pnlClass(toast.profit)}`}>{fmtUsd(toast.profit)}</span>
          </div>
        </div>
      )}

      {/* placar */}
      <aside className={`pointer-events-auto absolute right-4 top-24 w-[330px] flex flex-col ${card} ${fold.placar ? '' : 'bottom-4'}`}>
        <button onClick={() => toggle('placar')} className="flex items-center justify-between gap-2 px-4 pt-3 pb-2 text-left" title={fold.placar ? 'Expandir' : 'Recolher'}>
          <span className="text-[12px] font-bold tracking-widest text-slate-300">PLACAR DA COMPETIÇÃO</span>
          <span className="ml-auto text-[10px] text-slate-500">{competition?.inicio_utc?.slice(5, 10).split('-').reverse().join('/')} → {competition?.fim_utc ? new Date(new Date(competition.fim_utc.replace(' ', 'T') + 'Z').getTime() - 1).toISOString().slice(5, 10).split('-').reverse().join('/') : '…'}</span>
          <Chevron open={!fold.placar} />
        </button>
        <div className={`flex-1 overflow-y-auto px-2 pb-2 [scrollbar-width:thin] ${fold.placar ? 'hidden' : ''}`}>
          {(competition?.placar || []).map((r, i) => {
            const a = byId[r.agente];
            return (
              <button
                key={r.agente}
                onClick={() => a && onSelect(a)}
                className={`w-full flex items-center gap-2 rounded-xl px-2 py-1.5 text-left transition hover:bg-white/5 ${selected?.agent_id === r.agente ? 'bg-white/10' : ''}`}
              >
                <span className="w-6 text-right font-mono text-[11px] text-slate-500">{i + 1}</span>
                <span className="h-2 w-2 rounded-full" style={{ background: a ? zoneColor(a.sector) : '#475569' }} />
                <span className="flex-1 truncate text-[12px]">{shortName(r.agente)}</span>
                <span className="text-[10px] text-slate-500">{r.trades}t</span>
                <span className={`w-[68px] text-right font-mono text-[12px] font-bold ${pnlClass(r.pnl)}`}>{fmtUsd(r.pnl)}</span>
              </button>
            );
          })}
        </div>
      </aside>

      {/* feed de fechamentos */}
      <section className={`pointer-events-auto absolute left-4 bottom-4 w-[360px] max-h-[34vh] flex flex-col ${card}`}>
        <button onClick={() => toggle('feed')} className="flex items-center gap-2 px-4 pt-3 pb-2 text-left" title={fold.feed ? 'Expandir' : 'Recolher'}>
          <span className="text-[12px] font-bold tracking-widest text-slate-300">POSIÇÕES FECHADAS</span>
          {fold.feed && recentCloses[0] && (
            <span className={`text-[11px] font-mono ${pnlClass(Number(recentCloses[0].profit_usd))}`}>
              últ. {shortName(recentCloses[0].agent_id)} {fmtUsd(Number(recentCloses[0].profit_usd))}
            </span>
          )}
          <Chevron open={!fold.feed} />
        </button>
        <div className={`overflow-y-auto px-2 pb-2 [scrollbar-width:thin] ${fold.feed ? 'hidden' : ''}`}>
          {recentCloses.length === 0 && <div className="px-2 py-3 text-[12px] text-slate-500">Nenhum fechamento ainda.</div>}
          {recentCloses.map((t) => (
            <div key={t.ticket_mt5} className={`flex items-center gap-2 rounded-xl px-2 py-1.5 ${liveIds.has(String(t.ticket_mt5)) ? 'bg-white/10 ring-1 ring-white/20' : ''}`}>
              <span className="w-[86px] font-mono text-[10px] text-slate-500">{(t.closed_at || '').slice(5, 16).replace('T', ' ')}</span>
              <span className="flex-1 truncate text-[12px]">{shortName(t.agent_id)}</span>
              <span className="text-[10px] text-slate-500">{t.order_type} {t.symbol}</span>
              <span className={`w-[64px] text-right font-mono text-[12px] font-bold ${pnlClass(Number(t.profit_usd))}`}>{fmtUsd(Number(t.profit_usd))}</span>
            </div>
          ))}
        </div>
      </section>

      {/* auditor */}
      <section className={`pointer-events-auto absolute left-[390px] bottom-4 w-[min(520px,calc(100vw-760px))] max-h-[34vh] flex flex-col ${card}`}>
        <button onClick={() => toggle('auditor')} className="flex items-center gap-2 px-4 pt-3 pb-2 text-left" title={fold.auditor ? 'Expandir' : 'Recolher'}>
          <ShieldAlert size={14} className="text-slate-400" />
          <span className="text-[12px] font-bold tracking-widest text-slate-300">AUDITOR</span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${statusCls}`}>{status}</span>
          <span className="ml-auto text-[10px] text-slate-500">{auditor?.created_at ? new Date(auditor.created_at).toLocaleString('pt-BR') : ''}</span>
          <Chevron open={!fold.auditor} />
        </button>
        <div className={`overflow-y-auto whitespace-pre-line px-4 pb-3 text-[12px] leading-relaxed text-slate-300 [scrollbar-width:thin] ${fold.auditor ? 'hidden' : ''}`}>
          {auditText || 'A próxima auditoria aparece aqui (a cada 4 horas).'}
        </div>
      </section>

      {/* ficha do agente */}
      {selected && <AgentDrawer agent={selected} trades={trades} competition={competition} placarFolded={fold.placar} onClose={() => onSelect(null)} />}
    </div>
  );
}

function AgentDrawer({ agent, trades, competition, placarFolded, onClose }: { agent: AgentStatus; trades: Trade[]; competition: Competition | null; placarFolded: boolean; onClose: () => void }) {
  const group = groupOf(agent.agent_id);
  const style = GROUP_STYLE[group];
  const row = competition?.placar.find((r) => r.agente === agent.agent_id);
  const rank = (competition?.placar.findIndex((r) => r.agente === agent.agent_id) ?? -1) + 1;
  const mine = trades.filter((t) => t.agent_id === agent.agent_id)
    .sort((a, b) => new Date(b.closed_at || b.opened_at).getTime() - new Date(a.closed_at || a.opened_at).getTime());
  const open = mine.find((t) => String(t.status) === 'OPEN');
  const closed = mine.filter((t) => String(t.status) === 'CLOSED');
  const total = closed.reduce((s, t) => s + (Number(t.profit_usd) || 0), 0);
  const wins = closed.filter((t) => Number(t.profit_usd) > 0).length;
  return (
    <aside className={`pointer-events-auto absolute z-10 w-[360px] overflow-y-auto p-4 ${card} ${placarFolded ? 'right-4 top-[9.5rem] max-h-[calc(100vh-11rem)]' : 'right-[350px] top-24 max-h-[calc(100vh-8rem)]'}`}>
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-xl grid place-items-center font-black text-slate-950" style={{ background: zoneColor(agent.sector) }}>#{rank || '–'}</div>
        <div className="flex-1">
          <div className="text-[15px] font-bold">{shortName(agent.agent_id)}</div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ${style.badge}`}>{style.label}</span>
            <span className="text-[11px] text-slate-400">{agent.agent_id}</span>
          </div>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-white/10"><X size={16} /></button>
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-slate-300">{agent.strategy_style}</p>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        {[
          ['Competição', fmtUsd(row?.pnl), pnlClass(row?.pnl ?? 0)],
          ['Acumulado', fmtUsd(total), pnlClass(total)],
          ['Acerto', closed.length ? `${Math.round((wins / closed.length) * 100)}%` : '–', 'text-slate-200'],
          ['Trades', String(closed.length), 'text-slate-200'],
          ['PF comp.', row?.profit_factor == null ? '–' : row.profit_factor === 'inf' ? '∞' : Number(row.profit_factor).toFixed(2), 'text-slate-200'],
          ['Perdas seg.', String(agent.consecutive_losses ?? 0), 'text-slate-200'],
        ].map(([k, v, c]) => (
          <div key={k} className="rounded-xl bg-white/5 px-2 py-2 ring-1 ring-white/5">
            <div className="text-[10px] text-slate-500">{k}</div>
            <div className={`font-mono text-[14px] font-bold ${c}`}>{v}</div>
          </div>
        ))}
      </div>
      {open && (
        <div className="mt-3 rounded-xl bg-white/5 p-3 ring-1 ring-white/10 text-[12px]">
          <div className="text-slate-400 text-[10px] mb-1">POSIÇÃO ABERTA</div>
          <div className="flex justify-between"><span>{open.order_type} {open.volume} {open.symbol} @ {Number(open.entry_price).toFixed(2)}</span>
            <b className={`font-mono ${pnlClass(Number(open.profit_usd))}`}>{fmtUsd(Number(open.profit_usd))}</b></div>
          <div className="text-slate-500 text-[11px] mt-1">SL {open.sl || '–'} · TP {open.tp || '–'}</div>
        </div>
      )}
      <div className="mt-3 text-[10px] text-slate-500">ÚLTIMOS TRADES</div>
      <div className="mt-1 space-y-1">
        {closed.slice(0, 10).map((t) => (
          <div key={t.ticket_mt5} className="flex items-center gap-2 text-[12px]">
            <span className="w-[86px] font-mono text-[10px] text-slate-500">{(t.closed_at || '').slice(5, 16).replace('T', ' ')}</span>
            <span className="flex-1 text-slate-300">{t.order_type} {t.exit_reason}</span>
            <span className={`font-mono font-bold ${pnlClass(Number(t.profit_usd))}`}>{fmtUsd(Number(t.profit_usd))}</span>
          </div>
        ))}
        {closed.length === 0 && <div className="text-[12px] text-slate-500">Ainda sem trades fechados.</div>}
      </div>
    </aside>
  );
}
