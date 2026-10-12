## Clone This Repository

```
git clone https://github.com/THU-AI-Testing/CityNDE_bin.git
cd CityNDE_bin
```

## Setup Environment
Run the following commands in CityNDE working directory:
```
conda env create -f environment.yml
conda activate cnde
pip install -e .
```
Setup nuplan and tuplan dependency based on the official repositories:

```
git clone git@github.com:motional/nuplan-devkit.git
cd nuplan-devkit
pip install -e .
cd ..
git clone git@github.com:autonomousvision/tuplan_garage.git
cd tuplan_garage
pip install -e .
```

Update scikit-learn for CityNDE environment:
```
pip install scikit-learn -U
```
Although latest version of scikit may be incompatible with tuplan_garage, it works well in cnde environment.

## Download Assets
DownLoad checkpoints, map and other assets with Tsinghua VPN and run
```
wget 166.111.73.90/cnde/assets.tar.gz
tar -xvf assets.tar.gz
```
Then your file structure will look like
```
CityNDE_bin/
|__ assets
|______ ...
|__ cnde
|______ ...
|__ csim
|______ ...
|__ cutils
|______ ...
|__ nuplan-devkit
|______ ...
|__ scripts
|______ ...
|__ tuplan_garage
|______ ...
|__ ...
```

## Use CityNDE to Simulate
Run CityNDE with python scripts in ```./scripts``` folder.

We provide 2 ways to use CityNDE (see ```cnde_main.py``` and ```cnde_part.py```). Scenarios are saved in  ```./output```. Run ```view_scenario.py``` to make videos.
```
cd scripts
python cnde_main.py
python cnde_part.py
python view_scenario.py
```

## Customize CityNDE
### Change Simulation Area
CityNDE reads configs and related files in ```./assets```. Add new pickle map to ```./assets/map``` and change python scripts accordingly to change simulation area. Refer to provided map file for the format. 

[Optional] Change intention_prior files in ```./assets/intention_priors``` and update config in ```./assets/config``` with new intention priors. Modify the config file path in scripts accordingly.

### Change Simulation Logic
We provide source code of CityNDE simulator and controller in the following files:
```
./csim/simulator/simulator.py
./csim/controller/controller.py
```
Customize simulation logic as you need.
## Interactive UI (Pause-Driven Editing)

The interactive UI is available in `scripts/cnde_interactive.py` and runs in a browser.

### Start

Run from workspace root:

```bash
python scripts/cnde_interactive.py \
  --map_path assets/map/your_map.pkl \
  --viewer_mode region_full \
  --port 8890 \
  --default_spawn_speed 2.0
```

Open:

```text
http://localhost:8890
```

### Pause/Resume Rule

You can pause/resume directly from UI (`Pause` / `Resume`).

Action availability:

- Always allowed (running or paused):
- `set_rate` (arrival rate update)
- `toggle_vehicle_id` (show/hide vehicle id)
- Paused only:
- map switch
- all add/remove operations
- click-to-spawn
- click-to-delete
- advanced pkl operations

The paused-only rule is enforced in both frontend and backend.

### Features in UI

- Map switch from `assets/map/*.pkl`
- Arrival rate update:
- set all start lanes by using `lane_id = all`
- set one lane by specific `lane_id`
- Add vehicle by coordinate:
- moving or static
- moving speed configurable in UI
- heading in radians
- Remove vehicle by id
- Click mode:
- `Spawn On Click`: spawn at nearest lane center point with lane heading
- `Delete On Click`: click vehicle box to remove
- Display toggle:
- show/hide id text at vehicle box center
- Advanced PKL:
- add new vehicle(s) from pkl
- inject future `n`-step behavior for vehicle(s)

### Click Spawn Behavior

For moving spawn from click:

- pose is projected to nearest lane center point
- heading is aligned to lane centerline heading
- velocity is set from UI speed and lane heading
- history warm-up uses `history_step` frames (default 11), consistent with `generate_agent` style initialization

### Advanced PKL Formats

#### 1) Existing scenario format (compatible)

Supported keys:

- `vehicle_id_per_step`
- `vehicle_state_per_step`
- `vehicle_static_attribute` (optional)

Example structure:

```python
{
  "vehicle_id_per_step": [
    [1001, 1002],
    [1001, 1002],
    [1001, 1003]
  ],
  "vehicle_state_per_step": [
    # each row: [x, y, heading, vx, vy, ax, ay]
    np.array([[10.0, 20.0, 0.1, 2.0, 0.0, 0.0, 0.0],
              [12.0, 21.0, 0.2, 1.0, 0.0, 0.0, 0.0]], dtype=float),
    np.array([[10.2, 20.0, 0.1, 2.0, 0.0, 0.0, 0.0],
              [12.1, 21.0, 0.2, 1.0, 0.0, 0.0, 0.0]], dtype=float),
    np.array([[10.4, 20.0, 0.1, 2.0, 0.0, 0.0, 0.0],
              [13.0, 22.0, 0.3, 1.5, 0.0, 0.0, 0.0]], dtype=float),
  ],
  "vehicle_static_attribute": {
    1001: [3.8, 1.8, 1.5],
    1002: [4.2, 1.9, 1.6]
  }
}
```

Notes:

- state dimension must be at least 7
- `advanced_add_from_pkl` imports vehicle history from this file
- `advanced_control_from_pkl` reads future steps from `current_step + 1`

#### 2) Simplified ops format

Top-level `ops` list is supported.

Example:

```python
{
  "ops": [
    {
      "type": "add",
      "vehicle_id": 2001,
      "static": False,
      "static_lwh": [3.8, 1.8, 1.5],
      "states": [
        [30.0, -5.0, 1.57, 2.0, 0.0, 0.0, 0.0],
        [30.2, -5.0, 1.57, 2.0, 0.0, 0.0, 0.0],
        [30.4, -5.0, 1.57, 2.0, 0.0, 0.0, 0.0]
      ]
    },
    {
      "type": "control",
      "vehicle_id": 1001,
      "states": [
        [11.0, 20.0, 0.1, 3.0, 0.0, 0.0, 0.0],
        [11.3, 20.0, 0.1, 3.0, 0.0, 0.0, 0.0],
        [11.6, 20.0, 0.1, 3.0, 0.0, 0.0, 0.0]
      ]
    }
  ]
}
```

Notes:

- `type=add` is used by `Add From PKL`
- `type=control` is used by `Control From PKL`
- only first 7 columns are consumed
- `horizon` in UI truncates control sequence length

### Security Constraint

Map switching is restricted to files under `assets/map/`.

Access to `../CityNDE_bin` is blocked by path validation and is not used by this UI workflow.
