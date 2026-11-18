# Orange Pi 融合与首次联调说明

## 基线与保护范围

本目录 `/home/HwHiAiUser/Projects/smart-home-project-merged` 基于 GitHub main
`7136f15594783f1442dac10c1b33e5f8fbdf02ca`（`7136f15 connet finish`）。
旧目录 `/home/HwHiAiUser/Projects/smart-home-project-github-latest` 仅用于静态比较，
不在旧目录启动测试、不 pull、不修改、不覆盖数据库、人脸文件或模型。

主线保留：最新 YOLO/灯泡权重与检测逻辑、摄像头采集流、哨兵功能及新页面、
HardwareService / SerialBridge、QENV、FAN/LAMP、环境 telemetry 和最新固件源码。
最新灯泡模型阈值为 0.55。固件和模型不作融合改写。

移植的是旧版本经过验证的安全约束：USB 身份绑定、OPEN 禁止重试、失败不假成功、
模拟/真实数据隔离、ACK 与物理状态分离、只读 preflight 以及相关测试。
未复制旧 hardware_adapter.py、旧协议分发器、旧 UI 整页或旧模型；硬件通信仍只有
DeviceManager → HardwareService → SerialBridge 一套架构。

## 板卡身份与接线

| 角色 | 板卡 | 实测 USB Serial Number |
| --- | --- | --- |
| Door | UNOII | `3433031323135141F0D1` |
| Environment | UNOI | `24238313635351910130` |

身份仅写在 `config/hardware.env.example` 和本文，业务代码从环境变量读取。
Linux 每次连接/重连枚举 pyserial 的 serial_number，精确匹配唯一设备，动态获取
当前 `/dev/ttyACM*`。没有配置、找不到、匹配多个或两角色配置相同身份时明确失败；
不按 tty 编号、VID、描述或枚举顺序猜测角色，也不回退到手写 tty 路径。

ASRPRO 已采用 SoftwareSerial 9600：TX → UNO A3，RX ← UNO A4；
D0/D1 保留给 USB Hardware Serial。首次联调只核对实际接线是否与此一致，
不再要求按旧 D0/D1 冲突方案断开语音模块。

## 安全行为与数据源

- `SerialBridge.send()` 将命令名规范化后，对 OPEN 强制 retries=0；
  `open_door()` 也明确传入 0。全局或调用方指定更高重试次数均不能覆盖。
  超时表示“未确认”，可能已执行，禁止自动再次开门。查询仍可合理重试。
- 启用硬件后即使服务初始化失败，也保留硬件控制入口。缺板、权限失败、断线、
  timeout 返回失败；设备控制 API 返回 HTTP 503/code=1，不退回 mock 成功。
- OPEN OK 是 command accepted。门状态保存 command_state、locked=null、
  physical_position=unknown、position_confirmed=false。
  BOOT、自动关门事件和等待计时器均不当作位置传感器证据。
- `SMART_HOME_SERIAL_ENV_ENABLED=1` 时环境数据源始终为 hardware，
  即便 SIMULATION_MODE=true、板卡断开也不会运行 simulator 或接受模拟注入。
  无有效读数显示未上报，DHT 无效或数据过期不填入默认 25℃/50%。
  真实温湿度不再触发软件自动风扇控制，保留固件自治与 FAN/LAMP 交互。
- 模拟环境历史使用 `data/smart_home.db`，真实环境使用独立的
  `data/smart_home_hardware.db`，真实库不填入演示数据。页面明确标明数据源。
  本轮仅用临时/内存数据库测试，没有创建、迁移或覆盖这些运行数据库。
  独立真实库首次启用时人员表为空；真实人脸联调前需要另行确认授权人员及
  embeddings/known_faces 的迁移或重新注册方案，不能直接用 mock 库覆盖真实库。
- 默认配置仍为 mock，两条 serial enabled 均为 0。本轮未启用真实串口。

## 第一条命令：只读 preflight

未来插板后，在 Orange Pi SSH 终端执行：

```bash
cd ~/Projects/smart-home-project-merged && source /usr/local/miniconda3/bin/activate && conda activate base && source config/hardware.env.example && python scripts/hardware_preflight.py
```

示例文件只设置当前 shell 的身份和 mock 配置，不启动服务、不打开串口。
preflight 不导入应用、不创建 Serial，只读枚举 USB、检查 pyserial/dialout、
设备 read/write 权限、角色缺失/歧义，以及 GET `/api/hardware/status`。
它分别报告 shell 的 configured_mode 和运行服务的 mode；服务未运行时为 unknown，
不能假设是 mock。退出码 0 需要设备身份/权限就绪且模式匹配，否则返回 1。
`--status-url` 可以指定服务地址；必须确认目标服务来自本融合目录，不能把仍在运行的
旧副本响应当作新版本验证。inventory_ready 不代表已授权开门，也不验证固件行为。

## 软件回归

使用原 Conda base/Python 3.9 环境，不安装依赖：

```bash
python scripts/run_software_tests.py
```

测试在临时目录运行，禁止构造真实 Serial，Flask 启动测试使用临时数据库、
替身视觉服务并禁止摄像头访问。覆盖假串口协议、USB 身份、OPEN 无重试、
真实数据拒绝模拟注入、活体拒绝不动作、API 失败、ACK 状态及 preflight。
Flask 的 mock 和硬件启动失败场景分别用本地临时 HTTP 服务验证 7 个页面及状态 API。
这些结果不代表真机摄像头、YOLO、InsightFace 或 Arduino 已实测通过。

## 固定首次真机联调顺序

插入 Arduino → 只读识别 → preflight → 确认两个 Serial Number
→ 明确授权后显式启用 Hardware Mode → 查看 `/devices` 的 Hardware Status 和
`/api/hardware/status` → 首先测试 QRAIN / QENV
→ 测试 USB disconnect/reconnect 与设备节点交换
→ 核对 ASRPRO A3/A4、9600 及 D0/D1 专供 USB
→ 经明确授权后测试 OPEN → 最后测试 Face Recognition → OPEN。

真正启用两板需要设置 `SMART_HOME_SERIAL_ENABLED=1`、
`SMART_HOME_SERIAL_ENV_ENABLED=1`、`SMART_HOME_SIMULATION_MODE=false` 并启动新服务。
本轮不执行这一步。打开串口可能触发 UNO reset，后台会自动发查询/心跳；
因此不能把启用硬件服务当成只读 preflight。

仍需真机验证：两板身份和权限、固件原始回包/协议能力、QRAIN/QENV 与无效 DHT、
拔插恢复、语音接线、ACK 丢失及自动关门事件、FAN/LAMP 的自治/手动行为、
最后的人脸→OPEN。无门位置传感器时任何测试都不能建立“物理门位置已确认”。

## 本轮验证记录（2026-11-17）

- 原 Conda base：Python 3.9.2，pyserial 3.5，HwHiAiUser 属于 dialout。
- `python scripts/run_software_tests.py`：108 tests，全部 OK。
- 两种启动模式各验证 7 个 HTTP 页面（首页、设备、门禁、检测、哨兵、人员、分析）。
  Mock status 返回 mock；硬件初始化失败仍保持硬件入口，控制返回 503、无模拟采样。
- 只读 preflight 实测两板 present 且 read/write=true：Door 当前为 `/dev/ttyACM0`，
  Environment 当前为 `/dev/ttyACM1`。这些只是本次枚举结果，不作为配置固定下来。
- 当时端口 5000 无运行服务，running_application=unknown；inventory_ready=true，
  preflight 返回 1，原因是无法核对运行模式。这不是完整运行态 preflight 通过。
- 融合前后 SHA256 对比：旧目录 210 个文件、新 models 2 个、新 data 4 个、
  新 known_faces 8 个，变化为 0。没有迁移旧数据库、人脸文件或覆盖模型。
- git diff --check 通过；15 个已有文件修改、8 个新增文件，暂存区为空，无 commit/push。
- 没有打开真实串口、发送任何串口命令、操作摄像头、刷固件或修改权限/环境依赖。
- 软件准备已完成，可在明确授权启用串口后进入真实 QRAIN/QENV 阶段；真机结果待验证。


## UNOI 三态控制修复（本轮只做软件，不刷写）

### 用户提供的后续真机结果

Door QRAIN 已通过（未发送 OPEN）；Environment 使用 post-boot-wait=2 后获得
22.7℃/21.0%、valid=1；随后 Environment→Flask→API→真实数据库链路连续写入有效数据。
首帧 250/500/0 已被丢弃，未混入模拟历史。用户已将原 InsightFace 模型补入融合目录。
这些是用户提供的实测记录；本轮不重复连接两块已插入的 UNO，不启动真实应用。

### 根因与低温风扇的证据边界

旧固件 ON 设置 manual=true，OFF 设置 manual=false，OFF 和 AUTO 混淆。
风扇在高温时可下一轮重新开；灯在光敏检测到变暗时可重新亮，旧 2 秒 settle
只能抑制短暂变化，而且会提前更新 oldDarkState，不能建立持久手动关闭。
光敏是 LDR 数字输入 HIGH=暗、LOW=亮，连续超过 10 次相同读数确认；不是软件 lux 阈值。

另外，旧手动命令 syncReported() 后只有 ACK，没有对应输出 EVT。
SerialBridge 正确消费 ACK，但 HardwareService 不根据 ACK 猜测设备输出，
DeviceManager 因而可能一直保存 OFF。网页 switch 使用 /toggle，连续点击时可能
发出 FAN 1、FAN 1（灯亦同），没有真正发 OFF。本轮 fake API 测试复现了该路径。

旧固件源码在主机假 I/O 编译运行验证：温度=21.5℃时，FAN 1 后 fanManual=true、
引脚 LOW，持续转；收到 FAN 0 后 fanManual=false，controlFan() 写 HIGH，关闭。
setup 默认 fanManual=false、fanState=false、FAN_PIN=HIGH；applyFan 的定义为
LOW=开、HIGH=关。自治阈值仍为 >=30 开、<=28 关，28~30 保持。
因此 21.5℃ 的持续运行不能归因于正常 AUTO 温控：仍停留 manual ON 是已复现的
代码路径，停止 Flask 不会清除 Arduino 的 RAM 模式或输出。
当时是否真的收到 FAN 0 没有原始回包证明，不能把代码复现当作现场唯一原因。
若后续确认 FAN 0 已 ACK、输出 EVT OFF，而实体仍转，需再核对所烧固件及模块
有效电平/接线；本轮没有测量实体引脚，也没有更改有效电平。

### 新协议与状态机

| 命令 | 模式 | 输出/退出条件 |
| --- | --- | --- |
| FAN 1 | manual_on | 强制开，忽略温度 |
| FAN 0 | manual_off | 强制关，忽略温度 |
| FAN AUTO | auto | 立即按 30/28 温控判断，中间区间保持 |
| LAMP 1 <0~100> | manual_on | 强制开并设置亮度 |
| LAMP 0 | manual_off | 强制关，忽略光敏变化 |
| LAMP AUTO | auto | 立即按当前稳定光敏状态判断 |

手动 ON/OFF 不会因退出 Flask、断开主机或传感器变化自动释放。
只有显式 AUTO 恢复自治；板卡复位仍按原设计默认 AUTO、输出先关闭。
QENV、DHT-valid、温控阈值、接线、低电平风扇驱动、Door 固件与 OPEN 规则不变。

UNOI 启动横幅增加能力标记：`@BOOT 1 env-tristate-1`，协议主版本仍为 1。
每条手动/AUTO 控制均返回 ACK，并回报：
- `@EVT CTL MANUAL_ON|MANUAL_OFF|AUTO FAN|LAMP`
- `@EVT FAN ON|OFF` 或 `@EVT LAMP ON|OFF <亮度>`
模式和输出分别保存，输出仍以板端 EVT 为准。ACK 本身不伪装实际输出确认。
这是控制输出回报，不代表新增了风扇转速/灯光物理传感器。
重复 OFF 也会回报当前输出，方便恢复客户端状态。
旧固件的 FAN 参数使用 atoi，AUTO 可能被当作 0；软件只在识别到新能力标记时
允许 AUTO。新 ON/OFF 的保持语义必须配套刷写本次 UNOI，不能只更新 Python。

### 软件入口与固件来源

网页开关改为直接提交 on/off，不再由后端旧缓存推断 toggle；增加明确的恢复自动按钮。
API：POST `/api/devices/fan/control` 或 `/api/devices/light/control`，
JSON `{"status":"on"}`、`{"status":"off"}` 或 `{"status":"auto"}`。
mode 取值为 manual_on/manual_off/auto；无板端模式回报时页面显示未知。
串口失败仍返回错误，不把命令意图覆盖成实体成功；EVT 更新不会反向发命令。

待刷写的两个内容相同的源码文件：
`硬件代码/design-and-build-project-main/UNOI` 和 `UNOI.txt`。
`.bak` 文件仅是历史备份，不是本次刷写入口。UNOII 未修改。
本轮未运行刷写工具；用户确认后仅重新烧录 Environment UNOI。

### 软件验证与下一步最小真机验收

135 项测试通过，包含实际 UNOI 源码的 g++ 主机假 Arduino I/O 编译执行、
高低温 manual OFF 保持、光敏切换 manual OFF 保持、AUTO 滞回与亮暗恢复、
模式/输出 EVT、API 三态、失败保持旧状态以及旧 ACK-only toggle 问题复现。
主机 fake-I/O 编译不替代 Arduino AVR 工具链编译或电气验收。

下一步须另行明确授权，本轮不执行：
1. 仅烧录 Environment UNOI；检查身份与 `env-tristate-1` 横幅，Door 不动。
2. 取得有效 QENV，确认温度/有效标志，并先验证 FAN 0 / LAMP 0 有 ACK、
   MANUAL_OFF 与 OFF 事件，实体确实停止。
3. FAN 1 → FAN 0、LAMP 1 → LAMP 0，逐项记录原始回包，确认 UI 与实体一致。
4. 保持同一串口连接观察多轮 loop：高温/光敏变化不能覆盖 manual OFF。
   不用重开串口来检验保持，因为重开可能 DTR reset、恢复默认 AUTO。
5. 分别显式 AUTO，验证风扇 30/28 滞回、灯光亮暗控制及模式/状态回报。
6. 用网页再次 ON → OFF → AUTO；关闭 Flask 前先显式 OFF，观察实体保持关闭。
若低温 OFF 回包正确但实体仍转，停止继续动作，核查引脚输出与实际模块有效电平。
此阶段不需要 OPEN，也不需要改 Door。


## 2026-11-18 integration with upstream OLED changes

- UNOI source combines `MSG` OLED alerts with manual ON/OFF and explicit AUTO.
  FAN/LAMP AUTO remains gated on `env-tristate-1`; basic ON/OFF retains legacy ACK support.
  This source integration does not upload firmware or claim real-board validation.
- HardwareService retains the OLED message API and restores the AUTO entry points used
  by DeviceManager and the control page. SensorSimulator does not drive physical fans.
- `config/hardware.env.example` records both measured USB identities and defaults to
  simulation with both serial bridges disabled. Source it explicitly; enabling hardware
  opens ports and may reset boards. Do not use a test identity for real deployment.
- Databases, face galleries and `known_faces/` are now untracked runtime data.
  They were present in earlier commits; this change does not rewrite Git history.
  Before pulling this revision into an existing deployment, stop the application and
  back up those files outside the checkout: Git can remove previously tracked files
  when applying their removal. Restore the local files after the update; `.gitignore`
  then keeps them local. A new clone intentionally has no enrolled people or history.
- The running Orange Pi checkout was not updated during publication; this integration
  was validated in a separate worktree. Deployment is a separate step.
