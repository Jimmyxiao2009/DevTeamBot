@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [程序组bot] 启动自检...
".venv\Scripts\python.exe" scripts\check_env.py
if errorlevel 1 (
    echo.
    echo 自检未通过，请按上面提示处理后重试。暂停 30 秒后自动关闭...
    timeout /t 30 >nul
    exit /b 1
)

echo.
echo [程序组bot] 启动中（Ctrl+C 停止）...
".venv\Scripts\python.exe" bot.py
pause
