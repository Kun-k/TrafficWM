"""Resident distributed HTTP worker for Cosmos Transfer2.5 multiview inference."""
from __future__ import annotations

import argparse
import gc
import json
import os
import queue
import random
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class _State:
    def __init__(
        self,
        *,
        world_size: int = 1,
        multiview_compat: dict[str, Any] | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=8)
        self.loaded_at = time.time()
        self.busy = False
        self.current_job_id = ""
        self.resident_camera_keys: tuple[str, ...] = ()
        self.busy_since_unix = 0.0
        self.jobs: dict[str, dict[str, Any]] = {}
        self.shutdown_requested = False
        self.world_size = int(world_size)
        self.multiview_compat = dict(multiview_compat or {})

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            running_jobs = [job for job in self.jobs.values() if job.get("run_state") == "running"]
            return {
                "ok": True,
                "service": "cosmos-transfer2.5",
                "run_state": "busy" if self.busy else "ready",
                "model_loaded": True,
                "loaded_at_unix": self.loaded_at,
                "current_job_id": self.current_job_id,
                "resident_camera_keys": list(self.resident_camera_keys),
                "busy_since_unix": self.busy_since_unix,
                "busy_seconds": round(time.time() - self.busy_since_unix, 3) if self.busy_since_unix else 0.0,
                "running_jobs": running_jobs,
                "queued_jobs": self.commands.qsize(),
                "context_parallel_size": self.world_size,
                "multiview_compat": self.multiview_compat,
                "jobs": list(self.jobs.values())[-20:],
            }


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _next_rank0_command(state: _State, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """Keep every distributed rank entering the control broadcast regularly."""
    try:
        return state.commands.get(timeout=max(0.001, float(timeout_seconds)))
    except queue.Empty:
        return {"type": "idle"}


def _start_http(state: _State, host: str, port: int) -> _Server:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._json(state.snapshot())
                return
            if path.startswith("/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                with state.lock:
                    job = state.jobs.get(job_id)
                self._json({"ok": bool(job), "job": job} if job else {"ok": False, "error": "job not found"}, 200 if job else 404)
                return
            self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            size = int(self.headers.get("Content-Length", "0") or "0")
            try:
                payload = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"ok": False, "error": "invalid JSON"}, 400)
                return
            if path == "/generate":
                spec_path = Path(str(payload.get("spec_path") or "")).expanduser().resolve()
                output_dir = Path(str(payload.get("output_dir") or "")).expanduser().resolve()
                if not spec_path.is_file() or spec_path.suffix != ".json":
                    self._json({"ok": False, "error": "spec_path must be an existing JSON file"}, 400)
                    return
                if not str(output_dir):
                    self._json({"ok": False, "error": "output_dir is required"}, 400)
                    return
                job_id = str(payload.get("job_id") or uuid.uuid4().hex)
                job = {
                    "id": job_id,
                    "run_state": "queued",
                    "spec_path": str(spec_path),
                    "output_dir": str(output_dir),
                    "submitted_at_unix": time.time(),
                }
                with state.lock:
                    if job_id in state.jobs:
                        self._json({"ok": False, "error": "job id already exists"}, 409)
                        return
                    state.jobs[job_id] = job
                try:
                    state.commands.put_nowait({"type": "generate", "job_id": job_id, **job})
                except queue.Full:
                    with state.lock:
                        job.update({"run_state": "error", "error": "worker queue is full"})
                    self._json({"ok": False, "error": "worker queue is full"}, 429)
                    return
                self._json({"ok": True, "job": job}, 202)
                return
            if path == "/shutdown":
                state.shutdown_requested = True
                state.commands.put({"type": "shutdown"})
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": "not found"}, 404)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = _Server((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="transfer-http").start()
    return server


def _load_sample(spec_path: Path):
    from cosmos_transfer2.multiview_config import MultiviewInferenceArguments

    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    previous = Path.cwd()
    try:
        os.chdir(spec_path.parent)
        return MultiviewInferenceArguments.model_validate(raw)
    finally:
        os.chdir(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8895)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--disable-guardrails", action="store_true", default=True)
    args = parser.parse_args(argv)

    from cosmos_oss.init import cleanup_environment, init_environment

    init_environment()
    from backend.cosmos.transfer_multiview_compat import install_multiview_vae_batching

    multiview_compat = install_multiview_vae_batching()
    import torch
    import numpy as np
    from cosmos_transfer2.multiview import MultiviewInference
    from cosmos_transfer2.multiview_config import MultiviewSetupArguments

    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    setup = MultiviewSetupArguments(
        model="auto/multiview",
        context_parallel_size=world_size,
        output_dir=args.output_dir.resolve(),
        keep_going=False,
        disable_guardrails=bool(args.disable_guardrails),
    )
    inference = MultiviewInference(setup)
    torch.distributed.barrier() if world_size > 1 else None
    control_group = (
        torch.distributed.new_group(ranks=list(range(world_size)), backend="gloo")
        if world_size > 1
        else None
    )

    state = (
        _State(world_size=world_size, multiview_compat=multiview_compat)
        if rank == 0
        else None
    )
    server = _start_http(state, args.host, args.port) if state is not None else None
    try:
        resident_camera_keys: tuple[str, ...] = ()
        while True:
            command_list: list[Any] = [_next_rank0_command(state) if state is not None else None]
            if world_size > 1:
                torch.distributed.broadcast_object_list(command_list, src=0, group=control_group)
            command = command_list[0]
            if command.get("type") == "shutdown":
                break
            if command.get("type") == "idle":
                continue
            if command.get("type") != "generate":
                continue
            job_id = str(command["job_id"])
            started = time.time()
            sample = None
            outputs = None
            if state is not None:
                with state.lock:
                    state.busy = True
                    state.current_job_id = job_id
                    state.busy_since_unix = started
                    state.jobs[job_id].update({"run_state": "running", "started_at_unix": started})
            try:
                sample = _load_sample(Path(command["spec_path"]))
                job_seed = int(sample.seed)
                random.seed(job_seed)
                np.random.seed(job_seed)
                torch.manual_seed(job_seed)
                torch.cuda.manual_seed(job_seed)
                torch.cuda.manual_seed_all(job_seed)
                requested_camera_keys = tuple(sample.active_camera_keys)
                if resident_camera_keys and requested_camera_keys != resident_camera_keys:
                    raise RuntimeError(
                        "TRANSFER_TOPOLOGY_CHANGE: resident="
                        f"{','.join(resident_camera_keys)} requested={','.join(requested_camera_keys)}"
                    )
                if not resident_camera_keys:
                    resident_camera_keys = requested_camera_keys
                    if state is not None:
                        with state.lock:
                            state.resident_camera_keys = resident_camera_keys
                outputs = inference.generate([sample], Path(command["output_dir"]))
                if state is not None:
                    with state.lock:
                        state.jobs[job_id].update(
                            {
                                "run_state": "completed",
                                "outputs": outputs,
                                "finished_at_unix": time.time(),
                                "generation_seconds": round(time.time() - started, 3),
                            }
                        )
            except BaseException as exc:
                if state is not None:
                    with state.lock:
                        state.jobs[job_id].update(
                            {
                                "run_state": "error",
                                "error": str(exc),
                                "traceback": traceback.format_exc()[-8000:],
                                "finished_at_unix": time.time(),
                            }
                        )
            finally:
                sample = None
                outputs = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                if world_size > 1:
                    torch.distributed.barrier()
                if state is not None:
                    with state.lock:
                        state.busy = False
                        state.current_job_id = ""
                        state.busy_since_unix = 0.0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        cleanup_environment()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
