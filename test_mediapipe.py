from pathlib import Path
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


def main():
    # 根据当前脚本位置寻找模型，不依赖终端所在目录
    project_dir = Path(__file__).resolve().parent
    model_dir = project_dir / "models"

    pose_path = model_dir / "pose_landmarker_lite.task"
    face_path = model_dir / "face_landmarker.task"

    # 检查文件是否存在
    for path in (pose_path, face_path):
        if not path.is_file():
            raise FileNotFoundError(f"找不到模型文件：{path}")

    # 人体检测器配置
    pose_options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(pose_path)
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )

    # 人脸检测器配置
    face_options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(face_path)
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
    )

    camera = cv2.VideoCapture(0)

    try:
        if not camera.isOpened():
            raise RuntimeError("摄像头打开失败，请检查权限或是否被占用。")

        with (
            vision.PoseLandmarker.create_from_options(
                pose_options
            ) as pose_detector,
            vision.FaceLandmarker.create_from_options(
                face_options
            ) as face_detector,
        ):
            print("两个模型加载成功，点击画面后按英文 q 退出。")

            start_time = time.monotonic()
            last_timestamp = -1

            while True:
                success, frame = camera.read()

                if not success:
                    print("摄像头画面读取失败。")
                    break

                # OpenCV读取的是BGR，MediaPipe使用RGB
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb_frame,
                )

                # VIDEO模式要求时间戳递增，单位为毫秒
                timestamp = int(
                    (time.monotonic() - start_time) * 1000
                )
                timestamp = max(timestamp, last_timestamp + 1)
                last_timestamp = timestamp

                pose_result = pose_detector.detect_for_video(
                    image, timestamp
                )
                face_result = face_detector.detect_for_video(
                    image, timestamp
                )

                height, width = frame.shape[:2]

                # 绘制人体关键点：
                # 0鼻子、7左耳、8右耳、11左肩、12右肩
                if pose_result.pose_landmarks:
                    landmarks = pose_result.pose_landmarks[0]
                    points = {}

                    for index in (0, 7, 8, 11, 12):
                        landmark = landmarks[index]

                        # 暂不绘制可信度低或画面外的点
                        if (landmark.visibility or 0.0) < 0.5:
                            continue
                        if not (
                            0 <= landmark.x < 1
                            and 0 <= landmark.y < 1
                        ):
                            continue

                        x = int(landmark.x * width)
                        y = int(landmark.y * height)
                        points[index] = (x, y)

                        cv2.circle(
                            frame, (x, y), 6, (0, 255, 0), -1
                        )

                    # 两肩之间画线
                    if 11 in points and 12 in points:
                        cv2.line(
                            frame,
                            points[11],
                            points[12],
                            (0, 255, 0),
                            2,
                        )

                # 绘制人脸关键点
                if face_result.face_landmarks:
                    for landmark in face_result.face_landmarks[0]:
                        if not (
                            0 <= landmark.x < 1
                            and 0 <= landmark.y < 1
                        ):
                            continue

                        x = int(landmark.x * width)
                        y = int(landmark.y * height)

                        cv2.circle(
                            frame, (x, y), 1, (0, 255, 255), -1
                        )

                status = (
                    f"Pose: {bool(pose_result.pose_landmarks)}  "
                    f"Face: {bool(face_result.face_landmarks)}"
                )

                cv2.putText(
                    frame,
                    status,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )

                cv2.imshow("MediaPipe Test - Q to exit", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()