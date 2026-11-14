@echo off
REM Feed de orderflow BTCUSDT (Binance) + modo sombra. Nao envia ordens. Aberto pelo start_engine.bat.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
:loop
echo [%date% %time%] Iniciando ORDERFLOW...
"%PY%" run_orderflow_feed.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] ORDERFLOW encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
