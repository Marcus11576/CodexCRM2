@echo off
setlocal

echo ===========================================
echo Antigravity CRM HTTPS Tunnel (localtunnel)
echo ===========================================
echo.
echo Keep this window open while testing on mobile.
echo It will print an https:// URL you can open on your phone.
echo.

npx --yes localtunnel --port 8009

endlocal
