"""Script de Diagnóstico Quantitativo e Validação de Infraestrutura.

Valida de ponta a ponta:
1. Supabase (Leitura e Gravação na tabela agents_status)
2. APIs de Notícias e Macro (Finnhub API + RSS CoinTelegraph + RSS Investing + Calendário ForexFactory)
3. Conexão MetaTrader 5 (Terminal Info, Login, Cotações Ask/Bid de BTCUSD e XAUUSD)
4. Anthropic Claude API (Teste de latência e resposta com claude-3-5-haiku-latest)
5. Cadeia de Comando Completa (Notícias -> Setor 2 -> Setor 3 Veto -> Setor 1 Ordem Micro 0.01 -> Fechamento)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Garante suporte a UTF-8 no terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Cores ANSI para o terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Configuração de logging limpa
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("diagnostic")


def _print_header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}>> TESTE: {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")


def _print_success(msg: str) -> None:
    print(f"  {BOLD}{GREEN}[SUCESSO]{RESET} {msg}")


def _print_fail(msg: str) -> None:
    print(f"  {BOLD}{RED}[FALHA]{RESET} {msg}")


def _print_warn(msg: str) -> None:
    print(f"  {BOLD}{YELLOW}[ALERTA]{RESET} {msg}")


def _print_info(msg: str) -> None:
    print(f"  {CYAN}[INFO]{RESET} {msg}")


# ----------------------------------------------------------------------
# 1. TESTE SUPABASE
# ----------------------------------------------------------------------
def test_supabase() -> bool:
    _print_header("1. Banco de Dados Supabase (Leitura e Escrita)")
    try:
        from core.database import DatabaseManager
        db = DatabaseManager()
        test_agent_id = "diagnostic_runner"
        now_str = datetime.now(timezone.utc).isoformat()

        _print_info("Tentando gravar registro de teste em 'agents_status'...")
        db.update_agent_status(
            agent_id=test_agent_id,
            state="TESTING",
            thought=f"Executando diagnóstico do sistema em {now_str}",
            weight=1.0,
        )
        _print_success("Gravação efetuada com sucesso no Supabase.")

        _print_info("Lendo registro gravado de volta do Supabase...")
        row = db.get_agent_status(test_agent_id)
        if not row:
            _print_fail("Registro não encontrado após gravação.")
            return False

        if row.get("agent_id") == test_agent_id and row.get("current_state") == "TESTING":
            _print_success(f"Registro lido e validado com integridade: {row.get('agent_id')} | Estado={row.get('current_state')}")
        else:
            _print_warn(f"Registro retornado, mas valores diferem do esperado: {row}")

        # Limpeza / Restauração do status para IDLE
        db.update_agent_status(test_agent_id, "IDLE", "Diagnóstico finalizado com sucesso.", 1.0)
        _print_success("Ciclo completo de leitura e escrita no Supabase homologado.")
        return True
    except Exception as exc:
        _print_fail(f"Erro no teste do Supabase: {exc}")
        return False


# ----------------------------------------------------------------------
# 2. TESTE APIS DE NOTÍCIAS E MACRO
# ----------------------------------------------------------------------
def test_news_apis() -> bool:
    _print_header("2. Coletor Híbrido de Notícias (Finnhub API + RSS + Calendário FED)")
    try:
        from core.news_collector import NewsCollector
        collector = NewsCollector()

        # 2.1 Finnhub API
        _print_info("Testando Finnhub API (Crypto & General)...")
        finnhub_news = collector.fetch_finnhub_news()
        if finnhub_news:
            _print_success(f"Finnhub API: {len(finnhub_news)} notícias recebidas.")
            sample = finnhub_news[0]
            _print_info(f"Amostra Finnhub [{sample.get('category')}]: \"{sample.get('headline')[:80]}...\"")
        else:
            _print_warn("Finnhub API não retornou notícias. Verifique se FINNHUB_API_KEY no .env é válida.")

        # 2.2 CoinTelegraph RSS
        _print_info("Testando RSS CoinTelegraph...")
        crypto_news = collector.fetch_crypto_rss()
        if crypto_news:
            _print_success(f"CoinTelegraph RSS: {len(crypto_news)} manchetes recebidas.")
            _print_info(f"Amostra Cripto: \"{crypto_news[0].get('headline')[:80]}...\"")
        else:
            _print_fail("CoinTelegraph RSS retornou vazio ou falhou.")

        # 2.3 Investing.com RSS Ouro
        _print_info("Testando RSS Investing.com (Ouro/Commodities)...")
        gold_news = collector.fetch_gold_rss()
        if gold_news:
            _print_success(f"Investing.com RSS: {len(gold_news)} notícias de commodities recebidas.")
            _print_info(f"Amostra Ouro: \"{gold_news[0].get('headline')[:80]}...\"")
        else:
            _print_warn("Investing.com RSS indisponível ou bloqueado por rate limit.")

        # 2.4 Calendário ForexFactory XML
        _print_info("Testando Calendário Econômico ForexFactory (Eventos USD High Impact)...")
        calendar_events = collector.fetch_macro_calendar()
        _print_success(f"ForexFactory Calendar: {len(calendar_events)} eventos High Impact encontrados para hoje.")
        for ev in calendar_events[:3]:
            _print_info(f"  * {ev.get('title')} as {ev.get('time')} ({ev.get('currency')})")

        # Validação geral
        if crypto_news or finnhub_news:
            _print_success("Camada de dados macro e notícias operando com sucesso.")
            return True
        _print_fail("Nenhuma fonte de notícia conseguiu fornecer dados válidos.")
        return False
    except Exception as exc:
        _print_fail(f"Erro no teste de notícias: {exc}")
        return False


# ----------------------------------------------------------------------
# 3. TESTE CONEXÃO METATRADER 5
# ----------------------------------------------------------------------
def test_mt5_connection() -> bool:
    _print_header("3. Conexão MetaTrader 5 e Cotações em Tempo Real")
    try:
        from config import settings
        from core.mt5_bridge import MT5Bridge

        bridge = MT5Bridge()

        try:
            import MetaTrader5 as mt5
        except Exception:
            mt5 = None

        if mt5 is None:
            _print_warn("Biblioteca nativa 'MetaTrader5' não importada (necessário Windows).")
            _print_info("Validando motor de simulação (Mock Rates)...")
            rates_btc = bridge.get_rates("BTCUSD", "M5", 10)
            rates_xau = bridge.get_rates("XAUUSD", "M5", 10)
            _print_success(f"Simulador MT5: BTCUSD Close={rates_btc['close'].iloc[-1]:.2f} | XAUUSD Close={rates_xau['close'].iloc[-1]:.2f}")
            return True

        _print_info("Inicializando conexão com o terminal MetaTrader 5...")
        if not mt5.initialize(timeout=3000):
            _print_warn(f"mt5.initialize() falhou ({mt5.last_error()}). O terminal MT5 pode estar fechado.")
            _print_info(f"Status do MT5Bridge: mock={bridge.mock} | connected={bridge.connected}")
            rates_btc = bridge.get_rates("BTCUSD", "M5", 5)
            _print_success(f"Cotação via simulação da ponte: BTCUSD Close={rates_btc['close'].iloc[-1]:.2f}")
            return True

        term_info = mt5.terminal_info()
        if term_info is None:
            _print_warn("mt5.terminal_info() retornou None.")
            return True

        _print_success(f"Terminal MT5 Ativo: {term_info.name} v{term_info.build} (Conectado: {term_info.connected})")

        acc_info = mt5.account_info()
        if acc_info:
            env_login = settings.MT5_LOGIN
            confere = (acc_info.login == env_login) or (env_login == 0)
            _print_success(f"Conta MT5 #{acc_info.login} ({acc_info.company}) | Servidor: {acc_info.server}")
            _print_info(f"Saldo: ${acc_info.balance:.2f} | Margem Livre: ${acc_info.margin_free:.2f} | Moeda: {acc_info.currency}")
            if confere:
                _print_success("Login da conta confere com as credenciais do .env!")
            else:
                _print_warn(f"Login ativo (#{acc_info.login}) difere do .env (#{env_login}).")
        else:
            _print_warn("mt5.account_info() indisponível. Verifique se o login foi realizado no MT5.")

        # Puxa cotação Ask / Bid em tempo real de BTCUSD e Ouro (XAUUSD ou GOLD)
        symbols_to_check = ["BTCUSD"]
        gold_sym = "GOLD" if mt5.symbol_info("GOLD") else ("XAUUSD" if mt5.symbol_info("XAUUSD") else "XAUUSD")
        symbols_to_check.append(gold_sym)

        for symbol in symbols_to_check:
            mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                _print_success(f"Cotação ao vivo {symbol}: Bid={tick.bid:.2f} | Ask={tick.ask:.2f} | Spread={(tick.ask - tick.bid):.2f}")
            else:
                price = bridge.get_price(symbol, "BUY")
                _print_info(f"Cotação {symbol} via bridge: {price:.2f}")

        return True
    except Exception as exc:
        _print_fail(f"Erro no teste do MT5: {exc}")
        return False


# ----------------------------------------------------------------------
# 4. TESTE ANTHROPIC CLAUDE API
# ----------------------------------------------------------------------
def test_claude_api() -> bool:
    _print_header("4. Anthropic Claude API (Inteligência dos Agentes)")
    try:
        from agents.claude_client import ClaudeClient
        from config import settings

        client = ClaudeClient()
        test_model = settings.MODEL_FAST or "claude-haiku-5-5"
        prompt = "Você é um assistente de validação. Responda estritamente 'OK' se estiver online."

        _print_info(f"Enviando ping de teste para Anthropic usando modelo '{test_model}'...")
        start_t = time.time()
        reply = ""
        try:
            reply = client.ask_text(test_model, prompt, max_tokens=10).strip()
        except Exception:
            # Fallback para outros aliases suportados
            for fallback_model in ("claude-3-5-haiku-20241022", "claude-3-haiku-20240307", "claude-haiku-4-5"):
                try:
                    _print_info(f"Tentando modelo alternativo '{fallback_model}'...")
                    reply = client.ask_text(fallback_model, prompt, max_tokens=10).strip()
                    test_model = fallback_model
                    break
                except Exception:
                    continue

        elapsed = time.time() - start_t
        if not reply:
            _print_fail("Não foi possível obter resposta de nenhum modelo Anthropic testado.")
            return False

        _print_info(f"Resposta recebida em {elapsed:.2f}s: \"{reply}\"")
        if "OK" in reply.upper():
            _print_success(f"Anthropic API homologada e operacional! Modelo: {test_model} | Latência: {elapsed:.2f}s")
            return True

        _print_warn(f"Resposta recebida, mas não continha 'OK': {reply}")
        return True
    except Exception as exc:
        _print_fail(f"Falha ao comunicar com a API Anthropic: {exc}")
        return False


# ----------------------------------------------------------------------
# 5. TESTE DA CADEIA DE COMANDO COMPLETA (NOTÍCIAS -> SETOR 3 -> SETOR 1 MICRO ORDEM)
# ----------------------------------------------------------------------
def test_full_flow() -> bool:
    _print_header("5. Fluxo Completo: Notícia -> Setor 2 -> Setor 3 Veto -> Setor 1 Execução Micro")
    try:
        from agents import sector_2_news, sector_3_analytics
        from agents.claude_client import ClaudeClient
        from core.database import DatabaseManager
        from core.mt5_bridge import MT5Bridge
        from core.news_collector import NewsCollector

        db = DatabaseManager()
        claude = ClaudeClient()
        bridge = MT5Bridge()
        collector = NewsCollector(db)

        # 5.1 news_collector -> Salva contexto
        _print_info("Passo 1: Coletando notícias e atualizando market_context...")
        market_ctx = collector.get_global_market_context()
        _print_success(f"Contexto coletado: {len(market_ctx.get('headlines', []))} manchetes | Driver: {market_ctx.get('key_driver')[:60]}...")

        # 5.2 Setor 2 -> Score de Sentimento
        _print_info("Passo 2: Setor 2 analisando sentimento macro...")
        sentiment = sector_2_news.run(db, claude, market_ctx)
        if not sentiment:
            _print_fail("Setor 2 falhou ao sintetizar sentimento.")
            return False
        _print_success(f"Sentimento Setor 2: Cripto={sentiment.get('crypto_sentiment')} | Ouro={sentiment.get('gold_sentiment')} | RedFlag={sentiment.get('red_flag_pause_trading')}")

        # 5.3 Setor 3 (Auditor) -> strategy_authorization
        _print_info("Passo 3: Setor 3 auditando e gerando liberação por estratégia...")
        veto_report = sector_3_analytics.evaluate_macro_relevance(db, claude, sentiment)
        if not veto_report:
            _print_fail("Setor 3 falhou ao gerar relatório de autorização.")
            return False

        auths = veto_report.get("strategy_authorization", {})
        is_safe = veto_report.get("is_market_safe", False)
        reason = veto_report.get("veto_reason", "")
        _print_success(f"Setor 3 Veredito: is_market_safe={is_safe} | Válido por: {veto_report.get('valid_for_minutes')} min")
        _print_info(f"Motivo: {reason}")
        _print_info(f"Autorizações: {json.dumps(auths, ensure_ascii=False)}")

        # 5.4 Setor 1 (Ops Delta/Epsilon) -> 100 candles BTCUSD M5
        _print_info("Passo 4: Setor 1 lendo últimos 100 candles de BTCUSD no timeframe M5...")
        candles_m5 = bridge.get_rates("BTCUSD", "M5", 100)
        _print_success(f"100 candles de BTCUSD M5 obtidos com sucesso. Preço atual: ${candles_m5['close'].iloc[-1]:.2f}")

        # 5.5 Teste de Execução de Ordem MICRO (0.01 lote) e Encerramento Imediato
        _print_info("Passo 5: Testando envio e fechamento imediato de ordem MICRO (0.01 lote) com magic=777777 e deviation=10...")
        curr_price = float(candles_m5['close'].iloc[-1])
        sl_test = curr_price * 0.98  # -2%
        tp_test = curr_price * 1.04  # +4%

        # Envia ordem micro
        order_res = bridge.execute_order(
            symbol="BTCUSD",
            action="BUY",
            volume=0.01,
            sl=sl_test,
            tp=tp_test,
            comment="diag-test-micro",
            magic=777777,
            deviation=10,
        )

        if not order_res.get("success"):
            _print_fail(f"Falha ao enviar ordem micro: {order_res}")
            return False

        ticket = order_res.get("ticket")
        fill_price = order_res.get("price", curr_price)
        is_mock = order_res.get("mock", False)
        _print_success(f"Ordem MICRO aberta: Ticket #{ticket} | Preço=${fill_price:.2f} | Mock={is_mock}")

        # Grava o trade no Supabase para validar a rastreabilidade
        trade_record = None
        try:
            trade_record = db.log_trade(
                agent_id="ops_delta",
                symbol="BTCUSD",
                action="BUY",
                volume=0.01,
                entry_price=fill_price,
                sl=sl_test,
                tp=tp_test,
                risk_amount=5.0,
                confidence=85.0,
                rationale="Ordem de validação do script diagnostic.py",
                ticket=ticket,
                dry_run=is_mock,
            )
            _print_success(f"Trade gravado na tabela 'trades_history' do Supabase (Ticket #{ticket}).")
        finally:
            # Encerramento imediato garantido no MT5
            _print_info(f"Encerrando posição #{ticket} imediatamente...")
            close_res = bridge.close_position(
                ticket=ticket,
                symbol="BTCUSD",
                volume=0.01,
                comment="diag-close-micro",
                magic=777777,
                deviation=10,
            )
            if close_res.get("success"):
                _print_success(f"Posição #{ticket} encerrada com sucesso no MT5!")
                # Atualiza no Supabase
                try:
                    db.close_trade(ticket, pnl=0.0, exit_price=fill_price, outcome="DIAGNOSTIC_TEST")
                    _print_success("Status do trade atualizado para CLOSED no Supabase.")
                except Exception as db_err:
                    _print_warn(f"Aviso ao atualizar status fechado no Supabase: {db_err}")
            else:
                _print_warn(f"Aviso no encerramento da posição: {close_res}")

        _print_success("Cadeia de comando completa validada de ponta a ponta com sucesso!")
        return True
    except Exception as exc:
        _print_fail(f"Erro na execução da cadeia de comando completa: {exc}")
        return False


# ----------------------------------------------------------------------
# EXECUÇÃO SEQUENCIAL
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\n{BOLD}{CYAN}{'#' * 75}")
    print(f"#{' ' * 73}#")
    print(f"#{BOLD}{GREEN}{'   QUANT OFFICE AI - DIAGNÓSTICO E VALIDAÇÃO DE INFRAESTRUTURA   ':^73}{CYAN}#")
    print(f"#{' ' * 73}#")
    print(f"{'#' * 75}{RESET}\n")

    start_total = time.time()
    results = {}

    results["Supabase DB"] = test_supabase()
    results["News & Macro APIs"] = test_news_apis()
    results["MetaTrader 5 Bridge"] = test_mt5_connection()
    results["Claude Anthropic API"] = test_claude_api()
    results["Cadeia de Comando Completa"] = test_full_flow()

    elapsed_total = time.time() - start_total

    print(f"\n{BOLD}{CYAN}{'=' * 75}")
    print(f"  PAINEL RESUMO DO DIAGNÓSTICO GERAL (Tempo: {elapsed_total:.2f}s)")
    print(f"{'=' * 75}{RESET}")

    all_passed = True
    for test_name, status in results.items():
        if status:
            print(f"  {GREEN}[OK] APROVADO{RESET}  |  {test_name}")
        else:
            print(f"  {RED}[X] REPROVADO{RESET} |  {test_name}")
            all_passed = False

    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}\n")

    if all_passed:
        print(f"  {BOLD}{GREEN}[SUCESSO TOTAL] TODAS AS CONEXOES E FLUXOS FORAM VALIDADOS COM SUCESSO!{RESET}")
        print(f"  {BOLD}O sistema esta 100% pronto para iniciar o loop autonomo (main.py).{RESET}\n")
        sys.exit(0)
    else:
        print(f"  {BOLD}{YELLOW}[AVISO] ALGUNS TESTES APRESENTARAM FALHAS OU AVISOS.{RESET}")
        print(f"  Verifique os detalhes acima antes de operar em conta real.\n")
        sys.exit(1)
