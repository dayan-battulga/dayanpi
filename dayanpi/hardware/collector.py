import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple


# ======== Classes ===========
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
        self._previous: dict | None = None

    def sample(self) -> RateSample | None:
        base = self.net_root / self.interface / "statistics"
        current = {
            "times": read_cpu_times(self.stat_path.read_text()),
            "rx": int((base / "rx_bytes").read_text().strip()),
            "tx": int((base / "tx_bytes").read_text().strip()),
            "at": time.monotonic(),
        }
        previous = self._previous
        if previous is None:
            self._previous = current
            return None

        # same jiffy → dividing by zero would blow up
        if current["times"]["cpu"].total == previous["times"]["cpu"].total:
            return None

        cpu_percent = compute_busy_percent(previous["times"]["cpu"], current["times"]["cpu"])
        # A core that went offline since the last sample has no delta to report.
        core_percents = [
            round(compute_busy_percent(previous["times"][name], core), 2)
            for name, core in current["times"].items()
            if name != "cpu" and name in previous["times"]
        ]
        # bytes → kilobits/sec
        elapsed = current["at"] - previous["at"]
        rx_kbps = (current["rx"] - previous["rx"]) * 8 / 1000 / elapsed
        tx_kbps = (current["tx"] - previous["tx"]) * 8 / 1000 / elapsed
        self._previous = current

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


def memory_usage() -> dict:
    memory_path = Path("/proc/meminfo")
    meminfo: dict[str, int] = {}

    for line in memory_path.read_text().splitlines():
        key, value, *_ = line.split()
        meminfo[key.rstrip(":")] = int(value)

    total_mb = meminfo["MemTotal"] / 1024
    available_mb = meminfo["MemAvailable"] / 1024
    percent_used = (1 - available_mb / total_mb) * 100

    return {
        "total_mb": round(total_mb, 2),
        "available_mb": round(available_mb, 2),
        "percent_used": round(percent_used, 2),
    }


def disk_usage(path: str = "/") -> dict:
    usage = shutil.disk_usage(path)
    total_gb = usage.total / (1024**3)
    free_gb = usage.free / (1024**3)
    percent_used = (1 - free_gb / total_gb) * 100

    return {
        "total_gb": total_gb,
        "free_gb": free_gb,
        "percent_used": percent_used,
    }


def throttle_status() -> dict:
    result = subprocess.run(
        ["vcgencmd", "get_throttled"],
        capture_output=True,
        text=True,
        check=True,
    )

    value = int(result.stdout.strip().split("=")[1], 16)

    return {
        "is_undervoltage": bool(value & (1 << 0)),
        "is_frequency_capped": bool(value & (1 << 1)),
        "is_throttled": bool(value & (1 << 2)),
        # sticky since boot (bits 16+)
        "has_undervoltage_occured": bool(value & (1 << 16)),  # under-voltage since boot
        "has_throttling_occured": bool(value & (1 << 18)),  # throttling since boot
    }


def snapshot(sampler: RateSampler) -> dict:
    rates = sampler.sample()
    return {
        "temperature_celsius": temperature_celcius(),
        "uptime_seconds": uptime_seconds(),
        "memory": memory_usage(),
        "disk": disk_usage(),
        "throttle": throttle_status(),
        "rates": rates._asdict() if rates is not None else None,
    }

