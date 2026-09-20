@echo off
chcp 65001 >nul

echo 停止调度器...
taskkill /fi "windowtitle eq QuantScheduler*" /f >nul 2>&1
echo 停止前端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5273.*LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)
echo 停止后端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)

timeout /t 1 /nobreak >nul

echo.
netstat -ano | findstr ":5273.*LISTENING :8000.*LISTENING" >nul
if %errorlevel%==0 (
    echo ✅ 全部已停
) else (
    echo ⚠️  仍有端口占用，请手动检查：
    netstat -ano | findstr ":5273 :8000"
)
echo.
pause
