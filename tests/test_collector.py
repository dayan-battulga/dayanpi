import pytest

from dayanpi.hardware.collector import CpuSampler, CpuTimes, compute_busy_percent, read_cpu_times


def make_stat(user: int, idle: int) -> str:
    """A /proc/stat whose whole-chip line has these totals, with a core line and the noise lines after it."""
    lines = [f"cpu  {user} 0 0 {idle} 0 0 0 0 0 0", f"cpu0 {user} 0 0 {idle} 0 0 0 0 0 0", "intr 12345 0 0", "ctxt 999", "btime 1700000000"]
    stat = "\n".join(lines) + "\n"
    return stat


def test_read_cpu_times_reads_the_whole_chip_line():
    assert read_cpu_times(make_stat(150, 850)) == CpuTimes(total=1000, idle=850)


def test_read_cpu_times_counts_iowait_as_idle():
    times = read_cpu_times("cpu  10 0 5 80 5 0 0 0 0 0\n")
    assert times == CpuTimes(total=100, idle=85)


def test_busy_percent_is_zero_when_no_time_passed():
    reading = CpuTimes(total=500, idle=480)
    assert compute_busy_percent(reading, reading) == 0.0


def test_the_sampler_needs_two_readings(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text(make_stat(100, 900))
    sampler = CpuSampler(stat_path=stat)
    assert sampler.sample() is None, "nothing to compare with yet"

    stat.write_text(make_stat(175, 925))
    assert sampler.sample() == pytest.approx(75.0)
    assert sampler.sample() == 0.0, "no time passed since the last one"
