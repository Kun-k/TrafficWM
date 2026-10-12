# CityNDE 数据与 GUI 对接说明

## 目录约定

- `code -> ../../../algorithm_sources/CityNDE_src`：指向当前 CityNDE 源码目录，不在新后端结构中复制源码。
- `data/citynde_output -> ../../../../output/scenarios/citynde`：兼容旧入口，真实数据统一位于根目录 `output/`。
- `output/runtime/citynde/logs/`：统一管理层启动 CityNDE 实验时保存的子进程日志。
- `output/runtime/citynde/metadata/`：统一管理层保存的平台侧实验启动参数与命令记录。
- `interface/citynde_gui_adapter.py`：CityNDE 专用 GUI 适配器，导入原始 CityNDE 类并对外暴露统一 `/api/v1` 接口。
- `interface/citynde_adapter.py`：管理层构造 CityNDE 子进程命令的辅助模块。

## 对原 CityNDE 代码的修改

当前平台以 `algorithm_sources/CityNDE_src` 为 CityNDE 代码、资产和输出根目录。

历史 GUI 改动已通过 `snapshots/20260602_152546_before_citynde_reset` 记录。由于当前工作区的 `.git` 被只读挂载，无法创建 commit 或 stash，因此记录形式为 git diff、git status 和未跟踪代码压缩包。

外部适配器完成的能力：

- 场景生成：加载 CityNDE 模型、控制器和地图，运行仿真并发布 `status`、`map_state`、`sim_state`、`metrics`。
- 场景回放：读取 CityNDE 原始 `.pkl` 场景文件，按统一接口发布回放帧和轻量指标。
- 控制命令：支持终止、暂停/恢复、到达率设置、车辆增删等前端动作。
- 数据补充：平台侧日志写入 `output/runtime/citynde`；适配器保存新 `.pkl` 后会写出同名 `.pkl.meta.json`，用于回放页自动显示地图、初始化模式、到达率和总步数，不改动车辆轨迹数组，也避免数据管理刷新时反序列化大型 `.pkl`。

## 功能与指标能力

CityNDE 当前支持以下前端能力：

- 场景生成：地图选择、初始化模式、从 `.pkl` 初始化、入口到达率、GPU ID、最大仿真时间。
- 场景回放：读取 `output/scenarios/citynde` 下的 `.pkl` 场景；旧 source 路径通过符号链接保持兼容。
- 离线测试：复用 CityNDE 场景回放数据；选择文件后先进入 idle 预览并显示第 0 帧所有车辆，前端可点击选择 AV，也可随机选择 AV。启动离线测试后进入 playback，默认控制模式下 AV 沿保存的回放轨迹运行；`EXTERNAL_TCP`/`VTD_TCP` 会启动平台侧 TCP 控制端口，接收与 Highway AV TCP 一致的 newline-delimited JSON 命令，并用 `x/y/speed/acceleration/angle/heading` 覆盖选中 AV 的回放状态。
- `IDM_MOBIL` 由 Manager 自动启动 `/mnt/rk/cnde/autonomous_vehicles/idm_mobil` 中的模型，经同一 TCP 感知流读取周车、车道邻接和中心线，并返回 20 步状态轨迹。`LEAD_TFV6_STREAM` 预留给 CARLA RGB/LiDAR/导航传感器适配器；TFv6 checkpoint 不能仅靠 CityNDE 二维状态或 Cosmos RGB 等价推理。
- 运行时操作：入口到达率调整、车辆添加、车辆删除、暂停、恢复、终止并保存 `.pkl`。
- 在线 AV 测试：场景生成首个可用车辆帧支持手动点选确认或随机选择 AV；CityNDE 仍以 5 帧为一次模型推理，
  平台按 `0.1 s` 逐帧与外部 AV 同步。外部 AV 轨迹参与 safety layer 碰撞检查但保持固定，求解器只调整 BV。
  控制支持直接状态量与简化动力学执行器量，协议见 `docs/av_tcp_protocol.md`。AV 碰撞或离开场景会结束实验。
- 预留接口：不可行区域和多模态接口保留前端入口；后端未实现时不改变 CityNDE 原始逻辑。

指标由 `backend/algorithms/citynde/interface/citynde_gui_adapter.py` 从运行时车辆状态轻量计算，不修改 CityNDE 源码：

- 车辆数、平均速度、速度样本；
- 近似跟车距离；
- 近似 TTC；
- 近似碰撞计数。

TTC、跟车距离和碰撞计数使用车辆中心、朝向、速度、长宽做轻量近似计算。计算只读取当前帧车辆状态，不写入 CityNDE 内部对象；当车辆数较大时会对车辆集合降采样以避免明显影响推理速度。

## 数据存储策略

CityNDE 原始 `.pkl` 场景保存流程不被替换。适配器调用 CityNDE `save_to()` 后，写出同名 `.pkl.meta.json` 元数据，便于数据管理和回放页读取；已有历史文件如果没有该 sidecar 文件，前端对应参数保持为空。

管理层启动新实验时把场景保存到 `output/scenarios/citynde/experiments`。日志、指标和报告分别写入 `output/runtime/citynde`，不再在算法源码目录维护独立 output。

## GUI 通信方式

- 管理端：`GET/POST /api/v1/...`
- 实验详情：`/proxy/<experiment_id>/api/v1/...`
- CityNDE 子进程：由 `interface/citynde_gui_adapter.py` 提供 `status`、`map_state`、`sim_state`、`metrics`、`action`、`pause`、`resume` 等接口。
- AV TCP：由 `backend/common/av_tcp.py` 提供双向逐帧 JSON 协议；执行器控制调用
  `backend/dynamics/kinematic_bicycle.py`，不把外部控制逻辑写入 CityNDE 模型。
