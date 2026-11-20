@echo off
REM Sincronizacao MT5 -> Supabase do painel (somente leitura no MT5). Aberto pelo start_engine.bat.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
:loop
echo [%date% %time%] Iniciando SYNC...
"%PY%" run_supabase_sync.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] SYNC encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
