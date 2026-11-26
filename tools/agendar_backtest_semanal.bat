@echo off
REM Cria (ou atualiza) a tarefa "QuantOffice\BacktestSemanal": todo sabado as 10:00, como o usuario logado.
REM Roda so com o usuario logado (o Autologon da VPS garante): precisa do MT5 aberto e do login do Claude Code.
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
schtasks /Create /TN "QuantOffice\BacktestSemanal" /TR "\"%ROOT%\run_backtest_semanal.bat\"" /SC WEEKLY /D SAT /ST 10:00 /RL HIGHEST /F
if errorlevel 1 (
  echo Falhou. Rode este arquivo como Administrador.
  exit /b 1
)
schtasks /Query /TN "QuantOffice\BacktestSemanal" /FO LIST | findstr /i "Nome TaskName Proxima Next Status"
echo.
echo Para testar agora:  schtasks /Run /TN "QuantOffice\BacktestSemanal"
echo Para remover:       schtasks /Delete /TN "QuantOffice\BacktestSemanal" /F
