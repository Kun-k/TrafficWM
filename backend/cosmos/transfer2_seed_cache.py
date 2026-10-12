"""Content-addressed cache for deterministic Transfer2.5 world seeds."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any


SCHEMA = "denseworld.transfer2.5-seed-cache.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_identity(spec_path: Path) -> tuple[str, dict[str, Any], dict[str, Any]]:
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    settings: dict[str, Any] = {}
    controls: dict[str, dict[str, Any]] = {}
    for key, value in spec.items():
        if key == "name":
            continue
        if key == "prompt_path":
            prompt_path = Path(str(value)).expanduser().resolve()
            settings["prompt"] = prompt_path.read_text(encoding="utf-8")
            continue
        if isinstance(value, dict) and value.get("control_path"):
            control_path = Path(str(value["control_path"])).expanduser().resolve()
            controls[key] = {
                "sha256": _sha256(control_path),
                "size_bytes": int(control_path.stat().st_size),
            }
            continue
        settings[key] = value
    identity = {
        "schema": SCHEMA,
        "model": "auto/multiview",
        "settings": settings,
        "controls": controls,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), identity, spec


def default_cache_root(repository_root: Path) -> Path:
    return Path(
        os.environ.get(
            "COSMOS_TRANSFER2_SEED_CACHE_DIR",
            str(Path(repository_root).resolve() / "output/cosmos/cache/transfer2_seed"),
        )
    ).expanduser().resolve()


def restore(
    spec_path: Path,
    output_dir: Path,
    cache_root: Path,
) -> dict[str, Any] | None:
    cache_key, identity, spec = cache_identity(spec_path)
    cache_dir = Path(cache_root).resolve() / cache_key
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    views = sorted(identity["controls"])
    if manifest.get("identity") != identity or manifest.get("views") != views:
        return None
    cached_outputs = {view: cache_dir / f"{view}.mp4" for view in views}
    if not all(path.is_file() and path.stat().st_size > 0 for path in cached_outputs.values()):
        return None

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = str(spec.get("name") or "").strip()
    if not name:
        return None
    outputs = []
    for view, source in cached_outputs.items():
        target = output_dir / f"{name}_{view}.mp4"
        shutil.copy2(source, target)
        outputs.append(str(target))
    return {
        "cache_hit": True,
        "cache_key": cache_key,
        "cache_manifest": str(manifest_path),
        "outputs": outputs,
    }


def store(
    spec_path: Path,
    output_dir: Path,
    cache_root: Path,
) -> dict[str, Any]:
    cache_key, identity, spec = cache_identity(spec_path)
    views = sorted(identity["controls"])
    name = str(spec.get("name") or "").strip()
    output_dir = Path(output_dir).resolve()
    sources = {view: output_dir / f"{name}_{view}.mp4" for view in views}
    missing = [str(path) for path in sources.values() if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise FileNotFoundError("Transfer2.5 cache source is incomplete: " + ", ".join(missing))

    cache_root = Path(cache_root).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_dir = cache_root / cache_key
    manifest_path = cache_dir / "manifest.json"
    if manifest_path.is_file():
        return {
            "cache_hit": False,
            "cache_key": cache_key,
            "cache_manifest": str(manifest_path),
            "already_stored": True,
        }

    temporary = cache_root / f".{cache_key}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True)
    try:
        for view, source in sources.items():
            shutil.copy2(source, temporary / f"{view}.mp4")
        (temporary / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "cache_key": cache_key,
                    "identity": identity,
                    "views": views,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            temporary.replace(cache_dir)
        except FileExistsError:
            pass
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "cache_hit": False,
        "cache_key": cache_key,
        "cache_manifest": str(cache_dir / "manifest.json"),
        "already_stored": False,
    }
