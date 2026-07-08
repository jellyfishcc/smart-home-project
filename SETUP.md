# 智能家居管理系统 - 环境配置与运行说明

## 一、环境要求

| 项目 | 最低要求 |
|------|----------|
| 操作系统 | Windows 10+ / macOS 12+ / Linux (Ubuntu 20.04+) |
| Python | **3.10 或 3.11**（推荐 3.11） |
| 内存 | 4GB+ |
| 磁盘 | 2GB+ 空闲空间（含依赖和模型文件） |
| 网络 | 首次运行需联网下载 YOLO 模型（约 6MB） |

> Python 3.12+ 暂未完全测试，可能出现兼容性问题。

## 二、安装步骤

### 第1步：确认 Python 已安装

打开终端（Windows: PowerShell / macOS/Linux: Terminal），输入：

```bash
python --version
```

应显示 `Python 3.10.x` 或 `Python 3.11.x`。

如未安装，前往 https://www.python.org/downloads/ 下载安装，**安装时勾选 "Add Python to PATH"**。

### 第2步：解压项目

将 `smart_home_release` 文件夹解压到任意目录（路径不要包含中文或空格）。

### 第3步：创建虚拟环境

进入项目目录：

```bash
cd smart_home_release
```

创建虚拟环境：

```bash
python -m venv venv
```

### 第4步：激活虚拟环境

**Windows (PowerShell):**
```powershell
venv\Scripts\activate
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
source venv/bin/activate
```

激活成功后，终端前面会显示 `(venv)` 标识。

### 第5步：安装依赖

```bash
pip install -r requirements.txt
```

> 安装可能需要 5-15 分钟，取决于网速。ultralytics 和 opencv 包较大，请耐心等待。

### 第6步：下载 YOLO 模型（自动）

首次运行 `python app.py` 时，ultralytics 会自动下载 `yolov8n.pt` 模型文件到当前目录，约 6MB。

> 如自动下载失败，可手动下载：
> https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt
> 将下载的文件放到 `smart_home_release/` 目录下。

## 三、启动系统

```bash
python app.py
```

启动成功后，终端显示：

```
==================================================
  智能家居管理系统启动中...
  YOLO 检测: 可用
  人脸识别: 未训练(请注册人脸)
  传感器模式: 模拟
  访问地址: http://localhost:5000
==================================================
```

浏览器打开 **http://localhost:5000** 即可使用。

## 四、项目功能一览

| 功能模块 | 页面地址 | 说明 |
|----------|----------|------|
| 仪表盘 | `/` | 实时状态总览、灯光使用摘要、温度趋势 |
| 门禁管理 | `/access` | 人脸识别开门、2真1假身份验证、活体检测 |
| 物体检测 | `/detection` | YOLO 物体识别、灯泡检测自动开灯 |
| 设备控制 | `/devices` | 灯光/风扇/空调/门锁/窗户远程控制 |
| 数据分析 | `/analysis` | 温度/湿度/灯光分析、设备统计、每日汇总 |
| 人员管理 | `/persons` | 授权人员增删改查、人脸注册 |

## 五、验证安装

启动后，访问以下 API 确认系统正常：

```bash
# 查看仪表盘数据
curl http://localhost:5000/api/dashboard

# 查看灯光统计
curl http://localhost:5000/api/lighting/stats?hours=24

# 查看所有设备状态
curl http://localhost:5000/api/devices
```

## 六、常见问题

### Q1: 提示 "python 不是内部或外部命令"
Python 未安装或未添加到 PATH。重新安装 Python 并勾选 "Add Python to PATH"。

### Q2: pip install 时报错 "Microsoft Visual C++ 14.0 is required"
安装 Visual Studio Build Tools：
https://visualstudio.microsoft.com/visual-cpp-build-tools/
选择 "Desktop development with C++"，安装后重试。

### Q3: YOLO 模型下载失败
手动从 GitHub 下载 `yolov8n.pt` 放到项目根目录：
https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt

### Q4: 人脸识别功能不可用
需要 `opencv-contrib-python` 包才能使用 LBPH 人脸识别。确认已执行 `pip install -r requirements.txt`。

### Q5: 端口 5000 被占用
修改 `app.py` 最后一行的端口号，例如改为 8080：
```python
socketio.run(app, host='0.0.0.0', port=8080, debug=True, allow_unsafe_werkzeug=True)
```

### Q6: macOS/Linux 上 opencv 安装失败
尝试：
```bash
pip install opencv-contrib-python==4.10.0.84
```

## 七、目录结构

```
smart_home_release/
├── app.py                  # 主程序入口
├── config.py               # 配置文件（温度阈值、模拟模式等）
├── models.py               # 数据库模型（6张表，含灯光记录）
├── database.py             # 数据库初始化 + 演示数据
├── requirements.txt        # Python 依赖清单
├── start.bat               # Windows 一键启动脚本
├── SETUP.md                # 本说明文件
├── routes/
│   ├── api.py              # 全部 REST API（8大模块）
│   └── pages.py            # 页面路由
├── services/
│   ├── device_manager.py   # 设备管理器
│   ├── sensor_simulator.py # 传感器模拟器
│   ├── object_detection.py # YOLO 物体检测
│   └── face_recognition_service.py  # 人脸识别
├── templates/              # 前端页面模板（7个）
├── static/                 # CSS / JS 静态资源
├── data/                   # 数据库存放（自动生成）
├── uploads/                # 上传文件存放
│   ├── detections/
│   └── faces/
└── known_faces/            # 人脸样本存放
```

## 八、数据库表说明

| 表名 | 说明 |
|------|------|
| `authorized_persons` | 授权人员信息 |
| `access_logs` | 门禁访问日志 |
| `temperature_logs` | 温度/湿度记录 |
| `device_status_logs` | 设备状态操作日志 |
| `detection_records` | YOLO 物体检测记录 |
| `lighting_records` | **灯光专用记录（开灯/关灯/亮度/能耗/来源）** |

## 九、关闭系统

在终端按 `Ctrl + C` 即可停止服务器。
