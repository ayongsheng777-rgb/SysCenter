@echo off
REM SysCenter 后端启动脚本（本机 Windows 进程运行，psutil 直读真实宿主机）
REM 用法：双击或在 CMD 中运行；首次会自动建 venv 并装依赖
REM 注：不再写死 Python 绝对路径（P3-01），改用系统 python/py 启动器创建本地 venv
setlocal
cd /d "%~dp0"

set VENV=%~dp0.venv

if not exist "%VENV%" (
    echo [SysCenter] 创建虚拟环境...
    where py >nul 2>nul && py -3 -m venv "%VENV%" || python -m venv "%VENV%"
    if errorlevel 1 (
        echo [SysCenter] 创建 venv 失败：请先安装 Python 3.11+ 并确保 python 或 py 在 PATH 中
        exit /b 1
    )
)

call "%VENV%\Scripts\activate.bat"

echo [SysCenter] 安装依赖（如需走代理请确认 http_proxy 已设置）...
set PIP_EXTRA=
if defined http_proxy (set PIP_EXTRA=--proxy %http_proxy%)
python -m pip install -r "%~dp0requirements.txt" -q %PIP_EXTRA%

REM ===== 运行环境 =====
set DATA_DIR=%~dp0data
set BACKEND_HOST=0.0.0.0
set BACKEND_PORT=8352
set PG_HOST=127.0.0.1
set PG_PORT=5442
set REDIS_HOST=127.0.0.1
set REDIS_PORT=6387
set TZ=Asia/Shanghai

echo [SysCenter] 启动后端 http://%BACKEND_HOST%:%BACKEND_PORT%
uvicorn app.main:app --host %BACKEND_HOST% --port %BACKEND_PORT%
endlocal
