import pytest

from dayanpi.hardware import collector
from dayanpi.hardware.collector import CpuTimes, RateSampler, compute_busy_percent, read_cpu_times


def make_stat(cores: list[tuple[int, int]]) -> str:
    """A /proc/stat with the whole-chip line summed from (user, idle) per core, plus the noise lines after it."""
    user_total = sum(user for user, _ in cores)
    idle_total = sum(idle for _, idle in cores)
    lines = [f"cpu  {user_total} 0 0 {idle_total} 0 0 0 0 0 0"]
    lines += [f"cpu{index} {user} 0 0 {idle} 0 0 0 0 0 0" for index, (user, idle) in enumerate(cores)]
    lines += ["intr 12345 0 0", "ctxt 999", "btime 1700000000", "procs_running 2"]
    stat = "\n".join(lines) + "\n"
    return stat


@pytest.fixture
def files(tmp_path):
    stats = tmp_path / "net" / "wlan0" / "statistics"
    stats.mkdir(parents=True)
    (stats / "rx_bytes").write_text("1000\n")
    (stats / "tx_bytes").write_text("500\n")
    return tmp_path


def test_read_cpu_times_keeps_the_chip_and_every_core_in_order():
    times = read_cpu_times(make_stat([(100, 400), (50, 450)]))
    assert list(times) == ["cpu", "cpu0", "cpu1"]
    assert times["cpu"] == CpuTimes(total=1000, idle=850)
    assert times["cpu1"] == CpuTimes(total=500, idle=450)


def test_read_cpu_times_counts_iowait_as_idle():
    times = read_cpu_times("cpu  10 0 5 80 5 0 0 0 0 0\n")
    assert times["cpu"] == CpuTimes(total=100, idle=85)


def test_busy_percent_is_zero_when_no_time_passed():
    reading = CpuTimes(total=500, idle=480)
    assert compute_busy_percent(reading, reading) == 0.0


def test_sampler_reports_each_core(files, monkeypatch):
    clock = iter([100.0, 101.0])
    monkeypatch.setattr(collector.time, "monotonic", lambda: next(clock))
    stat = files / "stat"
    stat.write_text(make_stat([(100, 400), (50, 450), (0, 500), (20, 480)]))
    sampler = RateSampler("wlan0", stat_path=stat, net_root=files / "net")

    assert sampler.sample() is None

    # cpu0 75% busy, cpu1 10%, cpu2 idle, cpu3 got no time at all.
    stat.write_text(make_stat([(175, 425), (60, 540), (0, 600), (20, 480)]))
    (files / "net" / "wlan0" / "statistics" / "rx_bytes").write_text("2000\n")
    rates = sampler.sample()

    assert rates.core_percents == [75.0, 10.0, 0.0, 0.0]
    assert rates.cpu_percent == pytest.approx(28.33, abs=0.01)
    assert rates.rx_kbps == pytest.approx(8.0)
    assert rates._asdict()["core_percents"] == [75.0, 10.0, 0.0, 0.0]


def test_sampler_skips_a_core_that_just_came_online(files, monkeypatch):
    clock = iter([100.0, 101.0])
    monkeypatch.setattr(collector.time, "monotonic", lambda: next(clock))
    stat = files / "stat"
    stat.write_text(make_stat([(100, 400)]))
    sampler = RateSampler("wlan0", stat_path=stat, net_root=files / "net")
    sampler.sample()

    stat.write_text(make_stat([(150, 450), (30, 70)]))
    rates = sampler.sample()

    assert rates.core_percents == [50.0]
