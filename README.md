# 智能家居管理系统 (Smart Home Management System)

> 以安全和舒适为重点的智能家居系统原型 — 软件部分

## 项目概述

本项目为智能家居系统的数据访问软件部分，涵盖数据库/后端设计、物体识别、人脸识别门禁、Web GUI 及远程控制等全部软件要求。

## 功能与需求对照表

### 基本要求

| # | 要求 | 实现方式 | 对应模块 |
|---|------|----------|----------|
| 1 | 管理信息：存储和管理授权人员的信息 | SQLite 数据库 + SQLAlchemy ORM，支持增删改查 | 人员管理页面 `/persons` |
| 2 | 物体识别：YOLO 算法识别物体 | YOLOv8 (ultralytics)，默认加载定制权重 `models/yolo/best.pt`（drone / fire_extinguisher 两类），缺失时降级 `yolov8n.pt`（COCO 80 类）；支持图片上传和摄像头拍照 | 物体检测页面 `/detection` |
| 3 | 人脸识别开启门禁：至少2真1假 | InsightFace (buffalo_l) 人脸特征 + 余弦相似度比对，预置 2个真实授权 + 1个假身份 | 门禁管理页面 `/access` |
| 4 | GUI：显示信息 + 数据统计和分析 | Flask Web GUI + Chart.js 图表，支持温度/灯光/门/窗历史数据检索 | 仪表盘 `/` + 数据分析 `/analysis` |

### 附加功能

| # | 要求 | 实现方式 |
|---|------|----------|
| 5 | 远程控制：通过 GUI 远程控制灯、空调等 | REST API + WebSocket 实时推送；门（UNO II 门禁板）与风扇/灯带（UNO I 环境板）经串口直连，空调/窗户为软件模拟状态 |
| 6 | 自定义：摄像头检测到灯泡图片后控制灯 | YOLO 专用灯泡模型 `models/yolo/light_bulb.pt` 检测到灯泡后自动触发灯光开启（亮度80%） |

### 额外功能

- 温度超过阈值 (30°C) 自动开启风扇（与 UNO I 固件 FAN_ON_TEMP 保持一致）
- 启发式活体检测（基于清晰度/色彩/亮度，防照片伪造）
- 门窗状态实时监控
- 灯光亮度无级调节 (0-100%)
- **灯光专用记录表：追踪开关历史、亮度变化、使用时长、能耗统计、操作来源分析**
- **灯光数据分析：亮度趋势图、来源分布饼图、每日使用汇总（柱状图+折线图）**
- **哨兵模式：定时巡检 + 人形检测 + 人脸核验 + 连拍留证 + 告警推送（见下文）**
- **串口硬件对接：UNO 门禁板 / 环境板双串口自定义行协议（见下文）**
- WebSocket 实时数据推送
- 传感器数据模拟（无硬件时可运行）

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端框架 | Flask 3.0 + Flask-SocketIO 5.3 |
| 数据库 | SQLite + Flask-SQLAlchemy 3.1 |
| 物体检测 | YOLOv8 (ultralytics 8.3) + 定制权重 |
| 人脸识别 | InsightFace 1.0 (buffalo_l) + ONNX Runtime（余弦相似度比对） |
| 硬件通信 | pyserial 3.5（自定义行协议，门禁板/环境板双串口） |
| 前端 | HTML5 + CSS3 + JavaScript + Chart.js 4.4 |
| 实时通信 | WebSocket (Flask-SocketIO) |
| 图像处理 | OpenCV 4.10 + Pillow + NumPy |

## 项目结构

```
smart_home/
├── app.py                      # 主应用入口 (Flask + SocketIO)
├── config.py                   # 配置文件（哨兵/串口等均可环境变量覆盖）
├── models.py                   # 数据库模型 (7张表)
├── database.py                 # 数据库初始化与种子数据（硬件模式下不灌演示数据）
├── requirements.txt            # Python 依赖（开发/Windows）
├── requirements_orangepi.txt   # 香橙派精简依赖
├── start.bat                   # Windows 一键启动
├── start_win_camera.bat        # Windows 本机摄像头启动
├── SETUP.md                    # 环境配置详细说明（必读）
├── routes/
│   ├── api.py                  # REST API (10大模块, 43 接口)
│   └── pages.py                # 页面路由 (7个页面)
├── services/
│   ├── object_detection.py     # YOLO 物体检测服务
│   ├── face_recognition_service.py         # 人脸识别兼容层（转发到 InsightFace 实现）
│   ├── insightface_recognition_service.py  # InsightFace 识别实现
│   ├── insightface_backend.py  # InsightFace 模型加载与人脸检测
│   ├── face_gallery_scope.py   # 人脸特征库按数据库隔离
│   ├── device_manager.py       # 设备管理器 (灯/风扇/门/窗/空调)
│   ├── sensor_simulator.py     # 传感器模拟器 / 真实读数注入
│   ├── camera_stream.py        # 常驻摄像头采集线程（单路采集、按需分发）
│   ├── camera_capture.py       # 摄像头拍照辅助
│   ├── image_io.py             # 图像读写工具
│   ├── sentry_service.py       # 哨兵模式（巡检/核验/留证/告警）
│   ├── serial_bridge.py        # 串口通信层（协议解析/重试/重连，可脱离 Flask）
│   └── hardware_service.py     # 硬件对接胶水层（命令转发/事件归位）
├── templates/                  # Jinja2 HTML 模板（7 页 + base）
├── static/
│   ├── css/style.css           # 主样式
│   └── js/                     # common / dashboard / sentry / environment_controls
├── models/yolo/                # 定制 YOLO 权重 (best.pt / light_bulb.pt)
├── scripts/                    # 运维脚本
│   ├── download_face_models.py # 下载 InsightFace 模型
│   ├── flash_uno.py            # 烧录 UNO 固件
│   ├── hardware_preflight.py   # 硬件连线预检
│   ├── serial_probe.py         # 脱离 Flask 的串口探测
│   ├── launch_win_camera.py    # Windows 摄像头启动辅助
│   └── run_software_tests.py   # 纯软件测试入口（临时库、不碰硬件）
├── tests/                      # unittest 用例（22 个文件，串口/哨兵/硬件为主）
├── data/                       # SQLite 数据库 + 人脸特征库
├── uploads/                    # 上传文件 (detections / faces / sentry)
├── known_faces/                # 已注册人脸样本
├── face-recognition/           # 独立的本地人脸授权 CLI 子项目（自带 README）
└── 硬件代码/                   # Arduino 固件代码，需要烧录到对应硬件中，在这里仅作硬件逻辑参考（UNO I 环境板 / UNO II 门禁板）
```

## 快速开始

**详细安装步骤请阅读 [SETUP.md](SETUP.md)**

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 准备模型（首次）
python scripts/download_face_models.py   # InsightFace buffalo_l
# YOLO：models/yolo/ 下的 best.pt、light_bulb.pt 为定制权重（仓库自带）；
# yolov8n.pt 缺失时首次运行会自动下载（约 6MB）

# 5. 启动系统
python app.py

# 6. 浏览器打开 http://localhost:5000
```

## 使用指南

### 仪表盘 (/)
- 实时显示温度、灯光、门锁、窗户、风扇、空调状态
- 24小时温度趋势图（含风扇激活标记）
- 最近门禁记录和检测记录
- **灯光使用摘要卡片：今日开灯时长、能耗、操作次数、平均亮度**

### 门禁管理 (/access)
- 上传照片进行人脸识别开门（也可调摄像头拍照识别）
- 启发式活体检测防止照片伪造
- 门禁访问日志查询（支持按结果筛选）
- 授权人员状态概览（2真1假）

### 物体检测 (/detection)
- 上传图片使用 YOLOv8 检测物体（定制权重 / COCO 降级）
- 检测结果图片对比展示
- 检测到灯泡自动触发灯光控制
- 检测历史记录查询

### 哨兵模式 (/sentry)
- 布防/撤防、立即巡检、模拟入侵、解除告警
- 定时巡检：YOLO 人形检测 → InsightFace 人脸核验
- 未授权人员连续命中 N 轮升级为告警，连拍留证（快照 2fps 轮播回放）
- 告警同时推送到环境板 OLED；事件支持确认/误报/删除
- 详细策略与参数见下文「哨兵模式」

### 设备控制 (/devices)
- 灯光：开关 + 亮度滑块 (0-100%) + 快捷档位
- 风扇：开关 + 4档风速（含自动模式）
- 空调：开关 + 温度调节 (16-30°C)
- 门锁：开锁/锁定
- 窗户：打开/关闭
- 设备操作历史记录

### 人员管理 (/persons)
- 添加/编辑/删除授权人员
- 上传人脸照片注册人脸特征
- 标记身份类型：真实授权 / 伪造未授权
- 人脸注册状态查看

### 数据分析 (/analysis)
- 温度趋势图（平均/最高/最低）
- 湿度变化趋势
- **灯光亮度变化趋势图**
- **灯光操作来源分布饼图**
- **每日灯光使用汇总（柱状图+能耗折线图）**
- 设备状态统计图（柱状对比）
- 门禁访问统计（饼图）
- 温度数据明细表 + 灯光操作明细表
- 设备操作汇总表
- 支持时间范围筛选 (6h/12h/24h/48h/7天)

## API 文档

### 授权人员管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/persons` | 获取所有人员 |
| GET | `/api/persons/<id>` | 获取单个人员 |
| POST | `/api/persons` | 添加人员 |
| PUT | `/api/persons/<id>` | 更新人员 |
| DELETE | `/api/persons/<id>` | 删除人员 |
| POST | `/api/persons/<id>/register-face` | 注册人脸 |

### 人脸识别门禁
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/access/recognize` | 上传照片识别开门 |
| POST | `/api/access/camera` | 摄像头拍照识别开门 |
| GET | `/api/access/logs` | 门禁日志查询 |

### 物体检测
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/detection/upload` | 上传图片检测 |
| POST | `/api/detection/camera` | 摄像头拍照检测 |
| GET | `/api/detection/records` | 检测记录查询 |

### 设备控制
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/devices` | 获取所有设备状态 |
| GET | `/api/devices/<name>` | 获取单个设备 |
| POST | `/api/devices/<name>/control` | 控制设备 |
| POST | `/api/devices/<name>/toggle` | 切换设备开关 |
| POST | `/api/devices/light/brightness` | 设置灯光亮度 |

### 灯光记录
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/lighting/history` | 灯光操作历史 |
| GET | `/api/lighting/stats` | 灯光统计数据（时长/能耗/亮度/来源） |
| GET | `/api/lighting/daily-summary` | 每日灯光使用汇总 |

### 传感器数据
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sensor/current` | 当前传感器读数 |
| POST | `/api/sensor/inject` | 注入真实传感器数据 |

### 硬件状态
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/hardware/status` | 串口硬件状态（端口/协议/固件/计数器/最近事件） |
| POST | `/api/hardware/message` | 推送文字到环境板 OLED |

### 哨兵模式
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sentry/status` | 哨兵当前状态 |
| POST | `/api/sentry/arm` | 布防 |
| POST | `/api/sentry/disarm` | 撤防 |
| POST | `/api/sentry/patrol` | 立即执行一轮巡检 |
| POST | `/api/sentry/simulate` | 注入一次模拟入侵（演示用） |
| GET | `/api/sentry/clips` | 留证片段列表 |
| GET | `/api/sentry/events` | 事件列表 |
| POST | `/api/sentry/events/<id>/handle` | 处理事件（确认/误报） |
| POST | `/api/sentry/alarm/clear` | 解除当前告警 |
| DELETE | `/api/sentry/events/<id>` | 删除单条事件（含快照文件） |
| DELETE | `/api/sentry/events` | 清空全部事件 |

### 摄像头
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/camera/snapshot` | 抓拍当前帧 (JPEG) |
| GET | `/api/camera/stream` | MJPEG 实时流 |
| GET | `/api/camera/status` | 采集线程状态 |

### 历史数据
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/temperature` | 温度历史 |
| GET | `/api/history/devices` | 设备状态历史 |
| GET | `/api/history/devices/summary` | 设备统计摘要 |
| GET | `/api/dashboard` | 仪表盘综合数据 |

### 文件
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files/<subdir>/<filename>` | 访问 uploads 下的文件（detections/faces/sentry） |

### WebSocket 事件
| 事件 | 方向 | 说明 |
|------|------|------|
| `sensor_update` | 服务器→客户端 | 实时传感器数据（source=simulation/hardware） |
| `device_update` | 服务器→客户端 | 设备状态变化 |
| `hardware_status` | 服务器→客户端 | 串口硬件在线状态 |
| `sentry_state` | 服务器→客户端 | 哨兵布防/撤防/状态变化 |
| `sentry_patrol` | 服务器→客户端 | 每轮巡检结果 |
| `sentry_alarm` | 服务器→客户端 | 哨兵告警触发 |
| `sentry_alarm_cleared` | 服务器→客户端 | 告警解除 |
| `request_status` | 客户端→服务器 | 请求当前状态 |

## 数据库设计

| 表名 | 说明 |
|------|------|
| `authorized_persons` | 授权人员 (姓名/工号/角色/授权状态/人脸路径) |
| `access_logs` | 门禁日志 (人员/时间/结果/置信度/方式) |
| `temperature_logs` | 温度记录 (温度/湿度/时间/风扇激活) |
| `device_status_logs` | 设备状态日志 (设备名/状态/数值/来源/时间) |
| `detection_records` | 检测记录 (图片路径/检测结果/数量/触发动作) |
| `lighting_records` | 灯光记录 (开关状态/亮度/来源/持续时长/能耗) |
| `sentry_events` | **哨兵事件 (类型/等级/人数/相似度/快照/处理状态)** |

## 硬件与串口通信

### 分层架构

| 层 | 模块 | 职责 |
|------|------|------|
| 通信层 | `services/serial_bridge.py` | 只做信息交换：串口打开/自动重连、按行收发、协议解析、同步命令超时重试、缓存板子最近上报值。不依赖 Flask，可单独运行（`scripts/serial_probe.py` 就是这么用的） |
| 胶水层 | `services/hardware_service.py` | 把「协议」翻译成「状态」，把「状态」翻译成「命令」：命令转发、事件归位、在线状态汇总 |
| 业务层 | `services/device_manager.py` | 设备状态机、日志、WebSocket 推送，对协议无感知 |

### 两块板与命令

两块 UNO 各占一条串口、各一个 `SerialBridge` 实例，互不认识：

| 板子 | 角色 | 下行命令 | 上行消息 |
|------|------|----------|----------|
| UNO II | 门禁板 | `OPEN` `CLOSE` `QRAIN` `PING` | `@BOOT` `@ACK`/`@NAK` `@EVT DOOR OPEN\|CLOSED` `@EVT ACCESS KEYPAD_OK\|FAIL` `@DATA RAIN 0\|1` |
| UNO I | 环境板 | `QENV` `FAN 0\|1\|AUTO` `LAMP 0\|1 [亮度]` `MSG <文本>` | `@DATA ENV <温度×10> <湿度×10> <DHT有效标志>` `@EVT FAN\|LAMP\|CTL ...` |

> 注意：串口实际只接了**门（UNO II）**和**风扇+灯带（UNO I）**；空调、窗户没有串口命令，仍停留在软件模拟状态。
> `MSG` 用于环境板 OLED 临时提示：`|` 分隔最多 3 行、单行 21 字符、只认 ASCII（6x12_tr 没有中文字模），约 3 秒后自动翻回温湿度页。

### 消息格式与旧固件兼容

新协议统一为 `@KIND NAME args...` 行文本：`@BOOT <协议版本> <固件>`、`@ACK NAME`、`@NAK NAME <原因>`、`@EVT NAME args`、`@DATA NAME args`、`@PONG`，无法识别的行归为 LOG（只用于人工查看）。
通信层同时兼容旧固件的裸文本（`SmartHome Ready`、`OPEN OK`、`RAIN`/`NORAIN`、`密码正确`、`密码错误`、`自动关门` 等，见 `serial_bridge.py` 的 `_LEGACY_EXACT`），新老固件可混用。

### 可靠性约定

- **写操作必须串行**：固件是「攒满一行再整行比较」，`OPEN` 和 `QRAIN` 连发会被拼成 `OPENQRAIN`，两条都匹配不上。因此 `_tx_lock` 把写操作串成严格一问一答，命令间留最小间隔 50ms
- **开串口 = 板子复位**：打开串口会拉低 DTR 触发 ATmega328P 复位，连接成功后必须等 `@BOOT` 启动横幅；收到 BOOT 视为「位置未知、所有待确认命令作废」
- **重试策略**：命令超时 0.3s，查询/幂等命令重试 2 次，**`OPEN` 强制 0 重试**（非幂等，避免重复开门）
- **保活自适应**：新固件用 `PING` 保活，旧固件退化为 `QRAIN`/`QENV`（旧固件收到 `PING` 不吭声，硬发会误判离线）；离线判定窗口为 `max(10s, 3×轮询周期)`，断线 2s 自动重连
- **端口身份不许猜**：两块板同为 `2341:0043`，Linux 必须按 USB Serial Number 解析（换 USB 口不失效），Windows 才允许显式 COM 口；两块板映射重复直接拒绝启动
- **能力协商**：`protocol == 'legacy'` 时跳过 `CLOSE`（旧固件不回复，硬等只会卡 900ms）；`FAN/LAMP AUTO` 要求 `env-tristate-1` 固件
- **回环防护**：硬件上报的状态用 `source='hardware'` 写回 DeviceManager，不再反向下发命令，避免「命令 → 事件 → 命令」死循环
- **自动关门不撒谎**：开门后 6s 宽限到期只标记 `auto_close_unconfirmed`，不伪造物理门位置

### 配置项（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `SMART_HOME_SERIAL_ENABLED` | `0` | 启用门禁板对接 |
| `SMART_HOME_SERIAL_ENV_ENABLED` | `0` | 启用环境板对接（开启后温湿度以硬件为准，数据库切到 `data/smart_home_hardware.db` 且不再灌演示数据） |
| `SMART_HOME_DOOR_USB_SERIAL` / `SMART_HOME_ENVIRONMENT_USB_SERIAL` | - | 两块板的 USB Serial Number（Linux 必填） |
| `SMART_HOME_SERIAL_PORT` / `SMART_HOME_SERIAL_ENV_PORT` | - | 显式端口（仅 Windows 兼容用） |
| `SMART_HOME_SERIAL_BAUD` | `9600` | 波特率 |
| `SMART_HOME_SERIAL_TIMEOUT` / `SMART_HOME_SERIAL_RETRIES` | `0.3` / `2` | 单条命令超时(秒) / 查询重试次数 |
| `SMART_HOME_SERIAL_BOOT_WAIT` | `2.5` | 等启动横幅时间(秒)；环境板用 `SMART_HOME_SERIAL_ENV_BOOT_WAIT`（默认 4） |
| `SMART_HOME_SERIAL_HEARTBEAT` / `SMART_HOME_SERIAL_OFFLINE` | `3` / `10` | 心跳间隔(秒) / 离线判定(秒) |
| `SMART_HOME_SERIAL_RAIN_POLL` / `SMART_HOME_SERIAL_ENV_POLL` | `30` / `10` | 雨滴 / 温湿度轮询间隔(秒) |
| `SMART_HOME_SERIAL_RECONNECT` | `2` | 断线重连间隔(秒) |
| `SMART_HOME_SERIAL_AUTO_CLOSE` | `6` | 开门后自动关门的确认宽限(秒) |

### 调试与测试

- `scripts/serial_probe.py`：脱离 Flask 直接探测串口与协议
- `scripts/hardware_preflight.py`：上电前的连线与配置预检
- `scripts/flash_uno.py`：烧录 UNO 固件
- 状态接口：`GET /api/hardware/status`（端口/协议/固件/计数器/最近事件）
- 实时推送：WebSocket `hardware_status`、`sensor_update`（`source=hardware`）
- 固件源码：`硬件代码/design-and-build-project-main/{UNOI,UNOII}`
- 串口相关测试：`tests/test_serial_*.py`、`tests/test_env_*.py`、`tests/test_hardware_*.py`

## 预置数据

系统启动时在**模拟数据库**中自动插入演示数据（开启环境板硬件对接后，数据库切换到 `data/smart_home_hardware.db`，且不再灌演示数据）：
- **授权人员**：张明(EMP001, 管理员) + 李华(EMP002, 成员) + 未知人员(FAKE001, 假身份)
- **温度数据**：过去24小时温度记录（每30分钟一条）
- **设备日志**：过去50小时设备状态变化记录
- **门禁日志**：20条访问记录（含允许/拒绝/未知）
- **灯光记录**：过去24小时灯光开关记录（48条，按作息规律模拟）

人脸不再是训练 LBPH 模型，而是注册 InsightFace 特征；特征库按当前数据库隔离存放于 `data/`。

## 哨兵模式

哨兵是布防状态下的自动值守：定时从摄像头取帧 → YOLO 人形检测 → InsightFace 人脸核验 → 判定/留证/告警。页面 `/sentry` 提供布防/撤防、立即巡检、模拟入侵、解除告警、实时/回放视图与事件管理。

### 图片采集策略

**只开一次摄像头，所有模块按需从同一路视频流取帧**，不再各自 `cv2.VideoCapture` 抢占设备（Windows 与香橙派摄像头通常独占）。

| 环节 | 做法 |
|------|------|
| 采集 | `services/camera_stream.py` 启动一个常驻采集线程，独占一路 `cv2.VideoCapture`（设备由 `config.CAMERA_SOURCE` 指定），持续读帧 |
| 分发 | 不用帧队列，只维护「最新帧 + 单调递增 `seq`」，靠条件变量唤醒等待者；各消费者记住自己的 `last_seq` 去重，慢消费者不会积压延迟，也不会把帧从别人手里抢走 |
| 取帧 | 巡检每轮先取最新帧（`max_age=3s`，超过即视为摄像头卡住）；需要留证连拍时以当前 `seq` 为基准逐张 `wait_for_frame`，按 `SENTRY_BURST_GAP`（默认 0.12s）间隔抓 `SENTRY_BURST_FRAMES`（默认 10）张，凑成一小段"短录像"；取不到新帧就复用首帧，保证告警一定有图 |
| 健康检查 | 每 5 帧算一次平均亮度，低于 12 判为画面过暗/遮挡；连续读帧失败 5 次自动重开设备（间隔 2s）。哨兵遇到暗帧只记「跳过检测」，不误判入侵 |
| 节奏与落盘 | 布防后每 `SENTRY_PATROL_INTERVAL`（默认 10s）巡检一轮：取帧 → YOLO 人形检测（只取 person 类，conf 0.35）→ 人脸核验 → 判定/告警；命中人员的快照写入 `uploads/sentry/`，命名 `YYYYMMDD_HHMMSS_毫秒_序号.jpg`，经 `/api/files/sentry/<name>` 访问 |

推理（YOLO 人形检测、人脸核验）全部放在巡检线程里做，采集线程只负责读帧和分发，帧回调必须毫秒级返回，避免拖慢采集帧率。

### 哨兵策略

1. 布防后每轮巡检取 1 帧，YOLO 检测是否有人；无人则回归初始状态
2. 检测到未录入人脸：连拍留证，记一条「活动」事件（info 级，不告警），连续轮次计数 +1
3. 连续命中达到 `SENTRY_ALARM_ROUNDS`（默认 3）轮升级为告警（critical），冷却期内重复触发只累加次数，不再刷屏
4. 升级前若识别到已录入人脸或人离开：清除留证与计数器；授权出现且从未告警时，滚动窗口内的留证会被整批清除
5. 告警同时推送到环境板 OLED（`MSG` 命令，未接环境板时自动跳过）

### 哨兵参数（config.py，均可用环境变量覆盖）

| 参数 | 默认 | 说明 |
|------|------|------|
| `SENTRY_PATROL_INTERVAL` | 10s | 巡检间隔（香橙派上 YOLOv8n 单帧 0.3~1s，不建议低于 5s） |
| `SENTRY_ARM_DELAY` | 0 | 布防延时，留出关门离开的时间（演示默认 0，按下即布防） |
| `SENTRY_ALARM_COOLDOWN` | 60s | 同类告警冷却 |
| `SENTRY_BURST_FRAMES` / `SENTRY_BURST_GAP` | 10 / 0.12s | 每轮留证张数 / 连拍间隔 |
| `SENTRY_ALARM_ROUNDS` | 3 | 连续多少轮出现未授权人员后升级为告警（第 1 轮只记「活动」，路过的人撑不到 3 轮） |
| `SENTRY_SNAPSHOT_WINDOW` | 12 轮 | 未告警时的留证滚动窗口，超出自动删除最旧一轮 |
| `SENTRY_PERSON_CONF` | 0.35 | 人形检测阈值（略低于常规，提高远处/背光召回率） |
| `SENTRY_PERSON_MODEL` | yolov8n.pt | 哨兵专用 COCO 模型（必须含 person 类；不能复用 best.pt，它只有 drone/fire_extinguisher） |

## 测试

`tests/` 下 22 个 unittest 用例文件，重点覆盖串口协议、硬件对接、环境板三态控制与哨兵逻辑：

```bash
python -m unittest discover tests        # 全量
python scripts/run_software_tests.py     # 纯软件路径（临时库、绝不碰硬件）
```
