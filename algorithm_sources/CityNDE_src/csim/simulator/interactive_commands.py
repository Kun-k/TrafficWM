from __future__ import annotations
import shlex
from dataclasses import dataclass, field


'''
>>> help                           # 查看所有命令

>>> map assets/map/new_map.pkl     # 更换地图

>>> rate 42 0.1                    # 设置 lane 42 的到达率为 0.1

>>> add 100.5 200.3 1.57           # 在 (100.5, 200.3) 添加车辆，朝向 1.57
>>> add 100.5 200.3 1.57 --static  # 添加静止车辆（不受控制器控制）

>>> remove 315                     # 删除 ID=315 的车辆

>>> view overview                  # 切换到全局概览点状视图
>>> view region 100 200            # 切换到以 (100,200) 为中心的局部细节视图
>>> view region_full               # 切换到全图细节视图（可在网页端拖拽/缩放）

>>> status                         # 查看当前状态
'''


@dataclass
class Command:
    kind: str = "noop"
    args: dict = field(default_factory=dict)


def parse_command(raw: str) -> Command:
    raw = raw.strip()
    if not raw:
        return Command("noop")

    parts = shlex.split(raw)
    cmd = parts[0].lower()
    rest = parts[1:]

    if cmd in ("help", "h", "?"):
        return Command("help")

    if cmd in ("resume", "r"):
        return Command("resume")

    if cmd in ("quit", "q"):
        return Command("quit")

    if cmd == "status":
        return Command("status")

    if cmd == "step":
        n = int(rest[0]) if rest else 1
        return Command("step", {"n": n})

    if cmd == "map":
        if not rest:
            print("Usage: map <path_to_pkl>")
            return Command("noop")
        return Command("map", {"path": rest[0]})

    if cmd == "rate":
        if len(rest) < 2:
            print("Usage: rate <lane_id> <probability>")
            return Command("noop")
        try:
            lane_id = int(rest[0])
        except ValueError:
            lane_id = rest[0]
        prob = float(rest[1])
        return Command("rate", {"lane_id": lane_id, "prob": prob})

    if cmd == "add":
        return _parse_add(rest)

    if cmd == "remove":
        if not rest:
            print("Usage: remove <vehicle_id>")
            return Command("noop")
        try:
            vid = int(rest[0])
        except ValueError:
            vid = rest[0]
        return Command("remove", {"vehicle_id": vid})

    if cmd == "view":
        return _parse_view(rest)

    print(f"Unknown command: '{cmd}'. Type 'help' for available commands.")
    return Command("noop")


def _parse_add(rest: list[str]) -> Command:
    """Parse: add <x> <y> <heading> [vx] [vy] [--static] [--length L] [--width W] [--height H]"""
    if len(rest) < 3:
        print("Usage: add <x> <y> <heading> [vx] [vy] [--static] [--length L] [--width W] [--height H]")
        return Command("noop")

    args = {
        "x": float(rest[0]),
        "y": float(rest[1]),
        "heading": float(rest[2]),
        "vx": 0.,
        "vy": 0.,
        "static": False,
        "length": 3.8,
        "width": 1.8,
        "height": 1.5,
    }

    i = 3
    if i < len(rest) and not rest[i].startswith("--"):
        args["vx"] = float(rest[i])
        i += 1
    if i < len(rest) and not rest[i].startswith("--"):
        args["vy"] = float(rest[i])
        i += 1

    while i < len(rest):
        flag = rest[i]
        if flag == "--static":
            args["static"] = True
            i += 1
        elif flag == "--length" and i + 1 < len(rest):
            args["length"] = float(rest[i + 1])
            i += 2
        elif flag == "--width" and i + 1 < len(rest):
            args["width"] = float(rest[i + 1])
            i += 2
        elif flag == "--height" and i + 1 < len(rest):
            args["height"] = float(rest[i + 1])
            i += 2
        else:
            print(f"Unknown flag or missing value: {flag}")
            i += 1

    return Command("add", args)


def _parse_view(rest: list[str]) -> Command:
    """Parse: view overview | view region <x> <y> | view region_full"""
    if not rest:
        print("Usage: view overview | view region <x> <y> | view region_full")
        return Command("noop")

    sub = rest[0].lower()
    if sub == "overview":
        return Command("view", {"mode": "overview"})
    if sub == "region_full":
        return Command("view", {"mode": "region_full"})
    if sub == "region":
        if len(rest) < 3:
            print("Usage: view region <x> <y>")
            return Command("noop")
        return Command("view", {
            "mode": "region",
            "x": float(rest[1]),
            "y": float(rest[2]),
        })

    print(f"Unknown view mode: '{sub}'. Use 'overview', 'region', or 'region_full'.")
    return Command("noop")


HELP_TEXT = """
Available commands:
  map <path>                         - Reload map from a new .pkl file
  rate <lane_id> <probability>       - Set arrival rate for a start lane (0.0-1.0)
  add <x> <y> <heading> [vx] [vy]   - Add a vehicle at position (x, y) with heading
       [--static]                      Options: --static (vehicle stays still)
       [--length L] [--width W]                 --length, --width, --height
       [--height H]
  remove <vehicle_id>                - Remove a vehicle by its ID
  view overview                      - Switch to overview mode
  view region <x> <y>                - Switch to region-centric mode centered at (x, y)
  view region_full                   - Switch to full-map detail mode
  status                             - Print simulation status
  step [n]                           - Advance n steps (default 1) then pause again
  resume / r                         - Resume continuous simulation
  quit / q                           - Stop simulation
  help / h / ?                       - Show this help message
"""
