# 本地人脸识别授权器

本项目目前提供一个精简的本地人脸授权模块：输入一张图片，返回其中的人脸是否已授权。

## 授权人脸目录

将授权人脸照片放入 `authorized_faces/` 下，每个人一个文件夹：

```text
authorized_faces/
  person_a/
    a1.jpg
    a2.jpg
  person_b/
    b1.jpg
```

文件夹名称将用作该人员的 `id` 和当前显示名称。  
每张注册照片应仅包含一张人脸。

## 配置

配置项位于 `config.py` 中，也可通过环境变量覆盖：

- `AUTHORIZED_FACES_DIR`：授权人脸目录，默认为 `./authorized_faces`
- `FACE_MATCH_THRESHOLD`：余弦相似度阈值，默认为 `0.45`
- `INSIGHTFACE_MODEL_ROOT`：模型根目录，默认为 `./models`
- `INSIGHTFACE_MODEL_NAME`：模型名称，默认为 `buffalo_l`

InsightFace 使用 `CPUExecutionProvider` 初始化。

## 验证单张图片

```powershell
python main.py path\to\input.jpg
```

示例结果：

```json
{
  "success": true,
  "result": "AUTHORIZED",
  "authorized": true,
  "person": {
    "id": "person_a",
    "name": "person_a"
  },
  "similarity_score": 0.68,
  "door_action": "OPEN",
  "message": "人脸识别成功，门已打开"
}
```

可能的 `result` 取值：

- `AUTHORIZED`：识别为授权人员
- `DENIED`：检测到人脸但相似度低于阈值
- `NO_FACE`：未检测到人脸
- `MULTI_FACE`：检测到多于一张人脸

## 测试

```powershell
python -m unittest tests.test_face_authorizer
```
