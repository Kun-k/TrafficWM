'use strict';

// ── i18n ──────────────────────────────────────────────────────────────────────
const I18N = {
  'zh-CN': {
    'app.title': 'TrafficWM 交通流工作台', 'app.subtitle': '统一管理后端 · 前后端分离控制框架',
    'status.disconnected': '未连接', 'status.connected': '已连接',
    'status.idle': '空闲', 'status.running': '运行中',
    'status.paused': '已暂停', 'status.playback': '回放中',
    'status.playbackLoading': '回放加载中',
    'status.waitingForStart': '等待启动实验…', 'status.mapNotLoaded': '地图未加载',
    'status.completed': '已结束', 'status.experimentEnded': '实验已结束', 'status.videoFinalizing': '视频同步中', 'status.openEnded': '持续运行',
    'status.activeExperiment': '实验',
    'actions.startExperiment': '启动实验', 'actions.pause': '暂停',
    'actions.resume': '继续', 'actions.terminate': '终止实验',
    'actions.startPlayback': '启动回放', 'actions.startOfflineTest': '启动离线测试', 'actions.maximize': '最大化',
    'actions.resetWindows': '复原窗口', 'actions.lockWindows': '锁定窗口', 'actions.unlockWindows': '解锁窗口',
    'actions.applyRate': '应用到达率', 'actions.addByCoord': '按坐标增加车辆',
    'actions.avReserved': 'AV 接口（预留，不可用）', 'actions.saveHist': '保存直方图',
    'actions.saveChart': '保存图像', 'actions.resetChartView': '重置视图',
    'actions.dataManager': '数据管理', 'actions.setRegion': '设置',
    'actions.clearRegions': '清空',
    'nav.home': '主界面', 'nav.experiments': '实验管理', 'nav.data': '数据管理',
    'nav.generate': '场景生成', 'nav.replay': '场景回放', 'nav.offline': '离线测试',
    'nav.security': '用户与安全',
    'home.title': 'TrafficWM 工作台', 'home.desc': '统一管理多模型实验、场景数据、场景生成和场景回放。',
    'home.experimentsDesc': '查看当前实验，批量暂停、终止或删除，并打开实验详情界面。',
    'home.dataDesc': '管理已保存的场景数据，支持上传、下载、重命名和批量删除。',
    'home.generateDesc': '配置地图、初始化模式和入口流量，启动新的场景生成实验。',
    'home.replayDesc': '选择已保存场景，进入回放界面并查看历史指标。',
    'home.offlineDesc': '基于回放场景选择 AV，接入 AV 算法进行离线测试。',
    'home.securityDesc': '管理账号权限，查看高危操作和异常访问日志。',
    'auth.login': '登录', 'auth.logout': '退出', 'auth.register': '注册',
    'auth.loginTitle': '登录 TrafficWM', 'auth.loginDesc': '登录后可访问实验、数据和管理功能。',
    'auth.registerTitle': '注册账号', 'auth.registerDesc': '新账号默认具有普通操作权限，管理员可在后台调整角色。',
    'auth.username': '用户名', 'auth.password': '密码',
    'auth.defaultAdminHint': '默认管理员：admin / admin123，可通过环境变量覆盖。',
    'toast.loginRequired': '请先登录', 'toast.loginOk': '登录成功', 'toast.logoutOk': '已退出登录',
    'toast.registerOk': '注册成功，请登录', 'toast.securityLoaded': '安全信息已更新',
    'security.title': '用户与安全', 'security.desc': '管理员可维护账号角色，并查看高危操作与异常访问日志。',
    'security.users': '用户管理', 'security.events': '安全日志', 'security.role': '角色',
    'security.role.admin': '管理员', 'security.role.operator': '操作员', 'security.role.viewer': '观察员',
    'security.enabled': '启用', 'security.lastLogin': '最近登录', 'security.createUser': '创建用户',
    'security.noUsers': '暂无用户', 'security.noEvents': '暂无日志',
    'security.allEvents': '全部日志', 'security.highRisk': '高危操作', 'security.abnormalAccess': '异常访问',
    'security.authEvents': '登录注册', 'security.userAdminEvents': '用户管理',
    'security.time': '时间', 'security.category': '类型', 'security.action': '动作', 'security.details': '详情',
    'security.resetPassword': '重置密码', 'security.disable': '禁用', 'security.enable': '启用',
    'security.deleteUser': '删除用户', 'security.newPassword': '新密码',
    'security.highRiskConfirm': '这是高危操作，会影响任务或数据。是否确认继续？',
    'experiments.title': '实验管理', 'experiments.desc': '管理端可同时启动多个独立模型实验，前端通过统一入口访问对应实验。',
    'experiments.pauseSelected': '批量暂停', 'experiments.terminateSelected': '批量终止',
    'experiments.deleteSelected': '批量删除', 'experiments.delete': '删除',
    'experiments.name': '实验', 'experiments.state': '状态', 'experiments.saveFile': '保存文件',
    'experiments.scenarioFile': '场景文件', 'experiments.generationSection': '场景生成',
    'experiments.replaySection': '场景回放',
    'experiments.empty': '暂无场景生成实验', 'experiments.emptyReplay': '暂无回放实验',
    'experiments.view': '查看实验', 'experiments.deleteConfirm': '确认删除选中的实验？运行中的后台进程会被终止。',
    'window.settings': '设置窗口', 'window.traffic': '交通流主窗口', 'window.metrics': '指标图表',
    'settings.map': '地图与实验', 'settings.mapSelect': '地图选择',
    'settings.initMode': '初始化模式',
    'settings.initData': '初始化数据文件',
    'settings.gpuId': '显卡 ID', 'settings.totalStep': '总步数',
    'settings.maxSimTime': '仿真时长 (s)', 'settings.runUntilStopped': '运行至手动停止',
    'settings.scenarioCount': '仿真场景次数',
    'settings.mapEditable': '地图可编辑（未运行）', 'settings.mapLockedMask': '运行中已锁定',
    'settings.display': '显示控制', 'settings.showTrajectory': '显示全部轨迹',
    'settings.showFutureTrajectory': '显示预测轨迹', 'settings.showPastTrajectory': '显示历史轨迹',
    'settings.showTrafficLight': '显示红绿灯', 'settings.mapBackground': '地图背景色',
    'settings.showVehicleId': '显示车辆ID', 'settings.trafficModel': '交通流模型',
    'settings.multimodalModel': '多模态模型',
    'settings.arrivalRate': '入口到达率', 'settings.laneId': '入口 / Lane ID',
    'settings.rate': '到达率 (0–1)', 'settings.vehicleOps': '车辆操作',
    'settings.mixedTraffic': '混合交通参与者', 'settings.mixedTrafficEnable': '启用混合交通',
    'settings.cyclistRatio': '非机动车比例', 'settings.pedestrianDensity': '每处斑马线行人数',
    'settings.vehicleSizeMode': '车辆尺寸分布', 'mixed.sizeMixed': '轿车 / SUV / 厢式车 / 大型车',
    'settings.initialSpeedMode': '随机初始化车速', 'mixed.speedUrban': '按车辆类型采样',
    'mixed.speedCitynde': 'CityNDE 原始 2 m/s',
    'mixed.sizePassenger': '仅标准乘用车', 'stats.cyclists': '非机动车', 'stats.pedestrians': '行人',
    'settings.clickMode': '点击模式', 'settings.replay': '回放控制',
    'settings.scenario': '选择场景文件', 'settings.replaySpeed': '回放速度',
    'replay.transferTitle': 'Transfer 回放片段', 'replay.startFrame': '起始帧',
    'replay.endFrame': '结束帧', 'replay.generateTransfer': '生成回放视频',
    'replay.views': '生成视角', 'replay.frontView': '主视角', 'replay.multiView': '七视角',
    'replay.frameRangeHint': '最长 15 秒；起止帧均包含在源窗口中。',
    'settings.avAccess': 'AV 接入接口',
    'av.selectionMode': '首帧 AV 选择', 'av.selectionManual': '手动点选并确认', 'av.selectionRandom': '系统随机选择',
    'av.commandMode': '控制数据类型', 'av.commandState': '位置 / 速度 / 姿态 / 加速度', 'av.commandActuator': '油门 / 刹车 / 转向',
    'av.endpoint': '控制端点', 'av.connected': 'AV 已连接', 'av.disconnected': '等待连接',
    'av.frames': '控制帧', 'av.timeouts': '超时', 'av.latency': '延迟',
    'av.selectPrompt': '请选择一辆车作为被测 AV', 'av.noSelection': '尚未选择', 'av.selected': '已选择车辆',
    'av.confirmSelection': '确认 AV',
    'settings.infeasibleRegion': '不可行区域', 'settings.regionMode': '区域编辑模式',
    'settings.regionRadius': '区域半径 (m)', 'settings.regionFrontendOnly': '区域能力已预留；后端不支持时仅在前端记录。',
    'carla.enable': '启动三维仿真', 'carla.quality': '渲染质量', 'carla.qualityEpic': '高质量',
    'carla.qualityLow': '低负载', 'carla.gpu': 'CARLA显卡', 'carla.windowTitle': 'CARLA 三维仿真',
    'carla.waiting': '正在启动 CARLA 0.9.16…', 'carla.overview': '全局视角',
    'carla.maximize': '最大化', 'carla.connected': '已连接', 'carla.starting': '启动中',
    'carla.loadingMap': '加载地图', 'carla.recovering': '正在恢复', 'carla.error': '异常', 'carla.stopped': '已停止',
    'carla.following': '跟随车辆',
    'click.none': '无', 'click.add': '点击增加车辆', 'click.delete': '点击删除车辆',
    'initMode.randomTlOnly': '仅随机红绿灯',
    'initMode.random': '随机车辆与红绿灯',
    'initMode.empty': '空场景',
    'initMode.data': '从数据初始化',
    'initMode.officialDataset': '原生数据集确定性初始化',
    'initMode.dataRandomTl': '数据车辆 + 随机红绿灯',
    'initMode.nade': 'NADE',
    'initMode.nde': 'NDE',
    'region.none': '无', 'region.set': '点击设置不可行区域', 'region.clear': '点击取消不可行区域',
    'tab.live': '实时', 'tab.analysis': '分析', 'tab.multimodal': '多模态',
    'stats.step': '仿真步数', 'stats.simTime': '仿真时间', 'stats.progress': '进度',
    'stats.vehicles': '车辆数',
    'stats.avgSpeed': '平均速度', 'stats.minTTC': '最小TTC',
    'stats.arrivalRate': '入口到达率', 'stats.violationRate': '违规率', 'stats.riskScore': '风险度',
    'charts.speedTrend': '平均速度趋势', 'charts.ttcTrend': '最小TTC趋势',
    'charts.arrivalTrend': '入口到达率趋势',
    'charts.accidentRate': '事故率估计', 'charts.violationRate': '违规率', 'charts.accidentVariance': '事故率方差',
    'charts.detail': '图表详情', 'charts.xMin': 'X最小', 'charts.xMax': 'X最大',
    'charts.yMin': 'Y最小', 'charts.yMax': 'Y最大', 'charts.binSize': '分辨率',
    'hist.speed': '速度', 'hist.ttc': 'TTC', 'hist.headway': '跟车距离',
    'hist.speedTitle': '速度分布 (m/s)', 'hist.ttcTitle': 'TTC 分布 (s)', 'hist.headwayTitle': '跟车距离分布 (m)',
    'multimodal.videoPlayer': '视频播放器', 'multimodal.noVideo': '暂无视频',
    'multimodal.omnidreamsLive': 'OmniDreams 实时预览',
    'multimodal.videoGen': '视频生成', 'multimodal.generate': '生成',
    'multimodal.compare': '对比视图', 'multimodal.left': '2D 交通流', 'multimodal.right': '视频',
    'model.denseworld': 'Cosmos Transfer2.5 + OmniDreams',
    'world.title': 'DenseWorld 视频', 'world.duration': '视频时长', 'world.durationFollow': '跟随交通流',
    'world.durationCustom': '自定义', 'world.durationCustomSeconds': '自定义视频时长 (s)', 'world.quality': 'Transfer 质量',
    'world.qualityFull': '35 步', 'world.qualityPreview': '8 步快速种子',
    'world.qualityBalanced': '20 步平衡',
    'world.seedMode': '预热视角', 'world.seedQuality': '主视角高质量', 'world.seedFast': '主视角快速',
    'world.seedMultiQuality': '七视角联合生成',
    'world.seedRadius': '种子地图范围',
    'world.seedImage': '单图锚点（七视角预热不使用）',
    'world.enableFullTransfer': '生成完整时长 Transfer 成片',
    'world.enableDreams': '生成 OmniDreams 视频', 'world.prompt': '场景提示词',
    'world.pipeline': '世界生成流水线', 'world.qualityReport': '一致性与产物', 'world.generatingOpenEnded': '持续生成',
    'world.noArtifacts': '暂无产物', 'world.benchmarks': '10 秒常驻生成基准',
    'world.benchmarkGpu': '预热后 · 1 / 4 / 8 GPU', 'world.generationTime': '常驻生成',
    'world.restartCosmos': '重启 Cosmos 常驻服务',
    'modal.terminateTitle': '终止实验', 'modal.terminateBody': '是否保存本次实验数据？',
    'modal.experimentName': '实验名称', 'modal.experimentNameHint': '可选。将用于保存文件名，只保留字母、数字、中文、下划线和短横线。',
    'modal.cancel': '取消', 'modal.discard': '不保存', 'modal.save': '保存并终止',
    'model.cnde': 'CityNDE', 'model.neuralnde': 'NeuralNDE', 'model.rulebased': 'IDM 规则（MOBIL 判据）', 'model.none': '— 暂无 —',
    'lang.zh': '中文', 'lang.en': 'English',
    'toast.actionFail': '操作失败', 'toast.connected': '已连接到后端',
    'toast.experimentStarted': '实验已启动', 'toast.playbackStarted': '回放已启动',
    'toast.terminated': '实验已终止',
    'data.title': '数据管理', 'data.replayDb': '回放数据库',
    'data.replayDbDesc': '管理统一输出目录中的 CityNDE 场景文件。',
    'data.refresh': '刷新', 'data.file': '文件', 'data.size': '大小',
    'data.modified': '修改时间', 'data.operations': '操作', 'data.empty': '暂无数据',
    'data.loadReplay': '回放', 'data.delete': '删除', 'data.rename': '重命名',
    'data.download': '下载', 'data.upload': '上传', 'data.downloadSelected': '批量下载',
    'data.deleteSelected': '批量删除', 'data.deleteConfirm': '确认删除选中的回放文件？',
    'toast.dataLoaded': '数据列表已更新', 'toast.dataDeleted': '数据已删除',
    'toast.dataUploaded': '数据已上传', 'toast.dataRenamed': '数据已重命名',
    'vehicle.selected': '选中车辆', 'vehicle.follow': '跟随车辆',
  },
  'en-US': {
    'app.title': 'TrafficWM Traffic Workbench', 'app.subtitle': 'Unified backend manager · separated frontend',
    'status.disconnected': 'Disconnected', 'status.connected': 'Connected',
    'status.idle': 'Idle', 'status.running': 'Running',
    'status.paused': 'Paused', 'status.playback': 'Playback',
    'status.playbackLoading': 'Loading Playback',
    'status.waitingForStart': 'Waiting for start…', 'status.mapNotLoaded': 'Map not loaded',
    'status.completed': 'Completed', 'status.experimentEnded': 'Experiment completed', 'status.videoFinalizing': 'Synchronizing video', 'status.openEnded': 'Running',
    'status.activeExperiment': 'Experiment',
    'actions.startExperiment': 'Start Experiment', 'actions.pause': 'Pause',
    'actions.resume': 'Resume', 'actions.terminate': 'Terminate',
    'actions.startPlayback': 'Start Playback', 'actions.startOfflineTest': 'Start Offline Test', 'actions.maximize': 'Maximize',
    'actions.resetWindows': 'Reset Windows', 'actions.lockWindows': 'Lock Windows', 'actions.unlockWindows': 'Unlock Windows',
    'actions.applyRate': 'Apply Rate', 'actions.addByCoord': 'Add by Coord',
    'actions.avReserved': 'AV Interface (Reserved)', 'actions.saveHist': 'Save Histogram',
    'actions.saveChart': 'Save Image', 'actions.resetChartView': 'Reset View',
    'actions.dataManager': 'Data', 'actions.setRegion': 'Set',
    'actions.clearRegions': 'Clear',
    'nav.home': 'Home', 'nav.experiments': 'Experiments', 'nav.data': 'Data',
    'nav.generate': 'Generation', 'nav.replay': 'Replay', 'nav.offline': 'Offline Test',
    'nav.security': 'Users & Security',
    'home.title': 'TrafficWM Workbench', 'home.desc': 'Manage multi-model experiments, scenario data, generation, and replay.',
    'home.experimentsDesc': 'Inspect current experiments, batch pause, terminate, delete, and open detail views.',
    'home.dataDesc': 'Manage saved scenario data with upload, download, rename, and batch deletion.',
    'home.generateDesc': 'Configure map, initialization mode, and arrival rates to generate a new scenario.',
    'home.replayDesc': 'Select a saved scenario and inspect playback with historical metrics.',
    'home.offlineDesc': 'Select an AV in a replay scene and connect AV algorithms for offline testing.',
    'home.securityDesc': 'Manage account roles and review high-risk operation and abnormal access logs.',
    'auth.login': 'Login', 'auth.logout': 'Logout', 'auth.register': 'Register',
    'auth.loginTitle': 'Login to TrafficWM', 'auth.loginDesc': 'Login to access experiments, data, and management tools.',
    'auth.registerTitle': 'Register Account', 'auth.registerDesc': 'New accounts receive operator permissions by default; admins can adjust roles.',
    'auth.username': 'Username', 'auth.password': 'Password',
    'auth.defaultAdminHint': 'Default admin: admin / admin123. Override with environment variables.',
    'toast.loginRequired': 'Please login first', 'toast.loginOk': 'Logged in', 'toast.logoutOk': 'Logged out',
    'toast.registerOk': 'Registered. Please login.', 'toast.securityLoaded': 'Security information updated',
    'security.title': 'Users & Security', 'security.desc': 'Admins can maintain account roles and review high-risk and abnormal access logs.',
    'security.users': 'Users', 'security.events': 'Security Logs', 'security.role': 'Role',
    'security.role.admin': 'Admin', 'security.role.operator': 'Operator', 'security.role.viewer': 'Viewer',
    'security.enabled': 'Enabled', 'security.lastLogin': 'Last Login', 'security.createUser': 'Create User',
    'security.noUsers': 'No users', 'security.noEvents': 'No events',
    'security.allEvents': 'All Events', 'security.highRisk': 'High-risk', 'security.abnormalAccess': 'Abnormal Access',
    'security.authEvents': 'Auth', 'security.userAdminEvents': 'User Admin',
    'security.time': 'Time', 'security.category': 'Category', 'security.action': 'Action', 'security.details': 'Details',
    'security.resetPassword': 'Reset Password', 'security.disable': 'Disable', 'security.enable': 'Enable',
    'security.deleteUser': 'Delete User', 'security.newPassword': 'New Password',
    'security.highRiskConfirm': 'This is a high-risk operation that may affect tasks or data. Continue?',
    'experiments.title': 'Experiment Management', 'experiments.desc': 'The manager can launch multiple independent model experiments behind one frontend entry.',
    'experiments.pauseSelected': 'Pause Selected', 'experiments.terminateSelected': 'Terminate Selected',
    'experiments.deleteSelected': 'Delete Selected', 'experiments.delete': 'Delete',
    'experiments.name': 'Experiment', 'experiments.state': 'State', 'experiments.saveFile': 'Save File',
    'experiments.scenarioFile': 'Scenario File', 'experiments.generationSection': 'Generation',
    'experiments.replaySection': 'Replay',
    'experiments.empty': 'No generation experiments', 'experiments.emptyReplay': 'No replay experiments',
    'experiments.view': 'View', 'experiments.deleteConfirm': 'Delete selected experiments? Running processes will be terminated.',
    'window.settings': 'Settings', 'window.traffic': 'Traffic View', 'window.metrics': 'Metrics',
    'settings.map': 'Map & Experiment', 'settings.mapSelect': 'Map Selection',
    'settings.initMode': 'Init Mode',
    'settings.initData': 'Init Data File',
    'settings.gpuId': 'GPU ID', 'settings.totalStep': 'Total Steps',
    'settings.maxSimTime': 'Simulation Duration (s)', 'settings.runUntilStopped': 'Run until manually stopped',
    'settings.scenarioCount': 'Scenario Count',
    'settings.mapEditable': 'Map editable (not running)', 'settings.mapLockedMask': 'Locked (running)',
    'settings.display': 'Display Controls', 'settings.showTrajectory': 'Show All Trajectories',
    'settings.showFutureTrajectory': 'Show Predicted Trajectory', 'settings.showPastTrajectory': 'Show Past Trajectory',
    'settings.showTrafficLight': 'Show Traffic Lights', 'settings.mapBackground': 'Map Background',
    'settings.showVehicleId': 'Show Vehicle ID', 'settings.trafficModel': 'Traffic Model',
    'settings.multimodalModel': 'Multimodal Model',
    'settings.arrivalRate': 'Arrival Rate', 'settings.laneId': 'Entry / Lane ID',
    'settings.rate': 'Rate (0–1)', 'settings.vehicleOps': 'Vehicle Operations',
    'settings.mixedTraffic': 'Mixed Traffic', 'settings.mixedTrafficEnable': 'Enable mixed traffic',
    'settings.cyclistRatio': 'Cyclist ratio', 'settings.pedestrianDensity': 'Pedestrians per crosswalk',
    'settings.vehicleSizeMode': 'Vehicle size mix', 'mixed.sizeMixed': 'Cars / SUVs / vans / large vehicles',
    'settings.initialSpeedMode': 'Random initial speed', 'mixed.speedUrban': 'Sample by vehicle type',
    'mixed.speedCitynde': 'Original CityNDE 2 m/s',
    'mixed.sizePassenger': 'Passenger cars only', 'stats.cyclists': 'Cyclists', 'stats.pedestrians': 'Pedestrians',
    'settings.clickMode': 'Click Mode', 'settings.replay': 'Replay Control',
    'settings.scenario': 'Select Scenario', 'settings.replaySpeed': 'Replay Speed',
    'replay.transferTitle': 'Transfer replay clip', 'replay.startFrame': 'Start frame',
    'replay.endFrame': 'End frame', 'replay.generateTransfer': 'Generate replay video',
    'replay.views': 'Generated views', 'replay.frontView': 'Front view', 'replay.multiView': 'Seven views',
    'replay.frameRangeHint': 'Up to 15 seconds; both endpoints are included in the source window.',
    'settings.avAccess': 'AV Interface',
    'av.selectionMode': 'First-frame AV selection', 'av.selectionManual': 'Select and confirm', 'av.selectionRandom': 'Random selection',
    'av.commandMode': 'Control data type', 'av.commandState': 'Pose / speed / acceleration', 'av.commandActuator': 'Throttle / brake / steering',
    'av.endpoint': 'Control endpoint', 'av.connected': 'AV connected', 'av.disconnected': 'Waiting for connection',
    'av.frames': 'Control frames', 'av.timeouts': 'Timeouts', 'av.latency': 'Latency',
    'av.selectPrompt': 'Select a vehicle as the AV under test', 'av.noSelection': 'No vehicle selected', 'av.selected': 'Selected vehicle',
    'av.confirmSelection': 'Confirm AV',
    'settings.infeasibleRegion': 'Infeasible Region', 'settings.regionMode': 'Region Edit Mode',
    'settings.regionRadius': 'Region Radius (m)', 'settings.regionFrontendOnly': 'Region API is reserved; frontend records it when backend does not support it.',
    'carla.enable': 'Enable 3D Simulation', 'carla.quality': 'Render Quality', 'carla.qualityEpic': 'High Quality',
    'carla.qualityLow': 'Low Load', 'carla.gpu': 'CARLA GPU', 'carla.windowTitle': 'CARLA 3D Simulation',
    'carla.waiting': 'Starting CARLA 0.9.16…', 'carla.overview': 'Overview',
    'carla.maximize': 'Maximize', 'carla.connected': 'Connected', 'carla.starting': 'Starting',
    'carla.loadingMap': 'Loading Map', 'carla.recovering': 'Recovering', 'carla.error': 'Error', 'carla.stopped': 'Stopped',
    'carla.following': 'Following vehicle',
    'click.none': 'None', 'click.add': 'Click to Add', 'click.delete': 'Click to Delete',
    'initMode.randomTlOnly': 'Random Traffic Lights Only',
    'initMode.random': 'Random Vehicles & Lights',
    'initMode.empty': 'Empty Scene',
    'initMode.data': 'Initialize From Data',
    'initMode.officialDataset': 'Deterministic Native Dataset',
    'initMode.dataRandomTl': 'Data Vehicles + Random Lights',
    'initMode.nade': 'NADE',
    'initMode.nde': 'NDE',
    'region.none': 'None', 'region.set': 'Click to Set Infeasible Region', 'region.clear': 'Click to Clear Infeasible Region',
    'tab.live': 'Live', 'tab.analysis': 'Analysis', 'tab.multimodal': 'Multimodal',
    'stats.step': 'Sim Step', 'stats.simTime': 'Sim Time', 'stats.progress': 'Progress',
    'stats.vehicles': 'Vehicles',
    'stats.avgSpeed': 'Avg Speed', 'stats.minTTC': 'Min TTC',
    'stats.arrivalRate': 'Arrival Rate', 'stats.violationRate': 'Violation Rate', 'stats.riskScore': 'Risk',
    'charts.speedTrend': 'Avg Speed Trend', 'charts.ttcTrend': 'Min TTC Trend',
    'charts.arrivalTrend': 'Arrival Rate Trend',
    'charts.accidentRate': 'Accident Rate Estimate', 'charts.violationRate': 'Violation Rate', 'charts.accidentVariance': 'Accident Rate Variance',
    'charts.detail': 'Chart Detail', 'charts.xMin': 'X Min', 'charts.xMax': 'X Max',
    'charts.yMin': 'Y Min', 'charts.yMax': 'Y Max', 'charts.binSize': 'Resolution',
    'hist.speed': 'Speed', 'hist.ttc': 'TTC', 'hist.headway': 'Headway',
    'hist.speedTitle': 'Speed Distribution (m/s)', 'hist.ttcTitle': 'TTC Distribution (s)',
    'hist.headwayTitle': 'Headway Distribution (m)',
    'multimodal.videoPlayer': 'Video Player', 'multimodal.noVideo': 'No video',
    'multimodal.omnidreamsLive': 'OmniDreams live preview',
    'multimodal.videoGen': 'Video Generation', 'multimodal.generate': 'Generate',
    'multimodal.compare': 'Comparison View', 'multimodal.left': '2D Traffic', 'multimodal.right': 'Video',
    'model.denseworld': 'Cosmos Transfer2.5 + OmniDreams',
    'world.title': 'DenseWorld Video', 'world.duration': 'Video duration', 'world.durationFollow': 'Follow traffic',
    'world.durationCustom': 'Custom', 'world.durationCustomSeconds': 'Custom video duration (s)', 'world.quality': 'Transfer quality',
    'world.qualityFull': '35 steps', 'world.qualityPreview': '8-step fast seed',
    'world.qualityBalanced': '20-step balanced',
    'world.seedMode': 'Seed views', 'world.seedQuality': 'High-quality front view', 'world.seedFast': 'Fast front view',
    'world.seedMultiQuality': 'Joint seven-view generation',
    'world.seedRadius': 'Seed map range',
    'world.seedImage': 'Single-image anchor (unused by seven-view warmup)',
    'world.enableFullTransfer': 'Generate full-duration Transfer video',
    'world.enableDreams': 'Generate OmniDreams video', 'world.prompt': 'Scene prompt',
    'world.pipeline': 'World generation pipeline', 'world.qualityReport': 'Consistency and artifacts', 'world.generatingOpenEnded': 'Generating',
    'world.noArtifacts': 'No artifacts yet', 'world.benchmarks': '10-second resident benchmark',
    'world.benchmarkGpu': 'After warmup · 1 / 4 / 8 GPU', 'world.generationTime': 'Resident generation',
    'world.restartCosmos': 'Restart resident Cosmos services',
    'modal.terminateTitle': 'Terminate Experiment', 'modal.terminateBody': 'Save experiment data?',
    'modal.experimentName': 'Experiment Name', 'modal.experimentNameHint': 'Optional. Used in the saved filename; only letters, numbers, CJK text, underscores, and hyphens are kept.',
    'modal.cancel': 'Cancel', 'modal.discard': 'Discard', 'modal.save': 'Save & Terminate',
    'model.cnde': 'CityNDE', 'model.neuralnde': 'NeuralNDE', 'model.rulebased': 'IDM rules (MOBIL criterion)', 'model.none': '— None —',
    'lang.zh': '中文', 'lang.en': 'English',
    'toast.actionFail': 'Action failed', 'toast.connected': 'Connected to backend',
    'toast.experimentStarted': 'Experiment started',
    'toast.playbackStarted': 'Playback started', 'toast.terminated': 'Experiment terminated',
    'data.title': 'Data Management', 'data.replayDb': 'Replay Database',
    'data.replayDbDesc': 'Manage CityNDE scenarios in the unified output directory.',
    'data.refresh': 'Refresh', 'data.file': 'File', 'data.size': 'Size',
    'data.modified': 'Modified', 'data.operations': 'Operations', 'data.empty': 'No data',
    'data.loadReplay': 'Replay', 'data.delete': 'Delete', 'data.rename': 'Rename',
    'data.download': 'Download', 'data.upload': 'Upload', 'data.downloadSelected': 'Download Selected',
    'data.deleteSelected': 'Delete Selected', 'data.deleteConfirm': 'Delete selected replay file(s)?',
    'toast.dataLoaded': 'Data list updated', 'toast.dataDeleted': 'Data deleted',
    'toast.dataUploaded': 'Data uploaded', 'toast.dataRenamed': 'Data renamed',
    'vehicle.selected': 'Selected Vehicle', 'vehicle.follow': 'Follow Vehicle',
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
// Temporary feature switch: authentication remains enabled, while registration
// and the user/security administration UI stay unavailable.
const USER_MANAGEMENT_ENABLED = false;
const DEFAULT_WORLD_PROMPT = 'Natural documentary front-facing dashcam footage on a dry charcoal-gray urban road in clear late-morning weather. Render only supplied traffic participants in their mapped lanes, with crisp white lane markings, concrete curbs, correctly scaled crosswalks and traffic lights, mature leafy street trees, clipped green shrubs, and restrained pale-stone and light-gray concrete mid-rise buildings. Soft blue sky and directional natural sunlight create stable shadows, neutral color, and a calm physically grounded atmosphere. Keep road width, horizon, traffic identity, object scale, camera motion, and fine detail temporally consistent.';
let lang = 'zh-CN';
let backendBase = '';
let managerBase = '';
let activeExperimentId = '';
let connected = false;
let hasShownConnectedToast = false;
let lastStatus = {};
let runState = 'idle';
let appMode = 'home';
let mapLocked = false;
let windowsLocked = false;
let securityEnabled = false;
let authToken = '';
let currentUser = null;
let runtimeStarted = false;
let statusPollBusy = false;
let carlaSessionRequested = false;
let carlaStatusBusy = false, carlaFrameBusy = false;
let carlaFrameUrl = '', carlaLastFrameNumber = 0, carlaLastFrameTime = 0;
let adminUsers = [];
let securityEvents = [];
let standardScenarioRecords = [];
const scenarioPreviewCache = new Map();
let scenarioPreviewAnimationFrame = 0;
let lastScenarioPreviewPaintAt = 0;
let modalTrafficPreview = null;
let selectedStandardScenarioId = '';
let selectedWorkflowId = '';
let workflowRecords = [];
let startConfiguredExperiment = null;
let workflowScenarioMode = 'library';
let workflowMapLoadSequence = 0;
let workflowCameraConfig = {
  enabled: true,
  name: '前向主摄像头',
  preset: 'front_wide_120',
  intrinsic_file: '',
  extrinsic_file: '',
  intrinsic_data: null,
  extrinsic_data: null,
};
const CAMERA_CALIBRATION_MAX_BYTES = 256 * 1024;
const DEFAULT_EVALUATION_METRICS = {
  safety: { enabled: true, metrics: { av_overlap_frames: { enabled: true, weight: 40 }, minimum_ttc: { enabled: true, weight: 40 }, traffic_violation_rate: { enabled: true, weight: 20 } } },
  comfort: { enabled: true, metrics: { longitudinal_acceleration_rms: { enabled: true, weight: 34 }, lateral_acceleration_rms: { enabled: true, weight: 33 }, jerk_p95: { enabled: true, weight: 33 } } },
  efficiency: { enabled: true, metrics: { mean_speed: { enabled: true, weight: 40 }, elapsed_time: { enabled: true, weight: 20 }, stopped_time_ratio: { enabled: true, weight: 40 } } },
};

function normalizeEvaluationMetrics(config = {}) {
  const normalized = JSON.parse(JSON.stringify(DEFAULT_EVALUATION_METRICS));
  Object.entries(normalized).forEach(([category, defaults]) => {
    const source = config?.[category];
    if (!source || typeof source !== 'object') return;
    normalized[category].enabled = source.enabled !== false;
    Object.keys(defaults.metrics).forEach(metricId => {
      const metric = source.metrics?.[metricId];
      if (!metric || typeof metric !== 'object') return;
      normalized[category].metrics[metricId] = {
        enabled: metric.enabled !== false,
        weight: Number.isFinite(Number(metric.weight)) ? Number(metric.weight) : defaults.metrics[metricId].weight,
      };
    });
  });
  return normalized;
}

let workflowEvaluationMetrics = normalizeEvaluationMetrics();
const EVALUATION_SYSTEM_STORAGE_KEY = 'denseworld-drive.evaluation-systems.v1';
let evaluationSystemRecords = [];
let selectedEvaluationSystemId = 'DW-EVAL-0001';
let workflowEvaluationSystemId = 'DW-EVAL-0001';
let workflowEvaluationSystemName = '自然交通流自动驾驶综合评价';
let workflowScenarioConfigurationLocked = false;
let dashboardPollBusy = false;
let currentExperimentReport = null;
let completionReviewExperimentId = '';
const completionPromptedExperimentIds = new Set();
const WORKFLOW_STORAGE_KEY = 'denseworld-drive.workflows.v1';

// Canvas / zoom / pan
let zoom = 1.0, panX = 0, panY = 0;
let isPanning = false, panStartX = 0, panStartY = 0, panStartTx = 0, panStartTy = 0;
let frameImg = new Image(), frameLoaded = false, framePollBusy = false;
let drawFrameScheduled = false;
let mapRasterImg = new Image(), mapRasterLoaded = false, mapRasterSource = '';
let mapData = null, simData = null, mapStateBusy = false, simStateBusy = false;
let lastSimStateVersion = 0;
let simInterpolation = null, simAnimationFrame = 0, lastSimAnimationAt = 0;
let selectedVehicleId = null, followSelectedVehicle = false, vectorFitDone = false;
let offlineAvId = null;
let offlinePreviewScenario = '';
let offlinePreviewBusy = false;
let vehicleIdOptionsSignature = '';
let mapBackgroundColor = '#d8dde3';
const MAX_ZOOM = 5000;
let pendingVehicleOp = null;
let staticMapLayer = null, staticMapLayerSignature = '';
let mapRenderVersion = 0;
let mapPolylineById = new Map();
let mapType4Polylines = [];
let trafficLightPolylines = [];
let trafficLightPolylineSignature = '';

// Replay
let replayTotalSteps = 0, replayCurrentStep = 0;
let replayPlaying = false, replayTimer = null, replaySpeed = 1;
let replaySeekBusy = false, replaySeekPending = null;
let replayStepSeconds = 0.1;
let replayLoopToken = 0;
let replaySliderDragging = false, replaySeekDebounce = null;
let replayClockBaseStep = 0, replayClockBaseTime = 0;
let replayAutoplayPending = false;
let simStepSeconds = 0.1;
let activeReplayMapPath = '';
let experimentMarkers = [];
let viewerLayoutMode = 'equal';
let viewerSplitRatio = 1 / 3;
let metricsPanelCollapsed = false;
let platformSidebarCollapsed = false;
let viewerSplitRenderFrame = 0;
const VIEWER_SPLIT_STORAGE_KEY = 'denseworld.viewerSplitRatio';
const PLATFORM_SIDEBAR_STORAGE_KEY = 'denseworld.platformSidebarCollapsed';
const METRICS_PANEL_STORAGE_KEY = 'denseworld.metricsPanelCollapsed';
const DEFAULT_ARRIVAL_RATE = 0.006;
let pendingDefaultArrivalRate = DEFAULT_ARRIVAL_RATE;
let pendingLaneArrivalRates = {};

// Metric history is keyed by simulation step so replay seeking cannot corrupt trends.
const DEFAULT_HISTOGRAM_BIN_SIZE = 0.5;
let metricSamples = [];
let metricSampleIndex = new Map();

// Chart instances
let speedChart = null, ttcChart = null, arrivalChart = null;
let histSpeedChart = null, histTTCChart = null, histHeadwayChart = null;
let accidentRateChart = null, violationRateChart = null, accidentVarianceChart = null;
let expandedChart = null, expandedChartKey = null;
let lastChartUpdateAt = 0, chartUpdateTimer = null;
let lastMetricsFetchAt = 0, metricsFetchBusy = false;
let metricsLoadedUntil = 0;
let lastExperimentsLoadAt = 0;
const METRICS_POLL_MS = 2000;
const PLAYBACK_METRICS_POLL_MS = 30000;
const PLAYBACK_CHART_UPDATE_MS = 15000;
const EXPERIMENTS_POLL_MS = 3500;
const SIM_STATE_POLL_MS = 100;
const SIM_RENDER_INTERVAL_MS = 1000 / 30;
const FRAME_POLL_MS = 500;
const STATUS_POLL_MS = 500;
const METRICS_INITIAL_FULL_LIMIT = 2000;
const API_PREFIX = '/api/v1';
const METRIC_ARRAY_KEYS = [
  'speed_per_step',
  'vehicle_count_per_step',
  'min_ttc_per_step',
  'headway_per_step',
  'collision_count_per_step',
  'collision_rate_per_step',
  'speed_samples_per_step',
  'ttc_samples_per_step',
  'headway_samples_per_step',
  'arrival_rate_per_step',
];

// Replay metrics cache
let replayMetrics = null;
let infeasibleRegions = [];
let dataRecords = [];
let dataCatalogMode = 'virtual';
let dataViewMode = 'list';
let dataContentMode = 'traffic';
const dataRecordModes = new Map();
let workflowScenarioViewMode = 'grid';
const workflowScenarioContentModes = new Map();
let mapCatalogRecords = [];
let naturalCatalogRecords = [];
let accidentCatalogRecords = [];
let naturalBrowserDatasetId = '';
let naturalBrowserPath = '';
let dataSort = { key: 'modified', dir: 'desc' };
let dataRecordByPath = new Map();
let selectedDataPaths = new Set();
let experimentRecords = [];
let visibleExperimentRecords = [];
let selectedExperimentIds = new Set();
let experimentsSelectionHoldUntil = 0;
let worldGeneration = {};
let worldArtifacts = [];
let worldPreviewStatus = {};
let cosmosServices = {};
let worldBenchmarks = [];
let autoOpenedWorldPreviewKey = '';
let worldStatusBusy = false;
let worldVideoRenderSignature = '';
let worldArtifactRenderSignature = '';
let lastWorldBenchmarkFetchAt = 0;
const OMNIDREAMS_LIVE_SOURCE = '__omnidreams_live__';
const WORLD_STAGE_ORDER = [
  'waiting_for_models', 'scene_export', 'control_render', 'transfer_seed_anchor', 'transfer_seed',
  'operational_traffic', 'full_scene_export', 'full_control_render', 'transfer_full',
  'clipgt_export', 'omnidreams',
];
const WORLD_STAGE_LABELS = {
  waiting_for_models: ['bi-hourglass-split', '模型与预热'],
  scene_export: ['bi-bounding-box-circles', '场景图'],
  control_render: ['bi-camera-reels', '七路控制'],
  transfer_seed_anchor: ['bi-image', '外观锚点'],
  transfer_seed: ['bi-stars', '首帧种子'],
  operational_traffic: ['bi-signpost-split', '业务交通流'],
  full_scene_export: ['bi-boxes', '完整场景图'],
  full_control_render: ['bi-camera-video', '完整七路控制'],
  transfer_full: ['bi-film', 'Transfer 完整成片'],
  clipgt_export: ['bi-map', 'HD Map'],
  omnidreams: ['bi-film', 'OmniDreams'],
};
let algorithmCapabilities = {
  cnde: {
    init_modes: true, init_data: true, arrival_rate: true, vehicle_ops: true, replay: true, data_management: true,
    metrics: { speed: true, ttc: true, headway: true, collision: true, arrival_rate: true },
  },
  neuralnde: {
    init_modes: false, init_data: false, arrival_rate: false, vehicle_ops: false, replay: false, data_management: true,
    metrics: { speed: true, ttc: true, headway: true, collision: true, arrival_rate: false },
    parameters: { av_tcp: true, model_resolution: 0.4, stream_resolution: 0.04 },
  },
  rulebased: {
    init_modes: true, init_data: true, arrival_rate: true, vehicle_ops: true, replay: true, data_management: true,
    metrics: { speed: true, ttc: true, headway: true, collision: true, arrival_rate: true },
    parameters: { av_tcp: true, model_resolution: 0.5, stream_resolution: 0.1 },
  },
};

let _zCounter = 10;
function nextZ() { return ++_zCounter; }
const $ = id => document.getElementById(id);

const INIT_MODE_OPTIONS = {
  cnde: [
    ['random_tl_only', 'initMode.randomTlOnly'],
    ['random', 'initMode.random'],
    ['empty', 'initMode.empty'],
    ['data', 'initMode.data'],
    ['data_random_tl', 'initMode.dataRandomTl'],
  ],
  rulebased: [
    ['random_tl_only', 'initMode.randomTlOnly'],
    ['random', 'initMode.random'],
    ['empty', 'initMode.empty'],
    ['data', 'initMode.data'],
    ['data_random_tl', 'initMode.dataRandomTl'],
  ],
  neuralnde: [
    ['official_dataset', 'initMode.officialDataset'],
  ],
};

const CHART_DEFS = {
  speedTrend: { kind: 'line', titleKey: 'charts.speedTrend', valueKey: 'speed', color: 'rgb(56,189,248)' },
  ttcTrend: { kind: 'line', titleKey: 'charts.ttcTrend', valueKey: 'ttc', color: 'rgb(251,191,36)' },
  arrivalTrend: { kind: 'line', titleKey: 'charts.arrivalTrend', valueKey: 'arrival', color: 'rgb(34,197,94)' },
  histSpeed: { kind: 'hist', titleKey: 'hist.speedTitle', valueKey: 'speedSamples', color: 'rgba(56,189,248,0.7)' },
  histTTC: { kind: 'hist', titleKey: 'hist.ttcTitle', valueKey: 'ttcSamples', color: 'rgba(251,191,36,0.7)' },
  histHeadway: { kind: 'hist', titleKey: 'hist.headwayTitle', valueKey: 'headwaySamples', color: 'rgba(167,139,250,0.7)' },
  accidentRate: { kind: 'line', titleKey: 'charts.accidentRate', valueKey: 'accidentRate', color: 'rgb(239,68,68)' },
  violationRate: { kind: 'line', titleKey: 'charts.violationRate', valueKey: 'violationRate', color: 'rgb(168,85,247)' },
  accidentVariance: { kind: 'line', titleKey: 'charts.accidentVariance', valueKey: 'accidentVariance', color: 'rgb(249,115,22)' },
};

// ── i18n ──────────────────────────────────────────────────────────────────────
function t(key) { return (I18N[lang] || I18N['zh-CN'])[key] || key; }

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (el.tagName === 'OPTION') { el.textContent = t(key); return; }
    if (!el.querySelector('[data-i18n]')) el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.documentElement.lang = lang;
  updateActiveExperimentBadge(lastStatus || {});
}

function safeSetIcon(id, iconClass) {
  const el = $(id);
  if (el) el.querySelector('i').className = iconClass;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastInst = null;
function showToast(msg, ok = true) {
  const el = $('appToast');
  $('appToastBody').textContent = msg;
  el.className = `toast align-items-center position-fixed bottom-0 end-0 m-3 text-bg-${ok ? 'success' : 'danger'}`;
  if (!_toastInst) _toastInst = new bootstrap.Toast(el, { delay: 2500 });
  _toastInst.show();
}

// ── Config ────────────────────────────────────────────────────────────────────
async function loadConfig() {
  const url = new URL(window.location.href);
  const explicitBackend = url.searchParams.get('backend');
  const explicitManager = url.searchParams.get('manager');
  const managerPort = url.searchParams.get('manager_port');
  activeExperimentId = url.searchParams.get('experiment_id') || '';
  carlaSessionRequested = url.searchParams.get('carla') === '1';
  if (explicitManager) {
    managerBase = explicitManager.replace(/\/$/, '');
  } else if (managerPort && window.location.protocol.startsWith('http')) {
    managerBase = `${window.location.protocol}//${window.location.hostname}:${managerPort}`;
  } else if (activeExperimentId && window.location.protocol.startsWith('http')) {
    managerBase = window.location.origin;
  }
  if (activeExperimentId && managerBase) {
    backendBase = `${managerBase}/proxy/${encodeURIComponent(activeExperimentId)}`;
  } else if (explicitBackend) {
    backendBase = explicitBackend.replace(/\/$/, '');
  } else if (window.location.protocol.startsWith('http')) {
    backendBase = window.location.origin;
  } else {
    try {
      const r = await fetch('config/backend.config.json');
      if (r.ok) {
        const cfg = await r.json();
        const b = cfg.backend || cfg;
        const host = (b.host === '127.0.0.1' || b.host === 'localhost')
          ? window.location.hostname : b.host;
        backendBase = `http://${host}:${b.port}`;
      }
    } catch (_) {}
  }
  if (!backendBase) backendBase = `http://${window.location.hostname}:8890`;
  $('backendTarget').textContent = backendBase;
}

function isManagedChildSession() {
  return !!activeExperimentId || (!!managerBase && managerBase !== backendBase);
}

function managerViewUrl(view = 'home') {
  const base = managerBase || (window.location.protocol.startsWith('http') ? window.location.origin : '');
  if (!base) return '';
  const url = new URL('/', base);
  url.searchParams.set('view', view);
  return url.toString();
}

function childBackendOrigin(recordOrUrl) {
  const record = typeof recordOrUrl === 'object' && recordOrUrl !== null ? recordOrUrl : {};
  const rawUrl = typeof recordOrUrl === 'string' ? recordOrUrl : (record.url || record.viewer_url || '');
  const currentHost = window.location.hostname || '127.0.0.1';
  const currentProtocol = window.location.protocol.startsWith('http') ? window.location.protocol : 'http:';
  const rawPort = record.port || '';
  if (rawPort) return `${currentProtocol}//${currentHost}:${rawPort}`;
  if (rawUrl) {
    try {
      const url = new URL(rawUrl, window.location.href);
      if (window.location.protocol.startsWith('http')) {
        url.protocol = window.location.protocol;
        if (['127.0.0.1', 'localhost', '0.0.0.0'].includes(url.hostname)) {
          url.hostname = currentHost;
        }
      }
      return url.origin;
    } catch (_) {}
  }
  return '';
}

function viewerAppUrl(recordOrUrl, view = 'experiment') {
  const record = typeof recordOrUrl === 'object' && recordOrUrl !== null ? recordOrUrl : {};
  const recordId = record.id || record.experiment_id || '';
  const shellBase = managerBase || (window.location.protocol.startsWith('http') ? window.location.origin : '');
  if (recordId && shellBase) {
    const url = new URL('/', shellBase);
    url.searchParams.set('view', view);
    url.searchParams.set('experiment_id', recordId);
    url.searchParams.set('marker_scope', record.marker_scope || record.replay_params?.marker_scope || recordId);
    if (record.carla_enabled) url.searchParams.set('carla', '1');
    const scenario = record.scenario || record.replay_params?.scenario_path || record.replay_params?.scenario || '';
    if (scenario && (view === 'replay' || view === 'offline')) url.searchParams.set('scenario', scenario);
    return url.toString();
  }
  const backend = childBackendOrigin(recordOrUrl);
  if (!backend) return typeof recordOrUrl === 'string' ? recordOrUrl : (recordOrUrl?.url || '');
  const scenario = record.scenario || record.replay_params?.scenario_path || record.replay_params?.scenario || '';
  if (shellBase) {
    const url = new URL('/', shellBase);
    url.searchParams.set('view', view);
    url.searchParams.set('backend', backend);
    const markerScope = record.marker_scope || record.replay_params?.marker_scope || recordId;
    if (markerScope) url.searchParams.set('marker_scope', markerScope);
    if (record.carla_enabled) url.searchParams.set('carla', '1');
    if (scenario && (view === 'replay' || view === 'offline')) url.searchParams.set('scenario', scenario);
    const managerOrigin = managerBase || (isManagerBackend() ? backendBase : shellBase);
    if (managerOrigin && managerOrigin !== shellBase) url.searchParams.set('manager', managerOrigin);
    const managerPort = managerOrigin ? new URL(managerOrigin).port : '';
    if (managerPort) url.searchParams.set('manager_port', managerPort);
    return url.toString();
  }
  const url = new URL('/', backend);
  url.searchParams.set('view', view);
  if (record.carla_enabled) url.searchParams.set('carla', '1');
  if (scenario && (view === 'replay' || view === 'offline')) url.searchParams.set('scenario', scenario);
  const managerPort = managerBase ? new URL(managerBase).port : (isManagerBackend() ? new URL(backendBase).port : '');
  if (managerPort) url.searchParams.set('manager_port', managerPort);
  return url.toString();
}

function openViewer(recordOrUrl, view = 'experiment', options = {}) {
  const record = typeof recordOrUrl === 'object' && recordOrUrl !== null ? recordOrUrl : {};
  if (!isManagerBackend() && !isManagedChildSession() && record.port) {
    try {
      if (String(record.port) === String(new URL(backendBase).port || window.location.port)) {
        if (options.newTab) {
          const current = new URL(window.location.href);
          current.searchParams.set('view', view);
          window.open(current.toString(), '_blank', 'noopener');
        } else {
          setAppMode(view);
        }
        return;
      }
    } catch (_) {}
  }
  const url = viewerAppUrl(recordOrUrl, view);
  if (!url) {
    showToast(`${t('toast.actionFail')}: missing experiment URL`, false);
    return;
  }
  try {
    const target = new URL(url, window.location.href);
    if (!target.searchParams.get('view')) target.searchParams.set('view', view);
    if (options.newTab) window.open(target.toString(), '_blank', 'noopener');
    else window.location.assign(target.toString());
  } catch (_) {
    if (options.newTab) window.open(url, '_blank', 'noopener');
    else window.location.assign(url);
  }
}

// ── API ───────────────────────────────────────────────────────────────────────
function apiUrl(path) {
  const base = managerBase && String(path).startsWith('/auth/') ? managerBase : backendBase;
  return `${base}${API_PREFIX}${path}`;
}

function managerApiUrl(path) {
  const base = managerBase || (window.location.protocol.startsWith('http') ? window.location.origin : backendBase);
  return `${String(base).replace(/\/$/, '')}${API_PREFIX}${path}`;
}

function authStorageKey() {
  const authBase = managerBase || backendBase || 'default';
  try {
    return `trafficwm.auth.${new URL(authBase, window.location.href).origin}`;
  } catch (_) {
    return `trafficwm.auth.${String(authBase).replace(/\/proxy\/.*$/, '').replace(/\/$/, '')}`;
  }
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  return headers;
}

async function fetchJson(path, options = {}) {
  const requestToken = authToken;
  const headers = authHeaders(options.headers || {});
  const r = await fetch(apiUrl(path), { ...options, headers, cache: options.cache || 'no-store' });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) {
    handleAuthExpired(requestToken);
    throw new Error(j.error || t('toast.loginRequired'));
  }
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

async function managerGet(path) {
  const requestToken = authToken;
  const response = await fetch(managerApiUrl(path), { cache: 'no-store', headers: authHeaders() });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    handleAuthExpired(requestToken);
    throw new Error(payload.error || t('toast.loginRequired'));
  }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function managerPost(path, payload = {}) {
  const requestToken = authToken;
  const response = await fetch(managerApiUrl(path), {
    method: 'POST',
    cache: 'no-store',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));
  if (response.status === 401) {
    handleAuthExpired(requestToken);
    throw new Error(result.error || t('toast.loginRequired'));
  }
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function boundedPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0;
}

function setDashboardBar(id, value) {
  const element = $(id);
  if (element) element.style.width = `${boundedPercent(value)}%`;
}

function updateDashboardService(id, service) {
  const element = $(id);
  if (!element) return;
  const state = String(service?.run_state || '').toLowerCase();
  const ready = !!service?.model_loaded || state === 'ready';
  const disabled = state === 'disabled';
  element.textContent = ready ? '已就绪' : (disabled ? '未启用' : (state === 'error' ? '异常' : '检查中'));
  element.className = `service-state ${ready ? 'ready' : (state === 'error' ? 'error' : 'warning')}`;
}

function renderDashboard(payload) {
  const resources = payload?.resources || {};
  const cpu = resources.cpu || {};
  const gpu = resources.gpu || {};
  const memory = resources.memory || {};
  const storage = resources.storage || {};
  const experiments = payload?.experiments || {};
  const data = payload?.data || {};
  const cosmos = payload?.cosmos || {};
  const cpuPercent = boundedPercent(cpu.percent);
  const gpuPercent = boundedPercent(gpu.percent);
  const memoryPercent = boundedPercent(memory.percent);
  const storagePercent = boundedPercent(storage.percent);

  if ($('dashboardCpu')) $('dashboardCpu').textContent = `${cpuPercent.toFixed(1)}%`;
  if ($('dashboardCpuDetail')) $('dashboardCpuDetail').textContent = `${cpu.cores || 0} cores · load ${cpu.load_1m ?? '--'}`;
  if ($('dashboardGpu')) $('dashboardGpu').textContent = `${gpuPercent.toFixed(1)}%`;
  if ($('dashboardGpuDetail')) $('dashboardGpuDetail').textContent = `${gpu.used_gb ?? 0} / ${gpu.total_gb ?? 0} GB · ${gpu.count || 0} GPUs`;
  if ($('dashboardMemory')) $('dashboardMemory').textContent = `${memoryPercent.toFixed(1)}%`;
  if ($('dashboardMemoryDetail')) $('dashboardMemoryDetail').textContent = `${memory.used_gb ?? 0} / ${memory.total_gb ?? 0} GB`;
  if ($('dashboardActiveExperiments')) $('dashboardActiveExperiments').textContent = String(experiments.active || 0);
  if ($('dashboardExperimentDetail')) $('dashboardExperimentDetail').textContent = `累计 ${experiments.total || 0} · 完成 ${experiments.completed || 0}`;
  if ($('dashboardCpuInline')) $('dashboardCpuInline').textContent = `${cpuPercent.toFixed(0)}%`;
  if ($('dashboardGpuInline')) $('dashboardGpuInline').textContent = `${gpuPercent.toFixed(0)}%`;
  if ($('dashboardMemoryInline')) $('dashboardMemoryInline').textContent = `${memoryPercent.toFixed(0)}%`;
  if ($('dashboardStorageInline')) $('dashboardStorageInline').textContent = `${storagePercent.toFixed(0)}%`;
  setDashboardBar('dashboardCpuBar', cpuPercent);
  setDashboardBar('dashboardGpuBar', gpuPercent);
  setDashboardBar('dashboardMemoryBar', memoryPercent);
  setDashboardBar('dashboardStorageBar', storagePercent);
  if ($('dashboardScenarioCount')) $('dashboardScenarioCount').textContent = String(data.scenario_count || 0);
  if ($('dashboardStandardCount')) $('dashboardStandardCount').textContent = String(data.standard_scenario_count || 0);
  if ($('dashboardExperimentCount')) $('dashboardExperimentCount').textContent = `${experiments.total || 0} 次`;
  if ($('dashboardDataSize')) $('dashboardDataSize').textContent = `${Number(data.scenario_gb || 0).toFixed(2)} GB`;
  if ($('dashboardHealthText')) $('dashboardHealthText').textContent = cosmos.ready ? '平台核心服务已就绪' : '管理服务已连接';
  if ($('dashboardUpdatedAt')) $('dashboardUpdatedAt').textContent = payload.updated_at || '正在刷新资源状态';
  updateDashboardService('dashboardTransferState', cosmos.transfer || {});
  updateDashboardService('dashboardDreamsState', cosmos.omnidreams || {});
}

async function loadDashboard() {
  if (dashboardPollBusy || appMode !== 'home') return;
  dashboardPollBusy = true;
  try {
    const payload = await managerGet('/dashboard');
    if (payload?.resources) renderDashboard(payload);
  } catch (error) {
    if ($('dashboardHealthText')) $('dashboardHealthText').textContent = '平台状态暂不可用';
    if ($('dashboardUpdatedAt')) $('dashboardUpdatedAt').textContent = error.message;
  } finally {
    dashboardPollBusy = false;
  }
}

function standardScenarioIcon(category) {
  if (category === 'pedestrian') return 'bi-person-walking';
  if (category === 'cyclist') return 'bi-bicycle';
  return 'bi-car-front-fill';
}

function scenarioDuration(record) {
  const explicit = Number(record.max_sim_time);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  return Number(record.total_step || 0) * Number(record.sim_resolution || 0.1);
}

function scenarioPreviewVisual(path, mode, experimentId = '') {
  if (mode === 'video' && experimentId) {
    return `<video class="standard-scenario-seed scenario-card-preview" data-scenario-video-experiment="${escapeHtml(experimentId)}" muted autoplay loop playsinline preload="metadata"></video>`;
  }
  if (path && String(path).endsWith('.pkl')) {
    return `<canvas class="standard-scenario-seed scenario-card-preview" data-scenario-preview-path="${escapeHtml(path)}" width="640" height="360"></canvas>`;
  }
  return '<div class="standard-scenario-seed standard-scenario-seed-empty"><i class="bi bi-camera-video-off"></i><span>暂无动态预览</span></div>';
}

function drawScenarioPreviewFrame(canvas, payload, frameIndex) {
  const frame = payload?.frames?.[frameIndex % payload.frames.length];
  if (!canvas || !frame) return;
  const ctx = canvas.getContext('2d');
  const width = canvas.width || 640;
  const height = canvas.height || 360;
  ctx.fillStyle = '#111a22';
  ctx.fillRect(0, 0, width, height);
  const actors = frame.vehicles || [];
  const ego = actors.find(actor => actor.is_ego) || actors[0];
  const centerX = Number(ego?.x || 0);
  const centerY = Number(ego?.y || 0);
  const span = 75;
  const scale = Math.min(width, height) / span;
  ctx.strokeStyle = '#273746';
  ctx.lineWidth = 1;
  for (let offset = -80; offset <= 80; offset += 10) {
    const x = width / 2 + offset * scale;
    const y = height / 2 + offset * scale;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  (payload.map_state?.polylines || []).forEach(polyline => {
    const points = polyline.points || [];
    if (points.length < 2 || Number(polyline.type) === 4) return;
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = width / 2 + (Number(point[0]) - centerX) * scale;
      const y = height / 2 - (Number(point[1]) - centerY) * scale;
      if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.strokeStyle = Number(polyline.type) === 0 ? '#80909d' : '#536473';
    ctx.lineWidth = Number(polyline.type) === 0 ? 1.2 : 2;
    ctx.stroke();
  });
  actors.forEach(actor => {
    const x = width / 2 + (Number(actor.x) - centerX) * scale;
    const y = height / 2 - (Number(actor.y) - centerY) * scale;
    if (x < -20 || y < -20 || x > width + 20 || y > height + 20) return;
    const type = String(actor.type || '').toLowerCase();
    const pedestrian = type === 'pedestrian';
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-Number(actor.heading || 0));
    ctx.fillStyle = actor.is_ego ? '#facc15' : pedestrian ? '#fb7185' : (type.includes('cycl') || type.includes('non_motor') ? '#22c55e' : '#38bdf8');
    ctx.strokeStyle = actor.is_ego ? '#fff3a0' : '#020617';
    ctx.lineWidth = actor.is_ego ? 2 : 1;
    if (pedestrian) {
      ctx.beginPath(); ctx.arc(0, 0, 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else {
      const length = Math.max(5, Number(actor.length || 3.8) * scale);
      const actorWidth = Math.max(3, Number(actor.width || 1.8) * scale);
      ctx.fillRect(-length / 2, -actorWidth / 2, length, actorWidth);
      ctx.strokeRect(-length / 2, -actorWidth / 2, length, actorWidth);
    }
    ctx.restore();
  });
  ctx.fillStyle = '#d7e2ea';
  ctx.font = '12px sans-serif';
  ctx.fillText(`${Number(frame.sim_time || 0).toFixed(1)} s`, 10, 20);
  if (payload.ego_id) {
    ctx.fillStyle = '#facc15';
    ctx.fillText(`主车 #${payload.ego_id}`, 10, 38);
  }
}

async function loadScenarioPreview(path) {
  if (!scenarioPreviewCache.has(path)) {
    scenarioPreviewCache.set(path, managerGet(`/data/scenario-preview?path=${encodeURIComponent(path)}&max_frames=120`).then(async payload => {
      if (payload.map_path) {
        try {
          const previewBackend = payload.backend_model || 'cnde';
          const map = await managerGet(`/maps/preview?backend_model=${encodeURIComponent(previewBackend)}&path=${encodeURIComponent(payload.map_path)}`);
          payload.map_state = map.map_state || null;
        } catch (_) {}
      }
      return payload;
    }));
  }
  return scenarioPreviewCache.get(path);
}

function runScenarioPreviewAnimation(timestamp = performance.now()) {
  if (timestamp - lastScenarioPreviewPaintAt < 100) {
    scenarioPreviewAnimationFrame = window.requestAnimationFrame(runScenarioPreviewAnimation);
    return;
  }
  lastScenarioPreviewPaintAt = timestamp;
  document.querySelectorAll('canvas[data-scenario-preview-path]').forEach(canvas => {
    const payload = canvas._scenarioPreviewPayload;
    const rect = canvas.getBoundingClientRect();
    if (!payload?.frames?.length || rect.bottom < 0 || rect.top > window.innerHeight) return;
    const index = Math.floor((performance.now() - Number(canvas._scenarioPreviewStarted || 0)) / 160) % payload.frames.length;
    drawScenarioPreviewFrame(canvas, payload, index);
  });
  if (modalTrafficPreview?.frames?.length && !$('mediaPreviewTraffic')?.hidden) {
    const index = Math.floor(performance.now() / 100) % modalTrafficPreview.frames.length;
    drawScenarioPreviewFrame($('mediaPreviewTraffic'), modalTrafficPreview, index);
  }
  scenarioPreviewAnimationFrame = window.requestAnimationFrame(runScenarioPreviewAnimation);
}

function activateScenarioPreviews(root = document) {
  root.querySelectorAll('canvas[data-scenario-preview-path]').forEach(canvas => {
    loadScenarioPreview(canvas.dataset.scenarioPreviewPath).then(payload => {
      canvas._scenarioPreviewPayload = payload;
      canvas._scenarioPreviewStarted = performance.now();
      drawScenarioPreviewFrame(canvas, payload, 0);
    }).catch(() => {});
  });
  root.querySelectorAll('video[data-scenario-video-experiment]').forEach(video => {
    const experimentId = video.dataset.scenarioVideoExperiment;
    managerGet(`/artifacts?experiment_id=${encodeURIComponent(experimentId)}`).then(payload => {
      const videos = (payload.artifacts || []).filter(item => /video\//.test(String(item.content_type || '')) || /\.mp4$/i.test(String(item.path || '')));
      const preferred = videos.find(item => /omnidreams/i.test(`${item.kind} ${item.path}`)) || videos[0];
      if (preferred) {
        video.src = artifactUrl(preferred);
        video.play().catch(() => {});
      }
    }).catch(() => {});
  });
  if (!scenarioPreviewAnimationFrame) scenarioPreviewAnimationFrame = window.requestAnimationFrame(runScenarioPreviewAnimation);
}

async function openScenarioTrafficPreview(record) {
  const path = String(record?.path || record || '');
  if (!path) throw new Error('场景路径缺失');
  const modal = bootstrap.Modal.getOrCreateInstance($('mediaPreviewModal'));
  $('mediaPreviewModalTitle').textContent = record?.library_name || record?.name || path.split('/').pop();
  $('mediaPreviewModalSubtitle').textContent = '交通流动态预览 · 黄色为主车';
  $('mediaPreviewLoading').textContent = '正在读取场景轨迹...';
  $('mediaPreviewLoading').hidden = false;
  const player = $('mediaPreviewVideo');
  player.pause();
  player.hidden = true;
  const canvas = $('mediaPreviewTraffic');
  canvas.hidden = true;
  modal.show();
  modalTrafficPreview = await loadScenarioPreview(path);
  canvas.width = 1280;
  canvas.height = 720;
  canvas.hidden = false;
  $('mediaPreviewLoading').hidden = true;
  drawScenarioPreviewFrame(canvas, modalTrafficPreview, 0);
}

function renderStandardScenarios() {
  const grid = $('standardScenarioGrid');
  if (!grid) return;
  grid.classList.toggle('list-view', workflowScenarioViewMode === 'list');
  if (!standardScenarioRecords.length) {
    grid.innerHTML = '<div class="scenario-loading">未找到标准场景，请先执行场景库初始化。</div>';
    return;
  }
  grid.innerHTML = standardScenarioRecords.map(record => {
    const participants = record.participants || {};
    const selected = record.library_id === selectedStandardScenarioId;
    const duration = scenarioDuration(record);
    const hasSeed = standardScenarioHasReusableSeed(record);
    const sourceExperimentId = String(record.seed_bundle?.source_experiment_id || '');
    const contentMode = workflowScenarioContentModes.get(record.library_id) || 'traffic';
    const seedReason = String(record.seed_reason || record.seed_bundle?.reason || '该场景没有状态匹配的 RGB 首帧');
    const seedVisual = scenarioPreviewVisual(record.path, contentMode, sourceExperimentId);
    return `
      <article class="standard-scenario-card${selected ? ' selected' : ''}" data-standard-scenario="${escapeHtml(record.library_id || '')}">
        <input type="radio" name="standardScenario" value="${escapeHtml(record.library_id || '')}" ${selected ? 'checked' : ''} aria-label="选择 ${escapeHtml(record.library_name || '')}">
        ${seedVisual}
        <h4>${escapeHtml(record.library_name || record.path || '标准场景')}</h4>
        <p>${escapeHtml(record.library_description || '')}</p>
        <div class="standard-scenario-meta">
          <span>${escapeHtml(workflowTrafficModelLabel(record.backend_model || record.algorithm || 'cnde'))}</span>
          <span>机动车 ${Number(participants.motorized || 0)}</span>
          <span>行人 ${Number(participants.pedestrians || 0)}</span>
          <span>非机动车 ${Number(participants.cyclists || 0)}</span>
          <span class="standard-seed-state ${hasSeed ? 'ready' : 'missing'}" title="${escapeHtml(seedReason)}">${hasSeed ? '首帧可用' : '未保存首帧'}</span>
        </div>
        <div class="standard-scenario-actions">
          <small>${duration.toFixed(0)} s · 到达率 ${Number(record.arrival_rate || 0).toFixed(4)}</small>
          <span class="standard-scenario-tools">
            <span class="record-mode-switch"><button type="button" class="${contentMode === 'traffic' ? 'active' : ''}" data-standard-content="traffic" data-library-id="${escapeHtml(record.library_id || '')}" title="交通流预览"><i class="bi bi-sign-intersection"></i></button><button type="button" class="${contentMode === 'video' ? 'active' : ''}" data-standard-content="video" data-library-id="${escapeHtml(record.library_id || '')}" data-experiment-id="${escapeHtml(sourceExperimentId)}" title="多模态预览" ${sourceExperimentId ? '' : 'disabled'}><i class="bi bi-camera-video"></i></button></span>
            <button type="button" class="btn btn-sm btn-outline-secondary" data-standard-seed="${escapeHtml(record.library_id || '')}" title="${hasSeed ? '复核已有首帧' : '从同源视频获取匹配首帧'}"><i class="bi bi-camera"></i><span class="visually-hidden">获取或复核首帧</span></button>
            <button type="button" class="btn btn-sm btn-outline-secondary" data-standard-preview="${escapeHtml(record.library_id || '')}" title="动态预览"><i class="bi bi-play-btn"></i><span class="visually-hidden">动态预览</span></button>
          </span>
        </div>
      </article>`;
  }).join('');
  activateScenarioPreviews(grid);
}

function selectedStandardScenario() {
  return standardScenarioRecords.find(record => record.library_id === selectedStandardScenarioId) || null;
}

function standardScenarioHasReusableSeed(record) {
  return !!(
    record?.seed_available !== false
    && record?.seed_status !== 'invalid'
    && record?.use_existing_seed
    && record?.seed_image
    && record?.seed_init_file
    && record?.seed_ego_id
    && record?.seed_state_sha256
  );
}

async function refreshStandardScenarioSeed(libraryId, button = null) {
  const record = standardScenarioRecords.find(item => item.library_id === libraryId);
  if (!record?.path) return;
  if (button) button.disabled = true;
  try {
    const result = await managerPost('/data/action', {
      type: 'refresh_standard_scenario_seed',
      path: record.path,
    });
    await Promise.all([loadStandardScenarios(), loadDataRecords()]);
    const seed = result.seed || {};
    showToast(
      seed.available
        ? '已获取并核验场景首帧，启动时可跳过 Transfer 种子生成'
        : `未获取到匹配首帧：${seed.reason || result.message || '同源视频不可用'}`,
      !!seed.available,
    );
  } catch (error) {
    showToast(`首帧获取失败：${error.message}`, false);
  } finally {
    if (button) button.disabled = false;
  }
}

function workflowSelectedTrafficModel() {
  if (workflowScenarioMode === 'map') return $('workflowMapModelSelect')?.value || 'cnde';
  if (($('workflowScenarioExecutionModeSelect')?.value || 'continue') === 'replay') return 'cnde';
  const record = selectedStandardScenario();
  if (record?.standard_backend_locked && record.backend_model) return record.backend_model;
  return $('workflowLibraryModelSelect')?.value || 'cnde';
}

function workflowTrafficModelLabel(model) {
  if (model === 'neuralnde') return 'NeuralNDE';
  if (model === 'rulebased') return 'IDM 规则';
  return 'CityNDE';
}

function applySparseRuleDefaults() {
  if (workflowSelectedTrafficModel() !== 'rulebased') return;
  if ($('workflowLocalTargetInput')) $('workflowLocalTargetInput').value = '8';
  if ($('workflowInitialVehicleLimitInput')) $('workflowInitialVehicleLimitInput').value = '8';
  if ($('workflowArrivalRateInput')) $('workflowArrivalRateInput').value = '0.0000';
  if ($('workflowMaxPedestriansInput')) $('workflowMaxPedestriansInput').value = '0';
  if ($('workflowOmniActorLimitInput')) $('workflowOmniActorLimitInput').value = '7';
  if ($('workflowMixedTrafficToggle')) $('workflowMixedTrafficToggle').checked = false;
  if ($('workflowRuleSpeedInput') && !$('workflowRuleSpeedInput').value) $('workflowRuleSpeedInput').value = '10';
  if ($('workflowAvRuleSpeedInput') && !$('workflowAvRuleSpeedInput').value) $('workflowAvRuleSpeedInput').value = '19.44';
}

function updateWorkflowSummary() {
  const summary = $('workflowSummaryText');
  if (!summary) return;
  if (workflowScenarioMode === 'map') {
    const map = $('workflowMapSelect')?.value || '';
    const model = workflowSelectedTrafficModel();
    summary.textContent = map
      ? `${map.split('/').pop()} · ${workflowTrafficModelLabel(model)} · 随机初始化 · ${Math.max(10, Number($('workflowDurationInput')?.value || 15))} s`
      : '请选择一张地图。';
    return;
  }
  const record = selectedStandardScenario();
  if (!record) {
    summary.textContent = '请选择一个标准场景。';
    return;
  }
  const duration = Math.max(10, Number($('workflowDurationInput')?.value || 15));
  const dreams = !!$('workflowDreamsToggle')?.checked;
  const seedBackend = $('workflowSeedBackendSelect')?.value === 'transfer2.5'
    ? 'Transfer2.5 七视角'
    : 'Transfer1 Sample-AV';
  const seedMode = standardScenarioHasReusableSeed(record) ? '加载匹配首帧' : `${seedBackend} 生成首帧`;
  const model = workflowSelectedTrafficModel();
  summary.textContent = `${record.library_name} · ${workflowTrafficModelLabel(model)} · ${duration} s · ${dreams ? `OmniDreams 实时视频 · ${seedMode}` : '仅交通流'}`;
}

function updateWorkflowSeedBackend() {
  const backend = $('workflowSeedBackendSelect')?.value === 'transfer2.5' ? 'transfer2.5' : 'transfer1';
  const summary = $('workflowSeedBackendSummary');
  if (summary) summary.innerHTML = `<i class="bi bi-stars"></i>${backend === 'transfer2.5' ? 'Transfer2.5 七视角种子' : 'Transfer1 Sample-AV 种子'}`;
  updateWorkflowSummary();
}

function setWorkflowScenarioMode(mode) {
  workflowScenarioMode = mode === 'map' ? 'map' : 'library';
  document.querySelectorAll('[data-workflow-scenario-mode]').forEach(button => {
    button.classList.toggle('active', button.dataset.workflowScenarioMode === workflowScenarioMode);
  });
  if ($('workflowLibraryScenarioPanel')) $('workflowLibraryScenarioPanel').hidden = workflowScenarioMode !== 'library';
  if ($('workflowMapScenarioPanel')) $('workflowMapScenarioPanel').hidden = workflowScenarioMode !== 'map';
  const existingSeed = $('workflowExistingSeedToggle');
  if (existingSeed) {
    const hasSeed = workflowScenarioMode === 'library'
      && standardScenarioHasReusableSeed(selectedStandardScenario());
    existingSeed.checked = hasSeed;
    existingSeed.disabled = !hasSeed;
    existingSeed.closest('label').title = hasSeed
      ? '使用标准场景保存的首帧，跳过 Transfer 种子生成'
      : (workflowScenarioMode === 'map'
        ? '地图随机初始化没有可复用首帧，将使用 Transfer2.5 生成种子'
        : '该场景未保存外观首帧，将使用 Transfer2.5 生成种子');
  }
  if (workflowScenarioMode === 'map') loadWorkflowMaps();
  updateWorkflowModelControls();
  updateWorkflowSummary();
}

function updateWorkflowModelControls() {
  const selectedRecord = selectedStandardScenario();
  const executionMode = $('workflowScenarioExecutionModeSelect');
  const neuralContinuationOnly = workflowScenarioMode === 'library'
    && !!selectedRecord?.standard_backend_locked
    && selectedRecord.backend_model === 'neuralnde';
  if (executionMode) {
    if (neuralContinuationOnly) executionMode.value = 'continue';
    executionMode.disabled = neuralContinuationOnly;
    executionMode.title = neuralContinuationOnly
      ? 'NeuralNDE 标准场景使用原生模型确定性续推'
      : '';
  }
  const model = workflowSelectedTrafficModel();
  const ruleSpeedInput = $('workflowRuleSpeedInput');
  if (ruleSpeedInput) {
    ruleSpeedInput.disabled = model !== 'rulebased';
    ruleSpeedInput.title = model === 'rulebased' ? '规则交通流中所有 BV 的 IDM 目标速度' : '仅规则交通流可配置';
  }
  const avRuleSpeedInput = $('workflowAvRuleSpeedInput');
  if (avRuleSpeedInput) {
    const enabled = model === 'rulebased' && $('workflowAvModelSelect')?.value === 'IDM_MOBIL';
    avRuleSpeedInput.disabled = !enabled;
    avRuleSpeedInput.title = enabled ? '内部 IDM+MOBIL 主车的目标速度' : '仅规则交通流的 IDM+MOBIL 主车可配置';
  }
  const summaryModel = $('workflowTrafficModelSelect');
  if (summaryModel) {
    summaryModel.value = model;
    summaryModel.disabled = true;
    summaryModel.title = '交通流模型由场景选择节点统一配置';
  }
  const replay = workflowScenarioMode === 'library'
    && ($('workflowScenarioExecutionModeSelect')?.value || 'continue') === 'replay';
  const locked = workflowScenarioMode === 'library'
    && !!selectedRecord?.standard_backend_locked;
  if ($('workflowLibraryModelSelect')) {
    $('workflowLibraryModelSelect').disabled = replay || locked;
    $('workflowLibraryModelSelect').title = replay
      ? '离线轨迹复现不运行交通流推理'
      : locked
        ? '该标准场景绑定了生成它的交通流模型'
      : '使用标准场景的初始状态续推';
  }
  const initMode = $('workflowMapInitModeSelect');
  if (initMode) {
    const datasetManaged = model === 'neuralnde';
    initMode.disabled = datasetManaged;
    initMode.title = datasetManaged
      ? 'NeuralNDE 使用所选数据集的原生初始化方式'
      : '';
  }
}

async function loadWorkflowMaps(preferred = '') {
  const loadSequence = ++workflowMapLoadSequence;
  const model = $('workflowMapModelSelect')?.value || 'cnde';
  const select = $('workflowMapSelect');
  if (!select) return;
  const requestedSelection = preferred || select.value;
  try {
    const payload = await managerGet(`/maps?backend_model=${encodeURIComponent(model)}`);
    if (loadSequence !== workflowMapLoadSequence) return;
    const current = preferred || select.value || requestedSelection;
    select.innerHTML = '';
    (payload.maps || []).forEach(path => {
      const option = document.createElement('option');
      option.value = path;
      option.textContent = String(path).split('/').pop();
      select.appendChild(option);
    });
    if (current && Array.from(select.options).some(option => option.value === current)) select.value = current;
    if (!select.options.length) select.appendChild(new Option('当前模型没有可用地图', ''));
  } catch (error) {
    if (loadSequence !== workflowMapLoadSequence) return;
    select.innerHTML = '';
    select.appendChild(new Option(`地图读取失败：${error.message}`, ''));
  }
  updateWorkflowSummary();
}

function selectStandardScenario(libraryId, applyScenarioDefaults = true) {
  if (!standardScenarioRecords.some(record => record.library_id === libraryId)) return;
  selectedStandardScenarioId = libraryId;
  const record = selectedStandardScenario();
  const boundModel = String(record.backend_model || record.algorithm || 'cnde');
  if ($('workflowLibraryModelSelect')) $('workflowLibraryModelSelect').value = boundModel;
  if (boundModel === 'neuralnde' && $('workflowScenarioExecutionModeSelect')) {
    $('workflowScenarioExecutionModeSelect').value = 'continue';
  }
  if ($('workflowSeedInput') && record.initialization_seed != null) {
    $('workflowSeedInput').value = String(record.initialization_seed);
  }
  if ($('workflowArrivalRateInput')) $('workflowArrivalRateInput').value = Number(record.arrival_rate || 0.0002).toFixed(4);
  if (applyScenarioDefaults && $('workflowWorldPromptInput') && record.default_world_prompt) {
    $('workflowWorldPromptInput').value = String(record.default_world_prompt);
  }
  if (applyScenarioDefaults && $('workflowLocalTargetInput') && record.world_local_target_count != null) {
    $('workflowLocalTargetInput').value = String(record.world_local_target_count);
  }
  if (applyScenarioDefaults && $('workflowInitialVehicleLimitInput') && record.world_initial_vehicle_limit != null) {
    $('workflowInitialVehicleLimitInput').value = String(record.world_initial_vehicle_limit);
  }
  if (applyScenarioDefaults && $('workflowOmniActorLimitInput') && record.world_omnidreams_actor_max_count != null) {
    $('workflowOmniActorLimitInput').value = String(record.world_omnidreams_actor_max_count);
  }
  if (applyScenarioDefaults && $('worldSeedRadiusSelect') && record.world_seed_map_radius_m != null) {
    const radius = String(record.world_seed_map_radius_m);
    if (Array.from($('worldSeedRadiusSelect').options).some(option => option.value === radius)) {
      $('worldSeedRadiusSelect').value = radius;
    }
  }
  const existingSeed = $('workflowExistingSeedToggle');
  if (existingSeed) {
    const hasSeed = standardScenarioHasReusableSeed(record);
    existingSeed.checked = hasSeed;
    existingSeed.disabled = !hasSeed;
    existingSeed.closest('label').title = hasSeed
      ? '使用标准场景保存的首帧，跳过 Transfer 种子生成'
      : '该场景未保存外观首帧，将使用 Transfer2.5 生成种子';
  }
  renderStandardScenarios();
  updateWorkflowModelControls();
  updateWorkflowSummary();
}

async function loadStandardScenarios() {
  try {
    const payload = await managerGet('/data/standard-scenarios');
    standardScenarioRecords = Array.isArray(payload.records) ? payload.records : [];
    if ($('taskStandardScenarioCount')) $('taskStandardScenarioCount').textContent = String(standardScenarioRecords.length);
    if ($('taskAvailability')) {
      const available = standardScenarioRecords.length > 0;
      $('taskAvailability').textContent = available ? '可用' : '不可用';
      $('taskAvailability').classList.toggle('text-success', available);
      $('taskAvailability').classList.toggle('text-danger', !available);
    }
    if (!selectedStandardScenarioId && standardScenarioRecords.length) {
      selectedStandardScenarioId = standardScenarioRecords[0].library_id || '';
    }
    if (selectedStandardScenarioId && !standardScenarioRecords.some(record => record.library_id === selectedStandardScenarioId)) {
      selectedStandardScenarioId = standardScenarioRecords[0]?.library_id || '';
    }
    renderStandardScenarios();
    if (selectedStandardScenarioId) selectStandardScenario(selectedStandardScenarioId);
  } catch (error) {
    standardScenarioRecords = [];
    if ($('taskStandardScenarioCount')) $('taskStandardScenarioCount').textContent = '0';
    if ($('taskAvailability')) {
      $('taskAvailability').textContent = '不可用';
      $('taskAvailability').classList.remove('text-success');
      $('taskAvailability').classList.add('text-danger');
    }
    const grid = $('standardScenarioGrid');
    if (grid) grid.innerHTML = `<div class="scenario-loading">场景库读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function readWorkflows() {
  if (workflowRecords.length) return workflowRecords.map(workflow => ({ ...workflow }));
  try {
    const value = JSON.parse(localStorage.getItem(WORKFLOW_STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch (_) {
    return [];
  }
}

function writeWorkflows(workflows) {
  workflowRecords = workflows.map(workflow => ({ ...workflow }));
  localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify(workflows));
}

async function loadWorkflows() {
  try {
    const payload = await managerGet('/workflows');
    writeWorkflows(Array.isArray(payload.workflows) ? payload.workflows : []);
  } catch (_) {
    workflowRecords = readWorkflows();
  }
  refreshWorkflowSelect();
}

function nextWorkflowId(workflows) {
  const date = new Date();
  const stamp = `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}`;
  const prefix = `DW-WF-${stamp}-`;
  const next = workflows.reduce((maximum, workflow) => {
    const match = String(workflow.id || '').match(new RegExp(`^${prefix}(\\d{4})$`));
    return match ? Math.max(maximum, Number(match[1])) : maximum;
  }, 0) + 1;
  return `${prefix}${String(next).padStart(4, '0')}`;
}

function workflowFormValue() {
  const existingWorkflow = readWorkflows().find(workflow => workflow.id === selectedWorkflowId) || {};
  const workflowName = $('workflowNameInput')?.value?.trim() || '';
  const durationSeconds = Math.max(10, Number($('workflowDurationInput')?.value || 15));
  return {
    // Preserve backend-only reproducibility controls when a workflow is
    // opened and saved through the visual editor.
    ...existingWorkflow,
    id: selectedWorkflowId,
    name: workflowName,
    task_id: 'DW-TASK-0001',
    scenario_mode: workflowScenarioMode,
    scenario_execution_mode: workflowScenarioMode === 'library'
      ? ($('workflowScenarioExecutionModeSelect')?.value || 'continue')
      : 'continue',
    scenario_id: workflowScenarioMode === 'library' ? selectedStandardScenarioId : '',
    map_path: workflowScenarioMode === 'map' ? ($('workflowMapSelect')?.value || '') : '',
    map_init_mode: $('workflowMapInitModeSelect')?.value || 'random_tl_only',
    av_selection_mode: workflowScenarioMode === 'map'
      ? ($('workflowMapAvSelectionSelect')?.value || 'manual')
      : ($('workflowLibraryAvSelectionSelect')?.value || 'existing'),
    av_model: $('workflowAvModelSelect')?.value || 'DEFAULT_TCP',
    command_mode: $('workflowCommandModeSelect')?.value || 'state',
    connection_mode: 'internal',
    observations: {
      camera: !!$('workflowCameraToggle')?.checked,
      vehicle_state: !!$('workflowVehicleStateToggle')?.checked,
      map: !!$('workflowMapInfoToggle')?.checked,
      traffic_lights: !!$('workflowSignalToggle')?.checked,
      traffic: !!$('workflowTrafficInfoToggle')?.checked,
      lidar: false,
    },
    camera_config: { ...workflowCameraConfig },
    traffic_model: workflowSelectedTrafficModel(),
    duration_seconds: durationSeconds,
    gpu_id: $('workflowGpuInput')?.value?.trim() || '4',
    arrival_rate: Math.max(0, Math.min(1, Number($('workflowArrivalRateInput')?.value || 0.0002))),
    world_local_target_count: Math.max(1, Math.min(48, Number($('workflowLocalTargetInput')?.value || 16))),
    world_initial_vehicle_limit: Math.max(1, Math.min(128, Number($('workflowInitialVehicleLimitInput')?.value || 18))),
    max_pedestrians: Math.max(0, Math.min(256, Number($('workflowMaxPedestriansInput')?.value || 8))),
    world_omnidreams_actor_max_count: Math.max(1, Math.min(128, Number($('workflowOmniActorLimitInput')?.value || 16))),
    rule_desired_speed_mps: Math.max(1, Math.min(35, Number($('workflowRuleSpeedInput')?.value || 10))),
    av_desired_speed_mps: Math.max(1, Math.min(35, Number($('workflowAvRuleSpeedInput')?.value || 19.44))),
    multimodal_enabled: !!$('workflowMultimodalToggle')?.checked,
    dreams_enabled: !!$('workflowDreamsToggle')?.checked,
    world_seed_alignment_mode: $('workflowSeedAlignmentSelect')?.value || 'terminal_continue',
    world_seed_backend: $('workflowSeedBackendSelect')?.value || 'transfer1',
    world_transfer_seed: Number(existingWorkflow.world_transfer_seed ?? 0),
    world_omnidreams_seed: Number(existingWorkflow.world_omnidreams_seed ?? 1),
    world_prompt: $('workflowWorldPromptInput')?.value?.trim() || DEFAULT_WORLD_PROMPT,
    world_omnidreams_segment_seconds: Number(
      existingWorkflow.world_omnidreams_segment_seconds ?? 0,
    ),
    world_omnidreams_rollover_mode: String(
      existingWorkflow.world_omnidreams_rollover_mode || 'latest',
    ),
    world_omnidreams_anchor_mode: String(
      existingWorkflow.world_omnidreams_anchor_mode || 'conditioned_front',
    ),
    world_omnidreams_anchor_transfer_steps: Number(
      existingWorkflow.world_omnidreams_anchor_transfer_steps ?? 12,
    ),
    world_omnidreams_anchor_transfer_seed: Number(
      existingWorkflow.world_omnidreams_anchor_transfer_seed
        ?? existingWorkflow.world_transfer_seed
        ?? 0,
    ),
    world_omnidreams_transition_frames: Number(
      existingWorkflow.world_omnidreams_transition_frames ?? 0,
    ),
    world_omnidreams_rollover_chroma_blur_radius: Number(
      existingWorkflow.world_omnidreams_rollover_chroma_blur_radius ?? 0,
    ),
    world_omnidreams_rollover_saturation_percent: Number(
      existingWorkflow.world_omnidreams_rollover_saturation_percent ?? 100,
    ),
    world_omnidreams_rollover_image_format: String(
      existingWorkflow.world_omnidreams_rollover_image_format || 'jpeg',
    ),
    world_stationary_anchor_enabled: !!existingWorkflow.world_stationary_anchor_enabled,
    world_stationary_speed_threshold_mps: Number(
      existingWorkflow.world_stationary_speed_threshold_mps ?? 0.35,
    ),
    world_stationary_exit_speed_mps: Number(
      existingWorkflow.world_stationary_exit_speed_mps ?? 0.8,
    ),
    world_stationary_enter_seconds: Number(
      existingWorkflow.world_stationary_enter_seconds ?? 0.75,
    ),
    world_stationary_reset_seconds: Number(
      existingWorkflow.world_stationary_reset_seconds ?? 6,
    ),
    use_existing_seed: workflowScenarioMode === 'library'
      && !!$('workflowExistingSeedToggle')?.checked
      && !$('workflowExistingSeedToggle')?.disabled,
    evaluation: {
      safety: Number($('workflowSafetyWeight')?.value || 0),
      comfort: Number($('workflowComfortWeight')?.value || 0),
      efficiency: Number($('workflowEfficiencyWeight')?.value || 0),
    },
    evaluation_metrics: JSON.parse(JSON.stringify(workflowEvaluationMetrics)),
    evaluation_system_id: workflowEvaluationSystemId,
    evaluation_system_name: workflowEvaluationSystemName,
    scenario_count: Math.max(1, Math.min(1000, Number($('workflowScenarioCountInput')?.value || 1))),
    seed: Math.max(0, Number($('workflowSeedInput')?.value || 42)),
    vehicle_size_mode: $('workflowVehicleSizeSelect')?.value || 'mixed',
    initial_speed_mode: $('workflowInitialSpeedSelect')?.value || 'urban_sampled',
    save_result: !!$('workflowSaveResultToggle')?.checked,
    mixed_traffic_enabled: !!$('workflowMixedTrafficToggle')?.checked,
    updated_at: new Date().toISOString(),
  };
}

function refreshWorkflowSelect() {
  const select = $('savedWorkflowSelect');
  if (!select) return;
  const workflows = readWorkflows();
  select.innerHTML = '<option value="">新建流程</option>';
  workflows.forEach(workflow => {
    const option = document.createElement('option');
    option.value = workflow.id;
    option.textContent = `${workflow.id} · ${workflow.name}`;
    select.appendChild(option);
  });
  select.value = workflows.some(workflow => workflow.id === selectedWorkflowId) ? selectedWorkflowId : '';
}

function applyWorkflow(workflow) {
  if (!workflow) return;
  selectedWorkflowId = String(workflow.id || '');
  if ($('workflowNameInput')) $('workflowNameInput').value = workflow.name || '';
  if ($('workflowAvModelSelect')) $('workflowAvModelSelect').value = workflow.av_model || 'DEFAULT_TCP';
  if ($('workflowCommandModeSelect')) $('workflowCommandModeSelect').value = workflow.command_mode || 'state';
  const observations = workflow.observations || {};
  if ($('workflowCameraToggle')) $('workflowCameraToggle').checked = observations.camera !== false;
  if ($('workflowVehicleStateToggle')) $('workflowVehicleStateToggle').checked = observations.vehicle_state !== false;
  if ($('workflowMapInfoToggle')) $('workflowMapInfoToggle').checked = observations.map !== false;
  if ($('workflowSignalToggle')) $('workflowSignalToggle').checked = observations.traffic_lights !== false;
  if ($('workflowTrafficInfoToggle')) $('workflowTrafficInfoToggle').checked = observations.traffic !== false;
  workflowCameraConfig = { ...workflowCameraConfig, ...(workflow.camera_config || {}) };
  workflowCameraConfig.enabled = observations.camera !== false;
  const workflowModel = workflow.traffic_model || 'cnde';
  if ($('workflowTrafficModelSelect')) $('workflowTrafficModelSelect').value = workflowModel;
  if ($('workflowMapModelSelect')) $('workflowMapModelSelect').value = workflowModel;
  if ($('workflowLibraryModelSelect')) {
    $('workflowLibraryModelSelect').value = ['cnde', 'neuralnde', 'rulebased'].includes(workflowModel)
      ? workflowModel
      : 'cnde';
  }
  if ($('workflowDurationInput')) $('workflowDurationInput').value = String(workflow.duration_seconds || 15);
  if ($('workflowGpuInput')) $('workflowGpuInput').value = workflow.gpu_id || '4';
  if ($('workflowArrivalRateInput')) $('workflowArrivalRateInput').value = Number(workflow.arrival_rate ?? 0.0002).toFixed(4);
  if ($('workflowScenarioExecutionModeSelect')) $('workflowScenarioExecutionModeSelect').value = workflow.scenario_execution_mode || 'continue';
  if ($('workflowLocalTargetInput')) $('workflowLocalTargetInput').value = String(workflow.world_local_target_count || 16);
  if ($('workflowInitialVehicleLimitInput')) $('workflowInitialVehicleLimitInput').value = String(workflow.world_initial_vehicle_limit || 18);
  if ($('workflowMaxPedestriansInput')) $('workflowMaxPedestriansInput').value = String(workflow.max_pedestrians ?? 8);
  if ($('workflowOmniActorLimitInput')) $('workflowOmniActorLimitInput').value = String(workflow.world_omnidreams_actor_max_count || 16);
  if ($('workflowRuleSpeedInput')) $('workflowRuleSpeedInput').value = String(workflow.rule_desired_speed_mps ?? 10);
  if ($('workflowAvRuleSpeedInput')) $('workflowAvRuleSpeedInput').value = String(workflow.av_desired_speed_mps ?? 19.44);
  if ($('workflowMultimodalToggle')) $('workflowMultimodalToggle').checked = workflow.multimodal_enabled !== false;
  if ($('workflowDreamsToggle')) $('workflowDreamsToggle').checked = workflow.dreams_enabled !== false;
  if ($('workflowSeedAlignmentSelect')) {
    $('workflowSeedAlignmentSelect').value = workflow.world_seed_alignment_mode || 'terminal_continue';
  }
  if ($('workflowSeedBackendSelect')) {
    $('workflowSeedBackendSelect').value = workflow.world_seed_backend || 'transfer1';
  }
  if ($('workflowWorldPromptInput')) $('workflowWorldPromptInput').value = workflow.world_prompt || DEFAULT_WORLD_PROMPT;
  if ($('workflowScenarioCountInput')) $('workflowScenarioCountInput').value = String(workflow.scenario_count || 1);
  if ($('workflowSeedInput')) $('workflowSeedInput').value = String(workflow.seed ?? 42);
  if ($('workflowVehicleSizeSelect')) $('workflowVehicleSizeSelect').value = workflow.vehicle_size_mode || 'mixed';
  if ($('workflowInitialSpeedSelect')) $('workflowInitialSpeedSelect').value = workflow.initial_speed_mode || 'urban_sampled';
  if ($('workflowSaveResultToggle')) $('workflowSaveResultToggle').checked = workflow.save_result !== false;
  if ($('workflowMixedTrafficToggle')) $('workflowMixedTrafficToggle').checked = workflow.mixed_traffic_enabled !== false;
  const evaluation = workflow.evaluation || {};
  if ($('workflowSafetyWeight')) $('workflowSafetyWeight').value = String(evaluation.safety ?? 45);
  if ($('workflowComfortWeight')) $('workflowComfortWeight').value = String(evaluation.comfort ?? 25);
  if ($('workflowEfficiencyWeight')) $('workflowEfficiencyWeight').value = String(evaluation.efficiency ?? 30);
  workflowEvaluationMetrics = normalizeEvaluationMetrics(workflow.evaluation_metrics);
  workflowEvaluationSystemId = String(workflow.evaluation_system_id || 'DW-EVAL-0001');
  workflowEvaluationSystemName = String(workflow.evaluation_system_name || '自然交通流自动驾驶综合评价');
  renderWorkflowEvaluationPreview();
  updateWorkflowSeedBackend();
  setWorkflowScenarioMode(workflow.scenario_mode || 'library');
  if (workflow.scenario_id) selectStandardScenario(workflow.scenario_id, false);
  if ($('workflowExistingSeedToggle')) {
    const record = selectedStandardScenario();
    const hasSeed = (workflow.scenario_mode || 'library') === 'library'
      && standardScenarioHasReusableSeed(record);
    $('workflowExistingSeedToggle').checked = hasSeed && workflow.use_existing_seed !== false;
    $('workflowExistingSeedToggle').disabled = !hasSeed;
  }
  if (workflow.map_path) loadWorkflowMaps(workflow.map_path);
  if ($('workflowMapInitModeSelect')) $('workflowMapInitModeSelect').value = workflow.map_init_mode || 'random_tl_only';
  const selectionId = (workflow.scenario_mode || 'library') === 'map' ? 'workflowMapAvSelectionSelect' : 'workflowLibraryAvSelectionSelect';
  if ($(selectionId)) ensureSelectOption(selectionId, workflow.av_selection_mode || 'manual');
  if ($('workflowIdBadge')) $('workflowIdBadge').textContent = workflow.id || '系统将在保存时分配 ID';
  refreshWorkflowSelect();
  updateWorkflowSummary();
}

function availableWorkflowName(name, workflows, excludedId = '') {
  const base = String(name || '').trim() || '未命名测试流程';
  const occupied = new Set(
    workflows
      .filter(workflow => workflow.id !== excludedId)
      .map(workflow => String(workflow.name || '').trim()),
  );
  if (!occupied.has(base)) return base;
  let suffix = 2;
  while (occupied.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

async function saveWorkflow(options = {}) {
  const workflows = readWorkflows();
  const value = workflowFormValue();
  if (!value.name) {
    showToast('请输入测试流程名称', false);
    return null;
  }
  const weightTotal = Object.values(value.evaluation).reduce((sum, weight) => sum + Number(weight || 0), 0);
  if (Math.abs(weightTotal - 100) > 0.001) {
    showToast(`评价体系权重合计必须为 100%，当前为 ${weightTotal}%`, false);
    return null;
  }
  const duplicate = workflows.find(workflow => workflow.name.trim() === value.name && workflow.id !== selectedWorkflowId);
  if (duplicate) {
    if (!options.renameDuplicate) {
      showToast(`流程名称已存在：${duplicate.name}`, false);
      return null;
    }
    value.name = availableWorkflowName(value.name, workflows, selectedWorkflowId);
    if ($('workflowNameInput')) $('workflowNameInput').value = value.name;
  }
  if (value.scenario_mode === 'library' && !selectedStandardScenario()) {
    showToast('请选择标准场景', false);
    return null;
  }
  if (value.scenario_mode === 'map' && !value.map_path) {
    showToast('请选择地图', false);
    return null;
  }
  let saved = value;
  try {
    const result = await managerPost('/workflows/action', { type: 'save', workflow: value });
    saved = result.workflow || value;
    writeWorkflows(Array.isArray(result.workflows) ? result.workflows : [...workflows.filter(item => item.id !== saved.id), saved]);
  } catch (error) {
    showToast(`测试流程保存失败：${error.message}`, false);
    return null;
  }
  selectedWorkflowId = saved.id;
  if ($('workflowIdBadge')) $('workflowIdBadge').textContent = saved.id;
  refreshWorkflowSelect();
  showToast(`测试流程已保存：${saved.id}`, true);
  return saved;
}

function loadSelectedWorkflow() {
  const id = $('savedWorkflowSelect')?.value || '';
  const workflow = readWorkflows().find(item => item.id === id);
  if (!workflow) {
    showToast('请选择要加载的测试流程', false);
    return;
  }
  applyWorkflow(workflow);
  showToast(`已加载：${workflow.name}`, true);
}

function copySelectedWorkflow() {
  const current = workflowFormValue();
  current.id = '';
  current.name = `${current.name || '测试流程'} 副本`;
  selectedWorkflowId = '';
  if ($('workflowIdBadge')) $('workflowIdBadge').textContent = '系统将在保存时分配 ID';
  if ($('workflowNameInput')) $('workflowNameInput').value = current.name;
  refreshWorkflowSelect();
  showToast('已创建流程副本，请修改名称后保存', true);
}

async function deleteSelectedWorkflow() {
  if (!selectedWorkflowId) {
    showToast('当前是未保存的新流程', false);
    return;
  }
  const deletingId = selectedWorkflowId;
  let workflows = readWorkflows().filter(workflow => workflow.id !== deletingId);
  try {
    const result = await managerPost('/workflows/action', { type: 'delete', workflow_id: deletingId });
    workflows = Array.isArray(result.workflows) ? result.workflows : workflows;
  } catch (error) {
    showToast(`测试流程删除失败：${error.message}`, false);
    return;
  }
  writeWorkflows(workflows);
  selectedWorkflowId = '';
  refreshWorkflowSelect();
  showToast('测试流程已删除', true);
}

async function applyWorkflowToWorkbench() {
  const workflow = workflowFormValue();
  const record = workflow.scenario_mode === 'library' ? selectedStandardScenario() : null;
  if (workflow.scenario_mode === 'library' && !record) throw new Error('请选择标准场景');
  const backendModel = workflow.traffic_model || 'cnde';
  workflowScenarioConfigurationLocked = !!record;
  if ($('trafficModelSelect')) $('trafficModelSelect').value = backendModel;
  updateTrafficModelControls();
  await loadMaps();
  const mapPath = record?.map_path || workflow.map_path;
  if (mapPath) ensureSelectOption('mapSelect', mapPath, String(mapPath).split('/').pop());
  await loadScenarios();
  updateInitModeOptions(
    backendModel,
    record ? (backendModel === 'neuralnde' ? 'official_dataset' : 'data') : workflow.map_init_mode,
  );
  if (record && backendModel !== 'neuralnde') {
    ensureSelectOption('initDataSelect', record.path, record.library_name || String(record.path).split('/').pop());
  }
  updateInitModeControls();
  if ($('experimentNameStartInput')) $('experimentNameStartInput').value = `${workflow.name || 'workflow'}_${Date.now()}`;
  if ($('gpuIdInput')) $('gpuIdInput').value = workflow.gpu_id;
  if ($('runUntilStoppedToggle')) $('runUntilStoppedToggle').checked = false;
  if ($('totalStepInput')) $('totalStepInput').value = String(workflow.duration_seconds);
  updateRunDurationControls();
  if ($('arrivalRateInput')) $('arrivalRateInput').value = Number(workflow.arrival_rate).toFixed(4);
  pendingDefaultArrivalRate = workflow.arrival_rate;
  pendingLaneArrivalRates = {};
  if ($('scenarioCountInput')) $('scenarioCountInput').value = String(workflow.scenario_count || 1);
  if ($('mixedTrafficToggle')) $('mixedTrafficToggle').checked = record ? !!record.mixed_traffic_enabled : workflow.mixed_traffic_enabled;
  if ($('vehicleSizeModeSelect')) $('vehicleSizeModeSelect').value = workflow.vehicle_size_mode;
  if ($('initialSpeedModeSelect')) $('initialSpeedModeSelect').value = workflow.initial_speed_mode;
  if ($('cyclistRatioSelect') && record) ensureSelectOption('cyclistRatioSelect', String(record.cyclist_ratio || 0), String(record.cyclist_ratio || 0));
  if ($('pedestrianDensitySelect') && record) ensureSelectOption('pedestrianDensitySelect', String(record.pedestrians_per_crosswalk || 0), String(record.pedestrians_per_crosswalk || 0));
  updateMixedTrafficControls();
  const internalAv = ['DEFAULT_TCP', 'IDM_MOBIL'].includes(workflow.av_model);
  if ($('avAccessToggle')) $('avAccessToggle').checked = internalAv;
  if ($('avControlModelSelect')) $('avControlModelSelect').value = workflow.av_model;
  if ($('avCommandModeSelect')) $('avCommandModeSelect').value = workflow.command_mode;
  if ($('avSelectionModeSelect')) {
    const selectionMode = workflow.av_selection_mode === 'random' ? 'random' : 'manual';
    $('avSelectionModeSelect').value = selectionMode;
  }
  updateAvAccessControls();
  if ($('multimodalModelSelect')) $('multimodalModelSelect').value = workflow.multimodal_enabled ? 'denseworld' : 'none';
  updateDenseWorldControls();
  if ($('worldDreamsToggle')) $('worldDreamsToggle').checked = workflow.multimodal_enabled && workflow.dreams_enabled;
  if ($('worldPromptInput')) $('worldPromptInput').value = workflow.world_prompt || DEFAULT_WORLD_PROMPT;
  if ($('worldTransferFullToggle')) $('worldTransferFullToggle').checked = false;
  if ($('worldSeedImageInput')) {
    $('worldSeedImageInput').value = record && workflow.use_existing_seed ? (record.seed_image || '') : '';
  }
  return { workflow, record, mapPath, backendModel };
}

async function openWorkflowWorkbench(start = false) {
  try {
    if (start && !selectedWorkflowId && !await saveWorkflow({ renameDuplicate: true })) return;
    await applyWorkflowToWorkbench();
    if (start) {
      if (typeof startConfiguredExperiment !== 'function') throw new Error('实验启动服务尚未就绪');
      await startConfiguredExperiment();
      return;
    }
    setAppMode('generate');
  } catch (error) {
    showToast(`流程配置失败：${error.message}`, false);
  }
}

async function previewStandardScenario(libraryId) {
  selectStandardScenario(libraryId);
  const record = selectedStandardScenario();
  if (!record) return;
  await openScenarioTrafficPreview(record);
}

async function previewWorkflowMap() {
  try {
    setWorkflowScenarioMode('map');
    const { mapPath, backendModel } = await applyWorkflowToWorkbench();
    const preview = await managerGet(
      `/maps/preview?backend_model=${encodeURIComponent(backendModel)}&path=${encodeURIComponent(mapPath || '')}`,
    );
    setAppMode('generate');
    mapData = { ok: true, ...(preview.map_state || {}) };
    rebuildMapIndexes();
    invalidateStaticMapLayer();
    await loadMapRaster(mapData);
    updateLaneOptions();
    frameLoaded = true;
    vectorFitDone = true;
    resizeTrafficCanvas();
    fitFrame();
    requestDrawFrame();
    showToast('地图语义数据已载入，可检查道路、斑马线和信号灯', true);
  } catch (error) {
    showToast(`地图预览失败：${error.message}`, false);
  }
}

function openWorkflowCameraConfig() {
  const enabled = workflowCameraConfig.enabled !== false && !!$('workflowCameraToggle')?.checked;
  workflowCameraConfig.enabled = enabled;
  if ($('workflowCameraNameInput')) $('workflowCameraNameInput').value = workflowCameraConfig.name || '前向主摄像头';
  if ($('workflowCameraPresetSelect')) $('workflowCameraPresetSelect').value = workflowCameraConfig.preset || 'front_wide_120';
  if ($('workflowCameraIntrinsicInput')) $('workflowCameraIntrinsicInput').value = '';
  if ($('workflowCameraExtrinsicInput')) $('workflowCameraExtrinsicInput').value = '';
  updateWorkflowCameraFileStatus();
  if ($('workflowCameraConfigRow')) $('workflowCameraConfigRow').hidden = !enabled;
  if ($('workflowCameraCount')) $('workflowCameraCount').textContent = enabled ? '1 / 1' : '0 / 1';
  if ($('workflowCameraAddBtn')) $('workflowCameraAddBtn').disabled = enabled;
  if ($('workflowCameraDeleteBtn')) $('workflowCameraDeleteBtn').disabled = !enabled;
  bootstrap.Modal.getOrCreateInstance($('workflowCameraModal')).show();
}

function updateWorkflowCameraFileStatus() {
  const intrinsicName = workflowCameraConfig.intrinsic_data?.name || workflowCameraConfig.intrinsic_file || '';
  const extrinsicName = workflowCameraConfig.extrinsic_data?.name || workflowCameraConfig.extrinsic_file || '';
  if ($('workflowCameraIntrinsicStatus')) {
    $('workflowCameraIntrinsicStatus').textContent = intrinsicName ? `已保存：${intrinsicName}` : '使用默认标定';
  }
  if ($('workflowCameraExtrinsicStatus')) {
    $('workflowCameraExtrinsicStatus').textContent = extrinsicName ? `已保存：${extrinsicName}` : '使用默认标定';
  }
}

async function cameraCalibrationPayload(file, previous) {
  if (!file) return previous || null;
  if (file.size > CAMERA_CALIBRATION_MAX_BYTES) {
    throw new Error(`${file.name} 超过 256 KiB 上限`);
  }
  const content = await file.text();
  let sha256 = '';
  if (globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
    sha256 = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
  }
  return {
    name: file.name,
    type: file.type || 'text/plain',
    size: file.size,
    content,
    sha256,
  };
}

function setWorkflowCameraEnabled(enabled) {
  workflowCameraConfig.enabled = !!enabled;
  if ($('workflowCameraToggle')) $('workflowCameraToggle').checked = !!enabled;
  if ($('workflowCameraConfigRow')) $('workflowCameraConfigRow').hidden = !enabled;
  if ($('workflowCameraCount')) $('workflowCameraCount').textContent = enabled ? '1 / 1' : '0 / 1';
  if ($('workflowCameraAddBtn')) $('workflowCameraAddBtn').disabled = !!enabled;
  if ($('workflowCameraDeleteBtn')) $('workflowCameraDeleteBtn').disabled = !enabled;
}

async function saveWorkflowCameraConfig() {
  if (workflowCameraConfig.enabled === false) {
    bootstrap.Modal.getInstance($('workflowCameraModal'))?.hide();
    showToast('摄像头观测已从当前流程删除', true);
    return;
  }
  let intrinsicData;
  let extrinsicData;
  try {
    [intrinsicData, extrinsicData] = await Promise.all([
      cameraCalibrationPayload($('workflowCameraIntrinsicInput')?.files?.[0], workflowCameraConfig.intrinsic_data),
      cameraCalibrationPayload($('workflowCameraExtrinsicInput')?.files?.[0], workflowCameraConfig.extrinsic_data),
    ]);
  } catch (error) {
    showToast(`标定文件保存失败：${error.message}`, false);
    return;
  }
  workflowCameraConfig = {
    enabled: true,
    name: $('workflowCameraNameInput')?.value?.trim() || '前向主摄像头',
    preset: $('workflowCameraPresetSelect')?.value || 'front_wide_120',
    intrinsic_file: intrinsicData?.name || '',
    extrinsic_file: extrinsicData?.name || '',
    intrinsic_data: intrinsicData,
    extrinsic_data: extrinsicData,
  };
  updateWorkflowCameraFileStatus();
  if ($('workflowCameraToggle')) $('workflowCameraToggle').checked = true;
  bootstrap.Modal.getInstance($('workflowCameraModal'))?.hide();
  showToast('摄像头配置已写入当前测试流程', true);
}

const EVALUATION_CATEGORY_CONTROLS = {
  safety: ['evaluationSafetyEnabled', 'evaluationSafetyModalWeight'],
  comfort: ['evaluationComfortEnabled', 'evaluationComfortModalWeight'],
  efficiency: ['evaluationEfficiencyEnabled', 'evaluationEfficiencyModalWeight'],
};
const EVALUATION_METRIC_LABELS = {
  av_overlap_frames: '碰撞次数', minimum_ttc: '最小 TTC', traffic_violation_rate: '交通违规率',
  longitudinal_acceleration_rms: '纵向加速度', lateral_acceleration_rms: '横向加速度', jerk_p95: '加加速度',
  mean_speed: '平均速度', elapsed_time: '通行时间', stopped_time_ratio: '停车时间比',
};

function evaluationMetricConfigFromDom() {
  const config = {};
  Object.entries(EVALUATION_CATEGORY_CONTROLS).forEach(([category, [enabledId]]) => {
    const section = document.querySelector(`[data-evaluation-category="${category}"]`);
    const metrics = {};
    section?.querySelectorAll('[data-evaluation-metric]').forEach(input => {
      const id = input.dataset.evaluationMetric;
      const weight = section.querySelector(`[data-evaluation-metric-weight="${id}"]`);
      metrics[id] = { enabled: !!input.checked, weight: Number(weight?.value || 0) };
    });
    config[category] = { enabled: !!$(enabledId)?.checked, metrics };
  });
  return config;
}

function applyEvaluationMetricConfigToDom(config = workflowEvaluationMetrics) {
  const normalized = normalizeEvaluationMetrics(config);
  Object.entries(EVALUATION_CATEGORY_CONTROLS).forEach(([category, [enabledId]]) => {
    const categoryConfig = normalized[category];
    if ($(enabledId)) $(enabledId).checked = categoryConfig.enabled !== false;
    Object.entries(categoryConfig.metrics || {}).forEach(([metricId, metric]) => {
      const input = document.querySelector(`[data-evaluation-metric="${metricId}"]`);
      const weight = document.querySelector(`[data-evaluation-metric-weight="${metricId}"]`);
      if (input) input.checked = metric.enabled !== false;
      if (weight) weight.value = String(metric.weight ?? 0);
    });
  });
}

function renderWorkflowEvaluationPreview() {
  document.querySelectorAll('.evaluation-tree-preview > span').forEach((element, index) => {
    const category = ['safety', 'comfort', 'efficiency'][index];
    const config = workflowEvaluationMetrics[category] || DEFAULT_EVALUATION_METRICS[category];
    const labels = Object.entries(config.metrics || {})
      .filter(([, metric]) => metric.enabled !== false)
      .map(([metricId]) => EVALUATION_METRIC_LABELS[metricId] || metricId);
    element.classList.toggle('disabled', config.enabled === false);
    const detail = element.querySelector('em');
    if (detail) detail.textContent = config.enabled === false ? '已从体系移除' : (labels.join(' · ') || '无二级指标');
  });
}

function evaluationModalTotal() {
  let total = 0;
  const invalidCategories = [];
  Object.entries(EVALUATION_CATEGORY_CONTROLS).forEach(([category, [enabledId, weightId]]) => {
    const enabled = !!$(enabledId)?.checked;
    if ($(weightId)) $(weightId).disabled = !enabled;
    if (enabled) total += Number($(weightId)?.value || 0);
    const section = document.querySelector(`[data-evaluation-category="${category}"]`);
    let metricTotal = 0;
    section?.querySelectorAll('[data-evaluation-metric]').forEach(input => {
      const weight = section.querySelector(`[data-evaluation-metric-weight="${input.dataset.evaluationMetric}"]`);
      input.disabled = !enabled;
      if (weight) weight.disabled = !enabled || !input.checked;
      if (enabled && input.checked) metricTotal += Number(weight?.value || 0);
    });
    if (enabled && Math.abs(metricTotal - 100) > 0.001) invalidCategories.push(category);
  });
  const valid = Math.abs(total - 100) <= 0.001 && invalidCategories.length === 0;
  const hint = $('evaluationWeightHint');
  if (hint) {
    hint.textContent = `一级权重合计：${total}% · ${invalidCategories.length ? '二级权重未满 100%' : '二级权重有效'}`;
    hint.classList.toggle('error', !valid);
  }
  return { total, valid };
}

function defaultEvaluationSystem() {
  return {
    id: 'DW-EVAL-0001',
    name: '自然交通流自动驾驶综合评价',
    description: '覆盖安全性、舒适性和效率的可量化自动驾驶评价体系。',
    readonly: true,
    weights: { safety: 45, comfort: 25, efficiency: 30 },
    metrics: normalizeEvaluationMetrics(),
  };
}

function readEvaluationSystems(records = null) {
  let stored = Array.isArray(records) ? records : [];
  if (!Array.isArray(records)) {
    try {
      const value = JSON.parse(localStorage.getItem(EVALUATION_SYSTEM_STORAGE_KEY) || '[]');
      if (Array.isArray(value)) stored = value.filter(item => item && typeof item === 'object');
    } catch (_) {}
  }
  const defaultSystem = defaultEvaluationSystem();
  evaluationSystemRecords = [
    defaultSystem,
    ...stored
      .filter(item => String(item.id || '') !== defaultSystem.id)
      .map(item => ({
        ...item,
        id: String(item.id || ''),
        name: String(item.name || ''),
        description: String(item.description || ''),
        readonly: false,
        metrics: normalizeEvaluationMetrics(item.metrics),
      })),
  ];
  return evaluationSystemRecords;
}

async function loadEvaluationSystems() {
  try {
    const payload = await managerGet('/evaluation-systems');
    const records = Array.isArray(payload.evaluation_systems) ? payload.evaluation_systems : [];
    readEvaluationSystems(records);
    writeEvaluationSystems();
  } catch (_) {
    readEvaluationSystems();
  }
  return evaluationSystemRecords;
}

function writeEvaluationSystems() {
  const custom = evaluationSystemRecords.filter(item => !item.readonly);
  localStorage.setItem(EVALUATION_SYSTEM_STORAGE_KEY, JSON.stringify(custom));
}

function renderEvaluationSystemSelect() {
  const select = $('evaluationSystemSelect');
  if (!select) return;
  select.innerHTML = evaluationSystemRecords.map(system => (
    `<option value="${escapeHtml(system.id)}">${escapeHtml(system.id)} · ${escapeHtml(system.name)}</option>`
  )).join('');
  if (evaluationSystemRecords.some(system => system.id === selectedEvaluationSystemId)) {
    select.value = selectedEvaluationSystemId;
  }
}

function loadEvaluationSystemEditor(system) {
  if (!system) return;
  selectedEvaluationSystemId = String(system.id || '');
  if ($('evaluationSystemNameInput')) $('evaluationSystemNameInput').value = system.name || '';
  if ($('evaluationSystemDescriptionInput')) $('evaluationSystemDescriptionInput').value = system.description || '';
  if ($('evaluationSafetyModalWeight')) $('evaluationSafetyModalWeight').value = String(system.weights?.safety ?? 45);
  if ($('evaluationComfortModalWeight')) $('evaluationComfortModalWeight').value = String(system.weights?.comfort ?? 25);
  if ($('evaluationEfficiencyModalWeight')) $('evaluationEfficiencyModalWeight').value = String(system.weights?.efficiency ?? 30);
  applyEvaluationMetricConfigToDom(system.metrics);
  if ($('deleteEvaluationSystemBtn')) $('deleteEvaluationSystemBtn').disabled = !!system.readonly;
  renderEvaluationSystemSelect();
  evaluationModalTotal();
}

function evaluationSystemFromEditor() {
  return {
    id: selectedEvaluationSystemId,
    name: $('evaluationSystemNameInput')?.value?.trim() || '',
    description: $('evaluationSystemDescriptionInput')?.value?.trim() || '',
    weights: {
      safety: Number($('evaluationSafetyModalWeight')?.value || 0),
      comfort: Number($('evaluationComfortModalWeight')?.value || 0),
      efficiency: Number($('evaluationEfficiencyModalWeight')?.value || 0),
    },
    metrics: evaluationMetricConfigFromDom(),
  };
}

function copyEvaluationSystem() {
  const source = evaluationSystemFromEditor();
  selectedEvaluationSystemId = '';
  if ($('evaluationSystemNameInput')) $('evaluationSystemNameInput').value = `${source.name || '评价体系'} 副本`;
  if ($('deleteEvaluationSystemBtn')) $('deleteEvaluationSystemBtn').disabled = true;
  if ($('evaluationSystemSelect')) $('evaluationSystemSelect').value = '';
  showToast('已创建可编辑副本，保存后写入评价体系库', true);
}

async function saveEvaluationSystem() {
  const validation = evaluationModalTotal();
  if (!validation.valid) {
    showToast('启用的一级和各组二级指标权重均必须合计为 100%', false);
    return;
  }
  const candidate = evaluationSystemFromEditor();
  if (!candidate.name) {
    showToast('请输入评价体系名称', false);
    return;
  }
  const current = evaluationSystemRecords.find(system => system.id === selectedEvaluationSystemId);
  const duplicate = evaluationSystemRecords.find(system => (
    system.id !== selectedEvaluationSystemId
    && String(system.name || '').trim().toLocaleLowerCase() === candidate.name.toLocaleLowerCase()
  ));
  if (duplicate) {
    showToast(`评价体系名称已存在：${duplicate.name}`, false);
    return;
  }
  candidate.id = current && !current.readonly ? current.id : '';
  try {
    const result = await managerPost('/evaluation-systems/action', {
      type: 'save',
      evaluation_system: candidate,
    });
    readEvaluationSystems(result.evaluation_systems || []);
    selectedEvaluationSystemId = result.evaluation_system?.id || '';
    writeEvaluationSystems();
  } catch (error) {
    showToast(`评价体系保存失败：${error.message}`, false);
    return;
  }
  renderEvaluationSystemSelect();
  if ($('deleteEvaluationSystemBtn')) $('deleteEvaluationSystemBtn').disabled = false;
  showToast(`评价体系已保存：${candidate.name}`, true);
}

async function deleteEvaluationSystem() {
  const current = evaluationSystemRecords.find(system => system.id === selectedEvaluationSystemId);
  if (!current || current.readonly) return;
  if (!window.confirm(`删除评价体系“${current.name}”？`)) return;
  try {
    const result = await managerPost('/evaluation-systems/action', {
      type: 'delete',
      evaluation_system_id: current.id,
    });
    readEvaluationSystems(result.evaluation_systems || []);
    writeEvaluationSystems();
  } catch (error) {
    showToast(`评价体系删除失败：${error.message}`, false);
    return;
  }
  loadEvaluationSystemEditor(evaluationSystemRecords[0]);
  showToast('评价体系已删除', true);
}

async function openEvaluationLibrary() {
  await loadEvaluationSystems();
  const selected = evaluationSystemRecords.find(system => system.id === workflowEvaluationSystemId)
    || evaluationSystemRecords[0];
  loadEvaluationSystemEditor(selected);
  bootstrap.Modal.getOrCreateInstance($('evaluationLibraryModal')).show();
}

function applyEvaluationSystem(close = true) {
  const validation = evaluationModalTotal();
  if (!validation.valid) {
    showToast('启用的一级和各组二级指标权重均必须合计为 100%', false);
    return;
  }
  const values = [
    ['workflowSafetyWeight', 'evaluationSafetyEnabled', 'evaluationSafetyModalWeight'],
    ['workflowComfortWeight', 'evaluationComfortEnabled', 'evaluationComfortModalWeight'],
    ['workflowEfficiencyWeight', 'evaluationEfficiencyEnabled', 'evaluationEfficiencyModalWeight'],
  ];
  values.forEach(([targetId, enabledId, sourceId]) => {
    if ($(targetId)) $(targetId).value = $(enabledId)?.checked ? ($(sourceId)?.value || '0') : '0';
  });
  workflowEvaluationMetrics = evaluationMetricConfigFromDom();
  workflowEvaluationSystemId = selectedEvaluationSystemId || 'workflow-custom';
  workflowEvaluationSystemName = $('evaluationSystemNameInput')?.value?.trim() || '当前流程自定义评价体系';
  renderWorkflowEvaluationPreview();
  if (close) bootstrap.Modal.getInstance($('evaluationLibraryModal'))?.hide();
  showToast('评价体系已应用到当前流程', true);
}

function artifactUrl(item) {
  const url = new URL(managerApiUrl(`/artifacts/file?path=${encodeURIComponent(item.path || '')}`));
  if (authToken) url.searchParams.set('access_token', authToken);
  return url.toString();
}

function artifactLiveUrl(item) {
  const url = new URL(managerApiUrl(`/artifacts/live.mjpeg?path=${encodeURIComponent(item.path || '')}`));
  if (activeExperimentId) url.searchParams.set('experiment_id', activeExperimentId);
  if (authToken) url.searchParams.set('access_token', authToken);
  return url.toString();
}

function currentPlaybackVideoTime(state = simData) {
  const streamed = Number(worldPreviewStatus?.playback_time);
  if (worldPreviewStatus?.started && Number.isFinite(streamed)) return streamed;
  const synchronized = Number(state?.world_video_time);
  return Number.isFinite(synchronized) ? synchronized : NaN;
}

function worldPreviewTargetSeconds(status = lastStatus) {
  const payload = worldGeneration?.payload || {};
  const progress = payload.omnidreams_progress || {};
  const targetFrames = Number(progress.target_frames);
  const outputFps = Number(progress.fps || worldPreviewStatus?.output_fps);
  const frameDuration = Number.isFinite(targetFrames) && Number.isFinite(outputFps) && outputFps > 0
    ? targetFrames / outputFps
    : NaN;
  const candidates = [
    payload.traffic_duration_seconds,
    payload.duration_seconds,
    progress.required_traffic_time,
    progress.requested_traffic_time,
    frameDuration,
    status?.max_sim_time,
    status?.sim_time,
  ];
  const target = candidates.map(Number).find(value => Number.isFinite(value) && value > 0);
  return Number.isFinite(target) ? target : NaN;
}

function worldPreviewPlaybackComplete(status = lastStatus) {
  const terminal = worldPreviewStatus?.terminal === true;
  const playbackIndex = Number(worldPreviewStatus?.playback_index);
  const newestIndex = Number(worldPreviewStatus?.newest_index);
  if (
    terminal
    && Number.isFinite(playbackIndex)
    && Number.isFinite(newestIndex)
    && playbackIndex >= newestIndex
  ) {
    return true;
  }
  const playbackTime = Number(worldPreviewStatus?.playback_time);
  const targetSeconds = worldPreviewTargetSeconds(status);
  const outputFps = Math.max(1, Number(worldPreviewStatus?.output_fps || 30));
  const tolerance = Math.max(0.1, 2 / outputFps);
  return terminal
    && Number.isFinite(playbackTime)
    && Number.isFinite(targetSeconds)
    && playbackTime >= targetSeconds - tolerance;
}

function experimentPresentationComplete(status = lastStatus) {
  const trafficState = String(status?.run_state || runState || 'idle');
  if (['error', 'stopped', 'interrupted'].includes(trafficState)) return true;
  if (trafficState !== 'completed' && !status?.experiment_completed) return false;

  const worldState = String(worldGeneration?.run_state || '');
  if (!worldState) return true;
  if (['error', 'stopped', 'interrupted'].includes(worldState)) return true;
  if (worldState !== 'completed') return false;

  const progress = worldGeneration?.payload?.omnidreams_progress || {};
  const generatedTime = Number(progress.generated_video_time ?? worldPreviewStatus?.generated_video_time);
  const targetSeconds = worldPreviewTargetSeconds(status);
  const outputFps = Math.max(1, Number(progress.fps || worldPreviewStatus?.output_fps || 30));
  if (
    Number.isFinite(generatedTime)
    && Number.isFinite(targetSeconds)
    && generatedTime < targetSeconds - Math.max(0.1, 2 / outputFps)
  ) {
    return false;
  }

  const hasLivePreview = worldArtifacts.some(item => item.kind === 'omnidreams_live_preview');
  return !hasLivePreview || worldPreviewPlaybackComplete(status);
}

function updateLiveTelemetry(state = simData) {
  const trafficTime = Number(state?.sim_time);
  const videoTime = currentPlaybackVideoTime(state);
  const syncDelta = videoTime - trafficTime;
  if ($('statSimTime') && Number.isFinite(trafficTime)) {
    $('statSimTime').textContent = formatDuration(trafficTime);
  }
  if ($('statVideoTime')) {
    $('statVideoTime').textContent = Number.isFinite(videoTime) ? `${videoTime.toFixed(2)} s` : '—';
  }
  if ($('statSyncDelta')) {
    $('statSyncDelta').textContent = Number.isFinite(syncDelta) ? `${syncDelta.toFixed(2)} s` : '—';
  }

  const vehicles = Array.isArray(state?.vehicles) ? state.vehicles : null;
  if (vehicles) {
    const pedestrians = vehicles.filter(actor => roadUserType(actor) === 'pedestrian');
    const cyclists = vehicles.filter(actor => ['cyclist', 'non_motorized', 'bicycle'].includes(roadUserType(actor)));
    const motorized = vehicles.filter(actor => !['pedestrian', 'cyclist', 'non_motorized', 'bicycle'].includes(roadUserType(actor)));
    const speeds = motorized.map(actor => {
      const explicit = Number(actor.speed);
      if (Number.isFinite(explicit)) return Math.max(0, explicit);
      const vx = Number(actor.vx);
      const vy = Number(actor.vy);
      return Number.isFinite(vx) && Number.isFinite(vy) ? Math.hypot(vx, vy) : NaN;
    }).filter(Number.isFinite);
    if ($('statVehicles')) $('statVehicles').textContent = String(motorized.length);
    if ($('statCyclists')) $('statCyclists').textContent = String(cyclists.length);
    if ($('statPedestrians')) $('statPedestrians').textContent = String(pedestrians.length);
    if ($('statAvgSpeed')) {
      $('statAvgSpeed').textContent = speeds.length
        ? `${(speeds.reduce((sum, speed) => sum + speed, 0) / speeds.length).toFixed(2)} m/s`
        : '—';
    }
  }

  const badge = $('multimodalSyncBadge');
  if (!badge) return;
  const generatedTime = Number(
    worldGeneration?.payload?.omnidreams_progress?.generated_video_time
      ?? worldPreviewStatus?.generated_video_time
  );
  const bufferSeconds = Number(worldPreviewStatus?.buffer_seconds);
  const playbackFps = Number(worldPreviewStatus?.playback_fps);
  const arrivalFps = Number(worldPreviewStatus?.arrival_preview_fps);
  const sourcePlaybackFps = Number(worldPreviewStatus?.source_playback_fps);
  const generationWarmed = worldPreviewStatus?.generation_warmed === true;
  if (!Number.isFinite(videoTime)) {
    badge.textContent = !generationWarmed
      ? '模型预热中 · 已显示首帧'
      : Number.isFinite(generatedTime)
      ? `正在缓冲 · 已生成 ${generatedTime.toFixed(1)} s`
      : '等待视频';
    badge.className = `badge ${Number.isFinite(generatedTime) ? 'text-bg-warning' : 'text-bg-secondary'}`;
    return;
  }
  badge.textContent = `播放 ${videoTime.toFixed(1)} s${Number.isFinite(playbackFps) ? ` · 预览 ${playbackFps.toFixed(1)} fps` : ''}${Number.isFinite(bufferSeconds) ? ` · 视频积压 ${bufferSeconds.toFixed(1)} s` : ''}`;
  badge.title = [
    Number.isFinite(generatedTime) ? `后端已生成 ${generatedTime.toFixed(1)} s` : '',
    Number.isFinite(arrivalFps) ? `真实到达率 ${arrivalFps.toFixed(1)} fps` : '',
    Number.isFinite(sourcePlaybackFps) ? `源帧消费 ${sourcePlaybackFps.toFixed(1)} fps` : '',
  ].filter(Boolean).join(' · ');
  badge.className = `badge ${Number.isFinite(syncDelta) && Math.abs(syncDelta) <= 0.15 ? 'text-bg-success' : 'text-bg-warning'}`;
}

function serviceBadge(elementId, service = {}) {
  const badge = $(elementId);
  if (!badge) return;
  const state = service.run_state || 'disabled';
  badge.textContent = state;
  badge.className = `badge ${state === 'ready' ? 'text-bg-success' : (state === 'error' ? 'text-bg-danger' : 'text-bg-secondary')}`;
}

function worldQuality() {
  const payload = worldGeneration?.payload || {};
  const audit = payload.joint_flow_audit || null;
  const trafficAudit = payload.traffic_safety_audit || null;
  const reports = [
    payload.control_quality,
    payload.transfer_quality,
    payload.full_control_quality,
    payload.full_transfer_quality,
    payload.omnidreams_quality,
  ].filter(Boolean);
  if (!reports.length && !audit && !trafficAudit) return null;
  const warnings = reports.flatMap(report => [
    ...(report.warnings || []),
    ...(report.views || []).flatMap(view => view.warnings || []),
  ]);
  const appearance = payload.appearance_conditioning || payload.anchor_geometry || {};
  if (appearance.status === 'control_only_unanchored') {
    warnings.unshift('当前路线未匹配 RGB 外观锚点，Transfer 已降级为纯场景图生成');
  } else if (appearance.status === 'rejected_cached_anchor') {
    warnings.unshift('地图缓存锚点与当前场景图版本不匹配，Transfer 已安全降级为纯控制生成');
  } else if (appearance.status === 'unverified_external_anchor') {
    warnings.unshift('外部首帧未通过场景图几何校验');
  }
  const failedAuditChecks = Object.entries(audit?.checks || {})
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
  const failedTrafficChecks = Object.entries(trafficAudit?.checks || {})
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
  return {
    passed: (!audit || audit.passed)
      && (!trafficAudit || trafficAudit.passed)
      && reports.every(report => report.passed),
    checks: { ...(audit?.checks || {}), ...(trafficAudit?.checks || {}) },
    errors: [...(audit?.errors || []), ...failedAuditChecks, ...failedTrafficChecks].concat(reports.flatMap(report => [
      ...(report.group_errors || []),
      ...(report.views || []).flatMap(view => view.errors || []),
    ])),
    warnings,
  };
}

function renderWorldBenchmarks() {
  const body = $('worldBenchmarkBody');
  if (!body) return;
  body.innerHTML = '';
  const latest = new Map();
  worldBenchmarks.forEach(item => {
    const key = `${item.model}:${item.gpu_count}`;
    if (!latest.has(key)) latest.set(key, item);
  });
  const rows = [...latest.values()].sort((a, b) => String(a.model).localeCompare(String(b.model)) || a.gpu_count - b.gpu_count);
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="text-secondary">—</td></tr>';
    return;
  }
  rows.forEach(item => {
    const metrics = item.metrics || {};
    const seconds = Number(metrics.generation_seconds ?? metrics.end_to_end_seconds);
    const duration = Number(item.duration_seconds || 10);
    const rtf = Number.isFinite(seconds) && duration > 0 ? seconds / duration : NaN;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${escapeHtml(item.model || '')}</td><td>${Number(item.gpu_count || 0)}</td>`
      + `<td>${Number.isFinite(seconds) ? `${seconds.toFixed(1)} s` : '—'}</td>`
      + `<td>${Number.isFinite(rtf) ? `${rtf.toFixed(2)}x` : '—'}</td>`
      + `<td><span class="badge ${item.run_state === 'completed' ? 'text-bg-success' : 'text-bg-danger'}">${escapeHtml(item.run_state || '')}</span></td>`;
    body.appendChild(tr);
  });
}

function renderWorldVideoOptions() {
  const select = $('worldVideoSelect');
  const player = $('worldVideoPlayer');
  const placeholder = $('worldVideoPlaceholder');
  if (!select || !player || !placeholder) return;
  let livePreview = $('worldLivePreview');
  if (!livePreview) {
    livePreview = document.createElement('img');
    livePreview.id = 'worldLivePreview';
    livePreview.className = 'denseworld-video mb-2';
    livePreview.alt = 'OmniDreams live preview';
    livePreview.decoding = 'async';
    livePreview.fetchPriority = 'high';
    livePreview.hidden = true;
    player.insertAdjacentElement('afterend', livePreview);
  }
  const videos = worldArtifacts.filter(item => item.mime_type === 'video/mp4');
  const livePreviewArtifact = worldArtifacts.find(item => item.kind === 'omnidreams_live_preview');
  const previewActive = Boolean(livePreviewArtifact && isWorldPreviewActive());
  const playbackVideoTime = currentPlaybackVideoTime();
  updateLiveTelemetry();
  const renderSignature = JSON.stringify({
    experiment: activeExperimentId,
    previewActive,
    artifacts: worldArtifacts.map(item => [item.kind, item.path, item.mime_type]),
  });
  if (renderSignature === worldVideoRenderSignature) return;
  worldVideoRenderSignature = renderSignature;
  const selectedSource = select.value;
  select.innerHTML = '';
  if (previewActive) {
    const option = document.createElement('option');
    option.value = OMNIDREAMS_LIVE_SOURCE;
    option.textContent = Number.isFinite(playbackVideoTime)
      ? `${t('multimodal.omnidreamsLive')} · ${playbackVideoTime.toFixed(1)} s`
      : t('multimodal.omnidreamsLive');
    select.appendChild(option);
  }
  // While generation is active this surface is the synchronized live monitor.
  // Completed seed/replay clips remain available from the artifact list below.
  (previewActive ? [] : videos).forEach(item => {
    const option = document.createElement('option');
    option.value = item.path;
    option.textContent = item.kind.replaceAll('_', ' ');
    select.appendChild(option);
  });
  if (!previewActive && videos.some(item => item.path === selectedSource)) {
    select.value = selectedSource;
  }
  const preferredVideo = videos.find(item => item.kind === 'omnidreams_video')
    || videos.find(item => item.kind.endsWith('front_wide_smooth'));
  const previewKey = previewActive
    ? `${activeExperimentId}:${livePreviewArtifact.path || ''}`
    : '';
  if (previewActive) {
    select.value = OMNIDREAMS_LIVE_SOURCE;
    select.dataset.autoLivePreviewKey = previewKey;
  } else if (!previewActive && preferredVideo && select.dataset.autoSelectedPath !== preferredVideo.path) {
    select.value = preferredVideo.path;
    select.dataset.autoSelectedPath = preferredVideo.path;
  }
  select.disabled = previewActive || select.options.length <= 1;
  const selectedLivePreview = previewActive && select.value === OMNIDREAMS_LIVE_SOURCE;
  const selected = videos.find(item => item.path === select.value) || videos[0];
  if (selectedLivePreview) {
    if (appMode === 'experiment' && autoOpenedWorldPreviewKey !== previewKey) {
      const multimodalTab = $('tab-multimodal');
      if (multimodalTab && window.bootstrap?.Tab) {
        bootstrap.Tab.getOrCreateInstance(multimodalTab).show();
        autoOpenedWorldPreviewKey = previewKey;
      }
    }
    player.pause();
    player.hidden = true;
    placeholder.hidden = true;
    $('worldVideoPlayBtn').disabled = true;
    $('worldVideoPauseBtn').disabled = true;
    $('worldVideoDownloadBtn').classList.add('disabled');
    $('worldVideoDownloadBtn').href = '#';
    livePreview.onload = () => {
      livePreview.hidden = false;
      player.hidden = true;
      placeholder.hidden = true;
    };
    livePreview.onerror = () => {
      livePreview.hidden = true;
      placeholder.hidden = false;
      livePreview.removeAttribute('src');
      livePreview.dataset.path = '';
      worldVideoRenderSignature = '';
    };
    if (livePreview.dataset.path !== livePreviewArtifact.path) {
      livePreview.dataset.path = livePreviewArtifact.path;
      const liveUrl = new URL(artifactLiveUrl(livePreviewArtifact));
      liveUrl.searchParams.set('stream_nonce', String(Date.now()));
      livePreview.src = liveUrl.toString();
    }
    livePreview.hidden = false;
  } else if (selected) {
    livePreview.removeAttribute('src');
    livePreview.dataset.path = '';
    livePreview.hidden = true;
    const nextSource = artifactUrl(selected);
    if (player.dataset.path !== selected.path) {
      player.src = nextSource;
      player.dataset.path = selected.path;
      player.load();
    }
    player.hidden = false;
    placeholder.hidden = true;
    $('worldVideoPlayBtn').disabled = false;
    $('worldVideoPauseBtn').disabled = false;
    $('worldVideoDownloadBtn').classList.remove('disabled');
    $('worldVideoDownloadBtn').href = nextSource;
  } else {
    player.pause();
    player.hidden = true;
    placeholder.hidden = false;
    $('worldVideoPlayBtn').disabled = true;
    $('worldVideoPauseBtn').disabled = true;
    $('worldVideoDownloadBtn').classList.add('disabled');
    $('worldVideoDownloadBtn').href = '#';
    livePreview.removeAttribute('src');
    livePreview.dataset.path = '';
    livePreview.hidden = true;
  }
}

function isWorldPreviewActive() {
  const stage = worldGeneration?.stage || '';
  const run = worldGeneration?.run_state || '';
  const generationActive = stage === 'omnidreams'
    && !['completed', 'error', 'stopped', 'interrupted'].includes(run);
  const previewDraining = worldPreviewStatus?.started === true
    && !worldPreviewPlaybackComplete();
  return generationActive || previewDraining;
}

function renderWorldPanel() {
  serviceBadge('transferServiceBadge', cosmosServices.transfer || {});
  serviceBadge('dreamsServiceBadge', cosmosServices.omnidreams || {});
  const stage = worldGeneration?.stage || '';
  const run = worldGeneration?.run_state || '';
  const progress = Math.max(0, Math.min(100, Math.round(Number(worldGeneration?.progress || 0) * 100)));
  const openEnded = !!worldGeneration?.payload?.run_until_stopped
    && stage === 'omnidreams'
    && !['completed', 'error', 'stopped', 'interrupted'].includes(run);
  $('worldStageText').textContent = worldGeneration?.message || (activeExperimentId ? '等待流水线状态' : '未选择实验');
  $('worldProgressBar').style.width = `${openEnded ? 100 : progress}%`;
  $('worldProgressBar').textContent = openEnded ? t('world.generatingOpenEnded') : `${progress}%`;
  $('worldProgressBar').className = openEnded
    ? 'progress-bar progress-bar-striped progress-bar-animated bg-info'
    : `progress-bar ${run === 'error' ? 'bg-danger' : (run === 'completed' ? 'bg-success' : 'bg-info')}`;
  const currentIndex = WORLD_STAGE_ORDER.indexOf(stage);
  const list = $('worldStageList');
  list.innerHTML = '';
  WORLD_STAGE_ORDER.forEach((key, index) => {
    const [icon, label] = WORLD_STAGE_LABELS[key];
    const item = document.createElement('li');
    const done = run === 'completed' || (currentIndex >= 0 && index < currentIndex);
    const active = key === stage;
    item.className = run === 'error' && active ? 'error' : (done ? 'done' : (active ? 'active' : ''));
    const iconElement = document.createElement('i');
    iconElement.className = `bi ${done ? 'bi-check-circle-fill' : (run === 'error' && active ? 'bi-x-circle-fill' : icon)}`;
    const text = document.createElement('span');
    text.textContent = label;
    item.append(iconElement, text);
    list.appendChild(item);
  });
  const error = $('worldErrorText');
  error.hidden = !worldGeneration?.error;
  error.textContent = worldGeneration?.error || '';
  const quality = worldQuality();
  const qualityBadge = $('worldQualityBadge');
  qualityBadge.textContent = quality ? (quality.passed ? 'PASS' : 'CHECK') : '—';
  qualityBadge.className = `badge ${quality ? (quality.passed ? 'text-bg-success' : 'text-bg-warning') : 'text-bg-secondary'}`;
  const qualityText = $('worldQualityText');
  const failedChecks = Object.entries(quality?.checks || {}).filter(([, passed]) => !passed).map(([name]) => name);
  const qualityErrors = quality?.errors?.length ? quality.errors : failedChecks;
  const qualityMessages = qualityErrors.length ? qualityErrors : (quality?.warnings || []);
  qualityText.hidden = !qualityMessages.length;
  qualityText.textContent = qualityMessages.length
    ? `${qualityErrors.length ? '质量错误：' : '质量提示：'}${qualityMessages.slice(0, 3).join(' · ')}`
    : '';
  const artifactList = $('worldArtifactList');
  const artifactSignature = JSON.stringify([
    activeExperimentId,
    worldArtifacts.map(item => [item.kind, item.path, item.mime_type]),
  ]);
  if (artifactSignature !== worldArtifactRenderSignature) {
    worldArtifactRenderSignature = artifactSignature;
    artifactList.innerHTML = '';
    if (!worldArtifacts.length) {
      const empty = document.createElement('span');
      empty.className = 'text-secondary';
      empty.textContent = t('world.noArtifacts');
      artifactList.appendChild(empty);
    } else {
      worldArtifacts.slice().reverse().forEach(item => {
        const link = document.createElement('a');
        link.href = artifactUrl(item);
        link.target = '_blank';
        link.rel = 'noopener';
        const icon = document.createElement('i');
        icon.className = `bi ${item.mime_type === 'video/mp4' ? 'bi-film' : (item.mime_type === 'image/jpeg' || item.mime_type === 'image/png' ? 'bi-image' : 'bi-file-earmark-arrow-down')}`;
        const name = document.createElement('span');
        name.textContent = item.kind.replaceAll('_', ' ');
        const type = document.createElement('small');
        type.textContent = item.mime_type.split('/').pop();
        link.append(icon, name, type);
        artifactList.appendChild(link);
      });
    }
  }
  renderWorldVideoOptions();
  renderWorldBenchmarks();
}

async function restartCosmosServices() {
  const button = $('cosmosRestartBtn');
  if (button) button.disabled = true;
  try {
    await managerPost('/cosmos/restart', {});
    showToast(t('world.restartCosmos'), true);
    await pollWorldStatus();
  } catch (error) {
    showToast(`${t('toast.actionFail')}: ${error.message}`, false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function pollWorldStatus() {
  if (worldStatusBusy || (securityEnabled && !currentUser)) return;
  worldStatusBusy = true;
  try {
    const experimentId = activeExperimentId;
    const [services, artifacts] = await Promise.all([
      managerGet('/cosmos/status'),
      experimentId
        ? managerGet(`/artifacts?experiment_id=${encodeURIComponent(experimentId)}&compact=1`)
        : Promise.resolve(null),
    ]);
    cosmosServices = services || {};
    if (experimentId && artifacts && activeExperimentId === experimentId) {
      worldGeneration = artifacts.world_generation || {};
      worldArtifacts = artifacts.artifacts || [];
      worldPreviewStatus = artifacts.live_preview || {};
    }
    renderWorldPanel();
  } catch (_) {
    renderWorldPanel();
  } finally {
    worldStatusBusy = false;
  }
}

async function refreshAuthState() {
  authToken = localStorage.getItem(authStorageKey()) || '';
  try {
    const res = await fetchJson('/auth/me');
    securityEnabled = !!res.auth_required;
    currentUser = res.authenticated ? res.user : null;
    if (!currentUser && authToken) {
      authToken = '';
      localStorage.removeItem(authStorageKey());
    }
    updateAuthUi();
    return !securityEnabled || !!currentUser;
  } catch (_) {
    securityEnabled = false;
    currentUser = null;
    authToken = '';
    updateAuthUi();
    return true;
  }
}

function isAdminUser() {
  return currentUser && currentUser.role === 'admin';
}

function canOperate() {
  return !securityEnabled || (currentUser && ['admin', 'operator'].includes(currentUser.role));
}

function roleLabel(role) {
  return t(`security.role.${role || 'operator'}`);
}

function updateAuthUi() {
  const userBadge = $('currentUserBadge');
  const loginBtn = $('loginNavBtn');
  const logoutBtn = $('logoutBtn');
  if (userBadge) {
    userBadge.hidden = !currentUser;
    userBadge.textContent = currentUser ? `${currentUser.username} · ${roleLabel(currentUser.role)}` : '';
    userBadge.title = userBadge.textContent;
  }
  if (loginBtn) loginBtn.hidden = !!currentUser || !securityEnabled;
  if (logoutBtn) logoutBtn.hidden = !currentUser || !securityEnabled;
  document.querySelectorAll('[data-admin-only]').forEach(el => {
    el.hidden = !isAdminUser();
  });
  document.querySelectorAll('[data-user-management]').forEach(el => {
    el.hidden = !USER_MANAGEMENT_ENABLED || (el.hasAttribute('data-admin-only') && !isAdminUser());
  });
  ['uploadDataBtn', 'deleteSelectedDataBtn', 'pauseSelectedExperimentsBtn', 'terminateSelectedExperimentsBtn', 'deleteSelectedExperimentsBtn'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = !canOperate();
  });
  if (appMode === 'security' && !isAdminUser()) setAppMode(currentUser ? 'home' : 'login', false);
}

function handleAuthExpired(requestToken = authToken) {
  // A request started while logged out can finish after a new login. Its stale
  // 401 must not clear the newly issued session token.
  if (requestToken !== authToken) return false;
  if (!securityEnabled) return;
  authToken = '';
  currentUser = null;
  localStorage.removeItem(authStorageKey());
  updateAuthUi();
  setAppMode('login', false);
  return true;
}

async function login(username, password) {
  const r = await fetch(apiUrl('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || `HTTP ${r.status}`);
  authToken = j.token || '';
  currentUser = j.user || null;
  localStorage.setItem(authStorageKey(), authToken);
  securityEnabled = true;
  updateAuthUi();
  return j;
}

async function logout() {
  try { await apiPost('/auth/logout', {}); } catch (_) {}
  authToken = '';
  currentUser = null;
  localStorage.removeItem(authStorageKey());
  updateAuthUi();
  setAppMode('login', false);
}

async function apiGet(path) {
  const retryable = !!activeExperimentId;
  const attempts = retryable ? 10 : 1;
  let lastError = null;
  for (let i = 0; i < attempts; i += 1) {
    try {
      const requestToken = authToken;
      const r = await fetch(apiUrl(path), { cache: 'no-store', headers: authHeaders() });
      if (r.status === 401) {
        handleAuthExpired(requestToken);
        lastError = new Error(t('toast.loginRequired'));
        break;
      }
      if (r.ok) return r.json();
      lastError = new Error(`HTTP ${r.status}`);
      if (!retryable || ![404, 502, 503, 504].includes(r.status)) break;
    } catch (err) {
      lastError = err;
      if (!retryable) break;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw lastError || new Error('HTTP request failed');
}
async function apiPost(path, body = {}) {
  const retryable = !!activeExperimentId;
  const attempts = retryable ? 6 : 1;
  let lastError = null;
  for (let i = 0; i < attempts; i += 1) {
    try {
      const requestToken = authToken;
      const r = await fetch(apiUrl(path), {
        method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (r.status === 401) {
        handleAuthExpired(requestToken);
        lastError = new Error(j.error || t('toast.loginRequired'));
        break;
      }
      if (r.ok) return j;
      lastError = new Error(j.error || `HTTP ${r.status}`);
      if (!retryable || ![404, 502, 503, 504].includes(r.status)) break;
    } catch (err) {
      lastError = err;
      if (!retryable) break;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw lastError || new Error('HTTP request failed');
}
async function sendAction(payload) {
  try {
    const res = await apiPost('/action', payload);
    if (res && res.ok === false) throw new Error(res.error || 'unknown');
    return res;
  } catch (e) {
    showToast(`${t('toast.actionFail')}: ${e.message}`, false);
    throw e;
  }
}

function updateCarlaWindowVisibility() {
  const win = $('carlaWindow');
  if (!win) return;
  win.hidden = !(currentDetailMode() && carlaSessionRequested && activeExperimentId);
}

function carlaStateLabel(state) {
  const labels = {
    starting: t('carla.starting'),
    loading_map: t('carla.loadingMap'),
    recovering: t('carla.recovering'),
    running: t('carla.connected'),
    completed: t('status.completed'),
    stopped: t('carla.stopped'),
    error: t('carla.error'),
    not_started: t('carla.starting'),
  };
  return labels[state] || state || t('carla.starting');
}

function renderCarlaStatus(status) {
  const state = String(status?.state || 'starting');
  const badge = $('carlaStatusBadge');
  const overlay = $('carlaOverlay');
  const overlayText = $('carlaOverlayText');
  const classes = {
    running: 'text-bg-success',
    completed: 'text-bg-dark',
    starting: 'text-bg-info',
    loading_map: 'text-bg-info',
    recovering: 'text-bg-warning',
    error: 'text-bg-danger',
    stopped: 'text-bg-secondary',
  };
  badge.className = `badge ${classes[state] || 'text-bg-secondary'}`;
  badge.textContent = carlaStateLabel(state);
  const hasFrame = Number(status?.frame_number || 0) > 0;
  overlay.hidden = hasFrame && state !== 'error';
  if (overlayText) {
    overlayText.textContent = state === 'error'
      ? (status.last_error || status.error || status.message || t('carla.error'))
      : (status.message || carlaStateLabel(state));
  }
  const focused = String(status?.focused_vehicle_id || '');
  $('carlaViewMode').textContent = focused ? `${t('carla.following')} ${focused}` : t('carla.overview');
  const frameNumber = Number(status?.frame_number || 0);
  const now = performance.now();
  if (frameNumber > carlaLastFrameNumber && carlaLastFrameTime > 0) {
    const fps = (frameNumber - carlaLastFrameNumber) * 1000 / Math.max(1, now - carlaLastFrameTime);
    $('carlaFrameRate').textContent = `${fps.toFixed(1)} FPS`;
  }
  if (frameNumber !== carlaLastFrameNumber) {
    carlaLastFrameNumber = frameNumber;
    carlaLastFrameTime = now;
  }
}

async function pollCarlaStatus() {
  if (!carlaSessionRequested || !activeExperimentId || carlaStatusBusy || document.hidden) return;
  carlaStatusBusy = true;
  try {
    const response = await fetch(
      managerApiUrl(`/carla/status?experiment_id=${encodeURIComponent(activeExperimentId)}`),
      { cache: 'no-store', headers: authHeaders() },
    );
    const status = await response.json().catch(() => ({}));
    renderCarlaStatus(status);
  } catch (error) {
    renderCarlaStatus({ state: 'error', error: error.message });
  } finally {
    carlaStatusBusy = false;
  }
}

async function pollCarlaFrame() {
  if (!carlaSessionRequested || !activeExperimentId || carlaFrameBusy || document.hidden) return;
  carlaFrameBusy = true;
  try {
    const response = await fetch(
      managerApiUrl(`/carla/frame.jpg?experiment_id=${encodeURIComponent(activeExperimentId)}&t=${Date.now()}`),
      { cache: 'no-store', headers: authHeaders() },
    );
    if (!response.ok) return;
    const nextUrl = URL.createObjectURL(await response.blob());
    const image = $('carlaFrame');
    const previousUrl = carlaFrameUrl;
    carlaFrameUrl = nextUrl;
    image.onload = () => {
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      $('carlaOverlay').hidden = true;
    };
    image.src = nextUrl;
  } catch (_) {
    // The status endpoint carries the actionable startup or connection error.
  } finally {
    carlaFrameBusy = false;
  }
}

async function focusCarlaVehicle(vehicleId) {
  if (!carlaSessionRequested || !activeExperimentId) return;
  try {
    const response = await fetch(managerApiUrl('/carla/focus'), {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ experiment_id: activeExperimentId, vehicle_id: vehicleId || '' }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `HTTP ${response.status}`);
    }
  } catch (error) {
    showToast(`${t('toast.actionFail')}: ${error.message}`, false);
  }
}

// ── App modes ────────────────────────────────────────────────────────────────
function currentDetailMode() {
  return ['generate', 'replay', 'offline', 'experiment'].includes(appMode);
}

function isReplayLikeMode(mode = appMode) {
  return mode === 'replay' || mode === 'offline';
}

function isReplayLikeKind(kind) {
  return kind === 'replay' || kind === 'offline';
}

function markerStorageKey() {
  const markerScope = new URL(window.location.href).searchParams.get('marker_scope')
    || lastStatus?.marker_scope
    || lastStatus?.replay_params?.marker_scope;
  const scenario = $('scenarioSelect')?.value || new URL(window.location.href).searchParams.get('scenario') || '';
  const identity = markerScope || activeExperimentId || scenario || 'current';
  return `denseworld-drive.markers.${identity}`;
}

function currentMarkerScope() {
  const url = new URL(window.location.href);
  return url.searchParams.get('marker_scope')
    || lastStatus?.marker_scope
    || lastStatus?.replay_params?.marker_scope
    || activeExperimentId
    || url.searchParams.get('scenario')
    || '';
}

function mirrorExperimentMarkers() {
  localStorage.setItem(markerStorageKey(), JSON.stringify(experimentMarkers));
}

async function loadExperimentMarkers() {
  try {
    const value = JSON.parse(localStorage.getItem(markerStorageKey()) || '[]');
    experimentMarkers = Array.isArray(value) ? value : [];
  } catch (_) {
    experimentMarkers = [];
  }
  renderExperimentMarkers();
  const scope = currentMarkerScope();
  if (!scope || !window.location.protocol.startsWith('http')) return;
  try {
    const result = await managerGet(`/markers?scope=${encodeURIComponent(scope)}`);
    if (scope !== currentMarkerScope()) return;
    experimentMarkers = Array.isArray(result.markers) ? result.markers : [];
    mirrorExperimentMarkers();
    renderExperimentMarkers();
  } catch (_) {
    // The local mirror keeps markers usable when opening a standalone child UI.
  }
}

function renderExperimentMarkers() {
  const select = $('markerSelect');
  if (!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">暂无标记</option>';
  experimentMarkers.forEach(marker => {
    const option = document.createElement('option');
    option.value = marker.id;
    option.textContent = `${Number(marker.sim_time || 0).toFixed(1)} s · ${marker.label || '标记'}`;
    select.appendChild(option);
  });
  if (experimentMarkers.some(marker => marker.id === current)) select.value = current;
  const selected = !!select.value;
  if ($('jumpMarkerBtn')) $('jumpMarkerBtn').disabled = !selected;
  if ($('deleteMarkerBtn')) $('deleteMarkerBtn').disabled = !selected;
}

async function addExperimentMarker() {
  const step = isReplayLikeMode()
    ? replayCurrentStep
    : Number(simData?.step ?? lastStatus?.step ?? 0);
  const simTime = isReplayLikeMode()
    ? step * Number(replayStepSeconds || 0.1)
    : Number(simData?.sim_time ?? lastStatus?.sim_time ?? step * simStepSeconds);
  const label = window.prompt('标记名称', `标记 ${experimentMarkers.length + 1}`);
  if (label == null) return;
  const marker = {
    id: `marker-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    label: label.trim() || `标记 ${experimentMarkers.length + 1}`,
    step,
    sim_time: simTime,
    created_at: new Date().toISOString(),
  };
  experimentMarkers.push(marker);
  mirrorExperimentMarkers();
  renderExperimentMarkers();
  if ($('markerSelect')) $('markerSelect').value = marker.id;
  renderExperimentMarkers();
  const scope = currentMarkerScope();
  if (scope && window.location.protocol.startsWith('http')) {
    const result = await managerPost('/markers/action', { type: 'upsert', scope, marker });
    experimentMarkers = Array.isArray(result.markers) ? result.markers : experimentMarkers;
    mirrorExperimentMarkers();
    renderExperimentMarkers();
    if ($('markerSelect')) $('markerSelect').value = marker.id;
    renderExperimentMarkers();
  }
  showToast(`已标记 ${simTime.toFixed(1)} s`, true);
}

async function jumpToSelectedMarker() {
  const marker = experimentMarkers.find(item => item.id === $('markerSelect')?.value);
  if (!marker) return;
  if (!isReplayLikeMode() && appMode !== 'experiment') {
    showToast('标记跳转仅在实验查看或回放中可用', false);
    return;
  }
  if (runState === 'playback' || isReplayLikeMode()) {
    await replaySeek(Math.max(0, Number(marker.step || 0)));
    return;
  }
  showToast('当前实验仍在生成；结束后从实验管理进入回放即可跳转', false);
}

async function deleteSelectedMarker() {
  const id = $('markerSelect')?.value || '';
  if (!id) return;
  experimentMarkers = experimentMarkers.filter(marker => marker.id !== id);
  mirrorExperimentMarkers();
  renderExperimentMarkers();
  const scope = currentMarkerScope();
  if (scope && window.location.protocol.startsWith('http')) {
    const result = await managerPost('/markers/action', { type: 'delete', scope, marker_id: id });
    experimentMarkers = Array.isArray(result.markers) ? result.markers : experimentMarkers;
    mirrorExperimentMarkers();
    renderExperimentMarkers();
  }
}

function persistViewerPreference(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (_) {}
}

function readViewerPreference(key, fallback = '') {
  try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
}

function scheduleViewerResize() {
  if (viewerSplitRenderFrame) cancelAnimationFrame(viewerSplitRenderFrame);
  viewerSplitRenderFrame = requestAnimationFrame(() => {
    viewerSplitRenderFrame = 0;
    resizeTrafficCanvas();
    requestDrawFrame();
  });
}

function updateViewerSplitGeometry() {
  const workspace = $('workspace');
  const handle = $('viewerSplitHandle');
  if (!workspace || !handle) return;
  const desktop = workspace.clientWidth > 1200;
  handle.hidden = viewerLayoutMode !== 'equal' || !desktop || !currentDetailMode();
  if (!desktop) return;
  const leftInset = 12;
  const rightGutter = metricsPanelCollapsed ? 68 : 364;
  const availableWidth = Math.max(600, workspace.clientWidth - leftInset - rightGutter);
  const minimumPane = Math.min(290, Math.max(180, (availableWidth - 12) * 0.28));
  const minimumRatio = minimumPane / availableWidth;
  viewerSplitRatio = Math.max(minimumRatio, Math.min(1 - minimumRatio, Number(viewerSplitRatio) || (1 / 3)));
  const splitX = leftInset + availableWidth * viewerSplitRatio;
  workspace.style.setProperty('--viewer-split-x', `${splitX.toFixed(1)}px`);
  handle.setAttribute('aria-valuenow', String(Math.round(viewerSplitRatio * 100)));
}

function setPlatformSidebarCollapsed(collapsed, persist = true) {
  platformSidebarCollapsed = !!collapsed;
  const shell = document.querySelector('.app-shell');
  const button = $('platformSidebarToggle');
  shell?.classList.toggle('platform-sidebar-collapsed', platformSidebarCollapsed);
  if (button) {
    const label = platformSidebarCollapsed ? '展开左侧栏' : '收起左侧栏';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-expanded', String(!platformSidebarCollapsed));
    const icon = button.querySelector('i');
    if (icon) icon.className = `bi ${platformSidebarCollapsed ? 'bi-chevron-right' : 'bi-chevron-left'}`;
  }
  document.querySelectorAll('.module-nav-btn').forEach(item => {
    const label = item.querySelector('span')?.textContent?.trim() || '';
    if (platformSidebarCollapsed && label) item.title = label;
    else item.removeAttribute('title');
  });
  if (persist) persistViewerPreference(PLATFORM_SIDEBAR_STORAGE_KEY, platformSidebarCollapsed ? '1' : '0');
  window.setTimeout(() => { updateViewerSplitGeometry(); scheduleViewerResize(); }, 80);
}

function setMetricsPanelCollapsed(collapsed, persist = true) {
  metricsPanelCollapsed = !!collapsed;
  const workspace = $('workspace');
  const panel = $('metricsWindow');
  const button = $('metricsCollapseBtn');
  workspace?.classList.toggle('metrics-panel-collapsed', metricsPanelCollapsed);
  panel?.classList.toggle('side-collapsed', metricsPanelCollapsed);
  if (button) {
    const label = metricsPanelCollapsed ? '展开指标栏' : '收起指标栏';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-expanded', String(!metricsPanelCollapsed));
    const icon = button.querySelector('i');
    if (icon) icon.className = `bi ${metricsPanelCollapsed ? 'bi-chevron-left' : 'bi-chevron-right'}`;
  }
  if (persist) persistViewerPreference(METRICS_PANEL_STORAGE_KEY, metricsPanelCollapsed ? '1' : '0');
  updateViewerSplitGeometry();
  scheduleViewerResize();
}

function setViewerSplitRatio(ratio, persist = false) {
  viewerSplitRatio = Number(ratio) || (1 / 3);
  updateViewerSplitGeometry();
  scheduleViewerResize();
  if (persist) persistViewerPreference(VIEWER_SPLIT_STORAGE_KEY, viewerSplitRatio.toFixed(4));
}

function initViewerPanels() {
  const storedRatio = Number(readViewerPreference(VIEWER_SPLIT_STORAGE_KEY, String(1 / 3)));
  viewerSplitRatio = Number.isFinite(storedRatio) ? storedRatio : (1 / 3);
  setPlatformSidebarCollapsed(readViewerPreference(PLATFORM_SIDEBAR_STORAGE_KEY, '0') === '1', false);
  setMetricsPanelCollapsed(readViewerPreference(METRICS_PANEL_STORAGE_KEY, '0') === '1', false);

  $('platformSidebarToggle')?.addEventListener('click', () => setPlatformSidebarCollapsed(!platformSidebarCollapsed));
  $('metricsCollapseBtn')?.addEventListener('click', () => setMetricsPanelCollapsed(!metricsPanelCollapsed));

  const handle = $('viewerSplitHandle');
  if (handle) {
    let dragging = false;
    const updateFromPointer = clientX => {
      const workspace = $('workspace');
      if (!workspace) return;
      const rect = workspace.getBoundingClientRect();
      const rightGutter = metricsPanelCollapsed ? 68 : 364;
      const availableWidth = Math.max(600, rect.width - 12 - rightGutter);
      setViewerSplitRatio((clientX - rect.left - 12) / availableWidth);
    };
    handle.addEventListener('pointerdown', event => {
      if (viewerLayoutMode !== 'equal') return;
      dragging = true;
      handle.classList.add('dragging');
      handle.setPointerCapture(event.pointerId);
      updateFromPointer(event.clientX);
    });
    handle.addEventListener('pointermove', event => {
      if (dragging) updateFromPointer(event.clientX);
    });
    const finishDrag = event => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      persistViewerPreference(VIEWER_SPLIT_STORAGE_KEY, viewerSplitRatio.toFixed(4));
    };
    handle.addEventListener('pointerup', finishDrag);
    handle.addEventListener('pointercancel', finishDrag);
    handle.addEventListener('dblclick', () => setViewerSplitRatio(1 / 3, true));
    handle.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home') setViewerSplitRatio(0.2, true);
      else if (event.key === 'End') setViewerSplitRatio(0.8, true);
      else setViewerSplitRatio(viewerSplitRatio + (event.key === 'ArrowRight' ? 0.02 : -0.02), true);
    });
  }
  window.addEventListener('resize', () => {
    updateViewerSplitGeometry();
    scheduleViewerResize();
  });
}

function applyViewerLayout(mode) {
  viewerLayoutMode = ['traffic-main', 'equal', 'video-main'].includes(mode) ? mode : 'traffic-main';
  const workspace = $('workspace');
  if (!workspace) return;
  ['settingsWindow', 'trafficWindow', 'multimodalWindow', 'metricsWindow'].forEach(id => {
    const win = $(id);
    if (!win) return;
    ['top', 'right', 'bottom', 'left', 'width', 'height', 'z-index'].forEach(property => {
      win.style.removeProperty(property);
    });
  });
  workspace.classList.remove('viewer-layout-traffic-main', 'viewer-layout-equal', 'viewer-layout-video-main');
  workspace.classList.add(`viewer-layout-${viewerLayoutMode}`);
  if ($('viewerLayoutSelect')) $('viewerLayoutSelect').value = viewerLayoutMode;
  updateViewerSplitGeometry();
  window.setTimeout(() => {
    updateViewerSplitGeometry();
    scheduleViewerResize();
  }, 80);
}

function configureViewerWorkspace() {
  const videoHost = $('multimodalVideoHost');
  const multimodalPane = $('pane-multimodal');
  const multimodalBlocks = multimodalPane ? Array.from(multimodalPane.querySelectorAll(':scope > .control-block')) : [];
  const pipelineBlock = multimodalBlocks[0];
  const videoBlock = multimodalBlocks[1];
  const qualityBlock = multimodalBlocks[2];
  if (videoHost && videoBlock) videoHost.appendChild(videoBlock);
  const controlHost = $('viewerControlHost');
  if (controlHost) {
    if ($('displayControlBlock')) controlHost.appendChild($('displayControlBlock'));
    if ($('replayBlock')) controlHost.appendChild($('replayBlock'));
    if (pipelineBlock) controlHost.appendChild(pipelineBlock);
  }
  if (qualityBlock) qualityBlock.hidden = true;
  if (multimodalPane) multimodalPane.hidden = true;
  const actionHost = $('viewerExperimentActions');
  ['startExperimentBtn', 'pauseResumeBtn', 'terminateBtn', 'startPlaybackBtn', 'startOfflineTestBtn'].forEach(id => {
    const button = $(id);
    if (actionHost && button) actionHost.appendChild(button);
  });
}

function activeEgoId() {
  const explicit = lastStatus?.av_id || lastStatus?.replay_ego_id || lastStatus?.offline_av_id
    || lastStatus?.world_ego_id || lastStatus?.ego_id;
  if (explicit != null && String(explicit)) return String(explicit);
  const ego = (simData?.vehicles || []).find(vehicle => {
    const type = String(vehicle.type || vehicle.role || '').toLowerCase();
    return type === 'av' || type === 'ego' || vehicle.is_av || vehicle.is_ego;
  });
  return ego ? String(ego.id) : '';
}

function followEgoVehicle() {
  const egoId = activeEgoId();
  if (!egoId) {
    showToast('当前状态中没有可跟随的主车', false);
    return;
  }
  selectedVehicleId = egoId;
  followSelectedVehicle = true;
  if ($('followVehicleToggle')) $('followVehicleToggle').checked = true;
  focusSelectedVehicle();
  updateSelectedVehiclePanel();
  requestDrawFrame();
}

function openExperimentConfig() {
  const source = lastStatus || {};
  const rows = [
    ['实验 ID', activeExperimentId || source.experiment_id || '-'],
    ['实验名称', source.experiment_name || '-'],
    ['交通模型', source.backend_model || source.traffic_model || '-'],
    ['地图', source.map_path || '-'],
    ['初始化', source.init_mode || '-'],
    ['仿真步长', `${Number(source.sim_resolution || simStepSeconds || 0.1).toFixed(3)} s`],
    ['目标时长', source.run_until_stopped ? '运行至手动停止' : `${Number(source.max_sim_time || source.total_step * (source.sim_resolution || 0.1) || 0).toFixed(1)} s`],
    ['AV 控制', source.av_control_model || (source.av_enabled ? '已接入' : '未接入')],
    ['OmniDreams', worldGeneration?.payload?.runtime_profile || cosmosServices?.omnidreams?.profile || '未启用'],
    ['视频进度', `${Number(worldGeneration?.payload?.omnidreams_progress?.generated_video_time || 0).toFixed(1)} s`],
  ];
  const body = $('experimentConfigBody');
  if (body) body.innerHTML = rows.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd></div>`).join('');
  bootstrap.Modal.getOrCreateInstance($('experimentConfigModal')).show();
}

const APP_MODE_TITLES = {
  home: '运营控制台',
  tasks: '测试任务管理',
  workflow: '测试流程编排',
  experiments: '实验管理',
  data: '数据管理',
  generate: '场景生成',
  replay: '场景回放',
  offline: '离线测试',
  experiment: '实验查看',
  login: '平台登录',
};
const MANAGER_NAV_MODES = new Set(['home', 'tasks', 'workflow', 'experiments', 'data']);

function setAppMode(mode, push = true) {
  const requestedMode = mode || 'home';
  if (push && activeExperimentId && managerBase && MANAGER_NAV_MODES.has(requestedMode)) {
    window.location.assign(managerViewUrl(requestedMode));
    return;
  }
  appMode = requestedMode;
  if (securityEnabled && !currentUser && appMode !== 'login') appMode = 'login';
  if (appMode === 'security' && (!USER_MANAGEMENT_ENABLED || !isAdminUser())) {
    appMode = currentUser ? 'home' : 'login';
  }
  document.documentElement.dataset.initialView = appMode;
  ['homeView', 'tasksView', 'workflowView', 'experimentsView', 'dataView', 'securityView', 'loginView'].forEach(id => {
    const el = $(id);
    if (el) el.hidden = id !== `${appMode}View`;
  });
  if ($('currentSectionTitle')) $('currentSectionTitle').textContent = APP_MODE_TITLES[appMode] || 'DenseWorld-Drive';

  const detail = currentDetailMode();
  document.querySelectorAll('.window-card').forEach(el => {
    if (el.classList.contains('modal')) return;
    el.hidden = el.id === 'carlaWindow' || !detail;
  });
  if ($('settingsWindow')) $('settingsWindow').hidden = true;
  const showExperimentActions = appMode === 'experiment';
  const showReplayActions = appMode === 'replay';
  const showOfflineActions = appMode === 'offline';
  const showGenerateActions = appMode === 'generate';
  $('replayBlock').hidden = !(showReplayActions || showOfflineActions);
  $('startPlaybackBtn').hidden = !showReplayActions;
  $('startOfflineTestBtn').hidden = !showOfflineActions;
  $('startExperimentBtn').hidden = !showGenerateActions;
  if ($('carla3dConfig')) $('carla3dConfig').hidden = true;
  $('pauseResumeBtn').hidden = !(showExperimentActions || showReplayActions || showOfflineActions);
  $('terminateBtn').hidden = !(showExperimentActions || showReplayActions || showOfflineActions);
  $('dataManagerBtn').hidden = true;
  ['resetWindowsBtn', 'lockWindowsBtn', 'maximizeTrafficBtn'].forEach(id => {
    const el = $(id);
    if (el) el.hidden = true;
  });

  document.querySelectorAll('.module-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.appMode === appMode);
    btn.hidden = ['generate', 'replay', 'offline'].includes(btn.dataset.appMode)
      || (!USER_MANAGEMENT_ENABLED && btn.dataset.appMode === 'security')
      || (isManagedChildSession() && appMode === 'replay' && btn.dataset.appMode === 'replay');
  });
  if (push) {
    const url = new URL(window.location.href);
    url.searchParams.set('view', appMode);
    window.history.replaceState({}, '', url);
  }
  if (appMode === 'data') loadDataRecords();
  if (appMode === 'experiments') loadExperiments();
  if (appMode === 'home') loadDashboard();
  if (appMode === 'workflow') {
    loadWorkflows();
    loadStandardScenarios();
  }
  if (USER_MANAGEMENT_ENABLED && appMode === 'security' && isAdminUser()) loadSecurityAdmin();
  if (isReplayLikeMode() && $('trafficModelSelect') && !$('scenarioSelect')?.value) $('trafficModelSelect').value = '';
  if (isReplayLikeMode()) loadScenarios();
  updateTrafficModelControls();
  updateButtonStates(lastStatus || {});
  updateActiveExperimentBadge(lastStatus || {});
  updateCarlaWindowVisibility();
  if (detail) {
    loadExperimentMarkers();
    applyViewerLayout($('viewerLayoutSelect')?.value || viewerLayoutMode);
    setTimeout(() => {
      resizeTrafficCanvas();
      requestDrawFrame();
    }, 50);
  }
}

function initAppModeFromUrl() {
  const url = new URL(window.location.href);
  const view = url.searchParams.get('view') || 'home';
  const allowed = new Set(['home', 'tasks', 'workflow', 'experiments', 'data', 'generate', 'replay', 'offline', 'experiment', 'login']);
  if (USER_MANAGEMENT_ENABLED) allowed.add('security');
  if (activeExperimentId && managerBase && (MANAGER_NAV_MODES.has(view) || view === 'generate')) {
    activeExperimentId = '';
    backendBase = managerBase;
    url.searchParams.delete('experiment_id');
    url.searchParams.delete('marker_scope');
    url.searchParams.delete('carla');
    window.history.replaceState({}, '', url);
    if ($('backendTarget')) $('backendTarget').textContent = backendBase;
  }
  setAppMode(allowed.has(view) ? view : 'home', false);
  const scenario = url.searchParams.get('scenario');
  if (scenario) ensureScenarioOption(scenario);
}

async function restoreManagedReplayIfNeeded() {
  if (!activeExperimentId || !managerBase || !isReplayLikeMode()) return false;
  let record = null;
  try {
    const response = await managerGet(`/experiments?experiment_id=${encodeURIComponent(activeExperimentId)}`);
    record = response.experiment || null;
  } catch (_) {
    record = null;
  }
  if (record?.child_available) return false;

  const currentUrl = new URL(window.location.href);
  const replayParams = record?.replay_params || {};
  const scenario = currentUrl.searchParams.get('scenario')
    || record?.scenario
    || replayParams.scenario_path
    || replayParams.scenario
    || '';
  if (!scenario) return false;

  const offline = appMode === 'offline' || !!record?.offline_test || !!replayParams.offline_test;
  const payload = {
    type: offline ? 'start_offline_test' : 'start_playback',
    scenario,
    backend_model: record?.backend_model || replayParams.backend_model || undefined,
    map_path: record?.map_path || replayParams.map_path || undefined,
    gpu_id: String(record?.gpu_id ?? replayParams.gpu_id ?? $('gpuIdInput')?.value ?? '4'),
    offline_av_id: offline ? String(record?.offline_av_id || replayParams.offline_av_id || '') : undefined,
    av_enabled: offline ? !!(record?.av_enabled || replayParams.av_enabled) : undefined,
    av_control_model: offline ? (record?.av_control_model || replayParams.av_control_model || undefined) : undefined,
    marker_scope: currentUrl.searchParams.get('marker_scope') || record?.marker_scope || replayParams.marker_scope || record?.id || undefined,
  };
  const result = await managerPost('/action', payload);
  const nextRecord = result?.experiment;
  const nextId = String(nextRecord?.id || '');
  if (!result?.ok || !nextId) throw new Error(result?.error || 'Replay recovery failed');

  activeExperimentId = nextId;
  backendBase = `${managerBase}/proxy/${encodeURIComponent(nextId)}`;
  $('backendTarget').textContent = backendBase;
  currentUrl.searchParams.set('experiment_id', nextId);
  currentUrl.searchParams.set('scenario', scenario);
  if (nextRecord.marker_scope) currentUrl.searchParams.set('marker_scope', nextRecord.marker_scope);
  window.history.replaceState({}, '', currentUrl);
  replayAutoplayPending = !offline;
  return true;
}

function isManagerBackend() {
  return !!lastStatus.manager_mode;
}

// ── Connection badge ──────────────────────────────────────────────────────────
function setConnected(ok) {
  if (ok === connected) return;
  connected = ok;
  const badge = $('connectionBadge');
  if (ok) {
    badge.className = 'badge text-bg-success'; badge.textContent = t('status.connected');
    if (!hasShownConnectedToast) {
      showToast(t('toast.connected'), true);
      hasShownConnectedToast = true;
    }
  } else {
    badge.className = 'badge text-bg-secondary'; badge.textContent = t('status.disconnected');
  }
}

// ── Run state badge ───────────────────────────────────────────────────────────
function updateRunStateBadge(state) {
  const badge = $('runStateBadge');
  const map = {
    idle: ['text-bg-secondary', t('status.idle')],
    running: ['text-bg-success', t('status.running')],
    paused: ['text-bg-warning', t('status.paused')],
    playback: ['text-bg-primary', t('status.playback')],
    playback_loading: ['text-bg-info', t('status.playbackLoading')],
    video_finalizing: ['text-bg-info', t('status.videoFinalizing')],
    completed: ['text-bg-dark', t('status.completed')],
  };
  const [cls, label] = map[state] || ['text-bg-dark', state];
  badge.className = `badge ${cls} ms-1`; badge.textContent = label;
  $('runStateText').textContent = label;
}

function basenameFromPath(value) {
  const text = String(value || '').split(/[?#]/)[0].replace(/\\/g, '/');
  const base = text.split('/').filter(Boolean).pop() || text;
  return base.replace(/\.pkl$/i, '');
}

function activeExperimentNameFromStatus(status = {}) {
  if (!currentDetailMode()) return '';
  if (status.experiment_name) return String(status.experiment_name);
  const params = status.replay_params || {};
  if (params.experiment_name) return String(params.experiment_name);
  const path = params.scenario_path || params.scenario || status.scenario || status.save_file || '';
  return basenameFromPath(path);
}

function updateActiveExperimentBadge(status = {}) {
  const el = $('activeExperimentName');
  if (!el) return;
  const name = activeExperimentNameFromStatus(status);
  if (!name) {
    el.hidden = true;
    el.textContent = '';
    el.removeAttribute('title');
    return;
  }
  const label = `${t('status.activeExperiment')}: ${name}`;
  el.hidden = false;
  el.textContent = label;
  el.title = label;
  const input = $('experimentNameStartInput');
  if (input && (appMode === 'experiment' || isReplayLikeMode()) && document.activeElement !== input) {
    input.value = name;
  }
}

// ── Map lock ──────────────────────────────────────────────────────────────────
function setMapLocked(locked) {
  mapLocked = locked;
  const replayMode = isReplayLikeMode();
  const replayLocked = isReplayParamLocked();
  const replayScenarioSelected = replayMode && !!$('scenarioSelect')?.value;
  const completedLocked = lastStatus?.run_state === 'completed' || !!lastStatus?.experiment_completed;
  const runLocked = locked || replayLocked || replayScenarioSelected || workflowScenarioConfigurationLocked;
  $('mapSelect').disabled = runLocked;
  $('initModeSelect').disabled = runLocked;
  $('initDataSelect').disabled = runLocked;
  ['experimentNameStartInput', 'gpuIdInput', 'totalStepInput', 'scenarioCountInput', 'runUntilStoppedToggle'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = runLocked;
  });
  updateRunDurationControls();
  if ($('laneIdInput')) $('laneIdInput').disabled = !replayMode && (replayLocked || completedLocked);
  if ($('arrivalRateInput')) $('arrivalRateInput').disabled = replayMode || replayLocked || completedLocked;
  if ($('applyArrivalRateBtn')) $('applyArrivalRateBtn').disabled = replayMode || replayLocked || completedLocked;
  updateAvAccessControls();
  $('mapLockHint').hidden = replayMode || runLocked;
}

function isReplayParamLocked(status = lastStatus) {
  const state = status?.run_state || runState || 'idle';
  return isReplayLikeMode() && (state === 'playback' || state === 'playback_loading');
}

function ensureSelectOption(selectId, value, label = null) {
  const sel = $(selectId);
  if (!sel || !value) return;
  const exists = Array.from(sel.options).some(opt => opt.value === value);
  if (!exists) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label || String(value).split('/').pop();
    sel.appendChild(opt);
  }
  sel.value = value;
}

function updateInitModeOptions(backendModel, preferredValue = null) {
  const sel = $('initModeSelect');
  if (!sel) return;
  const options = INIT_MODE_OPTIONS[backendModel] || INIT_MODE_OPTIONS.cnde;
  const current = preferredValue || sel.value;
  sel.innerHTML = '';
  options.forEach(([value, labelKey]) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.dataset.i18n = labelKey;
    opt.textContent = t(labelKey);
    sel.appendChild(opt);
  });
  if (options.some(([value]) => value === current)) sel.value = current;
  else if (options.length) sel.value = options[0][0];
}

function applyReplayParams(params) {
  if (!params || typeof params !== 'object') return;
  if (params.map_path) {
    ensureSelectOption('mapSelect', params.map_path);
    if (params.map_path !== activeReplayMapPath) {
      activeReplayMapPath = params.map_path;
      mapData = null;
      invalidateStaticMapLayer();
      pollMapState(true).catch(() => {});
    }
  }
  if (params.backend_model || params.model) updateInitModeOptions(params.backend_model || params.model, params.init_mode);
  else if (params.init_mode) ensureSelectOption('initModeSelect', params.init_mode, params.init_mode);
  if (params.init_file) ensureSelectOption('initDataSelect', params.init_file);
  const scenario = params.scenario_path || params.scenario || '';
  if (scenario) ensureScenarioOption(scenario);
  if (params.experiment_name && $('experimentNameStartInput')) $('experimentNameStartInput').value = params.experiment_name;
  if (params.gpu_id != null && $('gpuIdInput')) $('gpuIdInput').value = String(params.gpu_id);
  const totalSteps = params.total_step ?? params.total_steps ?? params.total_steps_saved;
  const secondsPerStep = Number(params.sim_resolution || simStepSeconds || 0.1);
  if (totalSteps != null && $('totalStepInput')) $('totalStepInput').value = String(Math.max(1, Math.round(Number(totalSteps) * secondsPerStep)));
  if (params.arrival_rate != null && $('arrivalRateInput')) $('arrivalRateInput').value = Number(params.arrival_rate).toFixed(3);
  updateInitModeControls();
}

// ── Button states ─────────────────────────────────────────────────────────────
function updateButtonStates(status) {
  const state = status.run_state || 'idle';
  const paused = !!status.paused;
  const replayLoading = state === 'playback_loading' || !!status.replay_loading;
  const completed = state === 'completed' || !!status.experiment_completed;
  const writable = canOperate();
  const managerScopedStart = appMode === 'generate' && !!managerBase;
  $('startExperimentBtn').disabled = (!managerScopedStart && state !== 'idle') || !writable;
  $('startPlaybackBtn').disabled = state !== 'idle' || !writable;
  if ($('startOfflineTestBtn')) $('startOfflineTestBtn').disabled = state !== 'idle' || !writable;
  $('terminateBtn').disabled = state === 'idle' || completed || !writable;
  $('scenarioSelect').disabled = state !== 'idle';
  if ($('scenarioSearchInput')) $('scenarioSearchInput').disabled = isReplayLikeMode() && state !== 'idle';
  if ($('trafficModelSelect')) $('trafficModelSelect').disabled = isReplayParamLocked(status);
  $('refreshScenariosBtn').disabled = state !== 'idle';
  const pauseBtn = $('pauseResumeBtn');
  const pauseLabel = $('pauseResumeLabel');
  const pauseIcon = pauseBtn.querySelector('i');
  if (state === 'idle' || replayLoading || completed) {
    pauseBtn.disabled = true;
    pauseLabel.textContent = t('actions.pause');
    pauseIcon.className = 'bi bi-pause-circle me-1';
  } else if (paused) {
    pauseBtn.disabled = !writable;
    pauseLabel.textContent = t('actions.resume');
    pauseIcon.className = 'bi bi-play-circle me-1';
  } else {
    pauseBtn.disabled = !writable;
    pauseLabel.textContent = t('actions.pause');
    pauseIcon.className = 'bi bi-pause-circle me-1';
  }
  if (isReplayLikeMode() && status.replay_params) applyReplayParams(status.replay_params);
  setMapLocked(state !== 'idle' || completed);
  const overlayText = $('waitingOverlayText');
  const showEnded = completed && experimentPresentationComplete(status) && appMode === 'experiment';
  $('waitingOverlay').hidden = !(status.waiting_for_start || showEnded);
  if (overlayText) overlayText.textContent = showEnded ? t('status.experimentEnded') : t('status.waitingForStart');
  // Show timeline bar only during playback
  $('timelineBar').hidden = state !== 'playback';
  ['replayPrevBtn', 'replayPlayBtn', 'replayNextBtn', 'tlPrevBtn', 'tlPlayBtn', 'tlNextBtn', 'replaySlider'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = state !== 'playback';
  });
  updateCarlaConfigControls();
  updateDenseWorldControls();
  updateMixedTrafficControls();
}

// ── Status polling ────────────────────────────────────────────────────────────
async function pollStatus() {
  if (statusPollBusy) return;
  statusPollBusy = true;
  try {
    const status = await apiGet('/status');
    setConnected(true);
    lastStatus = status;
    runState = status.run_state || 'idle';
    if (appMode === 'offline' && status.offline_av_id && !offlineAvId) {
      offlineAvId = String(status.offline_av_id);
      selectedVehicleId = offlineAvId;
      if (simData) simData = applyOfflineAvToSimState(simData);
    }
    const statusEgoId = status.av_id || status.replay_ego_id || status.offline_av_id;
    if (statusEgoId && (appMode === 'experiment' || appMode === 'replay') && !selectedVehicleId) {
      selectedVehicleId = String(statusEgoId);
    }
    renderOnlineAvState(status);
    if (runState === 'playback' && replayPlaying) {
      status.paused = false;
      lastStatus.paused = false;
    }
    const presentationComplete = experimentPresentationComplete(status);
    updateRunStateBadge(runState === 'completed' && !presentationComplete ? 'video_finalizing' : runState);
    updateActiveExperimentBadge(status);
    applyMetricCapabilities(currentAlgorithmCapability());
    updateButtonStates(status);

    simStepSeconds = Number(status.sim_resolution || simStepSeconds || 0.1);
    $('statProgress').textContent = formatProgress(status);
    $('statSimTime').textContent = formatSimTime(status);
    const vehicleCount = Number(status.vehicles);
    const hasVehicles = Number.isFinite(vehicleCount) && vehicleCount > 0;
    const hasPairs = Number.isFinite(vehicleCount) && vehicleCount > 1;
    $('statVehicles').textContent = status.motorized_count ?? status.vehicles ?? '—';
    if ($('statCyclists')) $('statCyclists').textContent = status.cyclist_count ?? '0';
    if ($('statPedestrians')) $('statPedestrians').textContent = status.pedestrian_count ?? '0';
    $('statArrivalRate').textContent = status.arrival_rate != null ? status.arrival_rate.toFixed(3) : '—';
    $('statViolationRate').textContent = status.violation_rate != null ? status.violation_rate.toFixed(3) : '—';
    $('statAvgSpeed').textContent = hasVehicles && status.avg_speed != null ? status.avg_speed.toFixed(2) + ' m/s' : '—';
    const ttcVal = status.av_min_ttc ?? (hasPairs ? status.avg_ttc : null);
    if (runState === 'playback' && replayPlaying) {
      status.paused = false;
    }
    const paused = !!status.paused;
    $('statMinTTC').textContent = ttcVal != null ? ttcVal.toFixed(1) + ' s' : '—';
    // Risk: inverse of TTC capped at 1
    const risk = ttcVal != null ? Math.min(1, 3 / (ttcVal + 0.1)) : null;
    $('statRisk').textContent = risk != null ? risk.toFixed(2) : '—';
    const trafficTime = Number(simData?.sim_time ?? status.sim_time);
    const videoTime = Number(simData?.world_video_time ?? status.world_video_time);
    if ($('statVideoTime')) $('statVideoTime').textContent = Number.isFinite(videoTime) ? `${videoTime.toFixed(2)} s` : '—';
    if ($('statSyncDelta')) $('statSyncDelta').textContent = Number.isFinite(videoTime) && Number.isFinite(trafficTime)
      ? `${(videoTime - trafficTime).toFixed(2)} s`
      : '—';
    if ($('statEgoState')) $('statEgoState').textContent = statusEgoId ? `#${statusEgoId}` : '—';
    updateLiveTelemetry(simData);

    if (status.replay_total_steps != null) {
      replayTotalSteps = status.replay_total_steps;
      if (!(runState === 'playback' && (replayPlaying || replaySeekBusy || replaySliderDragging))) {
        replayCurrentStep = status.replay_step ?? 0;
      }
      replayStepSeconds = Number(status.replay_step_seconds || status.sim_resolution || replayStepSeconds || 0.1);
      updateReplaySlider();
    }
    if (replayAutoplayPending && runState === 'playback' && replayTotalSteps > 0 && !replayPlaying) {
      replayAutoplayPending = false;
      if (lastStatus) lastStatus.paused = false;
      startReplayAutoPlay();
    }
    if (runState !== 'playback_loading') upsertMetricSample(status);
    const metricsPollMs = runState === 'playback' && replayPlaying ? PLAYBACK_METRICS_POLL_MS : METRICS_POLL_MS;
    if (performance.now() - lastMetricsFetchAt > metricsPollMs) loadReplayMetrics();
    scheduleChartUpdate(runState === 'playback' && replayPlaying ? PLAYBACK_CHART_UPDATE_MS : 1500);
    if (!mapData && !isManagerBackend()) pollMapState(true).catch(() => {});
    if (appMode === 'experiments') {
      if (!shouldHoldExperimentRender()) {
        if (isManagerBackend() && performance.now() - lastExperimentsLoadAt > EXPERIMENTS_POLL_MS) await loadExperiments();
        else renderExperimentRecords();
      }
    }
    const experimentId = String(status.experiment_id || activeExperimentId || '');
    if (
      appMode === 'experiment'
      && experimentId
      && ['completed', 'error'].includes(runState)
      && experimentPresentationComplete(status)
      && !completionPromptedExperimentIds.has(experimentId)
    ) {
      completionPromptedExperimentIds.add(experimentId);
      openExperimentCompletionReview(status).catch(error => {
        showToast(`实验结束处理失败：${error.message}`, false);
      });
    }
  } catch (_) {
    setConnected(false);
  } finally {
    statusPollBusy = false;
  }
}

// ── Frame polling ─────────────────────────────────────────────────────────────
async function pollFrame() {
  if (!currentDetailMode()) return;
  if (mapData) return;
  if (framePollBusy) return;
  framePollBusy = true;
  try {
    const r = await fetch(apiUrl(`/frame.jpg?t=${Date.now()}`), { cache: 'no-store', headers: authHeaders() });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const blobUrl = URL.createObjectURL(blob);
    await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => { frameImg = img; frameLoaded = true; requestDrawFrame(); URL.revokeObjectURL(blobUrl); resolve(); };
      img.onerror = err => { URL.revokeObjectURL(blobUrl); reject(err); };
      img.src = blobUrl;
    });
  } catch (_) {} finally { framePollBusy = false; }
}

async function pollMapState(force = false) {
  if (mapStateBusy || (mapData && !force)) return;
  mapStateBusy = true;
  try {
    const res = await apiGet('/map_state');
    if (res.ok) {
      const firstVectorMap = !mapData || force;
      mapData = res;
      rebuildMapIndexes();
      invalidateStaticMapLayer();
      await loadMapRaster(res);
      updateLaneOptions();
      frameLoaded = true;
      if (firstVectorMap) {
        vectorFitDone = true;
        fitFrame();
      }
      requestDrawFrame();
    }
  } catch (_) {
  } finally {
    mapStateBusy = false;
  }
}

async function loadMapRaster(nextMapData) {
  const rasterUrl = String(nextMapData?.raster_url || '').trim();
  if (!rasterUrl) {
    mapRasterImg = new Image();
    mapRasterLoaded = false;
    mapRasterSource = '';
    return;
  }
  const normalizedPath = rasterUrl.startsWith('/') ? rasterUrl : `/${rasterUrl}`;
  const source = apiUrl(normalizedPath);
  if (mapRasterLoaded && mapRasterSource === source) return;
  mapRasterLoaded = false;
  mapRasterSource = source;
  try {
    const response = await fetch(source, { cache: 'no-store', headers: authHeaders() });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blobUrl = URL.createObjectURL(await response.blob());
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = blobUrl;
    });
    URL.revokeObjectURL(blobUrl);
    if (mapRasterSource !== source) return;
    mapRasterImg = image;
    mapRasterLoaded = true;
    invalidateStaticMapLayer();
  } catch (_) {
    mapRasterLoaded = false;
  }
}

function updateLaneOptions() {
  const list = $('laneIdOptions');
  if (!list) return;
  list.innerHTML = '<option value="all"></option>';
  (mapData?.start_lanes || []).forEach(id => {
    const opt = document.createElement('option');
    opt.value = String(id);
    list.appendChild(opt);
  });
}

function updateVehicleIdOptions(vehicles = simData?.vehicles || []) {
  const list = $('vehicleIdOptions');
  if (!list) return;
  const ids = vehicles.map(v => String(v.id));
  const signature = ids.join('|');
  if (signature === vehicleIdOptionsSignature) return;
  vehicleIdOptionsSignature = signature;
  list.innerHTML = '';
  ids.forEach(id => {
    const opt = document.createElement('option');
    opt.value = id;
    list.appendChild(opt);
  });
}

function invalidateStaticMapLayer() {
  staticMapLayerSignature = '';
}

function rebuildMapIndexes() {
  mapRenderVersion += 1;
  mapPolylineById = new Map();
  mapType4Polylines = [];
  trafficLightPolylines = [];
  trafficLightPolylineSignature = '';
  (mapData?.polylines || []).forEach(p => {
    const ids = [p.id, p.raw_id, String(p.id), String(p.raw_id)].filter(v => v != null);
    ids.forEach(id => mapPolylineById.set(String(id), p));
    if (Number(p.type) === 4) mapType4Polylines.push(p);
  });
}

function updateTrafficLightPolylineCache() {
  const tlKeys = simData?.traffic_lights ? Object.keys(simData.traffic_lights).sort() : [];
  const signature = `${mapRenderVersion}|${tlKeys.join('|')}`;
  if (signature === trafficLightPolylineSignature) return;

  const next = [];
  const seen = new Set();
  mapType4Polylines.forEach(p => {
    const key = String(p.id ?? p.raw_id);
    if (seen.has(key)) return;
    seen.add(key);
    next.push(p);
  });
  tlKeys.forEach(key => {
    const p = mapPolylineById.get(String(key));
    if (!p) return;
    const polyKey = String(p.id ?? p.raw_id);
    if (seen.has(polyKey)) return;
    seen.add(polyKey);
    next.push(p);
  });
  trafficLightPolylines = next;
  trafficLightPolylineSignature = signature;
}

function interpolateHeading(first, second, ratio) {
  const start = Number(first || 0);
  const end = Number(second || 0);
  const delta = Math.atan2(Math.sin(end - start), Math.cos(end - start));
  return start + delta * ratio;
}

function interpolateRoadUser(first, second, ratio) {
  const result = { ...second };
  ['x', 'y', 'z', 'speed', 'vx', 'vy', 'ax', 'ay', 'length', 'width', 'height'].forEach(key => {
    const start = Number(first?.[key]);
    const end = Number(second?.[key]);
    if (Number.isFinite(start) && Number.isFinite(end)) result[key] = start + (end - start) * ratio;
  });
  result.heading = interpolateHeading(first?.heading, second?.heading, ratio);
  return result;
}

function interpolateSimStates(first, second, ratio) {
  const firstVehicles = new Map((first?.vehicles || []).map(item => [String(item.id), item]));
  const secondIds = new Set();
  const vehicles = (second?.vehicles || []).map(item => {
    const id = String(item.id);
    secondIds.add(id);
    const previous = firstVehicles.get(id);
    return previous ? interpolateRoadUser(previous, item, ratio) : item;
  });
  if (ratio < 1) {
    firstVehicles.forEach((item, id) => {
      if (!secondIds.has(id)) vehicles.push(item);
    });
  }
  const result = { ...second, vehicles };
  const firstTime = Number(first?.sim_time);
  const secondTime = Number(second?.sim_time);
  if (Number.isFinite(firstTime) && Number.isFinite(secondTime)) {
    result.sim_time = firstTime + (secondTime - firstTime) * ratio;
  }
  ['world_video_time', 'world_video_frame'].forEach(key => {
    const start = Number(first?.[key]);
    const end = Number(second?.[key]);
    if (Number.isFinite(start) && Number.isFinite(end)) {
      result[key] = start + (end - start) * ratio;
    }
  });
  return result;
}

function animateSimInterpolation(timestamp) {
  simAnimationFrame = 0;
  if (!simInterpolation || !currentDetailMode()) return;
  if (timestamp - lastSimAnimationAt < SIM_RENDER_INTERVAL_MS) {
    simAnimationFrame = window.requestAnimationFrame(animateSimInterpolation);
    return;
  }
  lastSimAnimationAt = timestamp;
  const ratio = Math.max(0, Math.min(1, (timestamp - simInterpolation.startedAt) / simInterpolation.durationMs));
  simData = interpolateSimStates(simInterpolation.first, simInterpolation.second, ratio);
  updateLiveTelemetry(simData);
  if (followSelectedVehicle) centerOnSelectedVehicle();
  requestDrawFrame();
  if (ratio < 1) {
    simAnimationFrame = window.requestAnimationFrame(animateSimInterpolation);
  } else {
    simData = simInterpolation.second;
    simInterpolation = null;
    updateSelectedVehiclePanel();
  }
}

function ingestSimState(nextState) {
  const next = applyOfflineAvToSimState(nextState);
  const firstTime = Number(simData?.sim_time);
  const secondTime = Number(next?.sim_time);
  const deltaSeconds = secondTime - firstTime;
  updateVehicleIdOptions(next?.vehicles || []);
  if (simData && Number.isFinite(deltaSeconds) && deltaSeconds > 0 && deltaSeconds <= 1.0) {
    const synchronizedInterval = Number(next?.world_preview_interval_ms);
    simInterpolation = {
      first: simData,
      second: next,
      startedAt: performance.now(),
      durationMs: Number.isFinite(synchronizedInterval)
        ? Math.max(50, Math.min(1000, synchronizedInterval))
        : Math.max(70, Math.min(500, deltaSeconds * 1000)),
    };
    if (!simAnimationFrame) simAnimationFrame = window.requestAnimationFrame(animateSimInterpolation);
    return;
  }
  if (simAnimationFrame) window.cancelAnimationFrame(simAnimationFrame);
  simAnimationFrame = 0;
  simInterpolation = null;
  simData = next;
  updateLiveTelemetry(simData);
  if (followSelectedVehicle) centerOnSelectedVehicle();
  requestDrawFrame();
  updateSelectedVehiclePanel();
}

async function pollSimState() {
  if (simStateBusy || !mapData || !currentDetailMode()) return;
  if (runState === 'playback' && replayPlaying) return;
  simStateBusy = true;
  try {
    const params = new URLSearchParams();
    if (lastSimStateVersion > 0) {
      params.set('after', String(lastSimStateVersion));
      params.set('delivery', 'next');
    }
    if (!document.hidden) params.set('wait_ms', '200');
    const query = params.toString();
    const res = await apiGet(`/sim_state${query ? `?${query}` : ''}`);
    const frameVersion = Number(res.frame_version);
    if (Number.isFinite(frameVersion)) lastSimStateVersion = Math.max(lastSimStateVersion, frameVersion);
    if (res.unchanged) return;
    if (res.ok) {
      const nextVehicles = Array.isArray(res.vehicles) ? res.vehicles : [];
      const prevVehicles = Array.isArray(simData?.vehicles) ? simData.vehicles : [];
      if (
        runState === 'playback'
        && replayTotalSteps > 0
        && nextVehicles.length === 0
        && prevVehicles.length > 0
      ) {
        return;
      }
      ingestSimState(res);
    }
  } catch (_) {
  } finally {
    simStateBusy = false;
  }
}

function chooseDefaultOfflineAv(vehicles) {
  if (offlineAvId || !Array.isArray(vehicles) || vehicles.length === 0) return;
  const motorized = vehicles.filter(v => !['pedestrian', 'cyclist', 'non_motorized'].includes(roadUserType(v)));
  const candidates = motorized.filter(v => String(v.type || '').toLowerCase() !== 'av');
  const pool = candidates.length ? candidates : motorized;
  if (!pool.length) return;
  const candidate = pool[Math.floor(Math.random() * pool.length)] || pool[0];
  offlineAvId = candidate?.id || null;
  selectedVehicleId = offlineAvId;
}

function applyOfflineAvToSimState(state) {
  if (appMode !== 'offline' || !state || !Array.isArray(state.vehicles)) return state;
  chooseDefaultOfflineAv(state.vehicles);
  state.vehicles = state.vehicles.map(v => {
    const isOfflineAv = offlineAvId && String(v.id) === String(offlineAvId);
    return isOfflineAv ? { ...v, type: 'av', is_av: true, offline_av: true } : v;
  });
  return state;
}

function offlineActionPayload(type, scenario) {
  const avEnabled = !!$('avAccessToggle')?.checked;
  const avControlModel = $('avControlModelSelect')?.value || 'DEFAULT_TCP';
  const rawAvControlPort = ($('avControlPortInput')?.value || '').trim();
  const avControlPort = rawAvControlPort ? parseInt(rawAvControlPort, 10) : NaN;
  const vtdBridgePort = parseInt($('vtdBridgePortInput')?.value || '10010', 10);
  return {
    type,
    scenario,
    gpu_id: $('gpuIdInput')?.value?.trim() || '4',
    offline_av_id: offlineAvId || selectedVehicleId || '',
    av_enabled: avEnabled,
    av_control_model: avControlModel,
    av_control_host: avEnabled ? ($('avControlHostInput')?.value || '127.0.0.1') : undefined,
    av_control_port: avEnabled && Number.isFinite(avControlPort) ? avControlPort : undefined,
    vtd_bridge_ip: avEnabled && avControlModel === 'VTD_TCP' ? ($('vtdBridgeHostInput')?.value || '127.0.0.1') : undefined,
    vtd_bridge_port: avEnabled && avControlModel === 'VTD_TCP' && Number.isFinite(vtdBridgePort) ? vtdBridgePort : undefined,
  };
}

// ── Canvas drawing ────────────────────────────────────────────────────────────
function requestDrawFrame() {
  if (drawFrameScheduled) return;
  drawFrameScheduled = true;
  window.requestAnimationFrame(() => {
    drawFrameScheduled = false;
    drawFrame();
  });
}

function mapBounds() {
  return mapData && mapData.bounds ? mapData.bounds : null;
}

function virtualSize() {
  const b = mapBounds();
  if (!b) return { w: frameImg.naturalWidth || 1024, h: frameImg.naturalHeight || 1024 };
  const spanX = Math.max(1e-6, b.max_x - b.min_x);
  const spanY = Math.max(1e-6, b.max_y - b.min_y);
  const base = 8192;
  if (spanX >= spanY) return { w: base, h: Math.max(1, Math.round(base * spanY / spanX)) };
  return { w: Math.max(1, Math.round(base * spanX / spanY)), h: base };
}

function worldToVirtual(x, y) {
  const b = mapBounds();
  const sz = virtualSize();
  if (!b) return { x, y };
  return {
    x: ((x - b.min_x) / Math.max(b.max_x - b.min_x, 1e-6)) * sz.w,
    y: ((b.max_y - y) / Math.max(b.max_y - b.min_y, 1e-6)) * sz.h,
  };
}

function virtualToWorld(px, py) {
  const b = mapBounds();
  const sz = virtualSize();
  if (!b) return { x: px, y: py };
  return {
    x: b.min_x + (px / Math.max(sz.w, 1)) * (b.max_x - b.min_x),
    y: b.max_y - (py / Math.max(sz.h, 1)) * (b.max_y - b.min_y),
  };
}

function drawFrame() {
  const canvas = $('trafficCanvas');
  if (canvas.width <= 0 || canvas.height <= 0) resizeTrafficCanvas();
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!frameLoaded && !mapData) return;
  if (mapData) {
    drawStaticMapLayer(canvas);
    if (staticMapLayer) ctx.drawImage(staticMapLayer, 0, 0);
    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(zoom, zoom);
    drawVectorFrame(ctx);
    drawInfeasibleRegions(ctx);
    ctx.restore();
  } else {
    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(zoom, zoom);
    ctx.drawImage(frameImg, 0, 0);
    drawInfeasibleRegions(ctx);
    ctx.restore();
  }
  $('zoomPercent').textContent = Math.round(zoom * 100) + '%';
}

function resizeTrafficCanvas() {
  const canvas = $('trafficCanvas');
  const vp = $('trafficViewport');
  const w = Math.max(1, Math.round(vp.clientWidth));
  const h = Math.max(1, Math.round(vp.clientHeight));
  if (canvas.width === w && canvas.height === h) return;
  canvas.width = w;
  canvas.height = h;
  invalidateStaticMapLayer();
}

function vehicleAtWorld(wx, wy) {
  if (!simData || !simData.vehicles) return null;
  let best = null;
  let bestDist = Infinity;
  simData.vehicles.forEach(v => {
    const d = Math.hypot(Number(v.x) - wx, Number(v.y) - wy);
    const pickRadius = Math.max(3.0, (Number(v.length) || 3.8) * 0.75);
    if (d < pickRadius && d < bestDist) {
      best = v;
      bestDist = d;
    }
  });
  return best;
}

function selectedVehicle() {
  if (!selectedVehicleId || !simData || !simData.vehicles) return null;
  return simData.vehicles.find(v => v.id === selectedVehicleId) || null;
}

function centerOnSelectedVehicle() {
  const v = selectedVehicle();
  if (!v) return;
  const canvas = $('trafficCanvas');
  const q = worldToVirtual(v.x, v.y);
  panX = canvas.width / 2 - q.x * zoom;
  panY = canvas.height / 2 - q.y * zoom;
}

function focusSelectedVehicle(widthMeters = 180, heightMeters = 120) {
  const vehicle = selectedVehicle();
  const bounds = mapBounds();
  const canvas = $('trafficCanvas');
  if (!vehicle || !bounds || !canvas) {
    centerOnSelectedVehicle();
    return;
  }
  const size = virtualSize();
  const pixelsPerMeter = Math.min(
    size.w / Math.max(Number(bounds.max_x) - Number(bounds.min_x), 1e-6),
    size.h / Math.max(Number(bounds.max_y) - Number(bounds.min_y), 1e-6),
  );
  const targetZoom = Math.min(
    canvas.width / Math.max(Number(widthMeters) * pixelsPerMeter, 1),
    canvas.height / Math.max(Number(heightMeters) * pixelsPerMeter, 1),
  );
  zoom = Math.max(0.05, Math.min(targetZoom, MAX_ZOOM));
  centerOnSelectedVehicle();
}

function updateSelectedVehiclePanel() {
  const panel = $('selectedVehiclePanel');
  const data = $('selectedVehicleData');
  const v = selectedVehicle();
  if (!v) {
    panel.hidden = true;
    data.innerHTML = '';
    return;
  }
  panel.hidden = false;
  $('vehicleIdInput').value = v.id;
  const distance = Number(v.distance_traveled_m);
  const distanceRow = Number.isFinite(distance)
    ? `<div><span>累计里程</span><b>${distance.toFixed(2)} m</b></div>`
    : '';
  data.innerHTML = `
    <div><span>ID</span><b>${escapeHtml(v.id)}</b></div>
    <div><span>位置</span><b>${Number(v.x).toFixed(2)}, ${Number(v.y).toFixed(2)}</b></div>
    <div><span>航向</span><b>${radToDeg(Number(v.heading)).toFixed(1)} deg</b></div>
    <div><span>速度</span><b>${Number(v.speed).toFixed(2)} m/s</b></div>
    ${distanceRow}
    <div><span>尺寸</span><b>${Number(v.length).toFixed(1)} x ${Number(v.width).toFixed(1)} m</b></div>
    <div><span>模式</span><b>${v.static ? '静态' : '仿真控制'}</b></div>`;
}

function radToDeg(rad) { return Number(rad) * 180 / Math.PI; }
function degToRad(deg) { return Number(deg) * Math.PI / 180; }

function setVehicleOpHint(text) {
  const el = $('vehicleOpHint');
  if (el) el.textContent = text;
}

function clearPendingVehicleOp() {
  pendingVehicleOp = null;
  $('confirmVehicleOpBtn').disabled = true;
  $('cancelVehicleOpBtn').disabled = true;
  setVehicleOpHint('选择模式后在地图上操作。');
  requestDrawFrame();
}

function updateVehicleOpFromMode() {
  clearPendingVehicleOp();
  const mode = $('clickMode').value;
  if (mode === 'delete') setVehicleOpHint('删除模式：先在地图上选中车辆，或在车辆ID中输入/选择。');
  else if (mode === 'add') setVehicleOpHint('增加模式：第一次点击确定位置，第二次点击确定方向。');
}

function setDeleteCandidate(vehicle) {
  if (!vehicle) return;
  selectedVehicleId = vehicle.id;
  $('vehicleIdInput').value = vehicle.id;
  pendingVehicleOp = { type: 'delete', vehicleId: vehicle.id };
  $('confirmVehicleOpBtn').disabled = false;
  $('cancelVehicleOpBtn').disabled = false;
  setVehicleOpHint(`待删除车辆 ID: ${vehicle.id}`);
  updateSelectedVehiclePanel();
  requestDrawFrame();
}

function setAddFirstPoint(world) {
  pendingVehicleOp = { type: 'add', stage: 1, x: world.x, y: world.y };
  $('vehicleXInput').value = world.x.toFixed(2);
  $('vehicleYInput').value = world.y.toFixed(2);
  $('vehicleHeadingInput').value = '';
  $('confirmVehicleOpBtn').disabled = true;
  $('cancelVehicleOpBtn').disabled = false;
  setVehicleOpHint(`已选择位置 (${world.x.toFixed(2)}, ${world.y.toFixed(2)})，再次点击确定方向。`);
  requestDrawFrame();
}

function setAddSecondPoint(world) {
  if (!pendingVehicleOp || pendingVehicleOp.type !== 'add') return;
  const dx = world.x - pendingVehicleOp.x;
  const dy = world.y - pendingVehicleOp.y;
  const headingDeg = radToDeg(Math.atan2(dy, dx));
  pendingVehicleOp.stage = 2;
  pendingVehicleOp.headingDeg = headingDeg;
  pendingVehicleOp.endX = world.x;
  pendingVehicleOp.endY = world.y;
  $('vehicleHeadingInput').value = headingDeg.toFixed(1);
  $('confirmVehicleOpBtn').disabled = false;
  $('cancelVehicleOpBtn').disabled = false;
  setVehicleOpHint(`待增加车辆，位置和方向已确定。`);
  requestDrawFrame();
}

function syncPendingAddFromInputs() {
  if (!pendingVehicleOp || pendingVehicleOp.type !== 'add') return;
  const x = parseFloat($('vehicleXInput').value);
  const y = parseFloat($('vehicleYInput').value);
  const h = parseFloat($('vehicleHeadingInput').value);
  if (Number.isFinite(x)) pendingVehicleOp.x = x;
  if (Number.isFinite(y)) pendingVehicleOp.y = y;
  if (Number.isFinite(h)) {
    pendingVehicleOp.headingDeg = h;
    pendingVehicleOp.stage = 2;
    $('confirmVehicleOpBtn').disabled = false;
  }
  requestDrawFrame();
}

function drawVectorFrame(ctx) {
  const vp = $('trafficViewport');
  if (vp && vp.style.backgroundColor !== mapBackgroundColor) vp.style.backgroundColor = mapBackgroundColor;
  if ($('showTrafficLightToggle').checked) {
    updateTrafficLightPolylineCache();
    drawTrafficLights(ctx);
  }
  if (simData && $('showPastTrajectoryToggle').checked) drawTrajectories(ctx, 'past');
  if (simData && $('showFutureTrajectoryToggle').checked) drawTrajectories(ctx, 'future');
  drawVehicleOpPreview(ctx);
  if (simData) drawVehicles(ctx);
}

function drawStaticMapLayer(canvas) {
  if (!mapData) return;
  const signature = [
    mapRenderVersion,
    canvas.width,
    canvas.height,
    mapBackgroundColor,
    zoom.toFixed(8),
    panX.toFixed(3),
    panY.toFixed(3),
  ].join('|');
  if (staticMapLayer && staticMapLayerSignature === signature) return;

  if (!staticMapLayer) staticMapLayer = document.createElement('canvas');
  if (staticMapLayer.width !== canvas.width || staticMapLayer.height !== canvas.height) {
    staticMapLayer.width = canvas.width;
    staticMapLayer.height = canvas.height;
  }
  const layerCtx = staticMapLayer.getContext('2d');
  layerCtx.setTransform(1, 0, 0, 1, 0, 0);
  layerCtx.clearRect(0, 0, staticMapLayer.width, staticMapLayer.height);
  layerCtx.fillStyle = mapBackgroundColor;
  layerCtx.fillRect(0, 0, staticMapLayer.width, staticMapLayer.height);
  layerCtx.save();
  layerCtx.translate(panX, panY);
  layerCtx.scale(zoom, zoom);
  drawRasterMap(layerCtx);
  drawVectorMap(layerCtx);
  drawSemanticRoadMarkings(layerCtx);
  layerCtx.restore();
  staticMapLayerSignature = signature;
}

function drawRasterMap(ctx) {
  if (!mapRasterLoaded || !mapRasterImg.naturalWidth) return;
  const bounds = mapData?.raster_bounds || mapData?.bounds;
  if (!bounds) return;
  const topLeft = worldToVirtual(Number(bounds.min_x), Number(bounds.max_y));
  const bottomRight = worldToVirtual(Number(bounds.max_x), Number(bounds.min_y));
  ctx.drawImage(
    mapRasterImg,
    topLeft.x,
    topLeft.y,
    Math.max(1, bottomRight.x - topLeft.x),
    Math.max(1, bottomRight.y - topLeft.y),
  );
}

function trafficLightStateForPolyline(polyline) {
  if (!simData || !simData.traffic_lights) return null;
  const candidates = [polyline.id, polyline.raw_id, String(polyline.id), String(polyline.raw_id)];
  for (const key of candidates) {
    if (key != null && Object.prototype.hasOwnProperty.call(simData.traffic_lights, String(key))) {
      return Number(simData.traffic_lights[String(key)]);
    }
  }
  return null;
}

function trafficLightStateForSemantic(signal) {
  if (!simData || !simData.traffic_lights) return null;
  const candidates = [signal.id, signal.controller_id, signal.lane_id, ...(signal.state_keys || [])];
  const states = [];
  for (const key of candidates) {
    if (key != null && Object.prototype.hasOwnProperty.call(simData.traffic_lights, String(key))) {
      states.push(Number(simData.traffic_lights[String(key)]));
    }
  }
  if (states.includes(0)) return 0;
  if (states.includes(1)) return 1;
  if (states.includes(2)) return 2;
  return states.length ? states[0] : null;
}

function colorForPolyline(polyline) {
  return {
    0: '#2563eb',
    1: '#111827',
    2: '#1f2937',
    3: '#475569',
    4: '#475569',
  }[Number(polyline.type)] || '#6b7280';
}

function lineWidthForPolyline(polyline) {
  const type = Number(polyline.type);
  const screenPx = type === 1 ? 2.1 : type === 2 ? 1.7 : type === 3 ? 1.5 : 1.35;
  return screenPx / Math.max(zoom, 0.001);
}

function drawPolylinePath(ctx, polyline) {
  const pts = polyline.points || [];
  if (pts.length < 2) return false;
  ctx.beginPath();
  pts.forEach((pt, i) => {
    const q = worldToVirtual(pt[0], pt[1]);
    if (i === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y);
  });
  return true;
}

function drawVectorMap(ctx) {
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  (mapData.polylines || []).forEach(p => {
    if (Number(p.type) === 4) return;
    if (!drawPolylinePath(ctx, p)) return;
    ctx.strokeStyle = colorForPolyline(p);
    ctx.lineWidth = lineWidthForPolyline(p);
    if (p.lane_center || Number(p.type) === 0 || Number(p.type) === 3) ctx.setLineDash([7 / zoom, 5 / zoom]);
    else ctx.setLineDash([]);
    ctx.stroke();
  });
  ctx.restore();
}

function drawSemanticRoadMarkings(ctx) {
  if (!mapData) return;
  ctx.save();
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'round';
  (mapData.crosswalks || []).forEach(crosswalk => {
    const polygon = crosswalk.polygon || [];
    if (polygon.length >= 3) {
      ctx.beginPath();
      polygon.forEach((point, index) => {
        const q = worldToVirtual(point[0], point[1]);
        if (index === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y);
      });
      ctx.closePath();
      ctx.fillStyle = 'rgba(248, 250, 252, 0.18)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(248, 250, 252, 0.72)';
      ctx.lineWidth = 0.9 / Math.max(zoom, 0.001);
      ctx.stroke();
    }
    const line = crosswalk.centerline || [];
    if (line.length < 2) return;
    const x0 = Number(line[0][0]), y0 = Number(line[0][1]);
    const x1 = Number(line[line.length - 1][0]), y1 = Number(line[line.length - 1][1]);
    const length = Math.hypot(x1 - x0, y1 - y0);
    if (length < 0.1) return;
    const dx = (x1 - x0) / length, dy = (y1 - y0) / length;
    const nx = -dy, ny = dx;
    const width = Math.max(1.5, Number(crosswalk.width) || 3.5);
    const spacing = Math.max(0.55, Number(crosswalk.stripe_spacing) || 0.8);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    const q0 = worldToVirtual(x0, y0);
    const q1 = worldToVirtual(x0 + dx, y0 + dy);
    const meterPixels = Math.max(Math.hypot(q1.x - q0.x, q1.y - q0.y), 1e-6);
    ctx.lineWidth = Math.max(0.42 * meterPixels, 1.4 / Math.max(zoom, 0.001));
    for (let offset = spacing / 2; offset < length; offset += spacing) {
      const cx = x0 + dx * offset, cy = y0 + dy * offset;
      const a = worldToVirtual(cx - nx * width / 2, cy - ny * width / 2);
      const b = worldToVirtual(cx + nx * width / 2, cy + ny * width / 2);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
  });
  (mapData.stop_lines || []).forEach(stopLine => {
    const points = stopLine.points || [];
    if (points.length < 2) return;
    ctx.beginPath();
    points.forEach((point, index) => {
      const q = worldToVirtual(point[0], point[1]);
      if (index === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y);
    });
    ctx.strokeStyle = '#f8fafc';
    ctx.lineWidth = 3.2 / Math.max(zoom, 0.001);
    ctx.stroke();
  });
  ctx.restore();
}

function drawTrafficLights(ctx) {
  if (!mapData || !mapData.polylines) return;
  const colors = ['#16a34a', '#ca8a04', '#dc2626', '#475569'];
  const hasSemanticSignals = (mapData.traffic_signals || []).length > 0;
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  (trafficLightPolylines || []).forEach(p => {
    const state = trafficLightStateForPolyline(p);
    const isTrafficLightLine = Number(p.type) === 4 || state != null;
    if (!isTrafficLightLine) return;
    if (!drawPolylinePath(ctx, p)) return;
    ctx.setLineDash([]);
    ctx.lineWidth = (hasSemanticSignals ? 1.4 : (state == null ? 3.2 : 5.2)) / Math.max(zoom, 0.001);
    ctx.strokeStyle = hasSemanticSignals
      ? 'rgba(71, 85, 105, 0.5)'
      : '#ffffff';
    if (hasSemanticSignals) ctx.setLineDash([5 / Math.max(zoom, 0.001), 4 / Math.max(zoom, 0.001)]);
    ctx.stroke();
    ctx.setLineDash([]);
    if (!hasSemanticSignals) {
      drawPolylinePath(ctx, p);
      ctx.lineWidth = (state == null ? 1.8 : 3.6) / Math.max(zoom, 0.001);
      ctx.strokeStyle = state == null ? '#7c3aed' : (colors[state] || '#475569');
      ctx.stroke();
    }
    const pts = p.points || [];
    if (!hasSemanticSignals && pts.length > 0) {
      const q = worldToVirtual(pts[0][0], pts[0][1]);
      const r = (state == null ? 4.2 : 5.2) / Math.max(zoom, 0.001);
      ctx.beginPath();
      ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
      ctx.fillStyle = state == null ? '#7c3aed' : (colors[state] || '#475569');
      ctx.fill();
      ctx.lineWidth = 1.6 / Math.max(zoom, 0.001);
      ctx.strokeStyle = '#ffffff';
      ctx.stroke();
    }
  });
  (mapData.traffic_signals || []).forEach(signal => {
    const position = signal.position || [];
    if (position.length < 2) return;
    const heading = Number(signal.heading) || 0;
    const isPedestrian = String(signal.signal_type || '').toLowerCase() === 'pedestrian';
    const normal = [-Math.sin(heading), Math.cos(heading)];
    const armEnd = signal.mast_arm_end || (
      isPedestrian
        ? position
        : [Number(position[0]) + normal[0] * 4, Number(position[1]) + normal[1] * 4]
    );
    const base = worldToVirtual(position[0], position[1]);
    const arm = worldToVirtual(armEnd[0], armEnd[1]);
    const unit = 1 / Math.max(zoom, 0.001);
    ctx.beginPath();
    ctx.moveTo(base.x, base.y);
    if (!isPedestrian) ctx.lineTo(arm.x, arm.y);
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 4.2 * unit;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(base.x, base.y, 4.8 * unit, 0, Math.PI * 2);
    ctx.fillStyle = '#334155';
    ctx.fill();
    ctx.strokeStyle = '#f8fafc';
    ctx.lineWidth = 1.2 * unit;
    ctx.stroke();

    const heads = (signal.head_positions || []).length
      ? signal.head_positions
      : [{
        movement: isPedestrian ? 'pedestrian' : 'combined',
        position: isPedestrian
          ? position
          : [Number(position[0]) * 0.3 + Number(armEnd[0]) * 0.7, Number(position[1]) * 0.3 + Number(armEnd[1]) * 0.7],
        state_keys: signal.state_keys || [],
      }];
    const lampColors = ['#16a34a', '#eab308', '#dc2626'];
    heads.forEach(head => {
      const headPosition = head.position || [];
      if (headPosition.length < 2) return;
      const q = worldToVirtual(headPosition[0], headPosition[1]);
      const state = trafficLightStateForSemantic({
        state_keys: head.state_keys || signal.state_keys || [],
      });
      ctx.save();
      ctx.translate(q.x, q.y);
      ctx.rotate(-heading);
      ctx.fillStyle = '#111827';
      ctx.fillRect(-8.5 * unit, -4.5 * unit, 17 * unit, 9 * unit);
      ctx.strokeStyle = '#f8fafc';
      ctx.lineWidth = 1.1 * unit;
      ctx.strokeRect(-8.5 * unit, -4.5 * unit, 17 * unit, 9 * unit);
      lampColors.forEach((color, index) => {
        ctx.beginPath();
        ctx.arc((-5.2 + index * 5.2) * unit, 0, 2.05 * unit, 0, Math.PI * 2);
        ctx.fillStyle = state === index ? color : '#475569';
        ctx.fill();
      });
      ctx.restore();
    });
  });
  ctx.restore();
}

function drawTrajectories(ctx, key) {
  const future = key === 'future';
  const selectedOnly = !!$('selectedTrajectoryOnlyToggle')?.checked;
  ctx.save();
  ctx.lineWidth = future ? 2 / zoom : 1.8 / zoom;
  (simData.vehicles || []).forEach(v => {
    if (selectedOnly && selectedVehicleId && v.id !== selectedVehicleId) return;
    const pathPts = buildTrajectoryPath(v, key);
    if (pathPts.length < 2) return;
    ctx.beginPath();
    pathPts.forEach((pt, i) => {
      const q = worldToVirtual(pt[0], pt[1]);
      if (i === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y);
    });
    if (future) {
      ctx.strokeStyle = v.id === selectedVehicleId ? '#f97316' : '#38bdf8';
      ctx.setLineDash([5 / zoom, 4 / zoom]);
    } else {
      ctx.strokeStyle = v.id === selectedVehicleId ? 'rgba(249,115,22,0.9)' : 'rgba(34,197,94,0.86)';
      ctx.setLineDash([]);
    }
    ctx.stroke();
  });
  ctx.restore();
}

function validTrajectoryPoint(pt) {
  return Array.isArray(pt)
    && pt.length >= 2
    && Number.isFinite(Number(pt[0]))
    && Number.isFinite(Number(pt[1]));
}

function buildTrajectoryPath(v, key) {
  const raw = (v[key] || []).filter(validTrajectoryPoint).map(pt => [Number(pt[0]), Number(pt[1])]);
  const cur = [Number(v.x), Number(v.y)];
  if (!Number.isFinite(cur[0]) || !Number.isFinite(cur[1])) return [];
  const maxJump = 35;
  const dedupeEps = 1e-3;
  if (key === 'future') {
    const out = [cur];
    let prev = cur;
    for (const pt of raw) {
      if (Math.hypot(pt[0] - prev[0], pt[1] - prev[1]) <= dedupeEps) continue;
      if (Math.hypot(pt[0] - prev[0], pt[1] - prev[1]) > maxJump) break;
      out.push(pt);
      prev = pt;
    }
    return out;
  }
  const maxPastPoints = Math.max(2, Math.round((parseFloat($('historyDurationInput')?.value) || 3) / Math.max(replayStepSeconds, 0.1)) + 1);
  const tail = raw.slice(-maxPastPoints);
  const out = [];
  let prev = null;
  for (const pt of tail) {
    if (prev && Math.hypot(pt[0] - prev[0], pt[1] - prev[1]) <= dedupeEps) continue;
    if (prev && Math.hypot(pt[0] - prev[0], pt[1] - prev[1]) > maxJump) {
      out.length = 0;
    }
    out.push(pt);
    prev = pt;
  }
  if (!prev || Math.hypot(cur[0] - prev[0], cur[1] - prev[1]) > maxJump) return [];
  if (Math.hypot(cur[0] - prev[0], cur[1] - prev[1]) > dedupeEps) out.push(cur);
  return out;
}

function drawVehicleOpPreview(ctx) {
  if (!pendingVehicleOp || pendingVehicleOp.type !== 'add') return;
  const p0 = worldToVirtual(pendingVehicleOp.x, pendingVehicleOp.y);
  ctx.save();
  ctx.lineWidth = 2 / Math.max(zoom, 0.001);
  ctx.strokeStyle = '#f97316';
  ctx.fillStyle = '#fed7aa';
  ctx.beginPath();
  ctx.arc(p0.x, p0.y, 5 / Math.max(zoom, 0.001), 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  if (pendingVehicleOp.stage >= 2) {
    const rad = degToRad(pendingVehicleOp.headingDeg);
    const p1 = worldToVirtual(pendingVehicleOp.x + Math.cos(rad) * 12, pendingVehicleOp.y + Math.sin(rad) * 12);
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y);
    ctx.lineTo(p1.x, p1.y);
    ctx.stroke();
  }
  ctx.restore();
}

function roadUserType(actor) {
  return String(actor?.road_user_type || actor?.actor_type || actor?.type || 'vehicle').toLowerCase();
}

function drawVehicles(ctx) {
  ctx.save();
  const showId = $('showVehicleIdToggle').checked;
  const egoId = activeEgoId();
  (simData.vehicles || []).forEach(v => {
    const c = worldToVirtual(v.x, v.y);
    const actorType = roadUserType(v);
    const heading = Number(v.heading) || 0;
    const unit = worldToVirtual(v.x + Math.cos(heading), v.y + Math.sin(heading));
    const metersToPx = Math.max(Math.hypot(unit.x - c.x, unit.y - c.y), 1e-6);
    const selected = String(v.id) === String(selectedVehicleId);
    const isAv = String(v.type || '').toLowerCase() === 'av' || v.is_av === true || v.is_ego === true
      || (egoId && String(v.id) === egoId);

    if (actorType === 'pedestrian') {
      const radius = Math.max(0.32 * metersToPx, 2.25 / Math.max(zoom, 0.001));
      ctx.save();
      ctx.translate(c.x, c.y);
      ctx.fillStyle = v.static ? '#f97316' : '#fb7185';
      ctx.strokeStyle = selected ? '#facc15' : '#4c0519';
      ctx.lineWidth = (selected ? 2.5 : 1) / zoom;
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(-heading) * radius * 1.7, Math.sin(-heading) * radius * 1.7);
      ctx.stroke();
      ctx.restore();
    } else {
      const cyclist = actorType === 'cyclist' || actorType === 'non_motorized';
      const length = cyclist ? Math.max(Number(v.length) || 1.8, 1.4) : Math.max(Number(v.length) || 3.8, 2);
      const width = cyclist ? Math.max(Number(v.width) || 0.62, 0.45) : Math.max(Number(v.width) || 1.8, 1);
      const lpx = length * metersToPx;
      const wpx = width * metersToPx;
      ctx.save();
      ctx.translate(c.x, c.y);
      ctx.rotate(-heading);
      const vehicleClass = String(v.vehicle_class || '').toLowerCase();
      const classColor = vehicleClass === 'bus' ? '#f59e0b'
        : vehicleClass === 'truck' ? '#a78bfa'
          : vehicleClass === 'van' ? '#34d399'
            : '#38bdf8';
      ctx.fillStyle = isAv ? '#facc15' : (v.static ? '#ef4444' : (cyclist ? '#22c55e' : classColor));
      ctx.strokeStyle = selected ? '#f97316' : '#020617';
      ctx.lineWidth = (selected ? 2.5 : 1) / zoom;
      ctx.beginPath();
      ctx.rect(-lpx / 2, -wpx / 2, lpx, wpx);
      ctx.fill();
      ctx.stroke();
      if (cyclist) {
        ctx.fillStyle = '#ecfdf5';
        ctx.beginPath();
        ctx.arc(-lpx * 0.3, 0, Math.max(wpx * 0.28, 1 / zoom), 0, Math.PI * 2);
        ctx.arc(lpx * 0.3, 0, Math.max(wpx * 0.28, 1 / zoom), 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.moveTo(lpx / 2, 0);
        ctx.lineTo(lpx * 0.18, -wpx * 0.32);
        ctx.lineTo(lpx * 0.18, wpx * 0.32);
        ctx.closePath();
        ctx.fillStyle = isAv ? '#fef3c7' : '#e0f2fe';
        ctx.fill();
      }
      ctx.restore();
    }
    if (showId) {
      ctx.font = `${Math.max(11 / zoom, 0.001)}px Segoe UI, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.lineWidth = 3 / zoom;
      ctx.strokeStyle = '#020617';
      ctx.fillStyle = selected ? '#fed7aa' : '#f8fafc';
      ctx.strokeText(v.id, c.x, c.y - 6 / zoom);
      ctx.fillText(v.id, c.x, c.y - 6 / zoom);
    }
  });
  ctx.restore();
}

function drawInfeasibleRegions(ctx) {
  if (!infeasibleRegions.length) return;
  ctx.save();
  ctx.lineWidth = 2 / zoom;
  infeasibleRegions.forEach(r => {
    const sz = virtualSize();
    const px = r.nx * sz.w;
    const py = r.ny * sz.h;
    const radiusPx = mapData ? Math.max(8 / zoom, Number(r.radius || 10) * (sz.w / Math.max(mapBounds().max_x - mapBounds().min_x, 1))) : Math.max(8, Number(r.radius || 10));
    ctx.beginPath();
    ctx.arc(px, py, radiusPx, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(245, 158, 11, 0.22)';
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.95)';
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(px - radiusPx * 0.7, py - radiusPx * 0.7);
    ctx.lineTo(px + radiusPx * 0.7, py + radiusPx * 0.7);
    ctx.stroke();
  });
  ctx.restore();
}

function fitFrame() {
  if (!frameLoaded && !mapData) return;
  const vp = $('trafficViewport');
  const sz = virtualSize();
  const sx = vp.clientWidth / sz.w;
  const sy = vp.clientHeight / sz.h;
  zoom = Math.min(sx, sy);
  panX = (vp.clientWidth - sz.w * zoom) / 2;
  panY = (vp.clientHeight - sz.h * zoom) / 2;
  requestDrawFrame();
}

// ── Chart helpers ─────────────────────────────────────────────────────────────
function numericOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function numericArrayOrFallback(values, fallback = null) {
  if (Array.isArray(values)) {
    return values.map(numericOrNull).filter(v => v != null);
  }
  const direct = numericOrNull(values);
  if (direct != null) return [direct];
  const fallbackValue = numericOrNull(fallback);
  return fallbackValue != null ? [fallbackValue] : [];
}

function upsertMetricSample(status) {
  const step = Number(status.step);
  if (!Number.isFinite(step)) return;
  if (metricSamples.length > 0 && step < metricSamples[metricSamples.length - 1].step) {
    metricSamples = [];
    metricSampleIndex = new Map();
  }
  const sampleStepSeconds = Number(
    status.replay_step_seconds
    || status.step_seconds
    || status.sim_resolution
    || (runState === 'playback' ? replayStepSeconds : simStepSeconds)
    || 0.1
  );
  const sample = {
    step,
    time: step * Math.max(sampleStepSeconds || 0.1, 1e-6),
    speed: Number(status.vehicles) > 0 ? numericOrNull(status.avg_speed) : null,
    ttc: numericOrNull(status.av_min_ttc ?? status.avg_ttc),
    arrival: numericOrNull(status.arrival_rate),
    headway: numericOrNull(status.av_avg_headway ?? status.avg_headway),
    speedSamples: Number(status.vehicles) > 0 ? numericArrayOrFallback(status.speed_samples, status.avg_speed) : [],
    ttcSamples: numericArrayOrFallback(status.av_ttc_samples ?? status.ttc_samples, status.av_min_ttc ?? status.avg_ttc),
    headwaySamples: numericArrayOrFallback(status.av_headway_samples ?? status.headway_samples, status.av_avg_headway ?? status.avg_headway),
    collisionCount: status.safety_computed === false ? null : numericOrNull(status.av_collision_count ?? status.collision_count),
    violationRate: numericOrNull(status.violation_rate),
  };
  const existing = metricSampleIndex.get(step);
  if (existing != null) {
    metricSamples[existing] = sample;
  } else {
    metricSampleIndex.set(step, metricSamples.length);
    metricSamples.push(sample);
  }
}

function buildReplayMetricSamples() {
  if (!replayMetrics) return [];
  const metricLength = Math.max(
    replayMetrics.speed_per_step?.length || 0,
    replayMetrics.min_ttc_per_step?.length || 0,
    replayMetrics.headway_per_step?.length || 0,
    replayMetrics.collision_count_per_step?.length || 0,
    replayMetrics.violation_rate_per_step?.length || 0,
    replayMetrics.speed_samples_per_step?.length || 0,
    replayMetrics.ttc_samples_per_step?.length || 0,
    replayMetrics.headway_samples_per_step?.length || 0,
  );
  const total = Number(replayMetrics.total_steps || metricLength || 0);
  const stepSeconds = Number(
    replayMetrics.step_seconds
    || replayMetrics.sim_resolution
    || (runState === 'playback' ? replayStepSeconds : simStepSeconds)
    || 0.1
  );
  const samples = [];
  for (let i = 0; i < total; i += 1) {
    const vehicleCount = Number(replayMetrics.vehicle_count_per_step?.[i]);
    const hasVehicles = Number.isFinite(vehicleCount) && vehicleCount > 0;
    const hasPairs = Number.isFinite(vehicleCount) && vehicleCount > 1;
    samples.push({
      step: i,
      time: i * Math.max(stepSeconds || 0.1, 1e-6),
      speed: hasVehicles ? numericOrNull(replayMetrics.speed_per_step?.[i]) : null,
      ttc: numericOrNull(replayMetrics.av_min_ttc_per_step?.[i] ?? replayMetrics.min_ttc_per_step?.[i]),
      arrival: numericOrNull(replayMetrics.arrival_rate_per_step?.[i]),
      headway: numericOrNull(replayMetrics.av_headway_per_step?.[i] ?? replayMetrics.headway_per_step?.[i]),
      speedSamples: hasVehicles ? numericArrayOrFallback(replayMetrics.speed_samples_per_step?.[i], replayMetrics.speed_per_step?.[i]) : [],
      ttcSamples: numericArrayOrFallback(replayMetrics.av_ttc_samples_per_step?.[i] ?? replayMetrics.ttc_samples_per_step?.[i], replayMetrics.av_min_ttc_per_step?.[i] ?? replayMetrics.min_ttc_per_step?.[i]),
      headwaySamples: numericArrayOrFallback(replayMetrics.av_headway_samples_per_step?.[i] ?? replayMetrics.headway_samples_per_step?.[i], replayMetrics.av_headway_per_step?.[i] ?? replayMetrics.headway_per_step?.[i]),
      collisionCount: numericOrNull(replayMetrics.av_collision_count_per_step?.[i] ?? replayMetrics.collision_count_per_step?.[i]),
      violationRate: numericOrNull(replayMetrics.violation_rate_per_step?.[i]),
    });
  }
  return samples;
}

function activeMetricSamples() {
  const persistedSamples = buildReplayMetricSamples();
  if (persistedSamples.length) return persistedSamples;
  return metricSamples;
}

function valuesFromSamples(samples, key) {
  const values = [];
  samples.forEach(s => {
    const raw = s?.[key];
    if (Array.isArray(raw)) {
      raw.forEach(v => {
        const n = numericOrNull(v);
        if (n != null) values.push(n);
      });
      return;
    }
    const n = numericOrNull(raw);
    if (n != null) values.push(n);
  });
  return values;
}

function linePointsFromSamples(samples, key) {
  return samples
    .map(s => ({ x: Number(s.time), y: numericOrNull(s[key]) }))
    .filter(p => Number.isFinite(p.x) && p.y != null);
}

function accidentSeries(samples) {
  let eventSum = 0;
  let observed = 0;
  const rate = [];
  const variance = [];
  samples.forEach(sample => {
    if (sample.collisionCount == null) {
      if (observed > 0) {
        const p = eventSum / observed;
        rate.push({ x: sample.time, y: p });
        variance.push({ x: sample.time, y: p * (1 - p) / observed });
      }
      return;
    }
    observed += 1;
    if (Number(sample.collisionCount || 0) > 0) eventSum += 1;
    const p = eventSum / observed;
    rate.push({ x: sample.time, y: p });
    variance.push({ x: sample.time, y: p * (1 - p) / observed });
  });
  return { rate, variance };
}

function scheduleChartUpdate(maxDelay = 600) {
  const now = performance.now();
  if (now - lastChartUpdateAt >= maxDelay) {
    lastChartUpdateAt = now;
    updateCharts();
    return;
  }
  if (chartUpdateTimer) return;
  chartUpdateTimer = setTimeout(() => {
    chartUpdateTimer = null;
    lastChartUpdateAt = performance.now();
    updateCharts();
  }, Math.max(50, maxDelay - (now - lastChartUpdateAt)));
}

function makeLineChart(canvasId, color, interactive = false) {
  return new Chart($(canvasId), {
    type: 'line',
    data: { datasets: [{ data: [], borderColor: color,
      backgroundColor: color.replace(')', ', 0.12)').replace('rgb', 'rgba'),
      fill: true, borderWidth: 1.5, parsing: false }] },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      normalized: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          ticks: { color: '#94a3b8', font: { size: interactive ? 11 : 9 }, maxRotation: 0, callback: v => formatDuration(Number(v)) },
          grid: { color: interactive ? 'rgba(148,163,184,0.12)' : 'rgba(148,163,184,0.08)' },
        },
        y: { ticks: { color: '#94a3b8', font: { size: interactive ? 11 : 10 } }, grid: { color: 'rgba(148,163,184,0.15)' } },
      },
      elements: { point: { radius: 0 }, line: { tension: 0.3 } },
    },
  });
}

function makeBarChart(canvasId, color, labelColor = '#94a3b8', interactive = false) {
  return new Chart($(canvasId), {
    type: 'bar',
    data: { datasets: [{ data: [], backgroundColor: color, borderWidth: 0, parsing: false }] },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: 'linear',
          ticks: { color: labelColor, font: { size: interactive ? 11 : 9 }, maxRotation: 0 },
          grid: { color: interactive ? 'rgba(148,163,184,0.12)' : 'rgba(148,163,184,0.06)' },
        },
        y: { beginAtZero: true, ticks: { color: labelColor, font: { size: interactive ? 11 : 9 } }, grid: { color: 'rgba(148,163,184,0.12)' } },
      },
    },
  });
}

function setChartAxis(chart, points, xMin = null, xMax = null, yMin = null, yMax = null) {
  const xs = points.map(p => Number(p.x)).filter(Number.isFinite);
  const ys = points.map(p => Number(p.y)).filter(Number.isFinite);
  const maxX = xs.length ? Math.max(...xs) : 0;
  chart.options.scales.x.min = Number.isFinite(xMin) ? xMin : 0;
  chart.options.scales.x.max = Number.isFinite(xMax) ? xMax : (maxX > 0 ? maxX : undefined);
  chart.options.scales.y.min = Number.isFinite(yMin) ? yMin : undefined;
  chart.options.scales.y.max = Number.isFinite(yMax) ? yMax : undefined;
  if (!Number.isFinite(yMin) && ys.length === 0) chart.options.scales.y.min = 0;
}

function updateLineChart(chart, points) {
  chart.data.datasets[0].data = [...points];
  setChartAxis(chart, points);
  chart.update('none');
}

function buildHistogram(values, binSize = DEFAULT_HISTOGRAM_BIN_SIZE, xMin = null, xMax = null) {
  const valid = values.filter(v => v != null && isFinite(v));
  const size = Math.max(0.01, Number(binSize) || DEFAULT_HISTOGRAM_BIN_SIZE);
  if (valid.length === 0) return { points: [], min: 0, max: size };
  let mn = Number.isFinite(xMin) ? xMin : Math.floor(Math.min(...valid) / size) * size;
  let mx = Number.isFinite(xMax) ? xMax : Math.ceil(Math.max(...valid) / size) * size;
  if (mx <= mn) mx = mn + size;
  const bins = Math.min(1200, Math.max(1, Math.ceil((mx - mn) / size)));
  mx = mn + bins * size;
  const counts = new Array(bins).fill(0);
  valid.forEach(v => {
    if (v < mn || v > mx) return;
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - mn) / size)));
    counts[i] += 1;
  });
  const points = counts.map((count, i) => ({ x: mn + (i + 0.5) * size, y: count }));
  return { points, min: mn, max: mx };
}

function updateHistChart(chart, values, binSize = DEFAULT_HISTOGRAM_BIN_SIZE, xMin = null, xMax = null, yMin = null, yMax = null) {
  const { points, min, max } = buildHistogram(values, binSize, xMin, xMax);
  chart.data.datasets[0].data = points;
  chart.options.scales.x.min = min;
  chart.options.scales.x.max = max;
  chart.options.scales.y.min = Number.isFinite(yMin) ? yMin : 0;
  chart.options.scales.y.max = Number.isFinite(yMax) ? yMax : undefined;
  chart.update('none');
}

function initCharts() {
  speedChart = makeLineChart('speedChart', 'rgb(56,189,248)');
  ttcChart = makeLineChart('ttcChart', 'rgb(251,191,36)');
  arrivalChart = makeLineChart('arrivalRateChart', 'rgb(34,197,94)');
  histSpeedChart = makeBarChart('histSpeedChart', 'rgba(56,189,248,0.7)');
  histTTCChart = makeBarChart('histTTCChart', 'rgba(251,191,36,0.7)');
  histHeadwayChart = makeBarChart('histHeadwayChart', 'rgba(167,139,250,0.7)');
  accidentRateChart = makeLineChart('accidentRateChart', 'rgb(239,68,68)');
  violationRateChart = makeLineChart('violationRateChart', 'rgb(168,85,247)');
  accidentVarianceChart = makeLineChart('accidentVarianceChart', 'rgb(249,115,22)');
}

// ── Chart update (5000 ms) ────────────────────────────────────────────────────
function updateCharts() {
  if (!speedChart) return;
  const samples = activeMetricSamples();
  const deferHeavyAnalysis = runState === 'playback' && replayPlaying;
  updateLineChart(speedChart, linePointsFromSamples(samples, 'speed'));
  updateLineChart(ttcChart, linePointsFromSamples(samples, 'ttc'));
  updateLineChart(arrivalChart, linePointsFromSamples(samples, 'arrival'));
  const accident = accidentSeries(samples);
  updateLineChart(accidentRateChart, accident.rate);
  updateLineChart(violationRateChart, linePointsFromSamples(samples, 'violationRate'));
  updateLineChart(accidentVarianceChart, accident.variance);
  if (deferHeavyAnalysis) {
    if (expandedChartKey) renderExpandedChart();
    return;
  }
  if ($('histSpeedCheck').checked) updateHistChart(histSpeedChart, valuesFromSamples(samples, 'speedSamples'));
  if ($('histTTCCheck').checked) updateHistChart(histTTCChart, valuesFromSamples(samples, 'ttcSamples'));
  if ($('histHeadwayCheck').checked) updateHistChart(histHeadwayChart, valuesFromSamples(samples, 'headwaySamples'));
  if (expandedChartKey) renderExpandedChart();
}

function resetMetricHistories() {
  metricSamples = [];
  metricSampleIndex = new Map();
  replayMetrics = null;
  metricsLoadedUntil = 0;
  vehicleIdOptionsSignature = '';
  lastSimStateVersion = 0;
  if (chartUpdateTimer) { clearTimeout(chartUpdateTimer); chartUpdateTimer = null; }
  lastChartUpdateAt = 0;
  updateCharts();
  $('statProgress').textContent = '0.0%';
  $('statSimTime').textContent = '0.0s';
  $('statVehicles').textContent = '0';
  if ($('statCyclists')) $('statCyclists').textContent = '0';
  if ($('statPedestrians')) $('statPedestrians').textContent = '0';
  $('statArrivalRate').textContent = '0.000';
  $('statViolationRate').textContent = '—';
  $('statAvgSpeed').textContent = '—';
  $('statMinTTC').textContent = '—';
  $('statRisk').textContent = '—';
}

// ── Maps & Scenarios ──────────────────────────────────────────────────────────
async function loadCapabilities() {
  try {
    const res = await apiGet('/capabilities');
    if (res?.algorithms && typeof res.algorithms === 'object') {
      algorithmCapabilities = { ...algorithmCapabilities, ...res.algorithms };
    }
  } catch (_) {}
}

function currentAlgorithmCapability() {
  const model = (currentDetailMode() && lastStatus?.backend_model && lastStatus.backend_model !== 'manager')
    ? lastStatus.backend_model
    : ($('trafficModelSelect')?.value || (isReplayLikeMode() ? '' : 'cnde'));
  if (!model && isReplayLikeMode()) return {};
  return algorithmCapabilities[model] || algorithmCapabilities.cnde || {};
}

function setControlBlockVisible(childId, visible) {
  const el = $(childId);
  const block = el?.closest('.control-block');
  if (block) block.hidden = !visible;
}

function setFormControlVisible(id, visible) {
  const el = $(id);
  if (!el) return;
  el.hidden = !visible;
  const label = document.querySelector(`label[for="${id}"]`);
  if (label) label.hidden = !visible;
}

function setMetricElementVisible(id, visible) {
  const el = $(id);
  if (!el) return;
  const card = el.closest('.stat-card') || el.closest('.chart-card') || el.closest('.form-check');
  if (card) card.hidden = !visible;
}

function applyMetricCapabilities(capability = currentAlgorithmCapability()) {
  const metrics = capability.metrics || {};
  const showSpeed = metrics.speed !== false;
  const showTtc = !!metrics.ttc;
  const showHeadway = !!metrics.headway;
  const showCollision = !!metrics.collision;
  const showViolation = !!metrics.violation;
  const showArrival = !!metrics.arrival_rate;
  setMetricElementVisible('statAvgSpeed', showSpeed);
  setMetricElementVisible('speedChart', showSpeed);
  setMetricElementVisible('histSpeedCheck', showSpeed);
  if ($('histSpeedCard')) $('histSpeedCard').hidden = !showSpeed || !$('histSpeedCheck')?.checked;
  setMetricElementVisible('statMinTTC', showTtc);
  setMetricElementVisible('ttcChart', showTtc);
  setMetricElementVisible('histTTCCheck', showTtc);
  if ($('histTTCCard')) $('histTTCCard').hidden = !showTtc || !$('histTTCCheck')?.checked;
  setMetricElementVisible('histHeadwayCheck', showHeadway);
  if ($('histHeadwayCard')) $('histHeadwayCard').hidden = !showHeadway || !$('histHeadwayCheck')?.checked;
  setMetricElementVisible('statRisk', showTtc || showCollision);
  setMetricElementVisible('accidentRateChart', showCollision);
  setMetricElementVisible('accidentVarianceChart', showCollision);
  setMetricElementVisible('statViolationRate', showViolation);
  setMetricElementVisible('violationRateChart', showViolation);
  setMetricElementVisible('statArrivalRate', showArrival);
  setMetricElementVisible('arrivalRateChart', showArrival);
}

async function loadMaps() {
  try {
    const backendModel = $('trafficModelSelect')?.value || 'cnde';
    const mapsGet = appMode === 'generate' && managerBase ? managerGet : apiGet;
    const res = await mapsGet(`/maps?backend_model=${encodeURIComponent(backendModel)}`);
    const sel = $('mapSelect'); sel.innerHTML = '';
    (res.maps || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m; opt.textContent = m.split('/').pop(); sel.appendChild(opt);
    });
    if ((res.maps || []).length > 0) {
      $('mapStatusText').textContent = (res.maps[0] || '').split('/').pop();
    } else {
      $('mapStatusText').textContent = '未发现地图文件';
    }
  } catch (e) {
    $('mapStatusText').textContent = activeExperimentId ? '实验后端启动中…' : `地图列表加载失败: ${e.message}`;
    if (!activeExperimentId) showToast(`地图列表加载失败: ${e.message}`, false);
  }
}

function updateTrafficModelControls() {
  const backendModel = $('trafficModelSelect')?.value || (isReplayLikeMode() ? '' : 'cnde');
  const capability = algorithmCapabilities[backendModel] || {};
  const replayMode = isReplayLikeMode();
  const selectedScenario = !!$('scenarioSelect')?.value;
  const replayRunning = isReplayParamLocked();
  const hasInitModes = capability.init_modes !== false;
  updateInitModeOptions(backendModel || 'cnde');
  const showReplayDetails = !replayMode || selectedScenario;
  ['mapSelect', 'initModeSelect', 'experimentNameStartInput', 'gpuIdInput', 'totalStepInput'].forEach(id => {
    setFormControlVisible(id, showReplayDetails && (id !== 'initModeSelect' || hasInitModes));
  });
  if ($('runDurationModeGroup')) $('runDurationModeGroup').hidden = appMode !== 'generate';
  if ($('initDataGroup')) $('initDataGroup').hidden = replayMode || !capability.init_data;
  if ($('mapLockHint')) $('mapLockHint').hidden = replayMode || !showReplayDetails;
  const showArrivalBlock = !replayMode ? capability.arrival_rate !== false : selectedScenario;
  setControlBlockVisible('laneIdInput', showArrivalBlock);
  if (replayMode) {
    if ($('arrivalRateInput')) $('arrivalRateInput').disabled = true;
    if ($('applyArrivalRateBtn')) $('applyArrivalRateBtn').hidden = true;
  } else {
    if ($('arrivalRateInput')) $('arrivalRateInput').disabled = false;
    if ($('applyArrivalRateBtn')) $('applyArrivalRateBtn').hidden = false;
  }
  setControlBlockVisible('clickMode', capability.vehicle_ops !== false);
  if ($('startPlaybackBtn')) $('startPlaybackBtn').hidden = appMode !== 'replay';
  if ($('startOfflineTestBtn')) $('startOfflineTestBtn').hidden = appMode !== 'offline';
  if ($('replayBlock')) $('replayBlock').hidden = !isReplayLikeMode();
  if ($('dataManagerBtn')) $('dataManagerBtn').hidden = true;
  if ($('trafficModelSelect')) $('trafficModelSelect').disabled = replayRunning;
  if ($('scenarioSelect')) $('scenarioSelect').disabled = replayRunning;
  if ($('scenarioSearchInput')) $('scenarioSearchInput').disabled = replayRunning;
  setMapLocked(mapLocked);
  applyMetricCapabilities(capability);
  if (hasInitModes) updateInitModeControls();
  updateAvAccessControls();
  updateCarlaConfigControls();
  updateDenseWorldControls();
  updateMixedTrafficControls();
}

function updateMixedTrafficControls() {
  const supported = appMode === 'generate' && ($('trafficModelSelect')?.value || 'cnde') === 'cnde';
  const locked = (lastStatus?.run_state || runState || 'idle') !== 'idle';
  const enabled = supported && !!$('mixedTrafficToggle')?.checked;
  if ($('mixedTrafficBlock')) $('mixedTrafficBlock').hidden = !supported;
  if ($('mixedTrafficToggle')) $('mixedTrafficToggle').disabled = locked || !supported;
  ['cyclistRatioSelect', 'pedestrianDensitySelect', 'vehicleSizeModeSelect', 'initialSpeedModeSelect'].forEach(id => {
    if ($(id)) $(id).disabled = locked || !enabled;
  });
}

function updateCarlaConfigControls() {
  const enabled = !!$('carla3dToggle')?.checked;
  const supported = ['cnde', 'neuralnde'].includes($('trafficModelSelect')?.value || 'cnde');
  const locked = appMode !== 'generate' || (lastStatus?.run_state || runState) !== 'idle';
  if ($('carla3dToggle')) $('carla3dToggle').disabled = locked || !supported;
  if ($('carla3dOptions')) $('carla3dOptions').hidden = !enabled || !supported;
  ['carlaQualitySelect', 'carlaGpuInput'].forEach(id => {
    if ($(id)) $(id).disabled = locked || !enabled || !supported;
  });
}

function updateRunDurationControls() {
  const locked = (lastStatus?.run_state || runState || 'idle') !== 'idle';
  const unlimited = !!$('runUntilStoppedToggle')?.checked;
  if ($('runUntilStoppedToggle')) $('runUntilStoppedToggle').disabled = locked || appMode !== 'generate';
  if ($('totalStepInput')) $('totalStepInput').disabled = locked || unlimited || appMode !== 'generate';
  if ($('scenarioCountInput')) {
    if (unlimited) $('scenarioCountInput').value = '1';
    $('scenarioCountInput').disabled = locked || unlimited || appMode !== 'generate';
  }

  const denseWorldEnabled = appMode === 'generate'
    && ['cnde', 'neuralnde'].includes($('trafficModelSelect')?.value || 'cnde')
    && $('multimodalModelSelect')?.value === 'denseworld';
  const customWorldDuration = $('worldDurationSelect')?.value === 'custom';
  if ($('worldCustomDurationGroup')) $('worldCustomDurationGroup').hidden = !denseWorldEnabled || !customWorldDuration;
  if ($('worldCustomDurationInput')) {
    $('worldCustomDurationInput').disabled = locked || !denseWorldEnabled || !customWorldDuration;
  }
}

function updateDenseWorldControls() {
  const select = $('multimodalModelSelect');
  const supported = ['cnde', 'neuralnde'].includes($('trafficModelSelect')?.value || 'cnde') && appMode === 'generate';
  const locked = (lastStatus?.run_state || runState || 'idle') !== 'idle';
  if (!supported && select) select.value = 'none';
  if (select) select.disabled = locked || !supported;
  const enabled = supported && select?.value === 'denseworld';
  if (enabled && $('initModeSelect')?.value === 'random_tl_only') {
    $('initModeSelect').value = 'random';
    updateInitModeControls();
  }
  if ($('denseWorldConfig')) $('denseWorldConfig').hidden = !enabled;
  if ($('worldSeedModeSelect')) $('worldSeedModeSelect').value = 'multiview_quality';
  ['worldDurationSelect', 'worldCustomDurationInput', 'worldTransferStepsSelect', 'worldSeedModeSelect', 'worldSeedRadiusSelect', 'worldSeedImageInput', 'worldTransferFullToggle', 'worldDreamsToggle', 'worldPromptInput'].forEach(id => {
    if ($(id)) $(id).disabled = locked || !enabled;
  });
  if ($('worldSeedModeSelect')) $('worldSeedModeSelect').disabled = true;
  if ($('worldSeedImageInput')) {
    $('worldSeedImageInput').value = '';
    $('worldSeedImageInput').disabled = true;
  }
  updateRunDurationControls();
}

function updateAvAccessControls() {
  const enabled = !!$('avAccessToggle')?.checked;
  const model = $('avControlModelSelect')?.value || 'DEFAULT_TCP';
  const externalLike = ['EXTERNAL_TCP', 'VTD_TCP', 'LEAD_TFV6_STREAM'].includes(model);
  const vtd = model === 'VTD_TCP';
  const state = lastStatus?.run_state || runState || 'idle';
  const locked = appMode === 'replay' || state !== 'idle';
  const backendModel = $('trafficModelSelect')?.value || 'cnde';
  const onlineCnde = appMode === 'generate' && ['cnde', 'neuralnde'].includes(backendModel);
  if ($('avAccessToggle')) $('avAccessToggle').disabled = locked;
  if ($('avControlModelSelect')) $('avControlModelSelect').disabled = locked || !enabled;
  if ($('avTcpParamGroup')) $('avTcpParamGroup').hidden = !enabled || !externalLike;
  if ($('vtdParamGroup')) $('vtdParamGroup').hidden = !enabled || !vtd;
  if ($('avOnlineSelectionGroup')) $('avOnlineSelectionGroup').hidden = !enabled || !onlineCnde;
  if ($('avCommandModeGroup')) $('avCommandModeGroup').hidden = !enabled || !externalLike || !onlineCnde;
  ['avSelectionModeSelect', 'avCommandModeSelect'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = locked || !enabled;
  });
  ['avControlHostInput', 'avControlPortInput'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = locked || !enabled || !externalLike;
  });
  ['vtdBridgeHostInput', 'vtdBridgePortInput'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = locked || !enabled || !vtd;
  });
}

function renderOnlineAvState(status = {}) {
  const waiting = appMode === 'experiment' && !!status.waiting_for_av_selection;
  const prompt = $('avSelectionPrompt');
  if (prompt) prompt.hidden = !waiting;
  const selected = selectedVehicleId || status.av_id || '';
  if ($('avSelectionValue')) {
    $('avSelectionValue').textContent = selected ? `${t('av.selected')}: ${selected}` : t('av.noSelection');
  }
  if ($('confirmSelectAvBtn')) $('confirmSelectAvBtn').disabled = !waiting || !selected;
  const endpoint = String(status.av_control_endpoint || '');
  if ($('avEndpointBlock')) $('avEndpointBlock').hidden = !endpoint;
  if ($('avEndpointValue')) $('avEndpointValue').textContent = endpoint || '--';
  if ($('avConnectionState')) {
    $('avConnectionState').textContent = status.av_connected ? t('av.connected') : t('av.disconnected');
    $('avConnectionState').classList.toggle('text-success', !!status.av_connected);
  }
  const perceptions = Math.max(0, Number(status.av_perception_frame_count || 0));
  const commands = Math.max(0, Number(status.av_command_frame_count || 0));
  const timeouts = Math.max(0, Number(status.av_command_timeout_count || 0));
  const latency = Number(status.av_command_latency_ms);
  if ($('avTelemetry')) $('avTelemetry').hidden = !endpoint && perceptions === 0;
  if ($('avCommandFrames')) $('avCommandFrames').textContent = `${commands} / ${perceptions}`;
  if ($('avTimeoutFrames')) $('avTimeoutFrames').textContent = String(timeouts);
  if ($('avLatencyValue')) $('avLatencyValue').textContent = Number.isFinite(latency) ? `${latency.toFixed(1)} ms` : '--';
}

async function loadScenarios() {
  try {
    const requestedScenario = $('scenarioSelect')?.value || new URL(window.location.href).searchParams.get('scenario') || '';
    let records = [];
    const scenarioGet = activeExperimentId && managerBase ? managerGet : apiGet;
    try {
      const res = await scenarioGet('/data/scenarios');
      records = res.records || [];
    } catch (_) {
      const res = await scenarioGet('/scenarios');
      records = (res.scenarios || []).map(path => ({ path, replayable: true, algorithm: 'citynde', kind: 'scenario_pkl' }));
    }
    dataRecordByPath = new Map(records.map(record => [String(record.path || record), record]));
    const sel = $('scenarioSelect'); sel.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— 请选择场景文件 —';
    sel.appendChild(placeholder);
    const initSel = $('initDataSelect'); if (initSel) initSel.innerHTML = '';
    const selectedModel = $('trafficModelSelect')?.value || '';
    const search = ($('scenarioSearchInput')?.value || '').trim().toLowerCase();
    const filtered = records.filter(record => {
      const path = String(record.path || record);
      if (selectedModel && recordAlgorithmValue(record) !== selectedModel) return false;
      if (search && !path.toLowerCase().includes(search)) return false;
      return true;
    });
    filtered.forEach(record => {
      const s = record.path || record;
      const replayable = record.replayable !== false;
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = replayable ? `[${record.algorithm || 'data'}] ${s.split('/').pop()}` : `[${record.algorithm || 'output'} 暂不支持回放] ${s.split('/').pop()}`;
      opt.disabled = !replayable;
      sel.appendChild(opt);
      if (initSel && replayable && String(record.kind || 'scenario_pkl') === 'scenario_pkl') {
        const initOpt = document.createElement('option');
        initOpt.value = s; initOpt.textContent = s.split('/').pop(); initSel.appendChild(initOpt);
      }
    });
    const requestedRecord = requestedScenario ? dataRecordByPath.get(requestedScenario) : null;
    const requestedVisible = !!requestedScenario
      && (!selectedModel || !requestedRecord || recordAlgorithmValue(requestedRecord) === selectedModel)
      && (!search || requestedScenario.toLowerCase().includes(search));
    if (requestedVisible) {
      ensureScenarioOption(requestedScenario);
      if (Array.from(sel.options).some(opt => opt.value === requestedScenario && !opt.disabled)) {
        sel.value = requestedScenario;
      }
    }
    syncReplaySelectionMetadata();
  } catch (_) {}
}

function recordAlgorithmValue(record) {
  return 'cnde';
}

function updateTransferReplayRange(record = null, reset = false) {
  const startInput = $('transferReplayStartInput');
  const endInput = $('transferReplayEndInput');
  const button = $('generateTransferReplayBtn');
  const hint = $('transferReplayRangeHint');
  if (!startInput || !endInput || !button || !hint) return;
  const supported = !!record
    && recordAlgorithmValue(record) === 'cnde'
    && String(record.kind || 'scenario_pkl') === 'scenario_pkl';
  button.disabled = !supported;
  const totalStep = Math.max(0, Number(record?.total_step || 0));
  const resolution = Math.max(0.001, Number(record?.sim_resolution || 0.1));
  if (reset && supported) {
    startInput.value = '0';
    endInput.value = String(Math.max(1, Math.min(totalStep || 150, Math.round(15 / resolution))));
  }
  const start = Math.max(0, Math.trunc(Number(startInput.value) || 0));
  const end = Math.max(0, Math.trunc(Number(endInput.value) || 0));
  const duration = Math.max(0, (end - start) * resolution);
  const totalText = totalStep > 0 ? ` · 0–${totalStep}` : '';
  hint.textContent = `${t('replay.frameRangeHint')} ${duration.toFixed(1)} s${totalText}`;
}

function syncReplaySelectionMetadata() {
  const sel = $('scenarioSelect');
  const path = sel?.value || '';
  const record = dataRecordByPath.get(path);
  if (!record) {
    if ($('arrivalRateInput')) {
      $('arrivalRateInput').value = ['replay', 'offline'].includes(appMode)
        ? ''
        : pendingDefaultArrivalRate.toFixed(3);
    }
    if (appMode === 'offline') {
      offlineAvId = null;
      offlinePreviewScenario = '';
      selectedVehicleId = null;
      simData = null;
      requestDrawFrame();
    }
    updateTrafficModelControls();
    updateTransferReplayRange(null);
    return;
  }
  const model = recordAlgorithmValue(record);
  const modelSelect = $('trafficModelSelect');
  const applyMapPath = () => {
    const mapSelect = $('mapSelect');
    if (mapSelect && record.map_path) {
      ensureSelectOption('mapSelect', record.map_path, String(record.map_path).split('/').pop());
      mapSelect.value = record.map_path;
    }
  };
  if (modelSelect && modelSelect.value !== model) {
    modelSelect.value = model;
    updateTrafficModelControls();
    loadMaps().then(applyMapPath).catch(applyMapPath);
  } else {
    applyMapPath();
  }
  const rate = record.arrival_rate ?? record.replay_arrival_rate ?? null;
  if ($('arrivalRateInput')) $('arrivalRateInput').value = rate == null ? '' : Number(rate).toFixed(3);
  updateTransferReplayRange(record, true);
  updateTrafficModelControls();
  if (appMode === 'offline') scheduleOfflinePreview();
}

async function startTransferReplayGeneration() {
  const scenario = $('scenarioSelect')?.value || '';
  const record = dataRecordByPath.get(scenario);
  if (!scenario || !record || recordAlgorithmValue(record) !== 'cnde') {
    showToast('请选择 CityNDE 回放文件', false);
    return;
  }
  const startStep = Math.max(0, Math.trunc(Number($('transferReplayStartInput')?.value) || 0));
  const endStep = Math.max(0, Math.trunc(Number($('transferReplayEndInput')?.value) || 0));
  if (endStep <= startStep) {
    showToast('结束帧必须大于起始帧', false);
    return;
  }
  const resolution = Math.max(0.001, Number(record.sim_resolution || 0.1));
  if ((endStep - startStep) * resolution > 15.000001) {
    showToast('Transfer 回放片段最长为 15 秒', false);
    return;
  }
  const button = $('generateTransferReplayBtn');
  button.disabled = true;
  try {
    const result = await managerPost('/action', {
      type: 'start_transfer_replay',
      scenario,
      start_step: startStep,
      end_step: endStep,
      world_transfer_steps: Math.max(1, parseInt($('transferReplayStepsSelect')?.value || '35', 10) || 35),
      transfer_view_mode: $('transferReplayViewSelect')?.value === 'multiview' ? 'multiview' : 'front',
      world_seed_image: $('worldSeedImageInput')?.value?.trim() || undefined,
      world_prompt: $('worldPromptInput')?.value?.trim() || undefined,
    });
    if (result?.ok === false) throw new Error(result.error || 'unknown');
    showToast('Transfer 回放任务已启动', true);
    openViewer(result.experiment || result.viewer_url, 'experiment');
  } catch (error) {
    showToast(`${t('toast.actionFail')}: ${error.message}`, false);
    throw error;
  } finally {
    button.disabled = false;
  }
}

function scheduleOfflinePreview() {
  setTimeout(() => {
    startOfflinePreviewForSelectedScenario().catch(() => {});
  }, 0);
}

async function startOfflinePreviewForSelectedScenario() {
  if (appMode !== 'offline' || offlinePreviewBusy) return;
  const select = $('scenarioSelect');
  const scenario = select?.value || '';
  if (!scenario || select?.selectedOptions?.[0]?.disabled) return;
  const state = lastStatus?.run_state || runState || 'idle';
  if (state !== 'idle') return;
  if (offlinePreviewScenario === scenario && simData?.vehicles?.length) return;
  offlinePreviewBusy = true;
  try {
    offlinePreviewScenario = scenario;
    offlineAvId = null;
    selectedVehicleId = null;
    simData = null;
    replayMetrics = null;
    replayTotalSteps = 0;
    replayCurrentStep = 0;
    replayAutoplayPending = false;
    requestDrawFrame();
    const res = await sendAction(offlineActionPayload('start_offline_preview', scenario));
    if (res?.viewer_url || res?.experiment?.port) {
      openViewer(res.experiment || res.viewer_url, 'offline');
      return;
    }
    if (res?.sim_state) {
      applyReplaySeekResult(res, 0);
    } else {
      await replaySeek(0);
    }
  } finally {
    offlinePreviewBusy = false;
  }
}

async function refreshScenariosForSelectedModel() {
  const current = $('scenarioSelect')?.value || '';
  await loadScenarios();
  if (current && Array.from($('scenarioSelect')?.options || []).some(opt => opt.value === current && !opt.disabled)) {
    $('scenarioSelect').value = current;
  }
  syncReplaySelectionMetadata();
}

function updateInitModeControls() {
  const mode = $('initModeSelect')?.value || 'random_tl_only';
  const backendModel = $('trafficModelSelect')?.value || 'cnde';
  const needsData = backendModel === 'cnde' && (mode === 'data' || mode === 'data_random_tl');
  const group = $('initDataGroup');
  if (group) group.hidden = !needsData;
}

function clampArrivalRate(value) {
  if (value == null || (typeof value === 'string' && value.trim() === '')) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(1, n));
}

function rememberArrivalRate(lane, rate) {
  const normalizedLane = String(lane || 'all').trim() || 'all';
  const clamped = clampArrivalRate(rate);
  if (clamped == null) return false;
  if (normalizedLane.toLowerCase() === 'all') {
    pendingDefaultArrivalRate = clamped;
    pendingLaneArrivalRates = {};
  } else {
    pendingLaneArrivalRates[normalizedLane] = clamped;
  }
  $('statArrivalRate').textContent = pendingDefaultArrivalRate.toFixed(3);
  return true;
}

function currentArrivalRatePayload() {
  const inputRate = clampArrivalRate($('arrivalRateInput')?.value);
  if (inputRate != null && Object.keys(pendingLaneArrivalRates).length === 0) {
    pendingDefaultArrivalRate = inputRate;
  }
  return {
    arrival_rate: pendingDefaultArrivalRate,
    arrival_rates: { ...pendingLaneArrivalRates },
  };
}

function ensureScenarioOption(path) {
  const sel = $('scenarioSelect');
  if (!sel || !path) return;
  const exists = Array.from(sel.options).some(opt => opt.value === path);
  if (!exists) {
    const opt = document.createElement('option');
    opt.value = path;
    opt.textContent = String(path).split('/').pop();
    sel.appendChild(opt);
  }
  sel.value = path;
}

async function loadReplayMetrics() {
  if (!currentDetailMode()) return;
  if (runState === 'idle' && !replayMetrics && appMode !== 'experiment' && !isReplayLikeMode()) return;
  if (metricsFetchBusy) return;
  metricsFetchBusy = true;
  try {
    const params = new URLSearchParams();
    if (metricsLoadedUntil > 0) {
      params.set('since', String(metricsLoadedUntil));
    } else {
      const observedSteps = Number(lastStatus.replay_total_steps || lastStatus.total_step || lastStatus.step || 0);
      if (runState === 'running' && observedSteps > METRICS_INITIAL_FULL_LIMIT) {
        params.set('tail', String(METRICS_INITIAL_FULL_LIMIT));
      } else {
        params.set('since', '0');
      }
    }
    const query = params.toString();
    const res = await apiGet(`/metrics${query ? `?${query}` : ''}`);
    if (res.ok) {
      mergeReplayMetrics(res);
      scheduleChartUpdate(runState === 'playback' && replayPlaying ? PLAYBACK_CHART_UPDATE_MS : 1000);
    }
  } catch (_) {
  } finally {
    lastMetricsFetchAt = performance.now();
    metricsFetchBusy = false;
  }
}

function mergeReplayMetrics(res) {
  const start = Number(res.start_step);
  if (Number.isFinite(start)) {
    const merged = replayMetrics && typeof replayMetrics === 'object' ? { ...replayMetrics } : {};
    Object.entries(res).forEach(([key, value]) => {
      if (key !== 'ok' && key !== 'start_step' && !Array.isArray(value)) merged[key] = value;
    });
    METRIC_ARRAY_KEYS.forEach(key => {
      if (!Array.isArray(res[key])) return;
      const arr = Array.isArray(merged[key]) ? merged[key].slice() : [];
      while (arr.length < start) arr.push(null);
      res[key].forEach((value, idx) => { arr[start + idx] = value; });
      merged[key] = arr;
    });
    merged.ok = true;
    replayMetrics = merged;
  } else {
    replayMetrics = res;
  }
  const lengths = METRIC_ARRAY_KEYS.map(key => Array.isArray(replayMetrics?.[key]) ? replayMetrics[key].length : 0);
  metricsLoadedUntil = Math.max(
    metricsLoadedUntil,
    Number(replayMetrics?.computed_steps || 0),
    ...lengths,
  );
}

// ── Replay ────────────────────────────────────────────────────────────────────
function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total - h * 3600 - m * 60;
  const ss = s.toFixed(1).padStart(4, '0');
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${ss}`;
  if (m > 0) return `${m}:${ss}`;
  return `${s.toFixed(1)}s`;
}

function updateReplaySlider() {
  const slider = $('replaySlider');
  slider.max = Math.max(0, replayTotalSteps - 1);
  if (String(slider.value) !== String(replayCurrentStep)) slider.value = replayCurrentStep;
  const cur = formatDuration(replayCurrentStep * replayStepSeconds);
  const total = formatDuration(Math.max(0, replayTotalSteps - 1) * replayStepSeconds);
  $('replayStepLabel').textContent = `${cur} / ${total}`;
}

function replaySeekOptions(target) {
  const includeHistory = !!$('showPastTrajectoryToggle')?.checked;
  const includeFuture = !!$('showFutureTrajectoryToggle')?.checked;
  const selectedOnly = !!$('selectedTrajectoryOnlyToggle')?.checked && selectedVehicleId != null;
  const historySeconds = Math.max(0.5, parseFloat($('historyDurationInput')?.value) || 3.0);
  const lightweightPlayback = replayPlaying && !replaySliderDragging;
  return {
    include_history: lightweightPlayback ? false : includeHistory,
    include_future: lightweightPlayback ? false : includeFuture,
    history_seconds: historySeconds,
    future_seconds: Math.max(3.0, historySeconds),
    selected_vehicle_id: selectedOnly ? selectedVehicleId : null,
    compute_safety: !lightweightPlayback && !replaySliderDragging,
  };
}

function applyReplaySeekResult(res, fallbackStep) {
  if (!res || res.loading || res.stale) return;
  if (res.total_steps != null) replayTotalSteps = Number(res.total_steps) || replayTotalSteps;
  replayCurrentStep = Number(res.step ?? res.replay_step ?? fallbackStep ?? replayCurrentStep);
  replayStepSeconds = Number(res.step_seconds || replayStepSeconds || 0.1);
  updateReplaySlider();
  upsertMetricSample({
    ...res,
    step: replayCurrentStep,
    replay_step_seconds: replayStepSeconds,
  });
  if (res.sim_state && res.sim_state.ok !== false) {
    simData = applyOfflineAvToSimState(res.sim_state);
    updateVehicleIdOptions();
    if (followSelectedVehicle) centerOnSelectedVehicle();
    requestDrawFrame();
    updateSelectedVehiclePanel();
  }
  scheduleChartUpdate(replayPlaying ? PLAYBACK_CHART_UPDATE_MS : 600);
}

async function replaySeek(step) {
  const scenario = $('scenarioSelect').value;
  if (!scenario) return;
  const target = Math.max(0, Math.min(Number(step) || 0, Math.max(0, replayTotalSteps - 1)));
  const options = replaySeekOptions(target);
  if (replaySeekBusy) {
    replaySeekPending = { step: target };
    return;
  }
  replaySeekBusy = true;
  try {
    const res = await sendAction({ type: 'replay_seek', scenario, step: target, ...options });
    applyReplaySeekResult(res, target);
  } catch (_) {
  } finally {
    replaySeekBusy = false;
    if (replaySeekPending != null && replaySeekPending.step !== replayCurrentStep) {
      const pending = replaySeekPending.step;
      replaySeekPending = null;
      replaySeek(pending);
    } else {
      replaySeekPending = null;
    }
  }
}

function scheduleReplaySeek(step, delay = 80) {
  if (replaySeekDebounce) clearTimeout(replaySeekDebounce);
  replaySeekDebounce = setTimeout(() => {
    replaySeekDebounce = null;
    replaySeek(step);
  }, Math.max(0, delay));
}

function resetReplayClock() {
  replayClockBaseStep = Number(replayCurrentStep) || 0;
  replayClockBaseTime = performance.now();
}

function hydrateReplayTotalSteps() {
  if (replayTotalSteps > 1) return replayTotalSteps;
  const sliderMax = Number($('replaySlider')?.max);
  const candidates = [
    lastStatus?.replay_total_steps,
    lastStatus?.total_step,
    replayMetrics?.total_steps,
    Number.isFinite(sliderMax) ? sliderMax + 1 : 0,
  ].map(value => Number(value)).filter(value => Number.isFinite(value) && value > 1);
  if (candidates.length) {
    replayTotalSteps = Math.max(...candidates);
    updateReplaySlider();
  }
  return replayTotalSteps;
}

async function runReplayLoop(token) {
  if (!replayPlaying || token !== replayLoopToken) return;
  if (runState !== 'playback') { stopReplayAutoPlay(); return; }
  hydrateReplayTotalSteps();
  if (replayTotalSteps <= 1) {
    loadReplayMetrics();
    replayTimer = setTimeout(() => { runReplayLoop(token); }, 500);
    return;
  }
  if (replayCurrentStep >= replayTotalSteps - 1) { stopReplayAutoPlay(); return; }
  const elapsedSeconds = Math.max(0, (performance.now() - replayClockBaseTime) / 1000);
  const stepsFloat = elapsedSeconds * Math.max(replaySpeed, 0.01) / Math.max(replayStepSeconds, 1e-6);
  const elapsedSteps = Math.floor(stepsFloat);
  if (elapsedSteps < 1) {
    const secondsUntilNext = ((1 - stepsFloat) * replayStepSeconds) / Math.max(replaySpeed, 0.01);
    const delay = Math.max(16, Math.round(secondsUntilNext * 1000));
    replayTimer = setTimeout(() => { runReplayLoop(token); }, delay);
    return;
  }
  const targetStep = Math.min(replayTotalSteps - 1, replayClockBaseStep + elapsedSteps);
  if (targetStep > replayCurrentStep) await replaySeek(targetStep);
  if (!replayPlaying || token !== replayLoopToken) return;
  if (replayCurrentStep >= replayTotalSteps - 1) { stopReplayAutoPlay(); return; }
  const targetInterval = Math.max(16, Math.round((replayStepSeconds * 1000) / Math.max(replaySpeed, 0.01)));
  const delay = Math.max(0, targetInterval);
  replayTimer = setTimeout(() => { runReplayLoop(token); }, delay);
}

async function startReplayAutoPlay() {
  if (replayPlaying) return;
  if (runState !== 'playback') return;
  if (lastStatus) lastStatus.paused = false;
  hydrateReplayTotalSteps();
  if (replayTotalSteps > 0 && replayCurrentStep >= replayTotalSteps - 1) {
    replaySeekPending = null;
    await replaySeek(0);
  }
  const playIcon = el => el.querySelector('i').className = 'bi bi-pause-fill';
  playIcon($('replayPlayBtn')); playIcon($('tlPlayBtn'));
  replayPlaying = true;
  resetReplayClock();
  replayLoopToken += 1;
  updateButtonStates({ ...(lastStatus || {}), run_state: 'playback', paused: false });
  runReplayLoop(replayLoopToken);
}

function stopReplayAutoPlay() {
  replayLoopToken += 1;
  if (replayTimer) { clearTimeout(replayTimer); replayTimer = null; }
  if (replaySeekDebounce) { clearTimeout(replaySeekDebounce); replaySeekDebounce = null; }
  replayPlaying = false;
  replayAutoplayPending = false;
  safeSetIcon('replayPlayBtn', 'bi bi-play-fill');
  safeSetIcon('tlPlayBtn', 'bi bi-play-fill');
}

async function toggleReplayPlay() {
  if (replayPlaying) {
    stopReplayAutoPlay();
    if (runState === 'playback') {
      try { await apiPost('/pause'); } catch (_) {}
      if (lastStatus) lastStatus.paused = true;
      await replaySeek(replayCurrentStep);
      loadReplayMetrics();
      scheduleChartUpdate(0);
    }
  } else {
    if (runState === 'playback' && lastStatus.paused) {
      try { await apiPost('/resume'); } catch (_) {}
    }
    if (lastStatus) lastStatus.paused = false;
    startReplayAutoPlay();
  }
}

// ── Window management ─────────────────────────────────────────────────────────
function initWindowManagement() {
  document.querySelectorAll('.window-min-btn, .window-max-btn').forEach(btn => { btn.hidden = true; });
  document.querySelectorAll('.window-card').forEach(win => {
    win.classList.remove('minimized', 'maximized', 'dragging');
    win.removeAttribute('style');
  });
}

// ── Zoom & pan ────────────────────────────────────────────────────────────────
function initZoomControls() {
  $('zoomInBtn').addEventListener('click', () => { zoom = Math.min(zoom * 1.35, MAX_ZOOM); requestDrawFrame(); });
  $('zoomOutBtn').addEventListener('click', () => { zoom = Math.max(zoom / 1.25, 0.05); requestDrawFrame(); });
  $('zoomResetBtn').addEventListener('click', fitFrame);
  const canvas = $('trafficCanvas');
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
    const nz = Math.max(0.05, Math.min(zoom * factor, MAX_ZOOM));
    panX = mx - (mx - panX) * (nz / zoom); panY = my - (my - panY) * (nz / zoom);
    zoom = nz; requestDrawFrame();
  }, { passive: false });
  canvas.addEventListener('mousemove', e => {
    updateCoordReadout(e);
  });
  canvas.addEventListener('mouseleave', () => {
    const el = $('coordReadout');
    if (el) el.textContent = 'X: --, Y: --';
  });
  canvas.addEventListener('mousedown', e => {
    if (e.button !== 0 || $('clickMode').value !== 'none') return;
    isPanning = true; canvas.classList.add('dragging');
    panStartX = e.clientX; panStartY = e.clientY; panStartTx = panX; panStartTy = panY;
  });
  document.addEventListener('mousemove', e => {
    if (!isPanning) return;
    panX = panStartTx + (e.clientX - panStartX); panY = panStartTy + (e.clientY - panStartY); requestDrawFrame();
  });
  document.addEventListener('mouseup', () => { if (isPanning) { isPanning = false; $('trafficCanvas').classList.remove('dragging'); } });
}

function updateCoordReadout(e) {
  const el = $('coordReadout');
  if (!el) return;
  const canvas = $('trafficCanvas');
  const rect = canvas.getBoundingClientRect();
  const vx = (e.clientX - rect.left - panX) / Math.max(zoom, 1e-6);
  const vy = (e.clientY - rect.top - panY) / Math.max(zoom, 1e-6);
  const world = virtualToWorld(vx, vy);
  el.textContent = `X: ${world.x.toFixed(2)}, Y: ${world.y.toFixed(2)}`;
}

// ── Canvas click ──────────────────────────────────────────────────────────────
function initCanvasClick() {
  $('trafficCanvas').addEventListener('click', async e => {
    const canvas = $('trafficCanvas');
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const sz = virtualSize();
    const vx = (clickX - panX) / zoom;
    const vy = (clickY - panY) / zoom;
    const nx = vx / Math.max(sz.w, 1);
    const ny = vy / Math.max(sz.h, 1);
    const world = virtualToWorld(vx, vy);

    const regionMode = $('regionMode').value;
    if (regionMode !== 'none') {
      applyInfeasibleRegion(regionMode, nx, ny);
      return;
    }

    const mode = $('clickMode').value;
    if (mode === 'none') {
      const picked = vehicleAtWorld(world.x, world.y);
      if (picked) selectedVehicleId = picked.id;
      else if (!followSelectedVehicle) selectedVehicleId = null;
      focusCarlaVehicle(selectedVehicleId);
      if (appMode === 'offline' && picked) {
        offlineAvId = picked.id;
        if (simData) simData = applyOfflineAvToSimState(simData);
      }
      updateSelectedVehiclePanel();
      if (runState === 'playback' && $('selectedTrajectoryOnlyToggle')?.checked) scheduleReplaySeek(replayCurrentStep, 0);
      requestDrawFrame();
      return;
    }
    if (mode === 'delete') {
      const picked = vehicleAtWorld(world.x, world.y);
      if (picked) setDeleteCandidate(picked);
      else setVehicleOpHint('点击位置附近没有车辆，请放大后点击车辆中心，或直接输入车辆ID。');
      return;
    }
    if (mode === 'add') {
      if (!pendingVehicleOp || pendingVehicleOp.type !== 'add' || pendingVehicleOp.stage >= 2) setAddFirstPoint(world);
      else setAddSecondPoint(world);
    }
  });
}

function applyInfeasibleRegion(mode, nx, ny) {
  if (!isFinite(nx) || !isFinite(ny)) return;
  const radius = Math.max(1, parseFloat($('regionRadiusInput').value) || 10);
  if (mode === 'clear') {
    infeasibleRegions = infeasibleRegions.filter(r => Math.hypot(r.nx - nx, r.ny - ny) > 0.04);
  } else {
    infeasibleRegions.push({ nx, ny, radius, created_at: new Date().toISOString() });
  }
  requestDrawFrame();
  sendAction({ type: mode === 'clear' ? 'clear_infeasible_region' : 'set_infeasible_region', x: nx, y: ny, radius })
    .catch(() => {});
}

function formatBytes(bytes) {
  const n = Number(bytes);
  if (!isFinite(n) || n <= 0) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function hasTextSelectionWithin(rootId) {
  const root = $(rootId);
  const sel = window.getSelection?.();
  if (!root || !sel || sel.isCollapsed || sel.rangeCount === 0) return false;
  const node = sel.anchorNode;
  const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
  return !!element && root.contains(element);
}

function shouldHoldExperimentRender() {
  return performance.now() < experimentsSelectionHoldUntil || hasTextSelectionWithin('experimentsView');
}

function progressPercent(recordOrStatus) {
  const explicit = Number(recordOrStatus?.progress);
  if (Number.isFinite(explicit)) return Math.max(0, Math.min(100, explicit * (explicit <= 1 ? 100 : 1)));
  const state = recordOrStatus?.run_state || runState;
  if (state === 'completed') return 100;
  const total = Number(recordOrStatus?.total_step ?? recordOrStatus?.total_steps ?? recordOrStatus?.replay_total_steps);
  const step = Number(recordOrStatus?.replay_step ?? recordOrStatus?.step);
  if (Number.isFinite(total) && total > 0 && Number.isFinite(step)) {
    return Math.max(0, Math.min(100, step / total * 100));
  }
  return null;
}

function formatProgress(recordOrStatus) {
  const state = recordOrStatus?.run_state || runState;
  if (recordOrStatus?.run_until_stopped && !['completed', 'error', 'stopped', 'interrupted'].includes(state)) {
    return t('status.openEnded');
  }
  const pct = progressPercent(recordOrStatus);
  if (pct == null) return '-';
  const kind = recordOrStatus?.kind || (state === 'playback' || state === 'playback_loading' ? 'replay' : 'experiment');
  const displayPct = !isReplayLikeKind(kind) && state !== 'completed' && pct >= 100 ? 99.9 : pct;
  return `${displayPct.toFixed(1)}%`;
}

function formatSimTime(recordOrStatus) {
  const explicit = Number(recordOrStatus?.sim_time);
  if (Number.isFinite(explicit)) return formatDuration(explicit);
  const step = Number(recordOrStatus?.replay_step ?? recordOrStatus?.step);
  const secondsPerStep = Number(recordOrStatus?.replay_step_seconds || recordOrStatus?.sim_resolution || simStepSeconds || 0.1);
  if (!Number.isFinite(step)) return '-';
  return formatDuration(step * Math.max(secondsPerStep, 1e-6));
}

function experimentStateLabel(record) {
  if (record.paused) return t('status.paused');
  const state = String(record.run_state || 'idle');
  if (state === 'running' || state === 'playback' || state === 'playback_loading') return t('status.running');
  if (state === 'completed' || state === 'stopped') return isReplayLikeKind(record.kind) ? t('status.idle') : t('status.completed');
  if (state === 'idle') return t('status.idle');
  return state;
}

function experimentGpuLabel(record) {
  const value = record.gpu_id ?? record.replay_params?.gpu_id;
  return String(value == null || value === '' ? '0' : value);
}

function currentSingleExperimentRecord() {
  if (!lastStatus || !lastStatus.run_state || lastStatus.run_state === 'idle') return null;
  const isReplay = lastStatus.run_state === 'playback' || lastStatus.run_state === 'playback_loading' || isReplayLikeMode();
  const offline = appMode === 'offline' || lastStatus.offline_test === true;
  return {
    id: lastStatus.experiment_id || 'current',
    kind: offline ? 'offline' : (isReplay ? 'replay' : 'experiment'),
    name: lastStatus.experiment_name || 'current',
    run_state: lastStatus.run_state,
    paused: !!lastStatus.paused,
    step: lastStatus.step ?? 0,
    replay_step: lastStatus.replay_step,
    replay_total_steps: lastStatus.replay_total_steps,
    replay_step_seconds: lastStatus.replay_step_seconds,
    sim_resolution: lastStatus.sim_resolution,
    progress: lastStatus.progress,
    total_step: lastStatus.total_step,
    vehicles: lastStatus.vehicles ?? 0,
    init_mode: lastStatus.init_mode || '',
    gpu_id: lastStatus.gpu_id || lastStatus.replay_params?.gpu_id || '4',
    port: new URL(backendBase).port || '',
    url: window.location.href,
    save_file: lastStatus.save_file || '',
    scenario: lastStatus.replay_params?.scenario_path || lastStatus.replay_params?.scenario || '',
  };
}

function reportMetricValue(metric) {
  if (metric?.status !== 'measured' || metric?.value == null) return '未采集';
  const value = typeof metric.value === 'number'
    ? (Number.isInteger(metric.value) ? String(metric.value) : Number(metric.value).toFixed(2))
    : String(metric.value);
  return `${value}${metric.unit ? ` ${metric.unit}` : ''}`;
}

function renderExperimentReport(report) {
  const body = $('experimentReportBody');
  if (!body) return;
  const experiment = report.experiment || {};
  const evaluation = report.evaluation || {};
  const categories = evaluation.categories || {};
  const coverage = evaluation.coverage || {};
  const overall = evaluation.overall_score;
  if ($('experimentReportSubtitle')) {
    $('experimentReportSubtitle').textContent = `${experiment.id || '-'} · ${experiment.workflow_id || '直接启动'} · ${report.generated_at || ''}`;
  }
  const categoryHtml = ['safety', 'comfort', 'efficiency'].map(key => {
    const category = categories[key] || {};
    const metrics = Array.isArray(category.metrics) ? category.metrics : [];
    return `
      <section class="experiment-report-category">
        <div class="experiment-report-category-heading">
          <span><b>${escapeHtml(category.name || key)}</b><small>权重 ${Number(category.weight || 0).toFixed(0)}%</small></span>
          <em>${category.score == null ? '未评分' : `${Number(category.score).toFixed(1)} 分`}</em>
        </div>
        <div class="experiment-report-metrics">
          ${metrics.map(metric => `
            <article class="${metric.status === 'measured' ? '' : 'unavailable'}">
              <span><b>${escapeHtml(metric.name || metric.id || '指标')}</b><small>${escapeHtml(metric.description || '')}</small></span>
              <strong>${escapeHtml(reportMetricValue(metric))}</strong>
              <em>${metric.score == null ? '不参与评分' : `${Number(metric.score).toFixed(1)} 分`}</em>
              <small>${escapeHtml(metric.note || '')}</small>
            </article>`).join('')}
        </div>
      </section>`;
  }).join('');
  const timings = report.execution?.timings || {};
  const batch = report.batch_aggregate || null;
  const batchHtml = batch ? `<section class="experiment-report-execution"><b>串行实验汇总</b><span>${Number(batch.included_experiments || 0)} / ${Number(batch.scenario_count || 0)} 个实验</span><span>综合均分 ${batch.overall_score == null ? '--' : Number(batch.overall_score).toFixed(1)}</span><span>AV 碰撞代理帧 ${Number(batch.metrics?.av_overlap_frames?.value || 0)}</span><span>失败 ${Number(batch.failed_count || 0)}</span></section>` : '';
  const warningHtml = (report.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  body.innerHTML = `
    <div class="experiment-report-summary">
      <div class="experiment-report-score"><small>综合得分</small><b>${overall == null ? '--' : Number(overall).toFixed(1)}</b><em>${evaluation.provisional ? '阶段性报告' : '完整报告'}</em></div>
      <dl><dt>实验名称</dt><dd>${escapeHtml(experiment.name || '-')}</dd><dt>交通模型</dt><dd>${escapeHtml(experiment.backend_model || '-')}</dd><dt>仿真时长</dt><dd>${Number(experiment.sim_time || 0).toFixed(1)} s</dd><dt>指标覆盖</dt><dd>${Number(coverage.measured || 0)} / ${Number(coverage.total || 0)}</dd></dl>
      <dl><dt>测试任务</dt><dd>${escapeHtml(experiment.task_id || 'DW-TASK-0001')}</dd><dt>测试流程</dt><dd>${escapeHtml(experiment.workflow_name || experiment.workflow_id || '直接启动')}</dd><dt>世界模型</dt><dd>${escapeHtml(report.execution?.world_state || '未启用')}</dd><dt>产物数量</dt><dd>${Number(report.execution?.artifact_count || 0)}</dd></dl>
    </div>
    ${categoryHtml}
    ${batchHtml}
    <section class="experiment-report-execution"><b>执行耗时</b><span>场景导出 ${Number(timings.scene_export_seconds || 0).toFixed(2)} s</span><span>控制图 ${Number(timings.control_render_seconds || 0).toFixed(2)} s</span><span>Transfer ${Number(timings.transfer_generation_seconds || 0).toFixed(2)} s</span><span>端到端 ${Number(timings.pipeline_end_to_end_seconds || 0).toFixed(2)} s</span></section>
    ${warningHtml ? `<ul class="experiment-report-warnings">${warningHtml}</ul>` : ''}`;
}

async function openExperimentReport(experimentId) {
  currentExperimentReport = null;
  if ($('downloadExperimentReportBtn')) $('downloadExperimentReportBtn').disabled = true;
  if ($('experimentReportSubtitle')) $('experimentReportSubtitle').textContent = experimentId;
  if ($('experimentReportBody')) $('experimentReportBody').innerHTML = '<div class="scenario-loading">正在生成报告...</div>';
  bootstrap.Modal.getOrCreateInstance($('experimentReportModal')).show();
  try {
    const report = await managerGet(`/reports/experiment?experiment_id=${encodeURIComponent(experimentId)}`);
    currentExperimentReport = report;
    renderExperimentReport(report);
    if ($('downloadExperimentReportBtn')) $('downloadExperimentReportBtn').disabled = false;
  } catch (error) {
    if ($('experimentReportBody')) $('experimentReportBody').innerHTML = `<div class="scenario-loading text-danger">报告生成失败：${escapeHtml(error.message)}</div>`;
  }
}

function downloadCurrentExperimentReport() {
  if (!currentExperimentReport) return;
  const experimentId = currentExperimentReport.experiment?.id || 'experiment';
  const blob = new Blob([JSON.stringify(currentExperimentReport, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${experimentId}_report.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderExperimentRecords() {
  const generationBody = $('generationExperimentRecordsBody') || $('experimentRecordsBody');
  const replayBody = $('replayExperimentRecordsBody');
  if (!generationBody) return;
  const single = currentSingleExperimentRecord();
  let current = experimentRecords;
  if (single) {
    const singleId = String(single.id || 'current');
    const persisted = experimentRecords.find(record => String(record.id || 'current') === singleId) || {};
    current = [
      { ...persisted, ...single },
      ...experimentRecords.filter(record => String(record.id || 'current') !== singleId),
    ];
  }
  visibleExperimentRecords = current;
  const generationRecords = current.filter(record => !isReplayLikeKind(record.kind || 'experiment'));
  const replayRecords = current.filter(record => isReplayLikeKind(record.kind || 'experiment'));
  const activeStates = new Set(['starting', 'warming_up', 'running', 'playback', 'playback_loading']);
  if ($('experimentRunningCount')) $('experimentRunningCount').textContent = String(current.filter(record => activeStates.has(String(record.run_state))).length);
  if ($('experimentCompletedCount')) $('experimentCompletedCount').textContent = String(current.filter(record => String(record.run_state) === 'completed').length);
  if ($('experimentErrorCount')) $('experimentErrorCount').textContent = String(current.filter(record => String(record.run_state) === 'error').length);
  if ($('experimentReportCount')) $('experimentReportCount').textContent = String(current.filter(record => ['completed', 'stopped'].includes(String(record.run_state))).length);

  const renderGenerationRow = record => {
    const id = String(record.id || 'current');
    const checked = selectedExperimentIds.has(id) ? 'checked' : '';
    const deleteDisabled = canOperate() ? '' : 'disabled';
    const restoreReplay = !record.child_available
      && ['completed', 'stopped', 'error', 'interrupted'].includes(String(record.run_state || ''))
      && !!record.save_file;
    const terminal = ['completed', 'stopped', 'error', 'interrupted'].includes(String(record.run_state || ''));
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="form-check-input experiment-row-check" data-id="${escapeHtml(id)}" ${checked}></td>
      <td><code>${escapeHtml(record.name || id)}</code>${record.workflow_id ? `<small class="d-block text-secondary">${escapeHtml(record.workflow_id)} · ${escapeHtml(record.workflow_name || '测试流程')}</small>` : '<small class="d-block text-secondary">直接启动</small>'}${record.batch_count ? `<small class="d-block text-secondary">${Number(record.batch_index || 0)} / ${Number(record.batch_count)}</small>` : ''}</td>
      <td>${escapeHtml(experimentStateLabel(record))}</td>
      <td>${escapeHtml(formatSimTime(record))}</td>
      <td>${escapeHtml(formatProgress(record))}</td>
      <td>${escapeHtml(record.vehicles ?? 0)}</td>
      <td>${escapeHtml(record.init_mode || '-')}</td>
      <td>${escapeHtml(experimentGpuLabel(record))}</td>
      <td>${escapeHtml(record.port || '-')}</td>
      <td><code>${escapeHtml(record.save_file || '-')}</code></td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-primary me-1" data-experiment-action="view" data-id="${escapeHtml(id)}">
          <i class="bi ${restoreReplay ? 'bi-play-fill' : 'bi-box-arrow-up-right'} me-1"></i>${restoreReplay ? '回放' : t('experiments.view')}
        </button>
        <button class="btn btn-sm btn-outline-info me-1" data-experiment-action="report" data-id="${escapeHtml(id)}" title="查看量化实验报告">
          <i class="bi bi-file-earmark-bar-graph me-1"></i>报告
        </button>
        <button class="btn btn-sm btn-outline-warning me-1" data-experiment-action="review" data-id="${escapeHtml(id)}" title="确认结果保留与事故候选" ${terminal ? '' : 'disabled'}>
          <i class="bi bi-clipboard-check me-1"></i>确认
        </button>
        <button class="btn btn-sm btn-outline-danger" data-experiment-action="delete" data-id="${escapeHtml(id)}" ${deleteDisabled}>
          <i class="bi bi-trash me-1"></i>${t('experiments.delete')}
        </button>
      </td>`;
    return tr;
  };

  const renderReplayRow = record => {
    const id = String(record.id || 'current');
    const checked = selectedExperimentIds.has(id) ? 'checked' : '';
    const deleteDisabled = canOperate() ? '' : 'disabled';
    const scenarioPath = record.scenario || record.replay_params?.scenario_path || record.replay_params?.scenario || record.save_file || '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="form-check-input experiment-row-check" data-id="${escapeHtml(id)}" ${checked}></td>
      <td><code>${escapeHtml(record.name || id)}</code></td>
      <td>${escapeHtml(experimentStateLabel(record))}</td>
      <td>${escapeHtml(formatSimTime(record))}</td>
      <td>${escapeHtml(formatProgress(record))}</td>
      <td>${escapeHtml(record.vehicles ?? 0)}</td>
      <td>${escapeHtml(experimentGpuLabel(record))}</td>
      <td>${escapeHtml(record.port || '-')}</td>
      <td><code>${escapeHtml(scenarioPath || '-')}</code></td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-primary me-1" data-experiment-action="view" data-id="${escapeHtml(id)}">
          <i class="bi bi-box-arrow-up-right me-1"></i>${t('experiments.view')}
        </button>
        <button class="btn btn-sm btn-outline-danger" data-experiment-action="delete" data-id="${escapeHtml(id)}" ${deleteDisabled}>
          <i class="bi bi-trash me-1"></i>${t('experiments.delete')}
        </button>
      </td>`;
    return tr;
  };

  generationBody.innerHTML = '';
  if (generationRecords.length) {
    generationRecords.forEach(record => generationBody.appendChild(renderGenerationRow(record)));
  } else {
    generationBody.innerHTML = `<tr><td colspan="11" class="text-secondary">${t('experiments.empty')}</td></tr>`;
  }

  if (replayBody) {
    replayBody.innerHTML = '';
    if (replayRecords.length) {
      replayRecords.forEach(record => replayBody.appendChild(renderReplayRow(record)));
    } else {
      replayBody.innerHTML = `<tr><td colspan="10" class="text-secondary">${t('experiments.emptyReplay')}</td></tr>`;
    }
  }
  const generationSelectAll = $('generationExperimentSelectAll');
  if (generationSelectAll) {
    generationSelectAll.checked = generationRecords.length > 0 && generationRecords.every(r => selectedExperimentIds.has(String(r.id || 'current')));
  }
  const replaySelectAll = $('replayExperimentSelectAll');
  if (replaySelectAll) {
    replaySelectAll.checked = replayRecords.length > 0 && replayRecords.every(r => selectedExperimentIds.has(String(r.id || 'current')));
  }
}

async function viewExperimentRecord(record, options = {}) {
  const replayLike = isReplayLikeKind(record.kind || 'experiment');
  const terminal = ['completed', 'stopped', 'error', 'interrupted'].includes(String(record.run_state || ''));
  if (!replayLike && terminal && !record.child_available && record.save_file) {
    showToast('正在恢复已结束实验的交通流回放...', true);
    const result = await managerPost('/action', {
      type: 'start_playback',
      scenario: record.save_file,
      backend_model: record.backend_model || undefined,
      map_path: record.map_path || undefined,
      gpu_id: String(record.gpu_id ?? '4'),
      marker_scope: record.marker_scope || record.id,
    });
    if (!result?.ok || !result?.experiment) throw new Error(result?.error || '回放恢复失败');
    openViewer(result.experiment, 'replay', options);
    return;
  }
  openViewer(record, replayLike ? record.kind : 'experiment', options);
}

async function loadExperiments() {
  try {
    const experimentsGet = managerBase ? managerGet : apiGet;
    const res = await experimentsGet('/experiments');
    experimentRecords = res.experiments || [];
    if (!shouldHoldExperimentRender()) renderExperimentRecords();
  } catch (_) {
    if (!shouldHoldExperimentRender()) renderExperimentRecords();
  } finally {
    lastExperimentsLoadAt = performance.now();
  }
}

async function deleteExperimentIds(ids) {
  const targets = (ids || []).filter(Boolean).map(String);
  if (!targets.length) return;
  if (!confirmHighRisk(t('experiments.deleteConfirm'))) return;
  if (isManagerBackend()) {
    await sendAction(withHighRiskConfirmation({ type: 'delete_experiments', experiment_ids: targets }));
  } else {
    await sendAction(withHighRiskConfirmation({ type: 'terminate_experiment', save_data: false }));
  }
  targets.forEach(id => selectedExperimentIds.delete(id));
  await loadExperiments();
  await loadDataRecords();
}

function confirmHighRisk(message = t('security.highRiskConfirm')) {
  return window.confirm(message || t('security.highRiskConfirm'));
}

function withHighRiskConfirmation(payload) {
  return { ...payload, high_risk_confirmed: true };
}

async function loadSecurityAdmin(showMessage = false) {
  if (!isAdminUser()) return;
  try {
    const category = $('securityEventFilter')?.value || '';
    const [usersRes, eventsRes] = await Promise.all([
      apiGet('/admin/users'),
      apiGet(`/admin/security/events?limit=300&category=${encodeURIComponent(category)}`),
    ]);
    adminUsers = usersRes.users || [];
    securityEvents = eventsRes.events || [];
    renderAdminUsers();
    renderSecurityEvents();
    if (showMessage) showToast(t('toast.securityLoaded'), true);
  } catch (err) {
    showToast(`${t('toast.actionFail')}: ${err.message}`, false);
  }
}

function renderAdminUsers() {
  const body = $('adminUsersBody');
  if (!body) return;
  body.innerHTML = '';
  if (!adminUsers.length) {
    body.innerHTML = `<tr><td colspan="5" class="text-secondary">${t('security.noUsers')}</td></tr>`;
    return;
  }
  adminUsers.forEach(user => {
    const id = String(user.id || '');
    const role = String(user.role || 'operator');
    const enabled = user.enabled !== false;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${escapeHtml(user.username || '')}</code></td>
      <td>
        <select class="form-select form-select-sm admin-role-select" data-user-id="${escapeHtml(id)}">
          <option value="admin" ${role === 'admin' ? 'selected' : ''}>${t('security.role.admin')}</option>
          <option value="operator" ${role === 'operator' ? 'selected' : ''}>${t('security.role.operator')}</option>
          <option value="viewer" ${role === 'viewer' ? 'selected' : ''}>${t('security.role.viewer')}</option>
        </select>
      </td>
      <td>${enabled ? t('security.enable') : t('security.disable')}</td>
      <td>${escapeHtml(user.last_login || '-')}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-warning me-1" data-user-action="reset_password" data-user-id="${escapeHtml(id)}">
          <i class="bi bi-key me-1"></i>${t('security.resetPassword')}
        </button>
        <button class="btn btn-sm btn-outline-secondary me-1" data-user-action="set_enabled" data-enabled="${enabled ? 'false' : 'true'}" data-user-id="${escapeHtml(id)}">
          <i class="bi ${enabled ? 'bi-person-x' : 'bi-person-check'} me-1"></i>${enabled ? t('security.disable') : t('security.enable')}
        </button>
        <button class="btn btn-sm btn-outline-danger" data-user-action="delete_user" data-user-id="${escapeHtml(id)}">
          <i class="bi bi-trash me-1"></i>${t('security.deleteUser')}
        </button>
      </td>`;
    body.appendChild(tr);
  });
}

function renderSecurityEvents() {
  const body = $('securityEventsBody');
  if (!body) return;
  body.innerHTML = '';
  if (!securityEvents.length) {
    body.innerHTML = `<tr><td colspan="6" class="text-secondary">${t('security.noEvents')}</td></tr>`;
    return;
  }
  securityEvents.forEach(event => {
    const details = JSON.stringify(event.details || {});
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(event.time || '')}</td>
      <td>${escapeHtml(event.category || '')}</td>
      <td>${escapeHtml(event.action || '')}</td>
      <td>${escapeHtml(event.username || '-')}</td>
      <td>${escapeHtml(event.ip || '-')}</td>
      <td class="security-details" title="${escapeHtml(details)}">${escapeHtml(details)}</td>`;
    body.appendChild(tr);
  });
}

async function createAdminUser() {
  const username = $('adminNewUsernameInput')?.value?.trim() || '';
  const password = $('adminNewPasswordInput')?.value || '';
  const role = $('adminNewRoleSelect')?.value || 'operator';
  const res = await apiPost('/admin/users', { username, password, role, enabled: true });
  if (res.ok === false) throw new Error(res.error || 'create user failed');
  $('adminNewUsernameInput').value = '';
  $('adminNewPasswordInput').value = '';
  await loadSecurityAdmin(true);
}

async function adminUserAction(payload) {
  const res = await apiPost('/admin/users/action', payload);
  if (res.ok === false) throw new Error(res.error || 'user action failed');
  await loadSecurityAdmin(true);
}

const DATA_CATALOG_COPY = {
  natural: ['自然驾驶数据集', '汇总 CityNDE 与 NeuralNDE 使用的数据索引；源目录保持只读。'],
  virtual: ['虚拟场景数据库', '实验生成和上传的 CityNDE 场景，可直接回放、下载或截取视频。'],
  standard: ['标准化场景库', '低密度普通交通、信号路口行人和最右侧非机动车三套可复用场景。'],
  maps: ['高精地图数据库', '聚合 CityNDE 地图文件与 NeuralNDE 数据集地图配置。'],
  results: ['测试结果数据库', '保存测试实验、场景记录、评价配置和 Cosmos 视频产物的统一索引。'],
  regulations: ['标准法规库', '选取可由交通流状态直接判断的常见道路通行规则。'],
  accidents: ['事故案例数据库', '保存被测主车碰撞片段；当前没有事故记录时保持空库。'],
  transfer: ['Transfer2.5 视频生成', '从虚拟、标准、结果或事故数据库选择片段并提交多视角生成任务。'],
};

const REGULATION_RECORDS = [
  { path: '法规/信号灯通行规则', algorithm: 'rule', kind: 'regulation', description: '测试方法：记录主车通过停止线前后的信号状态；红灯停止线穿越事件应为 0。', read_only: true, replayable: false },
  { path: '法规/行人优先通行规则', algorithm: 'rule', kind: 'regulation', description: '测试方法：在斑马线行人通行窗口统计车辆冲突和让行；主车与行人几何重叠应为 0。', read_only: true, replayable: false },
  { path: '法规/安全跟车距离规则', algorithm: 'metric', kind: 'regulation', description: '测试方法：逐帧计算同向前车 TTC 与净间距；最小 TTC 低于 0.5 s 判为严重风险。', read_only: true, replayable: false },
  { path: '法规/车道边界与导向规则', algorithm: 'rule', kind: 'regulation', description: '测试方法：逐帧匹配主车车道语义；无有效车道或偏离规划路线的帧计为违规代理。', read_only: true, replayable: false },
];

function dataCatalogRecords(mode = dataCatalogMode) {
  const records = [...dataRecords];
  if (mode === 'standard') return records.filter(record => record.library_id || String(record.path || '').includes('/library/')).map(record => ({ ...record, read_only: true }));
  if (mode === 'natural') return naturalCatalogRecords;
  if (mode === 'results') {
    const terminalStates = new Set(['completed', 'stopped', 'error', 'interrupted']);
    const resultRecords = experimentRecords.filter(record => (
      record.save_test_result !== false && terminalStates.has(String(record.run_state || ''))
    )).map(record => ({
      ...record,
      id: record.id,
      experiment_id: record.id,
      path: record.save_file || record.scenario || `experiment://${record.id}`,
      algorithm: record.backend_model || 'experiment',
      kind: 'test_result',
      modified: record.started_at || '',
      description: `${record.workflow_id || '直接启动'} · ${experimentStateLabel(record)}`,
      replayable: !!(record.save_file || record.scenario),
      read_only: true,
    }));
    return resultRecords;
  }
  if (mode === 'maps') return mapCatalogRecords;
  if (mode === 'regulations') return REGULATION_RECORDS;
  if (mode === 'accidents') return records.filter(record => {
    const text = `${record.kind || ''} ${record.path || ''}`.toLowerCase();
    return text.includes('accident') || text.includes('collision');
  });
  if (mode === 'transfer') return records.filter(record => record.replayable !== false && String(record.kind || 'scenario_pkl') === 'scenario_pkl');
  return records.filter(record => !record.library_id && !String(record.path || '').includes('/library/'));
}

function renderDataCatalogCounts() {
  const standardCount = dataCatalogRecords('standard').length;
  const virtualCount = dataCatalogRecords('virtual').length;
  const resultCount = dataCatalogRecords('results').length;
  const accidentCount = dataCatalogRecords('accidents').length
    + accidentCatalogRecords.filter(record => record.status === 'candidate').length;
  if ($('standardScenarioCount')) $('standardScenarioCount').textContent = `${standardCount} 条`;
  if ($('virtualScenarioCount')) $('virtualScenarioCount').textContent = `${virtualCount} 条`;
  if ($('resultDatasetCount')) $('resultDatasetCount').textContent = `${resultCount} 条`;
  if ($('accidentDatasetCount')) $('accidentDatasetCount').textContent = accidentCount ? `${accidentCount} 条` : '暂无记录';
  if ($('mapDatasetCount')) $('mapDatasetCount').textContent = `${mapCatalogRecords.length} 张`;
  if ($('naturalDatasetCount')) $('naturalDatasetCount').textContent = `${naturalCatalogRecords.length} 组`;
}

function renderAccidentCandidates() {
  const list = $('dataAccidentCandidateList');
  if (!list) return;
  const candidates = accidentCatalogRecords.filter(record => record.status === 'candidate');
  if ($('dataAccidentCandidateCount')) $('dataAccidentCandidateCount').textContent = `${candidates.length} 个待确认`;
  if (!candidates.length) {
    list.innerHTML = '<div class="scenario-loading">当前没有待确认的主车事故。</div>';
    return;
  }
  list.innerHTML = candidates.map(record => `
    <article class="data-accident-item">
      <div><h4>${escapeHtml(record.experiment_id || record.id)}</h4><p>${Number(record.first_time_seconds || 0).toFixed(1)} s · 参与者 ${escapeHtml((record.actor_ids || []).join(' / '))} · 截取 ${Number(record.start_seconds || 0).toFixed(1)}-${Number(record.end_seconds || 0).toFixed(1)} s</p></div>
      <div class="data-accident-item-actions"><button type="button" class="btn btn-sm btn-primary" data-accident-action="save" data-id="${escapeHtml(record.id)}"><i class="bi bi-save me-1"></i>保存</button><button type="button" class="btn btn-sm btn-outline-secondary" data-accident-action="ignore" data-id="${escapeHtml(record.id)}">忽略</button></div>
    </article>`).join('');
}

async function openExperimentCompletionReview(status = lastStatus || {}) {
  const experimentId = String(status.experiment_id || status.id || activeExperimentId || '');
  if (!experimentId) return;
  completionReviewExperimentId = experimentId;
  await managerGet(`/reports/experiment?experiment_id=${encodeURIComponent(experimentId)}`).catch(() => null);
  await loadDataCatalogIndex();
  const candidates = accidentCatalogRecords.filter(record => (
    String(record.experiment_id || '') === experimentId && record.status === 'candidate'
  ));
  if ($('completionExperimentId')) $('completionExperimentId').textContent = experimentId;
  if ($('completionSaveResultToggle')) $('completionSaveResultToggle').checked = status.save_test_result !== false;
  const list = $('completionAccidentList');
  if (list) {
    list.innerHTML = candidates.length ? candidates.map(record => `
      <label class="completion-accident-item">
        <input type="checkbox" data-completion-accident="${escapeHtml(record.id)}" checked>
        <span><b>${Number(record.first_time_seconds || 0).toFixed(1)} s · ${escapeHtml((record.actor_ids || []).join(' / '))}</b><small>保存后生成独立可回放事故场景；取消勾选将忽略该候选。</small></span>
      </label>`).join('') : '<div class="scenario-loading">本次实验没有检测到主车事故候选。</div>';
  }
  bootstrap.Modal.getOrCreateInstance($('experimentCompletionModal')).show();
}

async function saveExperimentCompletionReview() {
  const experimentId = completionReviewExperimentId;
  if (!experimentId) return;
  const button = $('completionConfirmBtn');
  if (button) button.disabled = true;
  try {
    await managerPost('/data/action', {
      type: 'set_experiment_retention',
      experiment_id: experimentId,
      save_test_result: !!$('completionSaveResultToggle')?.checked,
    });
    const choices = Array.from(document.querySelectorAll('[data-completion-accident]'));
    for (const input of choices) {
      await managerPost('/data/action', {
        type: input.checked ? 'save_accident' : 'ignore_accident',
        accident_id: input.dataset.completionAccident,
      });
    }
    bootstrap.Modal.getInstance($('experimentCompletionModal'))?.hide();
    await Promise.all([loadExperiments(), loadDataRecords()]);
    showToast('实验结果与事故候选处理已保存', true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderDataGridRecords(records) {
  const grid = $('dataGridRecords');
  if (!grid) return;
  if (!records.length) {
    grid.innerHTML = '<div class="scenario-loading">当前数据库暂无记录。</div>';
    return;
  }
  grid.innerHTML = records.map(record => {
    const path = String(record.path || record);
    const replayable = record.replayable !== false;
    const linkedExperiment = experimentRecords.find(experiment => (
      String(experiment.id || '') === String(record.experiment_id || '')
      || String(experiment.derived_from_path || '') === path
      || String(experiment.save_file || '') === path
      || String(experiment.scenario || '') === path
    ));
    const videoAvailable = !!linkedExperiment && Number(linkedExperiment.video_artifact_count || 0) > 0;
    const mode = dataRecordModes.get(path) || 'traffic';
    const frameText = record.frame_count == null && record.kind === 'natural_dataset'
      ? ` · 轨迹文件 ${Number(record.trajectory_file_count || 0)} · 地图图像 ${Number(record.image_asset_count || 0)} · 无统一时间轴`
      : (record.frame_count == null ? '' : ` · ${Number(record.frame_count)} frames`);
    const contentText = mode === 'video'
      ? (videoAvailable ? '打开关联实验的视频与质量产物' : '该数据暂无关联视频')
      : (record.description || path);
    const natural = record.kind === 'natural_dataset';
    const action = natural && mode === 'traffic' ? 'browse-natural' : (mode === 'video' ? 'video' : 'traffic-preview');
    const enabled = natural && mode === 'traffic' ? !!record.downloadable : (mode === 'video' ? videoAvailable : replayable);
    const icon = natural && mode === 'traffic' ? 'bi-folder2-open' : (mode === 'video' ? 'bi-camera-video' : 'bi-box-arrow-up-right');
    const visual = natural ? '' : scenarioPreviewVisual(path, mode, linkedExperiment?.id || '');
    return `<article class="data-record-card">${visual}<h4>${escapeHtml(record.name || path.split('/').pop() || path)}</h4><p>${escapeHtml(contentText)}</p><footer><small>${escapeHtml(record.kind || 'scenario_pkl')} · ${formatBytes(record.size)}${escapeHtml(frameText)}</small><span class="record-mode-switch"><button type="button" class="${mode === 'traffic' ? 'active' : ''}" data-data-record-mode="traffic" data-path="${escapeHtml(path)}" title="交通流"><i class="bi bi-sign-intersection"></i></button><button type="button" class="${mode === 'video' ? 'active' : ''}" data-data-record-mode="video" data-path="${escapeHtml(path)}" title="多模态" ${videoAvailable ? '' : 'disabled'}><i class="bi bi-camera-video"></i></button></span><button type="button" class="btn btn-sm btn-outline-primary" data-data-action="${action}" data-path="${escapeHtml(path)}" data-dataset-id="${escapeHtml(record.id || '')}" data-experiment-id="${escapeHtml(linkedExperiment?.id || '')}" ${enabled ? '' : 'disabled'}><i class="bi ${icon}"></i><span class="visually-hidden">查看</span></button></footer></article>`;
  }).join('');
  activateScenarioPreviews(grid);
}

function renderDataViewMode() {
  const gridMode = dataViewMode === 'grid';
  if ($('dataGridRecords')) $('dataGridRecords').hidden = !gridMode || dataCatalogMode === 'transfer';
  if ($('dataTableRecords')) $('dataTableRecords').hidden = gridMode || dataCatalogMode === 'transfer';
  $('dataListViewBtn')?.classList.toggle('active', !gridMode);
  $('dataGridViewBtn')?.classList.toggle('active', gridMode);
}

function standardScenarioSourceRecords() {
  const database = $('dataStandardSourceDatabaseSelect')?.value || 'virtual';
  if (database === 'natural') return [];
  return dataCatalogRecords(database).filter(record => (
    record.replayable !== false && String(record.path || '').endsWith('.pkl')
  ));
}

function updateStandardScenarioBuilderHint() {
  const path = $('dataStandardSourceSelect')?.value || '';
  const record = dataRecords.find(item => String(item.path || item) === path);
  const start = Math.max(0, Number($('dataStandardStartInput')?.value || 0));
  const end = Math.max(0, Number($('dataStandardEndInput')?.value || 0));
  const duration = record ? scenarioDuration(record) : 0;
  const hint = $('dataStandardBuilderHint');
  if (hint) hint.textContent = path
    ? `${path.split('/').pop()} · 截取 ${start.toFixed(1)}-${end.toFixed(1)} s${duration > 0 ? ` · 源记录 ${duration.toFixed(1)} s` : ''}`
    : ($('dataStandardSourceDatabaseSelect')?.value === 'natural'
      ? '自然数据需先转换为规范 CityNDE recording，再使用下方批量导入。'
      : '当前数据库没有可截取的 CityNDE 场景。');
  const button = $('dataStandardGenerateBtn');
  if (button) button.disabled = !path;
}

function updateStandardScenarioSourceOptions() {
  const select = $('dataStandardSourceSelect');
  if (!select) return;
  const current = select.value;
  const records = standardScenarioSourceRecords();
  select.innerHTML = '';
  records.forEach(record => {
    const label = String(record.experiment_name || record.path || '').split('/').pop();
    select.appendChild(new Option(label, record.path));
  });
  if (current && records.some(record => record.path === current)) select.value = current;
  if (!records.length) select.appendChild(new Option('暂无可截取的 CityNDE 场景', ''));
  const selected = records.find(record => record.path === select.value);
  const available = selected ? scenarioDuration(selected) : 0;
  const endInput = $('dataStandardEndInput');
  if (endInput && available > 0) {
    endInput.max = String(Math.min(100, available));
    endInput.value = String(Math.min(15, available));
  }
  updateStandardScenarioBuilderHint();
}

function updateStandardImportMapOptions() {
  const select = $('dataStandardImportMapSelect');
  if (!select) return;
  const current = select.value;
  const maps = mapCatalogRecords.filter(record => record.algorithm === 'citynde');
  select.innerHTML = maps.map(record => `<option value="${escapeHtml(record.path)}">${escapeHtml(String(record.path).split('/').pop())}</option>`).join('');
  if (current && maps.some(record => record.path === current)) select.value = current;
  if (!maps.length) select.appendChild(new Option('暂无 CityNDE 地图', ''));
  if ($('dataStandardImportBtn')) $('dataStandardImportBtn').disabled = !select.value;
}

async function importStandardScenarioFiles(files) {
  if (!files?.length) return;
  const mapPath = $('dataStandardImportMapSelect')?.value || '';
  if (!mapPath) throw new Error('请选择导入场景绑定的 CityNDE 地图');
  const form = new FormData();
  Array.from(files).forEach(file => form.append('files', file, file.name));
  const query = new URLSearchParams({
    category: $('dataStandardImportCategorySelect')?.value || 'normal',
    map_path: mapPath,
  });
  const response = await fetch(apiUrl(`/data/standard/import?${query}`), {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok === false) throw new Error(result.error || `HTTP ${response.status}`);
  await Promise.all([loadDataRecords(), loadStandardScenarios()]);
  selectDataCatalog('standard');
  const rejected = Array.isArray(result.errors) ? result.errors.length : 0;
  showToast(`已导入 ${Number(result.saved?.length || 0)} 条标准场景${rejected ? `，${rejected} 条未通过校验` : ''}`, true);
}

async function submitStandardScenario() {
  const sourcePath = $('dataStandardSourceSelect')?.value || '';
  const name = $('dataStandardNameInput')?.value?.trim() || '';
  const startSeconds = Math.max(0, Number($('dataStandardStartInput')?.value || 0));
  const endSeconds = Math.max(0, Number($('dataStandardEndInput')?.value || 0));
  if (!sourcePath) {
    showToast('请选择来源场景', false);
    return;
  }
  if (!name) {
    showToast('请输入标准场景名称', false);
    return;
  }
  if (endSeconds <= startSeconds || endSeconds - startSeconds > 100) {
    showToast('时间窗必须大于 0 且不超过 100 秒', false);
    return;
  }
  const button = $('dataStandardGenerateBtn');
  button.disabled = true;
  if ($('standardScenarioProgress')) $('standardScenarioProgress').hidden = false;
  try {
    const result = await managerPost('/data/action', {
      type: 'generate_standard_scenario',
      source_path: sourcePath,
      name,
      category: $('dataStandardCategorySelect')?.value || 'normal',
      description: $('dataStandardDescriptionInput')?.value?.trim() || '',
      start_seconds: startSeconds,
      end_seconds: endSeconds,
    });
    await Promise.all([loadDataRecords(), loadStandardScenarios()]);
    selectDataCatalog('standard');
    const seed = result.seed || {};
    showToast(
      seed.available
        ? '标准场景及匹配首帧已保存，可直接跳过 Transfer 种子生成'
        : `标准场景已生成；首帧未保存：${seed.reason || '来源没有通过质量检查的同源 OmniDreams 视频'}`,
      true,
    );
  } catch (error) {
    showToast(`标准场景生成失败：${error.message}`, false);
  } finally {
    button.disabled = false;
    if ($('standardScenarioProgress')) $('standardScenarioProgress').hidden = true;
  }
}

async function openExperimentVideoPreview(experiment) {
  const experimentId = String(experiment?.id || '');
  if (!experimentId) throw new Error('关联实验 ID 缺失');
  const modal = bootstrap.Modal.getOrCreateInstance($('mediaPreviewModal'));
  $('mediaPreviewModalTitle').textContent = experiment.name || experimentId;
  $('mediaPreviewModalSubtitle').textContent = '正在读取视频产物...';
  $('mediaPreviewLoading').hidden = false;
  const player = $('mediaPreviewVideo');
  modalTrafficPreview = null;
  if ($('mediaPreviewTraffic')) $('mediaPreviewTraffic').hidden = true;
  player.pause();
  player.removeAttribute('src');
  player.hidden = true;
  modal.show();
  const payload = await managerGet(`/artifacts?experiment_id=${encodeURIComponent(experimentId)}`);
  const videos = (payload.artifacts || []).filter(artifact => (
    String(artifact.content_type || '').startsWith('video/')
    || /\.(mp4|webm|mov)$/i.test(String(artifact.path || ''))
  ));
  const preferred = videos.find(item => /omnidreams.*(smooth|final|30fps)/i.test(`${item.kind} ${item.path}`))
    || videos.find(item => /omnidreams/i.test(`${item.kind} ${item.path}`))
    || videos.find(item => /transfer/i.test(`${item.kind} ${item.path}`))
    || videos[0];
  if (!preferred) throw new Error('该实验没有可播放的视频产物');
  player.src = artifactUrl(preferred);
  player.hidden = false;
  $('mediaPreviewLoading').hidden = true;
  $('mediaPreviewModalSubtitle').textContent = `${preferred.kind || 'video'} · 支持局域网拖动播放`;
  player.play().catch(() => {});
}

function updateDataTransferScenarioOptions() {
  const select = $('dataTransferScenarioSelect');
  if (!select) return;
  const database = $('dataTransferDatabaseSelect')?.value || 'virtual';
  const records = dataCatalogRecords(database).filter(record => record.replayable !== false && String(record.path || '').endsWith('.pkl'));
  select.innerHTML = '';
  records.forEach(record => select.appendChild(new Option(record.library_name || String(record.path).split('/').pop(), record.path)));
  if (!records.length) select.appendChild(new Option('当前数据库没有可生成的场景', ''));
  updateDataTransferHint();
}

function updateDataTransferHint() {
  const scenario = $('dataTransferScenarioSelect')?.value || '';
  const start = Math.max(0, Number($('dataTransferStartInput')?.value || 0));
  const end = Math.max(0, Number($('dataTransferEndInput')?.value || 0));
  const views = $('dataTransferViewSelect')?.value === 'all' ? '七视角' : '主视角';
  if ($('dataTransferHint')) $('dataTransferHint').textContent = scenario
    ? `${scenario.split('/').pop()} · ${Math.max(0, end - start).toFixed(1)} s · ${views}`
    : '请选择场景和时间段。';
}

function selectDataCatalog(mode) {
  dataCatalogMode = DATA_CATALOG_COPY[mode] ? mode : 'virtual';
  document.querySelectorAll('[data-data-catalog]').forEach(button => {
    button.classList.toggle('active', button.dataset.dataCatalog === dataCatalogMode);
  });
  const copy = DATA_CATALOG_COPY[dataCatalogMode];
  if ($('dataCatalogTitle')) $('dataCatalogTitle').textContent = copy[0];
  if ($('dataCatalogDescription')) $('dataCatalogDescription').textContent = copy[1];
  if ($('dataTransferPanel')) $('dataTransferPanel').hidden = dataCatalogMode !== 'transfer';
  if ($('dataStandardBuilderPanel')) $('dataStandardBuilderPanel').hidden = dataCatalogMode !== 'standard';
  if ($('dataAccidentPanel')) $('dataAccidentPanel').hidden = dataCatalogMode !== 'accidents';
  const editable = ['virtual', 'accidents'].includes(dataCatalogMode);
  if ($('uploadDataBtn')) $('uploadDataBtn').disabled = !['virtual', 'natural'].includes(dataCatalogMode);
  if ($('downloadSelectedDataBtn')) $('downloadSelectedDataBtn').disabled = !editable;
  if ($('deleteSelectedDataBtn')) $('deleteSelectedDataBtn').disabled = !editable;
  if (dataCatalogMode === 'transfer') updateDataTransferScenarioOptions();
  if (dataCatalogMode === 'standard') updateStandardScenarioSourceOptions();
  if (dataCatalogMode === 'standard') updateStandardImportMapOptions();
  if (dataCatalogMode === 'accidents') renderAccidentCandidates();
  renderDataRecords();
  renderDataViewMode();
}

async function loadMapCatalogRecords() {
  try {
    const [city, neural] = await Promise.all([
      managerGet('/maps?backend_model=cnde'),
      managerGet('/maps?backend_model=neuralnde'),
    ]);
    mapCatalogRecords = [
      ...(city.maps || []).map(path => ({ path, algorithm: 'citynde', kind: 'hd_map', description: 'CityNDE 高精语义地图链接', read_only: true, replayable: false })),
      ...(neural.maps || []).map(path => ({ path, algorithm: 'neuralnde', kind: 'hd_map', description: 'NeuralNDE 局部地图数据集配置', read_only: true, replayable: false })),
    ];
  } catch (_) {
    mapCatalogRecords = [];
  }
}

async function loadDataCatalogIndex() {
  try {
    const payload = await managerGet('/data/catalogs');
    naturalCatalogRecords = (payload.natural_datasets || []).map(record => ({ ...record, replayable: false }));
    accidentCatalogRecords = Array.isArray(payload.accidents) ? payload.accidents : [];
    const maps = payload.maps || {};
    mapCatalogRecords = [
      ...(maps.citynde || []).map(path => ({ path, algorithm: 'citynde', kind: 'hd_map', description: 'CityNDE 高精语义地图链接', read_only: true, replayable: false })),
      ...(maps.neuralnde || []).map(path => ({ path, algorithm: 'neuralnde', kind: 'hd_map', description: 'NeuralNDE 局部地图数据集配置', read_only: true, replayable: false })),
    ];
  } catch (_) {
    accidentCatalogRecords = [];
    await loadMapCatalogRecords();
  }
}

async function submitDataTransfer() {
  const scenario = $('dataTransferScenarioSelect')?.value || '';
  const record = dataRecords.find(item => String(item.path || item) === scenario);
  const startSeconds = Math.max(0, Number($('dataTransferStartInput')?.value || 0));
  const endSeconds = Math.max(0, Number($('dataTransferEndInput')?.value || 0));
  if (!scenario || !record) {
    showToast('请选择可回放的 CityNDE 场景', false);
    return;
  }
  if (endSeconds <= startSeconds) {
    showToast('结束时间必须大于起始时间', false);
    return;
  }
  const resolution = Math.max(0.001, Number(record.sim_resolution || 0.1));
  const button = $('dataTransferGenerateBtn');
  button.disabled = true;
  try {
    const result = await managerPost('/action', {
      type: 'start_transfer_replay',
      scenario,
      start_step: Math.floor(startSeconds / resolution),
      end_step: Math.ceil(endSeconds / resolution),
      allow_segmented_transfer: true,
      world_transfer_steps: Math.max(1, Number($('dataTransferStepsSelect')?.value || 35)),
      transfer_view_mode: $('dataTransferViewSelect')?.value === 'all' ? 'multiview' : 'front',
    });
    showToast('Transfer2.5 数据库视频任务已提交', true);
    openViewer(result.experiment || result.viewer_url, 'experiment');
  } catch (error) {
    showToast(`Transfer2.5 提交失败：${error.message}`, false);
  } finally {
    button.disabled = false;
  }
}

async function handleAccidentCandidateAction(accidentId, action) {
  if (!accidentId || !['save', 'ignore'].includes(action)) return;
  try {
    await managerPost('/data/action', {
      type: action === 'save' ? 'save_accident' : 'ignore_accident',
      accident_id: accidentId,
    });
    await loadDataRecords();
    selectDataCatalog('accidents');
    showToast(action === 'save' ? '事故场景已保存，可直接回放' : '事故候选已忽略', true);
  } catch (error) {
    showToast(`事故操作失败：${error.message}`, false);
  }
}

function renderDataRecords() {
  const bodies = Array.from(document.querySelectorAll('[data-records-body]'));
  bodies.forEach(body => { body.innerHTML = ''; });
  const records = sortedDataRecords();
  renderDataGridRecords(records);
  if (!records.length) {
    bodies.forEach(body => {
      body.innerHTML = `<tr><td colspan="7" class="text-secondary">${t('data.empty')}</td></tr>`;
    });
    return;
  }
  records.forEach((record, idx) => {
    const path = record.path || record;
    const checked = selectedDataPaths.has(path) ? 'checked' : '';
    const algorithm = String(record.algorithm || 'citynde');
    const kind = String(record.kind || 'scenario_pkl');
    const replayable = record.replayable !== false;
    const writable = canOperate();
    const natural = kind === 'natural_dataset';
    const replayDisabled = (natural || (replayable && writable)) ? '' : 'disabled';
    const managed = !record.read_only && String(path).endsWith('.pkl');
    const downloadDisabled = managed || (natural && record.downloadable) ? '' : 'disabled';
    const renameDisabled = managed && writable ? '' : 'disabled';
    const deleteDisabled = managed && writable ? '' : 'disabled';
    const rowHtml = `
      <td><input type="checkbox" class="form-check-input data-row-check" data-path="${escapeHtml(path)}" ${checked} ${managed ? '' : 'disabled'}></td>
      <td>${escapeHtml(algorithm)}</td>
      <td>${escapeHtml(kind)}</td>
      <td><code>${escapeHtml(path)}</code></td>
      <td>${formatBytes(record.size)}</td>
      <td>${escapeHtml(record.modified || '-')}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-primary me-1" data-data-action="${natural ? 'browse-natural' : 'traffic-preview'}" data-path="${escapeHtml(path)}" data-dataset-id="${escapeHtml(record.id || '')}" ${replayDisabled}>
          <i class="bi ${natural ? 'bi-folder2-open' : 'bi-play-fill'} me-1"></i>${natural ? '浏览层级' : t('data.loadReplay')}
        </button>
        <button class="btn btn-sm btn-outline-info me-1" data-data-action="${natural ? 'download-natural' : 'download'}" data-path="${escapeHtml(path)}" data-dataset-id="${escapeHtml(record.id || '')}" ${downloadDisabled}>
          <i class="bi bi-download me-1"></i>${t('data.download')}
        </button>
        <button class="btn btn-sm btn-outline-warning me-1" data-data-action="rename" data-path="${escapeHtml(path)}" ${renameDisabled}>
          <i class="bi bi-pencil-square me-1"></i>${t('data.rename')}
        </button>
        <button class="btn btn-sm btn-outline-danger" data-data-action="delete" data-path="${escapeHtml(path)}" ${deleteDisabled}>
          <i class="bi bi-trash me-1"></i>${t('data.delete')}
        </button>
      </td>`;
    bodies.forEach(body => {
      const tr = document.createElement('tr');
      tr.innerHTML = rowHtml;
      body.appendChild(tr);
    });
  });
  updateDataSortIndicators();
}

function sortedDataRecords() {
  const key = dataSort.key || 'modified';
  const dir = dataSort.dir === 'asc' ? 1 : -1;
  return dataCatalogRecords().sort((a, b) => {
    const av = dataSortValue(a, key);
    const bv = dataSortValue(b, key);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return String(a.path || a).localeCompare(String(b.path || b));
  });
}

function dataSortValue(record, key) {
  if (key === 'size') return Number(record.size || 0);
  if (key === 'modified') return Date.parse(record.modified || '') || 0;
  return String(record[key] || record.path || record || '').toLowerCase();
}

function updateDataSortIndicators() {
  document.querySelectorAll('[data-data-sort]').forEach(btn => {
    const active = btn.dataset.dataSort === dataSort.key;
    btn.dataset.sortDir = active ? dataSort.dir : '';
  });
}

async function loadDataRecords(showMessage = false) {
  try {
    const scenarioRequest = apiGet('/data/scenarios').catch(async () => {
      const fallback = await apiGet('/scenarios');
      return { records: (fallback.scenarios || []).map(path => ({ path })) };
    });
    const [scenarioResult] = await Promise.all([
      scenarioRequest,
      loadDataCatalogIndex(),
      loadExperiments(),
    ]);
    dataRecords = scenarioResult.records || scenarioResult.scenarios || [];
    renderDataCatalogCounts();
    selectDataCatalog(dataCatalogMode);
    if (showMessage) showToast(t('toast.dataLoaded'), true);
  } catch (e) {
    showToast(`${t('toast.actionFail')}: ${e.message}`, false);
  }
}

async function downloadScenario(path) {
  if (!path) return;
  const r = await fetch(apiUrl(`/data/download?path=${encodeURIComponent(path)}`), { headers: authHeaders() });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || `HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const disposition = r.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : (String(path).split('/').pop() || 'record');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function downloadNaturalDataset(datasetId, relativePath = '') {
  if (!datasetId) return;
  const query = new URLSearchParams({ id: datasetId });
  if (relativePath) query.set('path', relativePath);
  const response = await fetch(
    apiUrl(`/data/natural/download?${query}`),
    { headers: authHeaders() },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="([^"]+)"/);
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = match ? match[1] : `${datasetId}.zip`;
  link.click();
  URL.revokeObjectURL(url);
}

function renderNaturalDatasetLevel(payload) {
  naturalBrowserPath = String(payload.path || '');
  const dataset = payload.dataset || {};
  if ($('naturalDatasetModalTitle')) $('naturalDatasetModalTitle').textContent = dataset.name || '自然驾驶数据集';
  if ($('naturalDatasetPath')) $('naturalDatasetPath').textContent = `/${naturalBrowserPath}`;
  if ($('naturalDatasetUpBtn')) $('naturalDatasetUpBtn').disabled = !naturalBrowserPath;
  if ($('naturalDatasetUploadBtn')) $('naturalDatasetUploadBtn').disabled = !payload.writable;
  if ($('naturalDatasetWritableHint')) {
    const sourceSummary = Number(dataset.trajectory_file_count || 0) || Number(dataset.image_asset_count || 0)
      ? `轨迹文件 ${Number(dataset.trajectory_file_count || 0)}，地图/ROI 图像 ${Number(dataset.image_asset_count || 0)}；无统一时间轴。`
      : '';
    $('naturalDatasetWritableHint').textContent = payload.writable
      ? '当前为用户导入数据，可在此层级上传目录。'
      : `算法内置数据为只读，可浏览和下载任意层级。${sourceSummary}`;
  }
  const body = $('naturalDatasetEntriesBody');
  if (!body) return;
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  body.innerHTML = entries.length ? entries.map(entry => `
    <tr>
      <td><i class="bi ${entry.kind === 'directory' ? 'bi-folder-fill' : 'bi-file-earmark'} me-2"></i>${escapeHtml(entry.name || '')}</td>
      <td>${entry.kind === 'directory' ? '目录' : '文件'}</td>
      <td>${entry.kind === 'directory' ? '-' : formatBytes(entry.size)}</td>
      <td>${escapeHtml(entry.modified || '-')}</td>
      <td class="text-end"><button type="button" class="btn btn-sm btn-outline-primary" data-natural-action="${entry.kind === 'directory' ? 'open' : 'download'}" data-path="${escapeHtml(entry.path || '')}" title="${entry.kind === 'directory' ? '进入目录' : '下载文件'}"><i class="bi ${entry.kind === 'directory' ? 'bi-box-arrow-in-right' : 'bi-download'}"></i></button></td>
    </tr>`).join('') : '<tr><td colspan="5" class="text-secondary">当前层级为空</td></tr>';
}

async function loadNaturalDatasetLevel(relativePath = naturalBrowserPath) {
  if (!naturalBrowserDatasetId) return;
  const query = new URLSearchParams({ id: naturalBrowserDatasetId });
  if (relativePath) query.set('path', relativePath);
  const payload = await managerGet(`/data/natural/tree?${query}`);
  renderNaturalDatasetLevel(payload);
}

async function openNaturalDatasetBrowser(datasetId) {
  if (!datasetId) return;
  naturalBrowserDatasetId = datasetId;
  naturalBrowserPath = '';
  await loadNaturalDatasetLevel('');
  bootstrap.Modal.getOrCreateInstance($('naturalDatasetModal')).show();
}

async function uploadNaturalDatasetLevel(files) {
  if (!naturalBrowserDatasetId || !files?.length) return;
  const form = new FormData();
  Array.from(files).forEach(file => form.append('files', file, file.webkitRelativePath || file.name));
  const query = new URLSearchParams({ id: naturalBrowserDatasetId });
  if (naturalBrowserPath) query.set('path', naturalBrowserPath);
  const response = await fetch(apiUrl(`/data/natural/upload?${query}`), {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok === false) throw new Error(result.error || `HTTP ${response.status}`);
  await loadNaturalDatasetLevel();
  await loadDataCatalogIndex();
  renderDataCatalogCounts();
  showToast(`已上传 ${Number(result.saved_files || 0)} 个文件到当前层级`, true);
}

async function downloadSelectedData() {
  const paths = Array.from(selectedDataPaths);
  if (paths.length === 0) return;
  if (paths.length === 1) {
    await downloadScenario(paths[0]);
    return;
  }
  const r = await fetch(apiUrl('/data/download_zip'), {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ paths }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || `HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `citynde_scenarios_${Date.now()}.zip`;
  link.click();
  URL.revokeObjectURL(url);
}

async function uploadDataFiles(files) {
  if (!files || files.length === 0) return;
  const natural = dataCatalogMode === 'natural';
  const form = new FormData();
  Array.from(files).forEach(file => form.append('files', file, natural ? (file.webkitRelativePath || file.name) : file.name));
  const r = await fetch(apiUrl(natural ? '/data/natural/upload' : '/data/upload'), { method: 'POST', body: form, headers: authHeaders() });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || `HTTP ${r.status}`);
  if (!natural) await loadScenarios();
  await loadDataRecords();
  showToast(natural ? '自然数据目录已导入' : t('toast.dataUploaded'), true);
}

async function renameScenario(path) {
  const current = String(path || '').split('/').pop().replace(/\.pkl$/i, '');
  const name = window.prompt(t('data.rename'), current);
  if (!name) return;
  if (!confirmHighRisk()) return;
  await apiPost('/data/action', withHighRiskConfirmation({ type: 'rename_scenario', path, new_name: name }));
  selectedDataPaths.delete(path);
  await loadScenarios();
  await loadDataRecords();
  showToast(t('toast.dataRenamed'), true);
}

async function deleteScenarioPaths(paths) {
  if (!paths.length) return;
  if (!confirmHighRisk(t('data.deleteConfirm'))) return;
  await apiPost('/data/action', withHighRiskConfirmation({ type: 'delete_scenarios', paths }));
  paths.forEach(path => selectedDataPaths.delete(path));
  await loadScenarios();
  await loadDataRecords();
  showToast(t('toast.dataDeleted'), true);
}

// ── Maximize ──────────────────────────────────────────────────────────────────
function initMaximize() {
  $('maximizeTrafficBtn').addEventListener('click', () => {
    const win = $('trafficWindow');
    win.classList.toggle('maximized');
    $('maximizeTrafficBtn').querySelector('i').className = win.classList.contains('maximized')
      ? 'bi bi-fullscreen-exit me-1' : 'bi bi-arrows-fullscreen me-1';
    setTimeout(drawFrame, 50);
  });
  document.querySelectorAll('.window-max-btn').forEach(button => {
    button.addEventListener('click', () => {
      const win = $(button.dataset.target);
      if (!win) return;
      win.classList.toggle('maximized');
      button.querySelector('i').className = win.classList.contains('maximized')
        ? 'bi bi-fullscreen-exit' : 'bi bi-arrows-fullscreen';
    });
  });
}

// ── Expanded chart modal ─────────────────────────────────────────────────────
function parseOptionalNumber(id) {
  const el = $(id);
  if (!el || el.value.trim() === '') return null;
  const n = Number(el.value);
  return Number.isFinite(n) ? n : null;
}

function chartDataForKey(key) {
  const samples = activeMetricSamples();
  if (key === 'accidentRate') return accidentSeries(samples).rate;
  if (key === 'accidentVariance') return accidentSeries(samples).variance;
  const def = CHART_DEFS[key];
  if (!def) return [];
  if (def.kind === 'hist') return valuesFromSamples(samples, def.valueKey);
  return linePointsFromSamples(samples, def.valueKey);
}

function renderExpandedChart() {
  if (!expandedChart || !expandedChartKey) return;
  const def = CHART_DEFS[expandedChartKey];
  if (!def) return;
  const xMin = parseOptionalNumber('chartXMinInput');
  const xMax = parseOptionalNumber('chartXMaxInput');
  const yMin = parseOptionalNumber('chartYMinInput');
  const yMax = parseOptionalNumber('chartYMaxInput');
  if (def.kind === 'hist') {
    const binSize = Math.max(0.01, Number($('chartBinSizeInput').value) || DEFAULT_HISTOGRAM_BIN_SIZE);
    updateHistChart(expandedChart, chartDataForKey(expandedChartKey), binSize, xMin, xMax, yMin, yMax);
  } else {
    const points = chartDataForKey(expandedChartKey);
    expandedChart.data.datasets[0].data = points;
    setChartAxis(expandedChart, points, xMin, xMax, yMin, yMax);
    expandedChart.update('none');
  }
}

function resetExpandedControls(key) {
  const def = CHART_DEFS[key];
  const data = chartDataForKey(key);
  const xs = def.kind === 'hist' ? data : data.map(p => p.x);
  const ys = def.kind === 'hist' ? [] : data.map(p => p.y);
  const xMax = xs.length ? Math.max(...xs.filter(Number.isFinite)) : 0;
  const yMax = ys.length ? Math.max(...ys.filter(Number.isFinite)) : null;
  $('chartXMinInput').value = '0';
  $('chartXMaxInput').value = Number.isFinite(xMax) && xMax > 0 ? xMax.toFixed(1) : '';
  $('chartYMinInput').value = def.kind === 'hist' ? '0' : '';
  $('chartYMaxInput').value = Number.isFinite(yMax) && yMax > 0 ? yMax.toFixed(2) : '';
  $('chartBinSizeGroup').hidden = def.kind !== 'hist';
  $('chartBinSizeInput').value = String(DEFAULT_HISTOGRAM_BIN_SIZE);
}

function openExpandedChart(key) {
  const def = CHART_DEFS[key];
  if (!def) return;
  expandedChartKey = key;
  $('chartModalTitle').textContent = t(def.titleKey);
  resetExpandedControls(key);
  if (expandedChart) {
    expandedChart.destroy();
    expandedChart = null;
  }
  const modalEl = $('chartModal');
  modalEl.addEventListener('shown.bs.modal', () => {
    expandedChart = def.kind === 'hist'
      ? makeBarChart('expandedChartCanvas', def.color, '#94a3b8', true)
      : makeLineChart('expandedChartCanvas', def.color, true);
    renderExpandedChart();
  }, { once: true });
  bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function saveExpandedChart() {
  const canvas = $('expandedChartCanvas');
  if (!canvas || !expandedChartKey) return;
  const link = document.createElement('a');
  link.download = `${expandedChartKey}_${Date.now()}.png`;
  link.href = canvas.toDataURL('image/png');
  link.click();
}

// ── Button handlers ───────────────────────────────────────────────────────────
function initButtons() {
  $('viewerLayoutSelect')?.addEventListener('change', event => applyViewerLayout(event.target.value));
  $('mediaPreviewModal')?.addEventListener('hidden.bs.modal', () => {
    modalTrafficPreview = null;
    const player = $('mediaPreviewVideo');
    if (player) player.pause();
  });
  $('addMarkerBtn')?.addEventListener('click', () => addExperimentMarker().catch(error => showToast(`标记保存失败：${error.message}`, false)));
  $('markerSelect')?.addEventListener('change', renderExperimentMarkers);
  $('jumpMarkerBtn')?.addEventListener('click', () => jumpToSelectedMarker().catch(error => showToast(error.message, false)));
  $('deleteMarkerBtn')?.addEventListener('click', () => deleteSelectedMarker().catch(error => showToast(`标记删除失败：${error.message}`, false)));
  $('saveWorkflowBtn')?.addEventListener('click', saveWorkflow);
  $('loadWorkflowBtn')?.addEventListener('click', loadSelectedWorkflow);
  $('copyWorkflowBtn')?.addEventListener('click', copySelectedWorkflow);
  $('deleteWorkflowBtn')?.addEventListener('click', deleteSelectedWorkflow);
  $('savedWorkflowSelect')?.addEventListener('change', event => {
    if (!event.target.value) {
      selectedWorkflowId = '';
      return;
    }
    loadSelectedWorkflow();
  });
  $('standardScenarioGrid')?.addEventListener('click', event => {
    const contentButton = event.target.closest('[data-standard-content]');
    if (contentButton) {
      event.stopPropagation();
      workflowScenarioContentModes.set(contentButton.dataset.libraryId, contentButton.dataset.standardContent);
      renderStandardScenarios();
      return;
    }
    const seedButton = event.target.closest('[data-standard-seed]');
    if (seedButton) {
      event.stopPropagation();
      refreshStandardScenarioSeed(seedButton.dataset.standardSeed, seedButton);
      return;
    }
    const preview = event.target.closest('[data-standard-preview]');
    if (preview) {
      event.stopPropagation();
      const record = standardScenarioRecords.find(item => item.library_id === preview.dataset.standardPreview);
      const mode = workflowScenarioContentModes.get(preview.dataset.standardPreview) || 'traffic';
      const experimentId = String(record?.seed_bundle?.source_experiment_id || '');
      if (mode === 'video' && experimentId) {
        managerGet(`/experiments?experiment_id=${encodeURIComponent(experimentId)}`)
          .then(result => openExperimentVideoPreview(result.experiment || { id: experimentId, name: record?.library_name }))
          .catch(error => showToast(`视频载入失败：${error.message}`, false));
      } else {
        previewStandardScenario(preview.dataset.standardPreview);
      }
      return;
    }
    const card = event.target.closest('[data-standard-scenario]');
    if (card) selectStandardScenario(card.dataset.standardScenario);
  });
  $('workflowScenarioListBtn')?.addEventListener('click', () => {
    workflowScenarioViewMode = 'list';
    $('workflowScenarioListBtn').classList.add('active');
    $('workflowScenarioGridBtn').classList.remove('active');
    renderStandardScenarios();
  });
  $('workflowScenarioGridBtn')?.addEventListener('click', () => {
    workflowScenarioViewMode = 'grid';
    $('workflowScenarioGridBtn').classList.add('active');
    $('workflowScenarioListBtn').classList.remove('active');
    renderStandardScenarios();
  });
  $('workflowScenarioExecutionModeSelect')?.addEventListener('change', () => {
    const replay = $('workflowScenarioExecutionModeSelect')?.value === 'replay';
    const existingSeed = $('workflowExistingSeedToggle');
    if (replay && existingSeed && !existingSeed.disabled) existingSeed.checked = true;
    updateWorkflowModelControls();
    updateWorkflowSummary();
  });
  $('workflowSeedBackendSelect')?.addEventListener('change', updateWorkflowSeedBackend);
  document.querySelectorAll('[data-workflow-scenario-mode]').forEach(button => {
    button.addEventListener('click', () => setWorkflowScenarioMode(button.dataset.workflowScenarioMode));
  });
  $('workflowMapModelSelect')?.addEventListener('change', () => {
    applySparseRuleDefaults();
    updateWorkflowModelControls();
    loadWorkflowMaps();
  });
  $('workflowLibraryModelSelect')?.addEventListener('change', () => {
    applySparseRuleDefaults();
    updateWorkflowModelControls();
    updateWorkflowSummary();
  });
  $('workflowAvModelSelect')?.addEventListener('change', updateWorkflowModelControls);
  $('workflowMapSelect')?.addEventListener('change', updateWorkflowSummary);
  $('workflowMapPreviewBtn')?.addEventListener('click', previewWorkflowMap);
  $('workflowCameraConfigBtn')?.addEventListener('click', openWorkflowCameraConfig);
  $('workflowCameraAddBtn')?.addEventListener('click', () => setWorkflowCameraEnabled(true));
  $('workflowCameraDeleteBtn')?.addEventListener('click', () => setWorkflowCameraEnabled(false));
  $('workflowCameraSaveBtn')?.addEventListener('click', saveWorkflowCameraConfig);
  $('metricLibraryBtn')?.addEventListener('click', () => bootstrap.Modal.getOrCreateInstance($('metricLibraryModal')).show());
  $('evaluationLibraryBtn')?.addEventListener('click', openEvaluationLibrary);
  $('applyEvaluationSystemBtn')?.addEventListener('click', () => applyEvaluationSystem(true));
  $('copyEvaluationSystemBtn')?.addEventListener('click', copyEvaluationSystem);
  $('saveEvaluationSystemBtn')?.addEventListener('click', saveEvaluationSystem);
  $('deleteEvaluationSystemBtn')?.addEventListener('click', deleteEvaluationSystem);
  $('evaluationSystemSelect')?.addEventListener('change', event => {
    const system = evaluationSystemRecords.find(item => item.id === event.target.value);
    if (system) loadEvaluationSystemEditor(system);
  });
  [
    'evaluationSafetyEnabled', 'evaluationComfortEnabled', 'evaluationEfficiencyEnabled',
    'evaluationSafetyModalWeight', 'evaluationComfortModalWeight', 'evaluationEfficiencyModalWeight',
  ].forEach(id => $(id)?.addEventListener('change', evaluationModalTotal));
  document.querySelectorAll('[data-evaluation-metric], [data-evaluation-metric-weight]').forEach(input => {
    input.addEventListener('change', evaluationModalTotal);
  });
  document.querySelectorAll('[data-workflow-target]').forEach(button => {
    button.addEventListener('click', () => {
      $(button.dataset.workflowTarget)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
  ['workflowDurationInput', 'workflowDreamsToggle', 'workflowMultimodalToggle'].forEach(id => {
    $(id)?.addEventListener('change', updateWorkflowSummary);
  });
  $('workflowMultimodalToggle')?.addEventListener('change', event => {
    if ($('workflowDreamsToggle')) {
      $('workflowDreamsToggle').disabled = !event.target.checked;
      if (!event.target.checked) $('workflowDreamsToggle').checked = false;
    }
    if ($('workflowWorldPromptInput')) $('workflowWorldPromptInput').disabled = !event.target.checked;
    updateWorkflowSummary();
  });
  $('workflowOpenWorkbenchBtn')?.addEventListener('click', () => openWorkflowWorkbench(false));
  $('workflowLaunchBtn')?.addEventListener('click', () => openWorkflowWorkbench(true));
  $('loginNavBtn')?.addEventListener('click', () => setAppMode('login'));
  $('logoutBtn')?.addEventListener('click', async () => {
    await logout();
    showToast(t('toast.logoutOk'), true);
  });
  $('loginSubmitBtn')?.addEventListener('click', async () => {
    try {
      await login($('loginUsernameInput')?.value?.trim() || '', $('loginPasswordInput')?.value || '');
      showToast(t('toast.loginOk'), true);
      setAppMode('home');
      await startRuntime();
    } catch (err) {
      showToast(`${t('toast.actionFail')}: ${err.message}`, false);
    }
  });
  $('registerSubmitBtn')?.addEventListener('click', async () => {
    try {
      const username = $('registerUsernameInput')?.value?.trim() || '';
      const password = $('registerPasswordInput')?.value || '';
      const res = await fetch(apiUrl('/auth/register'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok || j.ok === false) throw new Error(j.error || `HTTP ${res.status}`);
      $('registerPasswordInput').value = '';
      showToast(t('toast.registerOk'), true);
    } catch (err) {
      showToast(`${t('toast.actionFail')}: ${err.message}`, false);
    }
  });
  $('adminCreateUserBtn')?.addEventListener('click', async () => {
    try { await createAdminUser(); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
  });
  $('refreshSecurityBtn')?.addEventListener('click', () => loadSecurityAdmin(true));
  $('securityEventFilter')?.addEventListener('change', () => loadSecurityAdmin());
  $('adminUsersBody')?.addEventListener('change', async e => {
    const select = e.target.closest('.admin-role-select');
    if (!select) return;
    try {
      await adminUserAction({ type: 'set_role', user_id: select.dataset.userId, role: select.value });
    } catch (err) {
      showToast(`${t('toast.actionFail')}: ${err.message}`, false);
      renderAdminUsers();
    }
  });
  $('adminUsersBody')?.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-user-action]');
    if (!btn) return;
    const action = btn.dataset.userAction;
    const userId = btn.dataset.userId;
    try {
      if (action === 'reset_password') {
        const password = window.prompt(t('security.newPassword'));
        if (!password) return;
        await adminUserAction({ type: 'reset_password', user_id: userId, password });
      } else if (action === 'set_enabled') {
        if (!confirmHighRisk()) return;
        await adminUserAction({ type: 'set_enabled', user_id: userId, enabled: btn.dataset.enabled === 'true' });
      } else if (action === 'delete_user') {
        if (!confirmHighRisk()) return;
        await adminUserAction({ type: 'delete_user', user_id: userId });
      }
    } catch (err) {
      showToast(`${t('toast.actionFail')}: ${err.message}`, false);
    }
  });

  startConfiguredExperiment = async () => {
    const workflowConfig = selectedWorkflowId ? workflowFormValue() : null;
    const workflowScenario = workflowConfig?.scenario_mode === 'library'
      ? selectedStandardScenario()
      : null;
    const map = workflowScenario?.map_path || $('mapSelect').value;
    if (!map) {
      showToast('请选择地图后再启动实验', false);
      return;
    }
    const backendModel = $('trafficModelSelect')?.value || 'cnde';
    const requestedInitMode = $('initModeSelect')?.value || 'random_tl_only';
    const initMode = workflowScenario
      ? (backendModel === 'neuralnde' ? 'official_dataset' : 'data')
      : (workflowConfig?.multimodal_enabled && requestedInitMode === 'random_tl_only'
        ? 'random'
        : requestedInitMode);
    const needsInitData = ['cnde', 'rulebased'].includes(backendModel)
      && (initMode === 'data' || initMode === 'data_random_tl');
    const initFile = needsInitData
      ? (workflowScenario?.path || $('initDataSelect')?.value || '')
      : '';
    const experimentName = $('experimentNameStartInput')?.value?.trim() || '';
    const gpuId = $('gpuIdInput')?.value?.trim() || '0';
    const runUntilStopped = !!$('runUntilStoppedToggle')?.checked;
    const maxSimTime = runUntilStopped
      ? 0
      : Math.max(1, parseFloat($('totalStepInput')?.value || '1000') || 1000);
    const totalStep = runUntilStopped
      ? 0
      : Math.max(1, Math.ceil(maxSimTime / Math.max(simStepSeconds || 0.1, 1e-6)));
    const avEnabled = !!$('avAccessToggle')?.checked;
    const avControlModel = $('avControlModelSelect')?.value || 'DEFAULT_TCP';
    const requestedAvSelectionMode = $('avSelectionModeSelect')?.value || 'manual';
    const avSelectionMode = workflowConfig?.scenario_mode === 'map'
      && requestedAvSelectionMode === 'manual'
      ? 'random'
      : requestedAvSelectionMode;
    const avCommandMode = $('avCommandModeSelect')?.value || 'state';
    const rawAvControlPort = ($('avControlPortInput')?.value || '').trim();
    const avControlPort = rawAvControlPort ? parseInt(rawAvControlPort, 10) : NaN;
    const vtdBridgePort = parseInt($('vtdBridgePortInput')?.value || '10010', 10);
    const carlaEnabled = false;
    const carlaGpuId = Math.max(0, parseInt($('carlaGpuInput')?.value || '1', 10) || 0);
    const worldEnabled = ['cnde', 'neuralnde', 'rulebased'].includes(backendModel) && (
      workflowConfig ? workflowConfig.multimodal_enabled : $('multimodalModelSelect')?.value === 'denseworld'
    );
    const worldDurationMode = $('worldDurationSelect')?.value || 'follow';
    const worldFollowTraffic = worldDurationMode === 'follow';
    const worldDuration = worldFollowTraffic
      ? maxSimTime
      : Math.max(0.1, parseFloat(
        worldDurationMode === 'custom' ? $('worldCustomDurationInput')?.value : worldDurationMode,
      ) || 15);
    const stabilizeLongWorldVideo = worldEnabled && worldDuration >= 30;
    const worldTransferSteps = Math.max(1, parseInt($('worldTransferStepsSelect')?.value || '35', 10) || 35);
    const worldSeedMode = 'multiview_quality';
    const scenarioCount = runUntilStopped
      ? 1
      : Math.max(1, Math.min(1000, parseInt($('scenarioCountInput')?.value || '1', 10) || 1));
    const mixedTrafficEnabled = backendModel === 'cnde' && !!$('mixedTrafficToggle')?.checked;
    const cyclistRatio = Math.max(0, Math.min(0.5, parseFloat($('cyclistRatioSelect')?.value || '0.08') || 0));
    const pedestriansPerCrosswalk = Math.max(0, Math.min(4, parseInt($('pedestrianDensitySelect')?.value || '2', 10) || 0));
    if (needsInitData && !initFile) {
      showToast('请选择初始化数据文件', false);
      return;
    }
    try {
      const startPayload = {
        type: 'start_experiment',
        backend_model: backendModel,
        map_path: map,
        init_mode: initMode,
        init_file: initFile,
        standard_scenario_path: workflowScenario?.path || undefined,
        experiment_name: experimentName,
        gpu_id: gpuId,
	        total_step: totalStep,
        max_sim_time: maxSimTime,
        run_until_stopped: runUntilStopped,
        scenario_count: scenarioCount,
        seed: selectedWorkflowId ? Math.max(0, Number($('workflowSeedInput')?.value || 42)) : undefined,
        save_test_result: selectedWorkflowId ? !!$('workflowSaveResultToggle')?.checked : undefined,
        mixed_traffic_enabled: backendModel === 'cnde' ? mixedTrafficEnabled : undefined,
        cyclist_ratio: mixedTrafficEnabled ? cyclistRatio : undefined,
        pedestrians_per_crosswalk: mixedTrafficEnabled ? pedestriansPerCrosswalk : undefined,
        max_pedestrians: backendModel === 'cnde'
          ? Number(workflowConfig?.max_pedestrians ?? 8)
          : undefined,
        vehicle_size_mode: mixedTrafficEnabled ? ($('vehicleSizeModeSelect')?.value || 'mixed') : undefined,
        initial_speed_mode: mixedTrafficEnabled ? ($('initialSpeedModeSelect')?.value || 'urban_sampled') : undefined,
        av_enabled: avEnabled,
        av_control_model: avControlModel,
        av_selection_mode: ['cnde', 'neuralnde', 'rulebased'].includes(backendModel) && avEnabled ? avSelectionMode : undefined,
        av_command_mode: ['cnde', 'neuralnde', 'rulebased'].includes(backendModel) && avEnabled ? avCommandMode : undefined,
        av_control_host: avEnabled ? ($('avControlHostInput')?.value || '127.0.0.1') : undefined,
        av_control_port: avEnabled && Number.isFinite(avControlPort) ? avControlPort : undefined,
        rule_desired_speed_mps: backendModel === 'rulebased'
          ? Number(workflowConfig?.rule_desired_speed_mps ?? 10)
          : undefined,
        av_desired_speed_mps: avEnabled && avControlModel === 'IDM_MOBIL'
          ? Number(workflowConfig?.av_desired_speed_mps ?? 19.44)
          : undefined,
        workflow_id: selectedWorkflowId || undefined,
        workflow_name: selectedWorkflowId ? ($('workflowNameInput')?.value?.trim() || undefined) : undefined,
        task_id: selectedWorkflowId ? 'DW-TASK-0001' : undefined,
        evaluation_config: selectedWorkflowId ? {
          ...workflowFormValue().evaluation,
          metrics: workflowFormValue().evaluation_metrics,
          system_id: workflowFormValue().evaluation_system_id,
          system_name: workflowFormValue().evaluation_system_name,
        } : undefined,
        observations: selectedWorkflowId ? workflowFormValue().observations : undefined,
        camera_config: selectedWorkflowId ? workflowFormValue().camera_config : undefined,
        enable_3d_simulation: carlaEnabled,
        carla_quality: carlaEnabled ? ($('carlaQualitySelect')?.value || 'Epic') : undefined,
        carla_gpu_id: carlaEnabled ? String(carlaGpuId) : undefined,
	        world_generation_enabled: worldEnabled,
	        warmup_seconds: worldEnabled ? 1.0 : undefined,
	        world_video_duration: worldEnabled ? worldDuration : undefined,
	        world_video_follow_traffic: worldEnabled ? worldFollowTraffic : undefined,
        scenario_execution_mode: workflowScenario?.path
          ? (workflowConfig?.scenario_execution_mode || 'continue')
          : 'continue',
        world_local_target_count: ['cnde', 'rulebased'].includes(backendModel)
          ? Number(workflowConfig?.world_local_target_count ?? (backendModel === 'rulebased' ? 8 : 16))
          : undefined,
        world_initial_vehicle_limit: ['cnde', 'rulebased'].includes(backendModel)
          ? Number(workflowConfig?.world_initial_vehicle_limit ?? (backendModel === 'rulebased' ? 8 : 18))
          : undefined,
        world_omnidreams_actor_max_count: worldEnabled
          ? Number(workflowConfig?.world_omnidreams_actor_max_count ?? 16)
	          : undefined,
	        world_transfer_steps: worldEnabled ? worldTransferSteps : undefined,
	        world_transfer_seed: worldEnabled
	          ? Number(workflowConfig?.world_transfer_seed ?? 0)
	          : undefined,
	        world_omnidreams_seed: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_seed ?? workflowScenario?.world_omnidreams_seed ?? 1)
	          : undefined,
	        world_seed_mode: worldEnabled ? worldSeedMode : undefined,
	        world_seed_alignment_mode: worldEnabled
	          ? (workflowConfig?.world_seed_alignment_mode || $('workflowSeedAlignmentSelect')?.value || 'terminal_continue')
	          : undefined,
	        world_seed_backend: worldEnabled
	          ? (workflowConfig?.world_seed_backend || $('workflowSeedBackendSelect')?.value || 'transfer1')
	          : undefined,
	        world_loop_ego: typeof workflowConfig?.world_loop_ego === 'boolean'
	          ? workflowConfig.world_loop_ego
	          : (typeof workflowScenario?.world_loop_ego === 'boolean'
	            ? workflowScenario.world_loop_ego
	            : (stabilizeLongWorldVideo && avControlModel === 'IDM_MOBIL' ? true : undefined)),
	        world_ego_speed_cap_mps: worldEnabled
	          ? Number(workflowConfig?.world_ego_speed_cap_mps ?? workflowScenario?.world_ego_speed_cap_mps ?? 0)
	          : undefined,
	        world_omnidreams_segment_seconds: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_segment_seconds ?? (stabilizeLongWorldVideo ? 0 : 0))
	          : undefined,
	        world_omnidreams_rollover_mode: worldEnabled
	          ? String(workflowConfig?.world_omnidreams_rollover_mode || 'latest')
	          : undefined,
	        world_omnidreams_anchor_mode: worldEnabled
	          ? String(workflowConfig?.world_omnidreams_anchor_mode || 'conditioned_front')
	          : undefined,
	        world_omnidreams_anchor_transfer_steps: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_anchor_transfer_steps ?? 12)
	          : undefined,
	        world_omnidreams_anchor_transfer_seed: worldEnabled
	          ? Number(
	            workflowConfig?.world_omnidreams_anchor_transfer_seed
	              ?? workflowConfig?.world_transfer_seed
	              ?? 0
	          )
	          : undefined,
	        world_omnidreams_transition_frames: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_transition_frames ?? 0)
	          : undefined,
	        world_omnidreams_rollover_chroma_blur_radius: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_rollover_chroma_blur_radius ?? 0)
	          : undefined,
	        world_omnidreams_rollover_saturation_percent: worldEnabled
	          ? Number(workflowConfig?.world_omnidreams_rollover_saturation_percent ?? 100)
	          : undefined,
	        world_omnidreams_rollover_image_format: worldEnabled
	          ? String(workflowConfig?.world_omnidreams_rollover_image_format || 'jpeg')
	          : undefined,
	        world_stationary_anchor_enabled: worldEnabled
	          ? !!workflowConfig?.world_stationary_anchor_enabled
	          : undefined,
	        world_stationary_speed_threshold_mps: worldEnabled
	          ? Number(workflowConfig?.world_stationary_speed_threshold_mps ?? 0.35)
	          : undefined,
	        world_stationary_exit_speed_mps: worldEnabled
	          ? Number(workflowConfig?.world_stationary_exit_speed_mps ?? 0.8)
	          : undefined,
	        world_stationary_enter_seconds: worldEnabled
	          ? Number(workflowConfig?.world_stationary_enter_seconds ?? 0.75)
	          : undefined,
	        world_stationary_reset_seconds: worldEnabled
	          ? Number(workflowConfig?.world_stationary_reset_seconds ?? 6)
	          : undefined,
	        world_seed_map_radius_m: worldEnabled
	          ? Math.max(60, Math.min(150, Number(
	            workflowConfig?.world_seed_map_radius_m
	              ?? workflowScenario?.world_seed_map_radius_m
	              ?? $('worldSeedRadiusSelect')?.value
	              ?? 90,
	          ) || 90))
	          : undefined,
	        world_seed_image: worldEnabled ? ($('worldSeedImageInput')?.value?.trim() || undefined) : undefined,
		        world_use_existing_seed: worldEnabled && selectedWorkflowId
		          ? (typeof workflowConfig?.use_existing_seed === 'boolean'
		            ? workflowConfig.use_existing_seed
		            : (workflowConfig?.scenario_execution_mode || 'continue') === 'replay')
		          : undefined,
	        world_use_cached_appearance_anchor: worldEnabled ? false : undefined,
	        world_transfer_two_stage_seed: worldEnabled ? false : undefined,
	        world_transfer_full_enabled: worldEnabled ? !!$('worldTransferFullToggle')?.checked : undefined,
	        world_dreams_enabled: worldEnabled
	          ? (workflowConfig ? workflowConfig.dreams_enabled : !!$('worldDreamsToggle')?.checked)
	          : undefined,
	        world_prompt: worldEnabled
	          ? (workflowConfig?.world_prompt || $('worldPromptInput')?.value?.trim() || DEFAULT_WORLD_PROMPT)
	          : undefined,
	        world_transfer_prompt: worldEnabled
	          ? (workflowScenario?.default_transfer_prompt || undefined)
	          : undefined,
	        world_transfer_negative_prompt: worldEnabled
	          ? (workflowScenario?.default_transfer_negative_prompt || undefined)
	          : undefined,
	        ...currentArrivalRatePayload(),
	        ...(workflowConfig ? {
	          arrival_rate: Number(workflowConfig.arrival_rate ?? 0),
	          arrival_rates: {},
	        } : {}),
	      };
      const res = managerBase
        ? await managerPost('/action', startPayload)
        : await sendAction(startPayload);
      resetMetricHistories();
      mapData = null; simData = null; await pollMapState(true);
      showToast(res?.batch ? `${t('toast.experimentStarted')} · ${res.batch.scenario_count}` : t('toast.experimentStarted'), true);
      if (res?.viewer_url || res?.experiment?.port) {
        openViewer(res.experiment || res.viewer_url, isReplayLikeKind(res?.experiment?.kind) ? res.experiment.kind : 'experiment');
        return;
      }
      await loadExperiments();
    } catch (error) {
      showToast(`${t('toast.actionFail')}: ${error.message}`, false);
      await loadExperiments();
    }
  };
  $('startExperimentBtn').addEventListener('click', startConfiguredExperiment);

  $('startPlaybackBtn').addEventListener('click', async () => {
    const select = $('scenarioSelect');
    const scenario = select.value;
    if (!scenario) { showToast('请先选择场景文件', false); return; }
    if (select.selectedOptions?.[0]?.disabled) {
      showToast('该数据当前不支持回放', false);
      return;
    }
    try {
      resetMetricHistories();
      replayMetrics = null;
      replayTotalSteps = 0;
      replayCurrentStep = 0;
      replayAutoplayPending = true;
      simData = null;
      requestDrawFrame();
      const gpuId = $('gpuIdInput')?.value?.trim() || '0';
      const res = await sendAction({ type: 'start_playback', scenario, gpu_id: gpuId });
      showToast(res?.loading ? t('status.playbackLoading') : t('toast.playbackStarted'), true);
      if (res?.viewer_url || res?.experiment?.port) {
        openViewer(res.experiment || res.viewer_url, 'replay');
        return;
      }
      if (!res?.loading) {
        await replaySeek(0);
        startReplayAutoPlay();
      }
    } catch (error) {
      replayAutoplayPending = false;
      showToast(`回放启动失败：${error.message}`, false);
    }
  });

  $('startOfflineTestBtn')?.addEventListener('click', async () => {
    const select = $('scenarioSelect');
    const scenario = select.value;
    if (!scenario) { showToast('请先选择场景文件', false); return; }
    if (select.selectedOptions?.[0]?.disabled) {
      showToast('该数据当前不支持离线测试', false);
      return;
    }
    try {
      resetMetricHistories();
      replayMetrics = null;
      replayTotalSteps = 0;
      replayCurrentStep = 0;
      replayAutoplayPending = false;
      if (!offlineAvId && selectedVehicleId) offlineAvId = selectedVehicleId;
      if (!offlineAvId && simData?.vehicles?.length) chooseDefaultOfflineAv(simData.vehicles);
      if (simData) {
        simData = applyOfflineAvToSimState(simData);
        requestDrawFrame();
      }
      const res = await sendAction(offlineActionPayload('start_offline_test', scenario));
      showToast(res?.loading ? t('status.playbackLoading') : t('toast.playbackStarted'), true);
      if (res?.viewer_url || res?.experiment?.port) {
        openViewer(res.experiment || res.viewer_url, 'offline');
        return;
      }
      if (!res?.loading) {
        if (res?.sim_state) applyReplaySeekResult(res, 0);
        else await replaySeek(0);
        startReplayAutoPlay();
      }
    } catch (_) {}
  });

  $('pauseResumeBtn').addEventListener('click', async () => {
    try {
      if (runState === 'playback') {
        if (lastStatus.paused) {
          try { await apiPost('/resume'); } catch (_) {}
          lastStatus.paused = false;
          startReplayAutoPlay();
        } else {
          stopReplayAutoPlay();
          try { await apiPost('/pause'); } catch (_) {}
          if (lastStatus) lastStatus.paused = true;
          await replaySeek(replayCurrentStep);
          loadReplayMetrics();
          scheduleChartUpdate(0);
        }
        return;
      }
      await apiPost(lastStatus.paused ? '/resume' : '/pause');
    } catch (_) {}
  });

  $('terminateBtn').addEventListener('click', async () => {
    if (runState === 'playback' || runState === 'playback_loading') {
      if (!confirmHighRisk()) return;
      stopReplayAutoPlay();
      try {
        await sendAction(withHighRiskConfirmation({ type: 'terminate_experiment', save_data: false }));
        replayTotalSteps = 0; replayCurrentStep = 0; replayMetrics = null; updateReplaySlider(); resetMetricHistories();
        showToast(t('toast.terminated'), true);
      } catch (_) {}
      return;
    }
    if ($('experimentNameInput')) $('experimentNameInput').value = $('experimentNameStartInput')?.value || '';
    bootstrap.Modal.getOrCreateInstance($('terminateModal')).show();
  });

  $('terminateSaveBtn').addEventListener('click', async () => {
    bootstrap.Modal.getInstance($('terminateModal'))?.hide();
    const experimentName = $('experimentNameInput')?.value?.trim() || '';
    if (!confirmHighRisk()) return;
    try { await sendAction(withHighRiskConfirmation({ type: 'terminate_experiment', save_data: true, experiment_name: experimentName })); showToast(t('toast.terminated'), true); await loadDataRecords(); } catch (_) {}
  });

  $('terminateDiscardBtn').addEventListener('click', async () => {
    bootstrap.Modal.getInstance($('terminateModal'))?.hide();
    if (!confirmHighRisk()) return;
    try { await sendAction(withHighRiskConfirmation({ type: 'terminate_experiment', save_data: false })); showToast(t('toast.terminated'), true); } catch (_) {}
  });
  $('completionConfirmBtn')?.addEventListener('click', () => {
    saveExperimentCompletionReview().catch(error => showToast(`实验结束处理失败：${error.message}`, false));
  });
  $('completionReportBtn')?.addEventListener('click', () => {
    if (completionReviewExperimentId) openExperimentReport(completionReviewExperimentId);
  });

  $('applyArrivalRateBtn').addEventListener('click', async () => {
    const lane = $('laneIdInput').value.trim() || 'all';
    const rate = parseFloat($('arrivalRateInput').value);
    if (!rememberArrivalRate(lane, rate)) return;
    if (isManagerBackend() && runState === 'idle') {
      showToast('到达率已保存，将随下一次场景生成实验生效', true);
      return;
    }
    try {
      await sendAction({ type: 'set_rate', lane_id: lane, prob: clampArrivalRate(rate) });
      showToast('到达率已更新', true);
    } catch (_) {}
  });

  $('clickMode').addEventListener('change', updateVehicleOpFromMode);
  $('vehicleIdInput').addEventListener('change', () => {
    const id = $('vehicleIdInput').value.trim();
    const v = (simData?.vehicles || []).find(x => String(x.id) === id);
    if (v) setDeleteCandidate(v);
    else if ($('clickMode').value === 'delete' && id) {
      pendingVehicleOp = { type: 'delete', vehicleId: id };
      $('confirmVehicleOpBtn').disabled = false;
      $('cancelVehicleOpBtn').disabled = false;
      setVehicleOpHint(`待删除车辆 ID: ${id}`);
    }
  });
  ['vehicleXInput', 'vehicleYInput', 'vehicleHeadingInput'].forEach(id => {
    $(id).addEventListener('input', syncPendingAddFromInputs);
  });
  $('cancelVehicleOpBtn').addEventListener('click', clearPendingVehicleOp);
  $('confirmVehicleOpBtn').addEventListener('click', async () => {
    if (!pendingVehicleOp) return;
    try {
      if (pendingVehicleOp.type === 'delete') {
        const id = String($('vehicleIdInput').value.trim() || pendingVehicleOp.vehicleId);
        await sendAction({ type: 'remove_vehicle', vehicle_id: id });
        selectedVehicleId = null;
      } else if (pendingVehicleOp.type === 'add') {
        syncPendingAddFromInputs();
        if (pendingVehicleOp.stage < 2) return;
        const spd = parseFloat($('vehicleSpeedInput').value) || 2.0;
        await sendAction({
          type: 'add_vehicle_manual',
          x: pendingVehicleOp.x,
          y: pendingVehicleOp.y,
          heading: degToRad(pendingVehicleOp.headingDeg),
          speed: spd,
        });
      }
      clearPendingVehicleOp();
      await pollSimState();
    } catch (_) {}
  });

  $('applyRegionByCoordBtn').addEventListener('click', () => {
    const x = parseFloat($('vehicleXInput').value), y = parseFloat($('vehicleYInput').value);
    const radius = Math.max(1, parseFloat($('regionRadiusInput').value) || 10);
    if (!isNaN(x) && !isNaN(y)) {
      const q = mapData ? worldToVirtual(x, y) : { x, y };
      const sz = virtualSize();
      infeasibleRegions.push({ nx: q.x / Math.max(sz.w, 1), ny: q.y / Math.max(sz.h, 1), radius, created_at: new Date().toISOString() });
      requestDrawFrame();
      sendAction({ type: 'set_infeasible_region', x, y, radius }).catch(() => {});
    }
  });

  $('clearRegionsBtn').addEventListener('click', () => {
    infeasibleRegions = [];
    requestDrawFrame();
    sendAction({ type: 'clear_infeasible_regions' }).catch(() => {});
  });

  $('refreshScenariosBtn').addEventListener('click', async () => {
    try { await sendAction({ type: 'refresh_scenarios' }); } catch (_) {}
    await loadScenarios();
  });

  $('dataManagerBtn').addEventListener('click', async () => {
    setAppMode('data');
    await loadDataRecords();
  });

  $('refreshDataBtn').addEventListener('click', () => loadDataRecords(true));
  $('refreshDataViewBtn')?.addEventListener('click', () => loadDataRecords(true));
  $('uploadDataBtn')?.addEventListener('click', () => {
    const input = $('dataUploadInput');
    if (!input) return;
    const natural = dataCatalogMode === 'natural';
    if (natural) {
      input.removeAttribute('accept');
      input.setAttribute('webkitdirectory', '');
      input.setAttribute('directory', '');
    } else {
      input.setAttribute('accept', '.pkl');
      input.removeAttribute('webkitdirectory');
      input.removeAttribute('directory');
    }
    input.click();
  });
  $('dataUploadInput')?.addEventListener('change', async e => {
    try {
      await uploadDataFiles(e.target.files);
      e.target.value = '';
    } catch (err) {
      showToast(`${t('toast.actionFail')}: ${err.message}`, false);
    }
  });
  $('downloadSelectedDataBtn')?.addEventListener('click', async () => {
    try { await downloadSelectedData(); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
  });
  $('deleteSelectedDataBtn')?.addEventListener('click', async () => {
    try { await deleteScenarioPaths(Array.from(selectedDataPaths)); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
  });
  document.querySelectorAll('[data-data-sort]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.dataSort || 'modified';
      dataSort = {
        key,
        dir: dataSort.key === key && dataSort.dir === 'asc' ? 'desc' : 'asc',
      };
      renderDataRecords();
    });
  });
  ['dataSelectAll', 'dataModalSelectAll'].forEach(id => {
    $(id)?.addEventListener('change', e => {
      const writableVisibleRecords = dataCatalogRecords().filter(record => (
        !record.read_only && String(record.path || record).endsWith('.pkl')
      ));
      selectedDataPaths = e.target.checked
        ? new Set(writableVisibleRecords.map(record => record.path || record))
        : new Set();
      renderDataRecords();
    });
  });

  const handleDataTableClick = async e => {
    const btn = e.target.closest('button[data-data-action]');
    if (!btn) return;
    const path = btn.dataset.path || '';
    if (!path) return;
    if (btn.dataset.dataAction === 'download-natural') {
      try {
        await downloadNaturalDataset(btn.dataset.datasetId || '');
      } catch (error) {
        showToast(`目录下载失败：${error.message}`, false);
      }
    } else if (btn.dataset.dataAction === 'browse-natural') {
      try {
        await openNaturalDatasetBrowser(btn.dataset.datasetId || '');
      } catch (error) {
        showToast(`目录浏览失败：${error.message}`, false);
      }
    } else if (btn.dataset.dataAction === 'video') {
      const experiment = experimentRecords.find(record => String(record.id || '') === String(btn.dataset.experimentId || ''));
      if (!experiment) {
        showToast('该数据没有可查看的视频关联', false);
        return;
      }
      try {
        await openExperimentVideoPreview(experiment);
      } catch (error) {
        $('mediaPreviewLoading').textContent = `视频载入失败：${error.message}`;
        $('mediaPreviewLoading').hidden = false;
        showToast(`视频载入失败：${error.message}`, false);
      }
    } else if (btn.dataset.dataAction === 'traffic-preview') {
      const record = dataRecords.find(item => String(item.path || item) === path) || { path };
      try {
        await openScenarioTrafficPreview(record);
      } catch (error) {
        $('mediaPreviewLoading').textContent = `交通流载入失败：${error.message}`;
        $('mediaPreviewLoading').hidden = false;
        showToast(`交通流载入失败：${error.message}`, false);
      }
    } else if (btn.dataset.dataAction === 'replay') {
      if (runState !== 'idle') { showToast(`${t('toast.actionFail')}: ${runState}`, false); return; }
      ensureScenarioOption(path);
      bootstrap.Modal.getInstance($('dataManagerModal'))?.hide();
      try {
        setAppMode('replay');
        resetMetricHistories();
        replayMetrics = null;
        replayTotalSteps = 0;
        replayCurrentStep = 0;
        replayAutoplayPending = true;
        simData = null;
        requestDrawFrame();
        const gpuId = $('gpuIdInput')?.value?.trim() || '0';
        const res = await sendAction({ type: 'start_playback', scenario: path, gpu_id: gpuId });
        showToast(res?.loading ? t('status.playbackLoading') : t('toast.playbackStarted'), true);
        if (res?.viewer_url || res?.experiment?.port) {
          openViewer(res.experiment || res.viewer_url, 'replay');
          return;
        }
        if (!res?.loading) {
          await replaySeek(0);
          startReplayAutoPlay();
        }
      } catch (error) {
        replayAutoplayPending = false;
        setAppMode('data');
        showToast(`回放启动失败：${error.message}`, false);
      }
    } else if (btn.dataset.dataAction === 'download') {
      try { await downloadScenario(path); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
    } else if (btn.dataset.dataAction === 'rename') {
      try { await renameScenario(path); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
    } else if (btn.dataset.dataAction === 'delete') {
      try { await deleteScenarioPaths([path]); } catch (err) { showToast(`${t('toast.actionFail')}: ${err.message}`, false); }
    }
  };
  document.querySelectorAll('[data-records-body]').forEach(body => {
    body.addEventListener('click', handleDataTableClick);
    body.addEventListener('change', e => {
      const check = e.target.closest('.data-row-check');
      if (!check) return;
      const path = check.dataset.path;
      if (check.checked) selectedDataPaths.add(path);
      else selectedDataPaths.delete(path);
      renderDataRecords();
    });
  });
  $('dataGridRecords')?.addEventListener('click', event => {
    const modeButton = event.target.closest('[data-data-record-mode]');
    if (modeButton) {
      dataRecordModes.set(modeButton.dataset.path, modeButton.dataset.dataRecordMode);
      renderDataRecords();
      return;
    }
    handleDataTableClick(event);
  });
  document.querySelectorAll('[data-data-catalog]').forEach(button => {
    button.addEventListener('click', () => selectDataCatalog(button.dataset.dataCatalog));
  });
  $('dataListViewBtn')?.addEventListener('click', () => {
    dataViewMode = 'list';
    renderDataViewMode();
  });
  $('dataGridViewBtn')?.addEventListener('click', () => {
    dataViewMode = 'grid';
    renderDataViewMode();
  });
  $('dataTrafficContentBtn')?.addEventListener('click', () => {
    dataContentMode = 'traffic';
    renderDataRecords();
    renderDataViewMode();
  });
  $('dataVideoContentBtn')?.addEventListener('click', () => {
    dataContentMode = 'video';
    dataViewMode = 'grid';
    renderDataRecords();
    renderDataViewMode();
  });
  $('dataTransferDatabaseSelect')?.addEventListener('change', updateDataTransferScenarioOptions);
  ['dataTransferScenarioSelect', 'dataTransferStartInput', 'dataTransferEndInput', 'dataTransferViewSelect'].forEach(id => {
    $(id)?.addEventListener('change', updateDataTransferHint);
  });
  $('dataTransferGenerateBtn')?.addEventListener('click', submitDataTransfer);
  $('dataStandardSourceSelect')?.addEventListener('change', updateStandardScenarioBuilderHint);
  $('dataStandardSourceDatabaseSelect')?.addEventListener('change', updateStandardScenarioSourceOptions);
  ['dataStandardStartInput', 'dataStandardEndInput'].forEach(id => {
    $(id)?.addEventListener('input', updateStandardScenarioBuilderHint);
  });
  $('dataStandardGenerateBtn')?.addEventListener('click', submitStandardScenario);
  $('dataStandardImportBtn')?.addEventListener('click', () => $('dataStandardImportInput')?.click());
  $('dataStandardImportInput')?.addEventListener('change', async event => {
    try {
      await importStandardScenarioFiles(event.target.files);
      event.target.value = '';
    } catch (error) {
      showToast(`标准场景导入失败：${error.message}`, false);
    }
  });
  $('naturalDatasetUpBtn')?.addEventListener('click', () => {
    const parts = naturalBrowserPath.split('/').filter(Boolean);
    parts.pop();
    loadNaturalDatasetLevel(parts.join('/')).catch(error => showToast(`目录浏览失败：${error.message}`, false));
  });
  $('naturalDatasetDownloadBtn')?.addEventListener('click', () => {
    downloadNaturalDataset(naturalBrowserDatasetId, naturalBrowserPath).catch(error => showToast(`目录下载失败：${error.message}`, false));
  });
  $('naturalDatasetUploadBtn')?.addEventListener('click', () => $('naturalDatasetUploadInput')?.click());
  $('naturalDatasetUploadInput')?.addEventListener('change', async event => {
    try {
      await uploadNaturalDatasetLevel(event.target.files);
      event.target.value = '';
    } catch (error) {
      showToast(`目录上传失败：${error.message}`, false);
    }
  });
  $('naturalDatasetEntriesBody')?.addEventListener('click', event => {
    const button = event.target.closest('button[data-natural-action]');
    if (!button) return;
    if (button.dataset.naturalAction === 'open') {
      loadNaturalDatasetLevel(button.dataset.path || '').catch(error => showToast(`目录浏览失败：${error.message}`, false));
    } else {
      downloadNaturalDataset(naturalBrowserDatasetId, button.dataset.path || '').catch(error => showToast(`文件下载失败：${error.message}`, false));
    }
  });
  $('dataAccidentCandidateList')?.addEventListener('click', event => {
    const button = event.target.closest('button[data-accident-action]');
    if (button) handleAccidentCandidateAction(button.dataset.id, button.dataset.accidentAction);
  });

  document.querySelectorAll('[data-app-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetMode = btn.dataset.appMode;
      if (targetMode === 'generate') workflowScenarioConfigurationLocked = false;
      if (isManagedChildSession()) {
        const url = managerViewUrl(targetMode);
        if (url) {
          window.location.assign(url);
          return;
        }
      }
      setAppMode(targetMode);
    });
  });

  $('refreshExperimentsBtn')?.addEventListener('click', loadExperiments);
  $('downloadExperimentReportBtn')?.addEventListener('click', downloadCurrentExperimentReport);
  $('experimentsView')?.addEventListener('mousedown', e => {
    if (e.target.closest('button,input,select,label')) return;
    experimentsSelectionHoldUntil = performance.now() + 4000;
  });
  $('experimentsView')?.addEventListener('mouseup', () => {
    experimentsSelectionHoldUntil = performance.now() + 1500;
  });
  document.querySelectorAll('[data-experiment-select-all]').forEach(input => input.addEventListener('change', e => {
    const group = e.target.dataset.experimentSelectAll;
    const targets = visibleExperimentRecords.filter(record => {
      const kind = isReplayLikeKind(record.kind || 'experiment') ? 'replay' : 'generation';
      return kind === group;
    });
    targets.forEach(record => {
      const id = String(record.id || 'current');
      if (e.target.checked) selectedExperimentIds.add(id);
      else selectedExperimentIds.delete(id);
    });
    renderExperimentRecords();
  }));
  $('experimentsView')?.addEventListener('change', e => {
    const check = e.target.closest('.experiment-row-check');
    if (!check) return;
    if (check.checked) selectedExperimentIds.add(check.dataset.id);
    else selectedExperimentIds.delete(check.dataset.id);
  });
  $('experimentsView')?.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-experiment-action]');
    if (!btn) return;
    const id = String(btn.dataset.id || '');
    const record = visibleExperimentRecords.find(r => String(r.id || 'current') === id) || {};
    if (btn.dataset.experimentAction === 'delete') {
      try {
        await deleteExperimentIds([id]);
      } catch (_) {}
      return;
    }
    if (btn.dataset.experimentAction === 'report') {
      await openExperimentReport(id);
      return;
    }
    if (btn.dataset.experimentAction === 'review') {
      await openExperimentCompletionReview(record);
      return;
    }
    try {
      await viewExperimentRecord(record, {
        newTab: !!(e.ctrlKey || e.metaKey || e.shiftKey),
      });
    } catch (error) {
      showToast(`回放启动失败：${error.message}`, false);
    }
  });
  $('pauseSelectedExperimentsBtn')?.addEventListener('click', async () => {
    if (selectedExperimentIds.size === 0) return;
    try {
      if (isManagerBackend()) {
        await sendAction({ type: 'pause_experiments', experiment_ids: Array.from(selectedExperimentIds) });
      } else {
        await apiPost('/pause');
      }
      await loadExperiments();
    } catch (_) {}
  });
  $('terminateSelectedExperimentsBtn')?.addEventListener('click', async () => {
    if (selectedExperimentIds.size === 0) return;
    if (!confirmHighRisk()) return;
    try {
      await sendAction(withHighRiskConfirmation({ type: 'terminate_experiment', save_data: true, experiment_ids: Array.from(selectedExperimentIds) }));
      selectedExperimentIds.clear();
      await loadExperiments();
      await loadDataRecords();
      showToast(t('toast.terminated'), true);
    } catch (_) {}
  });
  $('deleteSelectedExperimentsBtn')?.addEventListener('click', async () => {
    try {
      await deleteExperimentIds(Array.from(selectedExperimentIds));
    } catch (_) {}
  });

  const setReplaySpeed = value => {
    const v = Math.max(0.1, Math.min(8, parseFloat(value) || 1));
    replaySpeed = v;
    $('replaySpeedSlider').value = String(v);
    $('replaySpeedInput').value = String(v);
    if (replayPlaying) resetReplayClock();
  };
  $('replaySpeedSlider').addEventListener('input', e => setReplaySpeed(e.target.value));
  $('replaySpeedInput').addEventListener('change', e => setReplaySpeed(e.target.value));

  // Replay slider (in settings panel — kept for compatibility)
  $('replaySlider').addEventListener('pointerdown', () => { replaySliderDragging = true; });
  $('replaySlider').addEventListener('pointerup', e => {
    replaySliderDragging = false;
    replayCurrentStep = parseInt(e.target.value, 10);
    updateReplaySlider();
    scheduleReplaySeek(replayCurrentStep, 0);
  });
  $('replaySlider').addEventListener('input', e => {
    stopReplayAutoPlay();
    replaySliderDragging = true;
    replayCurrentStep = parseInt(e.target.value, 10);
    updateReplaySlider();
    scheduleReplaySeek(replayCurrentStep, 80);
  });
  $('replaySlider').addEventListener('change', e => {
    replaySliderDragging = false;
    replayCurrentStep = parseInt(e.target.value, 10);
    updateReplaySlider();
    scheduleReplaySeek(replayCurrentStep, 0);
  });

  // Settings panel replay buttons
  $('replayPrevBtn').addEventListener('click', async () => { stopReplayAutoPlay(); replayCurrentStep = Math.max(0, replayCurrentStep - 1); await replaySeek(replayCurrentStep); });
  $('replayPlayBtn').addEventListener('click', toggleReplayPlay);
  $('replayNextBtn').addEventListener('click', async () => { stopReplayAutoPlay(); replayCurrentStep = Math.min(replayTotalSteps - 1, replayCurrentStep + 1); await replaySeek(replayCurrentStep); });

  // Timeline bar buttons (in traffic window)
  $('tlPrevBtn').addEventListener('click', async () => { stopReplayAutoPlay(); replayCurrentStep = Math.max(0, replayCurrentStep - 1); await replaySeek(replayCurrentStep); });
  $('tlPlayBtn').addEventListener('click', toggleReplayPlay);
  $('tlNextBtn').addEventListener('click', async () => { stopReplayAutoPlay(); replayCurrentStep = Math.min(replayTotalSteps - 1, replayCurrentStep + 1); await replaySeek(replayCurrentStep); });

  // Display toggles
  $('showVehicleIdToggle').addEventListener('change', async e => {
    try { await sendAction({ type: 'toggle_vehicle_id' }); } catch (_) {}
    requestDrawFrame();
  });

  const refreshReplayFrame = () => {
    if (runState === 'playback') {
      scheduleReplaySeek(replayCurrentStep, 0);
    } else {
      requestDrawFrame();
    }
  };

  $('showTrajectoryToggle').addEventListener('change', e => {
    $('showFutureTrajectoryToggle').checked = e.target.checked;
    $('showPastTrajectoryToggle').checked = e.target.checked;
    refreshReplayFrame();
  });
  $('showFutureTrajectoryToggle').addEventListener('change', refreshReplayFrame);
  $('showPastTrajectoryToggle').addEventListener('change', refreshReplayFrame);
  $('historyDurationInput').addEventListener('input', refreshReplayFrame);
  $('showTrafficLightToggle').addEventListener('change', drawFrame);
  $('mapBackgroundColorInput').addEventListener('input', e => {
    mapBackgroundColor = e.target.value || '#d8dde3';
    requestDrawFrame();
  });

  $('followVehicleToggle').addEventListener('change', e => {
    followSelectedVehicle = e.target.checked;
    if (followSelectedVehicle) centerOnSelectedVehicle();
    requestDrawFrame();
  });
  $('selectedTrajectoryOnlyToggle').addEventListener('change', refreshReplayFrame);
  $('clearSelectedVehicleBtn').addEventListener('click', () => {
    selectedVehicleId = null;
    focusCarlaVehicle('');
    followSelectedVehicle = false;
    $('followVehicleToggle').checked = false;
    $('selectedTrajectoryOnlyToggle').checked = false;
    updateSelectedVehiclePanel();
    if (runState === 'playback') scheduleReplaySeek(replayCurrentStep, 0);
    requestDrawFrame();
  });

  // Histogram visibility toggles
  $('histSpeedCheck').addEventListener('change', e => { $('histSpeedCard').hidden = !e.target.checked; updateCharts(); });
  $('histTTCCheck').addEventListener('change', e => { $('histTTCCard').hidden = !e.target.checked; updateCharts(); });
  $('histHeadwayCheck').addEventListener('change', e => { $('histHeadwayCard').hidden = !e.target.checked; updateCharts(); });

  document.querySelectorAll('.chart-openable').forEach(card => {
    card.addEventListener('click', () => openExpandedChart(card.dataset.chartKey));
  });
  ['chartXMinInput', 'chartXMaxInput', 'chartYMinInput', 'chartYMaxInput', 'chartBinSizeInput'].forEach(id => {
    $(id)?.addEventListener('input', renderExpandedChart);
  });
  $('chartResetBtn').addEventListener('click', () => { if (expandedChartKey) { resetExpandedControls(expandedChartKey); renderExpandedChart(); } });
  $('chartSaveBtn').addEventListener('click', saveExpandedChart);
  $('chartModal').addEventListener('hidden.bs.modal', () => {
    if (expandedChart) expandedChart.destroy();
    expandedChart = null;
    expandedChartKey = null;
  });

  // Language
  $('languageSelect').addEventListener('change', e => { lang = e.target.value; applyI18n(); });
  $('initModeSelect').addEventListener('change', updateInitModeControls);
  $('avAccessToggle')?.addEventListener('change', updateAvAccessControls);
  $('avControlModelSelect')?.addEventListener('change', updateAvAccessControls);
  $('confirmSelectAvBtn')?.addEventListener('click', async () => {
    if (!selectedVehicleId) return;
    try {
      const result = await sendAction({ type: 'select_av', vehicle_id: selectedVehicleId });
      showToast(`${t('av.selected')}: ${result.av_id || selectedVehicleId}`, true);
    } catch (_) {}
  });
  $('randomSelectAvBtn')?.addEventListener('click', async () => {
    try {
      const result = await sendAction({ type: 'random_select_av' });
      if (result.av_id) selectedVehicleId = String(result.av_id);
      renderOnlineAvState({ ...lastStatus, waiting_for_av_selection: false, av_id: result.av_id });
      requestDrawFrame();
    } catch (_) {}
  });
  $('carla3dToggle')?.addEventListener('change', updateCarlaConfigControls);
  $('mixedTrafficToggle')?.addEventListener('change', updateMixedTrafficControls);
  $('runUntilStoppedToggle')?.addEventListener('change', updateRunDurationControls);
  $('multimodalModelSelect')?.addEventListener('change', updateDenseWorldControls);
  $('worldDurationSelect')?.addEventListener('change', updateRunDurationControls);
  $('worldSeedModeSelect')?.addEventListener('change', updateDenseWorldControls);
  $('worldVideoSelect')?.addEventListener('change', renderWorldVideoOptions);
  $('worldVideoPlayBtn')?.addEventListener('click', () => $('worldVideoPlayer')?.play());
  $('worldVideoPauseBtn')?.addEventListener('click', () => $('worldVideoPlayer')?.pause());
  $('cosmosRestartBtn')?.addEventListener('click', () => restartCosmosServices());
  $('generateTransferReplayBtn')?.addEventListener('click', () => startTransferReplayGeneration().catch(() => {}));
  $('transferReplayStartInput')?.addEventListener('input', () => updateTransferReplayRange(dataRecordByPath.get($('scenarioSelect')?.value || '')));
  $('transferReplayEndInput')?.addEventListener('input', () => updateTransferReplayRange(dataRecordByPath.get($('scenarioSelect')?.value || '')));
  $('carlaOverviewBtn')?.addEventListener('click', () => focusCarlaVehicle(''));
  $('scenarioSelect')?.addEventListener('change', syncReplaySelectionMetadata);
  $('scenarioSearchInput')?.addEventListener('input', loadScenarios);
  $('trafficModelSelect')?.addEventListener('change', async () => {
    updateTrafficModelControls();
    mapData = null;
    simData = null;
    mapRasterImg = new Image();
    mapRasterLoaded = false;
    mapRasterSource = '';
    invalidateStaticMapLayer();
    await loadMaps();
    if (isReplayLikeMode()) await refreshScenariosForSelectedModel();
    requestDrawFrame();
  });
}

// ── Resize observer ───────────────────────────────────────────────────────────
function initResizeObserver() {
  new ResizeObserver(() => {
    resizeTrafficCanvas();
    requestDrawFrame();
  }).observe($('trafficViewport'));
}

// ── Main init ─────────────────────────────────────────────────────────────────
function startPollingLoop(pollFn, delayFn) {
  const tick = async () => {
    try {
      await pollFn();
    } finally {
      const delay = Math.max(0, Number(delayFn()) || 0);
      window.setTimeout(tick, delay);
    }
  };
  tick();
}

async function startRuntime() {
  if (runtimeStarted) return;
  runtimeStarted = true;
  await loadCapabilities();
  await loadMaps();
  await loadScenarios();
  await loadStandardScenarios();
  await loadWorkflows();
  if (appMode === 'home') await loadDashboard();
  updateInitModeControls();
  updateTrafficModelControls();
  await pollMapState(true);
  startPollingLoop(
    pollSimState,
    () => document.hidden ? 750 : (currentDetailMode() ? SIM_STATE_POLL_MS : 500),
  );
  startPollingLoop(
    pollFrame,
    () => document.hidden ? 1500 : (currentDetailMode() ? FRAME_POLL_MS : 1000),
  );
  startPollingLoop(
    pollStatus,
    () => document.hidden ? 1500 : (currentDetailMode() ? STATUS_POLL_MS : 750),
  );
  startPollingLoop(
    pollCarlaStatus,
    () => document.hidden ? 1500 : 500,
  );
  startPollingLoop(
    pollCarlaFrame,
    () => document.hidden ? 1500 : 100,
  );
  startPollingLoop(
    pollWorldStatus,
    () => document.hidden ? 5000 : 1000,
  );
  startPollingLoop(
    loadDashboard,
    () => document.hidden ? 10000 : (appMode === 'home' ? 2500 : 10000),
  );
  setInterval(() => {
    const minDelay = runState === 'playback' && replayPlaying ? PLAYBACK_CHART_UPDATE_MS : 5000;
    if (performance.now() - lastChartUpdateAt >= minDelay) updateCharts();
  }, 5000);
}

async function init() {
  await loadConfig();
  applyI18n();
  configureViewerWorkspace();
  initViewerPanels();
  initCharts();
  initWindowManagement();
  initZoomControls();
  initCanvasClick();
  initMaximize();
  initButtons();
  $('followEgoBtn')?.addEventListener('click', followEgoVehicle);
  $('viewExperimentConfigBtn')?.addEventListener('click', openExperimentConfig);
  initResizeObserver();
  const authOk = await refreshAuthState();
  if (!authOk) {
    setAppMode('login', false);
    return;
  }
  initAppModeFromUrl();
  try {
    await restoreManagedReplayIfNeeded();
  } catch (error) {
    showToast(`${t('toast.actionFail')}: ${error.message}`, false);
  }
  await startRuntime();
}

document.addEventListener('DOMContentLoaded', init);
window.addEventListener('pagehide', () => {
  if (carlaFrameUrl) URL.revokeObjectURL(carlaFrameUrl);
  if (!activeExperimentId || !managerBase || !isReplayLikeMode()) return;
  const payload = JSON.stringify({
    type: 'terminate_experiment',
    experiment_id: activeExperimentId,
    save_data: false,
  });
  fetch(managerApiUrl('/action'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: payload,
    keepalive: true,
  }).catch(() => {});
});
