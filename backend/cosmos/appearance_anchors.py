"""Map-specific RGB appearance anchors for geometry-controlled world seeds."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "cosmos"
    / "appearance_anchors"
    / "catalog.json"
)


def _angle_error(first: float, second: float) -> float:
    return abs((float(first) - float(second) + math.pi) % (2.0 * math.pi) - math.pi)


def load_appearance_anchors(
    map_path: str | Path,
    catalog_path: str | Path = DEFAULT_CATALOG,
) -> list[dict[str, Any]]:
    """Load anchors whose configured map suffix matches ``map_path``."""
    catalog_path = Path(catalog_path).expanduser().resolve()
    if not catalog_path.is_file():
        return []
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    normalized_map = str(map_path).replace("\\", "/")
    for entry in payload.get("maps") or []:
        map_suffix = str(entry.get("map_suffix") or "").replace("\\", "/")
        if not map_suffix or not normalized_map.endswith(map_suffix):
            continue
        anchors = []
        for raw in entry.get("anchors") or []:
            image_path = (catalog_path.parent / str(raw.get("image") or "")).resolve()
            control_path = (catalog_path.parent / str(raw.get("control") or "")).resolve()
            if not image_path.is_file() or not control_path.is_file():
                continue
            anchors.append(
                {
                    **raw,
                    "id": str(raw.get("id") or image_path.stem),
                    "x": float(raw["x"]),
                    "y": float(raw["y"]),
                    "heading": float(raw["heading"]),
                    "max_position_error_m": float(raw.get("max_position_error_m", 3.0)),
                    "max_heading_error_deg": float(raw.get("max_heading_error_deg", 8.0)),
                    "image_path": str(image_path),
                    "control_path": str(control_path),
                }
            )
        return anchors
    return []


def select_pose_matched_anchor(
    vehicles: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    *,
    seed: int,
) -> dict[str, Any] | None:
    """Randomly choose a valid anchor pose, then bind its nearest motorized actor."""
    matches: list[dict[str, Any]] = []
    for anchor in anchors:
        nearest: dict[str, Any] | None = None
        for vehicle in vehicles:
            actor_type = str(
                vehicle.get("road_user_type") or vehicle.get("type") or "vehicle"
            ).lower()
            if actor_type in {"pedestrian", "cyclist", "non_motorized", "bicycle"}:
                continue
            position_error = math.hypot(
                float(vehicle.get("x", 0.0)) - float(anchor["x"]),
                float(vehicle.get("y", 0.0)) - float(anchor["y"]),
            )
            heading_error = _angle_error(
                float(vehicle.get("heading", 0.0)), float(anchor["heading"])
            )
            if position_error > float(anchor["max_position_error_m"]):
                continue
            if math.degrees(heading_error) > float(anchor["max_heading_error_deg"]):
                continue
            score = position_error + heading_error * 3.0
            candidate = {
                "actor_id": vehicle.get("id"),
                "anchor": dict(anchor),
                "position_error_m": position_error,
                "heading_error_deg": math.degrees(heading_error),
                "score": score,
            }
            if nearest is None or score < float(nearest["score"]):
                nearest = candidate
        if nearest is not None:
            matches.append(nearest)
    if not matches:
        return None
    matches.sort(key=lambda item: (str(item["anchor"]["id"]), str(item["actor_id"])))
    selected = random.Random(int(seed) ^ 0xD35E).choice(matches)
    selected["candidate_count"] = len(matches)
    return selected
