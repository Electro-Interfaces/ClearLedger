@echo off
REM Dev-frontend (Vite) ClearLedger/TradeLedger с авто-рестартом.
REM Запускается Планировщиком задач Windows (ClearLedgerDevFrontend) и переживает
REM закрытие любых терминалов/сессий агента. Останов: schtasks /end /tn ClearLedgerDevFrontend
cd /d D:\Users\magsp\ELSYPLUS\Ledger\app\clearledger
:loop
call npm.cmd run dev >> "%TEMP%\clearledger-dev-frontend.log" 2>&1
echo [%date% %time%] frontend exited, restart in 3s >> "%TEMP%\clearledger-dev-frontend.log"
timeout /t 3 /nobreak >nul
goto loop
