# Algorithm sources

This directory contains source trees that belong to the TrafficWM workspace.
Platform integration code lives under `backend/algorithms`; it is not mixed
into upstream model repositories.

- `CityNDE_src/`: active CityNDE source used by the manager.
- `CityNDE/`: retained legacy CityNDE checkout for reference only.
- NeuralNDE: `/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment` by default.

NeuralNDE remains a separate Git checkout because it has its own upstream
history, Python 3.9 environment, datasets, and model checkpoints. The manager
discovers it through `NEURALNDE_ROOT`; no second source copy is needed here.

TeraSim and Highway Law-NADE-VTD were removed from the active model set. Their
historical generated data, where present, is read-only under `output/legacy/`.

All new runtime data belongs under the repository-level `output/` directory.
Source checkouts must not create independent output stores.
