@echo off
REM Backtest semanal: atualiza dados, revalida agentes ligados, roda a grade e manda relatorio no Telegram.
REM SO RELATA: nao altera nenhum agente. Agendado por tools\agendar_backtest_semanal.bat (sabado 10:00).
REM Prioridade BAIXA: os agentes ao vivo no MT5 tem preferencia de CPU.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
start "BACKTEST SEMANAL" /BELOWNORMAL /WAIT "%PY%" -m backtest.semanal.run %*
