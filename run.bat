@echo off
REM SunFest pipeline — regenerate events.json from the festival schedule,
REM build index.html + calendar.ics, then publish to GitHub Pages.
cd /d "%~dp0"
python build_events.py || goto :error
python pipeline.py --push || goto :error
echo.
echo Done. Live: https://mim21.github.io/sunfest/
goto :eof
:error
echo.
echo Pipeline failed.
exit /b 1
