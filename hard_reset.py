"""Hard Reset para Go-Live:
1. Zera a tabela trades_history
2. Reseta a conta mt5_account_status para $200.00 (id = 1)
3. Reseta todos os agentes de agents_status para IDLE (fora de quarentena, 0 perdas, peso 1.0x)
"""
import sys
import logging
from datetime import datetime, timezone
from core.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hard_reset")

def execute_hard_reset():
    db = DatabaseManager()
    if not db.client:
        log.error("Erro: Cliente Supabase não está conectado.")
        sys.exit(1)

    log.info("Iniciando Hard Reset de Produção (Go-Live)...")
    now_utc = datetime.now(timezone.utc).isoformat()

    # 1. Apagar todo o histórico de operações (trades_history)
    log.info("1. Limpando tabela 'trades_history'...")
    while True:
        rows = db.client.table("trades_history").select("ticket_mt5").limit(100).execute().data or []
        if not rows:
            break
        tickets = [r["ticket_mt5"] for r in rows]
        db.client.table("trades_history").delete().in_("ticket_mt5", tickets).execute()
        log.info("Lote de %d trades apagado.", len(tickets))
    log.info("Histórico de trades zerado com sucesso.")

    # 2. Resetar o painel da conta MT5 para $200.00
    log.info("2. Resetando 'mt5_account_status' para Banca Inicial de US$ 200.00...")
    account_payload = {
        "balance": 200.00,
        "equity": 200.00,
        "floating_pnl": 0.00,
        "free_margin": 200.00,
        "margin_level": 0.00,
        "total_tp_gain": 0.00,
        "total_sl_loss": 0.00,
        "win_count": 0,
        "loss_count": 0,
        "is_connected": True,
        "updated_at": now_utc,
    }
    db.client.table("mt5_account_status").update(account_payload).eq("id", 1).execute()
    log.info("Conta MT5 atualizada: Saldo $200.00 | Equity $200.00 | Margem Livre $200.00")

    # 3. Curar todos os agentes (Tirar da quarentena, zerar perdas e sentar nas mesas)
    log.info("3. Restaurando 'agents_status' para estado de fábrica (IDLE)...")
    agent_payload = {
        "current_state": "IDLE",
        "consecutive_losses": 0,
        "quarantine_until": None,
        "allocation_weight": 1.0,
        "last_thought": "No posto operacional... Pronto para a sessão de Go-Live.",
        "updated_at": now_utc,
    }
    agents = db.client.table("agents_status").select("agent_id").execute().data or []
    for a in agents:
        db.client.table("agents_status").update(agent_payload).eq("agent_id", a["agent_id"]).execute()
    log.info("Todos os %d agentes restaurados para IDLE.", len(agents))

    # 4. Verificação de Integridade
    log.info("--- VERIFICAÇÃO DE INTEGRIDADE PÓS-RESET ---")
    final_trades = db.client.table("trades_history").select("ticket_mt5").execute().data or []
    final_acc = db.client.table("mt5_account_status").select("*").eq("id", 1).execute().data or []
    final_agents = db.client.table("agents_status").select("agent_id, current_state, consecutive_losses, allocation_weight").execute().data or []

    print(f"\n[OK] 1. Trades em trades_history: {len(final_trades)}")
    if final_acc:
        acc = final_acc[0]
        print(f"[OK] 2. MT5 Account: Saldo=${acc.get('balance')} | Equity=${acc.get('equity')} | Margem Livre=${acc.get('free_margin')} | TP=${acc.get('total_tp_gain')} | SL=${acc.get('total_sl_loss')} | Wins={acc.get('win_count')} | Losses={acc.get('loss_count')}")
    print(f"[OK] 3. Total de Agentes em IDLE: {len([a for a in final_agents if a.get('current_state') == 'IDLE'])}/{len(final_agents)}")
    for a in final_agents:
        print(f"     • {a['agent_id']}: State={a['current_state']} | Losses={a['consecutive_losses']} | Weight={a['allocation_weight']}x")

if __name__ == "__main__":
    execute_hard_reset()
