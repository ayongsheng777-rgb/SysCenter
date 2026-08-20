#!/usr/bin/env bash
# SysCenter EXE 构建运行器（本机实际产出）
# 注意：本环境对「批量删除（>50 文件/次）」做安全拦截（回收站不可用即失败），
#       因此本脚本【绝不使用 rm -rf 批量删除】；构建目录用时间戳唯一命名，靠覆盖实现更新。
set -uo pipefail
cd /d/WorkBuddy/SysCenter || exit 1

export HTTP_PROXY=http://127.0.0.1:1080
export HTTPS_PROXY=http://127.0.0.1:1080
export http_proxy=http://127.0.0.1:1080
export https_proxy=http://127.0.0.1:1080

STAMP=$(date +%Y%m%d_%H%M%S)
VENV_DIR="build_venv_${STAMP}"
APP="dist_exe/SysCenter"
LOG=/d/WorkBuddy/SysCenter/build_venv_build.log
exec > >(tee -a "$LOG") 2>&1

echo "===== [$(date)] 开始构建 SysCenter.exe ====="

PY="C:/Users/anyong/.workbuddy/binaries/python/versions/3.13.12/python.exe"
echo ">>> 使用 Python: $($PY --version)"

echo ">>> [1] 创建构建 venv: $VENV_DIR"
"$PY" -m venv "$VENV_DIR"
VENV="$(pwd)/$VENV_DIR/Scripts/python.exe"
# 不执行 pip 自升级（本机 pip 删除走回收站安全删除，沙箱下不可用）

echo ">>> [2] 安装运行时依赖"
"$VENV" -m pip install --no-cache-dir -r backend/requirements.txt

echo ">>> [3] 安装打包依赖"
"$VENV" -m pip install --no-cache-dir -r packaging/windows/requirements-build.txt

echo ">>> [4] 编译/导入预检"
"$VENV" -m py_compile backend/syscenter_app.py backend/service.py backend/app/config.py backend/app/main.py
"$VENV" -c "import sys; sys.path.insert(0,'backend'); import app.config, app.main; print('backend import OK')"

echo ">>> [5] PyInstaller onefile 打包"
cd backend
"$VENV" -m PyInstaller --noconfirm --clean --onefile \
  --name SysCenter \
  --paths . \
  --hidden-import service \
  --hidden-import psutil \
  --hidden-import yaml \
  --hidden-import dotenv \
  --hidden-import win32serviceutil \
  --hidden-import win32service \
  --hidden-import win32event \
  --hidden-import asyncpg \
  --collect-all asyncpg \
  --hidden-import redis \
  --hidden-import redis.asyncio \
  --hidden-import alembic \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --collect-all lark_oapi \
  --collect-all uvicorn \
  --collect-all alembic \
  syscenter_app.py
cd ..

echo ">>> [6] 归置运行资源（覆盖式，不删除）"
mkdir -p "$APP"
cp -f backend/dist/SysCenter.exe "$APP"/
cp -f backend/alembic.ini "$APP"/
mkdir -p "$APP"/migrations
cp -rf backend/migrations/. "$APP"/migrations/
mkdir -p "$APP"/config
cp -rf config/. "$APP"/config/
mkdir -p "$APP"/frontend/dist
cp -rf frontend/dist/. "$APP"/frontend/dist/
if [ -f .env ]; then cp -f .env "$APP"/.env; else cp -f .env.example "$APP"/.env; fi

echo ">>> [7] Smoke: version"
"$APP/SysCenter.exe" version
echo ">>> [7] Smoke: doctor"
"$APP/SysCenter.exe" doctor

echo "===== [$(date)] 构建完成，产物：$APP ====="
