"""Module 2: Webcam Presence Detection.

Uses OpenCV with either Haar cascades (default, lightweight) or MediaPipe
(optional, more robust) to detect a face in the webcam feed at a fixed
interval. If the student is absent for longer than ``absence_threshold``,
an alert is fired once (cooldown applies) and presence/absence events are
logged to the encrypted store.

Runs as a daemon thread.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import cv2

from alert import AlertSender
from config import CONFIG
from storage import EncryptedStore


class WebcamMonitor:
    def __init__(
        self,
        store: EncryptedStore,
        alert_sender: AlertSender,
        cfg: Dict[str, Any],
    ) -> None:
        self.store = store
        self.alert = alert_sender
        self.cfg = cfg.get("webcam", {})
        self.alert_cfg = cfg.get("alerts", {})

        self.enabled = bool(self.cfg.get("enabled", True))
        self.camera_index = int(self.cfg.get("camera_index", 0))
        self.check_interval = float(self.cfg.get("check_interval", 5))
        self.absence_threshold = float(self.cfg.get("absence_threshold_seconds", 180))
        self.detector_kind = str(self.cfg.get("face_detector", "haar")).lower()

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._cap: Optional[Any] = None
        self._detector: Any = None

        # Presence state.
        self._present = False
        self._absence_start: Optional[float] = None
        self._alerted_absence = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self.running = True
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap or not self._cap.isOpened():
            print("[WEBCAM] Could not open camera; presence detection disabled.")
            self.running = False
            self._cap = None
            return
        self._detector = self._build_detector()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[WEBCAM] Presence detection started.")

    def stop(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        self.running = False
        # Log a final absence if we were tracking one.
        if self._absence_start is not None:
            self.store.record_presence(time.time(), False, time.time() - self._absence_start)
            self._absence_start = None
        if self.thread is not None:
            self.thread.join(timeout=timeout)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        print("[WEBCAM] Presence detection stopped.")

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while self.running:
            try:
                present = self._check_frame()
            except Exception as exc:
                print(f"[WEBCAM ERROR] {exc}")
                present = False

            now = time.time()
            changed = present != self._present

            if changed:
                if present:
                    # Student returned: close any open absence event.
                    if self._absence_start is not None:
                        absence = now - self._absence_start
                        self.store.record_presence(now, False, absence)
                        self._absence_start = None
                        self._alerted_absence = False
                        print("[WEBCAM] Student present at desk.")
                else:
                    # Student left: start absence timer.
                    self._absence_start = now
                    print("[WEBCAM] Student absent from desk.")
                self._present = present
                self.store.record_presence(now, present)

            # Continuous absence beyond threshold -> alert.
            if (
                not self._present
                and self._absence_start is not None
                and not self._alerted_absence
                and now - self._absence_start >= self.absence_threshold
            ):
                absence = now - self._absence_start
                self.alert.send(
                    f"Student absent from desk for {absence:.0f}s "
                    f"({self.absence_threshold:.0f}s threshold).",
                    kind="absence",
                )
                self._alerted_absence = True

            time.sleep(self.check_interval)

    # ------------------------------------------------------------------ #
    # Detection
    # ------------------------------------------------------------------ #
    def _build_detector(self) -> Any:
        if self.detector_kind == "mediapipe":
            try:
                import mediapipe as mp  # type: ignore

                return mp.solutions.face_detection.FaceDetection(
                    model_selection=0, min_detection_confidence=0.5
                )
            except Exception as exc:
                print(f"[WEBCAM] MediaPipe unavailable ({exc}); falling back to Haar.")
                self.detector_kind = "haar"
        if self.detector_kind == "haar":
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            if cascade.empty():
                raise RuntimeError("Haar cascade XML not found")
            return cascade
        raise ValueError(f"Unknown face_detector: {self.detector_kind}")

    def _check_frame(self) -> bool:
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return False
        if self.detector_kind == "mediapipe":
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._detector.process(rgb)  # type: ignore[attr-defined]
            return bool(getattr(results, "detections", None))
        # Haar cascade on grayscale.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
        return len(faces) > 0
