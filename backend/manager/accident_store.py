"""Persistent AV accident candidates derived from traffic safety audits."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any


class AccidentStore:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def list(self, *, include_ignored: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            records = self._read()
        if not include_ignored:
            records = [record for record in records if record.get("status") != "ignored"]
        return sorted(records, key=lambda item: str(item.get("detected_at") or ""), reverse=True)

    def get(self, accident_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.list(include_ignored=True) if item.get("id") == accident_id),
            None,
        )

    def sync_audit(self, experiment: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
        collisions = audit.get("collisions") if isinstance(audit.get("collisions"), dict) else {}
        av = audit.get("av") if isinstance(audit.get("av"), dict) else {}
        timeline = audit.get("timeline") if isinstance(audit.get("timeline"), dict) else {}
        experiment_id = str(experiment.get("id") or "").strip()
        av_id = str(av.get("id") or experiment.get("av_id") or "").strip()
        source_path = str(experiment.get("save_file") or "").strip()
        if not experiment_id or not av_id or not source_path:
            return []
        try:
            duration = max(0.0, float(timeline.get("duration_seconds") or experiment.get("sim_time") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0

        candidates = []
        for pair in collisions.get("pairs") or []:
            if not isinstance(pair, dict):
                continue
            actor_ids = sorted(str(item) for item in pair.get("ids") or [])
            if av_id not in actor_ids:
                continue
            first = max(0.0, float(pair.get("first_time_seconds") or 0.0))
            last = max(first, float(pair.get("last_time_seconds") or first))
            start = max(0.0, first - 2.0)
            end = min(duration, last + 3.0) if duration > 0.0 else last + 3.0
            if end <= start:
                end = start + 0.1
            identity = f"{experiment_id}|{'|'.join(actor_ids)}|{first:.3f}"
            accident_id = "accident-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            frames = max(1, int(pair.get("frames") or 1))
            candidates.append(
                {
                    "id": accident_id,
                    "kind": "accident_candidate",
                    "status": "candidate",
                    "experiment_id": experiment_id,
                    "source_path": source_path,
                    "av_id": av_id,
                    "actor_ids": actor_ids,
                    "collision_frames": frames,
                    "first_time_seconds": round(first, 6),
                    "last_time_seconds": round(last, 6),
                    "start_seconds": round(start, 6),
                    "end_seconds": round(end, 6),
                    "severity": "critical" if frames >= 3 else "warning",
                    "detected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "replayable": False,
                }
            )

        if not candidates:
            return []
        with self._lock:
            records = self._read()
            by_id = {str(item.get("id") or ""): item for item in records}
            for candidate in candidates:
                previous = by_id.get(candidate["id"])
                if previous:
                    candidate.update(
                        {
                            key: previous[key]
                            for key in ("status", "saved_path", "saved_at", "name")
                            if key in previous
                        }
                    )
                by_id[candidate["id"]] = candidate
            self._write(list(by_id.values()))
        return candidates

    def update(self, accident_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            records = self._read()
            updated = None
            for record in records:
                if str(record.get("id") or "") != str(accident_id):
                    continue
                record.update(changes)
                updated = dict(record)
                break
            if updated is None:
                return None
            self._write(records)
        return updated
