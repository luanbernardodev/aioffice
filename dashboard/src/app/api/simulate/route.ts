import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl =
  process.env.SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL ||
  '';

const supabaseKey =
  process.env.SUPABASE_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_KEY ||
  process.env.SUPABASE_SERVICE_ROLE_KEY ||
  '';

const supabaseAdmin = createClient(
  supabaseUrl || 'https://placeholder.supabase.co',
  supabaseKey || 'placeholder-key'
);

export async function POST(req: Request) {
  try {
    const { action } = await req.json();
    const now = new Date().toISOString();

    if (action === 'ORDER_ALPHA') {
      // 1. Ops Alpha to EXECUTING
      await supabaseAdmin.from('agents_status').update({
        current_state: 'EXECUTING',
        last_thought: '🚀 Rompimento confirmado no BTCUSD! Enviando ordem BUY 0.15 lote...',
        updated_at: now,
      }).eq('agent_id', 'ops_alpha');

      // 2. Insert new trade in trades_history
      const ticket = Math.floor(Math.random() * 900000000000000) + 100000000000000;
      const profit = Math.round((Math.random() * 350 - 50) * 100) / 100;
      await supabaseAdmin.from('trades_history').insert({
        ticket_mt5: ticket,
        agent_id: 'ops_alpha',
        symbol: 'BTCUSD',
        order_type: 'BUY',
        volume: 0.15,
        entry_price: 68450.0,
        sl: 67800.0,
        tp: 69800.0,
        status: 'CLOSED',
        profit_usd: profit,
        technical_rationale: 'Rompimento de canal de alta no M15 com volume 2.4x da média.',
        risk_amount: 100.0,
        confidence: 85.0,
        dry_run: true,
        opened_at: new Date(Date.now() - 3600000).toISOString(),
        closed_at: now,
      });

      // Reset to IDLE after 6 seconds in background
      setTimeout(async () => {
        try {
          await supabaseAdmin.from('agents_status').update({
            current_state: 'IDLE',
            last_thought: 'Ordem executada com sucesso. Monitorando trailing stop.',
            updated_at: new Date().toISOString(),
          }).eq('agent_id', 'ops_alpha');
        } catch {
          // ignore
        }
      }, 6000);

      return NextResponse.json({ success: true, message: 'Ordem Alpha disparada com sucesso!' });
    }

    if (action === 'EMERGENCY_MEETING') {
      // Send ALL 10 agents to IN_MEETING (both canonical and legacy aliases)
      const updates = [
        { id: 'ops_alpha', thought: 'Convocado para o Boardroom: Apresentando métricas de tendência.' },
        { id: 'ops_delta', thought: 'Convocado para o Boardroom: Relatando confluências de SMC Scalper.' },
        { id: 'ops_beta', thought: 'Reunião de emergência: Revisando filtros de reversão e drawdown.' },
        { id: 'ops_epsilon', thought: 'Convocado para o Boardroom: Dados de microestrutura VWAP M5.' },
        { id: 'ops_gamma', thought: 'Mesa redonda convocada: Protegendo posições abertas.' },
        { id: 'news_macro', thought: 'Briefing urgente do Conselho: Geopolítica e taxas de juros.' },
        { id: 'news_desk', thought: 'Briefing urgente do Conselho: Geopolítica e taxas de juros.' },
        { id: 'auditor_quant', thought: 'Cruzando matrizes de correlação, VAR e estresse do fundo.' },
        { id: 'analytics', thought: 'Cruzando matrizes de correlação, VAR e estresse do fundo.' },
        { id: 'rnd_engineer', thought: 'Apresentando calibração bayesiana dos algoritmos.' },
        { id: 'rnd', thought: 'Apresentando calibração bayesiana dos algoritmos.' },
        { id: 'cro_manager', thought: 'Convocando conselho executivo para avaliar risco macro e exposição.' },
        { id: 'manager', thought: 'Convocando conselho executivo para avaliar risco macro e exposição.' },
        { id: 'boardroom_chair', thought: 'Presidindo comitê extraordinário de deliberação quantitativa.' },
        { id: 'boardroom', thought: 'Presidindo comitê extraordinário de deliberação quantitativa.' },
      ];

      for (const item of updates) {
        await supabaseAdmin.from('agents_status').update({
          current_state: 'IN_MEETING',
          last_thought: item.thought,
          updated_at: now,
        }).eq('agent_id', item.id);
      }

      return NextResponse.json({ success: true, message: 'Todos os 10 agentes convocados para o Conselho de Crise!' });
    }

    if (action === 'QUARANTINE_BETA') {
      await supabaseAdmin.from('agents_status').update({
        current_state: 'QUARANTINED',
        last_thought: 'Alocação zerada pelo CRO. Em revisão estatística de drawdown.',
        allocation_weight: 0.0,
        updated_at: now,
      }).eq('agent_id', 'ops_beta');

      await supabaseAdmin.from('agents_status').update({
        last_thought: 'Suspensão de Ops Beta mantida. Risco sob controle estrito.',
        updated_at: now,
      }).eq('agent_id', 'cro_manager');
      await supabaseAdmin.from('agents_status').update({
        last_thought: 'Suspensão de Ops Beta mantida. Risco sob controle estrito.',
        updated_at: now,
      }).eq('agent_id', 'manager');

      return NextResponse.json({ success: true, message: 'Agente Beta colocado em Quarentena.' });
    }

    if (action === 'MARKET_ANALYSIS') {
      const ops = ['ops_alpha', 'ops_delta', 'ops_beta', 'ops_epsilon', 'ops_gamma'];
      for (const op of ops) {
        await supabaseAdmin.from('agents_status').update({
          current_state: 'ANALYZING',
          last_thought: 'Varrendo livro de ofertas e confluências técnicas M15...',
          updated_at: now,
        }).eq('agent_id', op);
      }
      return NextResponse.json({ success: true, message: 'Agentes operacionais em modo ANALYZING.' });
    }

    if (action === 'RESET_IDLE') {
      const allAgents = [
        { id: 'ops_alpha', thought: 'Na bancada. Trend pullback ativo.', weight: 1.5 },
        { id: 'ops_delta', thought: 'No posto operacional: SMC Scalper M1 varrendo liquidez.', weight: 1.0 },
        { id: 'ops_beta', thought: 'Calibrando gatilhos de reversão no RSI.', weight: 1.0 },
        { id: 'ops_epsilon', thought: 'No posto operacional: VWAP Scalper M5 monitorando bandas.', weight: 1.0 },
        { id: 'ops_gamma', thought: 'Vigilante para rompimentos em XAUUSD e BTC.', weight: 1.5 },
        { id: 'news_macro', thought: 'Monitorando feeds da Reuters, Bloomberg e On-Chain.', weight: 1.0 },
        { id: 'news_desk', thought: 'Monitorando feeds da Reuters, Bloomberg e On-Chain.', weight: 1.0 },
        { id: 'auditor_quant', thought: 'Matrizes de correlação e VAR atualizadas.', weight: 1.0 },
        { id: 'analytics', thought: 'Matrizes de correlação e VAR atualizadas.', weight: 1.0 },
        { id: 'rnd_engineer', thought: 'Testando otimização bayesiana de stops.', weight: 1.0 },
        { id: 'rnd', thought: 'Testando otimização bayesiana de stops.', weight: 1.0 },
        { id: 'cro_manager', thought: 'Diretoria de Risco: Exposição global balanceada.', weight: 1.0 },
        { id: 'manager', thought: 'Diretoria de Risco: Exposição global balanceada.', weight: 1.0 },
        { id: 'boardroom_chair', thought: 'Conselho Consultivo: Monitorando governança e teto de risco.', weight: 1.0 },
        { id: 'boardroom', thought: 'Conselho Consultivo: Monitorando governança e teto de risco.', weight: 1.0 },
      ];

      for (const a of allAgents) {
        await supabaseAdmin.from('agents_status').update({
          current_state: 'IDLE',
          last_thought: a.thought,
          allocation_weight: a.weight,
          updated_at: now,
        }).eq('agent_id', a.id);
      }

      return NextResponse.json({ success: true, message: 'Todos os 10 agentes retornaram aos seus postos em IDLE.' });
    }

    if (action === 'TOGGLE_RED_FLAG') {
      // Read latest
      const { data: latest } = await supabaseAdmin
        .from('market_context')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(1)
        .single();

      const newFlag = latest ? !latest.red_flag_pause_trading : true;
      const cryptoVal = newFlag ? -8 : 6;
      const goldVal = newFlag ? 9 : 2;
      const driver = newFlag
        ? 'ALERTA GLOBAL: Tensões geopolíticas elevadas e liquidação maciça em derivativos. Circuit breaker ativado!'
        : 'Fluxo institucional recorde em ETFs e estabilidade nas taxas de juros globais impulsionam apetite a risco.';

      await supabaseAdmin.from('market_context').insert({
        crypto_sentiment: cryptoVal,
        gold_sentiment: goldVal,
        red_flag_pause_trading: newFlag,
        key_driver: driver,
        created_at: now,
      });

      return NextResponse.json({
        success: true,
        message: `Status do mercado alterado: ${newFlag ? 'RED FLAG ATIVADO' : 'MERCADO NORMAL'}`,
      });
    }

    return NextResponse.json({ error: 'Ação não reconhecida' }, { status: 400 });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
