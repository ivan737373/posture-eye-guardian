"""P坐姿校准,D距离校准,R清空,Q/ESC退出"""
import argparse
import cv2
from vision import PostureDetector


def number(value, digits=2):
    return '--' if value is None else f'{value:.{digits}f}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=['default', 'dshow'], default='default')
    parser.add_argument('--reference-cm', type=float, default=60.0)
    args = parser.parse_args()
    camera = (cv2.VideoCapture(args.camera, cv2.CAP_DSHOW) if args.backend == 'dshow'
              else cv2.VideoCapture(args.camera))
    try:
        if not camera.isOpened():
            raise RuntimeError('摄像头打不开：检查设备')
        with PostureDetector() as detector:
            print('P: 坐直并保持，开始坐姿校准')
            print(f'D: 正脸保持在镜头前约{args.reference_cm}cm，开始距离校准')
            print('R: 清空校准；Q/ESC/关闭窗口: 退出；本演示不报警、不保存数据')
            while True:
                ok, frame = camera.read()
                if not ok or frame is None:
                    print('摄像头读取失败'); break
                result = detector.detect(frame)
                display = frame.copy()
                for point in result['points']['pose'].values():
                    cv2.circle(display, tuple(map(int, point)), 5, (0,255,0), -1)
                for point in result['points']['face'].values():
                    cv2.circle(display, tuple(map(int, point)), 3, (0,255,255), -1)
                pose_points = result['points']['pose']
                if '11' in pose_points and '12' in pose_points:
                    cv2.line(display, tuple(map(int,pose_points['11'])),
                             tuple(map(int,pose_points['12'])), (0,255,0), 2)
                pc, dc = result['posture_calibration'], result['distance_calibration']
                head = result['head_relative_position']
                lines = [
                    f"Pose valid: {result['posture_landmarks_valid']} | Face valid: {result['distance_landmarks_valid']}",
                    f"Shoulder: {number(result['shoulder_tilt_deg'])} deg | delta: {number(result['shoulder_delta_deg'])}",
                    'Head x,y: --' if head is None else f"Head x,y: {head['x']:.2f}, {head['y']:.2f}",
                    f"Head sideways: {number(None if result['head_offset_from_baseline'] is None else result['head_offset_from_baseline']['x'])} | downward: {number(None if result['head_offset_from_baseline'] is None else result['head_offset_from_baseline']['y'])}",
                    f"Shoulder bad: {result['shoulder_abnormal']} | Head bad: {result['head_abnormal']} | Hunch bad: {result['hunchback_abnormal']}",
                    f"Face width: {number(result['face_width_px'],1)} px | distance: {number(result['estimated_distance_cm'],1)} cm (approx)",
                    f"Too close: {result['too_close']} | Down bad: {result['head_down_abnormal']} | Ear ratio bad: {result['ear_shoulder_abnormal']}",
                    f"P calibration: {pc['state']} {pc['progress']*100:.0f}% {pc['message']}",
                    f"D calibration: {dc['state']} {dc['progress']*100:.0f}% {dc['message']}",
                    'P: posture | D: distance | R: reset | Q: quit',
                ]
                # 单独一个面板记录数据，和摄像头画面分开
                panel = detector.np.zeros(
                    (30 * len(lines) + 20, max(1100, frame.shape[1]), 3),
                    dtype='uint8'
                )
                for i,line in enumerate(lines):
                    cv2.putText(panel,line,(10,25+30*i),cv2.FONT_HERSHEY_SIMPLEX,
                                0.55,(255,255,255),1)
                cv2.imshow('Camera - Q to quit', display)
                cv2.imshow('Vision status', panel)
                key = cv2.waitKey(1) & 0xff
                if key in (ord('q'), ord('Q'), 27): break
                if (cv2.getWindowProperty('Camera - Q to quit', cv2.WND_PROP_VISIBLE) < 1
                        or cv2.getWindowProperty('Vision status', cv2.WND_PROP_VISIBLE) < 1):
                    break
                if key in (ord('p'),ord('P')): detector.start_posture_calibration()
                if key in (ord('d'),ord('D')): detector.start_distance_calibration(args.reference_cm)
                if key in (ord('r'),ord('R')): detector.reset_calibration()
    except KeyboardInterrupt:
        print('已中断，正在释放摄像头')
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
