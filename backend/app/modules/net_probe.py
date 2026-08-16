# -*- coding: utf-8 -*-
"""网络探测工具：ping 延迟、端口连通、ARP 表解析、网段扫描

全部基于本机执行（Windows 上 ping / arp 为系统命令），用于局域网设备发现与 VPS 存活监控。
"""
import logging
import shutil
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger("net_probe")


def ping(ip: str, timeout_ms: int = 800) -> Optional[float]:
    """返回往返延迟毫秒（不可达返回 None）。Windows ping -n 1 -w <ms>。"""
    if shutil.which("ping") is None:
        return None
    try:
        r = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True, text=True, timeout=max(2, timeout_ms / 1000 + 1))
        out = r.stdout
        if "TTL=" in out or "Reply from" in out or "回复来自" in out:
            # 提取时间
            for token in out.replace("=", " ").split():
                if token.replace(".", "").isdigit() and "ms" in out[out.find(token):out.find(token) + 6]:
                    try:
                        return float(token)
                    except Exception:
                        pass
            return 0.0
        return None
    except Exception:
        return None


def check_port(host: str, port: int, timeout_ms: int = 1500) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_ms / 1000):
            return True
    except Exception:
        return False


def arp_table() -> dict[str, str]:
    """返回 {ip: mac}。Windows: arp -a。"""
    out = {}
    try:
        r = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and _is_ipv4(parts[0]):
                mac = parts[1]
                if mac != "—" and mac.lower() != "ff-ff-ff-ff-ff-ff":
                    out[parts[0]] = mac
    except Exception:
        pass
    return out


def _is_ipv4(s: str) -> bool:
    try:
        socket.inet_aton(s)
        return True
    except Exception:
        return False


def scan_subnet(subnet: str, timeout_ms: int = 800, max_workers: int = 60) -> list[dict]:
    """扫描网段，subnet 形如 '192.168.1'（不含末尾点）。返回在线主机列表。"""
    if not subnet:
        return []
    arp = arp_table()
    hosts = []
    found = threading.Lock()

    def probe(last: int):
        ip = f"{subnet}.{last}"
        lat = ping(ip, timeout_ms)
        if lat is not None:
            try:
                name = socket.gethostbyaddr(ip)[0]
            except Exception:
                name = ""
            with found:
                hosts.append({
                    "ip": ip,
                    "mac": arp.get(ip, ""),
                    "latency_ms": lat,
                    "hostname": name,
                })

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(probe, range(1, 255)))
    hosts.sort(key=lambda h: int(h["ip"].split(".")[-1]))
    return hosts


def host_status(host: str, port: Optional[int] = None, timeout_ms: int = 1500) -> dict:
    lat = ping(host, timeout_ms)
    port_open = check_port(host, port) if port else None
    return {
        "host": host,
        "alive": lat is not None,
        "latency_ms": lat,
        "port": port,
        "port_open": port_open,
    }
