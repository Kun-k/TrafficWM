# GUI 网络接口规范

本目录定义 `GUI` 前端与统一后端管理服务的数据交互规范。  
浏览器访问管理服务的同一个 HTTP 入口，管理服务再负责调度 CityNDE 或 NeuralNDE 子进程。

## 1. 配置文件

路径：`GUI/config/backend.config.json`

字段：

- `protocol`: 协议（如 `http`）
- `host`: 后端地址（如 `127.0.0.1`）
- `port`: 后端端口（如 `8890`）
- `statusPath`: 状态拉取路径
- `actionPath`: 动作提交路径
- `mapsPath`: 地图列表路径
- `scenariosPath`: 回放场景列表路径
- `dataRecordsPath`: 数据管理列表路径
- `dataActionPath`: 数据管理动作路径
- `framePath`: 地图/视图帧路径
- `requestTimeoutMs`: 请求超时（毫秒）

## 2. 通信协议约定

- 传输方式：HTTP
- 数据格式：`application/json`（图片接口除外）
- API 前缀：`/api/v1`
- 前端所有控制操作统一走 `POST actionPath`，不做本地直改后端状态
- 实验详情页通过 `/proxy/<experiment_id>/api/v1/...` 访问对应子进程，公网或局域网部署时只需要暴露管理服务端口
- 典型请求头：`Content-Type: application/json`

## 3. 核心端点

请以 `endpoints.json` 为机器可读规范，关键端点如下：

1. `GET /api/v1/status`：实时状态（管理端或子实验状态）
2. `GET /api/v1/maps?backend_model=cnde|neuralnde`：可用地图或 NeuralNDE 数据集列表
3. `POST /api/v1/action`：动作通道（启动实验、启动回放、终止、删除、到达率、车辆增删）
4. `GET /api/v1/map_state`：矢量地图状态
5. `GET /api/v1/sim_state`：实时交通流状态
6. `GET /api/v1/metrics`：实时或回放指标
7. `GET /api/v1/scenarios`：回放场景路径列表
8. `GET /api/v1/data/scenarios`：回放数据库文件元数据列表
9. `POST /api/v1/data/action`：数据管理动作通道

## 4. 动作类型（`POST /action`）

统一字段：`type` + 业务载荷。

- `start_experiment`：支持 `backend_model=cnde|neuralnde`；CityNDE 支持 `init_mode=random_tl_only|random|empty|data|data_random_tl`；`data` / `data_random_tl` 需要 `init_file`
- `start_playback`
- `terminate_experiment`
- `delete_experiment` / `delete_experiments`
- `pause_experiments`
- `set_rate`
- `add_vehicle_manual`
- `remove_vehicle`
- `canvas_click`
- `set_infeasible_region` / `clear_infeasible_region` / `clear_infeasible_regions`（预留；后端不支持时前端保留本地状态）

## 5. 数据管理动作（`POST /data/action`）

- `delete_scenario`: 删除 `output/` 下的 `.pkl` 回放文件

请求示例：

```json
{
  "type": "delete_scenario",
  "path": "output/scenario_20260513_101500.pkl"
}
```

可按后端能力扩展动作类型，但需保持：

- 保留向后兼容字段名
- 新字段必须可选或有默认语义
- 在 `endpoints.json` 同步更新

## 5. 前端行为约束（与 prompt 对齐）

- 启动实验/回放后地图选择必须锁定
- 所有操作均通过网络协议发送
- AV 接口仅保留占位，不发送可执行动作
- 不可行区域接口为可替换模型预留；当前 CityNDE 后端未提供真实约束时，前端仍可记录和展示区域
