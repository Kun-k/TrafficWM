"""Build one persisted audit for traffic, AV, Transfer, and Dreams outputs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ego(frame: dict[str, Any], ego_id: str = "") -> dict[str, Any]:
    value = frame.get("ego")
    if isinstance(value, dict) and (not ego_id or str(value.get("id")) == ego_id):
        return value
    for vehicle in frame.get("vehicles") or []:
        if str(vehicle.get("id")) == ego_id:
            return vehicle
    return {}


def _state_matches(left: dict[str, Any], right: dict[str, Any], tolerance: float = 0.01) -> bool:
    if not left or not right or str(left.get("id")) != str(right.get("id")):
        return False
    return all(
        math.isclose(float(left.get(key, 0.0)), float(right.get(key, 0.0)), abs_tol=tolerance)
        for key in ("x", "y", "heading", "speed")
    )


def _qa_summary(report: dict[str, Any]) -> dict[str, Any]:
    views = list(report.get("views") or [])
    return {
        "passed": bool(report.get("passed")),
        "view_count": len(views),
        "frames": [int(view.get("frames", 0) or 0) for view in views],
        "fps": [float(view.get("fps", 0.0) or 0.0) for view in views],
        "blank_frames": sum(len(view.get("blank_frame_indices") or []) for view in views),
        "duplicate_transitions": sum(len(view.get("duplicate_transition_indices") or []) for view in views),
        "discontinuity_transitions": sum(
            len(view.get("discontinuity_transition_indices") or []) for view in views
        ),
    }


def audit_joint_flow(
    pipeline_root: Path,
    av_report_path: Path,
    warmup_frames_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    pipeline_root = pipeline_root.resolve()
    traffic_path = pipeline_root / "operational_traffic.json"
    transfer_qa_path = pipeline_root / "qa" / "transfer_full" / "video_qa.json"
    dreams_qa_path = pipeline_root / "qa" / "omnidreams" / "video_qa.json"
    visual_path = pipeline_root / "av_stream" / "lead_tfv6_stream_audit.json"

    traffic = _read_json(traffic_path)
    warmup = _read_json(warmup_frames_path.resolve())
    av_report = _read_json(av_report_path.resolve())
    transfer_qa = _read_json(transfer_qa_path)
    dreams_qa = _read_json(dreams_qa_path)
    visual = _read_json(visual_path)
    if not isinstance(traffic, list) or len(traffic) < 2:
        raise ValueError("Operational traffic must contain at least two states")
    if not isinstance(warmup, list) or not warmup:
        raise ValueError("Warmup traffic must contain at least one state")

    ego_id = str(traffic[0].get("ego_id") or _ego(traffic[0]).get("id") or "")
    formal_start = _ego(traffic[0], ego_id)
    formal_end = _ego(traffic[-1], ego_id)
    warmup_end = _ego(warmup[-1], ego_id)
    duration = float(traffic[-1].get("sim_time", 0.0) or 0.0)
    expected_commands = int(round(duration / 0.1))
    displacement = math.hypot(
        float(formal_end.get("x", 0.0)) - float(formal_start.get("x", 0.0)),
        float(formal_end.get("y", 0.0)) - float(formal_start.get("y", 0.0)),
    )
    transfer = _qa_summary(transfer_qa)
    dreams = _qa_summary(dreams_qa)
    checks = {
        "warmup_terminal_equals_formal_t0": _state_matches(warmup_end, formal_start),
        "formal_time_starts_at_zero": math.isclose(
            float(traffic[0].get("sim_time", -1.0)), 0.0, abs_tol=1e-6
        ),
        "formal_traffic_is_10hz": len(traffic) == expected_commands + 1,
        "av_identity_matches_camera_ego": bool(
            ego_id
            and str(av_report.get("av_id")) == ego_id
            and str(av_report.get("world_ego_id")) == ego_id
            and av_report.get("camera_matches_av")
        ),
        "av_command_for_every_formal_step": bool(
            int(av_report.get("perception_frames", 0) or 0) == expected_commands
            and int(av_report.get("command_frames", 0) or 0) == expected_commands
            and int(av_report.get("timeout_frames", 0) or 0) == 0
        ),
        "transfer_seven_view_video_passed": bool(
            transfer["passed"]
            and transfer["view_count"] == 7
            and all(frame == expected_commands for frame in transfer["frames"])
            and all(math.isclose(fps, 10.0, abs_tol=0.01) for fps in transfer["fps"])
        ),
        "dreams_front_video_passed": bool(
            dreams["passed"]
            and dreams["view_count"] == 1
            and dreams["frames"] == [int(round(duration * 30.0))]
            and all(math.isclose(fps, 30.0, abs_tol=0.01) for fps in dreams["fps"])
        ),
        "dreams_rgb_bev_stream_ready": bool(visual.get("rgb_bev_stream_ready")),
    }
    report = {
        "schema": "denseworld.joint-flow-audit.v1",
        "experiment_id": pipeline_root.name,
        "passed": all(checks.values()),
        "checks": checks,
        "timeline": {
            "warmup_seconds": 1.0,
            "formal_duration_seconds": duration,
            "formal_states": len(traffic),
            "formal_start": formal_start,
            "formal_end": formal_end,
            "ego_displacement_m": round(displacement, 4),
        },
        "av": {
            "model": av_report.get("model"),
            "command_mode": av_report.get("command_mode"),
            "perception_frames": av_report.get("perception_frames"),
            "command_frames": av_report.get("command_frames"),
            "timeout_frames": av_report.get("timeout_frames"),
            "latency_ms": av_report.get("latency_ms"),
            "safety_approximate_fallback_count": av_report.get(
                "safety_approximate_fallback_count", 0
            ),
        },
        "transfer": transfer,
        "dreams": dreams,
        "visual_av": {
            "algorithm": visual.get("algorithm"),
            "rgb_bev_stream_ready": visual.get("rgb_bev_stream_ready"),
            "full_tfv6_contract_met": visual.get("full_tfv6_contract_met"),
            "tfv6_inference_executed": visual.get("tfv6_inference_executed"),
            "missing_inputs": visual.get("missing_inputs") or [],
            "limitation": visual.get("limitation"),
        },
        "sources": {
            "traffic": str(traffic_path),
            "warmup": str(warmup_frames_path.resolve()),
            "av_report": str(av_report_path.resolve()),
            "transfer_qa": str(transfer_qa_path),
            "dreams_qa": str(dreams_qa_path),
            "visual_stream_audit": str(visual_path),
        },
    }
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline-root", type=Path, required=True)
    parser.add_argument("--av-report", type=Path, required=True)
    parser.add_argument("--warmup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_joint_flow(args.pipeline_root, args.av_report, args.warmup, args.output)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
