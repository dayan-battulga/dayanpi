import json
import os
import subprocess
import time
from pathlib import Path
from typing import NamedTuple


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


class RateSample(NamedTuple):
    cpu_percent: float
    rx_kbps: float
    tx_kbps: float
    core_percents: list[float]


class CpuTimes(NamedTuple):
    total: int
    idle: int


class RateSampler:
    def __init__(
        self,
        interface: str,
        stat_path: Path = Path("/proc/stat"),
        net_root: Path = Path("/sys/class/net"),
    ) -> None:
        self.interface = interface
        self.stat_path = stat_path
        self.net_root = net_root
        self._prev_total: int | None = None
        self._prev_idle: int | None = None
        self._prev_cores: dict[str, CpuTimes] = {}
        self._prev_rx: int | None = None
        self._prev_tx: int | None = None
        self._prev_time: float | None = None

    def sample(self) -> RateSample | None:
        times = read_cpu_times(self.stat_path.read_text())
        total = times["cpu"].total
        idle_total = times["cpu"].idle
        cores = {name: core for name, core in times.items() if name != "cpu"}

        base = self.net_root / self.interface / "statistics"
        rx = int((base / "rx_bytes").read_text().strip())
        tx = int((base / "tx_bytes").read_text().strip())
        now = time.monotonic()

        if self._prev_total is None:
            self._prev_total = total
            self._prev_idle = idle_total
            self._prev_cores = cores
            self._prev_rx = rx
            self._prev_tx = tx
            self._prev_time = now
            return None

        total_delta = total - self._prev_total
        idle_delta = idle_total - self._prev_idle
        elapsed = now - self._prev_time

        # same jiffy → dividing by zero would blow up
        if total_delta == 0:
            return None

        cpu_percent = 100 * (total_delta - idle_delta) / total_delta
        # A core that went offline since the last sample has no delta to report.
        core_percents = [
            round(compute_busy_percent(self._prev_cores[name], core), 2)
            for name, core in cores.items()
            if name in self._prev_cores
        ]
        # bytes → kilobits/sec
        rx_kbps = (rx - self._prev_rx) * 8 / 1000 / elapsed
        tx_kbps = (tx - self._prev_tx) * 8 / 1000 / elapsed

        self._prev_total = total
        self._prev_idle = idle_total
        self._prev_cores = cores
        self._prev_rx = rx
        self._prev_tx = tx
        self._prev_time = now

        return RateSample(
            cpu_percent=round(cpu_percent, 2),
            rx_kbps=round(rx_kbps, 2),
            tx_kbps=round(tx_kbps, 2),
            core_percents=core_percents,
        )


# ======== Functions ===========


def read_cpu_times(stat_text: str) -> dict[str, CpuTimes]:
    """Every cpu line of /proc/stat, in file order: "cpu" for the whole chip, then "cpu0", "cpu1"..."""
    times: dict[str, CpuTimes] = {}
    for line in stat_text.splitlines():
        if line.startswith("cpu"):
            name, *fields = line.split()
            values = [int(field) for field in fields]
            times[name] = CpuTimes(total=sum(values), idle=values[3] + values[4])  # idle + iowait
    return times


def compute_busy_percent(previous: CpuTimes, current: CpuTimes) -> float:
    """How busy a CPU was between two readings; 0 when no time passed for it."""
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    busy = 100 * (total_delta - idle_delta) / total_delta if total_delta > 0 else 0.0
    return busy


def temperature_celcius() -> float:
    temperature_path = Path("/sys/class/thermal/thermal_zone0/temp")
    temp_float = float(temperature_path.read_text().strip())
    normalized_temp = round(temp_float / 1000, 2)
    return normalized_temp


def uptime_seconds() -> float:
    uptime_seconds_path = Path("/proc/uptime")
    uptime_seconds = round(float(uptime_seconds_path.read_text().split()[0]), 2)
    return uptime_seconds


def memory_usage() -> MemoryUsage:
    memory_path = Path("/proc/meminfo")
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
        ["vcgencmd", "get_throttled"],
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


def snapshot(sampler: RateSampler) -> dict:
    rates = sampler.sample()
    return {
        "temperature_celsius": temperature_celcius(),
        "uptime_seconds": uptime_seconds(),
        "memory": memory_usage()._asdict(),
        "disk": disk_usage()._asdict(),
        "throttle": throttle_status()._asdict(),
        "rates": rates._asdict() if rates is not None else None,
    }


# ========== Main Run ============
if __name__ == "__main__":
    sampler = RateSampler("wlan0")  # or eth0 — ls /sys/class/net/
    time.sleep(1)
    print(json.dumps(snapshot(sampler), indent=2))
    time.sleep(1)
    print(json.dumps(snapshot(sampler), indent=2))
    time.sleep(1)
    print(json.dumps(snapshot(sampler), indent=2))
