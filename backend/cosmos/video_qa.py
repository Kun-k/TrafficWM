"""Objective temporal checks and visual contact sheets for generated driving videos."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def analyze_video(
    path: Path,
    expected_duration: float = 0.0,
    expected_fps: float = 0.0,
    quality_profile: str = "",
) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {"path": str(path), "passed": False, "errors": ["video cannot be opened"]}
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_count = 0
    blank_indices: list[int] = []
    diffs: list[float] = []
    luminance: list[float] = []
    sharpness: list[float] = []
    saturated_pixel_ratios: list[float] = []
    mean_saturation: list[float] = []
    chroma_edge_energy: list[float] = []
    lane_marking_scores: list[float] = []
    upper_lower_luminance_ratios: list[float] = []
    flow_magnitudes: list[float] = []
    histogram_distances: list[float] = []
    semantic_visible_pixel_ratios: list[float] = []
    previous = None
    previous_histogram = None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        small_color = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small_color, cv2.COLOR_BGR2GRAY)
        small = gray
        semantic_visible_ratio = float(np.mean(np.max(small_color, axis=2) > 24))
        semantic_visible_pixel_ratios.append(semantic_visible_ratio)
        hsv = cv2.cvtColor(small_color, cv2.COLOR_BGR2HSV)
        mean_saturation.append(float(np.mean(hsv[:, :, 1])) / 255.0)
        saturated_pixel_ratios.append(
            float(np.mean((hsv[:, :, 1] >= 220) & (hsv[:, :, 2] >= 64)))
        )
        lab = cv2.cvtColor(small_color, cv2.COLOR_BGR2LAB)
        chroma_edge_energy.append(
            float(
                (
                    cv2.Laplacian(lab[:, :, 1], cv2.CV_64F).var()
                    + cv2.Laplacian(lab[:, :, 2], cv2.CV_64F).var()
                )
                / 2.0
            )
        )
        frame_height, frame_width = small_color.shape[:2]
        upper_luminance = float(np.mean(small[: int(0.5 * frame_height)]))
        lower_luminance = float(
            np.mean(small[int(0.5 * frame_height) : int(0.875 * frame_height)])
        )
        upper_lower_luminance_ratios.append(
            upper_luminance / max(lower_luminance, 1e-6)
        )
        road_roi = small_color[
            int(0.53 * frame_height) : int(0.95 * frame_height),
            int(0.075 * frame_width) : int(0.925 * frame_width),
        ]
        road_hsv = cv2.cvtColor(road_roi, cv2.COLOR_BGR2HSV)
        road_value = road_hsv[:, :, 2]
        marking_value_threshold = max(
            70.0,
            float(np.percentile(road_value, 72)),
        )
        light_markings = np.where(
            (road_hsv[:, :, 1] < 100)
            & (road_value >= marking_value_threshold),
            255,
            0,
        ).astype(np.uint8)
        light_markings = cv2.morphologyEx(
            light_markings,
            cv2.MORPH_OPEN,
            np.ones((2, 2), dtype=np.uint8),
        )
        marking_edges = cv2.Canny(light_markings, 40, 120)
        marking_lines = cv2.HoughLinesP(
            marking_edges,
            1,
            np.pi / 180.0,
            12,
            minLineLength=14,
            maxLineGap=8,
        )
        marking_length = 0.0
        if marking_lines is not None:
            for x1, y1, x2, y2 in marking_lines[:, 0]:
                slope = abs(float(y2 - y1)) / max(1.0, abs(float(x2 - x1)))
                if slope > 0.12:
                    marking_length += math.hypot(float(x2 - x1), float(y2 - y1))
        lane_marking_scores.append(
            100.0 * marking_length / max(1.0, float(road_roi.shape[0] * road_roi.shape[1]))
        )
        mean, stddev = cv2.meanStdDev(small)
        luminance.append(float(mean[0, 0]))
        sharpness.append(float(cv2.Laplacian(small, cv2.CV_64F).var()))
        if quality_profile in {"semantic_control", "semantic_control_stationary"}:
            is_blank = semantic_visible_ratio < 0.0005
        else:
            is_blank = (
                float(stddev[0, 0]) < 2.5
                or float(mean[0, 0]) < 1.5
                or float(mean[0, 0]) > 253.5
            )
        if is_blank:
            blank_indices.append(frame_count)
        if previous is not None:
            diffs.append(float(cv2.absdiff(previous, small).mean()))
            flow = cv2.calcOpticalFlowFarneback(previous, small, None, 0.5, 2, 11, 2, 5, 1.1, 0)
            flow_magnitudes.append(float(np.median(np.linalg.norm(flow, axis=2))))
        histogram = cv2.calcHist([small], [0], None, [32], [0, 256])
        histogram = cv2.normalize(
            histogram,
            None,
            alpha=1.0,
            beta=0.0,
            norm_type=cv2.NORM_L1,
        )
        if previous_histogram is not None:
            histogram_distances.append(
                float(
                    cv2.compareHist(
                        previous_histogram,
                        histogram,
                        cv2.HISTCMP_BHATTACHARYYA,
                    )
                )
            )
        previous = small
        previous_histogram = histogram
        frame_count += 1
    capture.release()

    duration = frame_count / fps if fps > 0 else 0.0
    diff_array = np.asarray(diffs, dtype=np.float64)
    if diff_array.size:
        median = float(np.median(diff_array))
        mad = float(np.median(np.abs(diff_array - median)))
        p95 = float(np.percentile(diff_array, 95))
        threshold = max(12.0, median + 6.0 * max(mad, 0.2), p95 * 1.5)
        raw_discontinuities = np.where(diff_array > threshold)[0].astype(int).tolist()
        episodes: list[tuple[int, int]] = []
        for index in raw_discontinuities:
            if not episodes or index > episodes[-1][1] + 1:
                episodes.append((index, index))
            else:
                episodes[-1] = (episodes[-1][0], index)
        flow_array = np.asarray(flow_magnitudes, dtype=np.float64)
        histogram_array = np.asarray(histogram_distances, dtype=np.float64)
        discontinuities = []
        high_motion_transitions = []
        motion_floor = max(4.0, threshold * 0.65)
        for start, end in episodes:
            window_start = max(0, start - 2)
            window_end = min(diff_array.size, end + 3)
            local_diffs = diff_array[window_start:window_end]
            local_flows = flow_array[window_start:window_end]
            episode_histograms = histogram_array[start : end + 1]
            sustained_motion = int(np.count_nonzero(local_diffs >= motion_floor)) >= 3
            coherent_flow = bool(local_flows.size) and float(np.median(local_flows)) >= 0.75
            stable_appearance = (
                not episode_histograms.size
                or float(episode_histograms.max()) < 0.16
            )
            if sustained_motion and coherent_flow and stable_appearance:
                high_motion_transitions.append(start)
            else:
                discontinuities.append(start)
        # Low-texture control renders legitimately have tiny deltas. Encoded
        # cloned frames decode identically, so exact equality is the reliable
        # freeze signal across both line renders and photorealistic videos.
        duplicate_indices = np.where(diff_array <= 1e-6)[0].astype(int).tolist()
    else:
        median, mad, p95, threshold, discontinuities, duplicate_indices = 0.0, 0.0, 0.0, 12.0, [], []
        high_motion_transitions = []
        histogram_array = np.asarray(histogram_distances, dtype=np.float64)
    errors = []
    ignored_conditioning_handoffs: list[int] = []
    marginal_discontinuities: list[int] = []
    evaluated_discontinuities = list(discontinuities)
    conditioning_handoff = {
        "generated_driving_i2v_window": 0,
        "generated_driving_i2v5_window": 4,
    }.get(quality_profile)
    if conditioning_handoff is not None and conditioning_handoff in evaluated_discontinuities:
        ignored_conditioning_handoffs = [conditioning_handoff]
        evaluated_discontinuities = [
            index for index in evaluated_discontinuities if index != conditioning_handoff
        ]
    if declared_frames and declared_frames != frame_count:
        errors.append(f"decoded frame count {frame_count} differs from container count {declared_frames}")
    if expected_fps and abs(fps - expected_fps) > 0.02:
        errors.append(f"fps {fps:.4f} differs from expected {expected_fps:.4f}")
    if expected_duration and abs(duration - expected_duration) > max(0.05, 1.1 / max(fps, 1.0)):
        errors.append(f"duration {duration:.4f}s differs from expected {expected_duration:.4f}s")
    if blank_indices:
        errors.append(f"detected {len(blank_indices)} blank or near-uniform frames")
    if (
        quality_profile != "semantic_control_stationary"
        and len(duplicate_indices) > max(1, int(0.05 * max(1, frame_count - 1)))
    ):
        errors.append(f"duplicate frame ratio is {len(duplicate_indices) / max(1, frame_count - 1):.3f}")
    if len(evaluated_discontinuities) > max(1, int(0.02 * max(1, frame_count - 1))):
        errors.append(f"detected {len(evaluated_discontinuities)} temporal discontinuities")
    luminance_array = np.asarray(luminance, dtype=np.float64)
    luminance_delta_p95 = (
        float(np.percentile(np.abs(np.diff(luminance_array)), 95))
        if luminance_array.size > 1
        else 0.0
    )
    sharpness_array = np.asarray(sharpness, dtype=np.float64)
    quartile = max(1, sharpness_array.size // 4)
    sharpness_head = float(np.median(sharpness_array[:quartile])) if sharpness_array.size else 0.0
    sharpness_tail = float(np.median(sharpness_array[-quartile:])) if sharpness_array.size else 0.0
    sharpness_ratio = sharpness_tail / max(sharpness_head, 1e-9)
    sparse_semantic_control = bool(
        quality_profile == "semantic_control"
        and semantic_visible_pixel_ratios
        and min(semantic_visible_pixel_ratios) >= 0.0005
        and float(np.median(semantic_visible_pixel_ratios)) <= 0.015
        and not evaluated_discontinuities
    )
    suppressed_sparse_control_sharpness = bool(
        frame_count >= 40
        and sharpness_head >= 25.0
        and sharpness_ratio < 0.35
        and sparse_semantic_control
    )
    if (
        frame_count >= 40
        and sharpness_head >= 25.0
        and sharpness_ratio < 0.35
        and not sparse_semantic_control
    ):
        errors.append(f"tail sharpness retained only {sharpness_ratio:.3f} of the opening segment")
    saturated_array = np.asarray(saturated_pixel_ratios, dtype=np.float64)
    saturated_median = float(np.median(saturated_array)) if saturated_array.size else 0.0
    saturated_p95 = (
        float(np.percentile(saturated_array, 95)) if saturated_array.size else 0.0
    )
    mean_saturation_array = np.asarray(mean_saturation, dtype=np.float64)
    mean_saturation_median = (
        float(np.median(mean_saturation_array)) if mean_saturation_array.size else 0.0
    )
    chroma_edge_array = np.asarray(chroma_edge_energy, dtype=np.float64)
    chroma_edge_median = float(np.median(chroma_edge_array)) if chroma_edge_array.size else 0.0
    chroma_edge_p95 = (
        float(np.percentile(chroma_edge_array, 95)) if chroma_edge_array.size else 0.0
    )
    lane_marking_array = np.asarray(lane_marking_scores, dtype=np.float64)
    lane_marking_median = float(np.median(lane_marking_array)) if lane_marking_array.size else 0.0
    composition_array = np.asarray(upper_lower_luminance_ratios, dtype=np.float64)
    semantic_visible_array = np.asarray(
        semantic_visible_pixel_ratios, dtype=np.float64
    )
    upper_occlusion_mask = composition_array < 0.55
    upper_occlusion_longest_run = 0
    current_run = 0
    for occluded in upper_occlusion_mask:
        current_run = current_run + 1 if bool(occluded) else 0
        upper_occlusion_longest_run = max(upper_occlusion_longest_run, current_run)
    warnings = []
    if suppressed_sparse_control_sharpness:
        warnings.append(
            "tail sharpness decay is ignored for a continuous nonblank sparse semantic-control view"
        )
    if (
        quality_profile == "semantic_control_stationary"
        and len(duplicate_indices) > max(1, int(0.05 * max(1, frame_count - 1)))
    ):
        warnings.append(
            "duplicate semantic-control frames are expected for a verified stationary ego"
        )
    if quality_profile in {
        "generated_driving",
        "generated_driving_seed",
        "generated_driving_i2v_window",
        "generated_driving_i2v5_window",
    }:
        if ignored_conditioning_handoffs:
            warnings.append(
                "I2V conditioning handoff is excluded from mid-window discontinuity checks "
                f"at transition {ignored_conditioning_handoffs[0]}"
            )
        if evaluated_discontinuities:
            if len(evaluated_discontinuities) == 1:
                index = evaluated_discontinuities[0]
                histogram_distance = (
                    float(histogram_array[index])
                    if 0 <= index < histogram_array.size
                    else math.inf
                )
                if (
                    0 <= index < diff_array.size
                    and float(diff_array[index]) <= threshold * 1.05
                    and histogram_distance < 0.08
                ):
                    marginal_discontinuities = [index]
            if marginal_discontinuities:
                warnings.append(
                    "generated driving contains one marginal temporal-difference "
                    f"outlier at transition {marginal_discontinuities[0]}"
                )
            else:
                errors.append(
                    "generated driving video contains "
                    f"{len(evaluated_discontinuities)} temporal discontinuities"
                )
        # A route can naturally leave a highly textured city block for an open road.
        # Treat relative decay as model blur only when the tail is also soft in
        # absolute terms; the minimum guard still catches short collapsed spans.
        if (
            frame_count >= 120
            and sharpness_head >= 25.0
            and sharpness_ratio < 0.6
            and (sharpness_tail < 180.0 or float(sharpness_array.min()) < 140.0)
        ):
            errors.append(
                f"generated driving tail sharpness retained only {sharpness_ratio:.3f} of the opening segment"
            )
        if saturated_median > 0.45:
            errors.append(
                f"generated driving saturated-pixel ratio is implausibly high ({saturated_median:.3f})"
            )
        chroma_artifacts = chroma_edge_median > 80.0 or chroma_edge_p95 > 120.0
        elevated_chroma = chroma_edge_median > 45.0 or chroma_edge_p95 > 70.0
        if mean_saturation_median > 0.58:
            errors.append(
                f"generated driving mean saturation is implausibly high ({mean_saturation_median:.3f})"
            )
        elif mean_saturation_median > 0.43:
            message = (
                "generated driving mean saturation is elevated "
                f"({mean_saturation_median:.3f})"
            )
            (errors if elevated_chroma else warnings).append(message)
        if saturated_p95 > 0.10:
            if chroma_artifacts or saturated_median > 0.20:
                errors.append(
                    "generated driving high-saturation artifacts are excessive "
                    f"(pixel p95={saturated_p95:.3f}, mean={mean_saturation_median:.3f})"
                )
            else:
                warnings.append(
                    "generated driving contains a large coherent high-saturation region "
                    f"(pixel p95={saturated_p95:.3f}, mean={mean_saturation_median:.3f})"
                )
        elif saturated_p95 > 0.02:
            message = (
                "generated driving high-saturation pixel ratio is elevated "
                f"(p95={saturated_p95:.3f})"
            )
            (errors if chroma_artifacts else warnings).append(message)
        if chroma_artifacts:
            errors.append(
                "generated driving chroma-edge energy indicates color-fringing artifacts "
                f"(median={chroma_edge_median:.1f}, p95={chroma_edge_p95:.1f})"
            )
        if "front_wide" in path.stem.lower() and lane_marking_median < 0.18:
            warnings.append(
                "front-wide lane-marking visibility is too low "
                f"({lane_marking_median:.3f}); this is an image heuristic, not a Cosmos score"
            )
        minimum_occlusion_run = max(15, int(math.ceil(0.05 * frame_count)))
        if frame_count >= 120 and upper_occlusion_longest_run >= minimum_occlusion_run:
            errors.append(
                "generated driving video contains sustained upper-frame occlusion "
                f"({upper_occlusion_longest_run} consecutive frames)"
            )
    if quality_profile == "generated_driving_seed":
        # Natural brick, foliage, and sky can raise mean saturation without
        # indicating malformed geometry. The general checks above still reject
        # clipped color coverage and the high-frequency chroma edges produced
        # when a semantic control palette leaks into the generated image.
        if 0.34 < mean_saturation_median <= 0.43:
            warnings.append(
                f"world-seed mean saturation is elevated ({mean_saturation_median:.3f})"
            )
        if luminance_delta_p95 > 8.0:
            errors.append(
                f"world-seed luminance flicker p95 is too high ({luminance_delta_p95:.3f})"
            )
        elif luminance_delta_p95 > 3.5:
            warnings.append(
                f"world-seed luminance variation p95 is elevated ({luminance_delta_p95:.3f})"
            )
        # Approaching a textured building can legitimately make a short side
        # view sharper. Abrupt corruption is already covered by discontinuity
        # and chroma checks, so relative sharpness growth is advisory only.
        if sharpness_ratio > 1.8:
            warnings.append(
                f"world-seed tail sharpness inflated to {sharpness_ratio:.3f} of the opening segment"
            )
    return {
        "path": str(path.resolve()),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "width": width,
        "height": height,
        "fps": round(fps, 5),
        "frames": frame_count,
        "duration_seconds": round(duration, 5),
        "quality_profile": quality_profile,
        "blank_frame_indices": blank_indices[:100],
        "duplicate_transition_indices": duplicate_indices[:100],
        "discontinuity_transition_indices": discontinuities[:100],
        "coherent_high_motion_transition_indices": high_motion_transitions[:100],
        "ignored_conditioning_handoff_indices": ignored_conditioning_handoffs,
        "marginal_discontinuity_transition_indices": marginal_discontinuities,
        "temporal_difference": {
            "median": round(median, 4),
            "mad": round(mad, 4),
            "p95": round(p95, 4),
            "maximum": round(float(diff_array.max()), 4) if diff_array.size else 0.0,
            "threshold": round(threshold, 4),
        },
        "optical_flow_magnitude": {
            "median": round(float(np.median(flow_magnitudes)), 4) if flow_magnitudes else 0.0,
            "p95": round(float(np.percentile(flow_magnitudes, 95)), 4) if flow_magnitudes else 0.0,
        },
        "histogram_distance": {
            "median": round(float(np.median(histogram_array)), 4) if histogram_array.size else 0.0,
            "p95": round(float(np.percentile(histogram_array, 95)), 4) if histogram_array.size else 0.0,
            "maximum": round(float(histogram_array.max()), 4) if histogram_array.size else 0.0,
        },
        "luminance": {
            "mean": round(float(luminance_array.mean()), 4) if luminance_array.size else 0.0,
            "frame_delta_p95": round(luminance_delta_p95, 4),
        },
        "sharpness": {
            "opening_quartile_median": round(sharpness_head, 4),
            "closing_quartile_median": round(sharpness_tail, 4),
            "retention_ratio": round(sharpness_ratio, 4),
            "minimum": round(float(sharpness_array.min()), 4) if sharpness_array.size else 0.0,
        },
        "saturation": {
            "mean_median": round(mean_saturation_median, 4),
            "high_saturation_pixel_ratio_median": round(saturated_median, 4),
            "high_saturation_pixel_ratio_p95": (
                round(saturated_p95, 4)
            ),
        },
        "chroma_edge_energy": {
            "median": round(chroma_edge_median, 4),
            "p95": round(chroma_edge_p95, 4),
            "maximum": round(float(chroma_edge_array.max()), 4) if chroma_edge_array.size else 0.0,
        },
        "road_layout": {
            "metric": "adaptive_bright_lane_marking_geometry",
            "lane_marking_geometry_median": round(lane_marking_median, 4),
            "lane_marking_geometry_p10": (
                round(float(np.percentile(lane_marking_array, 10)), 4) if lane_marking_array.size else 0.0
            ),
        },
        "scene_composition": {
            "upper_to_lower_luminance_ratio_p05": (
                round(float(np.percentile(composition_array, 5)), 4)
                if composition_array.size
                else 0.0
            ),
            "upper_occlusion_ratio_threshold": 0.55,
            "upper_occlusion_frames": int(np.count_nonzero(upper_occlusion_mask)),
            "upper_occlusion_longest_run_frames": int(upper_occlusion_longest_run),
        },
        "semantic_control": {
            "visible_pixel_ratio_minimum": (
                round(float(semantic_visible_array.min()), 6)
                if semantic_visible_array.size
                else 0.0
            ),
            "visible_pixel_ratio_median": (
                round(float(np.median(semantic_visible_array)), 6)
                if semantic_visible_array.size
                else 0.0
            ),
            "blank_ratio_threshold": 0.0005,
        },
    }


def create_contact_sheet(paths: list[Path], output: Path, columns: int = 6) -> Path:
    rows = []
    thumb_w, thumb_h = 320, 180
    for path in paths:
        capture = cv2.VideoCapture(str(path))
        count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
        frames = []
        for index in np.linspace(0, count - 1, columns).astype(int):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = capture.read()
            if not ok:
                frame = np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)
            frame = cv2.resize(frame, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
            cv2.rectangle(frame, (0, 0), (thumb_w, 25), (15, 23, 42), -1)
            cv2.putText(frame, f"{path.stem}  f{index}", (7, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (248, 250, 252), 1, cv2.LINE_AA)
            frames.append(frame)
        capture.release()
        rows.append(np.hstack(frames))
    sheet = np.vstack(rows) if rows else np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise OSError(f"Failed to write contact sheet: {output}")
    return output


def analyze_group(
    paths: list[Path],
    output_dir: Path,
    expected_duration: float = 0.0,
    expected_fps: float = 0.0,
    quality_profile: str = "",
) -> dict[str, Any]:
    reports = [analyze_video(path, expected_duration, expected_fps, quality_profile) for path in paths]
    signatures = {(item.get("width"), item.get("height"), item.get("fps"), item.get("frames")) for item in reports}
    group_errors = []
    if len(signatures) > 1:
        group_errors.append("view videos do not have identical resolution, fps, and frame count")
    contact_sheet = create_contact_sheet(paths, output_dir / "contact_sheet.jpg")
    report = {
        "schema": "denseworld.video-consistency.v1",
        "passed": not group_errors and all(item.get("passed") for item in reports),
        "group_errors": group_errors,
        "views": reports,
        "contact_sheet": str(contact_sheet),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "video_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-duration", type=float, default=0.0)
    parser.add_argument("--expected-fps", type=float, default=0.0)
    parser.add_argument("--quality-profile", default="")
    args = parser.parse_args()
    report = analyze_group(
        args.videos,
        args.output_dir,
        args.expected_duration,
        args.expected_fps,
        args.quality_profile,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
