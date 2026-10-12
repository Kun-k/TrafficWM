"""Build transparent experiment reports from persisted traffic and Cosmos audits."""
from __future__ import annotations

import math
import time
from typing import Any


DEFAULT_EVALUATION_WEIGHTS = {
    "safety": 45.0,
    "comfort": 25.0,
    "efficiency": 30.0,
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def _metric(
    metric_id: str,
    name: str,
    value: Any,
    unit: str,
    description: str,
    *,
    score: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    measured = value is not None
    return {
        "id": metric_id,
        "name": name,
        "value": value if measured else None,
        "unit": unit,
        "description": description,
        "status": "measured" if measured else "unavailable",
        "score": _clamp_score(score) if measured and score is not None else None,
        "note": note if measured else (note or "本次实验未采集该指标"),
    }


def _category(
    name: str,
    weight: float,
    metrics: list[dict[str, Any]],
    metric_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metric_config = metric_config if isinstance(metric_config, dict) else {}
    selected = []
    for item in metrics:
        configured = metric_config.get(str(item.get("id") or ""))
        if isinstance(configured, dict) and configured.get("enabled") is False:
            continue
        next_item = dict(item)
        if isinstance(configured, dict):
            next_item["weight"] = max(0.0, _number(configured.get("weight")) or 0.0)
        selected.append(next_item)
    scored = [item for item in selected if item.get("score") is not None]
    if scored and any(item.get("weight") is not None for item in scored):
        score_weight = sum(float(item.get("weight") or 0.0) for item in scored)
        category_score = (
            sum(float(item["score"]) * float(item.get("weight") or 0.0) for item in scored)
            / score_weight
            if score_weight > 0.0
            else None
        )
    else:
        category_score = sum(float(item["score"]) for item in scored) / len(scored) if scored else None
    measured = sum(item.get("status") == "measured" for item in selected)
    return {
        "name": name,
        "weight": float(weight),
        "score": round(category_score, 1) if category_score is not None else None,
        "coverage": {"measured": measured, "total": len(selected)},
        "metrics": selected,
    }


def _evaluation_weights(snapshot: dict, config: dict) -> dict[str, float]:
    configured = snapshot.get("evaluation_config") or config.get("evaluation_config") or {}
    weights = {}
    for key, default in DEFAULT_EVALUATION_WEIGHTS.items():
        configured_value = _number(configured.get(key))
        weights[key] = max(0.0, default if configured_value is None else configured_value)
    total = sum(weights.values())
    if total <= 0.0:
        return dict(DEFAULT_EVALUATION_WEIGHTS)
    return {key: round(value * 100.0 / total, 4) for key, value in weights.items()}


def build_experiment_report(
    snapshot: dict,
    config: dict | None = None,
    world_job: dict | None = None,
    artifacts: list[dict] | None = None,
) -> dict[str, Any]:
    """Create a report without inventing values for metrics absent from source data."""
    config = dict(config or {})
    world_job = dict(world_job or {})
    artifacts = list(artifacts or [])
    payload = world_job.get("payload") if isinstance(world_job.get("payload"), dict) else {}
    audit = payload.get("traffic_safety_audit") if isinstance(payload.get("traffic_safety_audit"), dict) else {}
    av = audit.get("av") if isinstance(audit.get("av"), dict) else {}
    collisions = audit.get("collisions") if isinstance(audit.get("collisions"), dict) else {}
    timeline = audit.get("timeline") if isinstance(audit.get("timeline"), dict) else {}
    comfort = av.get("comfort") if isinstance(av.get("comfort"), dict) else {}
    following = av.get("following") if isinstance(av.get("following"), dict) else {}
    speed = av.get("speed_mps") if isinstance(av.get("speed_mps"), dict) else {}
    violations = audit.get("violations") if isinstance(audit.get("violations"), dict) else {}

    av_overlap_frames = _number(collisions.get("av_overlap_frames"))
    collision_score = None if av_overlap_frames is None else (100.0 if av_overlap_frames <= 0 else 0.0)
    min_ttc = _number(following.get("minimum_ttc_seconds"))
    ttc_score = None if min_ttc is None else _clamp_score((min_ttc - 0.5) / 3.5 * 100.0)
    violation_rate = _number(
        violations.get("rate_percent")
        if violations.get("available") is not False
        else None
    )
    if violation_rate is None:
        violation_rate = _number(snapshot.get("traffic_violation_rate"))
    violation_score = (
        None
        if violation_rate is None
        else _clamp_score((5.0 - violation_rate) / 5.0 * 100.0)
    )

    longitudinal_rms = _number(comfort.get("longitudinal_acceleration_rms_mps2"))
    lateral_rms = _number(comfort.get("lateral_acceleration_rms_mps2"))
    jerk_p95 = _number(comfort.get("jerk_magnitude_p95_mps3"))
    longitudinal_score = None if longitudinal_rms is None else _clamp_score((4.0 - longitudinal_rms) / 3.0 * 100.0)
    lateral_score = None if lateral_rms is None else _clamp_score((3.0 - lateral_rms) / 2.2 * 100.0)
    jerk_score = None if jerk_p95 is None else _clamp_score((5.0 - jerk_p95) / 4.0 * 100.0)

    mean_speed = _number(speed.get("mean"))
    moving_ratio = _number(av.get("moving_frame_ratio"))
    duration = _number(timeline.get("duration_seconds"))
    longest_stationary = av.get("longest_stationary_run") if isinstance(av.get("longest_stationary_run"), dict) else {}
    stationary_seconds = _number(longest_stationary.get("duration_seconds"))
    stopped_ratio = None
    if moving_ratio is not None:
        stopped_ratio = max(0.0, min(1.0, 1.0 - moving_ratio))
    elif duration and stationary_seconds is not None:
        stopped_ratio = max(0.0, min(1.0, stationary_seconds / duration))
    speed_score = None if mean_speed is None else _clamp_score(mean_speed / 5.0 * 100.0)
    stopped_score = None if stopped_ratio is None else _clamp_score((1.0 - stopped_ratio) * 100.0)

    weights = _evaluation_weights(snapshot, config)
    configured_evaluation = snapshot.get("evaluation_config") or config.get("evaluation_config") or {}
    configured_metrics = (
        configured_evaluation.get("metrics")
        if isinstance(configured_evaluation, dict)
        and isinstance(configured_evaluation.get("metrics"), dict)
        else {}
    )
    categories = {
        "safety": _category(
            "安全性",
            weights["safety"],
            [
                _metric(
                    "av_overlap_frames",
                    "主车碰撞代理帧",
                    int(av_overlap_frames) if av_overlap_frames is not None else None,
                    "帧",
                    "主车包围盒与其他交通参与者发生几何重叠的帧数。",
                    score=collision_score,
                    note="0 帧记为满分；几何重叠是碰撞代理，不替代事故责任判定。",
                ),
                _metric(
                    "minimum_ttc",
                    "最小 TTC",
                    round(min_ttc, 3) if min_ttc is not None else None,
                    "s",
                    "同向前车恒速假设下的最小预测碰撞时间。",
                    score=ttc_score,
                    note="0.5 s 及以下为 0 分，4 s 及以上为满分。",
                ),
                _metric(
                    "traffic_violation_rate",
                    "交通违规率",
                    round(violation_rate, 4) if violation_rate is not None else None,
                    "%",
                    "闯红灯、越界和不合规通行事件占有效帧比例。",
                    score=violation_score,
                    note="基于主车车道语义和红灯停止线穿越事件；5% 及以上记为 0 分。",
                ),
            ],
            (configured_metrics.get("safety") or {}).get("metrics")
            if isinstance(configured_metrics.get("safety"), dict)
            else {},
        ),
        "comfort": _category(
            "舒适性",
            weights["comfort"],
            [
                _metric(
                    "longitudinal_acceleration_rms",
                    "纵向加速度 RMS",
                    longitudinal_rms,
                    "m/s²",
                    "主车纵向加速度均方根。",
                    score=longitudinal_score,
                ),
                _metric(
                    "lateral_acceleration_rms",
                    "横向加速度 RMS",
                    lateral_rms,
                    "m/s²",
                    "主车横向加速度均方根。",
                    score=lateral_score,
                ),
                _metric(
                    "jerk_p95",
                    "加加速度 P95",
                    jerk_p95,
                    "m/s³",
                    "主车加速度向量变化率绝对值的 95 分位数。",
                    score=jerk_score,
                ),
            ],
            (configured_metrics.get("comfort") or {}).get("metrics")
            if isinstance(configured_metrics.get("comfort"), dict)
            else {},
        ),
        "efficiency": _category(
            "效率",
            weights["efficiency"],
            [
                _metric(
                    "mean_speed",
                    "平均行驶速度",
                    mean_speed,
                    "m/s",
                    "主车有效实验区间的时间平均速度。",
                    score=speed_score,
                    note="城市测试中 5 m/s 及以上记为满分，仅用于相对效率比较。",
                ),
                _metric(
                    "elapsed_time",
                    "有效实验时长",
                    duration,
                    "s",
                    "交通安全审计覆盖的有效仿真时长。",
                    note="未配置固定路线目标时只报告时长，不单独评分。",
                ),
                _metric(
                    "stopped_time_ratio",
                    "停车时间比",
                    round(stopped_ratio * 100.0, 2) if stopped_ratio is not None else None,
                    "%",
                    "速度低于审计移动阈值的帧占比。",
                    score=stopped_score,
                ),
            ],
            (configured_metrics.get("efficiency") or {}).get("metrics")
            if isinstance(configured_metrics.get("efficiency"), dict)
            else {},
        ),
    }
    categories = {
        key: value
        for key, value in categories.items()
        if not (
            isinstance(configured_metrics.get(key), dict)
            and configured_metrics[key].get("enabled") is False
        )
    }

    weighted = [
        (category["score"], category["weight"])
        for category in categories.values()
        if category.get("score") is not None
    ]
    all_categories_scored = len(weighted) == len(categories)
    overall_score = None
    if all_categories_scored:
        weight_total = sum(weight for _score, weight in weighted)
        if weight_total > 0:
            overall_score = round(sum(score * weight for score, weight in weighted) / weight_total, 1)

    measured = sum(category["coverage"]["measured"] for category in categories.values())
    total = sum(category["coverage"]["total"] for category in categories.values())
    warnings = []
    if not audit:
        warnings.append("未找到逐帧交通安全审计，报告仅包含实验配置与产物信息。")
    if measured < total:
        warnings.append(f"本次报告覆盖 {measured}/{total} 项指标；未采集项不参与类别得分。")
    if overall_score is None:
        warnings.append("至少一个一级类别没有可评分指标，因此不生成综合得分。")

    return {
        "ok": True,
        "schema": "denseworld.experiment-report.v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": {
            "id": str(snapshot.get("id") or ""),
            "name": str(snapshot.get("name") or snapshot.get("id") or ""),
            "task_id": str(snapshot.get("task_id") or config.get("task_id") or ""),
            "workflow_id": str(snapshot.get("workflow_id") or config.get("workflow_id") or ""),
            "workflow_name": str(snapshot.get("workflow_name") or config.get("workflow_name") or ""),
            "backend_model": str(snapshot.get("backend_model") or config.get("backend_model") or ""),
            "run_state": str(snapshot.get("run_state") or "unknown"),
            "started_at": str(snapshot.get("started_at") or ""),
            "sim_time": _number(snapshot.get("sim_time")),
            "map_path": str(snapshot.get("map_path") or config.get("map_path") or ""),
            "save_file": str(snapshot.get("save_file") or ""),
        },
        "evaluation": {
            "weights": weights,
            "categories": categories,
            "overall_score": overall_score,
            "provisional": measured < total,
            "coverage": {"measured": measured, "total": total},
        },
        "execution": {
            "world_stage": str(world_job.get("stage") or ""),
            "world_state": str(world_job.get("run_state") or ""),
            "timings": world_job.get("timings") if isinstance(world_job.get("timings"), dict) else {},
            "artifact_count": len(artifacts),
            "traffic_audit_schema": str(audit.get("schema") or ""),
            "traffic_audit_passed": audit.get("passed") if audit else None,
        },
        "warnings": warnings,
    }
