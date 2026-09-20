@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
set "ROOT=%cd%"

echo === 启动量化全套（Windows 版） ===
echo 项目根: %ROOT%
echo.

:: ---- 读 token ----
set "TOKEN="
for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%\quant-system\.env") do (
    if /i "%%a"=="XUANGUTONG_IVANKA_TOKEN" set "TOKEN=%%b"
)
if "%TOKEN%"=="" (
    echo ❌ quant-system\.env 缺 XUANGUTONG_IVANKA_TOKEN
    pause
    exit /b 1
)

:: ---- 1. 后端（:8000）----
netstat -ano | findstr ":8000.*LISTENING" >nul
if %errorlevel%==0 (
    echo ⏭ 后端已在运行（:8000）
) else (
    echo 🚀 启动后端 :8000
    if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
    set "QUANT_ADVICE_DIR=%ROOT%\quant-system\data\advice"
    set "QUANT_WEB_DIST=%ROOT%\quant-web\dist"
    cd /d "%ROOT%\quant-web\backend"
    start "QuantBackend" /min cmd /c "python main.py > %ROOT%\logs\backend.log 2>&1"
    cd /d "%ROOT%"
)

:: ---- 2. 前端（:5273，仅当用 dev 模式时启动；同源部署可不启动）----
set "START_FRONTEND=1"
if exist "%ROOT%\quant-web\dist\index.html" (
    echo ℹ️  检测到 dist\，如使用同源模式（http://localhost:8000）可跳过前端
    set "START_FRONTEND=1"
)

netstat -ano | findstr ":5273.*LISTENING" >nul
if %errorlevel%==0 (
    echo ⏭ 前端已在运行（:5273）
) else (
    if "%START_FRONTEND%"=="1" (
        echo 🚀 启动前端 :5273
        cd /d "%ROOT%\quant-web"
        start "QuantFrontend" /min cmd /c "npm run dev -- --host 0.0.0.0 --port 5273 > %ROOT%\logs\frontend.log 2>&1"
        cd /d "%ROOT%"
    )
)

:: ---- 3. 调度器 ----
tasklist /fi "imagename eq python.exe" /v | findstr "quant_system.scheduler" >nul
if %errorlevel%==0 (
    echo ⏭ 调度器已在运行
) else (
    if not exist "%ROOT%\quant-system\.venv\Scripts\python.exe" (
        echo ❌ 调度器未安装：%ROOT%\quant-system\.venv\Scripts\python.exe 不存在
        echo    请先在 quant-system\ 目录下运行：python -m venv .venv && .venv\Scripts\pip install -e ".[eltdx,dev]"
        pause
        exit /b 1
    )
    echo 🚀 启动调度器
    cd /d "%ROOT%\quant-system"
    start "QuantScheduler" /min cmd /c ".venv\Scripts\python.exe -m quant_system.scheduler > %ROOT%\logs\scheduler.log 2>&1"
    cd /d "%ROOT%"
)

timeout /t 3 /nobreak >nul

echo.
echo ✅ 启动完成
echo    前端（dev） http://localhost:5273
echo    后端同源   http://localhost:8000
echo    健康检查   http://localhost:8000/health
echo    今日建议   http://localhost:8000/api/advice
echo    日志目录   %ROOT%\logs\
echo.
echo 💡 停止服务请双击 stop-all.cmd
echo.
pause
