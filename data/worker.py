
import os
import sys
import queue
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data import database

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from vision import PostureDetector, VisionConfig
except Exception as _exc:
    PostureDetector = None
    VisionConfig = None
    print(f"[worker] 未能导入 vision 包：{_exc}")

#参数

CAMERA_INDEX = 0
FPS_LIMIT = 10
QUEUE_MAX = 2
READ_FAIL_LIMIT = 3# 连续读帧失败几次才算断流

HOLD_SEC = 5.0# 累计不良多少秒触发报警
DECAY_RATE = 0.6# 明确判为正常时的扣分速度
UNKNOWN_GIVEUP = 3.0 # 超过这么多秒判断不了，才开始扣分
ALERT_COOLDOWN_SEC = 60.0  # 同一问题再次提醒的间隔
MAX_FRAME_GAP_SEC = 1.0  # 单帧间隔超过这个值，不把时间计入

SITTING_LIMIT_SEC =45*60 # 久坐45分钟
BREAK_SEC = 5*60 # 休息5分钟

DEBUG = False # 排查完改成 False

ALERT_TEXT = {
    database.KIND_SHOULDER: "肩膀歪了，请坐正",
    database.KIND_HEAD: "头偏了，请回正",
    database.KIND_HUNCHBACK: "疑似驼背，请挺直腰背",
    database.KIND_TOO_CLOSE: "离屏幕太近，请后退",
}

FLAG_MAP = (
    ("shoulder_abnormal", database.KIND_SHOULDER),
    ("head_abnormal", database.KIND_HEAD),
    ("hunchback_abnormal", database.KIND_HUNCHBACK),
    ("too_close", database.KIND_TOO_CLOSE),
)


def _build_config():
    s = database.get_settings()

    def f(key, default):
        try:
            return float(s.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    return VisionConfig(
        shoulder_threshold_deg=f("shoulder_threshold_deg", 4.0),
        head_threshold_ratio=f("head_threshold_ratio", 0.15),
        hunchback_threshold_ratio=f("hunchback_threshold_ratio", 0.40),
        min_distance_cm=f("distance_threshold_cm", 50),
        landmark_confidence=f("landmark_confidence", 0.6),
    )


class MonitorWorker(threading.Thread):
    def __init__(self, frame_queue, camera_index=CAMERA_INDEX):
        super().__init__(daemon=True, name="MonitorWorker")
        self.q = frame_queue# 画面帧
        self.alerts = queue.Queue() # 报警，不丢弃
        self.camera_index = camera_index

        self._cmds = queue.Queue()
        self._stop_evt = threading.Event()

        self._cap = None
        self._detector = None
        self._session_id = None

        self._work_seconds = 0.0
        self._last_tick = None
        self._last_db_save = 0.0
        self._break_required = False
        self._read_fail = 0
        self._cooldown = ALERT_COOLDOWN_SEC
        self._stalled_reported = False
        try:
            self._cooldown = float(database.get_settings().get("alert_cooldown_sec", 60))
        except (TypeError, ValueError):
            self._cooldown = ALERT_COOLDOWN_SEC

        # 每个类别一份积分状态
        self._st = {kind: {"score": 0.0, "last": None, "last_true": None,
                           "alerted": False, "alerted_at": 0.0,
                           "event_id": None, "episode_start": None}
                    for _, kind in FLAG_MAP}

        # 调试统计
        self._cnt = {kind: {"T": 0, "F": 0, "N": 0} for _, kind in FLAG_MAP}
        self._dbg_frames = 0
        self._dbg_t0 = time.time()

    #对外

    @property
    def work_seconds(self):
        return int(self._work_seconds)

    def start_posture_calibration(self):
        self._cmds.put("posture")

    def start_distance_calibration(self, known_cm=60.0):
        self._cmds.put(("distance", known_cm))

    def reset_calibration(self):
        self._cmds.put("reset")

    def reload_settings(self):
        """设置面板保存后调用，把新阈值推给正在运行的检测器。"""
        self._cmds.put("reload_settings")

    def resume_after_break(self):
        self._break_required = False
        self._work_seconds = 0.0
        self._last_tick = time.time()

    def stop(self):
        self._stop_evt.set()

    def stop_and_wait(self, timeout=5.0):
        self.stop()
        if self.is_alive():
            self.join(timeout)

    #主循环

    def run(self):
        self._session_id = database.start_session()
        self._last_tick = time.time()

        try:
            self._open_camera()
            self._open_detector()
        except Exception as exc:
            self.alerts.put({"type": "fatal", "message": str(exc)})
            print("[worker] 初始化失败:", exc)
            self._cleanup()
            return

        interval = 1.0 / max(1, FPS_LIMIT)
        try:
            while not self._stop_evt.is_set():
                t0 = time.time()
                self._drain_commands()

                ok, frame = self._cap.read() if self._cap is not None else (False, None)

                if not ok or frame is None:
                    self._read_fail += 1
                    if self._read_fail >= READ_FAIL_LIMIT:
                        if not self._stalled_reported:
                            self.alerts.put({"type": "stalled"})
                            self._stalled_reported = True
                        self._end_all("read_fail")
                    self._stop_evt.wait(0.1)
                    continue

                self._read_fail = 0
                if self._stalled_reported:
                    print("[worker] 画面已恢复")
                    self._stalled_reported = False

                now = time.time()
                try:
                    result = self._detector.detect(frame)
                except Exception as exc:
                    print("[worker] 检测异常:", exc)
                    self._stop_evt.wait(0.2)
                    continue

                self._update_work_time(now)
                self._judge(result, now)
                self._publish(frame, result, now)
                if DEBUG:
                    self._debug(result, now)

                cost = time.time() - t0
                if cost < interval:
                    self._stop_evt.wait(interval - cost)
        finally:
            self._cleanup()

    #初始化

    def _open_camera(self):
        if cv2 is None:
            raise RuntimeError("未安装 opencv-contrib-python")
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"打不开摄像头 {self.camera_index}（可能被其他程序占用）")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap = cap
        print("[worker] 摄像头已打开")

    def _open_detector(self):
        if PostureDetector is None:
            raise RuntimeError("vision 包未导入，请把 vision/ 和 models/ 放到项目根目录")
        self._detector = PostureDetector(config=_build_config())
        print("[worker] 检测器已就绪")

    #命令

    def _drain_commands(self):
        while True:
            try:
                cmd = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                if cmd == "posture":
                    self._end_all("recalibrate")
                    self._detector.start_posture_calibration()
                    print("[worker] 开始坐姿校准")
                elif isinstance(cmd, tuple) and cmd[0] == "distance":
                    self._end_all("recalibrate")
                    self._detector.start_distance_calibration(cmd[1])
                    print(f"[worker] 开始距离校准，参考 {cmd[1]} cm")
                elif cmd == "reset":
                    self._end_all("reset")
                    self._detector.reset_calibration()
                    print("[worker] 已重置校准")
                elif cmd == "reload_settings":
                    cfg = _build_config()
                    self._detector.update_settings(
                        shoulder_threshold_deg=cfg.shoulder_threshold_deg,
                        head_threshold_ratio=cfg.head_threshold_ratio,
                        hunchback_threshold_ratio=cfg.hunchback_threshold_ratio,
                        min_distance_cm=cfg.min_distance_cm,
                        landmark_confidence=cfg.landmark_confidence,
                    )
                    try:
                        self._cooldown = float(
                            database.get_settings().get("alert_cooldown_sec", 60))
                    except (TypeError, ValueError):
                        pass
                    print(f"[worker] 设置已重载，冷却 {self._cooldown:.0f}s")
            except Exception as exc:
                print("[worker] 命令失败:", exc)

    #计时

    def _update_work_time(self, now):
        if self._break_required:
            self._last_tick = now
            return

        delta = 0.0 if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        if delta > MAX_FRAME_GAP_SEC:      # 卡顿，这段不计入
            delta = 0.0
        self._work_seconds += max(delta, 0.0)

        if now - self._last_db_save >= 60:
            database.update_work_seconds(self._session_id, int(self._work_seconds))
            self._last_db_save = now

        if self._work_seconds >= SITTING_LIMIT_SEC:
            self._break_required = True
            self._work_seconds = 0.0
            database.log_event(database.KIND_SITTING_LONG,
                               SITTING_LIMIT_SEC, self._session_id)
            self.alerts.put({"type": "break_required", "seconds": BREAK_SEC})

    #判定

    def _judge(self, result, now):
        for field, kind in FLAG_MAP:
            flag = result.get(field)
            st = self._st[kind]

            dt = 0.0 if st["last"] is None else now - st["last"]
            st["last"] = now
            if dt < 0 or dt > MAX_FRAME_GAP_SEC:
                dt = 0.0

            if DEBUG:
                self._cnt[kind]["T" if flag is True else
                                ("F" if flag is False else "N")] += 1

            if flag is True:
                st["score"] += dt
                st["last_true"] = now
            elif flag is False:
                st["score"] = max(0.0, st["score"] - dt * DECAY_RATE)
            else:
                # None：判断不了，不奖不罚；长时间判断不了才慢慢衰减
                if st["last_true"] and now - st["last_true"] > UNKNOWN_GIVEUP:
                    st["score"] = max(0.0, st["score"] - dt * DECAY_RATE)

            if st["score"] >= HOLD_SEC and not st["alerted"]:
                st["alerted"] = True
                st["alerted_at"] = now
                st["episode_start"] = now - st["score"]
                st["event_id"] = database.log_event(
                    kind, int(st["score"]), self._session_id,
                    detail=f"hold={HOLD_SEC:.0f}s")
                self.alerts.put({"type": "alert", "kind": kind,
                                 "text": ALERT_TEXT.get(kind, "请注意坐姿"),
                                 "duration": int(st["score"])})
                print(f"[judge] {kind} 触发报警 score={st['score']:.1f}")


            elif (st["alerted"]
                  and now - st["alerted_at"] >= self._cooldown
                  and st["score"] >= HOLD_SEC):
                st["alerted_at"] = now
                self.alerts.put({"type": "alert", "kind": kind,
                                 "text": ALERT_TEXT.get(kind, "请注意坐姿"),
                                 "duration": int(st["score"])})
            if st["score"] <= 0.0 and st["alerted"]:
                dur = int(now - st["episode_start"]) if st["episode_start"] else 0
                if st["event_id"] is not None and dur > 0:
                    database.update_event_duration(st["event_id"], dur)
                print(f"[judge] {kind} 结束，时长 {dur}s")
                st["alerted"] = False
                st["alerted_at"] = 0.0
                st["event_id"] = None
                st["episode_start"] = None

    def _end_all(self, reason):
        """结束所有正在进行的段（断流、重新校准、重置时调用）。"""
        now = time.time()
        for kind, st in self._st.items():
            if st["alerted"] and st["episode_start"]:
                dur = int(now - st["episode_start"])
                if st["event_id"] is not None and dur > 0:
                    database.update_event_duration(st["event_id"], dur)
            st["score"] = 0.0
            st["last"] = None
            st["last_true"] = None
            st["alerted"] = False
            st["alerted_at"] = 0.0
            st["event_id"] = None
            st["episode_start"] = None
        print(f"[worker] 所有计时已清零（{reason}）")

    # 调试

    def _debug(self, result, now):
        self._dbg_frames += 1
        if self._dbg_frames < 30:
            return
        self._dbg_frames = 0
        h = self._cnt[database.KIND_HEAD]
        print(f"[dbg] fps≈{30 / max(now - self._dbg_t0, 1e-6):.1f}  "
              f"头 score={self._st[database.KIND_HEAD]['score']:.1f}  "
              f"T/F/N={h['T']}/{h['F']}/{h['N']}  "
              f"可判定={result.get('posture_evaluable')}")
        self._cnt = {kind: {"T": 0, "F": 0, "N": 0} for _, kind in FLAG_MAP}
        self._dbg_t0 = now

    # 消息

    def _publish(self, frame, result, now):
        try:
            self.q.put_nowait({"type": "frame", "frame": frame,
                               "result": result, "ts": now})
            return
        except queue.Full:
            pass
        try:
            self.q.get_nowait()
        except queue.Empty:
            pass
        try:
            self.q.put_nowait({"type": "frame", "frame": frame,
                               "result": result, "ts": now})
        except queue.Full:
            pass

    #收尾

    def _cleanup(self):
        self._end_all("shutdown")
        try:
            if self._session_id is not None:
                database.update_work_seconds(self._session_id, int(self._work_seconds))
                database.end_session(self._session_id)
        except Exception as exc:
            print("[worker] 收尾写库失败:", exc)

        try:
            if self._detector is not None:
                self._detector.close()
        except Exception as exc:
            print("[worker] 关闭检测器失败:", exc)

        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass

        print("[worker] 已退出")


def start_monitor(camera_index=CAMERA_INDEX):
    database.init_db()
    q = queue.Queue(maxsize=QUEUE_MAX)
    w = MonitorWorker(q, camera_index=camera_index)
    w.start()
    return w, q