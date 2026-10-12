"""Shared RDS-HQ camera calibration for Transfer2.5 and OmniDreams."""
from __future__ import annotations

import io
import json
import math
import os
import tarfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np


REFERENCE_CAMERA_RIG_ID = "2d23a1f4-c269-46aa-8e7d-1bb595d1e421_2445376400000_2445396400000"
DEFAULT_CAMERA_RIG_PATH = Path(__file__).resolve().parents[2] / "assets" / "cosmos" / "rds_hq_camera_rig.json"
DEFAULT_FTHETA_INTRINSICS = Path(
    "/mnt/rk/cosmos/cosmos_transfer2.5/cosmos-transfer2.5/"
    "cosmos_transfer2/_src/imaginaire/auxiliary/world_scenario/"
    "dataloaders/default_ftheta_intrinsic.tar"
)


def default_ftheta_intrinsics_path() -> Path:
    return Path(os.environ.get("COSMOS_FTHETA_INTRINSICS", str(DEFAULT_FTHETA_INTRINSICS))).resolve()


def default_camera_rig_path() -> Path:
    return Path(os.environ.get("COSMOS_RDS_HQ_CAMERA_RIG", str(DEFAULT_CAMERA_RIG_PATH))).resolve()


def _load_tar_array(path: Path, suffix: str) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"Camera calibration archive not found: {path}")
    with tarfile.open(path, "r") as archive:
        member = next(
            (item for item in archive.getmembers() if item.isfile() and item.name.endswith(suffix)),
            None,
        )
        if member is None:
            raise KeyError(f"Camera calibration member '*{suffix}' not found in {path}")
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(f"Cannot read {member.name} from {path}")
        return np.load(io.BytesIO(stream.read()), allow_pickle=False)


@lru_cache(maxsize=16)
def _official_ftheta(camera_name: str, source_value: str) -> tuple[float, ...]:
    values = np.asarray(
        _load_tar_array(Path(source_value), f".ftheta_intrinsic.{camera_name}.npy"),
        dtype=np.float64,
    ).reshape(-1)
    if values.size < 11:
        raise ValueError(
            f"Invalid f-theta calibration for {camera_name}: expected at least 11 values, got {values.size}"
        )
    return tuple(float(value) for value in values)


@lru_cache(maxsize=16)
def _official_camera_to_vehicle(camera_name: str, rig_path_value: str) -> tuple[tuple[float, ...], ...]:
    rig_path = Path(rig_path_value)
    if not rig_path.is_file():
        raise FileNotFoundError(f"RDS-HQ camera rig is unavailable: {rig_path}")
    payload = json.loads(rig_path.read_text(encoding="utf-8"))
    try:
        matrix = np.asarray(payload["camera_to_vehicle_flu"][camera_name], dtype=np.float64)
    except KeyError as exc:
        raise KeyError(f"Camera {camera_name!r} is missing from {rig_path}") from exc
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError(f"Invalid RDS-HQ camera pose for {camera_name}")
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _rescale_ftheta(values: tuple[float, ...], width: int, height: int) -> list[float]:
    source_width = float(values[2])
    source_height = float(values[3])
    if source_width <= 0.0 or source_height <= 0.0:
        raise ValueError("F-theta source dimensions must be positive")
    ratio_w = float(width) / source_width
    ratio_h = float(height) / source_height
    average_ratio = math.sqrt(ratio_w * ratio_h)
    polynomial = list(values[4:10])
    is_backward = bool(round(values[10]))
    if is_backward:
        polynomial = [coefficient * (1.0 / average_ratio) ** index for index, coefficient in enumerate(polynomial)]
    else:
        polynomial = [coefficient * average_ratio for coefficient in polynomial]
    linear_cde = list(values[11:14]) if len(values) >= 14 else [1.0, 0.0, 0.0]
    return [
        values[0] * ratio_w,
        values[1] * ratio_h,
        float(width),
        float(height),
        *polynomial,
        1.0 if is_backward else 0.0,
        *linear_cde,
    ]


def _matrix_to_rpy_degrees(rotation: np.ndarray) -> list[float]:
    pitch = math.asin(max(-1.0, min(1.0, -float(rotation[2, 0]))))
    if abs(math.cos(pitch)) > 1e-8:
        roll = math.atan2(float(rotation[2, 1]), float(rotation[2, 2]))
        yaw = math.atan2(float(rotation[1, 0]), float(rotation[0, 0]))
    else:
        roll = math.atan2(-float(rotation[1, 2]), float(rotation[1, 1]))
        yaw = 0.0
    return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]


def _matrix_to_quaternion(rotation: np.ndarray) -> dict[str, float]:
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    else:
        diagonal = np.diag(rotation)
        axis = int(np.argmax(diagonal))
        if axis == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            w = (rotation[2, 1] - rotation[1, 2]) / scale
            x = 0.25 * scale
            y = (rotation[0, 1] + rotation[1, 0]) / scale
            z = (rotation[0, 2] + rotation[2, 0]) / scale
        elif axis == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            w = (rotation[0, 2] - rotation[2, 0]) / scale
            x = (rotation[0, 1] + rotation[1, 0]) / scale
            y = 0.25 * scale
            z = (rotation[1, 2] + rotation[2, 1]) / scale
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            w = (rotation[1, 0] - rotation[0, 1]) / scale
            x = (rotation[0, 2] + rotation[2, 0]) / scale
            y = (rotation[1, 2] + rotation[2, 1]) / scale
            z = 0.25 * scale
    return {"w": float(w), "x": float(x), "y": float(y), "z": float(z)}


def camera_calibration(camera_name: str, width: int, height: int) -> dict[str, Any]:
    if width <= 0 or height <= 0:
        raise ValueError("Camera output dimensions must be positive")
    ftheta_source = default_ftheta_intrinsics_path()
    rig_path = default_camera_rig_path()
    intrinsics = _rescale_ftheta(
        _official_ftheta(camera_name, str(ftheta_source)),
        int(width),
        int(height),
    )
    matrix = np.asarray(
        _official_camera_to_vehicle(camera_name, str(rig_path)),
        dtype=np.float64,
    )
    return {
        "schema": "denseworld.rds-hq-camera-calibration.v1",
        "camera_name": camera_name,
        "width": int(width),
        "height": int(height),
        "ftheta": {
            "principal_point": intrinsics[:2],
            "polynomial": intrinsics[4:10],
            "is_backward": bool(round(intrinsics[10])),
            "linear_cde": intrinsics[11:14],
            "array": intrinsics,
            "source": str(ftheta_source),
        },
        "camera_to_vehicle_flu": {
            "matrix": matrix.tolist(),
            "translation": matrix[:3, 3].tolist(),
            "rpy_degrees": _matrix_to_rpy_degrees(matrix[:3, :3]),
            "quaternion": _matrix_to_quaternion(matrix[:3, :3]),
            "source": str(rig_path),
            "source_example_id": REFERENCE_CAMERA_RIG_ID,
        },
    }


def omnidreams_camera_calibration(
    camera_name: str,
    width: int,
    height: int,
    *,
    fov_degrees: float = 120.0,
) -> dict[str, Any]:
    """Return the official RDS-HQ camera domain used by the Transfer seed.

    OmniDreams accepts both forward and backward f-theta polynomials over gRPC.
    Reusing the Transfer calibration is required because the generated seed and
    every runtime HD-map projection must occupy the same pixel coordinate frame.
    """
    if not 1.0 < float(fov_degrees) < 179.0:
        raise ValueError("OmniDreams camera FOV must be between 1 and 179 degrees")
    calibration = camera_calibration(camera_name, width, height)
    calibration.update(
        {
            "schema": "denseworld.omnidreams-camera-calibration.v1",
            "projection_domain": "official-rds-hq",
            "mount_domain": "official-rds-hq",
            "fov_degrees": float(fov_degrees),
        }
    )
    return calibration
