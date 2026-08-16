# -*- coding: utf-8 -*-
"""系统健康探针：psutil 直读本机（后端以 Windows 进程运行，故读到的就是真实宿主机）"""
import psutil
import time


def get_health() -> dict:
    boot_ts = psutil.boot_time()
    uptime = int(time.time() - boot_ts)
    # 物理磁盘分区（跳过 CD-ROM 等）
    disks = []
    for p in psutil.disk_partitions():
        if "cdrom" in p.opts or p.fstype == "":
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({
                "mount": p.mountpoint, "fstype": p.fstype,
                "total_gb": round(u.total / 1024 ** 3, 2),
                "used_gb": round(u.used / 1024 ** 3, 2),
                "percent": u.percent,
            })
        except Exception:
            continue

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    net = psutil.net_io_counters()

    # Top 进程（CPU 占用）
    top_cpu = []
    try:
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            top_cpu.append({
                "pid": p.info["pid"], "name": p.info["name"],
                "cpu": round(p.info["cpu_percent"] or 0, 1),
                "mem": round(p.info["memory_percent"] or 0, 1),
            })
        top_cpu = sorted(top_cpu, key=lambda x: x["cpu"], reverse=True)[:10]
    except Exception:
        top_cpu = []

    return {
        "hostname": __import__("socket").gethostname(),
        "platform": f"{psutil.WINDOWS and 'Windows' or 'Unknown'}",
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "ram_total_gb": round(mem.total / 1024 ** 3, 2),
        "ram_used_gb": round(mem.used / 1024 ** 3, 2),
        "ram_percent": mem.percent,
        "swap_percent": swap.percent,
        "disks": disks,
        "disk_total_gb": round(sum(d["total_gb"] for d in disks), 2),
        "disk_used_gb": round(sum(d["used_gb"] for d in disks), 2),
        "boot_time": boot_ts,
        "uptime_seconds": uptime,
        "process_count": len(psutil.pids()),
        "net_io": {
            "bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent, "packets_recv": net.packets_recv,
        },
        "top_cpu": top_cpu,
    }


def get_interfaces() -> list[dict]:
    """本机网卡状态与地址。"""
    out = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    for name, st in stats.items():
        ipv4 = [a.address for a in addrs.get(name, []) if a.family == __import__("socket").AF_INET]
        ipv6 = [a.address for a in addrs.get(name, []) if a.family == __import__("socket").AF_INET6]
        out.append({
            "name": name,
            "is_up": st.isup,
            "speed_mbps": st.speed,
            "mtu": st.mtu,
            "ipv4": ipv4,
            "ipv6": ipv6,
        })
    return out
