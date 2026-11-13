"""ui/main_window.py —— C 组员负责的主界面、交互与托盘"""

import time
import queue
import cv2
import threading
import win32com.client  # Windows 原生语音

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QSystemTrayIcon, QMenu, QDialog,
    QFormLayout, QSpinBox, QCheckBox
)

from data import database
from ui.charts import ChartDialog

POLL_MS = 50

# ==================== 语音播报模块（原生 SAPI，绝对不卡死） ====================
class VoiceEngine:
    def __init__(self):
        self.speech_queue = queue.Queue()
        self._stopped = False
        self._thread = threading.Thread(target=self._speech_worker, daemon=True, name="VoiceWorker")
        self._thread.start()

    def _speech_worker(self):
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            # 尝试找中文语音
            for voice in speaker.GetVoices():
                if "Chinese" in voice.GetDescription() or "中文" in voice.GetDescription():
                    speaker.Voice = voice
                    break
            
            while True:
                text = self.speech_queue.get()
                try:
                    if text is None: break
                    speaker.Speak(text)
                except Exception as exc:
                    print("[语音播报异常]", exc)
                finally:
                    self.speech_queue.task_done()
        except Exception as exc:
            print("[语音引擎初始化失败]", exc)

    def speak(self, text):
        if text and not self._stopped:
            self.speech_queue.put(text)

    def stop(self):
        if not self._stopped:
            self._stopped = True
            self.speech_queue.put(None)


# ==================== 全屏休息遮罩 ====================
class BreakOverlay(QWidget):
    def __init__(self, parent=None, on_resume=None):
        super().__init__(parent)
        self.on_resume = on_resume
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: rgba(15, 20, 25, 0.98);")
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        self.title = QLabel("该休息了！")
        self.title.setStyleSheet("color: #f39c12; font-size: 56px; font-weight: bold;")
        self.title.setAlignment(Qt.AlignCenter)
        
        self.subtitle = QLabel("站起来活动一下，喝杯水，眺望远方吧～\n保护颈椎，从此刻开始。")
        self.subtitle.setStyleSheet("color: #bdc3c7; font-size: 22px; margin-bottom: 50px; line-height: 1.5;")
        self.subtitle.setAlignment(Qt.AlignCenter)
        
        self.btn_resume = QPushButton("我休息好了，继续监测")
        self.btn_resume.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; color: white; border-radius: 12px;
                padding: 18px 50px; font-size: 22px; font-weight: bold;
            }
            QPushButton:hover { background-color: #27ae60; }
        """)
        self.btn_resume.setCursor(Qt.PointingHandCursor)
        self.btn_resume.clicked.connect(self._resume)

        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.btn_resume, alignment=Qt.AlignCenter)

    def _resume(self):
        if self.on_resume: self.on_resume()
        self.hide()


# ==================== 设置面板 ====================
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("偏好设置")
        self.setFixedWidth(320)
        self.setStyleSheet("background-color: #2c3e50; color: white; font-size: 14px;")
        self.settings = database.get_settings()
        
        layout = QFormLayout(self)
        
        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(1, 300) 
        self.spin_cooldown.setValue(int(self.settings.get("alert_cooldown_sec", 60)))
        layout.addRow("提醒冷却时间 (秒):", self.spin_cooldown)
        
        self.spin_distance = QSpinBox()
        self.spin_distance.setRange(30, 100)
        self.spin_distance.setValue(int(self.settings.get("distance_threshold_cm", 50)))
        layout.addRow("距离过近阈值 (cm):", self.spin_distance)
        
        self.chk_voice = QCheckBox("开启语音播报")
        self.chk_voice.setChecked(self.settings.get("voice_enabled", "true") == "true")
        layout.addRow(self.chk_voice)
        
        btn_save = QPushButton("保存并应用")
        btn_save.setStyleSheet("background-color: #3498db; padding: 8px; border-radius: 6px; font-weight: bold;")
        btn_save.clicked.connect(self.save_settings)
        layout.addRow(btn_save)

    def save_settings(self):
        database.set_setting("alert_cooldown_sec", self.spin_cooldown.value())
        database.set_setting("distance_threshold_cm", self.spin_distance.value())
        database.set_setting("voice_enabled", "true" if self.chk_voice.isChecked() else "false")
        self.accept()


# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def _open_report(self):
        dlg = ChartDialog(self)
        dlg.exec()
    def __init__(self, worker, result_q):
        super().__init__()
        self._worker = worker
        self._result_q = result_q
        self._breaking = False
        self._alert_until = 0.0
        self.voice = VoiceEngine()
        self._force_quit = False 
        self._last_voice_time = 0.0 
        
        self.setWindowTitle("健康坐姿助手 · MediaPipe")
        self.resize(1150, 750)
        self.setStyleSheet("background-color: #1a1a1a;")

        self._build_ui()
        self._init_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # 左侧视频
        left_widget = QWidget()
        left_widget.setStyleSheet("background-color: #000000; border-radius: 16px;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        
        self.lbl_video = QLabel("正在唤醒摄像头...")
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setStyleSheet("color: #666; font-size: 22px; font-weight: bold;")
        left_layout.addWidget(self.lbl_video)
        main_layout.addWidget(left_widget, stretch=3)

        # 右侧面板
        right_widget = QWidget()
        right_widget.setFixedWidth(320)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(15)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_status = QLabel("正在初始化...")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedHeight(100)
        self.lbl_status.setStyleSheet("font-size: 32px; font-weight: bold; color: #f39c12; background-color: #2a2a2a; border-radius: 12px;")
        right_layout.addWidget(self.lbl_status)

        self.lbl_shoulder = self._create_chip("肩部: -")
        self.lbl_head = self._create_chip("头部: -")
        self.lbl_hunch = self._create_chip("驼背: -")
        self.lbl_close = self._create_chip("距离: -")
        for lbl in (self.lbl_shoulder, self.lbl_head, self.lbl_hunch, self.lbl_close):
            right_layout.addWidget(lbl)

        self.lbl_work = QLabel("已连续工作 00:00")
        self.lbl_work.setAlignment(Qt.AlignCenter)
        self.lbl_work.setStyleSheet("font-size: 18px; font-weight: bold; color: #3498db; margin: 10px 0;")
        right_layout.addWidget(self.lbl_work)

        right_layout.addStretch()

        self.btn_calib_p = self._create_btn("校准坐姿", "#2980b9")
        self.btn_calib_d = self._create_btn("校准距离", "#2980b9")
        self.btn_settings = self._create_btn("偏好设置", "#7f8c8d")
        self.btn_report = self._create_btn("查看健康报告", "#9b59b6")  # 紫色按钮，比较显眼
        self.btn_reset = self._create_btn("重置校准", "#c0392b")
        
        self.btn_calib_p.clicked.connect(lambda: self._worker.start_posture_calibration())
        self.btn_calib_d.clicked.connect(lambda: self._worker.start_distance_calibration(60.0))
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_report.clicked.connect(self._open_report)
        self.btn_reset.clicked.connect(lambda: self._worker.reset_calibration())

        for btn in (self.btn_calib_p, self.btn_calib_d, self.btn_settings, self.btn_report, self.btn_reset):
            right_layout.addWidget(btn)

        main_layout.addWidget(right_widget, stretch=1)
        self.overlay = BreakOverlay(self, self._on_resume)

    def _create_chip(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedHeight(50)
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #333333; color: #888888; border-radius: 8px;")
        return lbl

    def _create_btn(self, text, color):
        btn = QPushButton(text)
        btn.setFixedHeight(45)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{ background-color: {color}; color: white; border-radius: 8px; font-size: 16px; font-weight: bold; border: none; }}
            QPushButton:hover {{ background-color: {color}dd; }}
            QPushButton:pressed {{ background-color: {color}aa; }}
        """)
        return btn

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon = QApplication.style().standardIcon(QApplication.style().StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.tray.setToolTip("健康坐姿助手")
        
        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #2c3e50; color: white; } QMenu::item:selected { background-color: #34495e; }")
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self.showNormal)
        quit_action = menu.addAction("退出程序")
        quit_action.triggered.connect(self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            if self._worker: self._worker.reload_settings()

    def _poll(self):
        if self._result_q is None: return

        while True:
            try: msg = self._result_q.get_nowait()
            except queue.Empty: break
            t = msg.get("type")
            if t == "frame":
                self._show_frame(msg["frame"], msg["result"])
                self._apply(msg["result"])
            elif t == "fatal":
                self.lbl_status.setText("启动失败")
                self.lbl_video.setText(msg.get("message", ""))
            elif t == "stalled":
                self.lbl_status.setText("断流重连中...")
                self.lbl_status.setStyleSheet("font-size: 28px; color: #e74c3c; background-color: #2a2a2a; border-radius: 12px;")

        if self._worker is not None:
            while True:
                try: msg = self._worker.alerts.get_nowait()
                except queue.Empty: break
                t = msg.get("type")
                if t == "alert":
                    text = msg.get("text", "请注意坐姿")
                    self.lbl_status.setText("⚠ " + text)
                    self.lbl_status.setStyleSheet("font-size: 28px; color: #e74c3c; background-color: #3a1a1a; border-radius: 12px;")
                    self._alert_until = time.time() + 3.0
                    self.tray.showMessage("姿势提醒", text, QSystemTrayIcon.Warning, 3000)
                elif t == "break_required":
                    self._on_break(msg.get("seconds", 300))

        if self._worker:
            s = getattr(self._worker, "work_seconds", 0)
            self.lbl_work.setText(f"已连续工作 {s // 60:02d}:{s % 60:02d}")

    def chk_voice_enabled(self):
        return database.get_settings().get("voice_enabled", "true") == "true"

    def _show_frame(self, frame, result):
        img_bgr = frame.copy()
        pts = ((result or {}).get("points") or {}).get("pose") or {}
        for i, p in pts.items():
            cv2.circle(img_bgr, (int(p[0]), int(p[1])), 4, (0, 255, 0), -1)
        face = ((result or {}).get("points") or {}).get("face") or {}
        for i, p in face.items():
            cv2.circle(img_bgr, (int(p[0]), int(p[1])), 2, (255, 100, 100), -1)

        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.lbl_video.setPixmap(QPixmap.fromImage(img).scaled(self.lbl_video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _apply(self, r: dict):
        if self._breaking: return
        
        # ==================== 智能部位连续播报 ====================
        if r.get("overall_posture_abnormal") is True:
            now_time = time.time()
            if now_time - self._last_voice_time > 3.0:  # 每 3 秒强提醒一次
                self._last_voice_time = now_time
                if self.chk_voice_enabled():
                    issues = []
                    if r.get("shoulder_abnormal") is True: issues.append("肩膀歪了")
                    if r.get("head_abnormal") is True: issues.append("头偏了")
                    if r.get("hunchback_abnormal") is True: issues.append("驼背了")
                    if r.get("too_close") is True: issues.append("太近了")
                    
                    if issues:
                        text_to_speak = "，".join(issues) + "，请注意"
                        self.voice.speak(text_to_speak)
                    else:
                        self.voice.speak("请注意坐姿")
        # ==========================================================

        pc = r.get("posture_calibration") or {}
        state = pc.get("state")

        if time.time() < self._alert_until: pass 
        elif state == "collecting":
            pct = int(pc.get("progress", 0) * 100)
            self.lbl_status.setText(f"校准中 {pct}%\n请坐正保持不动")
            self.lbl_status.setStyleSheet("font-size: 26px; color: #3498db; background-color: #1a2a3a; border-radius: 12px;")
        elif state == "failed":
            self.lbl_status.setText("校准失败，请重试")
            self.lbl_status.setStyleSheet("font-size: 28px; color: #e74c3c; background-color: #3a1a1a; border-radius: 12px;")
        elif not r.get("pose_detected", False):
            self.lbl_status.setText("未检测到人")
            self.lbl_status.setStyleSheet("font-size: 28px; color: #7f8c8d; background-color: #2a2a2a; border-radius: 12px;")
        elif state == "ready":
            if r.get("overall_posture_abnormal") is True:
                self.lbl_status.setText("⚠ 坐姿不良")
                self.lbl_status.setStyleSheet("font-size: 32px; color: #e74c3c; background-color: #3a1a1a; border-radius: 12px;")
            elif r.get("overall_posture_abnormal") is False:
                self.lbl_status.setText("坐姿正常")
                self.lbl_status.setStyleSheet("font-size: 32px; color: #2ecc71; background-color: #1a3a2a; border-radius: 12px;")
            else:
                self.lbl_status.setText("状态未知")
                self.lbl_status.setStyleSheet("font-size: 28px; color: #f39c12; background-color: #3a2a1a; border-radius: 12px;")
        else:
            self.lbl_status.setText("尚未校准\n请先点击下方按钮")
            self.lbl_status.setStyleSheet("font-size: 24px; color: #f39c12; background-color: #2a2a2a; border-radius: 12px;")

        def update_chip(label, name, val):
            if val is True:
                label.setText(f"{name}: 异常")
                label.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #c0392b; color: white; border-radius: 8px;")
            elif val is False:
                label.setText(f"{name}: 正常")
                label.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #27ae60; color: white; border-radius: 8px;")
            else:
                label.setText(f"{name}: -")
                label.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #333333; color: #888888; border-radius: 8px;")

        update_chip(self.lbl_shoulder, "肩部", r.get("shoulder_abnormal"))
        update_chip(self.lbl_head, "头部", r.get("head_abnormal"))
        update_chip(self.lbl_hunch, "驼背", r.get("hunchback_abnormal"))
        
        dist = r.get("estimated_distance_cm")
        if isinstance(dist, (int, float)):
            is_close = r.get("too_close") is True
            update_chip(self.lbl_close, "距离", is_close)
            self.lbl_close.setText(f"距离: {dist:.0f} cm" + (" (过近)" if is_close else ""))
        else:
            update_chip(self.lbl_close, "距离", None)

    def _on_break(self, seconds):
        if self._breaking: return
        self._breaking = True
        self.overlay.showFullScreen()
        if self.chk_voice_enabled(): self.voice.speak("您已连续工作较长时间，请站起来休息一下。")

    def _on_resume(self):
        if self._worker: self._worker.resume_after_break()
        self._breaking = False
        self._alert_until = 0.0
        self.lbl_status.setText("休息结束\n继续为您监测")
        self.lbl_status.setStyleSheet("font-size: 26px; color: #2ecc71; background-color: #1a3a2a; border-radius: 12px;")

    def _quit_app(self):
        self._force_quit = True
        self._timer.stop()
        if self._worker: self._worker.stop_and_wait()
        self.voice.stop()
        QApplication.quit()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                event.ignore()
                self.hide()
                self.tray.showMessage("健康坐姿助手", "程序已最小化到托盘，正在后台为您监测。", QSystemTrayIcon.Information, 3000)
        super().changeEvent(event)

    def closeEvent(self, event):
        if self._force_quit:
            event.accept()
            return
        self._timer.stop()
        if self._worker: self._worker.stop_and_wait()
        self.voice.stop()
        QApplication.quit()