#!/usr/bin/env python3
"""Touch-friendly GUI for Geek Szitman/useeplus USB cameras."""

import io
import json
import os
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageTk
from protocol_camera import Camera

NATIVE_W, NATIVE_H = 640, 480
SAVE_SIZES = {
    "Native": None,
    "2× upscale": (1280, 960),
    "3× upscale": (1920, 1440),
    "Full HD (letterboxed)": (1920, 1080),
}
ROTATION_OPTIONS = {
    "Portrait (90° CW)": 90,
    "Landscape (0°)": 0,
    "Upside down (180°)": 180,
    "Portrait (90° CCW)": 270,
}
DEFAULT_ROTATION = "Portrait (90° CW)"


def _color_shift(img, warm=True):
    r, g, b = img.split()
    if warm:
        r = r.point(lambda x: min(255, round(x * 1.1)))
        b = b.point(lambda x: round(x * 0.9))
    else:
        r = r.point(lambda x: round(x * 0.9))
        b = b.point(lambda x: min(255, round(x * 1.1)))
    return Image.merge("RGB", (r, g, b))


FILTERS = {
    "None": lambda img: img,
    "Detail": lambda img: img.filter(ImageFilter.DETAIL),
    "Edge": lambda img: img.filter(ImageFilter.EDGE_ENHANCE),
    "B&W": lambda img: ImageOps.grayscale(img).convert("RGB"),
    "Warm": lambda img: _color_shift(img, True),
    "Cool": lambda img: _color_shift(img, False),
}


def _letterbox_cv(frame, width, height, cv2, np):
    """Resize an OpenCV frame without cropping or changing its aspect ratio."""
    frame_h, frame_w = frame.shape[:2]
    if (frame_w, frame_h) == (width, height):
        return frame
    scale = min(width / frame_w, height / frame_h)
    resized_w = max(1, round(frame_w * scale))
    resized_h = max(1, round(frame_h * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interpolation)
    output = np.zeros((height, width, 3), dtype=frame.dtype)
    left, top = (width - resized_w) // 2, (height - resized_h) // 2
    output[top:top + resized_h, left:left + resized_w] = resized
    return output


def _orient_cv(frame, rotation, mirror_h, mirror_v, cv2):
    """Apply the same clockwise rotation and flips as the preview pipeline."""
    if rotation == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if mirror_h:
        frame = cv2.flip(frame, 1)
    if mirror_v:
        frame = cv2.flip(frame, 0)
    return frame


class CameraGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("UV Camera")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cam = None
        self.running = False
        self.paused = False
        self.recording = False
        self.record_frames = []
        self.record_start = None
        self.reader_thread = None
        self.timelapse_active = False
        self.timelapse_started = None
        self.timelapse_next = None
        self.timelapse_count = 0
        self.timelapse_dir = None
        self.last_timelapse_dir = None
        self._timelapse_video_result = None

        self.target_fps = 30
        self.brightness = 1.0
        self.contrast = 1.0
        self.saturation = 1.0
        self.sharpness = 1.0
        self.gamma = 1.0
        self.zoom = 1.0
        self.rotation = ROTATION_OPTIONS[DEFAULT_ROTATION]
        self.mirror_h = True
        self.mirror_v = False
        self.current_filter = "None"
        self.save_size_name = "Native"
        self.jpeg_quality = 100
        self.maximum_quality = True
        self.timelapse_interval = 10.0
        self.timelapse_shot_limit = 60
        self.timelapse_duration_minutes = 0.0
        self.timelapse_video_fps = 10
        self.timelapse_immediate = True
        self.timelapse_make_video = True
        self.capture_on_button = True
        self.selected_tab = "Camera"

        self.settings_path = os.path.expanduser("~/.config/uv-camera/settings.json")
        self._settings_save_job = None
        self._ui_ready = False

        self._pending_img = None
        self._pending_jpeg = None
        self._pending_raw_jpeg = None
        self._frame_lock = threading.Lock()
        self._last_photo = None
        self._last_processed = None
        self.last_jpeg = None
        self.last_raw_jpeg = None
        self._displayed_frames = 0
        self._display_fps = 0.0
        self._fps_window_start = time.monotonic()
        self._last_button_count = 0
        self._message = "Connecting..."
        self._message_until = 0.0
        self._fullscreen = root.winfo_screenwidth() <= 800
        self._load_settings()

        self.output_dir = os.path.expanduser("~/Pictures/supercamera")
        os.makedirs(self.output_dir, exist_ok=True)

        self._build_ui()
        if self._fullscreen:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("960x620")
        self._connect_camera()

    @staticmethod
    def _setting_number(settings, name, default, low, high, integer=False):
        try:
            value = int(settings[name]) if integer else float(settings[name])
        except (KeyError, TypeError, ValueError, OverflowError):
            return default
        value = max(low, min(high, value))
        return int(value) if integer else value

    def _load_settings(self):
        try:
            with open(self.settings_path, "r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
            if not isinstance(settings, dict):
                return
        except (OSError, json.JSONDecodeError):
            return

        self.target_fps = self._setting_number(
            settings, "host_fps_cap", self.target_fps, 1, 30, integer=True
        )
        limits = {
            "brightness": (0.25, 2.0), "contrast": (0.25, 2.0),
            "saturation": (0.0, 2.0), "sharpness": (0.0, 3.0),
            "gamma": (0.25, 3.0), "zoom": (1.0, 4.0),
        }
        for name, (low, high) in limits.items():
            setattr(
                self, name,
                self._setting_number(settings, name, getattr(self, name), low, high),
            )
        rotation = settings.get("rotation")
        if rotation in ROTATION_OPTIONS.values():
            self.rotation = rotation
        for name in (
            "mirror_h", "mirror_v", "maximum_quality", "timelapse_immediate",
            "timelapse_make_video", "capture_on_button", "fullscreen",
        ):
            value = settings.get(name)
            if isinstance(value, bool):
                if name == "fullscreen":
                    self._fullscreen = value
                else:
                    setattr(self, name, value)
        if settings.get("filter") in FILTERS:
            self.current_filter = settings["filter"]
        if settings.get("save_size") in SAVE_SIZES:
            self.save_size_name = settings["save_size"]
        if settings.get("selected_tab") in ("Camera", "Image", "Save", "Time"):
            self.selected_tab = settings["selected_tab"]
        self.jpeg_quality = self._setting_number(
            settings, "jpeg_quality", self.jpeg_quality, 40, 100, integer=True
        )
        self.timelapse_interval = self._setting_number(
            settings, "timelapse_interval", self.timelapse_interval, 1, 86400
        )
        self.timelapse_shot_limit = self._setting_number(
            settings, "timelapse_shot_limit", self.timelapse_shot_limit,
            0, 999999, integer=True,
        )
        self.timelapse_duration_minutes = self._setting_number(
            settings, "timelapse_duration_minutes", self.timelapse_duration_minutes,
            0, 100000,
        )
        self.timelapse_video_fps = self._setting_number(
            settings, "timelapse_video_fps", self.timelapse_video_fps,
            1, 60, integer=True,
        )

    @staticmethod
    def _variable_number(variable, fallback, low, high, integer=False):
        try:
            value = int(variable.get()) if integer else float(variable.get())
        except (tk.TclError, TypeError, ValueError, OverflowError):
            return fallback
        value = max(low, min(high, value))
        return int(value) if integer else value

    def _settings_payload(self):
        tab_name = self.selected_tab
        try:
            tab_name = self.tabs.tab(self.tabs.select(), "text")
        except tk.TclError:
            pass

        rotation_name = self.rotation_var.get()
        rotation = ROTATION_OPTIONS.get(rotation_name, self.rotation)
        filter_name = self.filter_var.get()
        if filter_name not in FILTERS:
            filter_name = self.current_filter
        save_size = self.save_size_var.get()
        if save_size not in SAVE_SIZES:
            save_size = self.save_size_name

        payload = {
            "host_fps_cap": self._variable_number(
                self.fps_var, self.target_fps, 1, 30, integer=True
            ),
            "rotation": rotation,
            "mirror_h": bool(self.mirror_h_var.get()),
            "mirror_v": bool(self.mirror_v_var.get()),
            "filter": filter_name,
            "save_size": save_size,
            "jpeg_quality": self._variable_number(
                self.quality_var, self.jpeg_quality, 40, 100, integer=True
            ),
            "maximum_quality": bool(self.maximum_quality_var.get()),
            "timelapse_interval": self._variable_number(
                self.timelapse_interval_var, self.timelapse_interval, 1, 86400
            ),
            "timelapse_shot_limit": self._variable_number(
                self.timelapse_shots_var, self.timelapse_shot_limit,
                0, 999999, integer=True,
            ),
            "timelapse_duration_minutes": self._variable_number(
                self.timelapse_duration_var, self.timelapse_duration_minutes, 0, 100000
            ),
            "timelapse_video_fps": self._variable_number(
                self.timelapse_video_fps_var, self.timelapse_video_fps,
                1, 60, integer=True,
            ),
            "timelapse_immediate": bool(self.timelapse_immediate_var.get()),
            "timelapse_make_video": bool(self.timelapse_video_var.get()),
            "capture_on_button": bool(self.button_capture_var.get()),
            "fullscreen": bool(self._fullscreen),
            "selected_tab": tab_name,
        }
        limits = {
            "brightness": (0.25, 2.0), "contrast": (0.25, 2.0),
            "saturation": (0.0, 2.0), "sharpness": (0.0, 3.0),
            "gamma": (0.25, 3.0), "zoom": (1.0, 4.0),
        }
        for name, (low, high) in limits.items():
            payload[name] = self._variable_number(
                self.value_vars[name], getattr(self, name), low, high
            )
        return payload

    def _queue_settings_save(self, *_args):
        if not self._ui_ready:
            return
        if self._settings_save_job is not None:
            try:
                self.root.after_cancel(self._settings_save_job)
            except tk.TclError:
                pass
        self._settings_save_job = self.root.after(300, self._save_settings)

    def _save_settings(self):
        self._settings_save_job = None
        settings_dir = os.path.dirname(self.settings_path)
        temporary_path = self.settings_path + ".tmp"
        try:
            os.makedirs(settings_dir, exist_ok=True)
            with open(temporary_path, "w", encoding="utf-8") as settings_file:
                json.dump(self._settings_payload(), settings_file, indent=2, sort_keys=True)
                settings_file.write("\n")
                settings_file.flush()
                os.fsync(settings_file.fileno())
            os.replace(temporary_path, self.settings_path)
        except (OSError, tk.TclError):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    def _tab_changed(self, _event=None):
        try:
            self.selected_tab = self.tabs.tab(self.tabs.select(), "text")
        except tk.TclError:
            return
        self._queue_settings_save()

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=0, minsize=218)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(3, 2))
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.btn_snap = ttk.Button(toolbar, text="Snapshot", command=self.snapshot)
        self.btn_snap.pack(side="left", padx=1)
        self.btn_record = ttk.Button(toolbar, text="Record", command=self.toggle_record)
        self.btn_record.pack(side="left", padx=1)
        self.btn_pause = ttk.Button(toolbar, text="Pause", command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=1)
        ttk.Button(toolbar, text="Folder", command=self.open_folder).pack(side="left", padx=1)
        ttk.Button(toolbar, text="Exit", command=self.on_close).pack(side="right", padx=1)
        ttk.Button(toolbar, text="Full", command=self.toggle_fullscreen).pack(side="right", padx=1)

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._render_preview())

        self.tabs = ttk.Notebook(self.root, width=214)
        self.tabs.grid(row=1, column=1, sticky="nsew", padx=(2, 3), pady=2)
        self._build_device_tab()
        self._build_image_tab()
        self._build_save_tab()
        self._build_timelapse_tab()

        self.status_var = tk.StringVar(value="Connecting...")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(4, 2)).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )

        self.root.bind("s", lambda _event: self.snapshot())
        self.root.bind("r", lambda _event: self.toggle_record())
        self.root.bind("t", lambda _event: self.toggle_timelapse())
        self.root.bind("<space>", lambda _event: self.toggle_pause())
        self.root.bind("q", lambda _event: self.on_close())
        self.root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _event: self._leave_fullscreen())

        for index in range(self.tabs.index("end")):
            if self.tabs.tab(index, "text") == self.selected_tab:
                self.tabs.select(index)
                break
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)

        saved_vars = [
            self.button_capture_var, self.fps_var, self.rotation_var,
            self.mirror_h_var, self.mirror_v_var, self.filter_var,
            self.save_size_var, self.maximum_quality_var, self.quality_var,
            self.timelapse_interval_var, self.timelapse_shots_var,
            self.timelapse_duration_var, self.timelapse_video_fps_var,
            self.timelapse_immediate_var, self.timelapse_video_var,
        ]
        saved_vars.extend(self.value_vars[name] for name in (
            "brightness", "contrast", "saturation", "sharpness", "gamma", "zoom"
        ))
        for variable in saved_vars:
            variable.trace_add("write", self._queue_settings_save)
        self._ui_ready = True
        self._queue_settings_save()

    def _build_device_tab(self):
        tab = ttk.Frame(self.tabs, padding=5)
        tab.columnconfigure(1, weight=1)
        self.tabs.add(tab, text="Camera")

        ttk.Label(tab, text="Hardware controls", font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(tab, text="Current stream:").grid(row=1, column=0, sticky="w")
        self.source_var = tk.StringVar(value="Lens 1")
        ttk.Label(tab, textvariable=self.source_var).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Button(tab, text="Switch lens / stream", command=self._switch_lens).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=2
        )

        self.button_capture_var = tk.BooleanVar(value=self.capture_on_button)
        ttk.Checkbutton(
            tab, text="Physical button saves photo", variable=self.button_capture_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(tab, text="Host FPS cap:").grid(row=4, column=0, sticky="w")
        self.fps_var = tk.IntVar(value=self.target_fps)
        fps = ttk.Spinbox(
            tab, from_=1, to=30, width=5, textvariable=self.fps_var,
            command=self._fps_changed
        )
        fps.grid(row=4, column=1, sticky="w", pady=2)
        fps.bind("<Return>", lambda _event: self._fps_changed())
        fps.bind("<FocusOut>", lambda _event: self._fps_changed())

        ttk.Button(tab, text="Reconnect camera", command=self.reconnect).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(6, 4)
        )
        ttk.Separator(tab).grid(row=6, column=0, columnspan=2, sticky="ew", pady=4)

        self.device_var = tk.StringVar(value="Detecting device...")
        ttk.Label(tab, textvariable=self.device_var, justify="left", wraplength=195).grid(
            row=7, column=0, columnspan=2, sticky="nw"
        )
        self.stats_var = tk.StringVar(value="Frames: 0")
        ttk.Label(tab, textvariable=self.stats_var, justify="left").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        ttk.Label(
            tab,
            text=("The camera sends proprietary 640×480 JPEG at up to about 30 fps. "
                  "The host cap only throttles reads. Sensor FPS, exposure, focus, gain, "
                  "white balance and LEDs are not exposed by its USB protocol."),
            justify="left", wraplength=195, foreground="#666666"
        ).grid(row=9, column=0, columnspan=2, sticky="sw", pady=(8, 0))

    def _build_image_tab(self):
        tab = ttk.Frame(self.tabs, padding=4)
        tab.columnconfigure(1, weight=1)
        self.tabs.add(tab, text="Image")
        self.value_vars = {}
        row = 0
        row = self._add_slider(tab, row, "Brightness", "brightness", 0.25, 2.0)
        row = self._add_slider(tab, row, "Contrast", "contrast", 0.25, 2.0)
        row = self._add_slider(tab, row, "Saturation", "saturation", 0.0, 2.0)
        row = self._add_slider(tab, row, "Sharpness", "sharpness", 0.0, 3.0)
        row = self._add_slider(tab, row, "Gamma", "gamma", 0.25, 3.0)
        row = self._add_slider(tab, row, "Zoom", "zoom", 1.0, 4.0)

        ttk.Label(tab, text="Rotate").grid(row=row, column=0, sticky="w", pady=2)
        rotation_name = next(
            name for name, degrees in ROTATION_OPTIONS.items() if degrees == self.rotation
        )
        self.rotation_var = tk.StringVar(value=rotation_name)
        rotation = ttk.Combobox(
            tab, textvariable=self.rotation_var,
            values=tuple(ROTATION_OPTIONS), state="readonly", width=8
        )
        rotation.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        rotation.bind("<<ComboboxSelected>>", self._rotation_changed)
        row += 1

        self.mirror_h_var = tk.BooleanVar(value=self.mirror_h)
        self.mirror_v_var = tk.BooleanVar(value=self.mirror_v)
        ttk.Checkbutton(
            tab, text="Mirror", variable=self.mirror_h_var, command=self._flip_changed
        ).grid(row=row, column=0, sticky="w")
        ttk.Checkbutton(
            tab, text="Flip", variable=self.mirror_v_var, command=self._flip_changed
        ).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        ttk.Label(tab, text="Effect").grid(row=row, column=0, sticky="w", pady=2)
        self.filter_var = tk.StringVar(value=self.current_filter)
        effects = ttk.Combobox(
            tab, textvariable=self.filter_var, values=tuple(FILTERS), state="readonly", width=9
        )
        effects.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        effects.bind("<<ComboboxSelected>>", self._filter_changed)
        row += 1

        ttk.Button(tab, text="Reset image settings", command=self.reset_image).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(5, 0)
        )

    def _add_slider(self, parent, row, label, attr, low, high):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        value = tk.DoubleVar(value=getattr(self, attr))
        self.value_vars[attr] = value
        ttk.Scale(
            parent, from_=low, to=high, variable=value,
            command=lambda raw, name=attr: self._slider_changed(name, raw)
        ).grid(row=row, column=1, sticky="ew", padx=2, pady=2)
        display = tk.StringVar(value=f"{getattr(self, attr):.2f}")
        self.value_vars[f"{attr}_display"] = display
        ttk.Label(parent, textvariable=display, width=4, anchor="e").grid(
            row=row, column=2, sticky="e"
        )
        return row + 1

    def _build_save_tab(self):
        tab = ttk.Frame(self.tabs, padding=5)
        tab.columnconfigure(0, weight=1)
        self.tabs.add(tab, text="Save")

        ttk.Label(tab, text="Saved size (orientation-aware)").grid(row=0, column=0, sticky="w")
        self.save_size_var = tk.StringVar(value=self.save_size_name)
        self.size_combo = ttk.Combobox(
            tab, textvariable=self.save_size_var, values=tuple(SAVE_SIZES), state="readonly"
        )
        self.size_combo.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.size_combo.bind("<<ComboboxSelected>>", self._save_size_changed)

        self.output_dimensions_var = tk.StringVar(value="Output: 480×640 lossless JPEG")
        ttk.Label(tab, textvariable=self.output_dimensions_var).grid(
            row=2, column=0, sticky="w", pady=(0, 3)
        )

        self.maximum_quality_var = tk.BooleanVar(value=self.maximum_quality)
        ttk.Checkbutton(
            tab, text="Maximum: preserve device JPEG", variable=self.maximum_quality_var,
            command=self._maximum_quality_changed
        ).grid(row=3, column=0, sticky="w", pady=1)

        self.quality_var = tk.IntVar(value=self.jpeg_quality)
        self.quality_label_var = tk.StringVar(value=f"JPEG quality: {self.jpeg_quality}")
        ttk.Label(tab, textvariable=self.quality_label_var).grid(row=4, column=0, sticky="w")
        self.quality_scale = ttk.Scale(
            tab, from_=40, to=100, variable=self.quality_var, command=self._quality_changed
        )
        self.quality_scale.grid(row=5, column=0, sticky="ew", pady=(0, 4))

        ttk.Button(tab, text="Save snapshot", command=self.snapshot).grid(
            row=6, column=0, sticky="ew", pady=2
        )
        ttk.Button(tab, text="Start / stop MP4 recording", command=self.toggle_record).grid(
            row=7, column=0, sticky="ew", pady=2
        )
        ttk.Button(tab, text="Open capture folder", command=self.open_folder).grid(
            row=8, column=0, sticky="ew", pady=2
        )
        ttk.Label(
            tab,
            text=("Maximum mode saves the camera's original 640×480 JPEG with "
                  "lossless portrait rotation/mirroring. Image effects, resizing and "
                  "the quality slider apply only when Maximum is off."),
            wraplength=195, justify="left", foreground="#666666"
        ).grid(row=9, column=0, sticky="sw", pady=(7, 0))
        self._maximum_quality_changed()

    def _build_timelapse_tab(self):
        tab = ttk.Frame(self.tabs, padding=5)
        tab.columnconfigure(1, weight=1)
        self.tabs.add(tab, text="Time")

        ttk.Label(tab, text="Timelapse settings", font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(tab, text="Interval (sec):").grid(row=1, column=0, sticky="w")
        self.timelapse_interval_var = tk.DoubleVar(value=self.timelapse_interval)
        ttk.Spinbox(
            tab, from_=1, to=86400, increment=1, width=8,
            textvariable=self.timelapse_interval_var
        ).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(tab, text="Shot limit:").grid(row=2, column=0, sticky="w")
        self.timelapse_shots_var = tk.IntVar(value=self.timelapse_shot_limit)
        ttk.Spinbox(
            tab, from_=0, to=999999, increment=1, width=8,
            textvariable=self.timelapse_shots_var
        ).grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(tab, text="Duration (min):").grid(row=3, column=0, sticky="w")
        self.timelapse_duration_var = tk.DoubleVar(value=self.timelapse_duration_minutes)
        ttk.Spinbox(
            tab, from_=0, to=100000, increment=1, width=8,
            textvariable=self.timelapse_duration_var
        ).grid(row=3, column=1, sticky="ew", pady=2)

        ttk.Label(tab, text="Video FPS:").grid(row=4, column=0, sticky="w")
        self.timelapse_video_fps_var = tk.IntVar(value=self.timelapse_video_fps)
        ttk.Spinbox(
            tab, from_=1, to=60, increment=1, width=8,
            textvariable=self.timelapse_video_fps_var
        ).grid(row=4, column=1, sticky="ew", pady=2)

        self.timelapse_immediate_var = tk.BooleanVar(value=self.timelapse_immediate)
        ttk.Checkbutton(
            tab, text="Capture first frame now", variable=self.timelapse_immediate_var
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=1)
        self.timelapse_video_var = tk.BooleanVar(value=self.timelapse_make_video)
        ttk.Checkbutton(
            tab, text="Build MP4 when finished", variable=self.timelapse_video_var
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=1)

        self.btn_timelapse = ttk.Button(
            tab, text="Start timelapse (T)", command=self.toggle_timelapse
        )
        self.btn_timelapse.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 3))
        self.timelapse_status_var = tk.StringVar(value="Ready — 0 means no limit")
        ttk.Label(
            tab, textvariable=self.timelapse_status_var, wraplength=195, justify="left"
        ).grid(row=8, column=0, columnspan=2, sticky="nw", pady=2)
        ttk.Button(
            tab, text="Open latest timelapse", command=self.open_timelapse_folder
        ).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(5, 2))
        ttk.Label(
            tab,
            text=("Each run gets its own folder. Frames use the current Image and Save settings. "
                  "If both limits are set, the first one reached stops the run."),
            wraplength=195, justify="left", foreground="#666666"
        ).grid(row=10, column=0, columnspan=2, sticky="sw", pady=(5, 0))

    def _slider_changed(self, attr, raw):
        value = round(float(raw), 2)
        setattr(self, attr, value)
        self.value_vars[f"{attr}_display"].set(f"{value:.2f}")

    def _rotation_changed(self, _event=None):
        self.rotation = ROTATION_OPTIONS[self.rotation_var.get()]
        self._update_output_dimensions()

    def _flip_changed(self):
        self.mirror_h = self.mirror_h_var.get()
        self.mirror_v = self.mirror_v_var.get()

    def _filter_changed(self, _event=None):
        self.current_filter = self.filter_var.get()

    def _save_size_changed(self, _event=None):
        self.save_size_name = self.save_size_var.get()
        self._update_output_dimensions()

    def _maximum_quality_changed(self):
        self.maximum_quality = self.maximum_quality_var.get()
        if self.maximum_quality:
            self.size_combo.configure(state="disabled")
            self.quality_scale.state(["disabled"])
            self.quality_label_var.set("JPEG quality: device original (fixed)")
        else:
            self.size_combo.configure(state="readonly")
            self.quality_scale.state(["!disabled"])
            self.quality_label_var.set(f"JPEG quality: {self.jpeg_quality}")
        self._update_output_dimensions()

    def _quality_changed(self, raw):
        self.jpeg_quality = max(40, min(100, round(float(raw))))
        if not self.maximum_quality:
            self.quality_label_var.set(f"JPEG quality: {self.jpeg_quality}")

    def _fps_changed(self):
        try:
            self.target_fps = max(1, min(30, int(self.fps_var.get())))
            self.fps_var.set(self.target_fps)
        except (tk.TclError, ValueError):
            self.fps_var.set(self.target_fps)

    def reset_image(self):
        defaults = {
            "brightness": 1.0, "contrast": 1.0, "saturation": 1.0,
            "sharpness": 1.0, "gamma": 1.0, "zoom": 1.0,
        }
        for attr, value in defaults.items():
            setattr(self, attr, value)
            self.value_vars[attr].set(value)
            self.value_vars[f"{attr}_display"].set(f"{value:.2f}")
        self.rotation = ROTATION_OPTIONS[DEFAULT_ROTATION]
        self.rotation_var.set(DEFAULT_ROTATION)
        self.mirror_h = True
        self.mirror_v = False
        self.mirror_h_var.set(True)
        self.mirror_v_var.set(False)
        self.current_filter = "None"
        self.filter_var.set("None")
        self._update_output_dimensions()
        self._show_message("Image settings reset")

    def _connect_camera(self):
        try:
            self.cam = Camera()
            self.running = True
            self.paused = False
            self._last_button_count = self.cam.button_press_count
            serial = self.cam.serial_number or "unknown"
            self.device_var.set(
                f"Geek Szitman supercamera\nUSB 2ce3:3828\nSerial {serial}\nNative 640x480 JPEG"
            )
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
            self._update_display()
            self._show_message("Camera connected")
        except Exception as exc:
            self.running = False
            self.cam = None
            self.device_var.set(f"Camera unavailable\n{exc}")
            self.status_var.set(f"Connection error: {exc}")

    def reconnect(self):
        self._stop_camera()
        self._clear_preview()
        self.status_var.set("Reconnecting...")
        self.root.after(350, self._connect_camera)

    def _stop_camera(self):
        self.running = False
        cam, self.cam = self.cam, None
        if cam:
            try:
                cam.release()
            except Exception:
                pass

    def _reader_loop(self):
        cam = self.cam
        while self.running and cam is self.cam:
            if self.paused:
                time.sleep(0.05)
                continue
            started = time.monotonic()
            try:
                jpeg = cam.read_jpeg()
                if jpeg:
                    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
                    img.load()
                    img = self._process_image(img)
                    save_img = self._prepare_save_image(img)
                    output = io.BytesIO()
                    save_img.save(output, format="JPEG", quality=self.jpeg_quality)
                    with self._frame_lock:
                        self._pending_img = img
                        self._pending_jpeg = output.getvalue()
                        self._pending_raw_jpeg = jpeg
            except Exception as exc:
                self._message = f"Frame error: {exc}"
                self._message_until = time.monotonic() + 2.0

            delay = (1.0 / self.target_fps) - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)

    def _process_image(self, img):
        if self.rotation == 90:
            img = img.transpose(Image.Transpose.ROTATE_270)
        elif self.rotation == 180:
            img = img.transpose(Image.Transpose.ROTATE_180)
        elif self.rotation == 270:
            img = img.transpose(Image.Transpose.ROTATE_90)
        if self.mirror_h:
            img = ImageOps.mirror(img)
        if self.mirror_v:
            img = ImageOps.flip(img)
        if self.zoom > 1.001:
            width, height = img.size
            crop_w, crop_h = max(1, round(width / self.zoom)), max(1, round(height / self.zoom))
            left, top = (width - crop_w) // 2, (height - crop_h) // 2
            img = img.crop((left, top, left + crop_w, top + crop_h)).resize(
                (width, height), Image.Resampling.LANCZOS
            )
        if self.brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(self.brightness)
        if self.contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(self.contrast)
        if self.saturation != 1.0:
            img = ImageEnhance.Color(img).enhance(self.saturation)
        if self.sharpness != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(self.sharpness)
        if self.gamma != 1.0:
            inv_gamma = 1.0 / self.gamma
            lut = [min(255, round(255 * ((value / 255) ** inv_gamma))) for value in range(256)]
            img = img.point(lut * 3)
        return FILTERS.get(self.current_filter, FILTERS["None"])(img)

    def _prepare_save_image(self, img):
        target = SAVE_SIZES.get(self.save_size_name)
        if target is None:
            return img.copy()
        if (img.width < img.height) != (target[0] < target[1]):
            target = (target[1], target[0])
        source_ratio = img.width / img.height
        target_ratio = target[0] / target[1]
        if abs(source_ratio - target_ratio) <= 0.01:
            return img.resize(target, Image.Resampling.LANCZOS)

        # Preserve the complete frame. Aspect-ratio mismatches (notably the
        # 4:3 sensor saved as 16:9 Full HD) receive black letterbox bars.
        contained = ImageOps.contain(img, target, Image.Resampling.LANCZOS)
        output = Image.new("RGB", target, "black")
        output.paste(
            contained,
            ((target[0] - contained.width) // 2, (target[1] - contained.height) // 2),
        )
        return output

    def _output_size(self):
        portrait = self.rotation in (90, 270)
        if self.maximum_quality:
            return (NATIVE_H, NATIVE_W) if portrait else (NATIVE_W, NATIVE_H)
        target = SAVE_SIZES.get(self.save_size_name)
        if target is None:
            return (NATIVE_H, NATIVE_W) if portrait else (NATIVE_W, NATIVE_H)
        if portrait and target[0] > target[1]:
            return target[1], target[0]
        if not portrait and target[0] < target[1]:
            return target[1], target[0]
        return target

    def _update_output_dimensions(self):
        width, height = self._output_size()
        orientation = "portrait" if height > width else "landscape"
        mode = "lossless device JPEG" if self.maximum_quality else orientation
        self.output_dimensions_var.set(f"Output: {width}×{height} {mode}")

    def _capture_jpeg(self):
        """Return the best available JPEG for snapshots/timelapse frames."""
        if not self.maximum_quality or self.last_raw_jpeg is None:
            return self.last_jpeg
        data = self.last_raw_jpeg
        transforms = []
        if self.rotation:
            transforms.append(("-rotate", str(self.rotation)))
        if self.mirror_h:
            transforms.append(("-flip", "horizontal"))
        if self.mirror_v:
            transforms.append(("-flip", "vertical"))
        for operation, value in transforms:
            result = subprocess.run(
                ["jpegtran", "-copy", "all", "-perfect", operation, value],
                input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            data = result.stdout
        return data

    def _update_display(self):
        if not self.running:
            return
        img = jpeg = raw_jpeg = None
        with self._frame_lock:
            if self._pending_img is not None:
                img = self._pending_img
                jpeg = self._pending_jpeg
                raw_jpeg = self._pending_raw_jpeg
                self._pending_img = None
                self._pending_jpeg = None
                self._pending_raw_jpeg = None
        if img is not None:
            self._last_processed = img
            self.last_jpeg = jpeg
            self.last_raw_jpeg = raw_jpeg
            self._render_preview()
            self._displayed_frames += 1
            if self.recording:
                self.record_frames.append(
                    raw_jpeg if self.record_native_source and raw_jpeg is not None else jpeg
                )

        now = time.monotonic()
        self._update_timelapse(now)
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._display_fps = self._displayed_frames / elapsed
            self._displayed_frames = 0
            self._fps_window_start = now

        cam = self.cam
        if cam:
            if cam.button_press_count > self._last_button_count:
                self._last_button_count = cam.button_press_count
                if self.button_capture_var.get():
                    self.snapshot(source="button")
            lens = cam.active_camera
            if lens in (0, 1):
                self.source_var.set(f"Lens {lens + 1}")
            self.stats_var.set(
                f"Frames: {cam.frames_read}\nDisplay: {self._display_fps:.1f} fps\n"
                f"Button events: {cam.button_press_count}"
            )
        self._refresh_status()
        self.root.after(16, self._update_display)

    def _render_preview(self):
        if self._last_processed is None:
            return
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        preview = ImageOps.contain(self._last_processed, (width, height), Image.Resampling.LANCZOS)
        self._last_photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(width // 2, height // 2, image=self._last_photo)

    def _clear_preview(self):
        self._last_processed = None
        self.last_jpeg = None
        self.last_raw_jpeg = None
        self.canvas.delete("all")

    def _switch_lens(self):
        cam = self.cam
        if not cam:
            return

        def switch():
            try:
                cam.switch_camera(1)
                self._message = "Lens switch requested"
            except Exception as exc:
                self._message = f"Lens switch failed: {exc}"
            self._message_until = time.monotonic() + 3.0

        threading.Thread(target=switch, daemon=True).start()

    def snapshot(self, source="screen"):
        if self.last_jpeg is None:
            self._show_message("No frame available")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        width, height = self._output_size()
        size = f"{width}x{height}"
        suffix = "_button" if source == "button" else ""
        path = os.path.join(self.output_dir, f"snap_{stamp}_{size}{suffix}.jpg")
        try:
            jpeg = self._capture_jpeg()
            with open(path, "wb") as output:
                output.write(jpeg)
        except Exception as exc:
            self._show_message(f"Snapshot failed: {exc}", 5.0)
            return
        self._show_message(f"Saved {os.path.basename(path)}", 4.0)

    def toggle_timelapse(self):
        if self.timelapse_active:
            self._finish_timelapse("Stopped by user")
            return
        if self.last_jpeg is None:
            self._show_message("No frame available")
            return
        try:
            interval = float(self.timelapse_interval_var.get())
            shots = int(self.timelapse_shots_var.get())
            duration = float(self.timelapse_duration_var.get())
            video_fps = int(self.timelapse_video_fps_var.get())
        except (tk.TclError, ValueError):
            self._show_message("Check timelapse settings")
            return
        if interval < 1 or shots < 0 or duration < 0 or not 1 <= video_fps <= 60:
            self._show_message("Interval ≥1; limits ≥0; video FPS 1–60")
            return

        self.timelapse_interval = interval
        self.timelapse_shot_limit = shots
        self.timelapse_duration_minutes = duration
        self.timelapse_video_fps = video_fps
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        self.timelapse_dir = os.path.join(self.output_dir, f"timelapse_{stamp}")
        os.makedirs(self.timelapse_dir, exist_ok=True)
        self.last_timelapse_dir = self.timelapse_dir
        self.timelapse_count = 0
        self.timelapse_started = time.monotonic()
        self.timelapse_next = (
            self.timelapse_started if self.timelapse_immediate_var.get()
            else self.timelapse_started + interval
        )
        self.timelapse_active = True
        self.btn_timelapse.config(text="Stop timelapse (T)")
        self.timelapse_status_var.set(f"Running • next in {max(0, interval):.1f}s")
        self._show_message("Timelapse started")

    def _update_timelapse(self, now):
        if self._timelapse_video_result is not None:
            result, self._timelapse_video_result = self._timelapse_video_result, None
            self.timelapse_status_var.set(result)
            self._show_message(result, 5.0)
        if not self.timelapse_active:
            return
        if self.paused:
            self.timelapse_status_var.set(
                f"Paused with preview • {self.timelapse_count} photos saved"
            )
            return

        elapsed = now - self.timelapse_started
        duration_seconds = self.timelapse_duration_minutes * 60.0
        if duration_seconds > 0 and elapsed >= duration_seconds:
            self._finish_timelapse("Duration reached")
            return

        if now >= self.timelapse_next and self.last_jpeg is not None:
            self.timelapse_count += 1
            filename = f"frame_{self.timelapse_count:06d}.jpg"
            path = os.path.join(self.timelapse_dir, filename)
            try:
                jpeg = self._capture_jpeg()
                with open(path, "wb") as output:
                    output.write(jpeg)
            except Exception as exc:
                self._finish_timelapse(f"Save failed: {exc}", build_video=False)
                return
            self.timelapse_next = max(
                self.timelapse_next + self.timelapse_interval,
                now + 0.05,
            )
            if self.timelapse_shot_limit and self.timelapse_count >= self.timelapse_shot_limit:
                self._finish_timelapse("Shot limit reached")
                return

        next_in = max(0.0, self.timelapse_next - now)
        limit = str(self.timelapse_shot_limit) if self.timelapse_shot_limit else "∞"
        self.timelapse_status_var.set(
            f"Running • {self.timelapse_count}/{limit} photos • next in {next_in:.1f}s"
        )

    def _finish_timelapse(self, reason, build_video=None):
        if not self.timelapse_active:
            return
        self.timelapse_active = False
        self.btn_timelapse.config(text="Start timelapse (T)")
        count = self.timelapse_count
        folder = self.timelapse_dir
        should_build = self.timelapse_video_var.get() if build_video is None else build_video
        if should_build and count > 0:
            self.timelapse_status_var.set(f"{reason} • building MP4 from {count} photos...")
            threading.Thread(
                target=self._build_timelapse_video,
                args=(folder, self.timelapse_video_fps),
                daemon=True,
            ).start()
            self._show_message(f"{reason}; building timelapse MP4", 5.0)
        else:
            text = f"{reason} • {count} photos saved"
            self.timelapse_status_var.set(text)
            self._show_message(text, 5.0)

    def _build_timelapse_video(self, folder, fps):
        try:
            import cv2
            import numpy as np
            frames = sorted(
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if name.startswith("frame_") and name.endswith(".jpg")
            )
            if not frames:
                raise RuntimeError("No timelapse frames found")
            first = cv2.imread(frames[0])
            if first is None:
                raise RuntimeError("Could not decode first timelapse frame")
            height, width = first.shape[:2]
            output_path = os.path.join(folder, "timelapse.mp4")
            writer = cv2.VideoWriter(
                output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
            )
            if not writer.isOpened():
                raise RuntimeError("Could not create MP4")
            for path in frames:
                frame = cv2.imread(path)
                if frame is None:
                    continue
                writer.write(_letterbox_cv(frame, width, height, cv2, np))
            writer.release()
            self._timelapse_video_result = f"Timelapse saved • {len(frames)} photos + MP4"
        except Exception as exc:
            self._timelapse_video_result = f"Photos saved; MP4 failed: {exc}"

    def open_timelapse_folder(self):
        subprocess.Popen(["xdg-open", self.last_timelapse_dir or self.output_dir])

    def toggle_record(self):
        if not self.recording:
            if self.last_jpeg is None:
                self._show_message("No frame available")
                return
            self.recording = True
            self.record_frames = []
            self.record_start = time.monotonic()
            self.record_native_source = self.maximum_quality
            self.record_transform = (self.rotation, self.mirror_h, self.mirror_v)
            self.btn_record.config(text="Stop")
        else:
            self.recording = False
            self.btn_record.config(text="Record")
            frames, self.record_frames = self.record_frames, []
            if frames:
                elapsed = max(0.1, time.monotonic() - self.record_start)
                self._show_message(f"Saving {len(frames)} video frames...", 30.0)
                threading.Thread(
                    target=self._save_video,
                    args=(frames, elapsed, self.record_native_source, self.record_transform),
                    daemon=True,
                ).start()

    def _save_video(self, frames, elapsed, native_source, transform):
        try:
            import cv2
            import numpy as np
            first = cv2.imdecode(np.frombuffer(frames[0], dtype=np.uint8), cv2.IMREAD_COLOR)
            if native_source:
                first = _orient_cv(first, *transform, cv2)
            height, width = first.shape[:2]
            fps = max(1.0, len(frames) / elapsed)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.output_dir, f"rec_{stamp}_{width}x{height}.mp4")
            writer = cv2.VideoWriter(
                path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
            )
            for jpeg in frames:
                frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    if native_source:
                        frame = _orient_cv(frame, *transform, cv2)
                    writer.write(_letterbox_cv(frame, width, height, cv2, np))
            writer.release()
            self._message = f"Saved {os.path.basename(path)}"
        except Exception as exc:
            self._message = f"Video save failed: {exc}"
        self._message_until = time.monotonic() + 5.0

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text="Resume" if self.paused else "Pause")
        self._show_message("Preview paused" if self.paused else "Preview resumed")

    def _show_message(self, message, seconds=2.0):
        self._message = message
        self._message_until = time.monotonic() + seconds
        self.status_var.set(message)

    def _refresh_status(self):
        if time.monotonic() < self._message_until:
            self.status_var.set(self._message)
        elif self.timelapse_active:
            next_in = max(0.0, self.timelapse_next - time.monotonic())
            self.status_var.set(
                f"Timelapse • {self.timelapse_count} photos • next in {next_in:.1f}s"
            )
        elif self.recording:
            elapsed = time.monotonic() - self.record_start
            self.status_var.set(f"Recording {elapsed:.1f}s • {len(self.record_frames)} frames")
        elif self.paused:
            self.status_var.set("Paused")
        elif self.cam:
            lens = self.cam.active_camera
            lens_text = f"Lens {lens + 1}" if lens in (0, 1) else "Lens ?"
            self.status_var.set(f"Connected • {lens_text} • {self._display_fps:.1f} fps")

    def open_folder(self):
        subprocess.Popen(["xdg-open", self.output_dir])

    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)
        self._queue_settings_save()

    def _leave_fullscreen(self):
        if self._fullscreen:
            self._fullscreen = False
            self.root.attributes("-fullscreen", False)
            self._queue_settings_save()

    def on_close(self):
        # Already captured timelapse frames are complete JPEGs and remain safe.
        self.timelapse_active = False
        self._save_settings()
        self._stop_camera()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    CameraGUI(root)
    root.mainloop()
