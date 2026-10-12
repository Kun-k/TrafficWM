"""A small, deterministic kinematic bicycle model for AV actuator commands."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class VehicleState:
    x: float
    y: float
    heading: float
    speed: float
    acceleration: float = 0.0

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "VehicleState":
        heading = value.get("heading")
        if heading is None and value.get("angle") is not None:
            heading = math.radians(90.0 - _finite(value.get("angle")))
        vx = value.get("vx")
        vy = value.get("vy")
        speed_default = math.hypot(_finite(vx), _finite(vy)) if vx is not None or vy is not None else 0.0
        acceleration = value.get("acceleration")
        if acceleration is None and (value.get("ax") is not None or value.get("ay") is not None):
            acceleration = math.hypot(_finite(value.get("ax")), _finite(value.get("ay")))
        return cls(
            x=_finite(value.get("x")),
            y=_finite(value.get("y")),
            heading=normalize_angle(_finite(heading)),
            speed=max(0.0, _finite(value.get("speed"), speed_default)),
            acceleration=_finite(acceleration),
        )

    def as_mapping(self) -> dict[str, float]:
        vx = self.speed * math.cos(self.heading)
        vy = self.speed * math.sin(self.heading)
        return {
            "x": self.x,
            "y": self.y,
            "heading": self.heading,
            "speed": self.speed,
            "acceleration": self.acceleration,
            "vx": vx,
            "vy": vy,
            "ax": self.acceleration * math.cos(self.heading),
            "ay": self.acceleration * math.sin(self.heading),
        }


@dataclass(frozen=True)
class KinematicBicycleModel:
    wheelbase: float = 2.8
    max_acceleration: float = 3.5
    max_deceleration: float = 7.0
    max_steering_angle: float = math.radians(35.0)
    rolling_deceleration: float = 0.08

    def step(
        self,
        state: VehicleState,
        *,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        dt: float = 0.1,
    ) -> VehicleState:
        dt = max(1e-4, _finite(dt, 0.1))
        throttle = _clamp(_finite(throttle), 0.0, 1.0)
        brake = _clamp(_finite(brake), 0.0, 1.0)
        steering = _clamp(_finite(steering), -1.0, 1.0)
        acceleration = (
            throttle * self.max_acceleration
            - brake * self.max_deceleration
            - (self.rolling_deceleration if state.speed > 0.05 and throttle <= 0.0 else 0.0)
        )
        next_speed = max(0.0, state.speed + acceleration * dt)
        average_speed = 0.5 * (state.speed + next_speed)
        steer_angle = steering * self.max_steering_angle
        yaw_rate = average_speed * math.tan(steer_angle) / max(0.1, self.wheelbase)
        midpoint_heading = state.heading + 0.5 * yaw_rate * dt
        return VehicleState(
            x=state.x + average_speed * math.cos(midpoint_heading) * dt,
            y=state.y + average_speed * math.sin(midpoint_heading) * dt,
            heading=normalize_angle(state.heading + yaw_rate * dt),
            speed=next_speed,
            acceleration=acceleration,
        )


def _direct_state(current: VehicleState, values: dict[str, Any], dt: float) -> VehicleState:
    heading = values.get("heading")
    if heading is None and values.get("angle") is not None:
        heading = math.radians(90.0 - _finite(values.get("angle")))
    heading = normalize_angle(_finite(heading, current.heading))
    speed = values.get("speed")
    if speed is None and (values.get("vx") is not None or values.get("vy") is not None):
        speed = math.hypot(_finite(values.get("vx")), _finite(values.get("vy")))
    acceleration = _finite(values.get("acceleration"), current.acceleration)
    speed = max(0.0, _finite(speed, current.speed + acceleration * dt))
    x_default = current.x + speed * math.cos(heading) * dt
    y_default = current.y + speed * math.sin(heading) * dt
    return VehicleState(
        x=_finite(values.get("x"), x_default),
        y=_finite(values.get("y"), y_default),
        heading=heading,
        speed=speed,
        acceleration=acceleration,
    )


def rollout_control(
    current: dict[str, Any],
    *,
    mode: str,
    state: dict[str, Any] | None = None,
    actuators: dict[str, Any] | None = None,
    trajectory: Iterable[dict[str, Any]] | None = None,
    horizon: int = 5,
    dt: float = 0.1,
    model: KinematicBicycleModel | None = None,
) -> list[dict[str, float]]:
    """Build a state trajectory from a direct-state or actuator command."""
    horizon = max(1, int(horizon))
    dt = max(1e-4, _finite(dt, 0.1))
    dynamics = model or KinematicBicycleModel()
    current_state = VehicleState.from_mapping(current)
    points = list(trajectory or [])
    output: list[dict[str, float]] = []

    if points:
        for point in points[:horizon]:
            current_state = _direct_state(current_state, point, dt)
            output.append(current_state.as_mapping())

    command_mode = str(mode or "state").strip().lower()
    state_values = state or {}
    actuator_values = actuators or {}
    while len(output) < horizon:
        if command_mode == "actuator":
            current_state = dynamics.step(
                current_state,
                throttle=actuator_values.get("throttle", 0.0),
                brake=actuator_values.get("brake", 0.0),
                steering=actuator_values.get("steering", actuator_values.get("steer", 0.0)),
                dt=dt,
            )
        elif not output:
            current_state = _direct_state(current_state, state_values, dt)
        else:
            current_state = _direct_state(
                current_state,
                {"heading": current_state.heading, "acceleration": current_state.acceleration},
                dt,
            )
        output.append(current_state.as_mapping())
    return output
