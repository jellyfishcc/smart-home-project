"""
智能家居系统 - 哨兵（Sentry）模式服务

职责：
  1. 维护布防状态机 disarmed / arming / armed
  2. 后台线程按固定节奏巡检：抓帧 -> 人形检测 -> 人脸核验 -> 判定
  3. 发现未授权人员时留证（连拍）+ 写事件 + WebSocket 推送 + 联动灯光
  4. 提供手动巡检与模拟入侵入口，供课程现场演示

设计约束（与项目现状强相关）：
  - 摄像头是独占资源，巡检**必须**复用 services.camera_stream 的常驻采集，
    不能再自己 cv2.VideoCapture 打开设备，否则会和门禁/检测接口抢设备。
  - 检测模型必须是含 person 类的 COCO 权重（yolov8n.pt）。
    项目默认的 models/yolo/best.pt 只有 drone / fire_extinguisher 两类，
    复用它会导致哨兵永远检测不到人。
  - 后台线程访问数据库必须带 app_context（见 sensor_simulator 的做法）。
  - 告警时间用本地时间，不用 utcnow，避免前端显示早 8 小时。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import config

logger = logging.getLogger(__name__)

# 画面平均亮度低于该值视为「无有效画面」（键盘摄像头未弹出、镜头遮挡等）
_DARK_MEAN = 12.0
# 连续多少轮拿不到有效画面后，在状态里标记摄像头异常
_NO_FRAME_WARN = 3


class SentryService:
    """哨兵模式单例服务。线程安全，状态读写在锁内完成。"""

    def __init__(self):
        self._app = None
        self._socketio = None
        self._device_manager = None
        self._face_service = None
        self._camera = None

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 状态机
        self._state = 'disarmed'          # disarmed / arming / armed
        self._mode = 'away'               # away / home
        self._interval = config.SENTRY_PATROL_INTERVAL
        self._arm_at = 0.0                # arming 结束的时间戳
        self._last_patrol: datetime | None = None
        self._last_alarm_at: dict[str, float] = {}
        self._last_alarm_time: datetime | None = None

        # 巡检统计
        self._patrol_count = 0
        self._alarm_count = 0
        self._person_hits = 0
        self._no_frame_streak = 0
        self._last_error: str | None = None
        self._camera_state = 'unknown'    # unknown / ok / dark / unavailable
        # 最近一轮巡检结论：哨兵页面据此显示 无人 / 未识别人员活动 / 已录入人脸 / 报警
        self._last_round: dict | None = None

        # 轨迹累积：连续 N 轮出现未授权人员才升级为告警。
        # 第 1 轮只记「活动」，避免「有人路过」直接触发告警。
        self._streak = 0                  # 当前轨迹连续命中轮次
        self._active_event_id = None      # 当前活跃事件，一条轨迹只对应一条记录
        self._alarm_active = False        # 是否已升级为告警（决定留证是否可清）
        self._alarm_since: datetime | None = None
        # 未告警时的留证滚动窗口：每项是一轮连拍的相对路径列表
        self._recent_rounds: deque[list[str]] = deque()
        # 告警前灯光的原始状态，解除告警时恢复
        self._light_before: dict | None = None

        # 模型惰性加载，避免拖慢应用启动
        self._model = None
        self._model_failed = False

    # ------------------------------------------------------------------ 接线

    def init_app(self, app):
        self._app = app
        app.config['SENTRY_SERVICE'] = self
        Path(config.SENTRY_SNAPSHOT_FOLDER).mkdir(parents=True, exist_ok=True)

    def set_socketio(self, socketio):
        self._socketio = socketio

    def set_device_manager(self, device_manager):
        self._device_manager = device_manager

    def set_face_service(self, face_service):
        self._face_service = face_service

    def set_camera_stream(self, camera_stream):
        self._camera = camera_stream

    # ------------------------------------------------------------------ 生命周期

    def start(self, mode='away', delay=None):
        """布防。已布防时只更新模式，不重启线程。"""
        delay = config.SENTRY_ARM_DELAY if delay is None else max(0, int(delay))
        with self._lock:
            self._mode = 'home' if mode == 'home' else 'away'
            if self._state in ('arming', 'armed'):
                return self.get_status()

            self._state = 'arming' if delay > 0 else 'armed'
            self._arm_at = time.time() + delay
            # 新一次布防从「等待首轮」开始，不沿用上一次的值守结论
            self._last_round = None

        # 清掉可能残留的唤醒标志，避免线程刚启动就多跑一轮
        self._wake.clear()
        # 线程若已在等待间隔，需要打断它才能立刻巡检；
        # 线程是新建的则本身就会先跑一轮，再 set 会导致连续巡检两次。
        already_running = self._thread is not None and self._thread.is_alive()
        self._ensure_worker()
        self._ensure_camera()
        if already_running:
            self._wake.set()

        logger.info('[Sentry] 已布防 mode=%s delay=%ss interval=%ss',
                    self._mode, delay, self._interval)
        self._emit('sentry_state', self.get_status())
        return self.get_status()

    def stop(self):
        """撤防。线程常驻空转，不销毁，避免反复建线程。"""
        with self._lock:
            self._state = 'disarmed'
            self._arm_at = 0.0
        # 撤防即结束当前轨迹：未告警的留证清掉，已告警的证据保留
        self._end_track('撤防')
        self._wake.set()
        logger.info('[Sentry] 已撤防')
        self._emit('sentry_state', self.get_status())
        return self.get_status()

    def shutdown(self):
        self._stop_event.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None

    def set_interval(self, seconds):
        seconds = int(seconds)
        if seconds < 3:
            seconds = 3
        with self._lock:
            self._interval = seconds
            armed = self._state in ('arming', 'armed')
        # 仅在值守中才需要打断等待；撤防状态下置位会遗留唤醒标志，
        # 导致下一次布防时线程刚启动就多跑一轮巡检。
        if armed:
            self._wake.set()
        return self._interval

    # ------------------------------------------------------------------ 状态

    def get_status(self):
        with self._lock:
            state = self._state
            countdown = max(0, int(round(self._arm_at - time.time()))) if state == 'arming' else 0
            return {
                'armed': state in ('arming', 'armed'),
                'state': state,
                'mode': self._mode,
                'interval': self._interval,
                'countdown': countdown,
                'last_patrol': self._last_patrol.strftime('%Y-%m-%d %H:%M:%S') if self._last_patrol else None,
                'last_alarm': self._last_alarm_time.strftime('%Y-%m-%d %H:%M:%S') if self._last_alarm_time else None,
                'patrol_count': self._patrol_count,
                'alarm_count': self._alarm_count,
                'person_hits': self._person_hits,
                # 轨迹状态：前端据此显示「第 2/3 轮」进度
                'streak': self._streak,
                'alarm_rounds': config.SENTRY_ALARM_ROUNDS,
                'alarm_active': self._alarm_active,
                'active_event_id': self._active_event_id,
                'alarm_since': self._alarm_since.strftime('%Y-%m-%d %H:%M:%S') if self._alarm_since else None,
                'window_rounds': len(self._recent_rounds),
                'window_files': sum(len(r) for r in self._recent_rounds),
                # 最近一轮结论，页面状态条直接用它（避免前端各自推断）
                'last_round': dict(self._last_round) if self._last_round else None,
                'camera_state': self._camera_state,
                'camera': self._camera.status() if self._camera is not None else None,
                'model_ready': self._model is not None,
                'error': self._last_error,
            }

    # ------------------------------------------------------------------ 巡检线程

    def _ensure_worker(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name='sentry-patrol', daemon=True)
        self._thread.start()
        logger.info('[Sentry] 巡检线程已启动')

    def _ensure_camera(self):
        if self._camera is not None and not self._camera.running:
            self._camera.start()

    def _run(self):
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                with self._lock:
                    state = self._state
                    arm_at = self._arm_at

                if state == 'arming' and time.time() >= arm_at:
                    with self._lock:
                        self._state = 'armed'
                    logger.info('[Sentry] 布防延时结束，进入值守')
                    self._emit('sentry_state', self.get_status())
                    state = 'armed'

                if state == 'armed':
                    self.patrol_once(source='schedule')

                with self._lock:
                    interval = self._interval
            except Exception as exc:  # 巡检线程绝不能因单轮异常退出
                logger.exception('[Sentry] 巡检异常')
                with self._lock:
                    self._last_error = str(exc)
                # 异常时也沿用配置的节奏，避免悄悄变成 5s 一轮（现场看会比设定值密）
                interval = config.SENTRY_PATROL_INTERVAL

            # 10 秒指「上一轮开始 -> 下一轮开始」，扣掉本轮检测耗时，
            # 这样巡检周期不会被 YOLO/人脸核验的执行时间逐步拉长。
            # 下限 0.5s：单轮耗时超过间隔时不至于变成死循环占满 CPU。
            elapsed = time.monotonic() - started
            self._wake.wait(max(0.5, interval - elapsed))
            self._wake.clear()

    # ------------------------------------------------------------------ 巡检主流程

    def patrol_once(self, source='manual', image_path=None):
        """执行一轮巡检，并把本轮结论推给哨兵页面。

        包装一层而不是在每个 return 前写推送：以后新增分支也不会漏更新状态。
        """
        try:
            result = self._patrol_once(source=source, image_path=image_path)
        except Exception as exc:
            self._publish_round({'ok': False, 'reason': f'巡检异常：{exc}'}, source)
            raise
        self._publish_round(result, source)
        return result

    def _classify_round(self, result):
        """把巡检返回值归一成页面上的四种状态（外加取帧异常）。"""
        result = result or {}
        if result.get('ok') is False:
            return 'unavailable', '画面异常', result.get('reason') or '本轮未取到有效画面'

        if result.get('alarm'):
            return 'alarm', '报警', result.get('reason') or '检测到未授权人员'

        if result.get('recognized'):
            name = result.get('person_name') or '授权人员'
            return 'authorized', '检测到已录入人脸', f'{name}，正常放行'

        if int(result.get('persons') or 0) > 0:
            total = config.SENTRY_ALARM_ROUNDS
            round_no = result.get('round') or self._streak
            detail = result.get('reason') or '存在未识别人员'
            # 未授权的 reason 自带「（第 2/3 轮观察）」，别重复拼轮次
            if round_no and '轮' not in detail:
                detail = f'第 {round_no}/{total} 轮 · {detail}'
            return 'activity', '有未识别人员活动', detail

        reason = result.get('reason') or ''
        if '画面过暗' in reason:
            return 'unavailable', '画面异常', reason
        return 'clear', '无人', reason or '画面内未检测到人员'

    def _publish_round(self, result, source='schedule'):
        """记录并推送本轮结论（WebSocket: sentry_patrol）。"""
        state, label, detail = self._classify_round(result)
        at = datetime.now().strftime('%H:%M:%S')
        with self._lock:
            payload = {
                'state': state,               # clear / activity / authorized / alarm / unavailable
                'label': label,
                'detail': detail,
                'source': source,             # schedule / manual / simulate
                'persons': int((result or {}).get('persons') or 0),
                'person_name': (result or {}).get('person_name'),
                'round': (result or {}).get('round') or self._streak,
                'streak': self._streak,
                'alarm_rounds': config.SENTRY_ALARM_ROUNDS,
                'alarm_active': self._alarm_active,
                'at': at,
            }
            self._last_round = payload
        self._emit('sentry_patrol', dict(payload))
        return payload

    def _patrol_once(self, source='manual', image_path=None):
        """执行一轮巡检。返回本轮结论，供接口直接回显。

        image_path 仅用于调试/演示：直接以指定图片作为本帧画面，
        并假定画面中存在 1 人（跳过人形检测，只验证核验与告警分支）。
        """
        injected = bool(image_path)
        if injected:
            path = Path(image_path)
            if not path.is_absolute():
                path = Path(config.BASE_DIR) / path
            if not path.exists():
                return {'ok': False, 'reason': f'图片不存在: {path}'}
            image = cv2.imread(str(path))
            if image is None:
                return {'ok': False, 'reason': f'图片读取失败: {path}'}
            frame = (image, time.time())
        else:
            frame = self._grab_frame()

        if frame is None:
            self._bump_no_frame('摄像头无可用画面')
            return {'ok': False, 'reason': '摄像头无可用画面', 'camera_state': self._camera_state}

        image, captured_at = frame
        mean = float(image.mean())
        if mean < _DARK_MEAN:
            # 画面全黑：设备在出帧但没有有效内容（镜头未弹出/遮挡），不做检测也不告警
            self._bump_no_frame('画面过暗，疑似镜头未就绪')
            with self._lock:
                self._camera_state = 'dark'
                self._last_patrol = datetime.now()
                self._patrol_count += 1
            return {'ok': True, 'persons': 0, 'reason': '画面过暗，跳过检测', 'mean': round(mean, 1)}

        with self._lock:
            self._camera_state = 'ok'
            self._no_frame_streak = 0
            self._last_patrol = datetime.now()
            self._patrol_count += 1

        if injected:
            persons = [{'class': 'person', 'confidence': 1.0, 'bbox': None, 'injected': True}]
        else:
            persons = self._detect_persons(image)
        if not persons:
            # 本轮无人：轨迹结束。未告警的留证随窗口清空，告警态则保留证据。
            ended = self._end_track('本轮无人')
            return {'ok': True, 'persons': 0, 'reason': '未检测到人员',
                    'patrol': True, 'purged': ended.get('purged', 0)}

        with self._lock:
            self._person_hits += 1

        # 每轮都留证：检测到人就拍一组，活动与告警共用同一套证据
        burst = self._capture_burst(image, use_camera=not injected)
        primary = burst[0] if burst else None
        face = self._verify_face(primary)

        if face.get('recognized'):
            return self._handle_authorized(persons, burst, face)

        return self._handle_unknown(persons, burst, face)

    # ------------------------------------------------------------------ 轨迹判定

    def _handle_authorized(self, persons, burst, face):
        """授权人员出现：直接放行。若此前只是「活动」且从未告警，

        说明那是误判（家人回来了 / 认出来的路人），把最近窗口内的留证整批删除，
        避免误报证据越积越多。已经告警过的情况保留证据，等开发者手动解除。
        """
        with self._lock:
            alarming = self._alarm_active
            rounds_before = self._streak

        purged = 0
        keep = burst
        if not alarming:
            ended = self._end_track('授权人员出现')
            purged = ended.get('purged', 0) + self._delete_snapshot_files(burst)
            keep = []            # 文件已删，事件里不再保留失效引用
            logger.info('[Sentry] 授权人员确认，清理未告警留证 %s 张（此前累积 %s 轮）',
                        purged, rounds_before)

        self._record_event(
            event_type='patrol', level='info',
            person_count=len(persons),
            person_name=face.get('person_name'),
            confidence=face.get('confidence'),
            snapshots=keep, detail='授权人员，正常放行',
        )
        return {'ok': True, 'persons': len(persons), 'recognized': True,
                'person_name': face.get('person_name'),
                'action': 'recorded', 'round': 0, 'purged': purged}

    def _handle_unknown(self, persons, burst, face):
        """未授权人员：累加轮次。第 1 轮记活动，满 N 轮才升级告警。"""
        with self._lock:
            self._streak += 1
            streak = self._streak
            alarming = self._alarm_active
            event_id = self._active_event_id

        reason = '未识别到人脸' if not face.get('faces_detected') else '人脸不属于授权人员'

        # 已告警：只追加证据，不再重复推送，避免刷屏。
        # event_id 丢失（记录被手动删除）时不能走这里，否则证据永远落不了库。
        if alarming and event_id:
            payload = self._append_evidence(event_id, burst, len(persons), reason)
            return {'ok': True, 'persons': len(persons), 'recognized': False,
                    'action': 'alarm_ongoing', 'alarm': True, 'round': streak,
                    'event': payload, 'reason': f'{reason}，告警持续中'}

        # 达到轮次阈值 -> 升级为真正的告警
        if streak >= config.SENTRY_ALARM_ROUNDS:
            payload = self._escalate(event_id, persons, burst, face, reason)
            return {'ok': True, 'persons': len(persons), 'recognized': False,
                    'action': 'alarm', 'alarm': True, 'round': streak,
                    'event': payload,
                    'reason': f'{reason}，连续 {streak} 轮未离开'}

        # 未达阈值：只记「活动」，不亮灯、不推告警
        self._push_round(burst)
        if event_id is None:
            payload = self._create_activity(persons, burst, face, reason, streak)
            with self._lock:
                self._active_event_id = (payload or {}).get('id')
        else:
            payload = self._append_evidence(event_id, burst, len(persons), reason)

        return {'ok': True, 'persons': len(persons), 'recognized': False,
                'action': 'activity', 'alarm': False, 'round': streak,
                'event': payload,
                'reason': f'{reason}（第 {streak}/{config.SENTRY_ALARM_ROUNDS} 轮观察）'}

    def _create_activity(self, persons, burst, face, reason, streak):
        return self._record_event(
            event_type='activity',
            level='info',
            person_count=len(persons),
            person_name=None,
            confidence=face.get('confidence') if face else None,
            snapshots=burst,
            detail=f'{reason}（第 {streak} 轮，观察中）',
            force=True,
            status='observing',
        )

    def _append_evidence(self, event_id, burst, person_count, reason):
        """把本轮留证并入已有事件，刷新轮次与持续时长。"""
        from models import db, SentryEvent

        with self._app.app_context():
            event = db.session.get(SentryEvent, event_id) if event_id else None
            if event is None:
                return None

            merged = []
            if event.snapshots:
                try:
                    merged = json.loads(event.snapshots)
                except (ValueError, TypeError):
                    merged = []
            merged.extend(p for p in (burst or []) if p not in merged)

            # 上限与滚动窗口一致（12 轮 × 10 张）。超出部分连同文件一起丢弃，
            # 否则窗口淘汰时会删掉仍被事件引用的图，前端出现坏图。
            cap = config.SENTRY_SNAPSHOT_WINDOW * config.SENTRY_BURST_FRAMES
            if len(merged) > cap:
                stale = merged[:-cap]
                merged = merged[-cap:]
                self._delete_snapshot_files(stale)

            event.snapshots = json.dumps(merged, ensure_ascii=False) if merged else None
            event.snapshot_path = merged[0] if merged else event.snapshot_path
            event.repeat_count = (event.repeat_count or 1) + 1
            event.person_count = person_count
            if event.created_at:
                event.duration = max(1, int((datetime.now() - event.created_at).total_seconds()))
            if event.status == 'observing':
                event.detail = (f'{reason}（第 {event.repeat_count}/'
                                f'{config.SENTRY_ALARM_ROUNDS} 轮观察）')
            db.session.commit()
            return event.to_dict()

    def _escalate(self, event_id, persons, burst, face, reason):
        """第 N 轮：把「活动」升级为「告警」，合并窗口内全部留证。"""
        from models import db, SentryEvent

        window = self._window_paths()
        merged = list(dict.fromkeys(window + list(burst or [])))
        now = datetime.now()

        with self._app.app_context():
            event = db.session.get(SentryEvent, event_id) if event_id else None
            if event is None:
                event = SentryEvent(created_at=now, repeat_count=1)
                db.session.add(event)

            event.event_type = 'intruder'
            event.level = 'critical'
            event.channel = 'CAM-01 门口'
            event.status = 'pending'
            event.person_count = len(persons)
            event.confidence = face.get('confidence') if face else None
            event.snapshots = json.dumps(merged, ensure_ascii=False) if merged else None
            event.snapshot_path = merged[0] if merged else None
            event.repeat_count = max(self._streak, event.repeat_count or 1)
            event.detail = f'{reason}，连续 {self._streak} 轮未离开'
            if event.created_at:
                event.duration = max(1, int((now - event.created_at).total_seconds()))
            db.session.commit()
            new_id = event.id
            payload = event.to_dict()

        with self._lock:
            self._active_event_id = new_id
            self._alarm_active = True
            self._alarm_since = now
            self._alarm_count += 1
            self._last_alarm_time = now
            rounds = self._streak
            # 窗口内的图已并入事件，归属告警证据；只清引用，不删文件
            self._recent_rounds.clear()

        self._emit('sentry_alarm', {
            'event': payload,
            'detail': payload.get('detail') if payload else reason,
            'level': 'critical',
            'channel': 'CAM-01 门口',
            'rounds': rounds,
        })
        self._flash_light()
        logger.warning('[Sentry] 升级为告警：%s，连续 %s 轮', reason, rounds)
        return payload

    def _end_track(self, reason='轨迹结束'):
        """结束当前轨迹：清零轮次，归档未告警的活动，清空留证。

        告警态下**不清留证**——证据要留到开发者手动解除。
        """
        with self._lock:
            event_id = self._active_event_id
            alarming = self._alarm_active
            rounds = self._streak
            self._streak = 0
            # 告警未解除前保留事件引用：否则人一走引用就丢，下一轮检测到人
            # 会另起一条新事件，同一次入侵被拆成两条记录。
            if not alarming:
                self._active_event_id = None

        if alarming:
            if event_id:
                self._update_event(event_id, detail=f'{reason}，告警记录待处理')
            return {'rounds': rounds, 'alarm': True, 'purged': 0}

        # 先清引用再删文件，避免中间态出现坏图
        if event_id:
            self._update_event(event_id, status='acknowledged',
                               snapshot_path=None, snapshots=None,
                               detail=f'{reason}，未达告警轮次（{rounds} 轮）')
        purged = self._purge_window()
        return {'rounds': rounds, 'alarm': False, 'purged': purged}
    def _update_event(self, event_id, **fields):
        from models import db, SentryEvent

        if not event_id or self._app is None:
            return None
        with self._app.app_context():
            event = db.session.get(SentryEvent, event_id)
            if event is None:
                return None
            for key, value in fields.items():
                setattr(event, key, value)
            db.session.commit()
            return event.to_dict()

    # ------------------------------------------------------------------ 留证窗口

    def _push_round(self, paths):
        """把本轮留证压入滚动窗口；超出窗口自动删除最旧一轮。"""
        if not paths:
            return
        dropped = None
        with self._lock:
            self._recent_rounds.append(list(paths))
            if len(self._recent_rounds) > config.SENTRY_SNAPSHOT_WINDOW:
                dropped = self._recent_rounds.popleft()
        if dropped:
            self._delete_snapshot_files(dropped)

    def _window_paths(self):
        with self._lock:
            return [p for round_paths in self._recent_rounds for p in round_paths]

    def _purge_window(self):
        """清空未告警窗口并删除文件，返回删除张数。"""
        with self._lock:
            rounds = list(self._recent_rounds)
            self._recent_rounds.clear()
        removed = 0
        for paths in rounds:
            removed += self._delete_snapshot_files(paths)
        return removed

    def _delete_snapshot_files(self, paths):
        removed = 0
        for rel in paths or []:
            try:
                path = Path(rel)
                if not path.is_absolute():
                    path = Path(config.UPLOAD_FOLDER) / path
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError:
                logger.debug('[Sentry] 删除留证失败: %s', rel)
        return removed

    def delete_event_files(self, event):
        """删除某条事件关联的全部快照文件，返回删除张数。"""
        if event is None:
            return 0
        paths = []
        if event.snapshot_path:
            paths.append(event.snapshot_path)
        if event.snapshots:
            try:
                paths.extend(json.loads(event.snapshots))
            except (ValueError, TypeError):
                pass
        return self._delete_snapshot_files(list(dict.fromkeys(paths)))

    # ------------------------------------------------------------------ 手动解除

    def clear_alarm(self, operator='developer', reason='手动解除'):
        """开发者手动解除告警：归档事件、清零轨迹、恢复灯光。

        与 `stop()` 的区别：撤防是关闭哨兵，这个是「这件事我已经处理完了」，
        哨兵保持布防继续值守。
        """
        with self._lock:
            event_id = self._active_event_id
            was_active = self._alarm_active
            rounds = self._streak
            self._alarm_active = False
            self._active_event_id = None
            self._streak = 0
            self._alarm_since = None
            # 告警结束后回到「等待下一轮」，避免页面继续显示报警
            self._last_round = None
            # 文件已归属告警事件，只清引用不删文件
            self._recent_rounds.clear()

        # 轮次以事件记录为准：人离开后 streak 会归零，直接读 streak 会显示成 1
        from models import db, SentryEvent
        if event_id:
            with self._app.app_context():
                event = db.session.get(SentryEvent, event_id)
                if event is not None:
                    rounds = event.repeat_count or rounds
                    event.status = 'acknowledged'
                    event.handled_at = datetime.now()
                    event.detail = f'{reason}（共 {rounds} 轮）'
                    db.session.commit()
        self._restore_light()
        self._emit('sentry_alarm_cleared', {
            'event_id': event_id, 'rounds': rounds, 'operator': operator,
        })
        logger.info('[Sentry] 告警已解除 by=%s event=%s rounds=%s', operator, event_id, rounds)
        return {'cleared': bool(was_active), 'event_id': event_id, 'rounds': rounds,
                'status': self.get_status()}

    def simulate_intrusion(self, image_path=None, note='模拟入侵', force=True):
        """演示入口：注入一次入侵，绕过 YOLO 结果与冷却。

        现场演示时真人走到镜头前受光照/角度影响，容易失败；
        该入口保证整条告警链路一定能被完整触发。
        """
        image = None
        if image_path:
            path = Path(image_path)
            if not path.is_absolute():
                path = Path(config.BASE_DIR) / path
            if path.exists():
                image = cv2.imread(str(path))
            else:
                return {'ok': False, 'reason': f'图片不存在: {path}'}
        if image is None:
            frame = self._grab_frame()
            if frame is None:
                return {'ok': False, 'reason': '摄像头无可用画面，且未提供模拟图片'}
            image = frame[0]

        persons = self._detect_persons(image) or [
            {'class': 'person', 'confidence': 0.0, 'bbox': None, 'simulated': True}
        ]
        burst = self._capture_burst(image, use_camera=not image_path)
        primary = burst[0] if burst else None
        face = self._verify_face(primary)

        event = self._raise_alarm(
            event_type='intruder',
            persons=persons,
            snapshots=burst,
            face=face,
            detail=note,
            force=force,
        )
        # 模拟入侵不走轮次累积，但页面同样要立刻显示「报警」
        self._publish_round({
            'ok': True, 'persons': len(persons), 'recognized': False,
            'alarm': True, 'reason': note,
        }, source='simulate')
        return {'ok': True, 'event': event, 'persons': len(persons), 'image_path': primary}

    # ------------------------------------------------------------------ 取帧 / 检测 / 核验

    def _grab_frame(self, timeout=3.0):
        """从常驻采集流取一帧，返回 (image, captured_at)。"""
        if self._camera is None:
            self._last_error = '摄像头采集流未接线'
            return None
        if not self._camera.running:
            self._camera.start()
            time.sleep(0.2)

        frame = self._camera.get_frame(copy=True, max_age=3.0)
        if frame is not None:
            return frame.image, frame.captured_at

        frame = self._camera.wait_for_frame(after_seq=-1, timeout=timeout, copy=True)
        if frame is None:
            return None
        return frame.image, frame.captured_at

    def _bump_no_frame(self, reason):
        with self._lock:
            self._no_frame_streak += 1
            self._last_error = reason
            if self._no_frame_streak >= _NO_FRAME_WARN:
                self._camera_state = 'unavailable'

    def _load_model(self):
        if self._model is not None or self._model_failed:
            return self._model
        try:
            from ultralytics import YOLO
            model_path = str(config.SENTRY_PERSON_MODEL)
            self._model = YOLO(model_path)
            logger.info('[Sentry] 人形检测模型已加载: %s', model_path)
        except Exception:
            self._model_failed = True
            logger.exception('[Sentry] 人形检测模型加载失败，哨兵将只做人脸核验')
        return self._model

    def _detect_persons(self, image):
        """只取 COCO 的 person 类，返回 bbox 列表。"""
        model = self._load_model()
        if model is None:
            return []
        try:
            results = model.predict(
                source=image,
                imgsz=640,
                conf=config.SENTRY_PERSON_CONF,
                classes=[0],          # COCO: 0 = person
                verbose=False,
            )
        except Exception:
            logger.exception('[Sentry] 检测失败')
            return []

        persons = []
        for result in results:
            boxes = getattr(result, 'boxes', None)
            if boxes is None:
                continue
            for box in boxes:
                conf = float(box.conf[0]) if box.conf is not None else 0.0
                xyxy = [round(float(v), 1) for v in box.xyxy[0].tolist()] if box.xyxy is not None else None
                persons.append({'class': 'person', 'confidence': round(conf, 3), 'bbox': xyxy})
        return persons

    def _verify_face(self, image_path):
        """人脸核验。没有脸时返回 faces_detected=0，不抛异常。

        image_path 是相对 uploads 的路径（sentry/xxx.jpg），
        人脸服务需要真实文件路径，必须补全为绝对路径，否则永远读不到图 -> 全员误报。
        """
        empty = {'recognized': False, 'faces_detected': 0,
                 'person_name': None, 'confidence': None, 'detail': ''}
        if not image_path or self._face_service is None:
            return empty

        path = Path(image_path)
        if not path.is_absolute():
            path = Path(config.UPLOAD_FOLDER) / path
        if not path.exists():
            logger.warning('[Sentry] 核验图片不存在: %s', path)
            return empty

        try:
            result = self._face_service.recognize(str(path))
        except Exception:
            logger.exception('[Sentry] 人脸核验失败')
            return empty
        if not result or result.get('error'):
            return empty
        return {
            'recognized': bool(result.get('recognized')),
            'faces_detected': int(result.get('faces_detected') or 0),
            'person_name': result.get('person_name'),
            'confidence': result.get('confidence'),
            'detail': result.get('detail', ''),
        }

    # ------------------------------------------------------------------ 留证

    def _capture_burst(self, first_image, use_camera=True):
        """围绕当前时刻连拍一组快照，返回相对路径列表（sentry/xxx.jpg）。

        复用常驻采集流，不重新打开设备；取不到新帧时复用首帧，
        保证告警一定有留证图。use_camera=False 时只用注入的首帧，
        避免把摄像头画面混进导入的测试图序列。
        """
        folder = Path(config.SENTRY_SNAPSHOT_FOLDER)
        folder.mkdir(parents=True, exist_ok=True)

        images = [first_image]
        if use_camera and self._camera is not None:
            seq = self._camera.latest_seq()
            for _ in range(max(0, config.SENTRY_BURST_FRAMES - 1)):
                frame = self._camera.wait_for_frame(after_seq=seq, timeout=0.5, copy=True)
                if frame is None:
                    break
                seq = frame.seq
                images.append(frame.image)
                if config.SENTRY_BURST_GAP > 0:
                    time.sleep(config.SENTRY_BURST_GAP)

        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        millis = int(time.time() * 1000) % 1000
        paths = []
        for index, image in enumerate(images):
            filename = f'{stamp}_{millis:03d}_{index}.jpg'
            target = folder / filename
            if cv2.imwrite(str(target), image):
                paths.append(f'sentry/{filename}')
        return paths

    def _burst_duration(self, count):
        if count <= 1:
            return 1
        real = (count - 1) * max(0.0, config.SENTRY_BURST_GAP)
        return max(1, int(round(real)) + 1)

    # ------------------------------------------------------------------ 事件写入与告警动作

    def _record_event(self, event_type, level, person_count=0, person_name=None,
                      confidence=None, snapshots=None, detail='', force=False,
                      status=None):
        from models import db, SentryEvent

        snapshots = snapshots or []
        now_ts = time.time()
        if not force:
            last = self._last_alarm_at.get(event_type, 0.0)
            if now_ts - last < config.SENTRY_ALARM_COOLDOWN:
                # 冷却期内：只累加次数，不新增记录，避免刷屏
                with self._lock:
                    self._last_alarm_at[event_type] = now_ts
                with self._app.app_context():
                    latest = (SentryEvent.query
                              .filter_by(event_type=event_type)
                              .order_by(SentryEvent.id.desc()).first())
                    if latest is not None:
                        latest.repeat_count = (latest.repeat_count or 1) + 1
                        db.session.commit()
                        return latest.to_dict()
                return None

        with self._lock:
            self._last_alarm_at[event_type] = now_ts

        with self._app.app_context():
            event = SentryEvent(
                event_type=event_type,
                level=level,
                channel='CAM-01 门口',
                person_count=person_count,
                person_name=person_name,
                confidence=confidence,
                snapshot_path=snapshots[0] if snapshots else None,
                snapshots=json.dumps(snapshots, ensure_ascii=False) if snapshots else None,
                detail=detail,
                # patrol 属于正常记录直接归档；activity 处于观察中；告警等待处理
                status=status or ('acknowledged' if event_type == 'patrol' else 'pending'),
                repeat_count=1,
                duration=self._burst_duration(len(snapshots)),
                created_at=datetime.now(),
                handled_at=datetime.now() if event_type == 'patrol' else None,
            )
            db.session.add(event)
            db.session.commit()
            # commit 会让实例过期，必须在会话内转成 dict 再离开上下文
            return event.to_dict()

    def _raise_alarm(self, event_type, persons, snapshots, face, detail, force=False):
        """强制告警（模拟入侵/手动触发用），跳过轮次累积。"""
        level = 'critical' if event_type == 'intruder' else 'warning'
        event = self._record_event(
            event_type=event_type,
            level=level,
            person_count=len(persons),
            person_name=face.get('person_name') if face else None,
            confidence=face.get('confidence') if face else None,
            snapshots=snapshots,
            detail=detail,
            force=force,
            status='pending',
        )

        with self._lock:
            self._alarm_active = True
            self._alarm_since = datetime.now()
            self._alarm_count += 1
            self._last_alarm_time = self._alarm_since
            if event:
                self._active_event_id = event.get('id')
            rounds = self._streak

        payload = {
            'event': event,
            'detail': detail,
            'level': level,
            'channel': 'CAM-01 门口',
            'rounds': rounds,
        }
        self._emit('sentry_alarm', payload)

        # 联动：把灯推到最亮，作为「有人闯入」的现场反应
        self._flash_light()
        logger.warning('[Sentry] 告警触发: %s (%s)', detail, event_type)
        return event

    def _flash_light(self):
        """联动灯光。必须包在 app_context 里：

        DeviceManager 本身只改内存状态，但它会回调 db_logger / lighting_logger
        写 device_status_logs 与 lighting_records，两者都要 db.session；
        而本方法运行在巡检子线程中，没有请求上下文，裸调用会抛
        RuntimeError: Working outside of application context。
        """
        if self._device_manager is None or self._app is None:
            return
        try:
            with self._app.app_context():
                # 只在第一次告警前记下原状态，解除时恢复，避免被自己覆盖成 100%
                if self._light_before is None:
                    current = self._device_manager.get_device('light') or {}
                    self._light_before = {
                        'on': bool(current.get('on')),
                        'brightness': int(current.get('brightness') or 0),
                    }
                self._device_manager.set_light_brightness(100, source='sentry')
        except Exception:
            logger.exception('[Sentry] 联动灯光失败')

    def _restore_light(self):
        """解除告警时把灯光恢复成告警前的状态。"""
        with self._lock:
            before = self._light_before
            self._light_before = None
        if not before or self._device_manager is None or self._app is None:
            return
        try:
            with self._app.app_context():
                if before.get('on'):
                    self._device_manager.set_light_brightness(
                        int(before.get('brightness') or 50), source='sentry')
                else:
                    self._device_manager.set_device('light', 'off', source='sentry')
            logger.info('[Sentry] 灯光已恢复: %s', before)
        except Exception:
            logger.exception('[Sentry] 恢复灯光失败')

    def _emit(self, event_name, payload):
        if self._socketio is None:
            return
        try:
            self._socketio.emit(event_name, payload)
        except Exception:
            logger.exception('[Sentry] WebSocket 推送失败 event=%s', event_name)


sentry_service = SentryService()
