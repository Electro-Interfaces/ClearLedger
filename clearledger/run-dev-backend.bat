@echo off
REM Dev-backend ClearLedger/TradeLedger с авто-рестартом.
REM Запускается Планировщиком задач Windows (ClearLedgerDevBackend) и переживает
REM закрытие любых терминалов/сессий агента. Останов: schtasks /end /tn ClearLedgerDevBackend
cd /d D:\Users\magsp\ELSYPLUS\Ledger\app\clearledger\server
:loop
py -3.13 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "%TEMP%\clearledger-dev-backend.log" 2>&1
echo [%date% %time%] backend exited, restart in 3s >> "%TEMP%\clearledger-dev-backend.log"
timeout /t 3 /nobreak >nul
goto loop
