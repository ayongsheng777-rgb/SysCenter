# -*- coding: utf-8 -*-
"""Windows Service 封装（规格书 §6/§7）

由 `SysCenter.exe install` 安装为系统服务；SvcDoRun 启动 uvicorn（后台线程）并等待
SCM 停止信号。恢复策略（第一次/第二次/后续失败均重启服务，延迟 5000ms）在安装时设置。

仅在 Windows + pywin32 环境下可用；非 Windows 导入本模块会失败（cmd_install 已做 ImportError 兜底）。
"""
import os
import sys
import win32event
import win32service
import win32serviceutil

# 确保 backend 在 sys.path（EXE 冻结后 syscenter_app 与 service 同目录）
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import syscenter_app  # noqa: E402


class SysCenterService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SysCenter"
    _svc_display_name_ = "SysCenter Service"
    _svc_description_ = "SysCenter Windows Management Platform"

    def __init__(self, args):
        super().__init__(args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self._thread = None

    def SvcDoRun(self):
        syscenter_app._setup_logging()
        # 单实例保护（规格书 §29）：避免多个后端争抢端口/数据库
        if syscenter_app._is_running():
            syscenter_app.log.warning("SysCenter 已在运行，Service 退出以避免重复实例")
            return
        syscenter_app._write_lock(os.getpid())
        try:
            self._thread = syscenter_app.start_server_thread()
            # 阻塞等待 SCM 停止信号（规格书 §7/§28 自动恢复由 SCM 负责）
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        finally:
            syscenter_app.stop_server()
            if self._thread is not None:
                self._thread.join(timeout=15)
            try:
                syscenter_app.LOCK_FILE.unlink()
            except OSError:
                pass

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(SysCenterService)
