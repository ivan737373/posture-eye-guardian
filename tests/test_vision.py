import unittest
import math
import json
from types import SimpleNamespace as NS
from unittest.mock import patch
import numpy as np

from vision.measurements import (VisionConfig, Calibration, pose_features,
                                  face_features, pixel_point)
from vision import PostureDetector


def point(x=0.5, y=0.5, visibility=1.0):
    return NS(x=x,y=y,visibility=visibility,presence=1.0)


def poses():
    p=[point() for _ in range(33)]
    p[0]=point(.5,.25); p[11]=point(.3,.6); p[12]=point(.7,.6)
    return p


def faces(scale=1.0):
    p=[point() for _ in range(478)]
    p[1]=point(.5,.4)
    p[33]=point(.5-.1*scale,.3); p[263]=point(.5+.1*scale,.3)
    p[234]=point(.5-.2*scale,.4); p[454]=point(.5+.2*scale,.4)
    return p


def mock_detector():
    # 只模拟模型推理，实际运行几何、校准、detect返回逻辑。
    d=PostureDetector.__new__(PostureDetector)
    d.config=VisionConfig()
    d.np=np; d.cv2=NS(COLOR_BGR2RGB=1,cvtColor=lambda frame,code:frame)
    d.mp=NS(ImageFormat=NS(SRGB=1),Image=lambda **kwargs:kwargs)
    d._closed=False; d._timestamp=-1; d._origin=0; d._shape=None
    d._pose_baseline=d._face_baseline=None
    d.pose_calibration=Calibration(d.config); d.distance_calibration=Calibration(d.config)
    d.pose_data=poses(); d.face_data=faces()
    d._pose=NS(detect_for_video=lambda *args:NS(pose_landmarks=[d.pose_data] if d.pose_data else []))
    d._face=NS(detect_for_video=lambda *args:NS(face_landmarks=[d.face_data] if d.face_data else []))
    return d


class GeometryTests(unittest.TestCase):
    def test_pose_geometry_and_confidence(self):
        p=poses(); f,_=pose_features(p,640,480,.6)
        self.assertAlmostEqual(f[0],0)
        self.assertAlmostEqual(f[1],0)
        self.assertLess(f[2],0)
        p[12].y=.7
        tilted,_=pose_features(p,640,480,.6)
        self.assertGreater(tilted[0],0)
        p[11].visibility=.1
        self.assertIsNone(pose_features(p,640,480,.6)[0])
        self.assertIsNone(pixel_point(point(float('nan'),.5),640,480))

    def test_face_rotation_clipping_size(self):
        f=faces(); ratio,_,reason=face_features(f,640,480)
        self.assertAlmostEqual(ratio,.4); self.assertIsNone(reason)
        self.assertAlmostEqual(face_features(f,1280,960)[0],ratio)
        f[1].x=.65
        self.assertEqual(face_features(f,640,480)[2],'face_not_frontal')
        f[234].x=-.1
        self.assertEqual(face_features(f,640,480)[2],'face_clipped')
        self.assertEqual(face_features(faces(.1),640,480)[2],'face_too_small')


class CalibrationTests(unittest.TestCase):
    def test_effective_time_only(self):
        c=Calibration(VisionConfig(calibration_seconds=1,calibration_min_samples=3))
        c.start(0)
        c.add((1,),0,lambda _: (1,))
        c.add((1,),.2,lambda _: (1,))
        c.add(None,.3,lambda _: (1,))
        c.add((1,),1.5,lambda _: (1,))
        self.assertAlmostEqual(c.valid_seconds,.2)
        c.add((1,),3,lambda _: (1,))
        self.assertAlmostEqual(c.valid_seconds,.2) # 超长帧间隔不累计
        value=None
        for t in (3.2,3.4,3.6,3.8,4.0):
            value=c.add((1,),t,lambda _: (1,)) or value
        self.assertEqual(c.state,'ready'); self.assertEqual(value,(1,))

    def test_unstable_and_timeout(self):
        c=Calibration(VisionConfig(calibration_seconds=.2,calibration_min_samples=3))
        c.start(0)
        for t,v in ((0,0),(.1,5),(.21,10)):
            c.add((v,),t,lambda _: (.01,))
        self.assertEqual(c.state,'collecting')
        self.assertEqual(len(c.samples),0)
        c.add(None,21,lambda _: (.01,))
        self.assertEqual(c.state,'failed')


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.d=mock_detector(); self.frame=np.zeros((480,640,3),dtype=np.uint8)

    def detect_at(self,t):
        with patch('vision.detector.time.monotonic',return_value=t):
            return self.d.detect(self.frame)

    def calibrate(self):
        with patch('vision.detector.time.monotonic',return_value=0):
            self.d.start_posture_calibration(); self.d.start_distance_calibration(60)
        r=None
        for i in range(33): r=self.detect_at(i*.1)
        return r

    def test_uncalibrated_and_loss(self):
        r=self.detect_at(0)
        self.assertTrue(r['tracking_valid']); self.assertFalse(r['posture_evaluable'])
        self.assertIsNone(r['posture_abnormal']); self.assertIsNone(r['too_close'])
        self.calibrate()
        self.d.pose_data=[]; self.d.face_data=[]
        r=self.detect_at(4)
        self.assertFalse(r['tracking_valid']); self.assertIsNone(r['posture_abnormal'])
        self.assertIsNone(r['estimated_distance_cm']); self.assertIsNone(r['too_close'])
        json.dumps(r,allow_nan=False)

    def test_calibrated_distance_and_head(self):
        r=self.calibrate()
        self.assertTrue(r['posture_evaluable']); self.assertTrue(r['distance_evaluable'])
        self.assertFalse(r['posture_abnormal']); self.assertAlmostEqual(r['estimated_distance_cm'],60)
        self.d.face_data=faces(1.5)
        self.d.pose_data[0].x=.62
        r=self.detect_at(4)
        self.assertAlmostEqual(r['estimated_distance_cm'],40)
        self.assertTrue(r['too_close']); self.assertTrue(r['head_abnormal'])
        self.assertTrue(r['posture_abnormal'])
        json.dumps(r,allow_nan=False)
        self.assertFalse(self.frame.any()) # detect不修改输入图像

    def test_shoulder_settings_and_independent_validity(self):
        self.calibrate()
        self.d.pose_data[12].y=.7
        r=self.detect_at(4)
        self.assertTrue(r['shoulder_abnormal'])
        self.d.face_data[1].x=.65
        r=self.detect_at(5)
        self.assertTrue(r['posture_evaluable']); self.assertFalse(r['distance_evaluable'])
        self.assertIsNone(r['too_close'])
        self.d.update_settings(shoulder_threshold_deg=30)
        self.assertFalse(self.detect_at(6)['shoulder_abnormal'])
        with self.assertRaises(ValueError): self.d.update_settings(min_distance_cm=-1)
        with self.assertRaises(ValueError): self.d.update_settings(unknown=1)

    def test_size_reset_timestamp_and_input(self):
        self.calibrate()
        r=self.detect_at(4); old=r['timestamp_ms']
        self.assertGreater(self.detect_at(4)['timestamp_ms'],old)
        self.frame=np.zeros((240,320,3),dtype=np.uint8)
        r=self.detect_at(5)
        self.assertFalse(r['posture_calibrated']); self.assertFalse(r['distance_calibrated'])
        self.assertIn('frame_size_changed_recalibrate',r['reasons'])
        with self.assertRaises(ValueError): self.d.detect(None)
        with self.assertRaises(ValueError): self.d.start_distance_calibration(float('nan'))
        self.d._closed=True
        with self.assertRaises(RuntimeError): self.d.detect(self.frame)


if __name__=='__main__': unittest.main()
