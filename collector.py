from asyncio.constants import FLOW_CONTROL_HIGH_WATER_SSL_READ
import os
from pstats import Stats
import subprocess
from this import s
import time
from typing import NamedTuple
from pathlib import Path


# ======== Classes ===========
class MemoryUsage(NamedTuple):
    total_mb: float
    available_mb: float
    percent_used: float


class DiskUsage(NamedTuple):
    total_gb: float
    free_gb: float
    percent_used: float


class ThrottleStatus(NamedTuple):
    is_undervoltage: bool
    is_frequency_capped: bool
    is_throttled: bool
    has_undervoltage_occured: bool
    has_throttling_occured: bool


# ======== Functions ===========


def temperature_celcius() -> float:
    temperature_path = Path("sys/class/thermal/thermal_zone0/temp")
    temp_float = float(temperature_path.read_text().strip())
    normalized_temp = round(temp_float / 1000, 2)
    return normalized_temp


def uptime_seconds() -> float:
    uptime_seconds_path = Path("/proc/uptime")
    uptime_seconds = round(float(uptime_seconds_path.read_text().strip()[0]), 2)
    return uptime_seconds


def memory_usage() -> MemoryUsage:
    memory_path = Path("proc/meminfo")
    meminfo: dict[str, int] = {}

    for line in memory_path.read_text().splitlines():
        key, value, *_ = line.split()
        meminfo[key.rstrip(":")] = int(value)

    total_mb = meminfo["MemTotal"] / 1024
    available_mb = meminfo["MemAvailable"] / 1024
    percent_used = (1 - available_mb / total_mb) * 100

    return MemoryUsage(
        total_mb=round(total_mb, 2),
        available_mb=round(available_mb, 2),
        percent_used=round(percent_used, 2),
    )


def disk_usage(path: str = "/") -> DiskUsage:
    stats = os.statvfs(path)
    total_gb = (stats.f_blocks * stats.f_frsize) / (1024**3)
    free_gb = (stats.f_bavail * stats.f_frsize) / (1024**3)
    percent_used = (1 - free_gb / total_gb) * 100

    return DiskUsage(
        total_gb=total_gb,
        free_gb=free_gb,
        percent_used=percent_used,
    )


def throttle_status() -> ThrottleStatus:
    result = subprocess.run(
        ["vengencmd", "get_throttled"],
        capture_output=True,
        text=True,
        check=True,
    )

    value = int(result.stdout.strip().split("=")[1], 16)

    return ThrottleStatus(
        is_undervoltage=bool(value & (1 << 0)),
        is_frequency_capped=bool(value & (1 << 1)),
        is_throttled=bool(value & (1 << 2)),
        # sticky since boot (bits 16+)
        has_undervoltage_occured=bool(value & (1 << 16)),  # under-voltage since boot
        has_throttling_occured=bool(value & (1 << 18)),  # throttling since boot
    )


# ========== Main Run ============
if __name__ == "__main__":
    print(temperature_celcius())
    print(uptime_seconds())
    print(memory_usage())
    print(disk_usage())
    print(throttle_status())
