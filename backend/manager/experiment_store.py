"""SQLite-backed experiment index used by the unified manager."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


ACTIVE_STATES = (
    "starting",
    "warming_up",
    "world_seed_pending",
    "running",
    "playback",
    "playback_loading",
)


def compact_replay_metadata(value):
    """Remove export-only map geometry from replay metadata persisted for the UI."""
    if isinstance(value, list):
        return [compact_replay_metadata(item) for item in value]
    if not isinstance(value, dict):
        return value
    compacted = {}
    for key, item in value.items():
        if key in {"recording_window", "window"} and isinstance(item, dict) and "map_state" in item:
            window = {name: compact_replay_metadata(data) for name, data in item.items() if name != "map_state"}
            semantic_quality = (item.get("map_state") or {}).get("semantic_quality") or {}
            if semantic_quality:
                window["semantic_quality"] = compact_replay_metadata(semantic_quality)
            compacted[key] = window
        else:
            compacted[key] = compact_replay_metadata(item)
    return compacted


class ExperimentStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                backend_model TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                run_state TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                map_path TEXT NOT NULL DEFAULT '',
                output_dir TEXT NOT NULL DEFAULT '',
                save_file TEXT NOT NULL DEFAULT '',
                snapshot_json TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_experiments_started_at ON experiments(started_at DESC)"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS world_jobs (
                experiment_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                run_state TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                timings_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(experiment_id, path),
                FOREIGN KEY(experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_markers (
                marker_scope TEXT NOT NULL,
                id TEXT NOT NULL,
                label TEXT NOT NULL,
                step INTEGER NOT NULL DEFAULT 0,
                sim_time REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(marker_scope, id)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_replay_markers_scope "
            "ON replay_markers(marker_scope, sim_time, created_at)"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                gpu_count INTEGER NOT NULL,
                duration_seconds REAL NOT NULL,
                run_state TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                artifact_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS simulation_batches (
                id TEXT PRIMARY KEY,
                backend_model TEXT NOT NULL,
                name TEXT NOT NULL,
                run_state TEXT NOT NULL,
                scenario_count INTEGER NOT NULL,
                completed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                current_index INTEGER NOT NULL DEFAULT 0,
                experiment_ids_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._compact_legacy_replay_metadata()
        self._connection.commit()

    @staticmethod
    def _json(value) -> str:
        return json.dumps(compact_replay_metadata(value), ensure_ascii=False, separators=(",", ":"), default=str)

    def _compact_legacy_replay_metadata(self) -> None:
        for table, id_column, columns in (
            ("experiments", "id", ("snapshot_json", "config_json")),
            ("world_jobs", "experiment_id", ("payload_json",)),
        ):
            selected = ", ".join((id_column, *columns))
            rows = self._connection.execute(
                f"SELECT {selected} FROM {table} WHERE "
                + " OR ".join(f"{column} LIKE '%\"map_state\"%'" for column in columns)
            ).fetchall()
            for row in rows:
                updates = []
                values = []
                for column, raw in zip(columns, row[1:]):
                    try:
                        compacted = self._json(json.loads(raw or "{}"))
                    except (TypeError, ValueError):
                        continue
                    if compacted != raw:
                        updates.append(f"{column}=?")
                        values.append(compacted)
                if updates:
                    values.append(row[0])
                    self._connection.execute(
                        f"UPDATE {table} SET {', '.join(updates)} WHERE {id_column}=?",
                        values,
                    )

    def upsert(self, snapshot: dict, config: dict | None = None):
        experiment_id = str(snapshot.get("id") or snapshot.get("experiment_id") or "").strip()
        if not experiment_id:
            return
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        run_state = str(snapshot.get("run_state") or "unknown")
        finished_at = now if run_state in {"completed", "error", "stopped", "interrupted"} else ""
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO experiments (
                    id, backend_model, kind, name, run_state, started_at, updated_at,
                    finished_at, map_path, output_dir, save_file, snapshot_json, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    backend_model=excluded.backend_model,
                    kind=excluded.kind,
                    name=excluded.name,
                    run_state=excluded.run_state,
                    updated_at=excluded.updated_at,
                    finished_at=CASE
                        WHEN excluded.finished_at != '' THEN excluded.finished_at
                        ELSE experiments.finished_at
                    END,
                    map_path=excluded.map_path,
                    output_dir=excluded.output_dir,
                    save_file=excluded.save_file,
                    snapshot_json=excluded.snapshot_json,
                    config_json=CASE
                        WHEN excluded.config_json != '{}' THEN excluded.config_json
                        ELSE experiments.config_json
                    END
                """,
                (
                    experiment_id,
                    str(snapshot.get("backend_model") or ""),
                    str(snapshot.get("kind") or "experiment"),
                    str(snapshot.get("name") or experiment_id),
                    run_state,
                    str(snapshot.get("started_at") or now),
                    now,
                    finished_at,
                    str(snapshot.get("map_path") or ""),
                    str(snapshot.get("output_dir") or ""),
                    str(snapshot.get("save_file") or ""),
                    self._json(snapshot),
                    self._json(config or {}),
                ),
            )
            self._connection.commit()

    def list(self, limit: int = 1000) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT snapshot_json FROM experiments ORDER BY started_at DESC, updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        records = []
        for (raw,) in rows:
            try:
                value = compact_replay_metadata(json.loads(raw))
                if isinstance(value, dict):
                    records.append(value)
            except (TypeError, ValueError):
                continue
        return records

    def get(self, experiment_id: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_json FROM experiments WHERE id=?",
                (str(experiment_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            value = compact_replay_metadata(json.loads(row[0]))
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def get_config(self, experiment_id: str) -> dict:
        with self._lock:
            row = self._connection.execute(
                "SELECT config_json FROM experiments WHERE id=?",
                (str(experiment_id),),
            ).fetchone()
        if row is None:
            return {}
        try:
            value = compact_replay_metadata(json.loads(row[0] or "{}"))
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) FROM experiments").fetchone()
        return int(row[0] if row else 0)

    def upsert_world_job(
        self,
        experiment_id: str,
        *,
        stage: str,
        run_state: str,
        progress: float = 0.0,
        message: str = "",
        error: str = "",
        payload: dict | None = None,
        timings: dict | None = None,
    ) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO world_jobs (
                    experiment_id, stage, run_state, progress, message, error,
                    payload_json, timings_json, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    stage=excluded.stage,
                    run_state=excluded.run_state,
                    progress=excluded.progress,
                    message=excluded.message,
                    error=excluded.error,
                    payload_json=excluded.payload_json,
                    timings_json=excluded.timings_json,
                    updated_at=excluded.updated_at
                """,
                (
                    experiment_id,
                    stage,
                    run_state,
                    max(0.0, min(1.0, float(progress))),
                    message,
                    error,
                    self._json(payload or {}),
                    self._json(timings or {}),
                    now,
                    now,
                ),
            )
            self._connection.commit()

    def world_job(self, experiment_id: str) -> dict:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT stage, run_state, progress, message, error, payload_json,
                       timings_json, started_at, updated_at
                FROM world_jobs WHERE experiment_id=?
                """,
                (experiment_id,),
            ).fetchone()
        if not row:
            return {}
        return {
            "experiment_id": experiment_id,
            "stage": row[0],
            "run_state": row[1],
            "progress": float(row[2]),
            "message": row[3],
            "error": row[4],
            "payload": compact_replay_metadata(json.loads(row[5] or "{}")),
            "timings": json.loads(row[6] or "{}"),
            "started_at": row[7],
            "updated_at": row[8],
        }

    def add_artifact(
        self,
        experiment_id: str,
        *,
        kind: str,
        path: str,
        mime_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO artifacts (experiment_id, kind, path, mime_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, path) DO UPDATE SET
                    kind=excluded.kind,
                    mime_type=excluded.mime_type,
                    metadata_json=excluded.metadata_json
                """,
                (experiment_id, kind, path, mime_type, self._json(metadata or {}), now),
            )
            self._connection.commit()

    def list_artifacts(self, experiment_id: str) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, kind, path, mime_type, metadata_json, created_at
                FROM artifacts WHERE experiment_id=? ORDER BY id
                """,
                (experiment_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "experiment_id": experiment_id,
                "kind": row[1],
                "path": row[2],
                "mime_type": row[3],
                "metadata": json.loads(row[4] or "{}"),
                "created_at": row[5],
            }
            for row in rows
        ]

    def list_markers(self, marker_scope: str) -> list[dict]:
        scope = str(marker_scope or "").strip()
        if not scope:
            return []
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, label, step, sim_time, created_at
                FROM replay_markers
                WHERE marker_scope=?
                ORDER BY sim_time, created_at, id
                """,
                (scope,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "marker_scope": scope,
                "label": row[1],
                "step": int(row[2] or 0),
                "sim_time": float(row[3] or 0.0),
                "created_at": row[4],
            }
            for row in rows
        ]

    def upsert_marker(self, marker_scope: str, marker: dict) -> dict:
        scope = str(marker_scope or "").strip()
        marker_id = str(marker.get("id") or "").strip()
        if not scope or not marker_id:
            raise ValueError("marker_scope and marker id are required")
        label = str(marker.get("label") or "标记").strip()[:120] or "标记"
        step = max(0, int(marker.get("step", 0) or 0))
        sim_time = max(0.0, float(marker.get("sim_time", 0.0) or 0.0))
        created_at = str(marker.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO replay_markers (
                    id, marker_scope, label, step, sim_time, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(marker_scope, id) DO UPDATE SET
                    label=excluded.label,
                    step=excluded.step,
                    sim_time=excluded.sim_time,
                    updated_at=excluded.updated_at
                """,
                (marker_id, scope, label, step, sim_time, created_at, updated_at),
            )
            self._connection.commit()
        return {
            "id": marker_id,
            "marker_scope": scope,
            "label": label,
            "step": step,
            "sim_time": sim_time,
            "created_at": created_at,
        }

    def delete_marker(self, marker_scope: str, marker_id: str) -> bool:
        scope = str(marker_scope or "").strip()
        marker_id = str(marker_id or "").strip()
        if not scope or not marker_id:
            return False
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM replay_markers WHERE marker_scope=? AND id=?",
                (scope, marker_id),
            )
            self._connection.commit()
        return bool(cursor.rowcount)

    def add_benchmark(
        self,
        *,
        model: str,
        gpu_count: int,
        duration_seconds: float,
        run_state: str,
        metrics: dict,
        artifact_path: str = "",
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO benchmark_results (
                    model, gpu_count, duration_seconds, run_state, metrics_json,
                    artifact_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model,
                    int(gpu_count),
                    float(duration_seconds),
                    run_state,
                    self._json(metrics),
                    artifact_path,
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            self._connection.commit()

    def list_benchmarks(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, model, gpu_count, duration_seconds, run_state,
                       metrics_json, artifact_path, created_at
                FROM benchmark_results ORDER BY id DESC
                """
            ).fetchall()
        return [
            {
                "id": row[0],
                "model": row[1],
                "gpu_count": row[2],
                "duration_seconds": row[3],
                "run_state": row[4],
                "metrics": json.loads(row[5] or "{}"),
                "artifact_path": row[6],
                "created_at": row[7],
            }
            for row in rows
        ]

    def upsert_batch(
        self,
        batch_id: str,
        *,
        backend_model: str,
        name: str,
        run_state: str,
        scenario_count: int,
        completed_count: int = 0,
        failed_count: int = 0,
        current_index: int = 0,
        experiment_ids: list[str] | None = None,
        payload: dict | None = None,
    ) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO simulation_batches (
                    id, backend_model, name, run_state, scenario_count,
                    completed_count, failed_count, current_index,
                    experiment_ids_json, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_state=excluded.run_state,
                    completed_count=excluded.completed_count,
                    failed_count=excluded.failed_count,
                    current_index=excluded.current_index,
                    experiment_ids_json=excluded.experiment_ids_json,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(batch_id),
                    str(backend_model),
                    str(name),
                    str(run_state),
                    max(1, int(scenario_count)),
                    max(0, int(completed_count)),
                    max(0, int(failed_count)),
                    max(0, int(current_index)),
                    json.dumps(experiment_ids or [], ensure_ascii=False),
                    self._json(payload or {}),
                    now,
                    now,
                ),
            )
            self._connection.commit()

    def list_batches(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, backend_model, name, run_state, scenario_count,
                       completed_count, failed_count, current_index,
                       experiment_ids_json, payload_json, created_at, updated_at
                FROM simulation_batches ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {
                "id": row[0],
                "backend_model": row[1],
                "name": row[2],
                "run_state": row[3],
                "scenario_count": row[4],
                "completed_count": row[5],
                "failed_count": row[6],
                "current_index": row[7],
                "experiment_ids": json.loads(row[8] or "[]"),
                "payload": json.loads(row[9] or "{}"),
                "created_at": row[10],
                "updated_at": row[11],
            }
            for row in rows
        ]

    def recover_interrupted(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        world_error = "Manager restarted before the DenseWorld pipeline completed"
        with self._lock:
            rows = self._connection.execute(
                f"SELECT id, snapshot_json FROM experiments WHERE run_state IN ({placeholders})",
                ACTIVE_STATES,
            ).fetchall()
            for experiment_id, raw in rows:
                try:
                    snapshot = json.loads(raw)
                except (TypeError, ValueError):
                    snapshot = {"id": experiment_id}
                snapshot.update(
                    {
                        "run_state": "interrupted",
                        "paused": False,
                        "termination_reason": "manager_restarted",
                    }
                )
                self._connection.execute(
                    """
                    UPDATE experiments
                    SET run_state='interrupted', updated_at=?, finished_at=?, snapshot_json=?
                    WHERE id=?
                    """,
                    (now, now, self._json(snapshot), experiment_id),
                )
            world_rows = self._connection.execute(
                "SELECT experiment_id FROM world_jobs WHERE run_state='running'"
            ).fetchall()
            for (experiment_id,) in world_rows:
                self._connection.execute(
                    """
                    UPDATE world_jobs
                    SET stage='interrupted', run_state='error',
                        message='DenseWorld generation was interrupted by a manager restart',
                        error=?, updated_at=?
                    WHERE experiment_id=?
                    """,
                    (world_error, now, experiment_id),
                )
                row = self._connection.execute(
                    "SELECT snapshot_json FROM experiments WHERE id=?",
                    (experiment_id,),
                ).fetchone()
                if not row:
                    continue
                try:
                    snapshot = json.loads(row[0])
                except (TypeError, ValueError):
                    continue
                world_generation = snapshot.get("world_generation")
                if not isinstance(world_generation, dict):
                    world_generation = {}
                world_generation.update(
                    {
                        "stage": "interrupted",
                        "run_state": "error",
                        "message": "DenseWorld generation was interrupted by a manager restart",
                        "error": world_error,
                        "updated_at": now,
                    }
                )
                snapshot["world_generation"] = world_generation
                self._connection.execute(
                    "UPDATE experiments SET snapshot_json=?, updated_at=? WHERE id=?",
                    (self._json(snapshot), now, experiment_id),
                )
            self._connection.commit()

    def delete(self, experiment_ids: list[str]):
        ids = [str(value) for value in experiment_ids if str(value)]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            self._connection.execute(f"DELETE FROM experiments WHERE id IN ({placeholders})", ids)
            self._connection.commit()

    def close(self):
        with self._lock:
            self._connection.close()
