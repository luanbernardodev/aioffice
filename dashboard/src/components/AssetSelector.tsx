'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { Check, Coins, Zap, Shield, Flame, Activity } from 'lucide-react';

interface AssetConfig {
  symbol: string;
  label: string;
  fullName: string;
  category: 'CRYPTO' | 'COMMODITY';
  activeColor: string;
  glowColor: string;
  badgeBg: string;
}

const SUPPORTED_ASSETS: AssetConfig[] = [
  {
    symbol: 'BTCUSD',
    label: 'BTC',
    fullName: 'Bitcoin',
    category: 'CRYPTO',
    activeColor: 'text-amber-400 border-amber-500/60 bg-amber-950/40',
    glowColor: 'shadow-[0_0_12px_rgba(245,158,11,0.35)]',
    badgeBg: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  },
  {
    symbol: 'ETHUSD',
    label: 'ETH',
    fullName: 'Ethereum',
    category: 'CRYPTO',
    activeColor: 'text-cyan-400 border-cyan-500/60 bg-cyan-950/40',
    glowColor: 'shadow-[0_0_12px_rgba(6,182,212,0.35)]',
    badgeBg: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
  },
  {
    symbol: 'SOLUSD',
    label: 'SOL',
    fullName: 'Solana',
    category: 'CRYPTO',
    activeColor: 'text-fuchsia-400 border-fuchsia-500/60 bg-fuchsia-950/40',
    glowColor: 'shadow-[0_0_12px_rgba(217,70,239,0.35)]',
    badgeBg: 'bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40',
  },
  {
    symbol: 'XAUUSD',
    label: 'XAUUSD',
    fullName: 'Gold (Ouro)',
    category: 'COMMODITY',
    activeColor: 'text-yellow-300 border-yellow-500/60 bg-yellow-950/40',
    glowColor: 'shadow-[0_0_12px_rgba(234,179,8,0.35)]',
    badgeBg: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  },
];

const DEFAULT_ASSETS = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'XAUUSD'];

interface AssetSelectorProps {
  className?: string;
  onAssetsChange?: (assets: string[]) => void;
}

export const AssetSelector: React.FC<AssetSelectorProps> = ({
  className = '',
  onAssetsChange,
}) => {
  const [activeAssets, setActiveAssets] = useState<string[]>(DEFAULT_ASSETS);
  const [updatingSymbol, setUpdatingSymbol] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);

  // 1. Carrega active_assets do Supabase (system_config id=1)
  const fetchActiveAssets = useCallback(async () => {
    try {
      const { data, error } = await supabase
        .from('system_config')
        .select('active_assets')
        .eq('id', 1)
        .limit(1);

      if (!error && data && data.length > 0) {
        const assets = data[0].active_assets;
        if (Array.isArray(assets) && assets.length > 0) {
          setActiveAssets(assets);
          if (onAssetsChange) onAssetsChange(assets);
        }
      }
    } catch (err) {
      console.error('Erro ao ler active_assets do system_config:', err);
    }
  }, [onAssetsChange]);

  // 2. Realtime listener para mudanças no system_config
  useEffect(() => {
    fetchActiveAssets();

    const channel = supabase
      .channel('system_config_asset_selector_realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'system_config' },
        (payload) => {
          if (payload.new) {
            const cfg = payload.new as any;
            if (cfg.active_assets && Array.isArray(cfg.active_assets)) {
              setActiveAssets(cfg.active_assets);
              if (onAssetsChange) onAssetsChange(cfg.active_assets);
            }
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchActiveAssets, onAssetsChange]);

  // 3. Toggle de Ativo com persistência instantânea no Supabase
  const handleToggleAsset = async (symbol: string) => {
    const isCurrentlyActive = activeAssets.includes(symbol);
    
    // Regra de segurança: impede desligar todos os ativos simultaneamente
    if (isCurrentlyActive && activeAssets.length === 1) {
      alert('Pelo menos um ativo deve permanecer ativo no Sentinela.');
      return;
    }

    const nextAssets = isCurrentlyActive
      ? activeAssets.filter((s) => s !== symbol)
      : [...activeAssets, symbol];

    // Atualização otimista imediata
    setActiveAssets(nextAssets);
    setUpdatingSymbol(symbol);
    setIsSyncing(true);

    try {
      const { error } = await supabase
        .from('system_config')
        .update({
          active_assets: nextAssets,
          updated_at: new Date().toISOString(),
        })
        .eq('id', 1);

      if (error) {
        console.error('Erro ao salvar active_assets no Supabase:', error);
        // Rollback em caso de erro
        setActiveAssets(activeAssets);
      } else {
        if (onAssetsChange) onAssetsChange(nextAssets);
      }
    } catch (err) {
      console.error('Falha de rede ao atualizar active_assets:', err);
      setActiveAssets(activeAssets);
    } finally {
      setUpdatingSymbol(null);
      setIsSyncing(false);
    }
  };

  const activeCount = activeAssets.length;

  return (
    <div
      className={`flex items-center gap-2 font-mono text-xs select-none flex-wrap justify-center ${
        className || 'bg-slate-950/85 backdrop-blur-md border border-slate-800/80 rounded-full px-3 py-1.5 shadow-xl'
      }`}
      title="Painel de Controlo de Ativos (Filtragem Dinâmica do Sentinela)"
    >
      {/* Título de Seção & Badge de Status */}
      <div className="flex items-center gap-1.5 text-slate-300 pr-1 border-r border-slate-800/80">
        <Activity className={`w-3.5 h-3.5 ${isSyncing ? 'text-amber-400 animate-spin' : 'text-cyan-400'}`} />
        <span className="font-bold tracking-wider text-[11px] text-slate-200 uppercase hidden sm:inline">
          Ativos:
        </span>
        <span className="px-1.5 py-0.2 rounded-md bg-cyan-950/70 text-cyan-300 border border-cyan-500/40 text-[10px] font-bold">
          {activeCount}/{SUPPORTED_ASSETS.length}
        </span>
      </div>

      {/* 4 Botões de Toggle (Interruptores) Elegantes */}
      <div className="flex items-center gap-1.5 flex-wrap justify-center">
        {SUPPORTED_ASSETS.map((asset) => {
          const isActive = activeAssets.includes(asset.symbol);
          const isPending = updatingSymbol === asset.symbol;

          return (
            <button
              key={asset.symbol}
              type="button"
              onClick={() => handleToggleAsset(asset.symbol)}
              disabled={isPending}
              className={`group relative flex items-center gap-2 px-2.5 py-1 rounded-full border text-xs font-bold transition-all duration-300 cursor-pointer ${
                isActive
                  ? `${asset.activeColor} ${asset.glowColor}`
                  : 'bg-slate-900/60 border-slate-800 text-slate-500 hover:border-slate-700 hover:text-slate-400'
              }`}
              title={`${asset.fullName} (${asset.symbol}): ${isActive ? 'ATIVADO no Sentinela (Clique para pausar)' : 'PAUSADO (Clique para ativar)'}`}
            >
              {/* Asset Badge / Icon */}
              <div className="flex items-center gap-1">
                <span className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${
                  isActive
                    ? 'bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse'
                    : 'bg-slate-600'
                }`} />
                <span className="tracking-wide text-[11px] font-black">
                  {asset.label}
                </span>
              </div>

              {/* Elegant Micro Switch Knob */}
              <div
                className={`w-7 h-3.5 flex items-center rounded-full p-0.5 transition-colors duration-300 ${
                  isActive ? 'bg-slate-800/90' : 'bg-slate-950/80 border border-slate-800'
                }`}
              >
                <div
                  className={`bg-white w-2.5 h-2.5 rounded-full shadow-md transform transition-transform duration-300 flex items-center justify-center ${
                    isActive
                      ? 'translate-x-3.5 bg-gradient-to-r from-emerald-400 to-cyan-400 shadow-[0_0_6px_#00f0ff]'
                      : 'translate-x-0 bg-slate-500'
                  }`}
                >
                  {isActive && <Check className="w-2 h-2 text-slate-950 stroke-[3]" />}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
