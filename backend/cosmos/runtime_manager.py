"""Own the resident Transfer2.5 and OmniDreams service processes."""
from __future__ import annotations

import json
import hashlib
import os
import re
import select
import shlex
import signal
import socket
import subprocess
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from backend.cosmos.omnidreams_profiles import resolve_omnidreams_profile


DEFAULT_OMNIDREAMS_PIPELINE_CONFIG = (
    "omnidreams-sv-2steps-chunk2-loc6-vae-vae"
)
_OMNIDREAMS_TRAINING_CHECKPOINTS = {
    "omnidreams-sv-35steps-chunk2-loc24-cosmos2-2b-res720p-30fps-hdmap-vae-mads1m": (
        "student-init",
        "a12bf26e-8855-4ff0-a651-e7c2a0cb0697_model.pt",
    ),
    "omnidreams-sv-35steps-chunk48-loc48-cosmos2-2b-res720p-30fps-hdmap-vae-mads1m": (
        "teacher",
        "3b4c21d0-7b77-4694-9d9d-6ac9b6dbba51_model.pt",
    ),
}


def _gpu_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _http_json(url: str, method: str = "GET", payload: Optional[dict[str, Any]] = None, timeout: float = 1.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct_opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"ok": False, "error": str(exc)}


def _tail(path: Path, limit: int = 5000) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit), os.SEEK_SET)
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _local_listener_metadata(port: int) -> dict[str, Any]:
    """Inspect a local listening process so stale resident models are not mis-adopted."""
    try:
        result = subprocess.run(
            ["ss", "-ltnp", f"sport = :{int(port)}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            check=False,
        )
        match = re.search(r"pid=(\d+)", result.stdout or "")
        if not match:
            return {}
        pid = int(match.group(1))
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        environment = {}
        for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            if b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            environment[key.decode("utf-8", errors="replace")] = value.decode("utf-8", errors="replace")
        return {"pid": pid, "command": command, "environment": environment}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _omnidreams_launcher_pid(listener_pid: int) -> int:
    """Find the torchrun parent that owns an OmniDreams listener rank."""
    pid = int(listener_pid)
    for _ in range(12):
        if pid <= 1:
            break
        try:
            command = (
                Path(f"/proc/{pid}/cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", errors="replace")
            )
            if "torchrun" in command and "backend.cosmos.omnidreams_server" in command:
                return pid
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            parent_match = re.search(r"^PPid:\s+(\d+)$", status, flags=re.MULTILINE)
            if not parent_match:
                break
            parent_pid = int(parent_match.group(1))
        except (OSError, ValueError):
            break
        if parent_pid == pid:
            break
        pid = parent_pid
    return int(listener_pid)


def _terminate_local_omnidreams(metadata: dict[str, Any], port: int) -> None:
    pid = int(metadata.get("pid") or 0)
    command = str(metadata.get("command") or "")
    if pid <= 1 or "backend.cosmos.omnidreams_server" not in command:
        raise RuntimeError(
            f"Port {port} is occupied by an incompatible, unmanaged OmniDreams endpoint"
        )
    launcher_pid = _omnidreams_launcher_pid(pid)
    descendants = _linux_descendant_pids(launcher_pid)
    try:
        for descendant in reversed(descendants):
            try:
                os.kill(descendant, signal.SIGINT)
            except OSError:
                pass
        os.killpg(os.getpgid(launcher_pid), signal.SIGINT)
    except OSError:
        try:
            os.kill(launcher_pid, signal.SIGINT)
        except OSError:
            pass
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        tree_alive = Path(f"/proc/{launcher_pid}").exists() or any(
            Path(f"/proc/{descendant}").exists() for descendant in descendants
        )
        endpoint_ready = _omnidreams_rpc_ready("127.0.0.1", port, timeout=0.3)
        if not tree_alive and not endpoint_ready:
            return
        time.sleep(0.25)
    for process_pid in [*reversed(descendants), launcher_pid]:
        try:
            os.kill(process_pid, signal.SIGKILL)
        except OSError:
            pass
    kill_deadline = time.monotonic() + 5.0
    while time.monotonic() < kill_deadline:
        if not Path(f"/proc/{launcher_pid}").exists() and not _omnidreams_rpc_ready(
            "127.0.0.1", port, timeout=0.3
        ):
            return
        time.sleep(0.1)
    raise RuntimeError(f"Timed out replacing incompatible OmniDreams service on port {port}")


def _linux_descendant_pids(root_pid: int) -> list[int]:
    """Return descendants before torchrun can orphan its rank processes."""
    parent_by_pid: dict[int, int] = {}
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            fields = {}
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    fields[key] = value.strip()
            parent_by_pid[int(status_path.parent.name)] = int(fields.get("PPid", "0"))
        except (OSError, TypeError, ValueError):
            continue
    descendants: list[int] = []
    frontier = [int(root_pid)]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, ppid in parent_by_pid.items() if ppid == parent]
        descendants.extend(children)
        frontier.extend(children)
    return descendants


def _omnidreams_rpc_ready(host: str, port: int, timeout: float = 0.8) -> bool:
    """Verify that a listener is the expected OmniDreams gRPC service."""
    try:
        import grpc
    except ImportError:
        return False

    channel = grpc.insecure_channel(
        f"{host}:{int(port)}",
        options=(("grpc.enable_http_proxy", 0),),
    )
    try:
        grpc.channel_ready_future(channel).result(timeout=timeout)
        get_version = channel.unary_unary(
            "/omnidreams.video_model.WorldModelService/get_version",
            request_serializer=lambda _request: b"",
            response_deserializer=lambda response: response,
        )
        get_version(b"", timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        channel.close()


def _available_master_port(preferred: int) -> int:
    """Keep the configured torchrun rendezvous port when free, else use a free port."""
    for candidate in (int(preferred), 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("0.0.0.0", candidate))
                return int(probe.getsockname()[1])
        except OSError:
            continue
    raise RuntimeError("Unable to allocate a torchrun rendezvous port")


def _resolve_omnidreams_checkpoint(
    pipeline_config: str,
    explicit_path: str,
    hf_home: str,
) -> str:
    """Resolve public training checkpoints used by FlashDreams quality configs."""
    if explicit_path.strip():
        path = Path(os.path.abspath(os.path.expanduser(explicit_path)))
        if not path.is_file():
            raise FileNotFoundError(f"OmniDreams checkpoint not found: {path}")
        return str(path)

    checkpoint = _OMNIDREAMS_TRAINING_CHECKPOINTS.get(pipeline_config)
    if checkpoint is None:
        return ""

    stage, filename = checkpoint
    cache_roots = [Path(hf_home).expanduser(), Path.home() / ".cache" / "huggingface"]
    for cache_root in cache_roots:
        snapshots = (
            cache_root
            / "hub"
            / "models--nvidia--omni-dreams-models"
            / "snapshots"
        )
        for candidate in snapshots.glob(f"*/single_view/{stage}/{filename}"):
            if candidate.is_file():
                # Keep the .pt symlink name. FlashDreams uses the suffix to
                # distinguish a single-file checkpoint from a DCP directory.
                return str(candidate.absolute())
    raise FileNotFoundError(
        f"OmniDreams pipeline {pipeline_config!r} requires {stage}/{filename}; "
        f"download it under {hf_home}/hub/models--nvidia--omni-dreams-models first"
    )


class CosmosRuntimeManager:
    def __init__(
        self,
        *,
        app_root: Path,
        transfer_root: Path,
        omnidreams_root: Path,
        autostart: bool = False,
        transfer_gpus: str = "0,1,2,3",
        anchor_transfer_gpus: str = "",
        omnidreams_gpus: str = "7",
        transfer_port: int = 8895,
        anchor_transfer_port: int = 8896,
        omnidreams_port: int = 50051,
        transfer_master_port: int = 29531,
        anchor_transfer_master_port: int = 29533,
        omnidreams_master_port: int = 29532,
        omnidreams_profile: str = "quality",
        omnidreams_pipeline_config: str = DEFAULT_OMNIDREAMS_PIPELINE_CONFIG,
        omnidreams_checkpoint_path: str = "",
        transfer_container_image: str = "trafficwm-cosmos-runtime:cu128",
        transfer_container_venv: str = "cosmos-transfer25-venv",
    ) -> None:
        self.app_root = app_root.resolve()
        self.transfer_root = transfer_root.resolve()
        self.omnidreams_root = omnidreams_root.resolve()
        self.transfer_gpus = _gpu_list(transfer_gpus)
        self.anchor_transfer_gpus = _gpu_list(anchor_transfer_gpus)
        self.omnidreams_gpus = _gpu_list(omnidreams_gpus)
        assigned_gpu_sets = {
            "transfer": set(self.transfer_gpus),
            "anchor_transfer": set(self.anchor_transfer_gpus),
            "omnidreams": set(self.omnidreams_gpus),
        }
        overlap_details = []
        names = list(assigned_gpu_sets)
        for index, first in enumerate(names):
            for second in names[index + 1 :]:
                overlap = sorted(assigned_gpu_sets[first] & assigned_gpu_sets[second])
                if overlap:
                    overlap_details.append(f"{first}/{second}={','.join(overlap)}")
        self.gpu_overlap = overlap_details
        allow_gpu_overlap = os.environ.get("TRAFFICWM_ALLOW_COSMOS_GPU_OVERLAP", "").strip().lower()
        if self.gpu_overlap and allow_gpu_overlap not in {"1", "true", "yes"}:
            raise ValueError(
                "Resident Cosmos services must use disjoint resident GPU sets; "
                f"overlap={';'.join(self.gpu_overlap)}. Set "
                "TRAFFICWM_ALLOW_COSMOS_GPU_OVERLAP=1 only for an intentional shared-GPU setup."
            )
        self.transfer_port = int(transfer_port)
        self.anchor_transfer_port = int(anchor_transfer_port)
        self.omnidreams_port = int(omnidreams_port)
        self.transfer_master_port = int(transfer_master_port)
        self.anchor_transfer_master_port = int(anchor_transfer_master_port)
        self.omnidreams_master_port = int(omnidreams_master_port)
        self.omnidreams_profile = resolve_omnidreams_profile(omnidreams_profile)
        self.omnidreams_pipeline_config = str(omnidreams_pipeline_config or "").strip()
        if not self.omnidreams_pipeline_config:
            raise ValueError("OmniDreams pipeline config must not be empty")
        self.omnidreams_checkpoint_path = str(omnidreams_checkpoint_path or "").strip()
        self._resolved_omnidreams_checkpoint = ""
        self.transfer_container_image = str(transfer_container_image or "").strip()
        self.transfer_container_venv = str(transfer_container_venv or "").strip()
        self.output_root = self.app_root / "output" / "cosmos"
        self.log_root = self.output_root / "runtime"
        self.log_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, Any] = {}
        self._container_names: dict[str, str] = {}
        self._adopted_services: set[str] = set()
        self._adopted_omnidreams_metadata: dict[str, Any] = {}
        self._active_master_ports = {
            "transfer": self.transfer_master_port,
            "anchor_transfer": self.anchor_transfer_master_port,
            "omnidreams": self.omnidreams_master_port,
        }
        self.started_at = 0.0
        self.enabled = bool(autostart)
        if self.enabled:
            self.start()

    def _spawn(self, name: str, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        log_path = self.log_root / f"{name}.log"
        log = log_path.open("w", encoding="utf-8", buffering=1)
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self._processes[name] = process
        self._logs[name] = log

    def start(self) -> None:
        with self._lock:
            if self._processes or self._adopted_services:
                return
            if not self.omnidreams_gpus:
                raise ValueError("OmniDreams GPU list must not be empty")
            if self.transfer_gpus:
                transfer_health = _http_json(
                    f"http://127.0.0.1:{self.transfer_port}/health", timeout=0.8
                )
                if (
                    transfer_health.get("ok")
                    and transfer_health.get("service") == "cosmos-transfer2.5"
                ):
                    self._adopted_services.add("transfer")
            if self.anchor_transfer_gpus:
                anchor_health = _http_json(
                    f"http://127.0.0.1:{self.anchor_transfer_port}/health",
                    timeout=0.8,
                )
                if anchor_health.get("ok") and anchor_health.get("service") == "cosmos-transfer2.5":
                    self._adopted_services.add("anchor_transfer")
            if _omnidreams_rpc_ready("127.0.0.1", self.omnidreams_port, timeout=1.2):
                metadata = _local_listener_metadata(self.omnidreams_port)
                environment = metadata.get("environment") or {}
                actual_gpus = _gpu_list(environment.get("CUDA_VISIBLE_DEVICES", ""))
                actual_pipeline = str(environment.get("OMNIDREAMS_PIPELINE_CONFIG") or "")
                compatible = bool(metadata) and actual_gpus == self.omnidreams_gpus and actual_pipeline == self.omnidreams_pipeline_config
                if compatible:
                    self._adopted_services.add("omnidreams")
                    self._adopted_omnidreams_metadata = metadata
                else:
                    _terminate_local_omnidreams(metadata, self.omnidreams_port)

            transfer_torchrun = self.transfer_root / ".venv" / "bin" / "torchrun"
            omni_torchrun = self.omnidreams_root / ".venv" / "bin" / "torchrun"
            if (
                self.transfer_gpus
                and "transfer" not in self._adopted_services
                and not self.transfer_container_image
                and not transfer_torchrun.is_file()
            ):
                raise FileNotFoundError(f"Transfer torchrun not found: {transfer_torchrun}")
            if "omnidreams" not in self._adopted_services and not omni_torchrun.is_file():
                raise FileNotFoundError(f"OmniDreams torchrun not found: {omni_torchrun}")
            if self.transfer_gpus and "transfer" not in self._adopted_services:
                self._active_master_ports["transfer"] = _available_master_port(self.transfer_master_port)
            if self.anchor_transfer_gpus and "anchor_transfer" not in self._adopted_services:
                self._active_master_ports["anchor_transfer"] = _available_master_port(
                    self.anchor_transfer_master_port
                )
            if "omnidreams" not in self._adopted_services:
                self._active_master_ports["omnidreams"] = _available_master_port(self.omnidreams_master_port)

            if self.transfer_container_image and (
                (
                    self.transfer_gpus
                    and "transfer" not in self._adopted_services
                )
                or (
                    self.anchor_transfer_gpus
                    and "anchor_transfer" not in self._adopted_services
                )
            ):
                permission_command = [
                    "docker", "run", "--rm",
                    "-v", f"{self.output_root}:{self.output_root}",
                    "--entrypoint", "chown", self.transfer_container_image,
                    "-R", f"{os.getuid()}:{os.getgid()}", str(self.output_root),
                ]
                subprocess.run(
                    ["sg", "docker", "-c", shlex.join(permission_command)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=120.0,
                    check=True,
                )

            common_env = os.environ.copy()
            common_env.update(
                {
                    "PYTHONUNBUFFERED": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                    "HF_HOME": common_env.get("HF_HOME", "/mnt/rk/huggingface"),
                    "HF_ENDPOINT": common_env.get("HF_ENDPOINT", "https://hf-mirror.com"),
                }
            )
            resolved_omni_checkpoint = _resolve_omnidreams_checkpoint(
                self.omnidreams_pipeline_config,
                self.omnidreams_checkpoint_path,
                common_env["HF_HOME"],
            )
            self._resolved_omnidreams_checkpoint = resolved_omni_checkpoint
            if common_env.get("COSMOS_HF_OFFLINE", "1").strip().lower() in {"1", "true", "yes"}:
                common_env["HF_HUB_OFFLINE"] = "1"
            transfer_env = common_env.copy()
            transfer_env["CUDA_VISIBLE_DEVICES"] = ",".join(self.transfer_gpus)
            transfer_env.setdefault("GLOO_SOCKET_IFNAME", "lo")
            nvidia_roots = list((self.transfer_root / ".venv" / "lib").glob("python*/site-packages/nvidia"))
            cuda_library_dirs = sorted(path for root in nvidia_roots for path in root.glob("*/lib") if path.is_dir())
            if nvidia_roots:
                transfer_env["CUDA_HOME"] = str(nvidia_roots[0])
                transfer_env["CUDA_PATH"] = str(nvidia_roots[0])
            if cuda_library_dirs:
                transfer_env["LD_LIBRARY_PATH"] = os.pathsep.join(
                    [*(str(path) for path in cuda_library_dirs), transfer_env.get("LD_LIBRARY_PATH", "")]
                ).rstrip(os.pathsep)
            transfer_env["PYTHONPATH"] = os.pathsep.join(
                [str(self.app_root), str(self.transfer_root), transfer_env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            transfer_worker_command = [
                "/workspace/.venv/bin/torchrun" if self.transfer_container_image else str(transfer_torchrun),
                f"--nproc_per_node={len(self.transfer_gpus)}",
                f"--master_port={self._active_master_ports['transfer']}",
                "-m",
                "backend.cosmos.transfer_worker",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.transfer_port),
                "--output-dir",
                str(self.output_root / "transfer"),
                "--disable-guardrails",
            ]
            transfer_cwd = self.transfer_root
            if self.transfer_container_image:
                container_name = f"trafficwm-transfer-{self.transfer_port}"
                if "transfer" not in self._adopted_services:
                    self._container_names["transfer"] = container_name
                hf_home = Path(transfer_env["HF_HOME"]).expanduser().resolve()
                docker_command = [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    container_name,
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--gpus",
                    "all",
                    "--network",
                    "host",
                    "--shm-size",
                    "32g",
                    "-e",
                    f"CUDA_VISIBLE_DEVICES={','.join(self.transfer_gpus)}",
                    "-e",
                    "PYTHONUNBUFFERED=1",
                    "-e",
                    "HOME=/tmp",
                    "-e",
                    "TOKENIZERS_PARALLELISM=false",
                    "-e",
                    f"HF_HOME={hf_home}",
                    "-e",
                    f"HF_ENDPOINT={transfer_env['HF_ENDPOINT']}",
                    "-e",
                    f"HF_HUB_OFFLINE={transfer_env.get('HF_HUB_OFFLINE', '0')}",
                    "-e",
                    f"PYTHONPATH={self.app_root}:/workspace",
                    "-v",
                    f"{self.transfer_container_venv}:/workspace/.venv",
                    "-v",
                    f"{self.transfer_root}:/workspace",
                    "-v",
                    f"{self.app_root}:{self.app_root}",
                    "-v",
                    f"{hf_home}:{hf_home}",
                    "--entrypoint",
                    "bash",
                    self.transfer_container_image,
                    "-lc",
                    f"export PATH={self.app_root}/backend/cosmos/container_bin:$PATH; "
                    "cd /workspace && exec " + shlex.join(transfer_worker_command),
                ]
                transfer_command = ["sg", "docker", "-c", shlex.join(docker_command)]
            else:
                transfer_command = transfer_worker_command

            anchor_transfer_command: list[str] | None = None
            anchor_transfer_env = transfer_env.copy()
            anchor_transfer_cwd = self.transfer_root
            if self.anchor_transfer_gpus:
                anchor_transfer_env["CUDA_VISIBLE_DEVICES"] = ",".join(
                    self.anchor_transfer_gpus
                )
                anchor_worker_command = [
                    "/workspace/.venv/bin/torchrun"
                    if self.transfer_container_image
                    else str(transfer_torchrun),
                    f"--nproc_per_node={len(self.anchor_transfer_gpus)}",
                    f"--master_port={self._active_master_ports['anchor_transfer']}",
                    "-m",
                    "backend.cosmos.transfer_worker",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.anchor_transfer_port),
                    "--output-dir",
                    str(self.output_root / "anchor_transfer"),
                    "--disable-guardrails",
                ]
                if self.transfer_container_image:
                    anchor_container_name = (
                        f"trafficwm-anchor-transfer-{self.anchor_transfer_port}"
                    )
                    if "anchor_transfer" not in self._adopted_services:
                        self._container_names["anchor_transfer"] = anchor_container_name
                    hf_home = Path(anchor_transfer_env["HF_HOME"]).expanduser().resolve()
                    anchor_docker_command = [
                        "docker",
                        "run",
                        "--rm",
                        "--name",
                        anchor_container_name,
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--gpus",
                        "all",
                        "--network",
                        "host",
                        "--shm-size",
                        "32g",
                        "-e",
                        f"CUDA_VISIBLE_DEVICES={','.join(self.anchor_transfer_gpus)}",
                        "-e",
                        "PYTHONUNBUFFERED=1",
                        "-e",
                        "HOME=/tmp",
                        "-e",
                        "TOKENIZERS_PARALLELISM=false",
                        "-e",
                        f"HF_HOME={hf_home}",
                        "-e",
                        f"HF_ENDPOINT={anchor_transfer_env['HF_ENDPOINT']}",
                        "-e",
                        f"HF_HUB_OFFLINE={anchor_transfer_env.get('HF_HUB_OFFLINE', '0')}",
                        "-e",
                        f"PYTHONPATH={self.app_root}:/workspace",
                        "-v",
                        f"{self.transfer_container_venv}:/workspace/.venv",
                        "-v",
                        f"{self.transfer_root}:/workspace",
                        "-v",
                        f"{self.app_root}:{self.app_root}",
                        "-v",
                        f"{hf_home}:{hf_home}",
                        "--entrypoint",
                        "bash",
                        self.transfer_container_image,
                        "-lc",
                        f"export PATH={self.app_root}/backend/cosmos/container_bin:$PATH; "
                        "cd /workspace && exec " + shlex.join(anchor_worker_command),
                    ]
                    anchor_transfer_command = [
                        "sg",
                        "docker",
                        "-c",
                        shlex.join(anchor_docker_command),
                    ]
                else:
                    anchor_transfer_command = anchor_worker_command

            omni_env = common_env.copy()
            omni_env["CUDA_VISIBLE_DEVICES"] = ",".join(self.omnidreams_gpus)
            omni_env["PATH"] = os.pathsep.join(
                [str(self.omnidreams_root / ".venv" / "bin"), omni_env.get("PATH", "")]
            ).rstrip(os.pathsep)
            omni_env["CXX"] = str(self.app_root / "backend" / "cosmos" / "container_bin" / "cxx20_compat")
            omni_site_packages = sorted((self.omnidreams_root / ".venv" / "lib").glob("python*/site-packages"))
            if omni_site_packages:
                omni_cuda_root = omni_site_packages[0] / "nvidia" / "cu13"
                omni_library_dirs = [omni_site_packages[0] / "torch" / "lib", omni_cuda_root / "lib"]
                omni_library_dirs = [path for path in omni_library_dirs if path.is_dir()]
                if omni_cuda_root.is_dir():
                    omni_env["CUDA_HOME"] = str(omni_cuda_root)
                    versioned_nvjpeg = omni_cuda_root / "lib" / "libnvjpeg.so.13"
                    linker_nvjpeg = omni_cuda_root / "lib" / "libnvjpeg.so"
                    if versioned_nvjpeg.is_file() and not linker_nvjpeg.exists():
                        linker_nvjpeg.symlink_to(versioned_nvjpeg.name)
                if omni_library_dirs:
                    omni_env["LD_LIBRARY_PATH"] = os.pathsep.join(
                        [*(str(path) for path in omni_library_dirs), omni_env.get("LD_LIBRARY_PATH", "")]
                    ).rstrip(os.pathsep)
            omni_env["PYTHONPATH"] = os.pathsep.join(
                [
                    str(self.app_root),
                    str(self.omnidreams_root / "flashdreams"),
                    str(self.omnidreams_root / "integrations" / "omnidreams"),
                    str(self.omnidreams_root / "integrations" / "omnidreams" / "ludus-renderer"),
                    omni_env.get("PYTHONPATH", ""),
                ]
            ).rstrip(os.pathsep)
            omni_env["OMNIDREAMS_PIPELINE_CONFIG"] = self.omnidreams_pipeline_config
            omni_env["OMNIDREAMS_PROFILE"] = self.omnidreams_profile.name
            omni_env.setdefault(
                "OMNIDREAMS_DISABLE_VAE_COMPILE",
                "1" if self.omnidreams_profile.disable_vae_compile else "0",
            )
            omni_env.setdefault(
                "OMNIDREAMS_DISABLE_VAE_CUDA_GRAPH",
                "1" if self.omnidreams_profile.disable_vae_cuda_graph else "0",
            )
            omni_env.setdefault(
                "OMNIDREAMS_WINDOW_SIZE_T",
                str(self.omnidreams_profile.temporal_window_size_t),
            )
            omni_env.setdefault(
                "OMNIDREAMS_SINK_SIZE_T",
                str(self.omnidreams_profile.temporal_sink_size_t),
            )
            omni_env.setdefault(
                "OMNIDREAMS_DISTRIBUTED_TIMEOUT_SECONDS",
                str(7 * 24 * 60 * 60),
            )
            if resolved_omni_checkpoint:
                omni_env["OMNIDREAMS_CHECKPOINT_PATH"] = resolved_omni_checkpoint
            omni_command = [
                str(omni_torchrun),
                f"--nproc_per_node={len(self.omnidreams_gpus)}",
                f"--master_port={self._active_master_ports['omnidreams']}",
                "-m",
                "backend.cosmos.omnidreams_server",
                "--pipeline_config_name",
                self.omnidreams_pipeline_config,
                "--host",
                "127.0.0.1",
                "--port",
                str(self.omnidreams_port),
                "--output_format",
                "jpeg",
                "--jpeg_quality",
                str(self.omnidreams_profile.jpeg_quality),
                "--record_dir",
                str(self.output_root / "omnidreams" / "recordings"),
            ]

            (self.output_root / "transfer").mkdir(parents=True, exist_ok=True)
            if self.anchor_transfer_gpus:
                (self.output_root / "anchor_transfer").mkdir(parents=True, exist_ok=True)
            (self.output_root / "omnidreams" / "recordings").mkdir(parents=True, exist_ok=True)
            self.started_at = time.time()
            if self.transfer_gpus and "transfer" not in self._adopted_services:
                self._spawn("transfer", transfer_command, transfer_cwd, transfer_env)
            if (
                anchor_transfer_command is not None
                and "anchor_transfer" not in self._adopted_services
            ):
                self._spawn(
                    "anchor_transfer",
                    anchor_transfer_command,
                    anchor_transfer_cwd,
                    anchor_transfer_env,
                )
            if "omnidreams" not in self._adopted_services:
                self._spawn("omnidreams", omni_command, self.omnidreams_root, omni_env)

    def _process_status(self, name: str) -> dict[str, Any]:
        process = self._processes.get(name)
        log_path = self.log_root / f"{name}.log"
        if process is None:
            if name in self._adopted_services:
                return {
                    "run_state": "loading",
                    "model_loaded": False,
                    "ownership": "adopted",
                    "log_path": str(log_path),
                }
            return {"run_state": "disabled", "model_loaded": False, "log_path": str(log_path)}
        code = process.poll()
        if code is not None:
            return {
                "run_state": "error",
                "model_loaded": False,
                "exit_code": code,
                "log_path": str(log_path),
                "log_tail": _tail(log_path),
            }
        return {"run_state": "loading", "model_loaded": False, "pid": process.pid, "log_path": str(log_path)}

    @staticmethod
    def _tcp_ready(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            transfer = self._process_status("transfer")
            anchor_transfer = self._process_status("anchor_transfer")
            omnidreams = self._process_status("omnidreams")
        health = (
            _http_json(
                f"http://127.0.0.1:{self.transfer_port}/health", timeout=0.7
            )
            if self.transfer_gpus
            else {}
        )
        if (
            self.transfer_gpus
            and health.get("ok")
            and health.get("service") == "cosmos-transfer2.5"
        ):
            if transfer.get("run_state") == "error":
                transfer["ownership"] = "adopted"
                for key in ("error", "exit_code", "log_tail"):
                    transfer.pop(key, None)
            transfer.update(health)
        elif self.transfer_gpus and "transfer" in self._adopted_services:
            transfer.update(
                {
                    "run_state": "error",
                    "model_loaded": False,
                    "error": "Adopted Transfer2.5 endpoint is unavailable",
                }
            )
        elif not self.transfer_gpus:
            transfer.update(
                {
                    "run_state": "disabled",
                    "model_loaded": False,
                    "reason": "No primary Transfer GPU partition is configured",
                }
            )

        if self.anchor_transfer_gpus:
            anchor_health = _http_json(
                f"http://127.0.0.1:{self.anchor_transfer_port}/health",
                timeout=0.7,
            )
            if (
                anchor_health.get("ok")
                and anchor_health.get("service") == "cosmos-transfer2.5"
            ):
                if anchor_transfer.get("run_state") == "error":
                    anchor_transfer["ownership"] = "adopted"
                    for key in ("error", "exit_code", "log_tail"):
                        anchor_transfer.pop(key, None)
                anchor_transfer.update(anchor_health)
            elif "anchor_transfer" in self._adopted_services:
                anchor_transfer.update(
                    {
                        "run_state": "error",
                        "model_loaded": False,
                        "error": "Adopted anchor Transfer2.5 endpoint is unavailable",
                    }
                )
        else:
            anchor_transfer.update(
                {
                    "run_state": "disabled",
                    "model_loaded": False,
                    "reason": "No anchor Transfer GPU partition is configured",
                }
            )

        omni_ready = _omnidreams_rpc_ready("127.0.0.1", self.omnidreams_port, timeout=0.7)
        if omni_ready:
            if omnidreams.get("run_state") == "error":
                omnidreams["ownership"] = "adopted"
                for key in ("error", "exit_code", "log_tail"):
                    omnidreams.pop(key, None)
            omnidreams.update(
                {
                    "run_state": "ready",
                    "model_loaded": True,
                    "grpc_target": f"127.0.0.1:{self.omnidreams_port}",
                }
            )
        elif "omnidreams" in self._adopted_services:
            omnidreams.update(
                {
                    "run_state": "error",
                    "model_loaded": False,
                    "error": "Adopted OmniDreams endpoint is unavailable",
                }
            )
        omnidreams["pipeline_config"] = self.omnidreams_pipeline_config
        omnidreams["profile"] = self.omnidreams_profile.name
        if "omnidreams" in self._adopted_services:
            adopted_environment = self._adopted_omnidreams_metadata.get("environment") or {}
            omnidreams["resident_pipeline_config"] = adopted_environment.get("OMNIDREAMS_PIPELINE_CONFIG", "")
            omnidreams["resident_gpus"] = _gpu_list(adopted_environment.get("CUDA_VISIBLE_DEVICES", ""))
            omnidreams["resident_world_size"] = int(adopted_environment.get("WORLD_SIZE", "0") or 0)
        omnidreams["profile_defaults"] = self.omnidreams_profile.as_dict()
        omnidreams["checkpoint_override"] = bool(self._resolved_omnidreams_checkpoint)
        anchor_ready = bool(
            not self.anchor_transfer_gpus or anchor_transfer.get("model_loaded")
        )
        ready = bool(
            (not self.transfer_gpus or transfer.get("model_loaded"))
            and anchor_ready
            and omnidreams.get("model_loaded")
        )
        return {
            "ok": True,
            "enabled": self.enabled,
            "ready": ready,
            "started_at_unix": self.started_at,
            "gpu_partition": {
                "transfer": self.transfer_gpus,
                "anchor_transfer": self.anchor_transfer_gpus,
                "omnidreams": self.omnidreams_gpus,
                "overlap": self.gpu_overlap,
                "isolated": not self.gpu_overlap,
            },
            "transfer_runtime": {
                "type": "docker" if self.transfer_container_image else "native",
                "image": self.transfer_container_image,
            },
            "transfer": transfer,
            "anchor_transfer": anchor_transfer,
            "omnidreams": omnidreams,
        }

    def submit_transfer(self, spec_path: Path, output_dir: Path, job_id: str = "") -> dict[str, Any]:
        if hasattr(self, "transfer_gpus") and not self.transfer_gpus:
            raise RuntimeError(
                "Transfer2.5 is disabled; configure COSMOS_TRANSFER_GPUS and restart the manager"
            )
        spec_path = Path(spec_path).resolve()
        output_dir = Path(output_dir).resolve()
        if self.transfer_container_image:
            spec_path = self._stage_transfer_spec_for_container(spec_path, job_id=job_id)
            try:
                output_dir.relative_to(self.app_root)
            except ValueError as exc:
                raise ValueError(
                    "Transfer output_dir must be inside the TrafficWM workspace when the "
                    f"resident Docker service is enabled: {output_dir}"
                ) from exc
        payload = {"spec_path": str(spec_path), "output_dir": str(output_dir)}
        if job_id:
            payload["job_id"] = job_id
        return _http_json(f"http://127.0.0.1:{self.transfer_port}/generate", "POST", payload, timeout=3.0)

    def _stage_transfer_spec_for_container(self, spec_path: Path, *, job_id: str) -> Path:
        """Copy host-only Transfer inputs under the workspace's mounted path."""
        if not spec_path.is_file():
            raise FileNotFoundError(f"Transfer spec does not exist: {spec_path}")
        try:
            spec_path.relative_to(self.app_root)
            spec_visible = True
        except ValueError:
            spec_visible = False

        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        safe_job = "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in (job_id or spec_path.stem)
        ).strip("-._") or "transfer-job"
        stage_root = self.output_root / "runtime_inputs" / safe_job
        changed = not spec_visible

        def stage_file(value: Any) -> str:
            nonlocal changed
            source = Path(str(value or "")).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Transfer input does not exist: {source}")
            try:
                source.relative_to(self.app_root)
                return str(source)
            except ValueError:
                pass
            stage_root.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
            target = stage_root / f"{digest}_{source.name}"
            shutil.copy2(source, target)
            if target.stat().st_size != source.stat().st_size:
                raise RuntimeError(f"Transfer input staging was truncated: {source}")
            changed = True
            return str(target.resolve())

        prompt_path = str(spec.get("prompt_path") or "").strip()
        if prompt_path:
            spec["prompt_path"] = stage_file(prompt_path)
        for config in spec.values():
            if not isinstance(config, dict):
                continue
            for media_key in ("control_path", "input_path"):
                if str(config.get(media_key) or "").strip():
                    config[media_key] = stage_file(config[media_key])

        if not changed:
            return spec_path
        stage_root.mkdir(parents=True, exist_ok=True)
        staged_spec = stage_root / "transfer_spec.json"
        temporary = staged_spec.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(staged_spec)
        return staged_spec.resolve()

    def transfer_job(self, job_id: str) -> dict[str, Any]:
        return _http_json(f"http://127.0.0.1:{self.transfer_port}/jobs/{job_id}", timeout=2.0)

    def submit_anchor_transfer(
        self,
        spec_path: Path,
        output_dir: Path,
        job_id: str = "",
    ) -> dict[str, Any]:
        if not self.anchor_transfer_gpus:
            raise RuntimeError("The dedicated anchor Transfer service is disabled")
        spec_path = Path(spec_path).resolve()
        output_dir = Path(output_dir).resolve()
        if self.transfer_container_image:
            spec_path = self._stage_transfer_spec_for_container(
                spec_path,
                job_id=f"anchor-{job_id}" if job_id else "anchor-transfer",
            )
            try:
                output_dir.relative_to(self.app_root)
            except ValueError as exc:
                raise ValueError(
                    "Anchor Transfer output_dir must be inside the TrafficWM workspace "
                    f"when the resident Docker service is enabled: {output_dir}"
                ) from exc
        payload = {"spec_path": str(spec_path), "output_dir": str(output_dir)}
        if job_id:
            payload["job_id"] = job_id
        return _http_json(
            f"http://127.0.0.1:{self.anchor_transfer_port}/generate",
            "POST",
            payload,
            timeout=3.0,
        )

    def anchor_transfer_job(self, job_id: str) -> dict[str, Any]:
        if not self.anchor_transfer_gpus:
            raise RuntimeError("The dedicated anchor Transfer service is disabled")
        return _http_json(
            f"http://127.0.0.1:{self.anchor_transfer_port}/jobs/{job_id}",
            timeout=2.0,
        )

    def render_controls(
        self,
        scene_root: Path,
        output_root: Path,
        *,
        clip_id: str,
        cameras: list[str],
        timeout: float = 1800.0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        arguments = [
            "scripts/generate_control_videos.py",
            "-i",
            str(scene_root.resolve()),
            "-o",
            str(output_root.resolve()),
            "--clip-id",
            clip_id,
            "--cameras",
            ",".join(cameras),
        ]
        if self.transfer_container_image:
            inner = ["/workspace/.venv/bin/python", *arguments]
            container_name = self._container_names.get("transfer", "")
            if not container_name and "transfer" in self._adopted_services:
                container_name = f"trafficwm-transfer-{self.transfer_port}"
            container_running = False
            if container_name:
                inspect = subprocess.run(
                    [
                        "sg",
                        "docker",
                        "-c",
                        shlex.join(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{.State.Running}}",
                                container_name,
                            ]
                        ),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10.0,
                    check=False,
                )
                container_running = inspect.returncode == 0 and inspect.stdout.strip() == "true"
            if container_running:
                docker_command = [
                    "docker", "exec", "--user", f"{os.getuid()}:{os.getgid()}",
                    "-e", "HOME=/tmp", container_name, "bash", "-lc",
                    "cd /workspace && " + shlex.join(inner),
                ]
                renderer_mode = "resident"
            else:
                renderer_gpus = (
                    self.transfer_gpus
                    or _gpu_list(os.environ.get("COSMOS_TRANSFER1_GPUS", ""))
                    or ["0"]
                )
                docker_command = [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--gpus",
                    "all",
                    "--network",
                    "host",
                    "--shm-size",
                    "8g",
                    "-e",
                    f"CUDA_VISIBLE_DEVICES={','.join(renderer_gpus)}",
                    "-e",
                    "PYTHONUNBUFFERED=1",
                    "-e",
                    "HOME=/tmp",
                    "-e",
                    "PYOPENGL_PLATFORM=egl",
                    "-e",
                    f"PYTHONPATH={self.app_root}:/workspace",
                    "-v",
                    f"{self.transfer_container_venv}:/workspace/.venv",
                    "-v",
                    f"{self.transfer_root}:/workspace",
                    "-v",
                    f"{self.app_root}:{self.app_root}",
                    "--entrypoint",
                    "bash",
                    self.transfer_container_image,
                    "-lc",
                    f"export PATH={self.app_root}/backend/cosmos/container_bin:$PATH; "
                    "cd /workspace && exec " + shlex.join(inner),
                ]
                renderer_mode = "one_shot"
            command = ["sg", "docker", "-c", shlex.join(docker_command)]
            cwd = self.app_root
        else:
            command = [str(self.transfer_root / ".venv" / "bin" / "python"), *arguments]
            cwd = self.transfer_root
            renderer_mode = "native"
        result = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stdout[-8000:] or f"Control renderer exited with {result.returncode}")
        return {
            "ok": True,
            "seconds": round(time.perf_counter() - started, 4),
            "mode": renderer_mode,
            "log_tail": result.stdout[-3000:],
        }

    def run_omnidreams(
        self,
        spec_path: Path,
        *,
        timeout: float | None = 14400.0,
        progress_callback=None,
        cancellation_callback=None,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        for key in (
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "grpc_proxy",
            "GRPC_PROXY",
        ):
            env.pop(key, None)
        env["NO_PROXY"] = ",".join(
            item
            for item in [env.get("NO_PROXY", ""), "127.0.0.1", "localhost", "::1"]
            if item
        )
        env["no_proxy"] = env["NO_PROXY"]
        env["GRPC_ARG_ENABLE_HTTP_PROXY"] = "0"
        site_packages = sorted((self.omnidreams_root / ".venv" / "lib").glob("python*/site-packages"))
        python_paths = [
            self.app_root,
            self.omnidreams_root / "flashdreams",
            self.omnidreams_root / "integrations" / "omnidreams",
            self.omnidreams_root / "integrations" / "omnidreams" / "ludus-renderer",
        ]
        env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
        env["PATH"] = os.pathsep.join([str(self.omnidreams_root / ".venv" / "bin"), env.get("PATH", "")])
        env["CXX"] = str(self.app_root / "backend" / "cosmos" / "container_bin" / "cxx20_compat")
        if site_packages:
            cuda_root = site_packages[0] / "nvidia" / "cu13"
            library_dirs = [site_packages[0] / "torch" / "lib", cuda_root / "lib"]
            env["CUDA_HOME"] = str(cuda_root)
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                [*(str(path) for path in library_dirs if path.is_dir()), env.get("LD_LIBRARY_PATH", "")]
            ).rstrip(os.pathsep)
        started = time.perf_counter()
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        output_dir = Path(spec["output_dir"])
        progress_path = output_dir / "progress.json"
        process = subprocess.Popen(
            [
                str(self.omnidreams_root / ".venv" / "bin" / "python"),
                "-m",
                "backend.cosmos.omnidreams_client",
                "--spec",
                str(spec_path.resolve()),
            ],
            cwd=str(self.app_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output_lines: list[str] = []
        if process.stdout is not None:
            os.set_blocking(process.stdout.fileno(), False)
        deadline = (
            time.monotonic() + float(timeout)
            if timeout is not None and float(timeout) > 0.0
            else None
        )
        last_progress_mtime = 0.0
        try:
            while process.poll() is None:
                if cancellation_callback is not None:
                    cancellation_callback()
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError("OmniDreams client timed out")
                if process.stdout is not None:
                    readable, _, _ = select.select([process.stdout], [], [], 0)
                    if readable:
                        chunk = process.stdout.read()
                        if chunk:
                            output_lines.append(chunk)
                            output_lines = output_lines[-400:]
                if progress_callback and progress_path.is_file():
                    try:
                        mtime = progress_path.stat().st_mtime
                        if mtime > last_progress_mtime:
                            progress_callback(json.loads(progress_path.read_text(encoding="utf-8")))
                            last_progress_mtime = mtime
                    except (OSError, ValueError, TypeError):
                        pass
                time.sleep(0.5)
        except BaseException:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=30.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10.0)
            raise
        if process.stdout is not None:
            remainder = process.stdout.read()
            if remainder:
                output_lines.append(remainder)
        if process.returncode != 0:
            raise RuntimeError("".join(output_lines)[-8000:] or f"OmniDreams client exited with {process.returncode}")
        manifest_path = output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["client_end_to_end_seconds"] = round(time.perf_counter() - started, 4)
        return manifest

    def restart(self) -> None:
        """Restart both resident services after a pre-request runtime failure."""
        self.close()
        self.enabled = True
        self.start()

    def close(self) -> None:
        with self._lock:
            for service, port in (
                ("transfer", self.transfer_port),
                ("anchor_transfer", self.anchor_transfer_port),
            ):
                process = self._processes.get(service)
                if process is not None and process.poll() is None:
                    _http_json(
                        f"http://127.0.0.1:{port}/shutdown",
                        "POST",
                        {},
                        timeout=1.0,
                    )
            processes = list(self._processes.items())
        for _name, process in processes:
            if process.poll() is not None:
                continue
            descendants = _linux_descendant_pids(process.pid)
            try:
                # torchrun ranks create independent sessions. Signal them
                # before the launcher exits and reparents them to PID 1.
                for descendant in reversed(descendants):
                    try:
                        os.kill(descendant, signal.SIGINT)
                    except OSError:
                        pass
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=20.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for descendant in reversed(descendants):
                try:
                    os.kill(descendant, 0)
                except OSError:
                    continue
                try:
                    os.kill(descendant, signal.SIGKILL)
                except OSError:
                    pass
        for container_name in self._container_names.values():
            subprocess.run(
                ["sg", "docker", "-c", shlex.join(["docker", "rm", "-f", container_name])],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15.0,
                check=False,
            )
        with self._lock:
            for log in self._logs.values():
                try:
                    log.close()
                except OSError:
                    pass
            self._logs.clear()
            self._processes.clear()
            self._container_names.clear()
            self._adopted_services.clear()
            self._adopted_omnidreams_metadata = {}
