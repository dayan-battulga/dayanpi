import subprocess
from pathlib import Path
from typing import NamedTuple


# ======== Classes ===========
class CpuTimes(NamedTuple):
    total: int
    idle: int


class CpuSampler:
    """How busy the CPU was since the last sample, from /proc/stat's running totals."""

    def __init__(self, stat_path: Path = Path("/proc/stat")) -> None:
        self.stat_path = stat_path
        self._previous: CpuTimes | None = None

    def sample(self) -> float | None:
        """The busy percent since the last call; None on the first one, when there's nothing to compare with."""
        current = read_cpu_times(self.stat_path.read_text())
        busy = None if self._previous is None else round(compute_busy_percent(self._previous, current), 2)
        self._previous = current
        return busy


# ======== Functions ===========


def read_cpu_times(stat_text: str) -> CpuTimes:
    """The whole chip's "cpu" line of /proc/stat."""
    fields = [int(field) for field in stat_text.splitlines()[0].split()[1:]]
    times = CpuTimes(total=sum(fields), idle=fields[3] + fields[4])  # idle + iowait
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


def throttle_status() -> dict:
    result = subprocess.run(
        ["vcgencmd", "get_throttled"],
        capture_output=True,
        text=True,
        check=True,
    )

    value = int(result.stdout.strip().split("=")[1], 16)

    return {"is_undervoltage": bool(value & (1 << 0))}


def snapshot(sampler: CpuSampler) -> dict:
    cpu_percent = sampler.sample()
    return {
        "temperature_celsius": temperature_celcius(),
        "uptime_seconds": uptime_seconds(),
        "memory": memory_usage(),
        "throttle": throttle_status(),
        "rates": None if cpu_percent is None else {"cpu_percent": cpu_percent},
    }
