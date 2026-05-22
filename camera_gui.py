#!/usr/bin/env python3
"""GUI for the supercamera endoscope with filters."""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageFilter, ImageEnhance
import io
import time
import threading
import os
from datetime import datetime

from supercamera import Camera

NATIVE_W, NATIVE_H = 640, 480
UPSCALE_W, UPSCALE_H = 1920, 1080

# Filter presets: name -> function(img) -> img
# All operate on PIL Image at native resolution (applied to display + save)
FILTERS = {
    "None": lambda img: img,
    "Sharpen": lambda img: img.filter(ImageFilter.SHARPEN),
    "Sharp Plus": lambda img: img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=2)),
    "Detail": lambda img: img.filter(ImageFilter.DETAIL),
    "Edge Enhance": lambda img: img.filter(ImageFilter.EDGE_ENHANCE),
    "Hi Contrast": lambda img: ImageEnhance.Contrast(img).enhance(1.5),
    "B&W": lambda img: img.convert("L").convert("RGB"),
    "Warm": lambda img: _color_shift(img, warm=True),
    "Cool": lambda img: _color_shift(img, warm=False),
}

def _color_shift(img, warm=True):
    """Shift color temperature."""
    r, g, b = img.split()
    if warm:
        r = r.point(lambda x: min(255, int(x * 1.1)))
        b = b.point(lambda x: int(x * 0.9))
    else:
        r = r.point(lambda x: int(x * 0.9))
        b = b.point(lambda x: min(255, int(x * 1.1)))
    return Image.merge("RGB", (r, g, b))


class CameraGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Supercamera")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cam = None
        self.running = False
        self.recording = False
        self.record_frames = []
        self.record_start = None
        self.target_fps = 5
        self.last_jpeg = None
        self.upscale = False
        self.current_filter = "None"

        # Frame from background thread
        self._pending_img = None
        self._pending_jpeg = None
        self._frame_lock = threading.Lock()

        self.output_dir = os.path.expanduser("~/Pictures/supercamera")
        os.makedirs(self.output_dir, exist_ok=True)

        self._build_ui()
        self._connect_camera()

    def _build_ui(self):
        # Preview canvas
        self.canvas = tk.Canvas(self.root, width=NATIVE_W, height=NATIVE_H, bg="black")
        self.canvas.pack(padx=5, pady=5)

        # Status bar
        self.status_var = tk.StringVar(value="Connecting...")
        self.status = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        self.status.pack(fill="x", padx=5)

        # Row 1: main actions
        row1 = ttk.Frame(self.root)
        row1.pack(fill="x", padx=5, pady=(5, 2))

        self.btn_snap = ttk.Button(row1, text="Snapshot (S)", command=self.snapshot)
        self.btn_snap.pack(side="left", padx=2)

        self.btn_record = ttk.Button(row1, text="Record (R)", command=self.toggle_record)
        self.btn_record.pack(side="left", padx=2)

        self.btn_pause = ttk.Button(row1, text="Pause (Space)", command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=2)

        # Upscale toggle
        self.upscale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="Upscale 1080p (U)", variable=self.upscale_var,
                        command=self._upscale_changed).pack(side="left", padx=(10, 2))

        ttk.Button(row1, text="Open Folder", command=self.open_folder).pack(side="right", padx=2)

        # Row 2: filter + FPS
        row2 = ttk.Frame(self.root)
        row2.pack(fill="x", padx=5, pady=(2, 5))

        ttk.Label(row2, text="Filter:").pack(side="left", padx=(0, 2))
        self.filter_var = tk.StringVar(value="None")
        filter_combo = ttk.Combobox(row2, textvariable=self.filter_var,
                                    values=list(FILTERS.keys()), state="readonly", width=12)
        filter_combo.pack(side="left", padx=2)
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_changed())

        ttk.Label(row2, text="FPS:").pack(side="left", padx=(10, 2))
        self.fps_var = tk.IntVar(value=self.target_fps)
        ttk.Spinbox(row2, from_=1, to=30, width=3,
                    textvariable=self.fps_var, command=self._fps_changed).pack(side="left", padx=2)

        # Key bindings
        self.root.bind("s", lambda e: self.snapshot())
        self.root.bind("r", lambda e: self.toggle_record())
        self.root.bind("<space>", lambda e: self.toggle_pause())
        self.root.bind("u", lambda e: self._toggle_upscale_key())
        self.root.bind("q", lambda e: self.on_close())
        self.root.bind("f", lambda e: self._cycle_filter())

        self.paused = False
        self.last_photo = None

    def _cycle_filter(self):
        """Cycle through filters with F key."""
        names = list(FILTERS.keys())
        idx = (names.index(self.current_filter) + 1) % len(names)
        self.filter_var.set(names[idx])
        self._filter_changed()

    def _filter_changed(self):
        self.current_filter = self.filter_var.get()
        self._update_status()

    def _toggle_upscale_key(self):
        self.upscale_var.set(not self.upscale_var.get())
        self._upscale_changed()

    def _upscale_changed(self):
        self.upscale = self.upscale_var.get()
        self._update_status()

    def _update_status(self):
        if self.paused:
            self.status_var.set("Paused")
        elif self.recording:
            return
        else:
            w, h = (UPSCALE_W, UPSCALE_H) if self.upscale else (NATIVE_W, NATIVE_H)
            filt = f" [{self.current_filter}]" if self.current_filter != "None" else ""
            self.status_var.set(f"Connected - {w}x{h} @ {self.target_fps} fps{filt}")

    def _fps_changed(self):
        try:
            self.target_fps = max(1, min(30, self.fps_var.get()))
        except (tk.TclError, ValueError):
            pass
        self._update_status()

    def _connect_camera(self):
        try:
            self.cam = Camera()
            self.running = True
            self._update_status()
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            self._update_display()
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _reader_loop(self):
        """Background thread: reads frames from USB at target FPS."""
        while self.running:
            if self.paused:
                time.sleep(0.05)
                continue

            frame_start = time.monotonic()
            try:
                jpeg = self.cam.read_jpeg()
                if jpeg:
                    # Validate by fully decoding
                    img = Image.open(io.BytesIO(jpeg))
                    img.load()
                    # Mirror to match real-world view
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                    # Apply filter
                    filt_func = FILTERS.get(self.current_filter, FILTERS["None"])
                    img = filt_func(img)
                    # Build save image (upscaled if enabled)
                    if self.upscale:
                        save_img = img.resize((UPSCALE_W, UPSCALE_H), Image.LANCZOS)
                    else:
                        save_img = img
                    # Re-encode for saving
                    buf = io.BytesIO()
                    save_img.save(buf, format="JPEG", quality=92)
                    jpeg = buf.getvalue()
                    with self._frame_lock:
                        self._pending_img = img
                        self._pending_jpeg = jpeg
            except Exception:
                pass

            elapsed = time.monotonic() - frame_start
            delay = (1.0 / self.target_fps) - elapsed
            if delay > 0:
                time.sleep(delay)

    def _update_display(self):
        """Main thread: picks up frames from the reader."""
        if not self.running:
            return

        img = None
        jpeg = None
        with self._frame_lock:
            if self._pending_img is not None:
                img = self._pending_img
                jpeg = self._pending_jpeg
                self._pending_img = None
                self._pending_jpeg = None

        if img is not None:
            try:
                self.last_photo = ImageTk.PhotoImage(img)
                self.canvas.create_image(NATIVE_W // 2, NATIVE_H // 2, image=self.last_photo)
                self.last_jpeg = jpeg

                if self.recording:
                    self.record_frames.append(jpeg)
                    elapsed = time.monotonic() - self.record_start
                    self.status_var.set(
                        f"Recording... {elapsed:.1f}s  ({len(self.record_frames)} frames)"
                    )
            except Exception:
                pass

        self.root.after(16, self._update_display)

    def snapshot(self):
        if self.last_jpeg is None:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        res = "1080p" if self.upscale else "480p"
        filt = f"_{self.current_filter.replace(' ', '_')}" if self.current_filter != "None" else ""
        path = os.path.join(self.output_dir, f"snap_{ts}_{res}{filt}.jpg")
        with open(path, "wb") as f:
            f.write(self.last_jpeg)
        self.status_var.set(f"Saved: {path}")

    def toggle_record(self):
        if not self.recording:
            self.recording = True
            self.record_frames = []
            self.record_start = time.monotonic()
            self.btn_record.config(text="Stop (R)")
            self.status_var.set("Recording...")
        else:
            self.recording = False
            self.btn_record.config(text="Record (R)")
            frames = self.record_frames
            self.record_frames = []
            if frames:
                self.status_var.set(f"Saving {len(frames)} frames...")
                threading.Thread(target=self._save_video, args=(frames,), daemon=True).start()
            else:
                self.status_var.set("No frames to save")

    def _save_video(self, frames):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.root.after(0, lambda: self.status_var.set(
                "pip install opencv-python numpy for video saving"
            ))
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        arr0 = np.frombuffer(frames[0], dtype=np.uint8)
        f0 = cv2.imdecode(arr0, cv2.IMREAD_COLOR)
        h, w = f0.shape[:2]
        res = f"{w}x{h}"

        filt = f"_{self.current_filter.replace(' ', '_')}" if self.current_filter != "None" else ""
        path = os.path.join(self.output_dir, f"rec_{ts}_{res}{filt}.mp4")

        elapsed = time.monotonic() - self.record_start if self.record_start else len(frames) / 10.0
        fps = max(1, len(frames) / elapsed) if elapsed > 0 else 10

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(path, fourcc, fps, (w, h))

        for jpeg in frames:
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                out.write(frame)
        out.release()

        self.root.after(0, lambda: self.status_var.set(
            f"Saved: {path} ({len(frames)} frames, {fps:.1f} fps)"
        ))

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text="Resume (Space)" if self.paused else "Pause (Space)")
        self._update_status()

    def open_folder(self):
        os.system(f'xdg-open "{self.output_dir}" &')

    def on_close(self):
        self.running = False
        if self.cam:
            try:
                self.cam.release()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraGUI(root)
    root.mainloop()
