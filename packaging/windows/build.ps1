# -*- coding: utf-8 -*-
# SysCenter Windows EXE 构建脚本（规格书 §66）
# 流程：清理 -> 准备 venv -> 装依赖 -> 前端 build -> 后端检查 -> PyInstaller 打包 -> 复制资源 -> 版本信息
#
# 说明（规格书 §4.1）：
#   本机构建环境缺少 MSVC cl.exe，Nuitka 需 MinGW 且对 asyncpg/cryptography/psutil 等
#   大量 C 扩展 + lark-oapi 兼容不稳定。故实际交付采用 PyInstaller（规格书允许的兼容方案）。
#   如需改用 Nuitka，设置环境变量 $env:USE_NUITKA=1 即可切换（会先验证 Nuitka 可行性）。
#
# 2026-08-20 重大修正（务必遵守）：
#   - 构建 Python 必须自带 tkinter（托盘 OTP 退出弹窗依赖）。托管版 3.13 是嵌入式构建，
#     无 tkinter，PyInstaller 会告警 "tkinter installation is broken" 并排除它 → 退出认证失效。
#     本机用 Python 3.12（C:\Program Files\Python312，自带 Tk 8.6）。
#   - 采用 onedir（不用 onefile）：onefile 每次启动向 %TEMP% 解压 1.1 万+ 文件（lark_oapi 占 9770），
#     退出时 rmtree 清理被火绒逐个扫描 → 进程无限期空转（version/doctor/退出全部挂死）。
#     onedir 不解压不清理，秒启动秒退出，交付物为 SysCenter/ 文件夹（exe + _internal/ + 资源）。
#   - 必须 --collect-all app：syscenter_app 以字符串 "app.main:app" 加载 ASGI 应用，
#     PyInstaller 静态分析看不到字符串导入，app.main/app.db 及全部路由/服务不会被打包 → 后端起不来。
param(
    [string]$Python = "C:\Program Files\Python312\python.exe",  # 必须自带 tkinter；可用 py -3.12 等
    [string]$OutDir = "dist_exe",           # 产物输出目录（相对仓库根）
    [switch]$SkipFrontend                   # 跳过 npm build（已构建好 dist 时使用）
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $Root
try {
    Write-Host "==> [1/7] 清理旧产物" -ForegroundColor Cyan
    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    if (Test-Path "build_venv") { Remove-Item -Recurse -Force "build_venv" }
    if (Test-Path "backend/build") { Remove-Item -Recurse -Force "backend/build" }
    if (Test-Path "backend/dist") { Remove-Item -Recurse -Force "backend/dist" }

    Write-Host "==> [2/7] 准备构建 venv 并安装依赖" -ForegroundColor Cyan
    if (-not (Test-Path "build_venv\Scripts\python.exe")) {
        & $Python -m venv build_venv
        $venvPy = Join-Path $Root "build_venv\Scripts\python.exe"
        # 注意：不执行 pip --upgrade（旧 pip 24.3.1 足够，升级触发卸载旧版 pip 可能被安全组件拦截）
        & $venvPy -m pip install -r backend/requirements.txt
        & $venvPy -m pip install -r packaging/windows/requirements-build.txt
    } else {
        $venvPy = Join-Path $Root "build_venv\Scripts\python.exe"
        Write-Host "    复用已有 build_venv（跳过重建与重装）" -ForegroundColor DarkGray
    }

    Write-Host "==> [3/7] 前端构建（npm ci && npm run build）" -ForegroundColor Cyan
    if (-not $SkipFrontend) {
        Push-Location frontend
        try {
            & npm ci
            & npm run build
        } finally { Pop-Location }
    } else {
        Write-Host "    跳过前端构建（使用已有 frontend/dist）"
    }

    Write-Host "==> [4/7] 后端导入/编译检查" -ForegroundColor Cyan
    & $venvPy -m py_compile backend/syscenter_app.py backend/service.py
    & $venvPy -c "import sys; sys.path.insert(0,'backend'); import app.config, app.main; print('backend import OK')"

    $useNuitka = $env:USE_NUITKA -eq "1"
    if ($useNuitka) {
        Write-Host "==> [5/7] Nuitka 打包（验证模式）" -ForegroundColor Cyan
        & $venvPy -m nuitka --onefile --standalone `
            --assume-yes-for-downloads `
            --output-dir=$OutDir `
            --include-package=app `
            --include-package-data=app `
            backend/syscenter_app.py
    } else {
        Write-Host "==> [5/7] PyInstaller 打包（onedir，见文件头 2026-08-20 重大修正）" -ForegroundColor Cyan
        & $venvPy -m PyInstaller --noconfirm --clean --onedir --windowed `
            --name SysCenter `
            --paths backend `
            --hidden-import uvicorn.logging `
            --hidden-import uvicorn.loops.auto `
            --hidden-import uvicorn.protocols.http.auto `
            --hidden-import uvicorn.protocols.websockets.auto `
            --hidden-import uvicorn.lifespan.on `
            --hidden-import tkinter `
            --collect-all lark_oapi `
            --collect-all uvicorn `
            --collect-all alembic `
            --collect-all asyncpg `
            --collect-all psycopg2 `
            --collect-all cryptography `
            --collect-all pydantic `
            --collect-all pydantic_settings `
            --collect-all segno `
            --collect-all pystray `
            --collect-all PIL `
            --collect-all app `
            --paths backend/alembic `
            backend/syscenter_app.py
        # PyInstaller onedir 输出：dist/SysCenter/（SysCenter.exe + _internal/）
        $pyiOut = Join-Path $Root "dist\SysCenter"
        $appHome = Join-Path $OutDir "SysCenter"
        New-Item -ItemType Directory -Force -Path $appHome | Out-Null
        Move-Item (Join-Path $pyiOut "SysCenter.exe") (Join-Path $appHome "SysCenter.exe") -Force
        Move-Item (Join-Path $pyiOut "_internal") (Join-Path $appHome "_internal") -Force
    }

    Write-Host "==> [6/7] 复制运行资源（alembic / migrations / config / frontend / .env 模板）" -ForegroundColor Cyan
    $appHome = Join-Path $OutDir "SysCenter"
    New-Item -ItemType Directory -Force -Path $appHome | Out-Null
    # exe 已由 [5/7] 归置到 SysCenter/ 下，资源同目录（规格书 §30/§86 安装布局）
    Copy-Item "backend/alembic.ini"        -Destination $appHome -Force
    Copy-Item "backend/migrations"        -Destination $appHome -Recurse -Force
    Copy-Item "config"                    -Destination $appHome -Recurse -Force
    Copy-Item "frontend/dist"             -Destination $appHome -Recurse -Force
    if (Test-Path ".env") { Copy-Item ".env" -Destination $appHome -Force }
    else { Copy-Item ".env.example" -Destination (Join-Path $appHome ".env") -Force }

    # 复制 OTP 密钥等敏感文件（沿用现有 otp_secret，避免重新绑定验证器）
    $dataSrc = Join-Path "backend" "data"
    $dataDst = Join-Path $appHome "data"
    New-Item -ItemType Directory -Force -Path $dataDst | Out-Null
    foreach ($f in @("otp_secret", "otp_enrolled", "otp_bootstrap", "session_secret")) {
        $src = Join-Path $dataSrc $f
        if (Test-Path $src) { Copy-Item $src -Destination $dataDst -Force }
    }

    Write-Host "==> [7/7] 版本信息 & Smoke Test" -ForegroundColor Cyan
    & (Join-Path $appHome "SysCenter.exe") version
    & (Join-Path $appHome "SysCenter.exe") doctor

    Write-Host ""
    Write-Host "构建完成。产物目录：$appHome" -ForegroundColor Green
    Write-Host "下一步：双击 SysCenter.exe 即以托盘模式运行（无终端窗口，缩右下角）；" -ForegroundColor Green
    Write-Host "        运行 'SysCenter.exe install' 设置登录自启；'SysCenter.exe uninstall' 取消自启。" -ForegroundColor Green
} finally {
    Pop-Location
}
