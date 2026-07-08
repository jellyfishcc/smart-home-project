# 智能家居管理系统 - 项目文档

## 1. 项目概述

### 1.1 项目简介

本项目是一个以**安全和舒适**为重点的智能家居系统原型，涵盖数据库/后端设计、物体识别、人脸识别门禁、Web GUI 及远程控制等全部软件功能。

### 1.2 功能需求对照

| 序号 | 功能要求 | 实现方式 | 对应模块 |
|------|----------|----------|----------|
| 1 | 管理授权人员信息（存储和管理） | SQLite + SQLAlchemy ORM，支持增删改查 | 人员管理页面 `/persons` |
| 2 | 物体识别（YOLO算法） | YOLOv8 (ultralytics) 检测 80 类物体 | 物体检测页面 `/detection` |
| 3 | 人脸识别门禁（至少2真1假） | OpenCV LBPH 人脸识别 + Haar 级联检测 | 门禁管理页面 `/access` |
| 4 | Web GUI（显示信息+数据统计） | Flask Web GUI + Chart.js 图表 | 仪表盘 `/` + 数据分析 `/analysis` |
| 5 | 远程控制（灯、空调等） | REST API + WebSocket 实时推送 | 设备控制页面 `/devices` |
| 6 | 自定义功能（检测灯泡后控制灯） | YOLO 检测到圆形物体后自动触发灯光开启 | 物体检测服务 |

### 1.3 额外功能

- 温度超过阈值 (28°C) 自动开启风扇
- 活体检测（防照片伪造）
- 门窗状态实时监控
- 灯光亮度无级调节 (0-100%)
- WebSocket 实时数据推送
- 传感器数据模拟（无硬件时可运行）

---

## 2. 技术架构

### 2.1 技术栈

| 层次 | 技术 | 版本 |
|------|------|------|
| 后端框架 | Flask | 3.0.3 |
| WebSocket | Flask-SocketIO | 5.3.6 |
| 数据库 | SQLite + Flask-SQLAlchemy | 3.1.1 |
| 物体检测 | YOLOv8 (ultralytics) | 8.3.0 |
| 人脸识别 | OpenCV (Haar级联 + LBPH) | 4.10.0 |
| 前端 | HTML5 + CSS3 + JavaScript + Chart.js | 4.4.x |
| 图像处理 | Pillow + NumPy | 10.4.0 / 1.26.4 |

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                        Web Browser                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐│
│  │Dashboard│ │ Access  │ │Detection│ │ Devices │ │ Analysis││
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘│
└───────┼───────────┼───────────┼───────────┼───────────┼─────┘
        │           │           │           │           │
┌───────▼───────────▼───────────▼───────────▼───────────▼─────┐
│                   Flask Web Server                          │
│  ┌──────────────────┐  ┌──────────────────────────────────┐ │
│  │   Pages Blueprint│  │           API Blueprint          │ │
│  │  (页面路由渲染)    │  │  人员管理 | 门禁 | 检测 | 设备   │ │
│  └──────────────────┘  └──────────────────────────────────┘ │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│                     Services Layer                         │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ FaceRecognition  │  │ ObjectDetection  │               │
│  │   (LBPH + Haar)  │  │     (YOLOv8)     │               │
│  └──────────────────┘  └──────────────────┘               │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │  DeviceManager   │  │ SensorSimulator  │               │
│  │  (设备状态管理)   │  │  (传感器模拟)    │               │
│  └──────────────────┘  └──────────────────┘               │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│                   SQLite Database                          │
│  authorized_persons | access_logs | temperature_logs      │
│  device_status_logs | detection_records                   │
└───────────────────────────────────────────────────────────┘
```

### 2.3 数据流

```
传感器数据 → SensorSimulator → 数据库记录 → WebSocket推送 → 前端展示
                                    ↓
                              温度阈值判断 → DeviceManager → 自动控制风扇

门禁照片 → FaceRecognitionService → 活体检测 → 人脸识别 → 授权判断 → 开门/拒绝
                                                              ↓
                                                      数据库记录门禁日志

上传图片 → ObjectDetectionService → YOLO检测 → 结果标注 → 触发动作判断
                                                              ↓
                                                      自动控制设备(如开灯)
```

---

## 3. 项目结构

```
smart_home/
├── app.py                      # 主应用入口 (Flask + SocketIO 初始化)
├── config.py                   # 配置文件 (路径/阈值/密钥)
├── models.py                   # 数据库模型 (5张表)
├── database.py                 # 数据库初始化与种子数据
├── requirements.txt            # Python 依赖
├── start.bat                   # Windows 启动脚本
├── server_output.log           # 服务器日志
├── routes/
│   ├── __init__.py
│   ├── api.py                  # REST API (7大模块, 25+ 接口)
│   └── pages.py                # 页面路由 (6个页面)
├── services/
│   ├── __init__.py
│   ├── device_manager.py       # 设备管理器 (灯/风扇/门/窗/空调)
│   ├── face_recognition_service.py  # 人脸识别服务 (LBPH + 活体检测)
│   ├── object_detection.py     # YOLO 物体检测服务
│   └── sensor_simulator.py     # 传感器数据模拟器 (温度/湿度)
├── templates/                  # Jinja2 HTML 模板
│   ├── base.html               # 基础模板 (侧边栏导航)
│   ├── dashboard.html          # 系统仪表盘
│   ├── access_control.html     # 门禁管理
│   ├── object_detection.html   # 物体检测
│   ├── device_control.html     # 设备控制
│   ├── data_analysis.html      # 数据分析
│   └── persons.html            # 人员管理
├── static/
│   ├── css/style.css           # 主样式 (丝绒优雅风格)
│   └── js/
│       ├── common.js           # 共享工具 (API/SocketIO/Toast)
│       └── dashboard.js        # 仪表盘实时更新逻辑
├── data/                       # SQLite 数据库 + 人脸模型
│   └── smart_home.db
├── uploads/                    # 上传文件
│   ├── detections/             # 检测图片
│   └── faces/                  # 人脸照片
├── known_faces/                # 已注册人脸样本 (用于训练)
└── venv/                       # Python 虚拟环境
```

---

## 4. 核心模块详解

### 4.1 主应用入口 [app.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/app.py)

**职责**: 应用初始化、服务注册、SocketIO 事件处理

**关键功能**:
- Flask 应用创建与配置加载
- 数据库初始化 (`init_db`)
- SocketIO 初始化与事件处理 (`connect`, `disconnect`, `request_status`)
- 服务注册（物体检测、人脸识别、设备管理、传感器模拟）
- 启动传感器模拟器（模拟模式）

**启动流程**:
```
app.py 启动
    │
    ├── 创建 Flask 应用
    ├── 加载配置 (config.py)
    ├── 初始化数据库 (SQLite)
    ├── 初始化 SocketIO
    ├── 初始化 YOLO 检测服务
    ├── 初始化人脸识别服务
    ├── 初始化设备管理器
    ├── 初始化传感器模拟器
    ├── 注册蓝图 (api_bp, pages_bp)
    ├── 启动传感器模拟线程 (SIMULATION_MODE=True)
    └── 运行 SocketIO 服务器
```

### 4.2 配置模块 [config.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/config.py)

**配置项说明**:

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///data/smart_home.db` | 数据库路径 |
| `UPLOAD_FOLDER` | `uploads/` | 上传文件目录 |
| `YOLO_MODEL` | `yolov8n.pt` | YOLO 模型名称 |
| `YOLO_CONF_THRESHOLD` | `0.4` | YOLO 置信度阈值 |
| `FACE_CONFIDENCE_THRESHOLD` | `70` | LBPH 置信度阈值（越低越匹配） |
| `TEMPERATURE_THRESHOLD` | `28.0` | 温度阈值（超过此温度自动开风扇） |
| `SIMULATION_MODE` | `True` | 是否启用模拟模式 |

### 4.3 数据库模型 [models.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/models.py)

**5张数据表**:

#### 4.3.1 `authorized_persons` - 授权人员表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 主键ID |
| `name` | String(100) | 姓名 |
| `employee_id` | String(50) | 工号/编号（唯一） |
| `role` | String(50) | 角色/身份 |
| `is_authorized` | Boolean | 是否授权 |
| `is_fake` | Boolean | 是否为假身份（用于2真1假测试） |
| `face_image_path` | String(500) | 人脸照片路径 |
| `face_encoding_path` | String(500) | 人脸特征数据文件路径 |
| `phone` | String(20) | 联系电话 |
| `department` | String(100) | 部门 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

#### 4.3.2 `access_logs` - 门禁访问日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 主键ID |
| `person_id` | Integer (FK) | 人员ID（未识别时为空） |
| `person_name` | String(100) | 识别到的人员姓名 |
| `access_time` | DateTime | 访问时间 |
| `access_result` | String(20) | 结果：granted/denied/unknown |
| `confidence` | Float | 识别置信度 |
| `image_path` | String(500) | 抓拍照片路径 |
| `method` | String(50) | 开门方式 |
| `detail` | String(500) | 详细信息 |

#### 4.3.3 `temperature_logs` - 温度记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 主键ID |
| `temperature` | Float | 温度值（摄氏度） |
| `humidity` | Float | 湿度（%） |
| `recorded_at` | DateTime | 记录时间 |
| `fan_activated` | Boolean | 是否触发了风扇 |

#### 4.3.4 `device_status_logs` - 设备状态日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 主键ID |
| `device_name` | String(50) | 设备名称：light/door/window/fan/ac |
| `status` | String(100) | 状态（JSON字符串） |
| `value` | String(100) | 数值（如亮度、风速） |
| `source` | String(50) | 操作来源：manual/auto/sensor/remote |
| `recorded_at` | DateTime | 记录时间 |

#### 4.3.5 `detection_records` - 物体检测记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 主键ID |
| `image_path` | String(500) | 原图路径 |
| `result_image_path` | String(500) | 标注后图片路径 |
| `objects_detected` | Text | 检测到的物体（JSON列表） |
| `object_count` | Integer | 检测到的物体总数 |
| `detected_at` | DateTime | 检测时间 |
| `source` | String(50) | 来源：upload/camera/auto |
| `triggered_action` | String(200) | 触发的动作 |

### 4.4 业务服务层

#### 4.4.1 人脸识别服务 [face_recognition_service.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/services/face_recognition_service.py)

**核心功能**:
- `register_face()` - 注册人脸（上传照片→检测→训练）
- `recognize()` - 人脸识别（检测→识别→授权判断）
- `check_liveness()` - 活体检测（清晰度/饱和度/光照分析）
- `_train_model()` - 训练 LBPH 模型

**技术实现**:
- 使用 OpenCV Haar 级联分类器检测人脸
- 使用 LBPH（Local Binary Patterns Histograms）人脸识别算法
- 活体检测通过分析图像纹理（拉普拉斯方差）、色彩饱和度、光照均匀性综合判断

#### 4.4.2 物体检测服务 [object_detection.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/services/object_detection.py)

**核心功能**:
- `detect()` - 检测图片中的物体（支持 YOLO 和降级模式）
- `check_trigger()` - 检查检测结果是否触发预设动作
- `detect_from_camera()` - 从摄像头捕获并检测

**触发规则**:
| 检测物体 | 触发动作 | 说明 |
|----------|----------|------|
| `light_bulb` | `turn_on_light` | 检测到灯泡图片，自动开启灯光（亮度80%） |
| `person` | `log` | 检测到人员，记录日志 |
| `car` | `log` | 检测到车辆，记录日志 |

#### 4.4.3 设备管理器 [device_manager.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/services/device_manager.py)

**管理的设备**:

| 设备 | 状态属性 | 控制能力 |
|------|----------|----------|
| `light` | `on`, `brightness` | 开关 + 亮度调节 (0-100%) |
| `fan` | `on`, `speed` | 开关 + 4档风速 |
| `door` | `locked` | 锁定/解锁 |
| `window` | `closed` | 打开/关闭 |
| `ac` | `on`, `temp` | 开关 + 温度调节 (16-30°C) |

**核心功能**:
- `set_device()` - 设置设备状态
- `toggle_device()` - 切换设备开关
- `set_light_brightness()` - 设置灯光亮度
- `auto_fan_control()` - 自动风扇控制（温度超过阈值自动开启）

#### 4.4.4 传感器模拟器 [sensor_simulator.py](file:///c:/Users/33664/WorkBuddy/2026-07-07-18-33-32/smart_home/services/sensor_simulator.py)

**核心功能**:
- `start()` - 启动传感器模拟线程（每30秒采样一次）
- `get_current_reading()` - 获取当前传感器读数
- `inject_reading()` - 注入真实传感器数据（硬件端调用）

**模拟逻辑**:
- 温度：基于时间模拟（中午最高，夜间最低），范围 20-33°C
- 湿度：与温度负相关，范围 30-80%
- 自动风扇控制：温度超过 28°C 自动开启风扇

---

## 5. API 接口文档

### 5.1 授权人员管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/persons` | 获取所有人员列表 |
| GET | `/api/persons/<id>` | 获取单个人员详情 |
| POST | `/api/persons` | 添加人员 |
| PUT | `/api/persons/<id>` | 更新人员信息 |
| DELETE | `/api/persons/<id>` | 删除人员 |
| POST | `/api/persons/<id>/register-face` | 注册人脸（上传照片） |

**POST /api/persons 请求体**:
```json
{
    "name": "张三",
    "employee_id": "EMP003",
    "role": "成员",
    "is_authorized": true,
    "is_fake": false,
    "phone": "13800138003",
    "department": "技术部"
}
```

### 5.2 人脸识别门禁

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/access/recognize` | 人脸识别开门（上传照片） |
| GET | `/api/access/logs` | 门禁日志查询（支持分页和结果筛选） |

**POST /api/access/recognize 响应**:
```json
{
    "code": 0,
    "message": "识别完成",
    "data": {
        "access_result": "granted",
        "person_name": "张明",
        "confidence": 35.2,
        "liveness": {"is_live": true, "score": 85},
        "detail": "授权人员 张明 识别成功，门禁已开启"
    }
}
```

### 5.3 物体检测

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/detection/upload` | 上传图片进行 YOLO 检测 |
| POST | `/api/detection/camera` | 摄像头拍照检测 |
| GET | `/api/detection/records` | 检测记录查询 |

### 5.4 设备控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/devices` | 获取所有设备状态 |
| GET | `/api/devices/<name>` | 获取单个设备状态 |
| POST | `/api/devices/<name>/control` | 控制设备 |
| POST | `/api/devices/<name>/toggle` | 切换设备开关 |
| POST | `/api/devices/light/brightness` | 设置灯光亮度 |

**POST /api/devices/light/control 请求体**:
```json
{
    "status": "on",
    "value": 80,
    "source": "remote"
}
```

### 5.5 传感器数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sensor/current` | 获取当前传感器读数 |
| POST | `/api/sensor/inject` | 注入真实传感器数据（硬件端调用） |

### 5.6 历史数据与统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/temperature` | 温度历史数据（支持时间范围筛选） |
| GET | `/api/history/devices` | 设备状态历史 |
| GET | `/api/history/devices/summary` | 设备统计摘要 |
| GET | `/api/dashboard` | 仪表盘综合数据 |

### 5.7 WebSocket 事件

| 事件名 | 方向 | 说明 |
|--------|------|------|
| `connect` | 客户端→服务器 | 客户端连接 |
| `disconnect` | 客户端→服务器 | 客户端断开 |
| `request_status` | 客户端→服务器 | 请求当前状态 |
| `sensor_update` | 服务器→客户端 | 实时传感器数据推送 |
| `device_update` | 服务器→客户端 | 设备状态变化推送 |

---

## 6. Web 页面功能

### 6.1 仪表盘 (`/`)

**功能**:
- 实时显示温度、湿度、灯光、门锁、窗户、风扇、空调状态
- 24小时温度趋势图（含风扇激活标记）
- 最近门禁记录列表
- 最近检测记录列表
- 快捷设备开关控制
- 授权人员统计概览

### 6.2 门禁管理 (`/access`)

**功能**:
- 上传照片进行人脸识别开门
- 活体检测结果显示
- 门禁访问日志查询（支持按结果筛选：全部/允许/拒绝）
- 授权人员状态概览（2真1假标识）

### 6.3 物体检测 (`/detection`)

**功能**:
- 上传图片使用 YOLOv8 检测物体（80类）
- 检测结果图片对比展示（原图 vs 标注后）
- 检测到灯泡自动触发灯光控制
- 检测历史记录查询

### 6.4 设备控制 (`/devices`)

**功能**:
- 灯光：开关 + 亮度滑块 (0-100%) + 快捷档位
- 风扇：开关 + 4档风速（含自动模式）
- 空调：开关 + 温度调节 (16-30°C)
- 门锁：开锁/锁定
- 窗户：打开/关闭
- 设备操作历史记录

### 6.5 人员管理 (`/persons`)

**功能**:
- 添加/编辑/删除授权人员
- 上传人脸照片注册人脸特征
- 标记身份类型：真实授权 / 伪造未授权
- 人脸注册状态查看

### 6.6 数据分析 (`/analysis`)

**功能**:
- 温度趋势图（平均/最高/最低）
- 湿度变化趋势
- 设备状态统计图（柱状对比）
- 门禁访问统计（饼图）
- 温度数据明细表
- 设备操作汇总表
- 支持时间范围筛选 (6h/12h/24h/48h/7天)

---

## 7. 部署与运行

### 7.1 环境要求

- Python 3.8+
- Windows / Linux / macOS

### 7.2 安装步骤

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

### 7.3 启动方式

```bash
# 方式一：直接运行
python app.py

# 方式二：Windows 双击启动
start.bat
```

### 7.4 访问地址

浏览器打开: http://localhost:5000

---

## 8. 硬件对接说明

当有实际硬件时，可通过以下方式对接：

### 8.1 温度传感器

通过 `POST /api/sensor/inject` 接口上传真实温度数据：

```bash
curl -X POST http://localhost:5000/api/sensor/inject \
  -H "Content-Type: application/json" \
  -d '{"temperature": 26.5, "humidity": 55}'
```

### 8.2 门禁控制

设备管理器状态变化通过 WebSocket 推送，硬件端监听 `device_update` 事件：

```javascript
socket.on('device_update', (data) => {
    if (data.device === 'door' && data.state.locked === false) {
        // 执行开门动作
        console.log('门禁已开启');
    }
});
```

### 8.3 摄像头拍照

调用 `POST /api/detection/camera` 接口触发拍照和检测：

```bash
curl -X POST http://localhost:5000/api/detection/camera
```

### 8.4 关闭模拟模式

修改 `config.py` 中 `SIMULATION_MODE = False`，系统将停止传感器模拟，等待真实数据注入。

---

## 9. 预置演示数据

系统启动时自动插入以下演示数据：

### 9.1 授权人员

| 姓名 | 工号 | 角色 | 授权状态 | 身份类型 |
|------|------|------|----------|----------|
| 张明 | EMP001 | 管理员 | 已授权 | 真实 |
| 李华 | EMP002 | 成员 | 已授权 | 真实 |
| 未知人员 | FAKE001 | 无 | 未授权 | 伪造 |

### 9.2 温度数据

- 过去 24 小时温度记录（每 30 分钟一条）
- 温度范围：22-32°C
- 自动标记风扇激活状态

### 9.3 设备日志

- 过去 50 小时设备状态变化记录
- 包含灯光、风扇、空调、门、窗的操作记录

### 9.4 门禁日志

- 20 条访问记录
- 包含允许（granted）、拒绝（denied）、未知（unknown）三种结果

---

## 10. 安全特性

### 10.1 活体检测

门禁系统集成活体检测功能，通过分析以下指标判断是否为真人：
- **清晰度**：拉普拉斯方差 > 30
- **色彩饱和度**：HSV 饱和度 > 40
- **光照均匀性**：亮度在 50-220 之间，标准差 > 30
- **综合评分**：60 分以上判定为活体

### 10.2 访问控制

- 2真1假测试：系统预置 2 个授权人员 + 1 个伪造身份，验证门禁安全性
- 授权判断：仅授权且非伪造身份的人员才能开门
- 详细日志：记录每次访问的时间、人员、结果、置信度

### 10.3 文件安全

- 文件名安全处理：使用 `secure_filename()` 过滤文件名
- 允许的文件类型：png, jpg, jpeg, bmp, gif

---

## 11. 扩展建议

### 11.1 性能优化

- 使用 Redis 缓存设备状态和传感器数据
- 引入消息队列（如 RabbitMQ）处理异步任务
- 增加人脸识别模型训练异步化

### 11.2 功能扩展

- 添加语音控制（集成语音识别 API）
- 实现场景模式（如"回家模式"、"睡眠模式"）
- 接入第三方智能设备（如米家、华为 HiLink）
- 添加移动端 APP 支持

### 11.3 安全增强

- 集成更高级的活体检测算法（如 3D 深度检测）
- 添加用户认证和权限管理
- 实现设备操作审计日志
- 添加 HTTPS 支持

---

## 12. 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-07-07 | 初始版本，包含所有基础功能 |

---

*文档生成时间: 2026-07-07*