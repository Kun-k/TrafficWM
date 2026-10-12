# TrafficWM 后端结构

当前项目按“前端 GUI + 统一管理层 + 算法适配层 + 原始算法代码”组织：

```text
algorithm_sources/          # 专门存放原始算法代码
  CityNDE_src/
  CityNDE/                  # 旧版本参考，不作为运行入口

/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment/
                            # NeuralNDE 独立 Git 仓库与 Python 3.9 环境

backend/
  common/                    # 与具体算法无关的 HTTP/API 工具
  manager/                   # 统一实验管理、调度、代理、数据管理
  algorithms/
    citynde/
      code -> ../../../algorithm_sources/CityNDE_src
      data/                  # 兼容入口，指向根目录 output/scenarios/citynde
      interface/             # CityNDE 与 GUI/管理层交互相关代码
      DATA_INTERFACE_CHANGES.md
    neuralnde/               # NeuralNDE 平台协议适配器，不是模型源码副本
  av/                        # IDM/MOBIL 内置客户端和外部 AV 数据流
  cosmos/                    # RDS/ClipGT 导出、常驻服务、生成和视频 QA
  scene/                     # 统一地图语义与局部地图裁切
```

`GUI/` 只保存前端页面、样式、脚本和接口说明。浏览器只访问统一管理服务，实验详情通过管理服务的 `/proxy/<experiment_id>/api/v1/...` 转发到子进程，因此公网或局域网访问只需要暴露一个管理端口。

## 命名说明

- `citynde`：平台内部算法目录名，对应完整 CityNDE 项目。
- `cnde`：前端/API 使用的模型短名，也对应 CityNDE 内部 Python 包 `cnde`。

因此目录统一使用 `backend/algorithms/citynde`，接口字段仍兼容 `backend_model=cnde`。

运行入口：

```bash
HOST=0.0.0.0 PORT=8890 scripts/run_manager.sh
```

## 算法能力矩阵

管理端 `/api/v1/capabilities` 会返回每个算法的功能能力，前端据此显示或隐藏配置项和指标图表。

| 能力 | CityNDE (`cnde`) | NeuralNDE |
| --- | --- | --- |
| 场景生成 | 支持在线局部交通流 | 支持 AA_rdbt / rounD 全局推理 |
| 场景回放 | 支持 `.pkl` | 生成时输出 25 Hz 统一状态流 |
| 入口到达率 | 支持全局/局部车道 | 由原模型数据集生成器维护 |
| AV 数据流 | IDM/MOBIL；LEAD 外部流 | 同一 TCP 桥与 25 Hz 感知流 |
| DenseWorld | RDS 七视图、Transfer、Dreams | 同一 Cosmos 流程，25 Hz 到 30 Hz 插值 |
| 输出 | `.pkl`、JSON、视频 | JSONL、关键帧、JSON、视频 |
| 安全指标 | 速度、TTC、车距、碰撞 | 速度、TTC、车距、碰撞 |

## 统一输出

- `output/scenarios/citynde/`: CityNDE 场景与回放文件。
- `output/experiments/`: NeuralNDE 和通用实验产物。
- `output/cosmos/`: Transfer2.5、OmniDreams、控制图和视频 QA。
- `output/runtime/<model>/`: 日志、启动元数据和性能 profile。
- `output/legacy/`: 已移除模型的历史结果，不参与新实验。

DenseWorld 的启动顺序、数据频率、首帧/缓存约束、AV 效果边界和 GPU 基准方法见
`docs/denseworld_drive.md`。AV newline-delimited JSON 控制协议见 `docs/av_tcp_protocol.md`。
