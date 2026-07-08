# 智能家居管理系统 (Smart Home Management System)

> 以安全和舒适为重点的智能家居系统原型 — 软件部分

## 项目概述

本项目为智能家居系统的数据访问软件部分，涵盖数据库/后端设计、物体识别、人脸识别门禁、Web GUI 及远程控制等全部软件要求。

## 功能与需求对照表

### 基本要求

| # | 要求 | 实现方式 | 对应模块 |
|---|------|----------|----------|
| 1 | 管理信息：存储和管理授权人员的信息 | SQLite 数据库 + SQLAlchemy ORM，支持增删改查 | 人员管理页面 `/persons` |
| 2 | 物体识别：YOLO 算法识别物体 | YOLOv8 (ultralytics) 检测 80 类物体，支持图片上传和摄像头拍照 | 物体检测页面 `/detection` |
| 3 | 人脸识别开启门禁：至少2真1假 | OpenCV LBPH 人脸识别 + Haar 级联检测，预置 2个真实授权 + 1个假身份 | 门禁管理页面 `/access` |
| 4 | GUI：显示信息 + 数据统计和分析 | Flask Web GUI + Chart.js 图表，支持温度/灯光/门/窗历史数据检索 | 仪表盘 `/` + 数据分析 `/analysis` |

### 附加功能

| # | 要求 | 实现方式 |
|---|------|----------|
| 5 | 远程控制：通过 GUI 远程控制灯、空调等 | REST API + WebSocket 实时推送，支持灯光/风扇/空调/门锁/窗户远程控制 |
| 6 | 自定义：摄像头检测到灯泡图片后控制灯 | YOLO 检测到灯泡/圆形物体后自动触发灯光开启（亮度80%） |

### 额外功能

- 温度超过阈值 (28°C) 自动开启风扇
- 活体检测（防照片伪造）
- 门窗状态实时监控
- 灯光亮度无级调节 (0-100%)
- **灯光专用记录表：追踪开关历史、亮度变化、使用时长、能耗统计、操作来源分析**
- **灯光数据分析：亮度趋势图、来源分布饼图、每日使用汇总（柱状图+折线图）**
- WebSocket 实时数据推送
- 传感器数据模拟（无硬件时可运行）

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端框架 | Flask 3.0 + Flask-SocketIO 5.3 |
| 数据库 | SQLite + Flask-SQLAlchemy 3.1 |
| 物体检测 | YOLOv8 (ultralytics 8.3) |
| 人脸识别 | OpenCV 4.10 (Haar 级联 + LBPH) |
| 前端 | HTML5 + CSS3 + JavaScript + Chart.js 4.4 |
| 实时通信 | WebSocket (Flask-SocketIO) |
| 图像处理 | OpenCV + Pillow + NumPy |

## 项目结构

```
smart_home/
├── app.py                      # 主应用入口 (Flask + SocketIO)
├── config.py                   # 配置文件
├── models.py                   # 数据库模型 (6张表)
├── database.py                 # 数据库初始化与种子数据
├── requirements.txt            # Python 依赖
├── start.bat                   # Windows 一键启动
├── SETUP.md                    # 环境配置详细说明（必读）
├── routes/
│   ├── api.py                  # REST API (8大模块, 28+ 接口)
│   └── pages.py                # 页面路由 (6个页面)
├── services/
│   ├── object_detection.py     # YOLO 物体检测服务
│   ├── face_recognition_service.py  # 人脸识别服务 (LBPH + 活体检测)
│   ├── device_manager.py       # 设备管理器 (灯/风扇/门/窗/空调)
│   └── sensor_simulator.py     # 传感器数据模拟器 (温度/湿度)
├── templates/                  # Jinja2 HTML 模板
│   ├── base.html               # 基础模板 (侧边栏)
│   ├── dashboard.html          # 系统仪表盘 (含灯光摘要)
│   ├── access_control.html     # 门禁管理
│   ├── object_detection.html   # 物体检测
│   ├── device_control.html     # 设备控制
│   ├── data_analysis.html      # 数据分析 (含灯光分析)
│   └── persons.html            # 人员管理
├── static/
│   ├── css/style.css           # 主样式 (丝绒优雅风格)
│   └── js/
│       ├── common.js           # 共享工具 (API/SocketIO/Toast)
│       └── dashboard.js        # 仪表盘逻辑
├── data/                       # SQLite 数据库 + 人脸模型
├── uploads/                    # 上传文件
│   ├── detections/             # 检测图片
│   └── faces/                  # 人脸照片
└── known_faces/                # 已注册人脸样本
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

# 4. 启动系统
python app.py

# 5. 浏览器打开 http://localhost:5000
```

## 使用指南

### 仪表盘 (/)
- 实时显示温度、灯光、门锁、窗户、风扇、空调状态
- 24小时温度趋势图（含风扇激活标记）
- 最近门禁记录和检测记录
- **灯光使用摘要卡片：今日开灯时长、能耗、操作次数、平均亮度**

### 门禁管理 (/access)
- 上传照片进行人脸识别开门
- 活体检测防止照片伪造
- 门禁访问日志查询（支持按结果筛选）
- 授权人员状态概览（2真1假）

### 物体检测 (/detection)
- 上传图片使用 YOLOv8 检测物体（80类）
- 检测结果图片对比展示
- 检测到灯泡自动触发灯光控制
- 检测历史记录查询

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
| POST | `/api/access/recognize` | 人脸识别开门 |
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

### 灯光记录（新增）
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

### 历史数据
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/temperature` | 温度历史 |
| GET | `/api/history/devices` | 设备状态历史 |
| GET | `/api/history/devices/summary` | 设备统计摘要 |
| GET | `/api/dashboard` | 仪表盘综合数据 |

### WebSocket 事件
| 事件 | 方向 | 说明 |
|------|------|------|
| `sensor_update` | 服务器→客户端 | 实时传感器数据 |
| `device_update` | 服务器→客户端 | 设备状态变化 |
| `request_status` | 客户端→服务器 | 请求当前状态 |

## 数据库设计

| 表名 | 说明 |
|------|------|
| `authorized_persons` | 授权人员 (姓名/工号/角色/授权状态/人脸路径) |
| `access_logs` | 门禁日志 (人员/时间/结果/置信度/方式) |
| `temperature_logs` | 温度记录 (温度/湿度/时间/风扇激活) |
| `device_status_logs` | 设备状态日志 (设备名/状态/数值/来源/时间) |
| `detection_records` | 检测记录 (图片路径/检测结果/数量/触发动作) |
| `lighting_records` | **灯光记录 (开关状态/亮度/来源/持续时长/能耗)** |

## 硬件对接说明

当有实际硬件时，可通过以下方式对接：

1. **温度传感器**：通过 `POST /api/sensor/inject` 接口上传真实温度数据
2. **门禁控制**：设备管理器状态变化通过 WebSocket 推送，硬件端监听 `device_update` 事件
3. **摄像头拍照**：调用 `POST /api/detection/camera` 接口触发拍照和检测
4. **设置模拟模式**：修改 `config.py` 中 `SIMULATION_MODE = False` 关闭模拟器

## 预置数据

系统启动时自动插入演示数据：
- **授权人员**：张明(EMP001, 管理员) + 李华(EMP002, 成员) + 未知人员(FAKE001, 假身份)
- **温度数据**：过去24小时温度记录（每30分钟一条）
- **设备日志**：过去50小时设备状态变化记录
- **门禁日志**：20条访问记录（含允许/拒绝/未知）
- **灯光记录**：过去24小时灯光开关记录（48条，按作息规律模拟）
