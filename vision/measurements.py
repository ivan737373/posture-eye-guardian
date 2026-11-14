"""纯几何与校准逻辑；不依赖摄像头，便于测试。"""
import math
import statistics
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionConfig:
    shoulder_threshold_deg: float = 4.0
    head_threshold_ratio: float = 0.15
    hunchback_threshold_ratio: float = 0.40
    min_distance_cm: float = 50.0
    landmark_confidence: float = 0.6
    calibration_seconds: float = 3.0
    calibration_min_samples: int = 20
    calibration_timeout_seconds: float = 20.0
    max_sample_gap_seconds: float = 0.5

    def __post_init__(self):
        for name in ('shoulder_threshold_deg', 'head_threshold_ratio','hunchback_threshold_ratio',
                     'min_distance_cm', 'calibration_seconds',
                     'calibration_timeout_seconds', 'max_sample_gap_seconds'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name}必须为有限正数')
        if not 0 < self.landmark_confidence <= 1:
            raise ValueError('landmark_confidence必须在(0,1]')
        if self.calibration_min_samples < 2:
            raise ValueError('calibration_min_samples至少为2')
        if self.calibration_timeout_seconds <= self.calibration_seconds:
            raise ValueError('校准超时必须大于采样时长')


def pixel_point(landmark, width, height, confidence=None):
    if not all(math.isfinite(v) for v in (landmark.x, landmark.y)):
        return None
    if not (0 <= landmark.x < 1 and 0 <= landmark.y < 1):
        return None
    if confidence is not None:
        for field in ('visibility', 'presence'):
            value = getattr(landmark, field, None)
            if value is not None and (not math.isfinite(value) or value < confidence):
                return None
    return (landmark.x * width, landmark.y * height)

def ear_shoulder_ratio(landmarks, width, height, confidence):
    """计算耳—肩水平距离比率；识别无效时返回None。"""
    if len(landmarks) < 13:
        return None, {}

    # 7左耳、8右耳、11左肩、12右肩
    # 左右指被检测者自身的左右，不是画面左右
    points = {
        i: pixel_point(landmarks[i], width, height, confidence)
        for i in (7, 8, 11, 12)
    }

    visible_points = {
        i: point
        for i, point in points.items()
        if point is not None
    }

    if len(visible_points) != 4:
        return None, visible_points

    left_ear = points[7]
    right_ear = points[8]
    left_shoulder = points[11]
    right_shoulder = points[12]

    dx = left_shoulder[0] - right_shoulder[0]
    dy = left_shoulder[1] - right_shoulder[1]
    shoulder_width = math.hypot(dx, dy)

    # 肩膀在画面中太窄，比例会不稳定，暂停判断
    if abs(dx) < width * 0.08 or shoulder_width < 20:
        return None, visible_points

    horizontal_distance = (
        abs(left_ear[0] - left_shoulder[0])
        + abs(right_ear[0] - right_shoulder[0])
    ) / 2

    ratio = horizontal_distance / shoulder_width

    return ratio, visible_points
def pose_features(landmarks, width, height, confidence):
    """图像左→右的肩线角度；鼻子相对肩中点的位置以肩宽归一化。"""
    if len(landmarks) < 13:
        return None, {}
    points = {i: pixel_point(landmarks[i], width, height, confidence)
              for i in (0, 11, 12)}
    if any(point is None for point in points.values()):
        return None, {i: p for i, p in points.items() if p is not None}
    left, right = sorted((points[11], points[12]), key=lambda p: p[0])
    dx, dy = right[0]-left[0], right[1]-left[1]
    span = math.hypot(dx, dy)
    if dx < width*0.08 or span < 20:
        return None, points
    cx, cy = (left[0]+right[0])/2, (left[1]+right[1])/2
    nose = points[0]
    return (math.degrees(math.atan2(dy, dx)),
            (nose[0]-cx)/span, (nose[1]-cy)/span), points


def face_features(landmarks, width, height):
    """脸侧点234/454的投影宽度；正脸门控只是经验规则，不是可靠头姿估计。"""
    if len(landmarks) <= 454:
        return None, {}, 'face_landmarks_incomplete'
    points = {i: pixel_point(landmarks[i], width, height)
              for i in (1, 33, 263, 234, 454)}
    if any(p is None for p in points.values()):
        return None, {i: p for i, p in points.items() if p is not None}, 'face_clipped'
    left, right = sorted((points[234], points[454]), key=lambda p: p[0])
    face_width = right[0]-left[0]
    if face_width < 30 or face_width/width < 0.05:
        return None, points, 'face_too_small'
    # 鼻子明显偏离两眼中点时暂停估距，降低转头误差。
    eye_left, eye_right = sorted((points[33], points[263]), key=lambda p: p[0])
    eye_span = eye_right[0]-eye_left[0]
    if eye_span < 10:
        return None, points, 'face_not_frontal'
    offset = abs(points[1][0]-(eye_left[0]+eye_right[0])/2)/eye_span
    if offset > 0.30:
        return None, points, 'face_not_frontal'
    return face_width/width, points, None


class Calibration:
    """只累计相邻有效帧间的短时间；无效帧和长间隔不计时。"""
    def __init__(self, config):
        self.config = config
        self.state = 'idle'
        self.reference = None
        self.samples = deque(maxlen=2000)
        self.valid_seconds = 0.0
        self.previous = None
        self.started = 0.0
        self.message = ''

    def start(self, now, reference=None):
        self.state, self.reference = 'collecting', reference
        self.samples.clear()
        self.valid_seconds, self.previous = 0.0, None
        self.started, self.message = now, 'collecting'

    def add(self, values, now, tolerances):
        if self.state != 'collecting':
            return None
        if now-self.started >= self.config.calibration_timeout_seconds:
            self.state, self.message = 'failed', 'timeout_press_key_to_retry'
            return None
        if values is None:
            self.previous = None
            self.message = 'waiting_for_valid_landmarks'
            return None
        if self.previous is not None:
            dt = now-self.previous
            if 0 < dt <= self.config.max_sample_gap_seconds:
                self.valid_seconds += dt
        self.previous = now
        self.samples.append(tuple(values))
        self.message = 'collecting'
        if (self.valid_seconds < self.config.calibration_seconds
                or len(self.samples) < self.config.calibration_min_samples):
            return None
        columns = list(zip(*self.samples))
        medians = tuple(statistics.median(col) for col in columns)
        stable = all(statistics.pstdev(col) <= limit
                     for col, limit in zip(columns, tolerances(medians)))
        if not stable:
            self.samples.clear()
            self.valid_seconds, self.previous = 0.0, None
            self.message = 'moved_too_much_hold_still'
            return None
        self.state, self.message = 'ready', 'calibrated'
        return medians

    def info(self):
        progress = min(self.valid_seconds/self.config.calibration_seconds,
                       len(self.samples)/self.config.calibration_min_samples, 1.0)
        return {'state': self.state, 'progress': progress,
                'valid_seconds': self.valid_seconds, 'samples': len(self.samples),
                'message': self.message}
