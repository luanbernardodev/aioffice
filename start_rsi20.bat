@echo off
REM Agente RSI20 (BTCUSD, magic 20261112) com auto-restart. Aberto automaticamente pelo start_engine.bat.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
:loop
echo [%date% %time%] Iniciando RSI20...
"%PY%" run_capitulation.py --section rsi20
if %errorlevel%==3 exit /b 0
echo [%date% %time%] RSI20 encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
