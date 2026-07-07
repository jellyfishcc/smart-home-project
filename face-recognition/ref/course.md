请为智能家居项目实现一个“本地人脸识别门禁模块”。

项目背景：
- 当前项目已经部署并可使用 InsightFace。
- 系统需要在无 CUDA 的普通电脑 CPU 环境下运行。
- 人脸识别模块用于控制智能家居入口门。
- 课程要求为“人脸识别开启门禁：至少实现 2 真 1 假”。
- 这里的“2 真 1 假”定义为：
  1. 至少登记两名授权用户；
  2. 两名授权用户的人脸均能识别成功并触发开门；
  3. 一名未登记人员识别失败，不能开门；
  4. 每次识别结果都需要保存到本地数据库或日志中。
- 当前阶段不强制实现活体检测；“假”指未授权人员，不是照片攻击或视频攻击。

请使用 Python 实现，优先采用以下技术：
- InsightFace：人脸检测和人脸特征提取；
- OpenCV：读取摄像头或图片；
- SQLite：保存授权人员、人脸特征和门禁记录；
- FastAPI：提供后端 API；
- 如果项目已有前端，则提供可直接调用的 HTTP 接口；
- 所有人脸数据只在本地处理，不使用云端人脸识别 API。

功能要求：

一、授权人员管理
1. 支持新增授权人员：
   - 姓名
   - 学号或编号
   - 是否启用
   - 多张注册人脸照片
2. 每名授权人员建议上传 3~5 张不同角度、不同光照条件下的人脸照片。
3. 对每张注册照片提取 InsightFace embedding，并保存到数据库。
4. 支持查看授权人员列表。
5. 支持删除或禁用某位授权人员。
6. 禁用后的人员即使人脸匹配，也不能开门。

二、人脸识别逻辑
1. 输入可以是：
   - 摄像头实时帧；
   - 前端上传的一张图片；
   - 本地测试图片。
2. 对输入图像执行人脸检测。
3. 默认只识别画面中最大的那张人脸。
4. 若未检测到人脸，返回“未检测到人脸”，不能开门。
5. 若检测到多张人脸，返回“检测到多人，请单人靠近摄像头”，不能开门。
6. 对检测到的人脸提取 embedding。
7. 使用余弦相似度与数据库中所有已启用授权人员的人脸 embedding 比较。
8. 对同一人员的多张注册 embedding，取最高相似度作为该人员的匹配分数。
9. 设置可配置的识别阈值，例如：
   FACE_MATCH_THRESHOLD = 0.45
   该阈值必须写入配置文件或环境变量，不能写死在业务逻辑中。
10. 若最高相似度大于等于阈值：
   - 返回识别成功；
   - 返回人员姓名、编号、相似度；
   - 触发开门动作；
   - 记录一次“授权通过”的门禁日志。
11. 若最高相似度低于阈值：
   - 返回“未知人员”；
   - 不开门；
   - 记录一次“拒绝访问”的门禁日志。

三、门禁控制接口
1. 人脸识别成功后，需要调用统一的开门函数，例如：
   open_door(person_id, source="face_recognition")
2. 初期可以先实现为软件模拟：
   - 修改 door_state 为 OPEN；
   - 输出日志；
   - 返回“门已打开”；
   - 3 秒后自动恢复为 CLOSED。
3. 门禁控制部分需要预留硬件接口，便于后续连接 Arduino、ESP32、串口或 HTTP 控制器。
4. 建议统一定义控制指令格式，例如：
   {
     "command": "OPEN_DOOR",
     "source": "face_recognition",
     "person_id": 1,
     "timestamp": "2026-07-06T20:00:00"
   }

四、数据库设计
请至少创建以下数据表：

1. authorized_persons
   - id
   - name
   - student_id
   - enabled
   - created_at

2. face_embeddings
   - id
   - person_id
   - embedding
   - source_image_path
   - created_at

3. access_logs
   - id
   - timestamp
   - person_id，可为空
   - detected_name，可为空
   - similarity_score，可为空
   - result，取值如 AUTHORIZED / DENIED / NO_FACE / MULTI_FACE
   - door_action，取值如 OPEN / NONE
   - snapshot_path，可为空

4. door_status
   - id
   - state，OPEN 或 CLOSED
   - updated_at
   - last_opened_by，可为空

五、后端 API
请实现并提供 Swagger 文档。建议包括：

1. POST /api/persons
   - 新增授权人员。

2. GET /api/persons
   - 获取授权人员列表。

3. PUT /api/persons/{person_id}/status
   - 启用或禁用授权人员。

4. DELETE /api/persons/{person_id}
   - 删除授权人员及其 embedding。

5. POST /api/persons/{person_id}/faces
   - 为指定人员上传注册照片并提取 embedding。

6. POST /api/face-recognition/verify
   - 上传一张待识别图片；
   - 返回识别结果和是否开门。

返回格式示例：
{
  "success": true,
  "result": "AUTHORIZED",
  "authorized": true,
  "person": {
    "id": 1,
    "name": "Person A",
    "student_id": "20260001"
  },
  "similarity_score": 0.68,
  "door_action": "OPEN",
  "message": "人脸识别成功，门已打开"
}

未授权人员示例：
{
  "success": true,
  "result": "DENIED",
  "authorized": false,
  "person": null,
  "similarity_score": 0.31,
  "door_action": "NONE",
  "message": "未知人员，拒绝开门"
}

7. GET /api/access-logs
   - 查询门禁历史记录；
   - 支持按时间范围、结果类型、人员姓名筛选。

8. GET /api/door/status
   - 获取当前门状态。

六、GUI 对接要求
请为前端提供清晰的数据接口，使 GUI 至少能展示：
1. 摄像头画面或上传图片区域；
2. 当前识别状态：
   - 识别中；
   - 授权通过；
   - 拒绝访问；
   - 未检测到人脸；
   - 检测到多人；
3. 识别成功时显示授权人员姓名和相似度；
4. 当前门状态：OPEN / CLOSED；
5. 最近门禁记录列表；
6. 授权人员管理页面或接口。

七、测试与验收要求
请提供完整测试脚本或测试说明，至少完成以下演示：

1. 注册两名授权人员：
   - Person A
   - Person B

2. 准备一名未登记人员：
   - Person C

3. 测试结果应满足：
   - Person A：识别成功，门打开，日志记录 AUTHORIZED；
   - Person B：识别成功，门打开，日志记录 AUTHORIZED；
   - Person C：识别失败，门不开，日志记录 DENIED；
   - 无人脸图片：返回 NO_FACE；
   - 多人脸图片：返回 MULTI_FACE。

八、工程要求
1. 代码结构清晰，拆分为：
   - database/
   - services/
   - routes/
   - models/
   - utils/
   - tests/
2. 不要把数据库操作、人脸识别逻辑和 API 路由写在同一个文件。
3. 使用 CPUExecutionProvider，确保没有 NVIDIA GPU 时也可以运行。
4. 对 InsightFace 模型加载失败、图片无法读取、数据库为空等情况进行异常处理。
5. 提供 README，说明：
   - 安装依赖；
   - 初始化数据库；
   - 如何注册两名授权人员；
   - 如何执行识别测试；
   - 如何启动 FastAPI 服务；
   - 如何访问 Swagger 页面。
6. 不要使用云端人脸识别服务。
7. 尽量保留现有项目结构，不要无关地重构其他模块。

请先检查当前项目文件结构和已有代码，再在现有项目基础上实现该模块。