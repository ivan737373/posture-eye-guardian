"""B要输出肩部、头部左右、疑似驼背、距离过近。

项目根目录运行：python example_for_b.py
P坐姿校准；D距离校准；R重置；Q/ESC退出。
仅演示接口，不实现B的5秒持续计时、冷却、数据库或正式GUI。
"""
import argparse
import json

import cv2
from vision import PostureDetector


def extract_flags(result):
    """按各项有效性提取当前帧分类；None表示未知，不是正常。"""
    return {
        'shoulder': (result['shoulder_abnormal']
                     if result['posture_evaluable'] else None),
        'head': (result['head_abnormal']
                 if result['posture_evaluable'] else None),
        'hunchback': (result['hunchback_abnormal']
                      if result['hunchback_evaluable'] else None),
        'too_close': (result['too_close']
                      if result['distance_evaluable'] else None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=['default', 'dshow'], default='default')
    parser.add_argument('--reference-cm', type=float, default=60.0)
    args = parser.parse_args()
    camera = (cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
              if args.backend == 'dshow' else cv2.VideoCapture(args.camera))
    window = 'B integration example - P/D/R/Q'
    try:
        if not camera.isOpened():
            raise RuntimeError('摄像头打开失败：检查编号、权限及设备占用')
        # 正式项目中，创建、检测、配置、校准和关闭都在B的同一后台线程执行。
        # 此处不自动校准，避免把用户尚未准备好的姿势当作基准。
        with PostureDetector() as detector:
            print('P：端坐保持，校准坐姿；D：在参考距离正脸保持，校准距离')
            print(f'参考距离：镜头到面部约{args.reference_cm}cm，请先用尺量好')
            print('R：清除校准；Q/ESC/关闭窗口：退出')
            while True:
                ok, frame = camera.read()
                if not ok or frame is None or frame.size == 0:
                    # 正式后台遇到断流须中断连续异常计时，不能沿用上一帧结果。
                    raise RuntimeError('摄像头读取失败，检测已中断')
                result = detector.detect(frame)
                flags = extract_flags(result)

                # B在此分别更新四个计时器：
                # True连续超过5秒再请求提醒；False或None清零。
                # 断流、长帧间隔、重校准、规则变化时也应清除相关计时。
                # Hunch的两个子原因不要作为两个独立事件重复记录。
                print(json.dumps({
                    'flags': flags,
                    'hunchback_causes': {
                        'head_down': result['head_down_abnormal'],
                        'ear_shoulder': result['ear_shoulder_abnormal'],
                    },
                    'overall_posture': result['overall_posture_abnormal'],
                    'head_offset': result['head_offset_from_baseline'],
                    'hunchback_ratio': result['hunchback_ratio'],
                    'distance_cm': result['estimated_distance_cm'],
                    'posture_calibration': result['posture_calibration'],
                    'distance_calibration': result['distance_calibration'],
                    'reasons': result['reasons'],
                }, ensure_ascii=False))

                # 预览仅用于独立调试；正式GUI由C负责。
                display = frame.copy()
                lines = [
                    'P: posture calibration | D: distance | R: reset | Q: quit',
                    f"Shoulder: {flags['shoulder']} | Head: {flags['head']}",
                    f"Hunch: {flags['hunchback']} | Too close: {flags['too_close']}",
                    f"P: {result['posture_calibration']['state']} | D: {result['distance_calibration']['state']}",
                ]
                for i, line in enumerate(lines):
                    cv2.putText(display, line, (10, 25 + 25 * i),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                cv2.imshow(window, display)
                key = cv2.waitKey(1) & 0xff
                if key in (ord('q'), ord('Q'), 27):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
                # 每次命令只调用一次；随后继续detect收集校准样本。
                if key in (ord('p'), ord('P')):
                    detector.start_posture_calibration()
                if key in (ord('d'), ord('D')):
                    detector.start_distance_calibration(args.reference_cm)
                if key in (ord('r'), ord('R')):
                    detector.reset_calibration()
    except KeyboardInterrupt:
        print('已中断，正在释放资源')
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
