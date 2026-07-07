# smart home project

## 使用 face-recognition 模块

主项目已经在 `pyproject.toml` 中以 editable 方式引用 `face-recognition`，先安装依赖：

```powershell
uv sync
```

首次克隆项目后，模型文件不会随 GitHub 自动下载。运行下面命令会把 InsightFace 的 `buffalo_l` 模型准备到 `face-recognition/models/models/buffalo_l/`：

```powershell
uv run python scripts/download_face_models.py
```

在主程序里直接导入 `smart_home_face` 提供的构建函数，启动时创建一次授权器，后续拿摄像头抓拍图或本地图片做校验：

```python
from smart_home_face.cli import build_authorizer

authorizer = build_authorizer()
result = authorizer.verify_image("path/to/camera_snapshot.jpg")

if result.authorized:
    # 开门或执行已授权逻辑
    print(result.person, result.door_action)
else:
    # 拒绝开门或提示未授权
    print(result.result, result.message)
```

授权人脸照片放在 `face-recognition/authorized_faces/<人员名>/` 目录下，每个人一个文件夹。也可以先用命令行快速验证单张图片：

```powershell
uv run smart-home-face-verify path\to\camera_snapshot.jpg
```
