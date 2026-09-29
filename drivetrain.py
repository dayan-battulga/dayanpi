import math
import threading
import time

DEADZONE = 0.05
SPEED_FLOOR = 0.4  # lowest duty cycle that still turns the wheels
MAX_SPEED = 0.6
PWM_FREQUENCY_HZ = 1000
REVERSAL_PAUSE_S = 0.15

# L298N wiring (BCM numbers). IN1/IN3 high = forward.
LEFT_FORWARD_PIN = 17
LEFT_BACKWARD_PIN = 27
LEFT_ENABLE_PIN = 12
RIGHT_FORWARD_PIN = 22
RIGHT_BACKWARD_PIN = 23
RIGHT_ENABLE_PIN = 13


def scale_speed(value: float) -> float:
    """Map a -1..1 input to a signed duty cycle: 0, or SPEED_FLOOR..MAX_SPEED."""
    # NaN slips through min/max as 1.0, i.e. full speed.
    safe_value = value if math.isfinite(value) else 0.0
    clamped = max(-1.0, min(1.0, safe_value))
    magnitude = abs(clamped)
    duty = 0.0
    if magnitude >= DEADZONE:
        span = (magnitude - DEADZONE) / (1.0 - DEADZONE)
        duty = SPEED_FLOOR + span * (MAX_SPEED - SPEED_FLOOR)
    signed_duty = math.copysign(duty, clamped)
    return signed_duty


class CommandTimer:
    """Remembers when the last drive command arrived; no GPIO, so it's easy to test."""

    def __init__(self, timeout_s: float, clock=time.monotonic) -> None:
        self._timeout_s = timeout_s
        self._clock = clock
        self._last_command_at: float | None = None

    def record_command(self) -> None:
        self._last_command_at = self._clock()

    def is_stale(self) -> bool:
        last_command_at = self._last_command_at
        stale = last_command_at is None or self._clock() - last_command_at > self._timeout_s
        return stale


class MotorSide:
    """One side of the L298N: two direction pins and one PWM enable pin."""

    def __init__(self, forward_pin: int, backward_pin: int, enable_pin: int, pin_factory) -> None:
        # Imported here, not at the top: if the venv can't see apt's gpiozero,
        # DriveTrain() fails (and app.py carries on without motors) instead of
        # `import drivetrain` taking the whole app down.
        from gpiozero import DigitalOutputDevice, PWMOutputDevice

        self._forward = DigitalOutputDevice(forward_pin, pin_factory=pin_factory)
        self._backward = DigitalOutputDevice(backward_pin, pin_factory=pin_factory)
        self._enable = PWMOutputDevice(
            enable_pin, frequency=PWM_FREQUENCY_HZ, pin_factory=pin_factory
        )
        self._applied_speed = 0.0
        self._last_direction = 0.0
        self._stopped_at = -math.inf

    def set_speed(self, speed: float, now: float) -> None:
        # Caller holds the lock. Slamming straight into reverse spikes the
        # current (and can brown out the Pi), so a reversal only goes through
        # once this side has been stopped for REVERSAL_PAUSE_S; until then it
        # stays at 0 and the browser's next resend applies the new direction.
        reversing = speed * self._last_direction < 0
        paused_long_enough = (
            self._applied_speed == 0 and now - self._stopped_at >= REVERSAL_PAUSE_S
        )
        applied_speed = 0.0 if reversing and not paused_long_enough else speed
        if applied_speed == 0 and self._applied_speed != 0:
            self._stopped_at = now
        if applied_speed != 0:
            self._last_direction = applied_speed
        self._applied_speed = applied_speed

        # EN goes to 0 first so the H-bridge never sees a direction flip while powered.
        self._enable.value = 0
        self._forward.value = applied_speed > 0
        self._backward.value = applied_speed < 0
        self._enable.value = abs(applied_speed)

    def close(self) -> None:
        self._forward.close()
        self._backward.close()
        self._enable.close()


class DriveTrain:
    """Sole owner of the six motor pins; every pin change happens under one lock."""

    def __init__(self, pin_factory=None, clock=time.monotonic) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._left = MotorSide(LEFT_FORWARD_PIN, LEFT_BACKWARD_PIN, LEFT_ENABLE_PIN, pin_factory)
        self._right = MotorSide(
            RIGHT_FORWARD_PIN, RIGHT_BACKWARD_PIN, RIGHT_ENABLE_PIN, pin_factory
        )

    def _set_both(self, left_speed: float, right_speed: float) -> None:
        now = self._clock()
        self._left.set_speed(left_speed, now)
        self._right.set_speed(right_speed, now)

    def drive(self, left: float, right: float) -> None:
        left_speed = scale_speed(left)
        right_speed = scale_speed(right)
        with self._lock:
            self._set_both(left_speed, right_speed)

    def stop(self) -> None:
        with self._lock:
            self._set_both(0.0, 0.0)

    def close(self) -> None:
        with self._lock:
            self._set_both(0.0, 0.0)
            self._left.close()
            self._right.close()
