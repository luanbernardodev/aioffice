@echo off
REM Auditor MT5 somente leitura. Agendado pelo Agendador de Tarefas (ver README).
REM Segredos via variaveis de ambiente: ANTHROPIC_API_KEY, TG_TOKEN, TG_CHAT_ID.
cd /d "%~dp0"
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m agents.auditor_mt5 %*
