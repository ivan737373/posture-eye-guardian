"""A交给B的接口：result = detector.detect(frame)。不打开摄像头、不报警、不存数据库。
在同一个后台线程中创建、调用、关闭；不要跨线程同时使用一个实例。
"""
import math
import time
from pathlib import Path
from contextlib import ExitStack
from dataclasses import replace

from .measurements import (VisionConfig, Calibration, pose_features, face_features,ear_shoulder_ratio)


class PostureDetector:
    def __init__(self, model_dir=None, config=None):
        import cv2
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self.cv2, self.mp, self.np = cv2, mp, np
        self.config = config or VisionConfig()
        self._stack = ExitStack()
        self._closed = False
        self._timestamp = -1
        self._origin = time.monotonic()
        self._pose_baseline = self._face_baseline = None
        self._shape = None
        self.pose_calibration = Calibration(self.config)
        self.distance_calibration = Calibration(self.config)
        root = Path(model_dir) if model_dir else Path(__file__).resolve().parents[1]/'models'
        pose_path, face_path = root/'pose_landmarker_lite.task', root/'face_landmarker.task'
        for path in (pose_path, face_path):
            if not path.is_file():
                raise FileNotFoundError(f'找不到模型：{path}')
        try:
            self._pose = self._stack.enter_context(vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=python.BaseOptions(model_asset_path=str(pose_path)),
                    running_mode=vision.RunningMode.VIDEO, num_poses=1)))
            self._face = self._stack.enter_context(vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=python.BaseOptions(model_asset_path=str(face_path)),
                    running_mode=vision.RunningMode.VIDEO, num_faces=1)))
        except BaseException:
            self._stack.close()
            raise

    def update_settings(self, **settings):
        """由B在检测线程调用；校准参数不允许运行中修改。"""
        allowed = {'shoulder_threshold_deg', 'head_threshold_ratio','hunchback_threshold_ratio',
                   'min_distance_cm', 'landmark_confidence'}
        if not set(settings) <= allowed:
            raise ValueError(f'只能修改：{sorted(allowed)}')
        self.config = replace(self.config, **settings)
        self.pose_calibration.config = self.distance_calibration.config = self.config

    def start_posture_calibration(self):
        self._pose_baseline = None
        self.pose_calibration.start(time.monotonic())

    def start_distance_calibration(self, known_distance_cm=60.0):
        """用尺量摄像头镜头到面部的大致距离；不是直接量眼睛到屏幕。"""
        if not math.isfinite(known_distance_cm) or known_distance_cm <= 0:
            raise ValueError('参考距离必须为有限正数')
        self._face_baseline = None
        self.distance_calibration.start(time.monotonic(), float(known_distance_cm))

    def reset_calibration(self):
        self._pose_baseline = self._face_baseline = None
        self.pose_calibration = Calibration(self.config)
        self.distance_calibration = Calibration(self.config)

    def detect(self, frame):
        """输入uint8、H×W×3、BGR图像；返回可JSON序列化的字典。
        不修改输入frame；标记点放在返回值points中，交给展示层使用。
        """
        if self._closed:
            raise RuntimeError('检测器已经关闭')
        if (not isinstance(frame, self.np.ndarray) or frame.dtype != self.np.uint8
                or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0):
            raise ValueError('frame必须是非空uint8 BGR三通道图像')
        now = time.monotonic()
        height, width = frame.shape[:2]
        reasons = []
        # 分辨率或图像比例改变后必须重新校准，避免沿用错误基准。
        if self._shape is not None and self._shape != (height, width):
            self.reset_calibration()
            reasons.append('frame_size_changed_recalibrate')
        self._shape = (height, width)
        timestamp = max(int((now-self._origin)*1000), self._timestamp+1)
        self._timestamp = timestamp
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        pose_result = self._pose.detect_for_video(image, timestamp)
        face_result = self._face.detect_for_video(image, timestamp)
        pose_detected, face_detected = bool(pose_result.pose_landmarks), bool(face_result.face_landmarks)
        pose, pose_points = None, {}
        hunchback_ratio = None
        face_width_ratio, face_points, face_reason = None, {}, 'no_face'
        if pose_detected:
            landmarks = pose_result.pose_landmarks[0]

            # 保留原来的肩部倾斜、头部位置偏移检测
            pose, pose_points = pose_features(
                landmarks, width, height,
                self.config.landmark_confidence
            )

            # 新增：耳朵到肩膀的水平距离比率
            hunchback_ratio, ear_points = ear_shoulder_ratio(
                landmarks, width, height,
                self.config.landmark_confidence
            )

            # 合并关键点，方便画面显示耳朵位置
            pose_points.update(ear_points)
        if face_detected:
            face_width_ratio, face_points, face_reason = face_features(
                face_result.face_landmarks[0], width, height)
        if pose is None:
            reasons.append('pose_missing_or_low_confidence')
        if face_reason:
            reasons.append(face_reason)
        new_pose = self.pose_calibration.add(
            pose, now, lambda medians: (2.0, 0.04, 0.04))
        if new_pose is not None:
            self._pose_baseline = new_pose
        new_face = self.distance_calibration.add(
            None if face_width_ratio is None else (face_width_ratio,), now,
            lambda medians: (medians[0]*0.04,))
        if new_face is not None:
            self._face_baseline = (new_face[0], self.distance_calibration.reference)
        posture_calibrated, distance_calibrated = self._pose_baseline is not None, self._face_baseline is not None
        posture_evaluable = pose is not None and posture_calibrated
        distance_evaluable = face_width_ratio is not None and distance_calibrated
        shoulder_delta = head_dx = head_dy = head_shift = None
        shoulder_bad = head_bad = posture_bad = None
        head_down_bad = None

        if posture_evaluable:
            shoulder_delta = pose[0] - self._pose_baseline[0]

            # 相对校准位置：x为左右偏移，y为上下偏移
            head_dx = pose[1] - self._pose_baseline[1]
            head_dy = pose[2] - self._pose_baseline[2]

            # 保留总偏移量用于观察，不再用于Head bad判定
            head_shift = math.hypot(head_dx, head_dy)

            shoulder_bad = (
                abs(shoulder_delta) > self.config.shoulder_threshold_deg
            )

            # Head bad：只判断左右偏移
            head_bad = (
                abs(head_dx) > self.config.head_threshold_ratio
            )

            # 图像y轴向下，所以只判断正方向的偏移
            head_down_bad = (
                head_dy > self.config.head_threshold_ratio
            )

            # 保留此字段为肩部与头部左右偏移的合并结果
            posture_bad = shoulder_bad or head_bad

        # 保留原来的耳—肩水平距离比率判定
        ear_shoulder_bad = None

        if posture_calibrated and hunchback_ratio is not None:
            ear_shoulder_bad = (
                hunchback_ratio > self.config.hunchback_threshold_ratio
            )

        if hunchback_ratio is None:
            reasons.append('ear_shoulder_landmarks_invalid')

        # Hunch bad：向下偏移或耳—肩比率异常，任意一个成立即可
        hunchback_flags = (head_down_bad, ear_shoulder_bad)

        if any(flag is True for flag in hunchback_flags):
            hunchback_bad = True
        elif all(flag is False for flag in hunchback_flags):
            hunchback_bad = False
        else:
            # 有一项无法判断，另一项也没有确认异常
            hunchback_bad = None

        hunchback_evaluable = hunchback_bad is not None

        # 肩部、头部左右偏移、疑似驼背的合并结果
        posture_flags = (shoulder_bad, head_bad, hunchback_bad)

        if any(flag is True for flag in posture_flags):
            overall_posture_bad = True
        elif all(flag is False for flag in posture_flags):
            overall_posture_bad = False
        else:
            overall_posture_bad = None
        distance_cm = too_close = None
        if distance_evaluable:
            baseline_width, known_cm = self._face_baseline
            distance_cm = known_cm*baseline_width/face_width_ratio
            too_close = distance_cm < self.config.min_distance_cm
        if not posture_calibrated:
            reasons.append('posture_not_calibrated')
        if not distance_calibrated:
            reasons.append('distance_not_calibrated')
        return {
            'timestamp_ms': timestamp,
            'pose_detected': pose_detected, 'face_detected': face_detected,
            # tracking_valid仅表示至少一类几何特征有效，不能代替各功能的evaluable。
            'tracking_valid': pose is not None or face_width_ratio is not None,
            'posture_landmarks_valid': pose is not None,
            'distance_landmarks_valid': face_width_ratio is not None,
            'posture_calibrated': posture_calibrated,
            'distance_calibrated': distance_calibrated,
            'posture_evaluable': posture_evaluable, 'distance_evaluable': distance_evaluable,
            'shoulder_tilt_deg': None if pose is None else pose[0],
            'shoulder_delta_deg': shoulder_delta,
            'head_relative_position': None if pose is None else {'x': pose[1], 'y': pose[2]},
            'head_offset_from_baseline': None if head_dx is None else {'x': head_dx, 'y': head_dy},
            'head_shift_ratio': head_shift,
            'shoulder_abnormal': shoulder_bad, 'head_abnormal': head_bad,
            'posture_abnormal': posture_bad,
            # 方便B区分Hunch bad具体由哪个条件触发
            'head_down_abnormal': head_down_bad,
            'ear_shoulder_abnormal': ear_shoulder_bad,
            'hunchback_ratio': hunchback_ratio,
            'hunchback_evaluable': hunchback_evaluable,
            'hunchback_abnormal': hunchback_bad,

            # 肩部、头部位置、疑似驼背三项的合并结果
            'overall_posture_abnormal': overall_posture_bad,
            'face_width_px': None if face_width_ratio is None else face_width_ratio*width,
            'face_width_ratio': face_width_ratio,
            'estimated_distance_cm': distance_cm, 'too_close': too_close,
            'posture_calibration': self.pose_calibration.info(),
            'distance_calibration': self.distance_calibration.info(),
            'reasons': reasons,
            'points': {'pose': {str(i): list(p) for i,p in pose_points.items()},
                       'face': {str(i): list(p) for i,p in face_points.items()}},
        }

    def close(self):
        if not self._closed:
            self._closed = True
            self._stack.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
