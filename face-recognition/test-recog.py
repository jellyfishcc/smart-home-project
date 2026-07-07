import cv2
import onnxruntime as ort
from insightface.app import FaceAnalysis
from config import test_photo

print("ONNX Runtime Providers:", ort.get_available_providers())

app = FaceAnalysis(
    name="buffalo_l",
    root=r"D:\myproject\face-recognition\models",
    providers=["CPUExecutionProvider"]
)

# ctx_id=-1 表示 CPU；降低检测尺寸可减少 CPU 压力
app.prepare(ctx_id=-1, det_size=(320, 320))

image = cv2.imread(test_photo)
if image is None:
    raise FileNotFoundError(f"未找到 {test_photo}")

faces = app.get(image)

print(f"检测到 {len(faces)} 张人脸")

for index, face in enumerate(faces, start=1):
    print(f"人脸 {index}")
    print("  置信度:", round(float(face.det_score), 3))
    print("  特征向量长度:", len(face.embedding))

result = app.draw_on(image.copy(), faces)
cv2.imwrite(f"{test_photo.split('.')[0]}_result.jpg", result)

print(f"识别结果已保存到 {test_photo.split('.')[0]}_result.jpg")