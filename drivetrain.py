import math
import threading
import time

from gpiozero import DigitalOutputDevice, PWMOutputDevice

# Tunables — change these in one place only.
DEADZONE = 0.05  # inputs below this are treated as 0
SPEED_FLOOR = 0.4  # lowest duty cycle that still turns the wheels
MAX_SPEED = 0.6
PWM_FREQUENCY_HZ = 1000

# L298N wiring (BCM numbers). IN1/IN3 high = forward.
LEFT_FORWARD_PIN = 17  # IN1
LEFT_BACKWARD_PIN = 27  # IN2
LEFT_ENABLE_PIN = 12  # ENA
RIGHT_FORWARD_PIN = 22  # IN3
RIGHT_BACKWARD_PIN = 23  # IN4
RIGHT_ENABLE_PIN = 13  # ENB


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


class DriveTrain:
    """Sole owner of the six motor pins; every pin change happens under one lock."""

    def __init__(self, pin_factory=None) -> None:
        self._lock = threading.Lock()
        self._left_forward = DigitalOutputDevice(LEFT_FORWARD_PIN, pin_factory=pin_factory)
        self._left_backward = DigitalOutputDevice(LEFT_BACKWARD_PIN, pin_factory=pin_factory)
        self._left_enable = PWMOutputDevice(
            LEFT_ENABLE_PIN, frequency=PWM_FREQUENCY_HZ, pin_factory=pin_factory
        )
        self._right_forward = DigitalOutputDevice(RIGHT_FORWARD_PIN, pin_factory=pin_factory)
        self._right_backward = DigitalOutputDevice(RIGHT_BACKWARD_PIN, pin_factory=pin_factory)
        self._right_enable = PWMOutputDevice(
            RIGHT_ENABLE_PIN, frequency=PWM_FREQUENCY_HZ, pin_factory=pin_factory
        )

    def _set_side(
        self,
        forward: DigitalOutputDevice,
        backward: DigitalOutputDevice,
        enable: PWMOutputDevice,
        speed: float,
    ) -> None:
        # Caller holds the lock. EN goes to 0 first so the H-bridge never
        # sees a direction flip while powered.
        enable.value = 0
        forward.value = speed > 0
        backward.value = speed < 0
        enable.value = abs(speed)

    def _set_both(self, left_speed: float, right_speed: float) -> None:
        self._set_side(self._left_forward, self._left_backward, self._left_enable, left_speed)
        self._set_side(self._right_forward, self._right_backward, self._right_enable, right_speed)

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
            for device in (
                self._left_forward,
                self._left_backward,
                self._left_enable,
                self._right_forward,
                self._right_backward,
                self._right_enable,
            ):
                device.close()
