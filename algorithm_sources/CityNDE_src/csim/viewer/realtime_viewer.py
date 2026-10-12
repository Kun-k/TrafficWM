from __future__ import annotations

from typing import Literal

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

from cutils import get_rotated_box


class RealtimeViewer:
    def __init__(
        self,
        map_ref,
        window_name: str = "CityNDE Realtime",
        mode: Literal["overview", "region", "region_full"] = "overview",
        region_center: np.ndarray | None = None,
        roi_radius: float = 180.0,
        video_dpi: int = 1200,
        image_size: int = 1024,
    ):
        self.map_ref = map_ref
        self.window_name = window_name
        self.mode = mode
        self.region_center = region_center
        self.roi_radius = roi_radius
        self.video_dpi = video_dpi
        self.image_size = image_size
        self._video_writer = None
        self.plot_id = False

        self._overview_cache: np.ndarray | None = None
        self._region_cache: np.ndarray | None = None
        self._region_cache_center: np.ndarray | None = None
        self._region_full_cache: np.ndarray | None = None

        self._region_tl_signature: tuple | None = None
        self._region_full_tl_signature: tuple | None = None

        self._map_bounds: tuple | None = None  # (cx, cy, hx, hy)

        self.vehicle_color = (255, 160, 50)
        self.static_vehicle_color = (0, 0, 200)
        self.default_lwh = np.array([3.8, 1.8, 1.5])

        self._compute_map_bounds()

    def render_frame_from_snapshot(
        self,
        current_step: int,
        valid_ids: np.ndarray,
        valid_states: np.ndarray,
        valid_statics: np.ndarray,
        static_vehicle_ids: set | None = None,
        tl_type_by_id: dict | None = None,
    ) -> np.ndarray:
        if self.mode == "overview":
            base = self._get_overview_base()
        elif self.mode == "region":
            base = self._get_region_base(tl_type_by_id=tl_type_by_id)
        elif self.mode == "region_full":
            base = self._get_region_full_base(tl_type_by_id=tl_type_by_id)
        else:
            raise ValueError(f"Unknown viewer mode: {self.mode}")

        frame = base.copy()

        if valid_ids is None or len(valid_ids) == 0:
            self._draw_info(frame, current_step, 0)
            return frame

        if self.mode == "overview":
            self._draw_vehicles_overview(frame, valid_ids, valid_states, static_vehicle_ids)
        elif self.mode == "region":
            self._draw_vehicles_region(
                frame,
                valid_ids,
                valid_states,
                valid_statics,
                static_vehicle_ids,
            )
        else:
            self._draw_vehicles_region_full(
                frame,
                valid_ids,
                valid_states,
                valid_statics,
                static_vehicle_ids,
            )

        self._draw_info(frame, current_step, len(valid_ids))
        return frame

    def switch_mode(
        self,
        mode: Literal["overview", "region", "region_full"],
        region_center: np.ndarray | None = None,
    ):
        self.mode = mode
        if region_center is not None:
            self.region_center = np.array(region_center, dtype=float)
            self._region_cache = None

    def invalidate_map_cache(self):
        self._overview_cache = None
        self._region_cache = None
        self._region_full_cache = None
        self._region_tl_signature = None
        self._region_full_tl_signature = None
        self._map_bounds = None
        self._compute_map_bounds()

    def image_pixel_to_world(self, px: float, py: float) -> np.ndarray:
        """Convert image pixel coordinates (without viewport transform) to world x,y."""
        if self.mode == "overview":
            cx, cy, hx, hy = self._map_bounds
            w, h = self.get_mode_canvas_size("overview")
            x = (float(px) / max(float(w), 1.0)) * (2.0 * hx) + (cx - hx)
            y = (cy + hy) - (float(py) / max(float(h), 1.0)) * (2.0 * hy)
            return np.array([x, y], dtype=float)

        if self.mode == "region":
            if self.region_center is None:
                cx, cy, _, _ = self._map_bounds
                self.region_center = np.array([cx, cy], dtype=float)
            c = self.region_center
            r = float(self.roi_radius)
            s = float(self.image_size)
            x = (float(px) / s) * (2.0 * r) + (c[0] - r)
            y = (c[1] + r) - (float(py) / s) * (2.0 * r)
            return np.array([x, y], dtype=float)

        cx, cy, hx, hy = self._map_bounds
        w, h = self.get_mode_canvas_size("region_full")
        x = (float(px) / max(float(w), 1.0)) * (2.0 * hx) + (cx - hx)
        y = (cy + hy) - (float(py) / max(float(h), 1.0)) * (2.0 * hy)
        return np.array([x, y], dtype=float)

    def _compute_map_bounds(self):
        all_points = []
        for pid in self.map_ref.polyline_ids:
            p = self.map_ref.polyline_dict[pid]
            all_points.append(p.points)

        assert len(all_points) != 0, "Map has no polylines."

        all_points = np.concatenate(all_points, axis=0)
        inf_pt = np.min(all_points, axis=0)[:2]
        sup_pt = np.max(all_points, axis=0)[:2]
        center = (inf_pt + sup_pt) / 2.0
        half = (sup_pt - inf_pt) / 2.0
        hx = float(max(half[0] * 1.05, 1e-3))
        hy = float(max(half[1] * 1.05, 1e-3))

        self._map_bounds = (center[0], center[1], hx, hy)

    def _aspect_canvas_size(self, span_x: float, span_y: float) -> tuple[int, int]:
        span_x = max(float(span_x), 1e-6)
        span_y = max(float(span_y), 1e-6)
        scale = float(self.image_size) / max(span_x, span_y)
        w = max(1, int(round(span_x * scale)))
        h = max(1, int(round(span_y * scale)))
        return w, h

    def get_mode_canvas_size(self, mode: str | None = None) -> tuple[int, int]:
        m = self.mode if mode is None else str(mode)
        if m in ("overview", "region_full"):
            _, _, hx, hy = self._map_bounds
            return self._aspect_canvas_size(2.0 * hx, 2.0 * hy)
        return int(self.image_size), int(self.image_size)

    @staticmethod
    def _tl_signature(tl_type_by_id: dict | None) -> tuple:
        if not tl_type_by_id:
            return tuple()
        return tuple(
            sorted(((str(k), int(v)) for k, v in tl_type_by_id.items()), key=lambda x: x[0])
        )

    @staticmethod
    def _lane_color(polyline_type: int, polyline_id, tl_type_by_id: dict | None):
        polyline_color = {0: "white", 1: "dimgray", 2: "black", 3: "gray", 4: "white"}
        tl_polyline_color = {0: "green", 1: "yellow", 2: "red", 3: "gray"}
        if polyline_type == 4 and tl_type_by_id is not None and polyline_id in tl_type_by_id:
            return tl_polyline_color.get(int(tl_type_by_id[polyline_id]), polyline_color[4])
        return polyline_color.get(polyline_type, "gray")

    def _get_overview_base(self) -> np.ndarray:
        if self._overview_cache is not None:
            return self._overview_cache

        cx, cy, hx, hy = self._map_bounds
        w, h = self.get_mode_canvas_size("overview")
        base = np.full((h, w, 3), 230, dtype=np.uint8)

        color_map = {
            0: (255, 255, 255),
            1: (169, 169, 169),
            2: (0, 0, 0),
            3: (128, 128, 128),
            4: (255, 255, 255),
        }
        thickness_map = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}

        for pid in self.map_ref.polyline_ids:
            p = self.map_ref.polyline_dict[pid]
            p_type = p.type
            if p_type not in (0, 1, 2, 3):
                continue
            pts = p.points[:, :2]
            if pts.shape[0] < 2:
                continue
            pts_px = [self._world_to_pixel_overview(x, y, cx, cy, hx, hy, w, h) for x, y in pts]
            color = color_map.get(p_type, (128, 128, 128))
            thick = thickness_map.get(p_type, 1)
            for i in range(len(pts_px) - 1):
                if p_type == 3 and i % 2 == 1:
                    continue
                cv2.line(base, pts_px[i], pts_px[i + 1], color, thick)

        self._overview_cache = base
        return self._overview_cache

    def _world_to_pixel_overview(self, x, y, cx, cy, hx, hy, w, h):
        px = int((x - (cx - hx)) / max(2 * hx, 1e-6) * w)
        py = int(((cy + hy) - y) / max(2 * hy, 1e-6) * h)
        return (px, py)

    def _draw_vehicles_overview(self, frame, valid_ids, valid_states, static_vehicle_ids):
        cx, cy, hx, hy = self._map_bounds
        h, w = frame.shape[:2]
        static_set = static_vehicle_ids or set()

        for vid, state in zip(valid_ids, valid_states):
            x, y = state[0], state[1]
            px, py = self._world_to_pixel_overview(x, y, cx, cy, hx, hy, w, h)
            color = self.static_vehicle_color if vid in static_set else self.vehicle_color
            cv2.circle(frame, (px, py), 3, color, -1)

    def _get_region_base(self, tl_type_by_id: dict | None = None) -> np.ndarray:
        if self.region_center is None:
            cx, cy, _, _ = self._map_bounds
            self.region_center = np.array([cx, cy])

        center = self.region_center
        tl_sig = self._tl_signature(tl_type_by_id)
        if (
            self._region_cache is not None
            and self._region_cache_center is not None
            and np.allclose(center, self._region_cache_center)
            and self._region_tl_signature == tl_sig
        ):
            return self._region_cache

        x_min = center[0] - self.roi_radius
        x_max = center[0] + self.roi_radius
        y_min = center[1] - self.roi_radius
        y_max = center[1] + self.roi_radius

        fig = plt.figure(dpi=self.video_dpi, facecolor="lightgray")
        ax = fig.add_subplot([0, 0, 1, 1])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.axis("off")

        polyline_style = {0: "dashed", 1: "solid", 2: "solid", 3: "dashed", 4: "dashed"}
        polyline_width = {0: 0.5, 1: 0.5, 2: 0.8, 3: 0.5, 4: 0.5}

        for pid in self.map_ref.polyline_ids:
            p = self.map_ref.polyline_dict[pid]
            p_type = p.type
            pts = p.points[:, :2]
            dist = np.linalg.norm(pts - center[None, :], axis=-1)
            if not np.any(dist < self.roi_radius):
                continue
            mask = dist < self.roi_radius
            color = self._lane_color(p_type, pid, tl_type_by_id)
            ax.plot(
                pts[mask, 0],
                pts[mask, 1],
                color=color,
                linestyle=polyline_style[p_type],
                linewidth=polyline_width[p_type],
                zorder=0,
            )

        canvas = FigureCanvas(fig)
        canvas.draw()
        width, height = fig.canvas.get_width_height()
        img_rgba = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape(height, width, 4)
        img_bgr = cv2.cvtColor(img_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
        plt.close(fig)

        img_bgr = cv2.resize(img_bgr, (self.image_size, self.image_size))

        self._region_cache = img_bgr
        self._region_cache_center = center.copy()
        self._region_tl_signature = tl_sig

        return self._region_cache

    def _get_region_full_base(self, tl_type_by_id: dict | None = None) -> np.ndarray:
        tl_sig = self._tl_signature(tl_type_by_id)
        if self._region_full_cache is not None and self._region_full_tl_signature == tl_sig:
            return self._region_full_cache

        cx, cy, hx, hy = self._map_bounds
        x_min = cx - hx
        x_max = cx + hx
        y_min = cy - hy
        y_max = cy + hy

        fig = plt.figure(dpi=self.video_dpi, facecolor="lightgray")
        ax = fig.add_subplot([0, 0, 1, 1])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.axis("off")

        polyline_style = {0: "dashed", 1: "solid", 2: "solid", 3: "dashed", 4: "dashed"}
        polyline_width = {0: 0.05, 1: 0.05, 2: 0.1, 3: 0.05, 4: 0.05}

        for pid in self.map_ref.polyline_ids:
            p = self.map_ref.polyline_dict[pid]
            p_type = p.type
            pts = p.points[:, :2]
            color = self._lane_color(p_type, pid, tl_type_by_id)
            ax.plot(
                pts[:, 0],
                pts[:, 1],
                color=color,
                linestyle=polyline_style[p_type],
                linewidth=polyline_width[p_type],
                zorder=0,
            )

        canvas = FigureCanvas(fig)
        canvas.draw()
        width, height = fig.canvas.get_width_height()
        img_rgba = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape(height, width, 4)
        img_bgr = cv2.cvtColor(img_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
        plt.close(fig)

        w, h = self.get_mode_canvas_size("region_full")
        self._region_full_cache = cv2.resize(img_bgr, (w, h))
        self._region_full_tl_signature = tl_sig

        return self._region_full_cache

    def _world_to_pixel_region(self, x, y):
        center = self.region_center
        r = self.roi_radius
        s = self.image_size
        px = int((x - (center[0] - r)) / (2 * r) * s)
        py = int(((center[1] + r) - y) / (2 * r) * s)
        return (px, py)

    def _world_to_pixel_region_full(self, x, y):
        cx, cy, hx, hy = self._map_bounds
        w, h = self.get_mode_canvas_size("region_full")
        px = int((x - (cx - hx)) / max(2 * hx, 1e-6) * w)
        py = int(((cy + hy) - y) / max(2 * hy, 1e-6) * h)
        return (px, py)

    def _draw_vehicles_region(self, frame, valid_ids, valid_states, valid_statics, static_vehicle_ids):
        center = self.region_center
        r = self.roi_radius
        static_set = static_vehicle_ids or set()

        dists = np.linalg.norm(valid_states[:, :2] - center[None, :], axis=-1)
        in_roi = dists < r

        roi_ids = valid_ids[in_roi]
        roi_states = valid_states[in_roi]
        roi_statics = valid_statics[in_roi]

        if len(roi_ids) == 0:
            return

        boxes = get_rotated_box(
            roi_states[:, 0],
            roi_states[:, 1],
            roi_statics[:, 0],
            roi_statics[:, 1],
            roi_states[:, 2],
        )

        for vid, box in zip(roi_ids, boxes):
            pts_px = np.array([self._world_to_pixel_region(bx, by) for bx, by in box], dtype=np.int32)
            color = self.static_vehicle_color if vid in static_set else self.vehicle_color
            cv2.fillPoly(frame, [pts_px], color)
            cv2.polylines(frame, [pts_px], True, (0, 0, 0), 1)

        if self.plot_id:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.3
            thickness = 1
            for vid, state in zip(roi_ids, roi_states):
                px, py = self._world_to_pixel_region(state[0], state[1])
                label = str(vid)
                (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
                # putText uses bottom-left anchor, so shift by half text size to center on box center
                org = (int(px - tw / 2), int(py + th / 2 - baseline / 2))
                cv2.putText(frame, label, org, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _draw_vehicles_region_full(self, frame, valid_ids, valid_states, valid_statics, static_vehicle_ids):
        static_set = static_vehicle_ids or set()

        boxes = get_rotated_box(
            valid_states[:, 0],
            valid_states[:, 1],
            valid_statics[:, 0],
            valid_statics[:, 1],
            valid_states[:, 2],
        )

        for vid, box in zip(valid_ids, boxes):
            pts_px = np.array([self._world_to_pixel_region_full(bx, by) for bx, by in box], dtype=np.int32)
            color = self.static_vehicle_color if vid in static_set else self.vehicle_color
            cv2.fillPoly(frame, [pts_px], color)
            cv2.polylines(frame, [pts_px], True, (0, 0, 0), 1)

        if self.plot_id:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.3
            thickness = 1
            for vid, state in zip(valid_ids, valid_states):
                px, py = self._world_to_pixel_region_full(state[0], state[1])
                label = str(vid)
                (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
                # putText uses bottom-left anchor, so shift by half text size to center on box center
                org = (int(px - tw / 2), int(py + th / 2 - baseline / 2))
                cv2.putText(frame, label, org, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _draw_info(self, frame, current_step: int, vehicle_count: int):
        info = f"Step: {current_step}  Vehicles: {vehicle_count}"
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 12
        thickness = 20
        (tw, th), baseline = cv2.getTextSize(info, font, font_scale, thickness)
        margin = 200
        org = (max(margin, w - tw - margin), max(th + margin, th + baseline ))
        cv2.putText(frame, info, org, font, font_scale, (0, 0, 0), thickness * 2, cv2.LINE_AA)
        cv2.putText(frame, info, org, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
