import tkinter as tk
from tkinter import ttk, messagebox
import copy
import json
import os
from datetime import datetime
from src.ui.ui_utils import block_main_interaction, unblock_main_interaction

class AdvancedSettingsDialog:
    def __init__(self, parent, config_mgr, on_save_callback):
        self.parent = parent
        self.top = tk.Toplevel(parent)
        self._fade_after_id = None
        self._stabilize_after_id = None
        self._dialog_shown = False
        self._alpha_supported = True
        self.top.withdraw()
        self.top.title("高级设置")
        
        self.config_mgr = config_mgr
        self.on_save_callback = on_save_callback
        
        self.map_config = self._load_map_config_with_recovery()
        self.advanced_config = self.map_config.get("advanced_settings", {})
        self.system_config = self.map_config.get("system", {})
        self.sources_config = self.map_config.get("sources", {})
        self.features_config = self.map_config.get("features", {})
        
        self.init_vars()
        self.initial_config = self.get_current_settings()
        
        self.create_widgets()

        self.show_dialog()
        
        block_main_interaction(self.parent, self.top)
        
        self.top.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def _show_recoverable_warning(self, title, message):
        try:
            messagebox.showwarning(
                title,
                f"{message}\n\n已切换到可恢复模式，当前窗口不会关闭，您可以继续编辑并稍后重试保存。",
                parent=self.top,
            )
        except Exception:
            pass

    def _build_fallback_map_config(self):
        try:
            fallback = self.config_mgr._build_map_config_from_legacy()
            if isinstance(fallback, dict):
                return fallback
        except Exception:
            pass
        advanced_defaults = {}
        try:
            advanced_defaults = self.config_mgr.get_default_advanced_config()
        except Exception:
            advanced_defaults = {"concurrency": 4, "retry": {"enabled": False, "max_retries": 2, "interval": 5}, "alert": {"enabled": False}}
        return {
            "version": 2,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "system": {"port": 8080},
            "advanced_settings": advanced_defaults,
            "sources": {},
            "features": {"smart_switch": False, "offline_mode": True, "cache_dir": "./cache_data"},
            "seeding": {"tasks": []},
        }

    def _load_map_config_with_recovery(self):
        map_config_path = getattr(self.config_mgr, "map_config_path", "")
        precheck_error = None
        if isinstance(map_config_path, str) and map_config_path and os.path.exists(map_config_path):
            try:
                with open(map_config_path, "r", encoding="utf-8") as file:
                    json.load(file)
            except Exception as exc:
                precheck_error = exc
        try:
            loaded = self.config_mgr.load_map_config()
            if not isinstance(loaded, dict):
                raise ValueError("map_config.json 数据结构无效")
        except Exception as exc:
            self._show_recoverable_warning("配置读取失败", f"读取 map_config.json 失败：{exc}")
            return self._build_fallback_map_config()
        if precheck_error is not None:
            self._show_recoverable_warning("配置已回退", f"检测到 map_config.json 解析异常，已自动回退至可用配置：{precheck_error}")
        return loaded

    def _set_alpha(self, alpha):
        """设置窗口透明度，失败时返回 False。"""
        try:
            self.top.attributes("-alpha", float(alpha))
            return True
        except Exception:
            return False

    def _show_dialog_fallback(self):
        """兜底显示窗口，保证最终可见且可交互。"""
        self._cancel_fade_animation()
        try:
            self.top.deiconify()
        except Exception:
            pass
        self._set_alpha(1.0)
        try:
            self.top.lift()
        except Exception:
            pass

    def _cancel_fade_animation(self):
        """取消淡入与稳定阶段调度，避免重复动画叠加。"""
        if self._fade_after_id is not None:
            try:
                self.top.after_cancel(self._fade_after_id)
            except Exception:
                pass
            self._fade_after_id = None
        if self._stabilize_after_id is not None:
            try:
                self.top.after_cancel(self._stabilize_after_id)
            except Exception:
                pass
            self._stabilize_after_id = None

    def _read_alpha(self):
        """读取当前透明度，失败时返回 None。"""
        try:
            alpha = self.top.attributes("-alpha")
        except Exception:
            return None
        try:
            return float(alpha)
        except Exception:
            return None

    def _safe_int(self, value, default=0):
        """将输入安全转换为整数，失败时返回默认值。"""
        try:
            return int(value)
        except Exception:
            return int(default)

    def _measure_dialog_size(self):
        """按请求尺寸与基线尺寸计算弹窗最终尺寸。"""
        try:
            self.top.update_idletasks()
        except Exception:
            pass

        req_w = self._safe_int(self.top.winfo_reqwidth(), 0)
        req_h = self._safe_int(self.top.winfo_reqheight(), 0)

        width = max(650, req_w)
        height = max(500, req_h)
        return width, height

    def _get_virtual_bounds(self):
        """读取虚拟桌面边界，用于多显示器与窗口管理器差异下的安全定位。"""
        try:
            self.parent.update_idletasks()
        except Exception:
            pass

        screen_w = self._safe_int(self.parent.winfo_screenwidth(), 0)
        screen_h = self._safe_int(self.parent.winfo_screenheight(), 0)

        v_x = self._safe_int(getattr(self.parent, "winfo_vrootx", lambda: 0)(), 0)
        v_y = self._safe_int(getattr(self.parent, "winfo_vrooty", lambda: 0)(), 0)
        v_w = self._safe_int(getattr(self.parent, "winfo_vrootwidth", lambda: screen_w)(), screen_w)
        v_h = self._safe_int(getattr(self.parent, "winfo_vrootheight", lambda: screen_h)(), screen_h)

        if v_w <= 0:
            v_w = max(1, screen_w)
        if v_h <= 0:
            v_h = max(1, screen_h)
        return v_x, v_y, v_w, v_h

    def _build_centered_geometry(self, width, height):
        """基于父窗口中心和虚拟桌面边界生成几何参数。"""
        parent_x = self._safe_int(self.parent.winfo_rootx(), 0)
        parent_y = self._safe_int(self.parent.winfo_rooty(), 0)
        parent_w = self._safe_int(self.parent.winfo_width(), 0)
        parent_h = self._safe_int(self.parent.winfo_height(), 0)

        v_x, v_y, v_w, v_h = self._get_virtual_bounds()

        if parent_w <= 1 or parent_h <= 1:
            center_x = v_x + v_w // 2
            center_y = v_y + v_h // 2
        else:
            center_x = parent_x + parent_w // 2
            center_y = parent_y + parent_h // 2

        x = center_x - (width // 2)
        y = center_y - (height // 2)

        min_x = v_x
        min_y = v_y
        max_x = v_x + max(0, v_w - width)
        max_y = v_y + max(0, v_h - height)

        if x < min_x:
            x = min_x
        if y < min_y:
            y = min_y
        if x > max_x:
            x = max_x
        if y > max_y:
            y = max_y

        return int(width), int(height), int(x), int(y)

    def _position_hidden_dialog(self):
        """在可见前完成尺寸测量与居中定位。"""
        width, height = self._measure_dialog_size()
        width, height, x, y = self._build_centered_geometry(width, height)
        self.top.geometry(f"{width}x{height}+{x}+{y}")
        self.top.minsize(550, 450)

    def _build_centered_child_geometry(self, width, height):
        """基于高级设置面板当前几何信息计算子弹窗居中位置。"""
        dialog_x = self._safe_int(self.top.winfo_rootx(), 0)
        dialog_y = self._safe_int(self.top.winfo_rooty(), 0)
        dialog_w = self._safe_int(self.top.winfo_width(), 0)
        dialog_h = self._safe_int(self.top.winfo_height(), 0)

        if dialog_w <= 1 or dialog_h <= 1:
            return self._build_centered_geometry(width, height)

        center_x = dialog_x + dialog_w // 2
        center_y = dialog_y + dialog_h // 2
        x = center_x - (width // 2)
        y = center_y - (height // 2)

        v_x, v_y, v_w, v_h = self._get_virtual_bounds()
        min_x = v_x
        min_y = v_y
        max_x = v_x + max(0, v_w - width)
        max_y = v_y + max(0, v_h - height)

        if x < min_x:
            x = min_x
        if y < min_y:
            y = min_y
        if x > max_x:
            x = max_x
        if y > max_y:
            y = max_y
        return int(width), int(height), int(x), int(y)

    def _ask_cancel_confirmation(self):
        """显示跟随高级设置面板居中的取消确认框，失败时回退系统确认框。"""
        confirm_top = None
        try:
            confirm_top = tk.Toplevel(self.top)
            confirm_top.withdraw()
            confirm_top.title("确认")
            confirm_top.resizable(False, False)
            confirm_top.transient(self.top)

            body = ttk.Frame(confirm_top, padding=(18, 14))
            body.pack(fill=tk.BOTH, expand=True)
            ttk.Label(body, text="有未保存的更改，确定要取消吗？").pack(anchor=tk.W)

            result = {"confirmed": False}

            def _resolve(value):
                result["confirmed"] = bool(value)
                try:
                    confirm_top.grab_release()
                except Exception:
                    pass
                confirm_top.destroy()

            actions = ttk.Frame(body, padding=(0, 12, 0, 0))
            actions.pack(fill=tk.X)
            ttk.Button(actions, text="是", command=lambda: _resolve(True), width=8).pack(side=tk.RIGHT, padx=(8, 0))
            ttk.Button(actions, text="否", command=lambda: _resolve(False), width=8).pack(side=tk.RIGHT)

            confirm_top.protocol("WM_DELETE_WINDOW", lambda: _resolve(False))
            confirm_top.update_idletasks()
            req_w = self._safe_int(confirm_top.winfo_reqwidth(), 320)
            req_h = self._safe_int(confirm_top.winfo_reqheight(), 130)
            width = max(320, req_w)
            height = max(130, req_h)
            width, height, x, y = self._build_centered_child_geometry(width, height)
            confirm_top.geometry(f"{width}x{height}+{x}+{y}")
            confirm_top.deiconify()
            confirm_top.lift()
            confirm_top.grab_set()
            confirm_top.focus_force()
            confirm_top.wait_window()
            return result["confirmed"]
        except Exception:
            if confirm_top is not None:
                try:
                    confirm_top.destroy()
                except Exception:
                    pass
            return messagebox.askyesno("确认", "有未保存的更改，确定要取消吗？", parent=self.top)

    def _stabilize_and_fade_in(self):
        """在映射后执行一次无感重定位，再启动淡入动画。"""
        self._stabilize_after_id = None
        try:
            self.top.update_idletasks()
            width = self._safe_int(self.top.winfo_width(), 0)
            height = self._safe_int(self.top.winfo_height(), 0)
            if width <= 1 or height <= 1:
                width, height = self._measure_dialog_size()
            width, height, x, y = self._build_centered_geometry(width, height)
            self.top.geometry(f"{width}x{height}+{x}+{y}")
            self.top.update_idletasks()
            self.fade_in()
        except Exception:
            self._show_dialog_fallback()

    def show_dialog(self):
        """按单向时序执行弹框显示：布局、定位、显示、淡入。"""
        if self._dialog_shown:
            return
        self._dialog_shown = True
        try:
            self._cancel_fade_animation()
            self.top.withdraw()
            self._alpha_supported = self._set_alpha(0.0)
            self._position_hidden_dialog()
            try:
                self.top.transient(self.parent)
            except Exception:
                pass
            self.top.deiconify()
            self.top.lift()
            if self._alpha_supported:
                self._stabilize_after_id = self.top.after_idle(self._stabilize_and_fade_in)
            else:
                self._show_dialog_fallback()
        except Exception:
            self._show_dialog_fallback()

    def fade_in(self, alpha=None):
        """
        实现窗口淡入动画效果
        """
        self._fade_after_id = None
        if not self._alpha_supported:
            self._show_dialog_fallback()
            return

        current_alpha = self._read_alpha()
        try:
            alpha_value = float(alpha) if alpha is not None else None
        except Exception:
            alpha_value = None
        base_alpha = current_alpha if current_alpha is not None else alpha_value
        if base_alpha is None:
            base_alpha = 0.0
        if base_alpha < 0.0:
            base_alpha = 0.0
        if base_alpha > 1.0:
            base_alpha = 1.0

        next_alpha = min(1.0, float(base_alpha) + 0.1)
        if not self._set_alpha(next_alpha):
            self._alpha_supported = False
            self._show_dialog_fallback()
            return

        if next_alpha < 1.0:
            self._fade_after_id = self.top.after(20, self.fade_in, next_alpha)
        else:
            self._fade_after_id = None

    def init_vars(self):
        """初始化变量"""
        # 性能与基础
        self.concurrency_var = tk.IntVar(value=self.advanced_config.get("concurrency", 4))
        
        retry_cfg = self.advanced_config.get("retry", {})
        self.retry_enabled_var = tk.BooleanVar(value=retry_cfg.get("enabled", False))
        self.max_retries_var = tk.IntVar(value=retry_cfg.get("max_retries", 2))
        self.retry_interval_var = tk.IntVar(value=retry_cfg.get("interval", 5))
        
        alert_cfg = self.advanced_config.get("alert", {})
        self.alert_enabled_var = tk.BooleanVar(value=alert_cfg.get("enabled", False))

        # 地图源与功能
        default_global = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%(z)s/%(y)s/%(x)s"
        self.global_url_var = tk.StringVar(value=self.sources_config.get("global_url", default_global))
        self.china_url_var = tk.StringVar(value=self.sources_config.get("china_url", ""))
        self.smart_switch_var = tk.BooleanVar(value=self.features_config.get("smart_switch", False))
        self.offline_mode_var = tk.BooleanVar(value=self.features_config.get("offline_mode", True))
        self.cache_dir_var = tk.StringVar(value=self.features_config.get("cache_dir", "./cache_data"))
        self.seeding_tasks = self._normalize_seeding_tasks(self.map_config.get("seeding", {}).get("tasks"))
        self.seed_task_tree = None
        self.btn_seed_edit = None
        self.btn_seed_delete = None
        self.btn_seed_copy = None
        self.btn_seed_move_up = None
        self.btn_seed_move_down = None

    def close(self):
        """Close dialog and re-enable parent"""
        self._cancel_fade_animation()
        unblock_main_interaction(self.parent, self.top)
        self.top.destroy()
        
    def center_window(self):
        """居中窗口"""
        self._position_hidden_dialog()

    def _extract_font_size(self, font_value, default_size):
        """从字体定义中提取字号，失败时回退到默认值。"""
        try:
            if isinstance(font_value, (tuple, list)) and len(font_value) >= 2:
                size = int(font_value[1])
                if size != 0:
                    return size
        except Exception:
            pass
        return int(default_size)

    def _resolve_shared_font_sizes(self):
        """解析与主面板一致的基础字号与标题字号。"""
        default_size = -16
        body_size = default_size
        title_size = default_size
        ui_fonts = getattr(self.parent, "_ui_fonts", {})
        if isinstance(ui_fonts, dict):
            body_size = self._extract_font_size(ui_fonts.get("body"), default_size)
            title_size = self._extract_font_size(
                ui_fonts.get("title"),
                self._extract_font_size(ui_fonts.get("subtitle"), body_size),
            )
        return int(body_size), int(title_size)

    def _build_visual_tokens(self):
        base_font_size, title_font_size = self._resolve_shared_font_sizes()
        self._visual_tokens = {
            "font_family": "Microsoft YaHei",
            "base_font_size": base_font_size,
            "title_font_size": title_font_size,
            "bg_base": "#F5F7FA",
            "bg_surface": "#FFFFFF",
            "bg_surface_alt": "#F8FAFD",
            "border": "#D6DAE1",
            "text_primary": "#111111",
            "text_secondary": "#4C5565",
            "menu_selected_bg": "#E7F0FF",
            "menu_selected_border": "#8AB4F8",
            "menu_selected_text": "#0B3D91",
            "menu_hover_bg": "#EEF3FB",
            "spacing_outer": 10,
            "spacing_inner": 8,
            "menu_inner_pad_x": 10,
            "menu_inner_pad_y": 10,
            "menu_item_select_border": 1,
            "menu_width": 170,
            "content_gap": 0,
            "splitter_width": 1,
        }

    def _configure_dialog_styles(self):
        tokens = getattr(self, "_visual_tokens", {})
        style = ttk.Style(self.top)
        try:
            style.configure(
                "AdvancedSettings.Base.TFrame",
                background=tokens.get("bg_base", "#F5F7FA"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.Surface.TFrame",
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.Card.TLabelframe",
                relief="solid",
                borderwidth=1,
                background=tokens.get("bg_surface", "#FFFFFF"),
                foreground=tokens.get("text_primary", "#111111"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.Card.TLabelframe.Label",
                font=(
                    tokens.get("font_family", "Microsoft YaHei"),
                    tokens.get("title_font_size", 11),
                    "bold",
                ),
                foreground=tokens.get("text_secondary", "#4C5565"),
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.Title.TLabel",
                font=(
                    tokens.get("font_family", "Microsoft YaHei"),
                    tokens.get("title_font_size", 11),
                    "bold",
                ),
                foreground=tokens.get("text_primary", "#111111"),
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.Subtitle.TLabel",
                font=(
                    tokens.get("font_family", "Microsoft YaHei"),
                    tokens.get("base_font_size", 10),
                    "normal",
                ),
                foreground=tokens.get("text_secondary", "#4C5565"),
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.CardText.TLabel",
                font=(
                    tokens.get("font_family", "Microsoft YaHei"),
                    tokens.get("base_font_size", 10),
                    "normal",
                ),
                foreground=tokens.get("text_primary", "#111111"),
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
        except Exception:
            pass
        try:
            style.configure(
                "AdvancedSettings.CardCheck.TCheckbutton",
                font=(
                    tokens.get("font_family", "Microsoft YaHei"),
                    tokens.get("base_font_size", 10),
                    "normal",
                ),
                foreground=tokens.get("text_primary", "#111111"),
                background=tokens.get("bg_surface", "#FFFFFF"),
            )
            style.map(
                "AdvancedSettings.CardCheck.TCheckbutton",
                background=[
                    ("active", tokens.get("bg_surface", "#FFFFFF")),
                    ("selected", tokens.get("bg_surface", "#FFFFFF")),
                    ("!disabled", tokens.get("bg_surface", "#FFFFFF")),
                ],
                foreground=[
                    ("disabled", tokens.get("text_secondary", "#4C5565")),
                    ("!disabled", tokens.get("text_primary", "#111111")),
                ],
            )
        except Exception:
            pass

    def _apply_menu_item_state(self, selected_index):
        tokens = getattr(self, "_visual_tokens", {})
        menu_count = 0
        try:
            menu_count = int(self.menu_listbox.size())
        except Exception:
            menu_count = 0
        for idx in range(menu_count):
            is_selected = idx == selected_index
            bg = tokens.get("bg_surface_alt", "#F8FAFD")
            fg = tokens.get("text_secondary", "#4C5565")
            if is_selected:
                bg = tokens.get("menu_selected_bg", "#E7F0FF")
                fg = tokens.get("menu_selected_text", "#0B3D91")
            try:
                self.menu_listbox.itemconfig(idx, background=bg, foreground=fg)
            except Exception:
                pass

    def create_widgets(self):
        """创建界面组件"""
        self._build_visual_tokens()
        self._configure_dialog_styles()
        tokens = self._visual_tokens

        try:
            self.top.configure(background=tokens["bg_base"])
        except Exception:
            pass

        main_frame = ttk.Frame(
            self.top,
            padding=str(tokens["spacing_outer"]),
            style="AdvancedSettings.Base.TFrame",
        )
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(tokens["spacing_outer"], 0))
        
        ttk.Button(btn_frame, text="保存", command=self.save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="还原默认值", command=self.restore_defaults).pack(side=tk.LEFT, padx=5)

        content_frame = ttk.Frame(main_frame, style="AdvancedSettings.Base.TFrame")
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        content_shell = tk.Frame(
            content_frame,
            bg=tokens["bg_surface"],
            highlightbackground=tokens["border"],
            highlightthickness=0,
            bd=0,
        )
        content_shell.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(
            content_shell,
            width=tokens["menu_width"],
            bg=tokens["bg_surface"],
            bd=0,
        )
        left_frame.pack(
            side=tk.LEFT,
            fill=tk.Y,
            padx=(0, tokens["content_gap"]),
            pady=0,
        )
        left_frame.pack_propagate(False)

        self.menu_listbox = tk.Listbox(
            left_frame,
            selectmode=tk.SINGLE,
            font=(tokens["font_family"], tokens["base_font_size"]),
            activestyle="none",
            exportselection=False,
            bd=0,
            relief=tk.FLAT,
            selectborderwidth=tokens["menu_item_select_border"],
            highlightthickness=0,
            background=tokens["bg_surface"],
            foreground=tokens["text_secondary"],
            selectbackground=tokens["menu_selected_bg"],
            selectforeground=tokens["menu_selected_text"],
            disabledforeground=tokens["text_secondary"],
            justify=tk.LEFT,
        )
        self.menu_listbox.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
            padx=tokens["menu_inner_pad_x"],
            pady=tokens["menu_inner_pad_y"],
        )

        splitter = tk.Frame(
            content_shell,
            bg=tokens["border"],
            width=tokens["splitter_width"],
            bd=0,
            highlightthickness=0,
        )
        splitter.pack(side=tk.LEFT, fill=tk.Y)

        self.right_frame = tk.Frame(
            content_shell,
            bg=tokens["bg_surface"],
            bd=0,
        )
        self.right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_header = tk.Frame(self.right_frame, bg=tokens["bg_surface"], bd=0)
        self.right_header.pack(fill=tk.X)
        self.right_title_var = tk.StringVar(value="")
        ttk.Label(
            self.right_header,
            textvariable=self.right_title_var,
            style="AdvancedSettings.Title.TLabel",
        ).pack(side=tk.TOP, anchor=tk.W, padx=12, pady=(10, 0))

        self.right_panel_container = tk.Frame(self.right_frame, bg=tokens["bg_surface"], bd=0)
        self.right_panel_container.pack(fill=tk.BOTH, expand=True)

        self.panels = {}

        self.menu_listbox.insert(tk.END, "性能与基础")
        panel_perf = tk.Frame(self.right_panel_container, bg=tokens["bg_surface"], bd=0)
        self.create_perf_tab(panel_perf)
        self.panels["性能与基础"] = panel_perf

        self.menu_listbox.insert(tk.END, "地图源与功能")
        panel_map = tk.Frame(self.right_panel_container, bg=tokens["bg_surface"], bd=0)
        self.create_map_tab(panel_map)
        self.panels["地图源与功能"] = panel_map

        self.menu_listbox.insert(tk.END, "图层切片")
        panel_layer_seeding = tk.Frame(self.right_panel_container, bg=tokens["bg_surface"], bd=0)
        self.create_layer_seeding_tab(panel_layer_seeding)
        self.panels["图层切片"] = panel_layer_seeding

        self.menu_listbox.bind("<<ListboxSelect>>", self.on_menu_select)
        self.menu_listbox.bind("<Button-1>", self._on_menu_click)
        self.menu_listbox.bind("<Motion>", self._on_menu_hover)
        self.menu_listbox.bind("<Leave>", self._on_menu_leave)

        self.menu_listbox.selection_set(0)
        self.on_menu_select(None)

    def _on_menu_hover(self, event):
        tokens = getattr(self, "_visual_tokens", {})
        index = self._resolve_menu_hit_index(event)
        if index is None:
            return
        try:
            index = int(index)
        except Exception:
            return
        selected = self.menu_listbox.curselection()
        selected_index = selected[0] if selected else -1
        if index == selected_index:
            return
        try:
            self.menu_listbox.itemconfig(
                index,
                background=tokens.get("menu_hover_bg", "#EEF3FB"),
                foreground=tokens.get("text_primary", "#111111"),
            )
        except Exception:
            return

    def _resolve_menu_hit_index(self, event):
        try:
            event_y = int(getattr(event, "y"))
        except Exception:
            return None
        try:
            index = int(self.menu_listbox.nearest(event_y))
        except Exception:
            return None
        try:
            menu_count = int(self.menu_listbox.size())
        except Exception:
            return None
        if index < 0 or index >= menu_count:
            return None
        try:
            bbox = self.menu_listbox.bbox(index)
        except Exception:
            bbox = None
        if not bbox or len(bbox) < 4:
            return None
        try:
            item_x = int(bbox[0])
            item_y = int(bbox[1])
            item_w = int(bbox[2])
            item_h = int(bbox[3])
            event_x = int(getattr(event, "x"))
        except Exception:
            return None
        if event_x < item_x or event_x >= (item_x + item_w):
            return None
        if event_y < item_y or event_y >= (item_y + item_h):
            return None
        return index

    def _on_menu_click(self, event):
        if self._resolve_menu_hit_index(event) is None:
            return "break"

    def _on_menu_leave(self, _event):
        selection = self.menu_listbox.curselection()
        selected_index = selection[0] if selection else -1
        self._apply_menu_item_state(selected_index)

    def on_menu_select(self, event):
        """处理左侧菜单选择事件，切换右侧面板"""
        selection = self.menu_listbox.curselection()
        if not selection:
            return
            
        selected_text = self.menu_listbox.get(selection[0])
        self.right_title_var.set(selected_text)
        self._apply_menu_item_state(selection[0])
        
        for panel in self.panels.values():
            panel.pack_forget()
            
        if selected_text in self.panels:
            self.panels[selected_text].pack(fill=tk.BOTH, expand=True)

    def create_perf_tab(self, parent):
        """创建性能与基础选项卡"""
        grp_seed = ttk.LabelFrame(parent, text="Seed 服务管理配置", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_seed.pack(fill=tk.X, pady=6)
        
        ttk.Label(grp_seed, text="并发进程数 (1-16):", style="AdvancedSettings.CardText.TLabel").grid(row=0, column=0, sticky=tk.W, pady=5)
        sp_conc = ttk.Spinbox(grp_seed, from_=1, to=16, textvariable=self.concurrency_var, width=10)
        sp_conc.grid(row=0, column=1, padx=10, sticky=tk.W, pady=5)
        
        grp_retry = ttk.LabelFrame(parent, text="失败重试策略", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_retry.pack(fill=tk.X, pady=6)
        
        ttk.Checkbutton(grp_retry, text="启用自动重试", variable=self.retry_enabled_var, style="AdvancedSettings.CardCheck.TCheckbutton").grid(row=0, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(grp_retry, text="最大重试次数:", style="AdvancedSettings.CardText.TLabel").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=10, textvariable=self.max_retries_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(grp_retry, text="重试间隔 (秒):", style="AdvancedSettings.CardText.TLabel").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=60, textvariable=self.retry_interval_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        grp_alert = ttk.LabelFrame(parent, text="失败告警配置", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_alert.pack(fill=tk.X, pady=6)
        
        ttk.Checkbutton(grp_alert, text="启用失败告警", variable=self.alert_enabled_var, style="AdvancedSettings.CardCheck.TCheckbutton").grid(row=0, column=0, sticky=tk.W)

    def create_map_tab(self, parent):
        """创建地图源与功能选项卡"""
        grp_src = ttk.LabelFrame(parent, text="地图源配置", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_src.pack(fill=tk.X, pady=6)

        ttk.Label(grp_src, text="Global URL:", style="AdvancedSettings.CardText.TLabel").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_src, textvariable=self.global_url_var, width=50).grid(row=0, column=1, sticky=tk.W, padx=10)

        ttk.Label(grp_src, text="China URL:", style="AdvancedSettings.CardText.TLabel").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_src, textvariable=self.china_url_var, width=50).grid(row=1, column=1, sticky=tk.W, padx=10)

        grp_feat = ttk.LabelFrame(parent, text="地图功能配置", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_feat.pack(fill=tk.X, pady=6)

        ttk.Checkbutton(grp_feat, text="启用智能切换 (国内天地图，国外Global)", variable=self.smart_switch_var, style="AdvancedSettings.CardCheck.TCheckbutton").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        ttk.Label(grp_feat, text="seed数据类型:", style="AdvancedSettings.CardText.TLabel").grid(row=1, column=0, sticky=tk.W, pady=5)
        radio_frame = ttk.Frame(grp_feat)
        radio_frame.grid(row=1, column=1, sticky=tk.W, padx=10)
        ttk.Radiobutton(radio_frame, text="Tile(多文件)", variable=self.offline_mode_var, value=False).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(radio_frame, text="MBTiles(单文件)", variable=self.offline_mode_var, value=True).pack(side=tk.LEFT)

        ttk.Label(grp_feat, text="数据缓存根目录:", style="AdvancedSettings.CardText.TLabel").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_feat, textvariable=self.cache_dir_var, width=50).grid(row=2, column=1, sticky=tk.W, padx=10)

    def create_layer_seeding_tab(self, parent):
        """创建图层切片选项卡"""
        grp_seed = ttk.LabelFrame(parent, text="图层切片任务管理", padding="16", style="AdvancedSettings.Card.TLabelframe")
        grp_seed.pack(fill=tk.BOTH, expand=True, pady=6)
        grp_seed.columnconfigure(0, weight=1)
        grp_seed.columnconfigure(1, weight=0)
        grp_seed.columnconfigure(2, weight=1)
        grp_seed.rowconfigure(1, weight=1)

        ttk.Label(
            grp_seed,
            text="请在左侧待选列表中选择预设任务，点击添加即可加入到右侧已选任务中。",
            style="AdvancedSettings.CardText.TLabel",
            wraplength=650,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        # 预设任务列表
        self._preset_tasks = [
            {"label": "全球0-5", "name": "global_low_zoom", "zoom_levels": [0, 5], "bbox": [-180.0, -90.0, 180.0, 90.0]},
            {"label": "中国6-10", "name": "china_mid_zoom", "zoom_levels": [6, 10], "bbox": [73.0, 18.0, 135.0, 54.0]},
            {"label": "中国11-15", "name": "china_high_zoom", "zoom_levels": [11, 15], "bbox": [73.0, 18.0, 135.0, 54.0]},
            {"label": "北京市", "name": "china_beijing", "zoom_levels": [16, 18], "bbox": [115.4, 39.4, 117.5, 41.1]},
            {"label": "天津市", "name": "china_tianjin", "zoom_levels": [16, 18], "bbox": [116.7, 38.5, 118.1, 40.3]},
            {"label": "河北省", "name": "china_hebei", "zoom_levels": [16, 18], "bbox": [113.4, 36.0, 119.9, 42.7]},
            {"label": "山西省", "name": "china_shanxi", "zoom_levels": [16, 18], "bbox": [110.2, 34.5, 114.6, 40.8]},
            {"label": "内蒙古自治区", "name": "china_neimenggu", "zoom_levels": [16, 18], "bbox": [97.1, 37.4, 126.1, 53.4]},
            {"label": "辽宁省", "name": "china_liaoning", "zoom_levels": [16, 18], "bbox": [118.8, 38.7, 125.8, 43.5]},
            {"label": "吉林省", "name": "china_jilin", "zoom_levels": [16, 18], "bbox": [118.8, 38.7, 131.3, 46.3]},
            {"label": "黑龙江省", "name": "china_heilongjiang", "zoom_levels": [16, 18], "bbox": [121.1, 43.4, 135.1, 53.6]},
            {"label": "上海市", "name": "china_shanghai", "zoom_levels": [16, 18], "bbox": [120.8, 30.6, 122.2, 31.9]},
            {"label": "江苏省", "name": "china_jiangsu", "zoom_levels": [16, 18], "bbox": [116.3, 30.7, 121.9, 35.1]},
            {"label": "浙江省", "name": "china_zhejiang", "zoom_levels": [16, 18], "bbox": [118.0, 27.0, 123.0, 31.2]},
            {"label": "安徽省", "name": "china_anhui", "zoom_levels": [16, 18], "bbox": [114.8, 29.3, 119.7, 34.7]},
            {"label": "福建省", "name": "china_fujian", "zoom_levels": [16, 18], "bbox": [115.8, 23.5, 120.5, 28.5]},
            {"label": "江西省", "name": "china_jiangxi", "zoom_levels": [16, 18], "bbox": [113.5, 24.4, 118.5, 30.1]},
            {"label": "山东省", "name": "china_shandong", "zoom_levels": [16, 18], "bbox": [114.7, 34.3, 122.7, 38.4]},
            {"label": "河南省", "name": "china_henan", "zoom_levels": [16, 18], "bbox": [114.7, 31.3, 122.7, 38.4]},
            {"label": "湖北省", "name": "china_hubei", "zoom_levels": [16, 18], "bbox": [108.3, 29.0, 116.1, 33.3]},
            {"label": "湖南省", "name": "china_hunan", "zoom_levels": [16, 18], "bbox": [108.7, 24.6, 114.3, 30.1]},
            {"label": "广东省", "name": "china_guangdong", "zoom_levels": [16, 18], "bbox": [109.6, 20.2, 117.3, 25.5]},
            {"label": "广西壮族自治区", "name": "china_guangxi", "zoom_levels": [16, 18], "bbox": [104.4, 20.2, 112.1, 26.4]},
            {"label": "海南省", "name": "china_hainan", "zoom_levels": [16, 18], "bbox": [108.6, 18.1, 117.3, 25.5]},
            {"label": "重庆市", "name": "china_chongqing", "zoom_levels": [16, 18], "bbox": [105.2, 28.1, 110.2, 32.3]},
            {"label": "四川省", "name": "china_sichuan", "zoom_levels": [16, 18], "bbox": [97.3, 26.0, 108.5, 34.3]},
            {"label": "贵州省", "name": "china_guizhou", "zoom_levels": [16, 18], "bbox": [104.4, 24.6, 110.0, 29.2]},
            {"label": "云南省", "name": "china_yunnan", "zoom_levels": [16, 18], "bbox": [103.5, 21.1, 109.6, 29.2]},
            {"label": "西藏自治区", "name": "china_xizang", "zoom_levels": [16, 18], "bbox": [97.5, 21.1, 106.2, 29.2]},
            {"label": "陕西省", "name": "china_shaanxi", "zoom_levels": [16, 18], "bbox": [105.4, 31.7, 111.2, 39.6]},
            {"label": "甘肃省", "name": "china_gansu", "zoom_levels": [16, 18], "bbox": [92.3, 32.5, 108.7, 42.8]},
            {"label": "青海省", "name": "china_qinghai", "zoom_levels": [16, 18], "bbox": [89.1, 31.6, 108.7, 42.8]},
            {"label": "宁夏回族自治区", "name": "china_ningxia", "zoom_levels": [16, 18], "bbox": [94.1, 35.2, 107.6, 39.3]},
            {"label": "新疆维吾尔自治区", "name": "china_xinjiang", "zoom_levels": [16, 18], "bbox": [73.4, 34.3, 96.4, 49.2]},
            {"label": "台湾省", "name": "china_taiwan", "zoom_levels": [16, 18], "bbox": [119.2, 21.8, 122.1, 25.4]},
            {"label": "香港特别行政区", "name": "china_hongkong", "zoom_levels": [16, 18], "bbox": [113.8, 22.1, 114.4, 22.6]},
            {"label": "澳门特别行政区", "name": "china_macau", "zoom_levels": [16, 18], "bbox": [113.5, 22.1, 113.6, 22.2]},
        ]

        # 左侧待选列表
        left_frame = ttk.Frame(grp_seed)
        left_frame.grid(row=1, column=0, sticky="nsew")
        ttk.Label(left_frame, text="待选任务").pack(anchor=tk.W, pady=(0, 4))
        
        self.listbox_available = tk.Listbox(left_frame, selectmode=tk.SINGLE, height=15)
        self.listbox_available.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_avail = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.listbox_available.yview)
        self.listbox_available.configure(yscrollcommand=scroll_avail.set)
        scroll_avail.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox_available.bind("<<ListboxSelect>>", self._on_shuttle_selection_changed)
        self.listbox_available.bind("<Double-1>", lambda _event: self._add_seed_task())

        # 中间操作按钮
        mid_frame = ttk.Frame(grp_seed)
        mid_frame.grid(row=1, column=1, padx=10, sticky="n")
        self.btn_shuttle_add = ttk.Button(mid_frame, text="添加 >>", command=self._add_seed_task, state=tk.DISABLED)
        self.btn_shuttle_add.pack(pady=(40, 10))
        self.btn_shuttle_remove = ttk.Button(mid_frame, text="<< 移除", command=self._remove_seed_task, state=tk.DISABLED)
        self.btn_shuttle_remove.pack()

        # 右侧已选列表
        right_frame = ttk.Frame(grp_seed)
        right_frame.grid(row=1, column=2, sticky="nsew")
        ttk.Label(right_frame, text="已选任务").pack(anchor=tk.W, pady=(0, 4))
        
        self.listbox_selected = tk.Listbox(right_frame, selectmode=tk.SINGLE, height=15)
        self.listbox_selected.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_sel = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.listbox_selected.yview)
        self.listbox_selected.configure(yscrollcommand=scroll_sel.set)
        scroll_sel.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox_selected.bind("<<ListboxSelect>>", self._on_shuttle_selection_changed)
        self.listbox_selected.bind("<Double-1>", lambda _event: self._remove_seed_task())

        self._refresh_shuttle_boxes()

    def _get_preset_task_by_label(self, label):
        """根据显示标签获取预设任务的详细配置。"""
        for pt in self._preset_tasks:
            if pt["label"] == label:
                return pt
        return None

    def _refresh_shuttle_boxes(self):
        """刷新左右两侧的列表框。"""
        selected_names = [str(task.get("name", "")) for task in self.seeding_tasks]
        
        self.listbox_available.delete(0, tk.END)
        self.listbox_selected.delete(0, tk.END)
        
        for pt in self._preset_tasks:
            if pt["name"] not in selected_names:
                self.listbox_available.insert(tk.END, pt["label"])
                
        for task in self.seeding_tasks:
            # 尝试找对应的 label
            name = str(task.get("name", ""))
            label = name
            for pt in self._preset_tasks:
                if pt["name"] == name:
                    label = pt["label"]
                    break
            self.listbox_selected.insert(tk.END, label)
            
        self._update_shuttle_buttons_state()

    def _on_shuttle_selection_changed(self, event=None):
        """响应穿梭框选中变化。"""
        self._update_shuttle_buttons_state()

    def _update_shuttle_buttons_state(self):
        """更新添加/移除按钮状态。"""
        avail_sel = self.listbox_available.curselection()
        sel_sel = self.listbox_selected.curselection()
        
        if avail_sel:
            self.btn_shuttle_add.configure(state=tk.NORMAL)
        else:
            self.btn_shuttle_add.configure(state=tk.DISABLED)
            
        if sel_sel:
            self.btn_shuttle_remove.configure(state=tk.NORMAL)
        else:
            self.btn_shuttle_remove.configure(state=tk.DISABLED)

    def _add_seed_task(self):
        """将选中的预设任务加入已选列表。"""
        sel = self.listbox_available.curselection()
        if not sel:
            return
        idx = sel[0]
        label = self.listbox_available.get(idx)
        pt = self._get_preset_task_by_label(label)
        if pt:
            new_task = {
                "name": pt["name"],
                "zoom_levels": pt["zoom_levels"],
                "bbox": pt["bbox"],
                "refresh_before": "2026-01-01T00:00:00"
            }
            self.seeding_tasks.append(new_task)
            self._refresh_shuttle_boxes()

    def _remove_seed_task(self):
        """将选中的任务从已选列表中移除。"""
        sel = self.listbox_selected.curselection()
        if not sel:
            return
        idx = sel[0]
        label = self.listbox_selected.get(idx)
        
        # 找到对应的 name
        target_name = label
        for pt in self._preset_tasks:
            if pt["label"] == label:
                target_name = pt["name"]
                break
        
        self.seeding_tasks = [task for task in self.seeding_tasks if str(task.get("name", "")) != target_name]
        self._refresh_shuttle_boxes()

    def _normalize_seeding_tasks(self, raw_tasks):
        """标准化图层切片任务列表。"""
        tasks = []
        if not isinstance(raw_tasks, list):
            raw_tasks = []
        for idx, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, dict):
                continue
            name = str(raw_task.get("name", f"seed_task_{idx + 1}") or f"seed_task_{idx + 1}").strip()
            zoom_levels_raw = raw_task.get("zoom_levels", [0, 8])
            zoom_from = 0
            zoom_to = 8
            if isinstance(zoom_levels_raw, list) and len(zoom_levels_raw) == 2:
                try:
                    zoom_from = int(zoom_levels_raw[0])
                    zoom_to = int(zoom_levels_raw[1])
                except Exception:
                    zoom_from, zoom_to = 0, 8
            if zoom_from > zoom_to:
                zoom_from, zoom_to = zoom_to, zoom_from
            bbox_raw = raw_task.get("bbox", [73.0, 18.0, 135.0, 54.0])
            bbox = [73.0, 18.0, 135.0, 54.0]
            if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
                try:
                    bbox = [float(bbox_raw[0]), float(bbox_raw[1]), float(bbox_raw[2]), float(bbox_raw[3])]
                except Exception:
                    bbox = [73.0, 18.0, 135.0, 54.0]
            refresh_before = str(raw_task.get("refresh_before", "2026-01-01T00:00:00") or "2026-01-01T00:00:00").strip()
            tasks.append(
                {
                    "name": name,
                    "zoom_levels": [zoom_from, zoom_to],
                    "bbox": bbox,
                    "refresh_before": refresh_before,
                }
            )
        
        # 默认添加全球0-5，保障服务正常访问
        if not tasks:
            tasks.append({
                "name": "global_low_zoom",
                "zoom_levels": [0, 5],
                "bbox": [-180.0, -90.0, 180.0, 90.0],
                "refresh_before": "2026-01-01T00:00:00"
            })
            
        return tasks


    def get_current_settings(self):
        """获取当前配置的字典形式"""
        return {
            "advanced": {
                "concurrency": self.concurrency_var.get(),
                "retry": {
                    "enabled": self.retry_enabled_var.get(),
                    "max_retries": self.max_retries_var.get(),
                    "interval": self.retry_interval_var.get()
                },
                "alert": {
                    "enabled": self.alert_enabled_var.get()
                }
            },
            "sources": {
                "global_url": self.global_url_var.get().strip(),
                "china_url": self.china_url_var.get().strip()
            },
            "features": {
                "smart_switch": self.smart_switch_var.get(),
                "offline_mode": self.offline_mode_var.get(),
                "cache_dir": self.cache_dir_var.get().strip()
            },
            "seeding": {
                "tasks": copy.deepcopy(self.seeding_tasks)
            }
        }

    def restore_defaults(self):
        """还原默认设置"""
        if messagebox.askyesno("确认", "确定要还原为默认设置吗？", parent=self.top):
            # Advanced defaults
            adv_defaults = self.config_mgr.get_default_advanced_config()
            self.concurrency_var.set(adv_defaults["concurrency"])
            self.retry_enabled_var.set(adv_defaults["retry"]["enabled"])
            self.max_retries_var.set(adv_defaults["retry"]["max_retries"])
            self.retry_interval_var.set(adv_defaults["retry"]["interval"])
            self.alert_enabled_var.set(adv_defaults["alert"]["enabled"])

            # Sources defaults
            self.global_url_var.set("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%(z)s/%(y)s/%(x)s")
            self.china_url_var.set("")

            # Features defaults
            self.smart_switch_var.set(False)
            self.offline_mode_var.set(True)
            self.cache_dir_var.set("./cache_data")
            self.seeding_tasks = [{
                "name": "global_low_zoom",
                "zoom_levels": [0, 5],
                "bbox": [-180.0, -90.0, 180.0, 90.0],
                "refresh_before": "2026-01-01T00:00:00"
            }]
            self._refresh_shuttle_boxes()
            
            messagebox.showinfo("提示", "已恢复默认设置，点击保存后生效", parent=self.top)

    def has_changes(self):
        """检查是否有未保存的更改"""
        current = self.get_current_settings()
        return current != self.initial_config

    def on_cancel(self):
        """取消操作时的处理"""
        if self.has_changes():
            if not self._ask_cancel_confirmation():
                return
        self.close()

    def save(self):
        """保存设置"""
        try:
            # Validation
            conc = self.concurrency_var.get()
            if not (1 <= conc <= 16):
                raise ValueError("并发数必须在 1-16 之间")
                
            max_retries = self.max_retries_var.get()
            if max_retries < 0:
                 raise ValueError("最大重试次数不能为负数")
                 
            interval = self.retry_interval_var.get()
            if interval < 0:
                 raise ValueError("重试间隔不能为负数")

            # Save
            new_settings = self.get_current_settings()
            self.config_mgr.validate_seeding_config(new_settings["seeding"])
            
            # Update via config_manager
            self.config_mgr.update_map_config(
                advanced_update=new_settings["advanced"],
                sources_update=new_settings["sources"],
                features_update=new_settings["features"],
                seeding_update=new_settings["seeding"],
                source="gui_advancedsetting_manager.save"
            )
            
            if self.on_save_callback:
                self.on_save_callback("高级设置已保存")
            else:
                messagebox.showinfo("成功", "设置已保存", parent=self.top)
            
            self.close()
            
        except Exception as e:
            messagebox.showerror("保存失败", f"保存失败：{e}\n\n当前编辑内容已保留，请修正后重试。", parent=self.top)


def show_advanced_settings_dialog(parent, config_mgr, on_save_callback=None):
    """
    Shows the Advanced Settings Dialog.
    
    Args:
        parent: The parent window.
        config_mgr: The ConfigManager instance.
        on_save_callback: Optional callback function to be called when settings are saved.
                          It receives a success message string.
    """
    try:
        AdvancedSettingsDialog(parent, config_mgr, on_save_callback)
    except Exception as e:
        messagebox.showerror("错误", f"高级设置窗口打开失败: {e}", parent=parent)
