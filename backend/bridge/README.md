# CARLA 0.9.16 integration

`carla_gateway.py` isolates CARLA's Python API and rendering workload from the
TrafficWM manager and algorithm environments. It consumes the child adapter's
latest `/sim_state` snapshot, mirrors actors into CARLA, and exposes the latest
camera frame through the authenticated manager API.

The gateway is started lazily when a scene-generation request contains
`enable_3d_simulation=true`. CARLA RPC remains bound to the server; browsers
only access `/api/v1/carla/status`, `/api/v1/carla/frame.jpg`, and
`/api/v1/carla/focus` through TrafficWM.

Runtime defaults:

- CARLA package: `/data/rk/cnde/CARLA_0.9.16`
- Python environment: `envs/carla`
- Gateway: `127.0.0.1:8892`
- CARLA RPC: `127.0.0.1:2000`
- Rendering: off-screen, Epic quality, 1280 x 720 camera
- Visualization tick: capped at 15 FPS by default
- Environment objects: capped at 450 by default

Run `scripts/setup_carla_0916.sh` to prepare the package and Python
environment. `scripts/run_manager.sh` passes the configured paths to the
manager.
