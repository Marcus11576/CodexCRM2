@echo off
setlocal

set "CF_EXE=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "CF_OUT=%TEMP%\cloudflared-8009.out.log"
set "CF_ERR=%TEMP%\cloudflared-8009.err.log"
set "CF_PID=%TEMP%\cloudflared-8009.pid"

if not exist "%CF_EXE%" (
  echo cloudflared executable not found at "%CF_EXE%"
  exit /b 1
)

if exist "%CF_OUT%" del /q "%CF_OUT%"
if exist "%CF_ERR%" del /q "%CF_ERR%"

for /f "tokens=2 delims=," %%A in ('tasklist /FI "IMAGENAME eq cloudflared.exe" /FO CSV /NH') do (
  taskkill /PID %%~A /F >nul 2>&1
)

start "" /B "%CF_EXE%" tunnel --url http://localhost:8009 1>"%CF_OUT%" 2>"%CF_ERR%"

timeout /t 2 /nobreak >nul
for /f "tokens=2 delims=," %%A in ('tasklist /FI "IMAGENAME eq cloudflared.exe" /FO CSV /NH') do (
  echo %%~A>"%CF_PID%"
  goto :done
)

:done
endlocal
exit /b 0
