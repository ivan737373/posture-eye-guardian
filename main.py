"""main.py —— 程序入口。界面骨架由 B 提供，C 负责美化。"""

import queue
import time
import sys
import winsound

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QVBoxLayout, QWidget)

from data import database
from data.worker import start_monitor

POLL_MS = 50

class Toast(QLabel):
    """浮在窗口上方的提示条，几秒后自动消失。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background:rgba(231,76,60,235); color:white;"
            "font-size:22px; font-weight:bold;"
            "border-radius:12px; padding:18px 28px;"
        )
        self.hide()

    def popup(self, text, ms=3000):
        self.setText(text)
        self.adjustSize()
        p = self.parent()
        if p is not None:
            self.move(max((p.width() - self.width()) // 2, 10), 70)
        self.show()
        self.raise_()
        QTimer.singleShot(ms, self.hide)

# 要连线的关键点：(起点, 终点, 颜色BGR)
#叠加层配色
COLOR_BONE = (215, 215, 215)# 骨架连线：浅灰
COLOR_JOINT = (255, 255, 255)# 关键点：白
COLOR_FACE = (190, 170, 150) # 脸框：低饱和蓝灰
LINE_W = 1# 线宽

FACE_BOX_SCALE = 1.35# 框高 = 脸宽 × 此值，这个大家都可以调

POSE_LINKS = (
    (0, 11, COLOR_BONE),
    (0, 12, COLOR_BONE),
    (7, 11, COLOR_BONE),
    (8, 12, COLOR_BONE),
    (11, 12, COLOR_BONE),
)

POINTS_TO_DOT = (0, 7, 8, 11, 12)


def draw_overlay(frame, result):
    pts = ((result or {}).get("points") or {}).get("pose") or {}

    def get(i):
        v = pts.get(str(i))
        if not v or len(v) < 2:
            return None
        return int(v[0]), int(v[1])

    for a, b, color in POSE_LINKS:
        pa, pb = get(a), get(b)
        if pa and pb:
            cv2.line(frame, pa, pb, color, LINE_W, cv2.LINE_AA)

    for i in POINTS_TO_DOT:
        q = get(i)
        if q:
            cv2.circle(frame, q, 3, COLOR_JOINT, -1, cv2.LINE_AA)

    return frame

def draw_face_box(frame, result):
    """用脸颊宽度推出整张脸的高度，框住额头到下巴。"""
    face = ((result or {}).get("points") or {}).get("face") or {}

    def p(i):
        v = face.get(str(i))
        if not v or len(v) < 2:
            return None
        return int(v[0]), int(v[1])

    cheek_l, cheek_r = p(234), p(454)
    if not (cheek_l and cheek_r):
        return frame

    left_x, right_x = sorted((cheek_l[0], cheek_r[0]))
    w = right_x - left_x
    if w <= 0:
        return frame

    # 以眼角为参照线：眼睛在上方，往上留一点额头，往下按比例补到下巴
    eyes = [q[1] for q in (p(33), p(263)) if q]
    ref_y = min(eyes) if eyes else cheek_l[1]

    top_y = ref_y - int(w * 0.30)
    bottom_y = top_y + int(w * FACE_BOX_SCALE)

    cv2.rectangle(frame, (left_x, top_y), (right_x, bottom_y),
                  COLOR_FACE, LINE_W, cv2.LINE_AA)
    cv2.putText(frame, f"{w}px", (left_x, top_y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_FACE, 1, cv2.LINE_AA)
    return frame

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("健康坐姿助手")
        self.resize(960, 720)

        self._worker = None
        self._result_q = None
        self._breaking = False

        self._build_ui()

        database.init_db()
        self._worker, self._result_q = start_monitor()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    #界面
    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)

        self.lbl_video = QLabel("正在打开摄像头…")
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setMinimumSize(640, 480)
        self.lbl_video.setStyleSheet("background:#111; color:#888;")
        lay.addWidget(self.lbl_video, stretch=1)

        self.lbl_status = QLabel("初始化中…")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("font-size:20px; font-weight:bold;")
        lay.addWidget(self.lbl_status)

        row = QHBoxLayout()
        self.lbl_shoulder = QLabel("肩部: -")
        self.lbl_head = QLabel("头部: -")
        self.lbl_hunch = QLabel("驼背: -")
        self.lbl_close = QLabel("距离: -")
        for w in (self.lbl_shoulder, self.lbl_head, self.lbl_hunch, self.lbl_close):
            row.addWidget(w)
        row.addStretch()
        self.lbl_work = QLabel("已连续工作 00:00")
        row.addWidget(self.lbl_work)
        lay.addLayout(row)

        btns = QHBoxLayout()
        self.btn_calib_p = QPushButton("校准坐姿")
        self.btn_calib_d = QPushButton("校准距离")
        self.btn_reset = QPushButton("重置校准")
        self.btn_resume = QPushButton("我休息好了")
        self.btn_resume.setEnabled(False)
        self.btn_calib_p.clicked.connect(lambda: self._worker.start_posture_calibration())
        self.btn_calib_d.clicked.connect(lambda: self._worker.start_distance_calibration(60.0))
        self.btn_reset.clicked.connect(lambda: self._worker.reset_calibration())
        self.btn_resume.clicked.connect(self._on_resume)
        for b in (self.btn_calib_p, self.btn_calib_d, self.btn_reset, self.btn_resume):
            btns.addWidget(b)
        lay.addLayout(btns)

    #轮询

    def _poll(self):
        if self._result_q is None:
            return
        while True:
            try:
                msg = self._result_q.get_nowait()
            except queue.Empty:
                break
            t = msg.get("type")
            if t == "frame":
                self._show_frame(msg["frame"], msg["result"])
                self._apply(msg["result"])
            elif t == "alert":
                self.lbl_status.setText("⚠ " + msg.get("text", ""))
                self.lbl_status.setStyleSheet(
                    "font-size:20px; color:#e74c3c; font-weight:bold;")
                self._alert_until = time.time() + 3.0
            elif t == "break_required":
                self._on_break(msg.get("seconds", 300))
            elif t == "fatal":
                self.lbl_status.setText("启动失败：" + msg.get("message", ""))
                self.lbl_status.setStyleSheet("font-size:16px; color:#e74c3c;")
                self.lbl_video.setText(msg.get("message", ""))
            elif t == "stalled":
                self.lbl_status.setText("摄像头断流，正在重试…")

        # 报警消息走独立队列
        if self._worker is not None:
            while True:
                try:
                    msg = self._worker.alerts.get_nowait()
                except queue.Empty:
                    break
                t = msg.get("type")
                if t == "alert":
                    text = msg.get("text", "请注意坐姿")
                    self.lbl_status.setText("⚠ " + text)
                    self.lbl_status.setStyleSheet(
                        "font-size:20px; color:#e74c3c; font-weight:bold;")
                    self._alert_until = time.time() + 3.0
                    self._toast.popup("⚠ " + text, 3000)  # ← 真正的浮层
                elif t == "break_required":
                    self._on_break(msg.get("seconds", 300))
                elif t == "fatal":
                    self.lbl_status.setText("启动失败：" + msg.get("message", ""))
                elif t == "stalled":
                    self.lbl_status.setText("摄像头断流，正在重试…")

        if self._worker:
            s = getattr(self._worker, "work_seconds", 0)
            self.lbl_work.setText(f"已连续工作 {s // 60:02d}:{s % 60:02d}")

    def _show_frame(self, frame, result):
        # 关键：先复制一份再画，别改到 worker 里的原图
        img_bgr = frame.copy()
        draw_overlay(img_bgr, result)
        draw_face_box(img_bgr, result)

        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.lbl_video.setPixmap(QPixmap.fromImage(img).scaled(
            self.lbl_video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _apply(self, r: dict):
        # 休息提示是持续状态，不能被每帧刷新覆盖
        if self._breaking:
            return

        pc = r.get("posture_calibration") or {}
        state = pc.get("state")

        # 报警期间不覆盖状态栏（让警告停留几秒）
        if time.time() < getattr(self, "_alert_until", 0):
            pass
        elif state == "collecting":
            pct = int(pc.get("progress", 0) * 100)
            self.lbl_status.setText(f"坐姿校准中… {pct}%   请坐正并保持不动")
            self.lbl_status.setStyleSheet("font-size:20px; color:#3498db; font-weight:bold;")
        elif state == "failed":
            self.lbl_status.setText("坐姿校准失败，请重新点「校准坐姿」")
            self.lbl_status.setStyleSheet("font-size:20px; color:#e74c3c; font-weight:bold;")
        elif not r.get("pose_detected", False):
            self.lbl_status.setText("未检测到人")
            self.lbl_status.setStyleSheet("font-size:20px; color:#999;")
        elif state == "ready":
            if r.get("overall_posture_abnormal") is True:
                self.lbl_status.setText("⚠ 坐姿不良")
                self.lbl_status.setStyleSheet("font-size:20px; color:#e74c3c; font-weight:bold;")
            else:
                self.lbl_status.setText("坐姿正常")
                self.lbl_status.setStyleSheet("font-size:20px; color:#2ecc71; font-weight:bold;")
        else:
            self.lbl_status.setText("尚未校准，请点「校准坐姿」")
            self.lbl_status.setStyleSheet("font-size:20px; color:#f39c12; font-weight:bold;")

        # 四个指标
        def chip(label, name, val):
            txt = "-" if val is None else ("异常" if val else "正常")
            label.setText(f"{name}: {txt}")

        chip(self.lbl_shoulder, "肩部", r.get("shoulder_abnormal"))
        chip(self.lbl_head, "头部", r.get("head_abnormal"))
        chip(self.lbl_hunch, "驼背", r.get("hunchback_abnormal"))

        dist = r.get("estimated_distance_cm")
        if isinstance(dist, (int, float)):
            flag = "" if r.get("too_close") is not True else "（过近）"
            self.lbl_close.setText(f"距离: {dist:.0f}cm{flag}")
        else:
            self.lbl_close.setText("距离: -")

    def _on_break(self, seconds):
        if self._breaking:
            return
        self._breaking = True
        self.lbl_status.setText(f"该休息了，起来活动 {seconds // 60} 分钟")
        self.lbl_status.setStyleSheet("font-size:20px; color:#f39c12; font-weight:bold;")
        self.btn_resume.setEnabled(True)
        self._alert_until = time.time() + 3.0
        self._toast.popup(f"该休息了，起来活动 {seconds // 60} 分钟", 5000)

    def _on_resume(self):
        if self._worker:
            self._worker.resume_after_break()
        self._breaking = False
        self._alert_until = 0.0
        self._toast = Toast(self)
        self.btn_resume.setEnabled(False)
        self.lbl_status.setText("休息结束，继续监测")
        self.lbl_status.setStyleSheet("font-size:20px; color:#2ecc71; font-weight:bold;")
        self._alert_until = time.time() + 2.0

    def closeEvent(self, event):
        self._timer.stop()
        if self._worker:
            self._worker.stop_and_wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()