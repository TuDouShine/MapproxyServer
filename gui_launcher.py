import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import tkinter.font as tkfont
import sys
import os
import subprocess
import threading
import queue
import shutil
import webbrowser
import logging
import json # Used for error handling/logging if needed, though ConfigManager handles file IO
import re
import time
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime
try:
    import main
except ImportError:
    main = None # Should not happen in bundle, but safe for dev
try:
    import process_manager
except ImportError:
    process_manager = None
from python_detector import find_python_interpreters
from modules.ui.gui_seed_manager import show_seed_manager_dialog
from modules.ui.gui_advancedsetting_manager import show_advanced_settings_dialog
from utils import cleanup_empty_legacy_launcher_dir_in_cwd, get_base_dir, get_work_dir, is_port_in_use
from config_manager import ConfigManager

# 工作目录名称 (referenced from utils implicitly by get_work_dir, but we might need it for display or logic)
LAUNCHER_DIR_NAME = "MapProxyLauncher"

class SeedProgressCanvasView:
    def __init__(
        self,
        parent: tk.Widget,
        *,
        colors: dict[str, str],
        get_fonts: Callable[[], dict[str, tuple]],
        on_package: Callable[[str], None],
        show_toast: Callable[[str], None],
    ) -> None:
        """用于“切片进度”页的高性能虚拟滚动卡片网格视图。"""
        self._parent = parent
        self._colors = colors
        self._get_fonts = get_fonts
        self._on_package = on_package
        self._show_toast = show_toast

        self._tasks: list[str] = []
        self._progress: dict[str, tuple[float, int, int]] = {}
        self._status: dict[str, str] = {}
        self._packaging: set[str] = set()

        self._card_gap = 16
        self._card_pad = 12
        self._card_height = 112

        self._rendered_indices: set[int] = set()
        self._button_hitboxes: dict[str, tuple[int, int, int, int]] = {}
        self._render_cache: dict[int, tuple] = {}

        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")

        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self._canvas.bind("<Enter>", lambda _e: self._canvas.focus_set(), add="+")

    def set_state(
        self,
        *,
        tasks: list[str],
        progress: dict[str, tuple[float, int, int]],
        packaging: set[str],
        status: dict[str, str] | None = None,
    ) -> None:
        """更新任务列表与进度数据，并触发重绘。"""
        tasks_new = list(tasks)
        if tasks_new != self._tasks:
            try:
                self._canvas.delete("seed_progress_item")
            except Exception:
                pass
            self._rendered_indices.clear()
            self._render_cache.clear()
            self._button_hitboxes.clear()
        self._tasks = tasks_new
        self._progress = dict(progress)
        self._status = dict(status) if isinstance(status, dict) else {}
        self._packaging = set(packaging)
        self._update_scroll_region()
        self._render_visible()

    def _get_columns(self, width: int) -> int:
        """根据可用宽度计算列数（>=1200 三列，>=800 两列，否则一列）。"""
        if width >= 1200:
            return 3
        if width >= 800:
            return 2
        return 1

    def _update_scroll_region(self) -> None:
        """根据任务数量与列数计算 scrollregion，保证滚动条正确。"""
        try:
            width = int(self._canvas.winfo_width() or 0)
            height = int(self._canvas.winfo_height() or 0)
        except Exception:
            width = 0
            height = 0

        if width <= 0 or height <= 0:
            self._canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        cols = self._get_columns(width)
        n = len(self._tasks)
        rows = (n + cols - 1) // cols if n > 0 else 0
        total_height = self._card_gap + rows * (self._card_height + self._card_gap)
        total_width = max(0, width)
        self._canvas.configure(scrollregion=(0, 0, total_width, max(total_height, height)))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """处理尺寸变化，更新列数布局与可视渲染。"""
        try:
            _ = int(event.width)
        except Exception:
            return
        self._update_scroll_region()
        self._render_visible()

    def _on_mousewheel(self, event: tk.Event) -> None:
        """Windows 下的鼠标滚轮滚动处理。"""
        try:
            delta = int(getattr(event, "delta", 0))
        except Exception:
            delta = 0
        if delta == 0:
            return
        step = -1 if delta > 0 else 1
        self._canvas.yview_scroll(step * 3, "units")
        self._render_visible()

    def _on_click(self, event: tk.Event) -> None:
        """处理打包按钮点击（命中测试在 Canvas 坐标系中完成）。"""
        try:
            x = int(self._canvas.canvasx(event.x))
            y = int(self._canvas.canvasy(event.y))
        except Exception:
            return

        for task_name, (x1, y1, x2, y2) in self._button_hitboxes.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                percent, _, _ = self._progress.get(task_name, (0, 0, 0))
                try:
                    percent_f = float(percent)
                except Exception:
                    percent_f = 0.0
                if percent_f < 100.0:
                    return
                if task_name in self._packaging:
                    self._show_toast("正在打包，请稍候…")
                    return
                self._on_package(task_name)
                return

    def _render_visible(self) -> None:
        """仅渲染当前可视区域的卡片，避免 1000+ 任务时卡顿。"""
        try:
            width = int(self._canvas.winfo_width() or 0)
            height = int(self._canvas.winfo_height() or 0)
        except Exception:
            return
        if width <= 0 or height <= 0:
            return

        cols = self._get_columns(width)
        n = len(self._tasks)
        if n == 0:
            self._canvas.delete("seed_progress_item")
            self._rendered_indices.clear()
            self._button_hitboxes.clear()
            self._render_cache.clear()
            return

        row_h = self._card_height + self._card_gap
        top_y = int(self._canvas.canvasy(0))
        bottom_y = top_y + height
        first_row = max(0, (top_y - self._card_gap) // row_h - 1)
        last_row = max(0, (bottom_y - self._card_gap) // row_h + 1)

        max_row = (n + cols - 1) // cols - 1
        if last_row > max_row:
            last_row = max_row

        start_idx = first_row * cols
        end_idx = min(n, (last_row + 1) * cols)
        wanted = set(range(start_idx, end_idx))

        for idx in list(self._rendered_indices):
            if idx not in wanted:
                self._canvas.delete(f"seedcard_{idx}")
                self._rendered_indices.remove(idx)
                self._render_cache.pop(idx, None)

        prev_hitboxes = dict(self._button_hitboxes)
        self._button_hitboxes.clear()

        for idx in range(start_idx, end_idx):
            task_name = self._tasks[idx]
            percent, processed, total = self._progress.get(task_name, (0, 0, 0))
            try:
                percent_f = float(percent)
            except Exception:
                percent_f = 0.0
            if percent_f < 0.0:
                percent_f = 0.0
            if percent_f > 100.0:
                percent_f = 100.0
            is_packaging = task_name in self._packaging
            status_code = str(self._status.get(task_name, "") or "")
            sig = (task_name, round(percent_f, 2), int(processed), int(total), status_code, bool(is_packaging), int(cols), int(width))

            if idx in self._rendered_indices and self._render_cache.get(idx) == sig:
                if task_name in prev_hitboxes:
                    self._button_hitboxes[task_name] = prev_hitboxes[task_name]
                continue

            self._canvas.delete(f"seedcard_{idx}")
            self._draw_card(idx, width, cols)
            self._rendered_indices.add(idx)
            self._render_cache[idx] = sig

    def _draw_card(self, idx: int, canvas_width: int, cols: int) -> None:
        """绘制单个 seed 任务卡片（含进度条、百分比、计数与打包按钮）。"""
        gap = self._card_gap
        pad = self._card_pad
        card_h = self._card_height

        usable = max(1, canvas_width - gap * (cols + 1))
        card_w = max(260, usable // cols)
        grid_total_w = gap * (cols + 1) + card_w * cols
        if grid_total_w > canvas_width:
            card_w = max(220, (canvas_width - gap * (cols + 1)) // cols)

        row = idx // cols
        col = idx % cols
        x0 = gap + col * (card_w + gap)
        y0 = gap + row * (card_h + gap)
        x1 = x0 + card_w
        y1 = y0 + card_h

        task_name = self._tasks[idx]
        percent_raw, processed, total = self._progress.get(task_name, (0, 0, 0))
        try:
            percent = float(percent_raw)
        except Exception:
            percent = 0.0
        if percent < 0.0:
            percent = 0.0
        if percent > 100.0:
            percent = 100.0
        status_code = str(self._status.get(task_name, "") or "").lower()
        is_done = percent >= 100.0 or status_code in {"completed", "finished"}
        is_packaging = task_name in self._packaging

        fonts = self._get_fonts() or {}
        body_font_raw = fonts.get("body", ("Microsoft YaHei", -14, "normal"))
        subtitle_font_raw = fonts.get("subtitle", ("Microsoft YaHei", -14, "bold"))
        mono_font_raw = fonts.get("mono", ("Consolas", -16, "normal"))

        def _with_px_size(font_tuple: tuple, px: int) -> tuple:
            """将字体元组的字号固定为指定像素值（保持字体族与字重不变）。"""
            try:
                family = str(font_tuple[0])
            except Exception:
                family = "Microsoft YaHei"
            try:
                weight = str(font_tuple[2])
            except Exception:
                weight = "normal"
            return (family, -abs(int(px)), weight)

        body_font = _with_px_size(body_font_raw, 16)
        subtitle_font = _with_px_size(subtitle_font_raw, 16)
        mono_font = _with_px_size(mono_font_raw, 16)
        percent_font = _with_px_size(subtitle_font_raw, 17)

        border = self._colors.get("border", "#D6DAE1")
        text = self._colors.get("text", "#111111")
        muted = self._colors.get("muted", "#5B616E")
        blue = self._colors.get("seed", "#1D4ED8")
        green = self._colors.get("success", "#0B6B2E")
        red = self._colors.get("error", "#B00020")
        orange = self._colors.get("warn", "#8A4B00")

        self._canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            fill="white",
            outline=border,
            width=1,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        name_y = y0 + pad
        name_x = x0 + pad
        name_max_w = max(80, card_w - pad * 2)
        name_text = self._ellipsize(task_name, body_font, name_max_w)
        self._canvas.create_text(
            name_x,
            name_y,
            anchor="nw",
            text=name_text,
            fill=text,
            font=body_font,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        bar_h = 10
        bar_y = name_y + 28
        percent_str = f"{percent:.2f}%"
        percent_w = tkfont.Font(font=percent_font).measure(percent_str)

        bar_x0 = x0 + pad
        bar_x1 = x1 - pad - percent_w - 10
        if bar_x1 < bar_x0 + 40:
            bar_x1 = bar_x0 + 40
        bar_y0 = bar_y
        bar_y1 = bar_y + bar_h

        self._canvas.create_rectangle(
            bar_x0,
            bar_y0,
            bar_x1,
            bar_y1,
            fill=self._colors.get("hover_bg", "#F5F7FA"),
            outline=border,
            width=1,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        fill_w = int((bar_x1 - bar_x0) * (percent / 100.0))
        fill_color = green if is_done else blue
        if fill_w > 0:
            self._canvas.create_rectangle(
                bar_x0,
                bar_y0,
                bar_x0 + fill_w,
                bar_y1,
                fill=fill_color,
                outline="",
                width=0,
                tags=(f"seedcard_{idx}", "seed_progress_item"),
            )

        self._canvas.create_text(
            x1 - pad,
            bar_y0 - 3,
            anchor="ne",
            text=percent_str,
            fill=text,
            font=percent_font,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        btn_w = 84
        btn_h = 28
        btn_x2 = x1 - pad
        btn_x1 = btn_x2 - btn_w
        btn_y2 = y1 - pad
        btn_y1 = btn_y2 - btn_h

        btn_enabled = is_done and not is_packaging
        btn_fill = blue if btn_enabled else self._colors.get("hover_bg", "#F5F7FA")
        btn_text = "打包中" if is_packaging else "打包"
        btn_fg = "white" if btn_enabled else muted

        self._canvas.create_rectangle(
            btn_x1,
            btn_y1,
            btn_x2,
            btn_y2,
            fill=btn_fill,
            outline=border,
            width=1,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )
        self._canvas.create_text(
            (btn_x1 + btn_x2) // 2,
            (btn_y1 + btn_y2) // 2,
            anchor="center",
            text=btn_text,
            fill=btn_fg,
            font=subtitle_font,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        row_y = btn_y1 + (btn_h // 2)
        count_x_right = btn_x1 - 10

        status_text = self._status_text_for_task(status_code, percent)
        status_color = self._status_color_for_text(status_text, green=green, blue=blue, red=red, orange=orange, muted=muted)
        status_str = f"状态: {status_text}"

        status_max_w = max(40, count_x_right - (x0 + pad) - 12)
        status_render = self._ellipsize(status_str, mono_font, status_max_w)
        try:
            status_w = tkfont.Font(font=mono_font).measure(status_render)
        except Exception:
            status_w = 0
        min_count_x = x0 + pad + int(status_w) + 12

        self._canvas.create_text(
            x0 + pad,
            row_y,
            anchor="w",
            text=status_render,
            fill=status_color,
            font=mono_font,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        count_str = f"已生成 {processed}/{total}"
        count_max_w = max(20, int(count_x_right) - int(min_count_x))
        count_render = self._ellipsize(count_str, mono_font, count_max_w)
        self._canvas.create_text(
            count_x_right,
            row_y,
            anchor="e",
            text=count_render,
            fill=muted,
            font=mono_font,
            tags=(f"seedcard_{idx}", "seed_progress_item"),
        )

        self._button_hitboxes[task_name] = (int(btn_x1), int(btn_y1), int(btn_x2), int(btn_y2))

    def _status_text_for_task(self, status_code: str, percent: float) -> str:
        try:
            pct = float(percent)
        except Exception:
            pct = 0.0
        code = str(status_code or "").lower()
        if code in {"failed", "error"}:
            return "失败"
        if code in {"retrying", "paused"}:
            return "暂停"
        if pct >= 100.0 or code in {"completed", "finished"}:
            return "已完成"
        if code in {"running", "starting"}:
            return "进行中"
        if pct <= 0.0:
            return "待处理"
        return "进行中"

    def _status_color_for_text(
        self,
        status_text: str,
        *,
        green: str,
        blue: str,
        red: str,
        orange: str,
        muted: str,
    ) -> str:
        txt = str(status_text or "")
        if txt == "已完成":
            return green
        if txt == "进行中":
            return blue
        if txt == "失败":
            return red
        if txt == "暂停":
            return orange
        return muted

    def _ellipsize(self, text: str, font: tuple, max_width: int) -> str:
        """将超长文本省略号截断，确保单行展示。"""
        try:
            f = tkfont.Font(font=font)
        except Exception:
            return text
        if f.measure(text) <= max_width:
            return text
        ell = "…"
        lo = 0
        hi = len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            candidate = text[:mid] + ell
            if f.measure(candidate) <= max_width:
                lo = mid + 1
            else:
                hi = mid
        cut = max(0, lo - 1)
        return text[:cut] + ell

def deploy_resources():
    """将内嵌资源部署到工作目录"""
    work_dir = get_work_dir()
    os.makedirs(work_dir, exist_ok=True)
    
    # 资源源目录
    if getattr(sys, 'frozen', False):
        source_dir = sys._MEIPASS
    else:
        source_dir = os.path.dirname(os.path.abspath(__file__))
    
    files_to_copy = [
        "mapproxy_config",
        "requirements.txt",
    ]
    
    for filename in files_to_copy:
        src = os.path.join(source_dir, filename)
        dst = os.path.join(work_dir, filename)
        
        if os.path.exists(src):
            if os.path.isdir(src):
                if not os.path.exists(dst):
                    try:
                        shutil.copytree(src, dst)
                        logging.info(f"Deploying directory: {filename}")
                    except Exception:
                        logging.exception(f"Failed to deploy directory: {filename}")
                continue

            if filename.endswith(".yaml") or filename.endswith(".json") or filename == "requirements.txt":
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        logging.info(f"Deploying config: {filename}")
                    except Exception:
                        logging.exception(f"Failed to deploy {filename}")
            else:
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    logging.exception(f"Failed to deploy {filename}")

# AdvancedSettingsDialog class has been moved to modules/ui/gui_advancedsetting_manager.py



class LauncherApp:
    def __init__(self, root):
        logging.basicConfig(level=logging.INFO)
        self.root = root
        self.root.title("MapProxy Server Launcher")
        self._capture_layout_mode = "--capture-layout" in sys.argv
        
        # 1. 窗口尺寸调整与限制
        try:
            screen_w = int(self.root.winfo_screenwidth() or 0)
            screen_h = int(self.root.winfo_screenheight() or 0)
        except Exception:
            screen_w = 0
            screen_h = 0

        target_w = 1256
        target_h = 740
        if screen_w > 0:
            target_w = min(target_w, max(980, int(screen_w * 0.92)))
            target_w = min(target_w, max(980, screen_w - 80))
        if screen_h > 0:
            target_h = min(target_h, max(640, int(screen_h * 0.92)))
            target_h = min(target_h, max(640, screen_h - 80))

        self.root.geometry(f"{target_w}x{target_h}")
        self.root.minsize(960, 600)
        
        # 变量
        self.python_path_var = tk.StringVar()
        self.port_var = tk.StringVar(value="8080")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.waitress_threads_var = tk.StringVar(value="16")
        self.allow_external_var = tk.BooleanVar(value=False)
        self.service_process = None
        self.log_queue = queue.Queue()
        self.server_log_path = os.path.join(get_work_dir(), "logs", "server.log")
        self.server_log_pos = 0
        self.current_host = "127.0.0.1"
        self.logger = logging.getLogger("Launcher")
        
        # Log Enhancement Variables
        self.log_auto_scroll = tk.BooleanVar(value=True)
        self.log_level_var = tk.StringVar(value="INFO") # DEBUG, INFO, WARN, ERROR
        self.system_log_buffer = [] # Store (level, message) tuples
        self.seed_log_buffer = [] # Store (level, message) tuples
        self.max_log_buffer = 5000
        self.show_seed_in_system_var = tk.BooleanVar(value=False)

        # Seed Progress Tab State
        self._seed_status_path = os.path.join(get_work_dir(), "mapproxy_config", "seed_status.json")
        self._seed_seed_yaml_path = os.path.join(get_work_dir(), "mapproxy_config", "mapproxy-seed.yaml")
        self._seed_task_names: list[str] = []
        self._seed_task_progress: dict[str, tuple[float, int, int]] = {}
        self._seed_task_status: dict[str, str] = {}
        self._seed_packaging: set[str] = set()
        self._seed_progress_refresh_pending = False
        self._seed_progress_yaml_mtime: Optional[float] = None
        
        # Config Manager
        self.config_mgr = ConfigManager(get_work_dir(), get_base_dir())
        
        # 新增状态变量
        self.status_var = tk.StringVar(value="就绪")
        self.service_url_var = tk.StringVar(value="")
        self.status_color = "gray" # 默认颜色
        
        # 部署资源
        deploy_resources()
        try:
            self.config_mgr.ensure_map_config_exists(source="gui_launcher.init")
        except Exception:
            pass

        self._ui_colors = {
            "text": "#111111",
            "muted": "#5B616E",
            "border": "#D6DAE1",
            "hover_bg": "#F5F7FA",
            "error": "#B00020",
            "warn": "#8A4B00",
            "success": "#0B6B2E",
            "seed": "#1D4ED8",
            "toast_bg": "#222222",
            "toast_fg": "#FFFFFF",
        }
        self._ui_fonts = {}
        self._log_text_default_height = 4
        self._log_text_min_height = 3
        self._log_min_visible_lines = 0
        self._log_font_px_normal = 16
        self._log_font_px_key = 18
        self._log_font_px_alert = 14
        self._log_font_min_px = -16
        self._log_font_size_px: Optional[int] = None
        self._log_notebook_height_ratio = 1.2
        self._log_notebook_base_height_px: Optional[int] = None
        self._did_initial_autosize = False

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        self._configure_visual_styles(initial_width=max(1, int(self.root.winfo_width() or 1280)))
        
        self.create_widgets()
        self._reload_seed_tasks_from_yaml()
        self._schedule_seed_progress_refresh()
        if not self._capture_layout_mode:
            self.load_config()
            self.scan_pythons()
            self.load_layers()
        
        # 绑定快捷键
        if not self._capture_layout_mode:
            self.root.bind('<Control-l>', lambda e: self.get_current_log_widget().see("end"))
            self.root.bind('<Control-L>', lambda e: self.get_current_log_widget().see("end"))
        
        # 启动日志更新定时器
        if not self._capture_layout_mode:
            self.root.after(100, self.update_logs)
            self.root.after(500, self._poll_seed_progress_sources)
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _configure_visual_styles(self, initial_width: int) -> None:
        """配置全局视觉样式（字体、间距、颜色映射），不改变现有业务逻辑。"""
        style = ttk.Style()

        try:
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", "white"), ("!disabled", "white")],
                background=[("readonly", "white"), ("!disabled", "white")],
                selectbackground=[("readonly", "white"), ("!disabled", "white")],
                selectforeground=[("readonly", "black"), ("!disabled", "black")],
            )
        except Exception:
            pass

        style.configure("Card.TLabelframe", relief="groove", borderwidth=2)
        self.adapt_ui_size(initial_width)

    def create_widgets(self):
        # Root layout configuration
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create Scrollable Canvas Container
        self.canvas = tk.Canvas(self.root, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, padding="16")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid_remove()
        
        # Ensure inner frame width matches canvas width
        self.canvas.bind('<Configure>', self.on_canvas_configure)
        
        # Main content frame (use this for all widgets)
        main_frame = self.scrollable_frame
        main_frame.columnconfigure(0, weight=1)
        # Configure row weights to allow log frame to expand
        main_frame.rowconfigure(0, weight=0) # Env
        main_frame.rowconfigure(1, weight=0) # Config
        main_frame.rowconfigure(2, weight=0) # Status
        main_frame.rowconfigure(3, weight=1) # Log & Monitor (Expandable)

        # 1. Python 环境 (Row 0) - Exclusive Row
        frame_env = ttk.LabelFrame(main_frame, text="运行环境", padding="16", style="Card.TLabelframe")
        frame_env.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        if getattr(sys, "frozen", False):
            ttk.Label(frame_env, text="内置解释器（固定）:").pack(side=tk.LEFT)
            self.entry_python_info = ttk.Entry(
                frame_env,
                textvariable=self.python_path_var,
                state="readonly",
                font=("Consolas", -16),
            )
            self.entry_python_info.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
            self.btn_copy_python = ttk.Button(
                frame_env,
                text="复制路径",
                command=lambda: self.copy_to_clipboard(sys.executable),
            )
            self.btn_copy_python.pack(side=tk.LEFT)
            self.combo_python = None
            self.btn_refresh = None
        else:
            ttk.Label(frame_env, text="Python 解释器:").pack(side=tk.LEFT)
            self.combo_python = ttk.Combobox(frame_env, textvariable=self.python_path_var, state="readonly")
            self.combo_python.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
            self.btn_refresh = ttk.Button(frame_env, text="刷新", command=self.scan_pythons)
            self.btn_refresh.pack(side=tk.LEFT)
        
        # 2. 服务配置 & 核心控制 (Row 1) - Merged & Refactored
        frame_config = ttk.LabelFrame(main_frame, text="服务配置与控制", padding="16", style="Card.TLabelframe")
        frame_config.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        frame_config.columnconfigure(1, weight=1) # Allow expansion
        
        # Line 1: Basic Config (Port, Host, Save, Advanced)
        config_line = ttk.Frame(frame_config)
        config_line.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 2))
        
        ttk.Label(config_line, text="端口:").pack(side=tk.LEFT, padx=(0, 8))
        self.entry_port = ttk.Entry(config_line, textvariable=self.port_var, width=8)
        self.entry_port.pack(side=tk.LEFT, padx=(0, 12))
        self.entry_port.bind('<KeyRelease>', self.validate_port_input)

        ttk.Label(config_line, text="线程:").pack(side=tk.LEFT, padx=(0, 8))
        self.entry_threads = ttk.Entry(config_line, textvariable=self.waitress_threads_var, width=8)
        self.entry_threads.pack(side=tk.LEFT, padx=(0, 12))
        self.entry_threads.bind('<KeyRelease>', self.validate_threads_input)
        
        self.chk_external = ttk.Checkbutton(config_line, text="允许外部访问", variable=self.allow_external_var, command=self.update_host_from_access)
        self.chk_external.pack(side=tk.LEFT, padx=(0, 12))
        
        self.lbl_host = ttk.Label(config_line, textvariable=self.host_var, foreground=self._ui_colors["muted"])
        self.lbl_host.pack(side=tk.LEFT, padx=(0, 12))
        
        self.btn_advanced = ttk.Button(config_line, text="高级设置", command=self.open_advanced_settings)
        self.btn_advanced.pack(side=tk.RIGHT, padx=(8, 0))
        
        self.btn_save = ttk.Button(config_line, text="保存配置", command=self.save_config)
        self.btn_save.pack(side=tk.RIGHT, padx=(8, 0))
        
        self.btn_seed = ttk.Button(config_line, text="切片预生成", command=lambda: show_seed_manager_dialog(self.root))
        self.btn_seed.pack(side=tk.RIGHT, padx=(8, 0))

        # Line 2: Start/Stop Buttons (Compact Group)
        control_line = ttk.Frame(frame_config, padding=(0, 16))
        control_line.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 0))
        
        # Start/Stop buttons
        self.btn_start = ttk.Button(control_line, text="启动服务", command=self.start_service)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        
        self.btn_stop = ttk.Button(control_line, text="停止服务", command=self.stop_service, state="disabled")
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # Line 3: Work Directory
        dir_line = ttk.Frame(frame_config)
        dir_line.grid(row=2, column=0, columnspan=3, sticky="ew")
        
        ttk.Label(dir_line, text="工作目录:").pack(side=tk.LEFT)
        
        self.work_dir_var = tk.StringVar(value=get_work_dir())
        entry_work_dir = ttk.Entry(dir_line, textvariable=self.work_dir_var, state="readonly", font=("Consolas", -16))
        entry_work_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        
        self.btn_dir = ttk.Button(dir_line, text="打开目录", command=self.open_work_dir)
        self.btn_dir.pack(side=tk.RIGHT)

        # 3. 运行状态模块 (Row 2) - Simplified
        frame_status_card = ttk.LabelFrame(main_frame, text="运行状态", padding="16", style="Card.TLabelframe")
        frame_status_card.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        
        # Status Header (Indicator + URL + Browser)
        status_header = ttk.Frame(frame_status_card)
        status_header.pack(fill=tk.X)
        
        # Indicator
        self.canvas_status = tk.Canvas(status_header, width=20, height=20, highlightthickness=0)
        self.canvas_status.pack(side=tk.LEFT, padx=(0, 5))
        self.status_circle = self.canvas_status.create_oval(2, 2, 18, 18, fill="gray", outline="gray")
        
        self.lbl_status = ttk.Label(status_header, textvariable=self.status_var, font=("Microsoft YaHei", -16, "bold"), foreground=self._ui_colors["muted"])
        self.lbl_status.pack(side=tk.LEFT, padx=(0, 8))
        
        # URL
        url_container = ttk.Frame(status_header)
        url_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Label(url_container, text="服务地址:").pack(side=tk.LEFT)
        entry_url = ttk.Entry(url_container, textvariable=self.service_url_var, state="readonly", font=("Consolas", -16))
        entry_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(url_container, text="复制", command=self.copy_url).pack(side=tk.LEFT)
        
        # Browser Button (Quick Access)
        self.btn_browser = ttk.Button(status_header, text="在浏览器打开", command=self.open_browser)
        self.btn_browser.pack(side=tk.RIGHT, padx=(8, 0))

        # 3.5 切片预生成监控 (Row 3) - REPLACED BY DIALOG
        # frame_seed removed.

        # 3. 运行日志&监控 (Row 3)
        frame_log = ttk.LabelFrame(main_frame, text="运行日志&监控", padding="16", style="Card.TLabelframe")
        # sticky="nsew" ensures it fills the expanded row
        frame_log.grid(row=3, column=0, sticky="nsew") 
        
        # Log Toolbar
        log_toolbar = ttk.Frame(frame_log)
        log_toolbar.pack(fill=tk.X, pady=(0, 2))
        
        ttk.Label(log_toolbar, text="日志级别:").pack(side=tk.LEFT)
        combo_level = ttk.Combobox(log_toolbar, textvariable=self.log_level_var, values=["DEBUG", "INFO", "WARN", "ERROR"], state="readonly", width=8)
        combo_level.pack(side=tk.LEFT, padx=(8, 12))
        combo_level.bind("<<ComboboxSelected>>", self.refresh_log_view)
        
        ttk.Checkbutton(log_toolbar, text="自动滚动", variable=self.log_auto_scroll).pack(side=tk.LEFT, padx=(0, 12))
        
        # Preference: Show seed logs in system tab
        ttk.Checkbutton(log_toolbar, text="在主日志显示Seed信息", variable=self.show_seed_in_system_var).pack(side=tk.LEFT, padx=(0, 12))
        
        ttk.Button(log_toolbar, text="导出日志", command=self.export_logs).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(log_toolbar, text="清空日志", command=self.clear_logs).pack(side=tk.RIGHT, padx=(8, 0))
        
        # Notebook for Tabs
        self.notebook_log = ttk.Notebook(frame_log)
        self.notebook_log.pack(fill=tk.BOTH, expand=True)
        
        # Tab 1: System Log
        self.tab_system = ttk.Frame(self.notebook_log)
        self.notebook_log.add(self.tab_system, text="系统日志")

        log_font = self._ui_fonts.get("log_mono", ("Consolas", -16, "normal"))
        try:
            font_family = str(log_font[0])
            font_size = int(log_font[1])
            font_weight = str(log_font[2])
        except Exception:
            font_family = "Consolas"
            font_size = -16
            font_weight = "normal"

        font_size = -abs(int(font_size))
        if abs(font_size) < 16:
            font_size = -16

        self._log_font_px_normal = abs(int(font_size))
        self._log_font_px_key = max(int(self._log_font_px_normal), 18)
        self._log_font_px_alert = 14
        log_font = (font_family, int(font_size), font_weight)
        
        self.text_log_system = scrolledtext.ScrolledText(
            self.tab_system,
            height=self._log_text_default_height,
            state="disabled",
            font=log_font,
            padx=8,
            pady=4,
        )
        self.text_log_system.pack(fill=tk.BOTH, expand=True)
        self._configure_log_tags(self.text_log_system)
        
        # Tab 2: Seed Monitor
        self.tab_seed = ttk.Frame(self.notebook_log)
        self.notebook_log.add(self.tab_seed, text="Seed监控")
        
        self.text_log_seed = scrolledtext.ScrolledText(
            self.tab_seed,
            height=self._log_text_default_height,
            state="disabled",
            font=log_font,
            padx=8,
            pady=4,
        )
        self.text_log_seed.pack(fill=tk.BOTH, expand=True)
        self._configure_log_tags(self.text_log_seed)

        # Tab 3: Layer List
        self.tab_layers = ttk.Frame(self.notebook_log)
        self.notebook_log.add(self.tab_layers, text="图层列表")
        
        columns = ("name", "format", "title")
        try:
            style = ttk.Style()
            body = self._ui_fonts.get("body", ("Microsoft YaHei", -16, "normal"))
            subtitle = self._ui_fonts.get("subtitle", ("Microsoft YaHei", -16, "bold"))
            body_16 = (str(body[0]), -abs(int(self._log_font_px_normal)), str(body[2]))
            subtitle_16 = (str(subtitle[0]), -abs(int(self._log_font_px_normal)), str(subtitle[2]))
            style.configure("Log.Treeview", font=body_16)
            style.configure("Log.Treeview.Heading", font=subtitle_16)
        except Exception:
            pass

        self.tree_layers = ttk.Treeview(self.tab_layers, columns=columns, show="headings", selectmode="none", height=2, style="Log.Treeview")
        
        self.tree_layers.heading("name", text="图层名称 (Name)")
        self.tree_layers.heading("format", text="格式 (Format)")
        self.tree_layers.heading("title", text="标题 (Title)")
        
        self.tree_layers.column("name", width=200, anchor=tk.CENTER)
        self.tree_layers.column("format", width=104, anchor=tk.CENTER)
        self.tree_layers.column("title", width=400, anchor=tk.CENTER)
        
        self.tree_layers.tag_configure("hover", background="#f5f5f5")
        
        scrollbar_layers = ttk.Scrollbar(self.tab_layers, orient=tk.VERTICAL, command=self.tree_layers.yview)
        self.tree_layers.configure(yscroll=scrollbar_layers.set)
        
        self.tree_layers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_layers.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree_layers.bind("<Button-1>", self.on_layer_click)
        self.tree_layers.bind("<Motion>", self.on_tree_hover)

        # Tab 4: Seed Progress (Insert at end)
        self.tab_seed_progress = ttk.Frame(self.notebook_log)
        self.notebook_log.add(self.tab_seed_progress, text="切片进度")
        self.seed_progress_view = SeedProgressCanvasView(
            self.tab_seed_progress,
            colors=self._ui_colors,
            get_fonts=lambda: self._ui_fonts,
            on_package=self._on_seed_progress_package_clicked,
            show_toast=self.show_toast,
        )
        
        # Alias for backward compatibility
        self.text_log = self.text_log_system

        try:
            self.root.after(0, self._ensure_log_min_visible_lines)
        except Exception:
            pass
        try:
            self.root.after(0, self._adjust_log_notebook_default_height)
        except Exception:
            pass

    def _reload_seed_tasks_from_yaml(self) -> None:
        """从 mapproxy-seed.yaml 加载 seed 任务列表并保持创建顺序。"""
        try:
            path = self._seed_seed_yaml_path
            if not os.path.exists(path):
                self._seed_task_names = []
                return

            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = None

            if mtime is not None and self._seed_progress_yaml_mtime is not None and mtime == self._seed_progress_yaml_mtime:
                return

            self._seed_progress_yaml_mtime = mtime

            data = {}
            yaml_mod = None
            try:
                import yaml as yaml_mod
            except Exception:
                yaml_mod = None

            if yaml_mod is not None:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml_mod.safe_load(f) or {}
                seeds = data.get("seeds", {})
                if isinstance(seeds, dict):
                    self._seed_task_names = [str(k) for k in seeds.keys()]
                else:
                    self._seed_task_names = []
            else:
                names: list[str] = []
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except Exception:
                    lines = []

                seeds_indent: Optional[int] = None
                for raw in lines:
                    line = raw.rstrip("\n")
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    if seeds_indent is None:
                        if re.match(r"^\s*seeds\s*:\s*$", line):
                            seeds_indent = len(line) - len(line.lstrip())
                        continue

                    indent = len(line) - len(line.lstrip())
                    if indent <= seeds_indent:
                        break
                    if indent != seeds_indent + 2:
                        continue
                    m = re.match(r"^\s*([^:#]+?)\s*:\s*$", line)
                    if not m:
                        continue
                    key = m.group(1).strip().strip("'\"")
                    if key:
                        names.append(key)
                self._seed_task_names = names
        except Exception:
            self._seed_task_names = []

    def _schedule_seed_progress_refresh(self) -> None:
        """合并频繁更新，避免日志高频写入导致重绘过于频繁。"""
        if self._seed_progress_refresh_pending:
            return
        self._seed_progress_refresh_pending = True

        def _do_refresh() -> None:
            self._seed_progress_refresh_pending = False
            try:
                if hasattr(self, "seed_progress_view") and self.seed_progress_view:
                    self.seed_progress_view.set_state(
                        tasks=self._seed_task_names,
                        progress=self._seed_task_progress,
                        packaging=self._seed_packaging,
                        status=self._seed_task_status,
                    )
            except Exception:
                pass

        try:
            self.root.after(120, _do_refresh)
        except Exception:
            self._seed_progress_refresh_pending = False

    def _poll_seed_progress_sources(self) -> None:
        """定时同步 seed 任务列表与总体完成状态（不影响其它Tab生命周期）。"""
        try:
            self._reload_seed_tasks_from_yaml()

            status = {}
            try:
                if os.path.exists(self._seed_status_path):
                    with open(self._seed_status_path, "r", encoding="utf-8") as f:
                        status = json.load(f) if f else {}
            except Exception:
                status = {}

            next_progress: dict[str, tuple[float, int, int]] = {}
            for name in self._seed_task_names:
                next_progress[name] = self._seed_task_progress.get(name, (0, 0, 0))
            next_status: dict[str, str] = {}
            for name in self._seed_task_names:
                next_status[name] = str(self._seed_task_status.get(name, "") or "")

            tasks_payload = status.get("tasks")
            if isinstance(tasks_payload, dict):
                for name in self._seed_task_names:
                    raw = tasks_payload.get(name)
                    if not isinstance(raw, dict):
                        continue
                    try:
                        pct_f = float(raw.get("percent", 0.0) or 0.0)
                    except Exception:
                        pct_f = 0.0
                    try:
                        processed = int(raw.get("processed", 0) or 0)
                    except Exception:
                        processed = 0
                    try:
                        total = int(raw.get("total", 0) or 0)
                    except Exception:
                        total = 0
                    try:
                        st = str(raw.get("status", "") or "")
                    except Exception:
                        st = ""

                    if pct_f < 0.0:
                        pct_f = 0.0
                    if pct_f > 100.0:
                        pct_f = 100.0
                    if total > 0 and processed >= total:
                        pct_f = 100.0
                        processed = total

                    next_progress[name] = (float(pct_f), int(processed), int(total))
                    if st:
                        next_status[name] = st

            state = str(status.get("status", "") or "").lower()
            if state in {"completed", "finished"}:
                for name in self._seed_task_names:
                    pct, processed, total = next_progress.get(name, (0, 0, 0))
                    if total > 0 and processed < total:
                        processed = total
                    next_progress[name] = (100.0, int(processed), int(total))
                    if str(next_status.get(name, "") or "").lower() not in {"failed", "error"}:
                        next_status[name] = "completed"

            self._seed_task_progress = next_progress
            self._seed_task_status = next_status
        except Exception:
            pass
        finally:
            self._schedule_seed_progress_refresh()
            try:
                self.root.after(1000, self._poll_seed_progress_sources)
            except Exception:
                pass

    def _try_update_seed_task_progress_from_log(self, message: str) -> bool:
        """从 seed 日志中解析进度并更新对应任务卡片数据。"""
        try:
            msg = str(message or "")
            if "%" not in msg or "/" not in msg:
                return False

            task = ""
            task_match = re.search(r"\[(?P<task>[A-Za-z0-9_]+)\]", msg)
            if task_match:
                task = str(task_match.group("task"))
            if not task:
                task_match2 = re.search(r"\[[0-9]{1,2}:[0-9]{2}:[0-9]{2}\]\s+(?P<task>[A-Za-z0-9_]+)\b", msg)
                if task_match2:
                    task = str(task_match2.group("task"))
            if not task:
                return False

            prog_match = re.search(
                r"(?P<pct>[0-9]+(?:\.[0-9]+)?)%\s+(?P<processed>[0-9]+)\s*/\s*(?P<total>[0-9]+)",
                msg,
            )
            if not prog_match:
                return False

            pct_f = float(prog_match.group("pct"))
            processed = int(prog_match.group("processed"))
            total = int(prog_match.group("total"))

            if total > 0 and processed >= total:
                pct_val = 100.0
                processed = total
            else:
                pct_val = float(pct_f)
                if pct_val < 0.0:
                    pct_val = 0.0
                if pct_val > 100.0:
                    pct_val = 100.0

            old = self._seed_task_progress.get(task)
            new = (float(pct_val), int(processed), int(total))
            if old == new:
                return False
            self._seed_task_progress[task] = new
            if float(pct_val) >= 100.0:
                self._seed_task_status[task] = "completed"
            else:
                self._seed_task_status[task] = "running"
            if task not in self._seed_task_names and task:
                self._seed_task_names.append(task)
            return True
        except Exception:
            return False

    def _on_seed_progress_package_clicked(self, seed_name: str) -> None:
        """处理“切片进度”卡片的打包按钮点击（异步 + toast）。"""
        self._package_seed_output_async(seed_name)

    def _package_seed_output_async(self, seed_name: str) -> None:
        """将 cache_data 打包为 zip（通过 toast 提示 loading/success/error）。"""
        seed_name_safe = re.sub(r"[^A-Za-z0-9_\\-]+", "_", str(seed_name))[:64] or "seed"
        work_dir = get_work_dir()
        
        # Read cache_dir from map_config.json
        cache_dir = os.path.join(work_dir, "cache_data")
        map_config_path = os.path.join(work_dir, "mapproxy_config", "map_config.json")
        if os.path.exists(map_config_path):
            try:
                import json
                with open(map_config_path, 'r', encoding='utf-8') as f:
                    map_cfg = json.load(f)
                    cache_dir_val = map_cfg.get("features", {}).get("cache_dir")
                    if cache_dir_val:
                        if os.path.isabs(cache_dir_val):
                            cache_dir = cache_dir_val
                        else:
                            cache_dir = os.path.normpath(os.path.join(work_dir, cache_dir_val))
            except Exception:
                pass
                
        output_dir = os.path.join(work_dir, "packaged_tiles")

        if seed_name in self._seed_packaging:
            self.show_toast("正在打包，请稍候…")
            return

        if not os.path.exists(cache_dir):
            self.show_toast("打包失败：缓存目录不存在")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            self.show_toast("打包失败：无法创建输出目录")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_base = os.path.join(output_dir, f"tiles_{seed_name_safe}_{timestamp}")

        self._seed_packaging.add(seed_name)
        self.show_toast("正在打包…")
        self._schedule_seed_progress_refresh()

        def _run() -> None:
            try:
                shutil.make_archive(zip_base, "zip", cache_dir)
                zip_path = zip_base + ".zip"
                self.root.after(0, lambda: self._on_package_done(seed_name, True, zip_path))
            except Exception as e:
                self.root.after(0, lambda: self._on_package_done(seed_name, False, str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_package_done(self, seed_name: str, success: bool, result: str) -> None:
        """打包完成回调：更新状态并以 toast 提示结果。"""
        try:
            self._seed_packaging.discard(seed_name)
            if success:
                self.show_toast("打包成功")
            else:
                self.show_toast("打包失败")
        except Exception:
            pass
        finally:
            self._schedule_seed_progress_refresh()

    def _configure_log_tags(self, widget):
        """配置日志 Text/ScrolledText 的高亮样式（颜色与差异化字号）。"""
        def _current_base_size() -> tuple[int, bool]:
            """获取控件当前字体大小（返回正数）与是否为像素尺寸。"""
            try:
                f = widget.cget("font")
            except Exception:
                return (int(self._log_font_px_normal), False)

            try:
                if isinstance(f, tuple) and len(f) >= 2:
                    size = int(f[1])
                    return (abs(size), size < 0)
                font_obj = tkfont.Font(font=f)
                size = int(font_obj.cget("size"))
                return (abs(size), size < 0)
            except Exception:
                return (int(self._log_font_px_normal), False)

        def _font_with_size(size_abs: int, use_pixels: bool) -> tuple:
            """从当前控件字体派生固定字号（保持字体族与字重不变）。"""
            try:
                f = widget.cget("font")
            except Exception:
                f = ("Consolas", 14, "normal")
            family = "Consolas"
            weight = "normal"
            try:
                if isinstance(f, tuple) and len(f) >= 3:
                    family = str(f[0])
                    weight = str(f[2])
                else:
                    font_obj = tkfont.Font(font=f)
                    family = str(font_obj.cget("family"))
                    weight = str(font_obj.cget("weight"))
            except Exception:
                pass
            s = abs(int(size_abs))
            return (family, -s if use_pixels else s, weight)

        base_abs, base_is_px = _current_base_size()
        base_px = int(base_abs)
        key_px = base_px
        alert_px = base_px

        widget.tag_config("DEBUG", foreground=self._ui_colors["muted"], font=_font_with_size(base_px, base_is_px))
        widget.tag_config("INFO", foreground=self._ui_colors["text"], font=_font_with_size(base_px, base_is_px))
        widget.tag_config("WARN", foreground=self._ui_colors["warn"], font=_font_with_size(alert_px, base_is_px))
        widget.tag_config("ERROR", foreground=self._ui_colors["error"], font=_font_with_size(alert_px, base_is_px))
        widget.tag_config("SUCCESS", foreground=self._ui_colors["success"], font=_font_with_size(key_px, base_is_px))
        widget.tag_config("SEED", foreground=self._ui_colors["seed"], font=_font_with_size(key_px, base_is_px))

    def on_canvas_configure(self, event):
        """Ensure inner frame matches canvas width and handles responsive layout"""
        # 1. Width Adaptation
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        self.adapt_ui_size(event.width)
        
        self._adjust_internal_scroll_widgets(int(getattr(event, "height", 0) or 0))
        self.canvas.itemconfig(self.canvas_window, height=event.height)
        self.scrollbar.grid_remove()
        self.canvas.configure(scrollregion=(0, 0, event.width, event.height))

    def _adjust_internal_scroll_widgets(self, available_height: int) -> None:
        """在固定窗口高度下，通过调整内部控件请求尺寸，避免主界面出现外层滚动条或裁剪。"""
        try:
            avail = int(available_height or 0)
        except Exception:
            return
        if avail <= 0:
            return

        try:
            self.scrollable_frame.update_idletasks()
            min_req_height = int(self.scrollable_frame.winfo_reqheight() or 0)
        except Exception:
            min_req_height = 0

        if min_req_height <= 0:
            return

        tol = 8
        try:
            cur_h = int(self.text_log_system.cget("height") or self._log_text_default_height)
        except Exception:
            cur_h = self._log_text_default_height

        target_h = max(self._log_text_min_height, min(self._log_text_default_height, cur_h))
        loops = 0
        while (min_req_height > (avail + tol)) and (target_h > self._log_text_min_height) and (loops < 8):
            target_h -= 1
            try:
                self.text_log_system.configure(height=target_h)
                self.text_log_seed.configure(height=target_h)
            except Exception:
                break
            try:
                self.scrollable_frame.update_idletasks()
                min_req_height = int(self.scrollable_frame.winfo_reqheight() or 0)
            except Exception:
                break
            loops += 1

        loops = 0
        while (min_req_height + tol * 2 < avail) and (target_h < self._log_text_default_height) and (loops < 8):
            target_h += 1
            try:
                self.text_log_system.configure(height=target_h)
                self.text_log_seed.configure(height=target_h)
            except Exception:
                break
            try:
                self.scrollable_frame.update_idletasks()
                min_req_height = int(self.scrollable_frame.winfo_reqheight() or 0)
            except Exception:
                break
            loops += 1

        self._ensure_log_min_visible_lines()

    def _ensure_log_min_visible_lines(self) -> None:
        """确保日志区域在当前像素高度下可视行数不少于阈值，必要时降低日志字体像素大小。"""
        def _visible_lines_for(w: tk.Widget) -> int:
            """基于当前像素高度与字体行高，估算 Text/ScrolledText 可视行数。"""
            try:
                w.update_idletasks()
                height_px = int(w.winfo_height() or 0)
            except Exception:
                return 0
            if height_px <= 0:
                return 0

            try:
                pad_y = int(w.cget("pady") or 0)
            except Exception:
                pad_y = 0

            try:
                font_obj = tkfont.Font(font=w.cget("font"))
                line_px = int(font_obj.metrics("linespace") or 0)
            except Exception:
                line_px = 0
            if line_px <= 0:
                return 0

            usable_px = max(0, height_px - pad_y * 2)
            return max(0, usable_px // max(1, line_px))

        try:
            target_lines = int(getattr(self, "_log_min_visible_lines", 8) or 8)
        except Exception:
            target_lines = 8
        if target_lines <= 0:
            return

        try:
            widget = self.text_log_system
            seed_widget = self.text_log_seed
        except Exception:
            return
        try:
            visible_lines = min(_visible_lines_for(widget), _visible_lines_for(seed_widget))
        except Exception:
            visible_lines = 0
        if visible_lines >= target_lines:
            return

        try:
            cur_font = widget.cget("font")
            font_obj = tkfont.Font(font=widget.cget("font"))
            if isinstance(cur_font, tuple) and len(cur_font) >= 2:
                cur_size = int(cur_font[1])
            else:
                parsed_size: int | None = None
                try:
                    if isinstance(cur_font, str):
                        m = re.search(r"(-?\d+)", cur_font)
                        if m:
                            parsed_size = int(m.group(1))
                except Exception:
                    parsed_size = None
                if parsed_size is None:
                    parsed_size = int(getattr(font_obj, "cget")("size"))
                cur_size = int(parsed_size)
        except Exception:
            cur_size = -16
        if cur_size > 0:
            cur_size = -cur_size

        self._log_font_size_px = cur_size

        min_size = int(getattr(self, "_log_font_min_px", -12) or -12)
        if min_size >= 0:
            min_size = -12

        new_size = int(cur_size)
        guard = 0
        while visible_lines < target_lines and new_size < min_size and guard < 24:
            new_size += 1
            guard += 1
            try:
                try:
                    widget.configure(font=("Consolas", new_size, "normal"))
                    seed_widget.configure(font=("Consolas", new_size, "normal"))
                except Exception:
                    font_obj = tkfont.Font(family="Consolas", size=new_size)
                    widget.configure(font=font_obj)
                    seed_widget.configure(font=font_obj)

                try:
                    self._configure_log_tags(widget)
                    self._configure_log_tags(seed_widget)
                except Exception:
                    pass

                visible_lines = min(_visible_lines_for(widget), _visible_lines_for(seed_widget))
            except Exception:
                break

        self._log_font_size_px = int(new_size)

    def _adjust_log_notebook_default_height(self) -> None:
        """基于现有像素高度按比例上调日志 Notebook 默认高度，并触发一次窗口自适配。"""
        try:
            ratio = float(getattr(self, "_log_notebook_height_ratio", 1.0) or 1.0)
        except Exception:
            ratio = 1.0
        ratio = max(1.0, min(1.25, ratio))

        try:
            self.notebook_log.update_idletasks()
            cur_px = int(self.notebook_log.winfo_height() or 0)
            if cur_px <= 0:
                cur_px = int(self.notebook_log.winfo_reqheight() or 0)
        except Exception:
            return
        if cur_px <= 0:
            return

        if self._log_notebook_base_height_px is None:
            self._log_notebook_base_height_px = cur_px

        base_px = int(self._log_notebook_base_height_px or cur_px)
        target_px = max(120, int(base_px * ratio))

        try:
            self.notebook_log.configure(height=target_px)
        except Exception:
            return

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        self._ensure_log_min_visible_lines()
        self._ensure_window_height_for_content()

    def _ensure_window_height_for_content(self) -> None:
        """在首屏阶段，必要时增大窗口高度以避免外层滚动条出现。"""
        if getattr(self, "_did_initial_autosize", False):
            return
        self._did_initial_autosize = True

        try:
            screen_h = int(self.root.winfo_screenheight() or 0)
        except Exception:
            screen_h = 0

        try:
            self.scrollable_frame.update_idletasks()
            req_h = int(self.scrollable_frame.winfo_reqheight() or 0)
        except Exception:
            return
        if req_h <= 0:
            return

        try:
            cur_h = int(self.root.winfo_height() or 0)
            cur_w = int(self.root.winfo_width() or 0)
        except Exception:
            return
        if cur_h <= 0 or cur_w <= 0:
            return

        try:
            current_scrollbar_visible = bool(self.scrollbar.winfo_ismapped())
        except Exception:
            current_scrollbar_visible = False

        if not current_scrollbar_visible and req_h <= cur_h:
            return

        max_h = cur_h
        if screen_h > 0:
            max_h = max(cur_h, int(screen_h * 0.92))
            max_h = min(max_h, max(200, screen_h - 120))

        target_h = min(max_h, max(cur_h, req_h + 8))
        if target_h <= cur_h:
            return

        try:
            self.root.geometry(f"{cur_w}x{target_h}")
            self.root.update_idletasks()
        except Exception:
            pass

    def adapt_ui_size(self, width: int) -> None:
        """根据屏幕宽度自适应调整字体与组件样式（仅视觉参数）。"""
        style = ttk.Style()

        w = max(1, int(width))
        if w < 1600:
            base_px = 14
            title_px = 16
        elif w < 2560:
            base_px = 16
            title_px = 18
        else:
            base_px = 18
            title_px = 20

        base_font_size = -max(14, base_px)
        title_font_size = -max(18, title_px)

        mono_font_size = base_font_size
        if mono_font_size > -16:
            mono_font_size = -16
        if mono_font_size < -18:
            mono_font_size = -18
        log_mono_font_size = -16

        self._ui_fonts = {
            "body": ("Microsoft YaHei", base_font_size, "normal"),
            "subtitle": ("Microsoft YaHei", base_font_size, "bold"),
            "title": ("Microsoft YaHei", title_font_size, "bold"),
            "mono": ("Consolas", mono_font_size, "normal"),
            "log_mono": ("Consolas", log_mono_font_size, "normal"),
        }

        style.configure(".", font=self._ui_fonts["body"])
        style.configure("TLabelframe.Label", font=self._ui_fonts["subtitle"])
        style.configure("Treeview.Heading", font=self._ui_fonts["subtitle"])
        tab_pad_y = 12
        try:
            tab_font = tkfont.Font(family=self._ui_fonts["subtitle"][0], size=int(self._ui_fonts["subtitle"][1]))
            line_px = int(tab_font.metrics("linespace") or 0)
            tab_pad_y = max(12, int((44 - line_px + 1) // 2))
        except Exception:
            tab_pad_y = 12
        style.configure("TNotebook.Tab", font=self._ui_fonts["subtitle"], padding=(16, tab_pad_y))
        style.configure("TButton", font=self._ui_fonts["body"], padding=(8, 6))
        style.configure("TCheckbutton", padding=(3, 3))
        style.configure("TRadiobutton", padding=(3, 3))

        try:
            style.configure("TEntry", padding=(8, 8))
        except Exception:
            pass

        try:
            style.map(
                "TButton",
                background=[
                    ("active", self._ui_colors["hover_bg"]),
                    ("!disabled", "white"),
                ],
                foreground=[
                    ("disabled", self._ui_colors["muted"]),
                    ("!disabled", self._ui_colors["text"]),
                ],
            )
        except Exception:
            pass

        style.configure("Treeview", font=self._ui_fonts["body"], rowheight=36)

    def set_status(self, status, color, url=""):
        self.status_var.set(status)
        self.lbl_status.config(foreground=color)
        self.canvas_status.itemconfig(self.status_circle, fill=color, outline=color)
        self.service_url_var.set(url)

    def get_current_log_widget(self):
        try:
            # Note: notebook index might be string or int depending on tk version/wrapper, 
            # but index("current") returns int usually.
            current_tab_index = self.notebook_log.index("current")
            if current_tab_index == 1: # Index 1 is Seed Tab
                return self.text_log_seed
        except Exception:
            pass
        return self.text_log_system

    def is_seed_log(self, message):
        # 1. Check for specific Seed modules
        if "SeedManager" in message or "SeedOrchestrator" in message:
            return True
            
        # 2. Check for standard seed progress format (fallback)
        # [15:20:00] 10.50% 100/1000 (15 tiles/s)
        if "tiles/s)" in message and "%" in message:
            return True
            
        return False

    def detect_log_level(self, message):
        """Attempt to detect log level from message content"""
        message_upper = message.upper()
        if "ERROR" in message_upper or "CRITICAL" in message_upper or "EXCEPTION" in message_upper:
            return "ERROR"
        if "WARN" in message_upper:
            return "WARN"
        if "DEBUG" in message_upper:
            return "DEBUG"
        if "SUCCESS" in message_upper:
            return "SUCCESS"
        return "INFO"

    def _write_to_log(self, widget, message, tag="INFO"):
        widget.config(state="normal")
        widget.insert("end", message + "\n", tag)
        if self.log_auto_scroll.get():
            widget.see("end")
        widget.config(state="disabled")

    def _check_and_write(self, widget, message, level):
        """Generic filter and write function"""
        min_level = self.log_level_var.get()
        # Map levels to integers
        levels_map = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "CRITICAL": 3, "SEED": 1, "SUCCESS": 1}
        
        # Determine numeric values
        msg_val = levels_map.get(level.upper(), 1)
        min_val = levels_map.get(min_level.upper(), 1)
        
        if msg_val >= min_val:
            self._write_to_log(widget, message, level)

    def refresh_log_view(self, event=None):
        """Refilter logs in all tabs based on level"""
        min_level = self.log_level_var.get()
        levels_map = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "CRITICAL": 3, "SEED": 1, "SUCCESS": 1}
        min_val = levels_map.get(min_level.upper(), 1)
        
        # 1. Refresh System Log
        self.text_log_system.config(state="normal")
        self.text_log_system.delete(1.0, tk.END)
        for level, msg in self.system_log_buffer:
            msg_val = levels_map.get(level.upper(), 1)
            if msg_val >= min_val:
                self.text_log_system.insert("end", msg + "\n", level)
        if self.log_auto_scroll.get():
            self.text_log_system.see("end")
        self.text_log_system.config(state="disabled")
        
        # 2. Refresh Seed Log
        self.text_log_seed.config(state="normal")
        self.text_log_seed.delete(1.0, tk.END)
        for level, msg in self.seed_log_buffer:
            msg_val = levels_map.get(level.upper(), 1)
            if msg_val >= min_val:
                self.text_log_seed.insert("end", msg + "\n", level)
        if self.log_auto_scroll.get():
            self.text_log_seed.see("end")
        self.text_log_seed.config(state="disabled")

    def log(self, message, level=None):
        # Auto-detect level if not provided
        if level is None:
            level = self.detect_log_level(message)
            
        # Normalize level
        level = level.upper()
        if level == "WARNING": level = "WARN"
            
        is_seed = self.is_seed_log(message)
        
        # Determine tag for coloring
        # For Seed logs, we prefer the actual level if it's WARN/ERROR, otherwise SEED/INFO
        log_tag = level
        if is_seed and level in ["INFO", "DEBUG"]:
            log_tag = "SEED"
        
        # Add to appropriate buffer
        if is_seed:
            self.seed_log_buffer.append((log_tag, message))
            if len(self.seed_log_buffer) > self.max_log_buffer:
                self.seed_log_buffer.pop(0)
        else:
            self.system_log_buffer.append((level, message))
            if len(self.system_log_buffer) > self.max_log_buffer:
                self.system_log_buffer.pop(0)

        # Routing Logic
        if is_seed:
            try:
                updated = self._try_update_seed_task_progress_from_log(message)
                if updated:
                    self._schedule_seed_progress_refresh()
            except Exception:
                pass
            # To seed tab (filtered)
            self._check_and_write(self.text_log_seed, message, log_tag)
            
            # Optionally to system tab (filtered)
            if self.show_seed_in_system_var.get():
                self._check_and_write(self.text_log_system, message, log_tag)
        else:
            # To system tab (filtered)
            self._check_and_write(self.text_log_system, message, level)

    def _check_and_write_system(self, message, level):
        # Legacy support or alias to new generic method
        self._check_and_write(self.text_log_system, message, level)

    def clear_logs(self):
        if messagebox.askyesno("确认", "确定要清空当前显示的日志吗？"):
            widget = self.get_current_log_widget()
            
            # Clear Widget
            widget.config(state="normal")
            widget.delete(1.0, tk.END)
            widget.config(state="disabled")
            
            # Clear Buffer
            if widget == self.text_log_seed:
                self.seed_log_buffer = []
            else:
                self.system_log_buffer = []

    def export_logs(self):
        from tkinter import filedialog
        
        widget = self.get_current_log_widget()
        is_seed_tab = (widget == self.text_log_seed)
        buffer = self.seed_log_buffer if is_seed_tab else self.system_log_buffer
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("Log Files", "*.log"), ("All Files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    for _, msg in buffer:
                        f.write(msg + "\n")
                messagebox.showinfo("成功", "日志已导出")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {e}")

    def scan_pythons(self):
        """扫描并刷新 Python 解释器列表（打包版固定为内置解释器）。"""
        if getattr(self, 'is_scanning', False):
            return

        if getattr(sys, "frozen", False):
            try:
                py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            except Exception:
                py_ver = "unknown"
            internal_value = f"Internal (内置) Python {py_ver} - {sys.executable}"
            self.python_path_var.set(internal_value)
            try:
                self.log("打包版运行：已固定使用内置解释器。")
            except Exception:
                pass
            return

        self.is_scanning = True
        if self.btn_refresh is not None:
            self.btn_refresh.config(state="disabled")
        if self.combo_python is not None:
            self.combo_python.config(state="disabled")
        self.log("正在扫描 Python 解释器...")
        
        def run_scan():
            try:
                interpreters = find_python_interpreters()
                self.root.after(0, self._on_scan_complete, interpreters)
            except Exception as e:
                self.root.after(0, self._on_scan_error, str(e))
                
        threading.Thread(target=run_scan, daemon=True).start()

    def _on_scan_complete(self, interpreters):
        self.is_scanning = False
        
        values = [f"{i['version']} - {i['path']}" for i in interpreters]
        if self.combo_python is not None:
            self.combo_python['values'] = values
        
        # Restore selection or default to first
        current = self.python_path_var.get()
        if current and current in values:
            if self.combo_python is not None:
                self.combo_python.current(values.index(current))
        elif values:
            if self.combo_python is not None:
                self.combo_python.current(0)
            
        self.log(f"扫描完成，发现 {len(interpreters)} 个解释器。")
        
        # Re-enable UI if service not running
        if not self.service_process:
            if self.btn_refresh is not None:
                self.btn_refresh.config(state="normal")
            if self.combo_python is not None:
                self.combo_python.config(state="readonly")

    def _on_scan_error(self, error_msg):
        self.is_scanning = False
        self.log(f"扫描出错: {error_msg}", "error")
        # Re-enable UI if service not running
        if not self.service_process:
            if self.btn_refresh is not None:
                self.btn_refresh.config(state="normal")
            if self.combo_python is not None:
                self.combo_python.config(state="readonly")

    def update_host_from_access(self):
        if self.allow_external_var.get():
            self.host_var.set("0.0.0.0")
        else:
            self.host_var.set("127.0.0.1")

    def update_controls_state(self, is_running):
        state = "disabled" if is_running else "normal"
        readonly = "disabled" if is_running else "readonly"
        
        # Environment
        if self.combo_python is not None:
            self.combo_python.config(state=readonly)
        if self.btn_refresh is not None:
            self.btn_refresh.config(state=state)
        
        # Config
        self.entry_port.config(state=state)
        self.entry_threads.config(state=state)
        self.chk_external.config(state=state)
        self.btn_save.config(state=state)
        self.btn_advanced.config(state=state)

    def load_layers(self):
        """加载并显示图层信息"""
        self.tree_layers.delete(*self.tree_layers.get_children())
        layers = self.config_mgr.get_layers()
        if not layers:
            # Try to insert a placeholder or log
            self.log("未找到图层信息或配置文件读取失败。")
            return

        for layer in layers:
            self.tree_layers.insert("", tk.END, values=(
                layer.get('name', ''),
                layer.get('format', ''),
                layer.get('title', '')
            ))
        self.log(f"已加载 {len(layers)} 个图层信息。")

    def on_layer_click(self, event):
        """单击图层列表复制单元格内容"""
        region = self.tree_layers.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree_layers.identify_column(event.x)
            item_id = self.tree_layers.identify_row(event.y)
            if item_id:
                # column returns #1, #2, etc. convert to index
                col_idx = int(column.replace('#', '')) - 1
                values = self.tree_layers.item(item_id, 'values')
                if 0 <= col_idx < len(values):
                    val = values[col_idx]
                    self.copy_to_clipboard(val)

    def on_tree_hover(self, event):
        """鼠标悬停效果"""
        region = self.tree_layers.identify("region", event.x, event.y)
        if region == "cell":
            self.tree_layers.configure(cursor="hand2")
            
            # 高亮行效果
            item_id = self.tree_layers.identify_row(event.y)
            
            # 清除所有其他行的 hover 状态 (或者只清除上一个)
            # 这里简单处理，如果行数不多，遍历清除。如果行数多，建议只追踪 last_hover_item
            # 由于 Treeview tag 系统，我们需要追踪上一个 hover 的项
            
            if hasattr(self, '_last_hover_item') and self._last_hover_item and self._last_hover_item != item_id:
                try:
                    self.tree_layers.item(self._last_hover_item, tags=())
                except Exception:
                    pass # Item might be deleted
            
            if item_id:
                self.tree_layers.item(item_id, tags=("hover",))
                self._last_hover_item = item_id
            else:
                self._last_hover_item = None

        else:
            self.tree_layers.configure(cursor="")
            # 移出 cell 区域时清除高亮
            if hasattr(self, '_last_hover_item') and self._last_hover_item:
                try:
                    self.tree_layers.item(self._last_hover_item, tags=())
                except Exception:
                    pass
                self._last_hover_item = None

    def show_toast(self, message):
        """显示简单的 Toast 消息"""
        try:
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            
            # 简单的样式
            label = tk.Label(
                toast,
                text=message,
                bg=self._ui_colors["toast_bg"],
                fg=self._ui_colors["toast_fg"],
                padx=16,
                pady=16,
                font=("Microsoft YaHei", -14),
            )
            label.pack()
            
            # 居中显示在主窗口下方或中间
            # 获取主窗口位置和大小
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
            
            # Toast 大小
            toast.update_idletasks()
            w = toast.winfo_width()
            h = toast.winfo_height()
            
            x = root_x + (root_w - w) // 2
            y = root_y + root_h - 100 # 底部偏上
            
            toast.geometry(f"+{x}+{y}")
            
            # 2秒后销毁
            toast.after(2000, toast.destroy)
        except Exception:
            pass # 忽略 Toast 错误

    def copy_to_clipboard(self, text):
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update() 
        self.log(f"已复制到剪贴板: {text}")
        # messagebox.showinfo("复制成功", f"内容已复制:\n{text}") # 替换为 Toast
        self.show_toast(f"已复制: {text}")

    def validate_port_input(self, event=None):
        try:
            port = int(self.port_var.get())
            if 1 <= port <= 65535:
                self.entry_port.config(foreground=self._ui_colors["text"])
                self.btn_save.config(state="normal")
                return True
            else:
                raise ValueError
        except ValueError:
            self.entry_port.config(foreground=self._ui_colors["error"])
            self.btn_save.config(state="disabled")
            return False

    def validate_threads_input(self, event=None):
        try:
            threads = int(self.waitress_threads_var.get())
            if 1 <= threads <= 32:
                self.entry_threads.config(foreground=self._ui_colors["text"])
                # Also check port to ensure save button state is correct overall
                if self.validate_port_input():
                    self.btn_save.config(state="normal")
                return True
            else:
                raise ValueError
        except ValueError:
            self.entry_threads.config(foreground=self._ui_colors["error"])
            self.btn_save.config(state="disabled")
            return False

    def save_config(self):
        # Double check: Prevent saving if service is running
        if self.service_process:
            messagebox.showwarning("警告", "服务正在运行，无法修改配置。请先停止服务。")
            return

        if not self.validate_port_input():
            messagebox.showerror("错误", "端口号无效")
            return

        if not self.validate_threads_input():
            messagebox.showerror("错误", "线程数无效 (1-32)")
            return

        selection = self.python_path_var.get()
        if not selection:
             messagebox.showerror("错误", "请选择 Python 版本")
             return
             
        # 提取路径
        if " - " in selection:
            python_path = selection.split(" - ")[-1]
        else:
            python_path = selection

        if "Internal" not in selection and not os.path.exists(python_path):
             messagebox.showerror("错误", "选定的 Python 路径不存在")
             return

        self.update_host_from_access()
        host_value = self.host_var.get().strip()
        
        config_data = {
            "python_path": python_path,
            "port": int(self.port_var.get()),
            "host": host_value,
            "allow_external_access": bool(self.allow_external_var.get()),
            "waitress_threads": int(self.waitress_threads_var.get()),
            "selection_label": selection # 保存完整标签以便回显
        }
        
        try:
            self.config_mgr.save_launcher_config(config_data, source="gui_launcher.save_config")
            self.log("配置已保存。")
            self.show_toast("配置已成功保存")
            # messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            self.logger.exception("保存配置失败")
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def load_config(self):
        try:
            config = self.config_mgr.load_launcher_config()
            path = config.get("python_path", "")
            port = config.get("port", 8080)
            allow_external = config.get("allow_external_access", False)
            threads = config.get("waitress_threads", 16)
            selection_label = config.get("selection_label", "")
            
            self.port_var.set(str(port))
            self.waitress_threads_var.set(str(threads))
            self.allow_external_var.set(bool(allow_external))
            self.update_host_from_access()
            
            if selection_label:
                self.python_path_var.set(selection_label)
            elif path:
                    self.python_path_var.set(path)
        except Exception:
            self.logger.exception("读取配置失败")

    def start_service(self):
        """启动服务进程并触发就绪检测。"""
        if self.service_process:
            return

        if not self.validate_port_input():
            return

        # 验证 MapProxy 配置
        try:
            self.config_mgr.validate_mapproxy_config()
        except Exception as e:
            if not messagebox.askyesno("配置验证警告", f"MapProxy 配置验证失败:\n{e}\n\n是否仍要尝试启动服务?", parent=self.root):
                return
            
        port = int(self.port_var.get())
        self.update_host_from_access()
        host_value = self.host_var.get().strip()
        
        if is_port_in_use(port, host_value):
             messagebox.showerror("错误", f"端口 {port} 已被占用", parent=self.root)
             return
        
        selection = self.python_path_var.get()
        if " - " in selection:
            python_path = selection.split(" - ")[-1]
        else:
            python_path = selection
            
        work_dir = get_work_dir()
        script_path = os.path.join(get_base_dir(), "main.py")
        is_frozen = bool(getattr(sys, "frozen", False))
        
        # 构造命令
        cmd = []
        
        # 判断是 Internal 还是 External
        if is_frozen:
            cmd = [sys.executable, '--service']
        elif "Internal" in selection or python_path == sys.executable:
            if not os.path.exists(script_path):
                messagebox.showerror("错误", f"找不到 main.py: {script_path}")
                return
            cmd = [sys.executable, script_path, '--service']
        else:
            # External Mode
            if is_frozen:
                messagebox.showerror("错误", "打包版不支持使用外部 Python 启动服务，请选择 Internal 模式。")
                return
            if not os.path.exists(python_path):
                 messagebox.showerror("错误", "Python 路径无效")
                 return
            if not os.path.exists(script_path):
                 messagebox.showerror("错误", f"找不到 main.py: {script_path}")
                 return
            
            # 使用 --python-path 明确传递所选 Python 路径给 main.py
            cmd = [python_path, script_path, '--service', '--python-path', python_path]

        # 添加通用参数
        cmd.extend(['--port', str(port), '--host', host_value, '--work-dir', work_dir, '--threads', self.waitress_threads_var.get()])
        self.current_host = host_value
        
        self.log(f"正在启动服务: {' '.join(cmd)}")
        self.set_status("正在初始化环境配置...", "orange") # 状态更新
        
        try:
            # Prepare Environment Variables
            env = os.environ.copy()
            
            # Proxy Support
            try:
                map_config = self.config_mgr.load_map_config()
                http_cfg = map_config.get("system", {}).get("http", {})
                proxy_url = http_cfg.get("proxy", "").strip()
                if proxy_url:
                    env["HTTP_PROXY"] = proxy_url
                    env["HTTPS_PROXY"] = proxy_url
                    self.log(f"已启用代理: {proxy_url}", "info")
            except Exception:
                pass

            seed_settings = self.config_mgr.load_advanced_config()
            env["MAPPROXY_SEED_CONCURRENCY"] = str(seed_settings.get("concurrency", 2))
            
            retry_cfg = seed_settings.get("retry", {})
            if retry_cfg.get("enabled", False):
                env["MAPPROXY_SEED_MAX_RETRIES"] = str(retry_cfg.get("max_retries", 2))
                env["MAPPROXY_SEED_RETRY_BACKOFF"] = str(retry_cfg.get("interval", 5))
            else:
                 env["MAPPROXY_SEED_MAX_RETRIES"] = "0"
                 
            alert_cfg = seed_settings.get("alert", {})
            env["MAPPROXY_SEED_ALERT_ENABLED"] = "true" if alert_cfg.get("enabled", False) else "false"

            # 使用 CREATE_NO_WINDOW 隐藏控制台窗口 (Windows)
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW

            # 注意：cwd 设置为 work_dir 很重要
            self.service_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
                cwd=work_dir,
                env=env
            )
            
            # 启动线程读取输出
            threading.Thread(target=self.read_process_output, args=(self.service_process,), daemon=True).start()
            self._sync_seed_running_status_with_service(True)
            try:
                self._schedule_service_ready_check(port, host_value)
            except Exception:
                pass
            
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.update_controls_state(True)
            
        except Exception as e:
            self.logger.exception("启动失败")
            self.log(f"启动失败: {e}", "error")
            self.set_status("启动失败", "red")
            self.update_controls_state(False)

    def read_process_output(self, process):
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                self.log_queue.put(line.strip())
        
        self.log_queue.put(None) # 标记结束

    def update_logs(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            if msg is None:
                self.log("服务已停止。", "error")
                self.set_status("服务已停止", "red")
                self._sync_seed_running_status_with_service(False)
                self.service_process = None
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
                self.update_controls_state(False)
            else:
                self.log(msg)
                if self.service_process and ("Serving on http://" in msg or "Serving on https://" in msg):
                    try:
                        url_part = msg.split("Serving on ")[1].strip()
                        if "0.0.0.0" in url_part:
                            url_part = url_part.replace("0.0.0.0", self.current_host)
                        self.set_status("运行成功", "green", url_part)
                    except Exception:
                        logging.exception("日志解析失败(Serving on)")
                elif self.service_process and "监听: http://" in msg:
                    try:
                        url_part = msg.split("监听: ")[1].strip()
                        if "0.0.0.0" in url_part:
                            url_part = url_part.replace("0.0.0.0", self.current_host)
                        self.set_status("运行成功", "green", url_part)
                    except Exception:
                        logging.exception("日志解析失败(监听)")
                elif self.service_process and "请访问 http://" in msg:
                    try:
                        url_part = msg.split("请访问 ")[1].strip()
                        if "localhost" not in url_part and "127.0.0.1" not in url_part:
                            pass
                        self.set_status("运行成功", "green", url_part)
                    except Exception:
                        logging.exception("日志解析失败(请访问)")
                elif self.service_process and "Configuration generation completed." in msg:
                    # 配置文件重新生成后，同步更新图层列表
                    self.load_layers()

        # 停止时不读取 server.log 以避免误判
        if self.service_process:
            self.read_server_log()
        
        self.root.after(100, self.update_logs)

    def _schedule_service_ready_check(self, port: int, host_value: str) -> None:
        """定时检测端口就绪，避免仅依赖日志关键字导致状态不更新。"""
        try:
            self._ready_check_started_at = time.time()
        except Exception:
            self._ready_check_started_at = None

        def _tick() -> None:
            should_reschedule = True
            try:
                if not self.service_process:
                    should_reschedule = False
                    return
                if self.service_process.poll() is not None:
                    should_reschedule = False
                    return

                display_host = "127.0.0.1" if host_value in ("0.0.0.0", "::") else host_value
                if is_port_in_use(int(port), display_host):
                    url = f"http://{display_host}:{int(port)}/demo/"
                    self.set_status("运行成功", "green", url)
                    should_reschedule = False
                    return

                if self._ready_check_started_at is not None:
                    if (time.time() - float(self._ready_check_started_at)) > 15:
                        should_reschedule = False
                        return
            except Exception:
                should_reschedule = False
                return
            if should_reschedule:
                try:
                    self.root.after(300, _tick)
                except Exception:
                    pass

        try:
            self.root.after(300, _tick)
        except Exception:
            pass

    def read_server_log(self):
        if self.service_process:
            return
        if not os.path.exists(self.server_log_path):
            return
        try:
            with open(self.server_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.server_log_pos)
                lines = f.readlines()
                self.server_log_pos = f.tell()
            for line in lines:
                text = line.rstrip()
                if text:
                    self.log(text)
        except Exception:
            logging.exception("读取 server.log 失败")

    def _sync_seed_running_status_with_service(self, is_running: bool) -> None:
        try:
            target_status = "running" if bool(is_running) else "paused"
            allowed_prev = {"paused"} if bool(is_running) else {"running", "starting", "retrying"}

            status_data: dict = {}
            if os.path.exists(self._seed_status_path):
                try:
                    with open(self._seed_status_path, "r", encoding="utf-8") as f:
                        status_data = json.load(f) if f else {}
                except Exception:
                    status_data = {}

            task_name: str = ""
            try:
                raw_current = status_data.get("current_task")
                if isinstance(raw_current, str):
                    task_name = raw_current
            except Exception:
                task_name = ""

            tasks_payload = status_data.get("tasks") if isinstance(status_data, dict) else None
            if task_name and isinstance(tasks_payload, dict):
                raw_task = tasks_payload.get(task_name)
                if isinstance(raw_task, dict):
                    cur_status = str(raw_task.get("status", "") or "").lower()
                    try:
                        cur_pct = float(raw_task.get("percent", 0.0) or 0.0)
                    except Exception:
                        cur_pct = 0.0
                    if cur_pct >= 100.0:
                        return
                    if cur_status not in allowed_prev:
                        task_name = ""
            else:
                task_name = ""

            if not task_name:
                for name, st in list(self._seed_task_status.items()):
                    try:
                        st_norm = str(st or "").lower()
                    except Exception:
                        st_norm = ""
                    if st_norm not in allowed_prev:
                        continue
                    pct, _processed, _total = self._seed_task_progress.get(name, (0.0, 0, 0))
                    try:
                        pct_f = float(pct)
                    except Exception:
                        pct_f = 0.0
                    if pct_f >= 100.0:
                        continue
                    task_name = str(name)
                    break

            if not task_name:
                return

            self._seed_task_status[task_name] = target_status
            self._schedule_seed_progress_refresh()

            if not os.path.exists(self._seed_status_path):
                return
            if not isinstance(status_data, dict):
                return
            tasks = status_data.get("tasks")
            if not isinstance(tasks, dict):
                tasks = {}
                status_data["tasks"] = tasks
            raw_entry = tasks.get(task_name)
            if not isinstance(raw_entry, dict):
                raw_entry = {}
                tasks[task_name] = raw_entry
            if str(raw_entry.get("status", "") or "").lower() in {"completed", "finished", "failed", "error"}:
                return
            raw_entry["status"] = target_status
            try:
                status_data["last_update"] = datetime.now().isoformat()
            except Exception:
                pass

            try:
                with open(self._seed_status_path, "w", encoding="utf-8") as f:
                    json.dump(status_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        except Exception:
            pass



    def stop_service(self):
        
        # 仅当持有有效的服务进程标识符时才执行终止操作
        if self.service_process:
            pid = self.service_process.pid
            self.log(f"正在停止服务进程 (PID: {pid})...")
            
            # 优先尝试使用 process_manager 进行完整的进程树清理
            if process_manager:
                success, msg = process_manager.kill_process_tree(pid)
                if success:
                    self.log(msg, "success")
                else:
                    self.log(msg, "error")
            else:
                # 降级方案：仅终止父进程
                try:
                    self.service_process.terminate()
                    try:
                        self.service_process.wait(timeout=3)
                        self.log(f"进程 {pid} 已终止", "success")
                    except subprocess.TimeoutExpired:
                        self.service_process.kill()
                        self.log(f"进程 {pid} 已强制杀死", "warning")
                except Exception as e:
                    logging.exception("停止进程失败")
                    self.log(f"停止进程失败: {e}", "error")
            
            # 清理标识符
            self.service_process = None
            self.set_status("服务已停止", "red")
            self._sync_seed_running_status_with_service(False)
            # 防止读取旧日志造成误判
            try:
                if os.path.exists(self.server_log_path):
                    self.server_log_pos = os.path.getsize(self.server_log_path)
            except Exception:
                logging.exception("更新日志指针失败")
            
            # 验证端口释放 (仅作为信息提示，不进行强制干预)
            try:
                port = int(self.port_var.get())
                if process_manager and process_manager.verify_port_release(port):
                    self.log(f"端口 {port} 已释放。", "success")
                else:
                    # 如果端口未释放，可能是其他进程占用了，或者清理不彻底，但我们不再强杀
                    pass
            except Exception:
                logging.exception("端口释放验证失败")

        else:
            self.log("当前没有运行的服务实例。", "warning")

        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.update_controls_state(False)

    def on_closing(self):
        """窗口关闭事件处理"""
        # 仅当持有服务进程句柄时才提示停止
        if self.service_process:
            if messagebox.askokcancel("退出", "服务正在运行，确定要停止服务并退出吗？", parent=self.root):
                self.stop_service()
                self.root.destroy()
        else:
            self.root.destroy()

    def open_advanced_settings(self):
        if self.service_process:
            messagebox.showwarning("警告", "服务正在运行，高级设置暂不可用。")
            return

        show_advanced_settings_dialog(self.root, self.config_mgr, lambda msg: self.show_toast(msg))

    def copy_url(self):
        url = self.service_url_var.get()
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.show_toast("地址已复制到剪贴板")
            # messagebox.showinfo("提示", "地址已复制到剪贴板")

    def open_browser(self):
        url = self.service_url_var.get()
        if url:
            webbrowser.open(url)
            
    def open_work_dir(self):
        work_dir = get_work_dir()
        if os.path.exists(work_dir):
            try:
                if os.name == 'nt':
                    subprocess.Popen(['explorer', os.path.abspath(work_dir)])
                else:
                    # Fallback for non-Windows (though OS rule says Windows)
                    if sys.platform == 'darwin':
                        subprocess.Popen(['open', work_dir])
                    else:
                        subprocess.Popen(['xdg-open', work_dir])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开目录: {e}")
        else:
            messagebox.showerror("错误", "工作目录不存在")

def _parse_cli_flag_value(argv: list[str], flag_name: str) -> str | None:
    """从命令行参数中解析形如 `--flag value` 的 value。"""
    try:
        idx = argv.index(flag_name)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    val = argv[idx + 1]
    if val.startswith("--"):
        return None
    return val

def _capture_layout_artifacts(tag: str) -> int:
    """启动 GUI 并在多分辨率下截图与生成滚动条验证动图。"""
    try:
        from PIL import Image, ImageGrab
    except Exception as e:
        print(f"Error: Pillow 未安装或不可用，无法截图: {e}")
        return 2

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    def _compute_text_visible_lines(widget: tk.Widget) -> int:
        """基于当前像素高度与字体行高，估算 Text/ScrolledText 可视行数。"""
        try:
            widget.update_idletasks()
            height_px = int(widget.winfo_height() or 0)
        except Exception:
            return 0
        if height_px <= 0:
            return 0

        try:
            pad_y = int(widget.cget("pady") or 0)
        except Exception:
            pad_y = 0

        try:
            font_obj = tkfont.Font(font=widget.cget("font"))
            line_px = int(font_obj.metrics("linespace") or 0)
        except Exception:
            line_px = 0
        if line_px <= 0:
            return 0

        usable_px = max(0, height_px - pad_y * 2)
        return max(0, usable_px // max(1, line_px))

    output_dir = Path(get_base_dir()) / "artifacts" / "gui_layout" / tag
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error: 无法创建产物目录 {output_dir}: {e}")
        return 3

    try:
        root = tk.Tk()
        app = LauncherApp(root)
    except Exception as e:
        print(f"Error: 无法启动 GUI 以生成产物: {e}")
        return 4

    profiles: list[tuple[str, int, int]] = [
        ("default", 1280, 720),
        ("1280x720", 1280, 720),
        ("1366x768", 1366, 768),
        ("1920x1080", 1920, 1080),
    ]

    captured_paths: list[Path] = []
    captured_seed_paths: list[Path] = []
    try:
        try:
            if hasattr(app, "seed_progress_view") and getattr(app, "seed_progress_view", None):
                dummy_tasks = [f"seed_{i:04d}" for i in range(12)]
                dummy_progress: dict[str, tuple[float, int, int]] = {}
                dummy_status: dict[str, str] = {}
                for i, name in enumerate(dummy_tasks):
                    pct = (i * 9) % 101
                    total = 1000
                    processed = int(total * (pct / 100.0))
                    if pct >= 100:
                        pct = 100
                        processed = total
                    dummy_progress[name] = (float(pct), int(processed), int(total))
                    if i % 7 == 0:
                        dummy_status[name] = "failed"
                    elif i % 5 == 0:
                        dummy_status[name] = "retrying"
                    elif pct >= 100:
                        dummy_status[name] = "completed"
                    else:
                        dummy_status[name] = "running"
                app.seed_progress_view.set_state(tasks=dummy_tasks, progress=dummy_progress, packaging=set(), status=dummy_status)
        except Exception:
            pass

        try:
            if hasattr(app, "tree_layers") and getattr(app, "tree_layers", None):
                app.tree_layers.delete(*app.tree_layers.get_children())
                demo_rows = [
                    ("world", "png", "世界底图 (demo)"),
                    ("china", "jpeg", "中国范围 (demo)"),
                    ("city", "webp", "城市级别 (demo)"),
                ]
                for r in demo_rows:
                    try:
                        app.tree_layers.insert("", "end", values=r)
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            if hasattr(app, "log"):
                app.log("[12:00:00] DEBUG 调试信息示例", "DEBUG")
                app.log("[12:00:01] INFO 普通信息示例", "INFO")
                app.log("[12:00:02] SUCCESS 关键信息示例", "SUCCESS")
                app.log("[12:00:03] WARN 警告信息示例", "WARN")
                app.log("[12:00:04] ERROR 错误信息示例", "ERROR")
                app.log("SeedManager [12:00:05] INFO Seed 进度信息示例", "INFO")
                app.log("SeedManager [12:00:06] WARN Seed 警告示例", "WARN")
                app.log("SeedManager [12:00:07] ERROR Seed 错误示例", "ERROR")
        except Exception:
            pass

        screen_w = int(root.winfo_screenwidth() or 0)
        screen_h = int(root.winfo_screenheight() or 0)
        for name, w, h in profiles:
            try:
                target_w = int(w)
                target_h = int(h)
                if screen_w > 0 and screen_h > 0:
                    target_w = min(target_w, max(200, screen_w - 80))
                    target_h = min(target_h, max(200, screen_h - 80))

                root.geometry(f"{target_w}x{target_h}+120+80")
                root.update_idletasks()
                root.update()
                time.sleep(0.25)
                root.update()

                try:
                    app.notebook_log.select(app.tab_system)
                    root.update_idletasks()
                    root.update()
                except Exception:
                    pass

                try:
                    if hasattr(app, "_ensure_log_min_visible_lines"):
                        app._ensure_log_min_visible_lines()
                        root.update_idletasks()
                        root.update()
                except Exception:
                    pass

                try:
                    tab_bbox = app.notebook_log.bbox(0)
                    tab_h = int(tab_bbox[3]) if tab_bbox and len(tab_bbox) >= 4 else 0
                    if tab_h and tab_h < 44:
                        print(f"Warn: Tab 点击区域高度不足 44px: {tab_h}px ({name})")
                except Exception:
                    pass

                try:
                    visible_lines = _compute_text_visible_lines(app.text_log_system)
                    if visible_lines < 6:
                        try:
                            h_px = int(app.text_log_system.winfo_height() or 0)
                        except Exception:
                            h_px = 0
                        try:
                            p_y = int(app.text_log_system.cget("pady") or 0)
                        except Exception:
                            p_y = 0
                        try:
                            f = app.text_log_system.cget("font")
                            fo = tkfont.Font(font=f)
                            l_px = int(fo.metrics("linespace") or 0)
                        except Exception:
                            f = ""
                            l_px = 0
                        print(
                            f"Warn: 日志可视行数不足 6 行: {visible_lines} ({name}) "
                            f"height={h_px}px pady={p_y}px line={l_px}px font={f}"
                        )
                except Exception:
                    pass

                scrollbar_visible = False
                try:
                    scrollbar_visible = bool(app.scrollbar.winfo_ismapped())
                except Exception:
                    scrollbar_visible = False

                suffix = "scrollbar_on" if scrollbar_visible else "scrollbar_off"

                try:
                    x = int(root.winfo_rootx())
                    y = int(root.winfo_rooty())
                    ww = int(root.winfo_width())
                    hh = int(root.winfo_height())
                    if ww <= 0 or hh <= 0:
                        raise RuntimeError(f"窗口尺寸异常: {ww}x{hh}")

                    def _snap(tab_widget: tk.Widget | None, file_key: str) -> Path | None:
                        """切换到指定 tab 并截图。"""
                        try:
                            if tab_widget is not None:
                                app.notebook_log.select(tab_widget)
                                root.update_idletasks()
                                root.update()
                                time.sleep(0.15)
                                root.update()
                        except Exception:
                            return None

                        try:
                            img = ImageGrab.grab(bbox=(x, y, x + ww, y + hh))
                        except Exception:
                            return None

                        out = output_dir / f"{name}_{target_w}x{target_h}_{file_key}_{suffix}.png"
                        try:
                            img.save(out)
                        except Exception:
                            return None
                        return out

                    sys_path = _snap(getattr(app, "tab_system", None), "system")
                    if sys_path:
                        captured_paths.append(sys_path)

                    seed_path = _snap(getattr(app, "tab_seed", None), "seed_monitor")
                    if seed_path:
                        captured_seed_paths.append(seed_path)

                    layers_path = _snap(getattr(app, "tab_layers", None), "layers")
                    if layers_path:
                        captured_seed_paths.append(layers_path)

                    prog_path = _snap(getattr(app, "tab_seed_progress", None), "seed_progress")
                    if prog_path:
                        captured_seed_paths.append(prog_path)
                except Exception:
                    pass
            except Exception as e:
                print(f"Warn: 生成截图失败 ({name}): {e}")

        if captured_paths:
            frames: list[Image.Image] = []
            for p in captured_paths:
                try:
                    frames.append(Image.open(p).convert("RGB"))
                except Exception:
                    continue
            if frames:
                gif_path = output_dir / "scrollbar_check.gif"
                frames[0].save(
                    gif_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=900,
                    loop=0,
                )
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    return 0

def _run_startup_benchmark() -> int:
    """以非 GUI 方式执行一次启动路径，并输出耗时结果（供构建脚本采集）。"""
    import time as _time
    import json as _json

    started = _time.perf_counter()
    output_path = _parse_cli_flag_value(sys.argv, "--benchmark-output")
    try:
        deploy_resources()
        work_dir = get_work_dir()
        os.makedirs(work_dir, exist_ok=True)
        cfg_mgr = ConfigManager(work_dir, get_base_dir())
        cfg_mgr.init_configs()

        elapsed_ms = int((_time.perf_counter() - started) * 1000)
        payload = {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "work_dir": work_dir,
            "base_dir": get_base_dir(),
            "is_frozen": bool(getattr(sys, "frozen", False)),
            "created_at": datetime.now().isoformat(),
        }
    except Exception as e:
        elapsed_ms = int((_time.perf_counter() - started) * 1000)
        payload = {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error": str(e),
            "work_dir": get_work_dir(),
            "base_dir": get_base_dir(),
            "is_frozen": bool(getattr(sys, "frozen", False)),
            "created_at": datetime.now().isoformat(),
        }

    try:
        if not output_path:
            output_path = os.path.join(get_work_dir(), "startup_benchmark.json")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        return 2
    return 0

if __name__ == "__main__":
    # Check for service arguments to avoid launching GUI when running as service
    if "--service" in sys.argv:
        if main:
            server = main.MapProxyServer()
            server.run()
            sys.exit(0)
        else:
            print("Error: main module not found.")
            sys.exit(1)

    if "--capture-layout" in sys.argv:
        tag = _parse_cli_flag_value(sys.argv, "--tag") or datetime.now().strftime("%Y%m%d_%H%M%S")
        raise SystemExit(_capture_layout_artifacts(tag))

    if "--benchmark-startup" in sys.argv:
        raise SystemExit(_run_startup_benchmark())

    try:
        # High DPI support
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    cleanup_empty_legacy_launcher_dir_in_cwd(LAUNCHER_DIR_NAME, "Launcher")
        
    try:
        root = tk.Tk()
        app = LauncherApp(root)
        root.mainloop()
    except Exception as e:
        # Log crash to file in the same directory as executable
        import traceback
        error_msg = f"Application crashed:\n{str(e)}\n\n{traceback.format_exc()}"
        
        try:
            # Try to determine a safe place to log
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            log_path = os.path.join(base_dir, "launcher_crash.log")
            
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(error_msg)
                
            # Try to show message box if possible
            import tkinter.messagebox
            # If root exists but mainloop failed
            if 'root' not in locals():
                root = tk.Tk()
                root.withdraw()
            tkinter.messagebox.showerror("Fatal Error", f"Application crashed. See launcher_crash.log for details.\n\n{str(e)}")
        except:
            pass # Failed to log or show message

