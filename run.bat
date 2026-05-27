@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: ── Python check ─────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: ── Virtual env ──────────────────────────────────────────────
if not exist ".venv\" (
    echo 首次运行，正在创建虚拟环境...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

:: ── Dependencies ─────────────────────────────────────────────
pip install -r requirements.txt -q --disable-pip-version-check

:: ── .env check ───────────────────────────────────────────────
if not exist ".env" (
    echo.
    echo 警告: 未找到 .env 文件，请复制 .env.example 并填写 API Key
    echo.
)

:: ── Menu ─────────────────────────────────────────────────────
echo.
echo ============================================
echo      Scope 3 Transport Calculator
echo ============================================
echo   Cat 6 — 商务出行
echo     1. 推断出行路线  (gen_routes^)
echo     2. 填充距离      (fill_amap^)
echo.
echo   Cat 4 — 上游运输
echo     3. 卡车运输距离  (distance_searcher^)
echo.
echo   Cat 4/9 — 海运
echo     4. 海运距离 — 离线图  (sea_dijkstra^)
echo     5. 海运距离 — PUB 151 (pub151^)
echo.
echo     0. 退出
echo ============================================
echo.
set /p choice=请选择 (0-5):

if "%choice%"=="1" goto opt1
if "%choice%"=="2" goto opt2
if "%choice%"=="3" goto opt3
if "%choice%"=="4" goto opt4
if "%choice%"=="5" goto opt5
if "%choice%"=="0" goto quit
echo 无效选择，请输入 0-5
pause
exit /b 1

:opt1
set /p excel=Excel 路径 [默认: 出发地目的地路线统计报告.xlsx]:
if "%excel%"=="" set excel=出发地目的地路线统计报告.xlsx
python cat6-business-travel\gen_routes.py --excel "%excel%"
goto end

:opt2
python cat6-business-travel\fill_amap.py
goto end

:opt3
python cat4-upstream-transport\distance_searcher.py
goto end

:opt4
python cat4-9-sea-transport\sea_distance_searcher.py
goto end

:opt5
python cat4-9-sea-transport\pub151_distance.py
goto end

:quit
echo 退出

:end
pause
