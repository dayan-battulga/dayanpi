import math

import pytest
from gpiozero.exc import GPIODeviceClosed
from gpiozero.pins.mock import MockFactory, MockPin, MockPWMPin

import drivetrain
from drivetrain import CommandTimer, DriveTrain


@pytest.fixture
def factory():
    mock_factory = MockFactory(pin_class=MockPWMPin)
    yield mock_factory
    mock_factory.close()


@pytest.fixture
def train(factory):
    drive_train = DriveTrain(pin_factory=factory)
    yield drive_train
    drive_train.close()


def read_side(factory, forward_pin, backward_pin, enable_pin):
    side_state = {
        "forward": bool(factory.pin(forward_pin).state),
        "backward": bool(factory.pin(backward_pin).state),
        "enable": factory.pin(enable_pin).state,
    }
    return side_state


def read_left(factory):
    return read_side(
        factory,
        drivetrain.LEFT_FORWARD_PIN,
        drivetrain.LEFT_BACKWARD_PIN,
        drivetrain.LEFT_ENABLE_PIN,
    )


def read_right(factory):
    return read_side(
        factory,
        drivetrain.RIGHT_FORWARD_PIN,
        drivetrain.RIGHT_BACKWARD_PIN,
        drivetrain.RIGHT_ENABLE_PIN,
    )


FORWARD_FULL = {"forward": True, "backward": False, "enable": pytest.approx(drivetrain.MAX_SPEED)}
BACKWARD_FULL = {"forward": False, "backward": True, "enable": pytest.approx(drivetrain.MAX_SPEED)}
STOPPED = {"forward": False, "backward": False, "enable": 0}


def test_forward(factory, train):
    train.drive(1, 1)
    assert read_left(factory) == FORWARD_FULL
    assert read_right(factory) == FORWARD_FULL


def test_backward(factory, train):
    train.drive(-1, -1)
    assert read_left(factory) == BACKWARD_FULL
    assert read_right(factory) == BACKWARD_FULL


def test_spin_in_place(factory, train):
    train.drive(1, -1)
    assert read_left(factory) == FORWARD_FULL
    assert read_right(factory) == BACKWARD_FULL


def test_clamps_out_of_range(factory, train):
    train.drive(5, -5)
    assert read_left(factory) == FORWARD_FULL
    assert read_right(factory) == BACKWARD_FULL


def test_deadzone_is_stopped(factory, train):
    train.drive(1, 1)
    train.drive(0.04, -0.04)
    assert read_left(factory) == STOPPED
    assert read_right(factory) == STOPPED


def test_non_finite_is_stopped(factory, train):
    train.drive(math.nan, math.inf)
    assert read_left(factory) == STOPPED
    assert read_right(factory) == STOPPED


def test_floor_scaling(factory, train):
    train.drive(drivetrain.DEADZONE, -0.525)
    assert read_left(factory)["enable"] == pytest.approx(drivetrain.SPEED_FLOOR)
    assert read_right(factory)["enable"] == pytest.approx(
        (drivetrain.SPEED_FLOOR + drivetrain.MAX_SPEED) / 2
    )
    assert read_right(factory)["backward"]


def test_stop(factory, train):
    train.drive(1, -1)
    train.stop()
    assert read_left(factory) == STOPPED
    assert read_right(factory) == STOPPED


def test_close(factory):
    drive_train = DriveTrain(pin_factory=factory)
    drive_train.drive(1, 1)
    drive_train.close()
    assert read_left(factory) == STOPPED
    assert read_right(factory) == STOPPED
    with pytest.raises(GPIODeviceClosed):
        drive_train.drive(1, 1)


def test_enable_drops_before_direction_flips(factory, train, monkeypatch):
    train.drive(1, 1)

    changes = []
    original_change_state = MockPin._change_state

    def record_change_state(pin, value):
        changes.append((pin, value))
        return original_change_state(pin, value)

    monkeypatch.setattr(MockPin, "_change_state", record_change_state)
    train.drive(-1, 1)

    enable = factory.pin(drivetrain.LEFT_ENABLE_PIN)
    forward = factory.pin(drivetrain.LEFT_FORWARD_PIN)
    backward = factory.pin(drivetrain.LEFT_BACKWARD_PIN)
    enable_off_at = changes.index((enable, 0))
    forward_off_at = changes.index((forward, False))
    backward_on_at = changes.index((backward, True))
    enable_on_at = changes.index((enable, pytest.approx(drivetrain.MAX_SPEED)))
    assert enable_off_at < forward_off_at < enable_on_at
    assert enable_off_at < backward_on_at < enable_on_at


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def timer(clock):
    return CommandTimer(timeout_s=0.5, clock=clock)


def test_timer_stale_before_any_command(timer):
    assert timer.is_stale()


def test_timer_fresh_within_timeout(clock, timer):
    timer.record_command()
    clock.now += 0.49
    assert not timer.is_stale()


def test_timer_stale_after_timeout(clock, timer):
    timer.record_command()
    clock.now += 0.51
    assert timer.is_stale()


def test_timer_new_command_resets(clock, timer):
    timer.record_command()
    clock.now += 0.4
    timer.record_command()
    clock.now += 0.4
    assert not timer.is_stale()
    clock.now += 0.2
    assert timer.is_stale()
