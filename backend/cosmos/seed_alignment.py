"""Strict state contracts between Transfer world seeds and OmniDreams traffic."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


SEED_ALIGNMENT_TERMINAL_CONTINUE = "terminal_continue"
SEED_ALIGNMENT_OPENING_RESTART = "opening_restart"
SEED_ALIGNMENT_MODES = {
    SEED_ALIGNMENT_TERMINAL_CONTINUE,
    SEED_ALIGNMENT_OPENING_RESTART,
}


def normalize_seed_alignment_mode(value: Any) -> str:
    normalized = str(value or SEED_ALIGNMENT_TERMINAL_CONTINUE).strip().lower()
    aliases = {
        "terminal": SEED_ALIGNMENT_TERMINAL_CONTINUE,
        "continue": SEED_ALIGNMENT_TERMINAL_CONTINUE,
        "endpoint": SEED_ALIGNMENT_TERMINAL_CONTINUE,
        "terminal_continue": SEED_ALIGNMENT_TERMINAL_CONTINUE,
        "opening": SEED_ALIGNMENT_OPENING_RESTART,
        "restart": SEED_ALIGNMENT_OPENING_RESTART,
        "first_frame": SEED_ALIGNMENT_OPENING_RESTART,
        "opening_restart": SEED_ALIGNMENT_OPENING_RESTART,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(SEED_ALIGNMENT_MODES))
        raise ValueError(
            f"Unsupported world seed alignment mode {value!r}; expected {choices}"
        ) from exc


def frame_actor_map(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actors: dict[str, dict[str, Any]] = {}
    ego = frame.get("ego")
    if isinstance(ego, dict) and ego.get("id") is not None:
        actors[str(ego["id"])] = ego
    for key in ("actors", "vehicles", "cyclists", "pedestrians"):
        for actor in frame.get(key) or []:
            if isinstance(actor, dict) and actor.get("id") is not None:
                actors[str(actor["id"])] = actor
    return actors


def _wrapped_heading_error(first: float, second: float) -> float:
    return abs((float(first) - float(second) + math.pi) % (2.0 * math.pi) - math.pi)


def _state_fingerprint(actors: dict[str, dict[str, Any]]) -> str:
    canonical = [
        {
            "id": actor_id,
            "x": round(float(actor.get("x", 0.0)), 8),
            "y": round(float(actor.get("y", 0.0)), 8),
            "heading": round(float(actor.get("heading", 0.0)), 8),
            "speed": round(float(actor.get("speed", 0.0)), 8),
        }
        for actor_id, actor in sorted(actors.items())
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def audit_seed_traffic_boundary(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    alignment_mode: str,
    position_tolerance_m: float = 1e-4,
    heading_tolerance_rad: float = 1e-5,
    speed_tolerance_mps: float = 1e-4,
) -> dict[str, Any]:
    """Verify that the RGB seed boundary and operational traffic share one state."""
    mode = normalize_seed_alignment_mode(alignment_mode)
    expected_actors = frame_actor_map(expected)
    actual_actors = frame_actor_map(actual)
    expected_ids = set(expected_actors)
    actual_ids = set(actual_actors)
    missing = sorted(expected_ids - actual_ids)
    added = sorted(actual_ids - expected_ids)
    comparisons = []
    violations = []
    for actor_id in sorted(expected_ids & actual_ids):
        lhs = expected_actors[actor_id]
        rhs = actual_actors[actor_id]
        position_error = math.hypot(
            float(lhs.get("x", 0.0)) - float(rhs.get("x", 0.0)),
            float(lhs.get("y", 0.0)) - float(rhs.get("y", 0.0)),
        )
        heading_error = _wrapped_heading_error(
            lhs.get("heading", 0.0), rhs.get("heading", 0.0)
        )
        speed_error = abs(
            float(lhs.get("speed", 0.0)) - float(rhs.get("speed", 0.0))
        )
        item = {
            "id": actor_id,
            "position_error_m": round(position_error, 9),
            "heading_error_rad": round(heading_error, 9),
            "speed_error_mps": round(speed_error, 9),
        }
        comparisons.append(item)
        if (
            position_error > position_tolerance_m
            or heading_error > heading_tolerance_rad
            or speed_error > speed_tolerance_mps
        ):
            violations.append(item)
    expected_ego = str((expected.get("ego") or {}).get("id") or "")
    actual_ego = str((actual.get("ego") or {}).get("id") or "")
    passed = (
        bool(expected_actors)
        and not missing
        and not added
        and not violations
        and expected_ego == actual_ego
    )
    return {
        "schema": "denseworld.seed-traffic-alignment.v1",
        "passed": passed,
        "alignment_mode": mode,
        "expected_boundary": (
            "transfer_frame_0_and_traffic_opening"
            if mode == SEED_ALIGNMENT_OPENING_RESTART
            else "transfer_terminal_frame_and_warmup_endpoint"
        ),
        "expected_sim_time": expected.get("sim_time"),
        "actual_sim_time": actual.get("sim_time"),
        "expected_ego_id": expected_ego,
        "actual_ego_id": actual_ego,
        "expected_actor_ids": sorted(expected_ids),
        "actual_actor_ids": sorted(actual_ids),
        "missing_actor_ids": missing,
        "unexpected_actor_ids": added,
        "violations": violations,
        "max_position_error_m": max(
            (float(item["position_error_m"]) for item in comparisons), default=0.0
        ),
        "max_heading_error_rad": max(
            (float(item["heading_error_rad"]) for item in comparisons), default=0.0
        ),
        "max_speed_error_mps": max(
            (float(item["speed_error_mps"]) for item in comparisons), default=0.0
        ),
        "expected_state_sha256": _state_fingerprint(expected_actors),
        "actual_state_sha256": _state_fingerprint(actual_actors),
        "position_tolerance_m": position_tolerance_m,
        "heading_tolerance_rad": heading_tolerance_rad,
        "speed_tolerance_mps": speed_tolerance_mps,
    }
