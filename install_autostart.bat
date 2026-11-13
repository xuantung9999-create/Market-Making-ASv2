@echo off
rem Start run_24x7.bat automatically when Windows logs in (after power cuts, updates, restarts).
rem Run once. To undo: delete "MarketMaker24x7.bat" from the Startup folder (Win+R, shell:startup).
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
(
  echo @echo off
  echo cd /d "%~dp0"
  echo start "Market maker 24x7" /min cmd /c run_24x7.bat
) > "%STARTUP%\MarketMaker24x7.bat"
echo Installed: run_24x7.bat now starts when you log in to Windows.
pause
