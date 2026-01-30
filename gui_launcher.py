import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sys
import os
import subprocess
import threading
import queue
import shutil
import webbrowser
import logging
import json # Used for error handling/logging if needed, though ConfigManager handles file IO
try:
    import main
except ImportError:
    main = None # Should not happen in bundle, but safe for dev
try:
    import process_manager
except ImportError:
    process_manager = None
from python_detector import find_python_interpreters
from utils import get_base_dir, get_work_dir, is_port_in_use
from config_manager import ConfigManager

# 工作目录名称 (referenced from utils implicitly by get_work_dir, but we might need it for display or logic)
LAUNCHER_DIR_NAME = "MapProxyLauncher"

def deploy_resources():
    """将内嵌资源部署到工作目录"""
    work_dir = get_work_dir()
    os.makedirs(work_dir, exist_ok=True)
    
    # 资源源目录
    if getattr(sys, 'frozen', False):
        source_dir = sys._MEIPASS
    else:
        source_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 需要复制的文件列表
    # 注意：ConfigManager 会处理配置文件的初始化，但这里我们还需要处理代码文件
    # 为了避免冲突，我们可以让 ConfigManager 处理配置，这里只处理代码
    # 或者为了简单，保留这里的逻辑，但确保一致性
    files_to_copy = [
        "main.py",
        "config.py",
        "seed_manager.py",
        "mapproxy.yaml",
        "mapproxy-seed.yaml",
        "requirements.txt",
        "utils.py",
        "env_manager.py",
        "dependency_manager.py",
        "service_runner.py",
        "seed_orchestrator.py",
        "config_manager.py",
        "python_detector.py" # Ensure all modules are deployed
    ]
    
    for filename in files_to_copy:
        src = os.path.join(source_dir, filename)
        dst = os.path.join(work_dir, filename)
        
        if os.path.exists(src):
            if filename.endswith(".yaml") or filename.endswith(".json") or filename == "requirements.txt" or filename == "config.py":
                # 配置文件/数据文件：仅当不存在时复制，以免覆盖用户配置
                # config.py 虽然是代码，但也包含用户可能修改的配置 (application entry)，所以小心覆盖
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        logging.info(f"Deploying config: {filename}")
                    except Exception as e:
                        logging.exception(f"Failed to deploy {filename}")
            else:
                # 代码文件：始终覆盖，确保版本更新
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logging.exception(f"Failed to deploy {filename}")

class AdvancedSettingsDialog:
    def __init__(self, parent, config_mgr, on_save_callback):
        self.parent = parent
        self.top = tk.Toplevel(parent)
        self.top.title("高级设置")
        
        self.config_mgr = config_mgr
        self.on_save_callback = on_save_callback
        
        # Load current settings
        self.config = self.config_mgr.load_advanced_config()
        import copy
        self.initial_config = copy.deepcopy(self.config)

        # Vars
        self.concurrency_var = tk.IntVar(value=self.config.get("concurrency", 2))
        
        retry_cfg = self.config.get("retry", {})
        self.retry_enabled_var = tk.BooleanVar(value=retry_cfg.get("enabled", False))
        self.max_retries_var = tk.IntVar(value=retry_cfg.get("max_retries", 2))
        self.retry_interval_var = tk.IntVar(value=retry_cfg.get("interval", 5))
        
        alert_cfg = self.config.get("alert", {})
        self.alert_enabled_var = tk.BooleanVar(value=alert_cfg.get("enabled", False))
        
        self.create_widgets()
        
        # Center window and Make modal
        self.center_window()
        self.top.transient(parent)
        self.top.grab_set()
        
        # Disable parent to prevent dragging/interaction (Windows specific but safe)
        try:
            self.parent.attributes('-disabled', True)
        except Exception:
            pass
        
        self.top.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def close(self):
        """Close dialog and re-enable parent"""
        try:
            self.parent.attributes('-disabled', False)
            self.parent.lift()
        except Exception:
            pass
        self.top.destroy()
        
    def center_window(self):
        width = 500
        height = 450
        
        # Ensure parent info is available
        self.parent.update_idletasks()
        
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() // 2) - (width // 2)
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() // 2) - (height // 2)
        
        if x < 0: x = 0
        if y < 0: y = 0
            
        self.top.geometry(f"{width}x{height}+{x}+{y}")
        self.top.minsize(400, 400)

    def create_widgets(self):
        main_frame = ttk.Frame(self.top, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Buttons (Pack at bottom first to ensure visibility)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        ttk.Button(btn_frame, text="保存", command=self.save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="还原默认值", command=self.restore_defaults).pack(side=tk.LEFT, padx=5)

        # Content Container (Scrollable if needed, but for now simple frame)
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Seed Concurrency
        grp_seed = ttk.LabelFrame(content_frame, text="Seed 服务管理配置", padding="10")
        grp_seed.pack(fill=tk.X, pady=5)
        
        ttk.Label(grp_seed, text="并发进程数 (1-16):").grid(row=0, column=0, sticky=tk.W, pady=5)
        sp_conc = ttk.Spinbox(grp_seed, from_=1, to=16, textvariable=self.concurrency_var, width=10)
        sp_conc.grid(row=0, column=1, padx=10, sticky=tk.W, pady=5)
        
        # Retry Policy
        grp_retry = ttk.LabelFrame(content_frame, text="失败重试策略", padding="10")
        grp_retry.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(grp_retry, text="启用自动重试", variable=self.retry_enabled_var).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(grp_retry, text="最大重试次数:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=10, textvariable=self.max_retries_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(grp_retry, text="重试间隔 (秒):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=60, textvariable=self.retry_interval_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        # Alert Policy
        grp_alert = ttk.LabelFrame(content_frame, text="失败告警配置", padding="10")
        grp_alert.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(grp_alert, text="启用失败告警", variable=self.alert_enabled_var).grid(row=0, column=0, sticky=tk.W)

    def get_current_settings(self):
        return {
            "concurrency": self.concurrency_var.get(),
            "retry": {
                "enabled": self.retry_enabled_var.get(),
                "max_retries": self.max_retries_var.get(),
                "interval": self.retry_interval_var.get()
            },
            "alert": {
                "enabled": self.alert_enabled_var.get()
            }
        }

    def restore_defaults(self):
        if messagebox.askyesno("确认", "确定要还原为默认设置吗？", parent=self.top):
            defaults = self.config_mgr.get_default_advanced_config()
            self.concurrency_var.set(defaults["concurrency"])
            
            self.retry_enabled_var.set(defaults["retry"]["enabled"])
            self.max_retries_var.set(defaults["retry"]["max_retries"])
            self.retry_interval_var.set(defaults["retry"]["interval"])
            
            self.alert_enabled_var.set(defaults["alert"]["enabled"])
            
            messagebox.showinfo("提示", "已恢复默认设置", parent=self.top)

    def has_changes(self):
        current = self.get_current_settings()
        # Compare current with initial
        # Need to handle potential type diffs if spinbox returns string, but IntVar handles that.
        # But we need to ensure structure matches.
        return current != self.initial_config

    def on_cancel(self):
        if self.has_changes():
            if not messagebox.askyesno("确认", "有未保存的更改，确定要取消吗？", parent=self.top):
                return
        self.close()

    def save(self):
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
            
            self.config_mgr.save_advanced_config(new_settings)
            
            if self.on_save_callback:
                self.on_save_callback("高级设置已保存")
            else:
                messagebox.showinfo("成功", "设置已保存", parent=self.top)
            
            self.close()
            
        except Exception as e:
            messagebox.showerror("保存失败", f"保存失败，请重试: {e}", parent=self.top)


class LauncherApp:
    def __init__(self, root):
        logging.basicConfig(level=logging.INFO)
        self.root = root
        self.root.title("MapProxy Server Launcher")
        
        # 1. 窗口尺寸调整与限制
        # Default size optimized for 1080p/768p screens to avoid scrollbar initially
        # Estimated height of fixed content ~500px + Min Log ~200px = 700px
        # 1280x900 provides ample space.
        self.root.geometry("1280x950")
        self.root.minsize(320, 480)
        
        # 变量
        self.python_path_var = tk.StringVar()
        self.port_var = tk.StringVar(value="8080")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.allow_external_var = tk.BooleanVar(value=False)
        self.service_process = None
        self.log_queue = queue.Queue()
        # 将日志路径调整到项目根目录下的 logs 目录，与 seed.log 保持一致
        self.server_log_path = os.path.join(get_base_dir(), "logs", "server.log")
        self.server_log_pos = 0
        self.current_host = "127.0.0.1"
        self.logger = logging.getLogger("Launcher")
        
        # Log Enhancement Variables
        self.log_auto_scroll = tk.BooleanVar(value=True)
        self.log_level_var = tk.StringVar(value="INFO") # DEBUG, INFO, WARN, ERROR
        self.log_buffer = [] # Store (level, message) tuples
        self.max_log_buffer = 5000
        
        # Config Manager
        self.config_mgr = ConfigManager(get_work_dir(), get_base_dir())
        
        # 新增状态变量
        self.status_var = tk.StringVar(value="就绪")
        self.service_url_var = tk.StringVar(value="")
        self.status_color = "gray" # 默认颜色
        
        # 部署资源
        deploy_resources()

        # 配置样式
        style = ttk.Style()
        # 修复 Combobox 在 Windows 下的样式问题
        style.map('TCombobox', 
                  fieldbackground=[('readonly', 'white'), ('!disabled', 'white')],
                  background=[('readonly', 'white'), ('!disabled', 'white')],
                  selectbackground=[('readonly', 'white'), ('!disabled', 'white')],
                  selectforeground=[('readonly', 'black'), ('!disabled', 'black')])
        
        # Card style
        style.configure("Card.TLabelframe", relief="groove", borderwidth=2)
        
        self.create_widgets()
        self.load_config()
        self.scan_pythons()
        self.load_layers()
        
        # 绑定快捷键
        self.root.bind('<Control-l>', lambda e: self.text_log.see("end"))
        self.root.bind('<Control-L>', lambda e: self.text_log.see("end"))
        
        # 启动日志更新定时器
        self.root.after(100, self.update_logs)
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        # Root layout configuration
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create Scrollable Canvas Container
        self.canvas = tk.Canvas(self.root, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, padding="15")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        # Scrollbar will be managed dynamically
        
        # Ensure inner frame width matches canvas width
        self.canvas.bind('<Configure>', self.on_canvas_configure)
        
        # Main content frame (use this for all widgets)
        main_frame = self.scrollable_frame
        main_frame.columnconfigure(0, weight=1)
        # Configure row weights to allow log frame to expand
        main_frame.rowconfigure(0, weight=0) # Env
        main_frame.rowconfigure(1, weight=0) # Config
        main_frame.rowconfigure(2, weight=0) # Status
        main_frame.rowconfigure(3, weight=0) # Layers
        main_frame.rowconfigure(4, weight=1) # Log (Expandable)

        # 1. Python 环境 (Row 0) - Exclusive Row
        frame_env = ttk.LabelFrame(main_frame, text="运行环境", padding="10", style="Card.TLabelframe")
        frame_env.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        
        ttk.Label(frame_env, text="Python 解释器:").pack(side=tk.LEFT)
        self.combo_python = ttk.Combobox(frame_env, textvariable=self.python_path_var, state="readonly")
        self.combo_python.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.btn_refresh = ttk.Button(frame_env, text="刷新", command=self.scan_pythons)
        self.btn_refresh.pack(side=tk.LEFT)
        
        # 2. 服务配置 & 核心控制 (Row 1) - Merged & Refactored
        frame_config = ttk.LabelFrame(main_frame, text="服务配置与控制", padding="10", style="Card.TLabelframe")
        frame_config.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        frame_config.columnconfigure(1, weight=1) # Allow expansion
        
        # Line 1: Basic Config (Port, Host, Save, Advanced)
        config_line = ttk.Frame(frame_config)
        config_line.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 15))
        
        ttk.Label(config_line, text="端口:").pack(side=tk.LEFT)
        self.entry_port = ttk.Entry(config_line, textvariable=self.port_var, width=8)
        self.entry_port.pack(side=tk.LEFT, padx=5)
        self.entry_port.bind('<KeyRelease>', self.validate_port_input)
        
        self.chk_external = ttk.Checkbutton(config_line, text="允许外部访问", variable=self.allow_external_var, command=self.update_host_from_access)
        self.chk_external.pack(side=tk.LEFT, padx=10)
        
        self.lbl_host = ttk.Label(config_line, textvariable=self.host_var, foreground="gray")
        self.lbl_host.pack(side=tk.LEFT, padx=5)
        
        self.btn_advanced = ttk.Button(config_line, text="高级设置", command=self.open_advanced_settings)
        self.btn_advanced.pack(side=tk.RIGHT, padx=5)
        
        self.btn_save = ttk.Button(config_line, text="保存配置", command=self.save_config)
        self.btn_save.pack(side=tk.RIGHT, padx=5)

        # Line 2: Start/Stop Buttons (Compact Group)
        control_line = ttk.Frame(frame_config)
        control_line.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 15))
        
        # Start/Stop buttons
        self.btn_start = ttk.Button(control_line, text="启动服务", command=self.start_service)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_stop = ttk.Button(control_line, text="停止服务", command=self.stop_service, state="disabled")
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # Line 3: Work Directory
        dir_line = ttk.Frame(frame_config)
        dir_line.grid(row=2, column=0, columnspan=3, sticky="ew")
        
        ttk.Label(dir_line, text="工作目录:").pack(side=tk.LEFT)
        
        self.work_dir_var = tk.StringVar(value=get_work_dir())
        entry_work_dir = ttk.Entry(dir_line, textvariable=self.work_dir_var, state="readonly", font=("Consolas", 9))
        entry_work_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        self.btn_dir = ttk.Button(dir_line, text="打开目录", command=self.open_work_dir)
        self.btn_dir.pack(side=tk.RIGHT)

        # 3. 运行状态模块 (Row 2) - Simplified
        frame_status_card = ttk.LabelFrame(main_frame, text="运行状态", padding="15", style="Card.TLabelframe")
        frame_status_card.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        
        # Status Header (Indicator + URL + Browser)
        status_header = ttk.Frame(frame_status_card)
        status_header.pack(fill=tk.X)
        
        # Indicator
        self.canvas_status = tk.Canvas(status_header, width=20, height=20, highlightthickness=0)
        self.canvas_status.pack(side=tk.LEFT, padx=(0, 5))
        self.status_circle = self.canvas_status.create_oval(2, 2, 18, 18, fill="gray", outline="gray")
        
        self.lbl_status = ttk.Label(status_header, textvariable=self.status_var, font=("Microsoft YaHei", 12, "bold"), foreground="gray")
        self.lbl_status.pack(side=tk.LEFT, padx=5)
        
        # URL
        url_container = ttk.Frame(status_header)
        url_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=20)
        ttk.Label(url_container, text="服务地址:").pack(side=tk.LEFT)
        entry_url = ttk.Entry(url_container, textvariable=self.service_url_var, state="readonly", font=("Consolas", 10))
        entry_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(url_container, text="复制", command=self.copy_url).pack(side=tk.LEFT)
        
        # Browser Button (Quick Access)
        self.btn_browser = ttk.Button(status_header, text="在浏览器打开", command=self.open_browser)
        self.btn_browser.pack(side=tk.RIGHT, padx=5)

        # 4. 图层信息 (Row 3)
        frame_layers = ttk.LabelFrame(main_frame, text="图层列表", padding="10", style="Card.TLabelframe")
        frame_layers.grid(row=3, column=0, sticky="nsew", pady=(0, 15))
        
        columns = ("name", "format", "title")
        self.tree_layers = ttk.Treeview(frame_layers, columns=columns, show="headings", selectmode="none", height=4)
        
        self.tree_layers.heading("name", text="图层名称 (Name)")
        self.tree_layers.heading("format", text="格式 (Format)")
        self.tree_layers.heading("title", text="标题 (Title)")
        
        self.tree_layers.column("name", width=200, anchor=tk.CENTER)
        self.tree_layers.column("format", width=100, anchor=tk.CENTER)
        self.tree_layers.column("title", width=400, anchor=tk.CENTER)
        
        self.tree_layers.tag_configure("hover", background="#f5f5f5")
        
        scrollbar_layers = ttk.Scrollbar(frame_layers, orient=tk.VERTICAL, command=self.tree_layers.yview)
        self.tree_layers.configure(yscroll=scrollbar_layers.set)
        
        self.tree_layers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_layers.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree_layers.bind("<Button-1>", self.on_layer_click)
        self.tree_layers.bind("<Motion>", self.on_tree_hover)

        # 5. 运行日志 (Row 4)
        frame_log = ttk.LabelFrame(main_frame, text="运行日志", padding="10", style="Card.TLabelframe")
        # sticky="nsew" ensures it fills the expanded row
        frame_log.grid(row=4, column=0, sticky="nsew") 
        
        # Ensure frame_log expands to fill its grid cell
        # But wait, frame_log is a TLabelframe. It needs to manage its children too.
        # It uses pack for children.
        # We need to ensure the ScrolledText fills frame_log.
        
        # Log Toolbar
        log_toolbar = ttk.Frame(frame_log)
        log_toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(log_toolbar, text="日志级别:").pack(side=tk.LEFT)
        combo_level = ttk.Combobox(log_toolbar, textvariable=self.log_level_var, values=["DEBUG", "INFO", "WARN", "ERROR"], state="readonly", width=8)
        combo_level.pack(side=tk.LEFT, padx=5)
        combo_level.bind("<<ComboboxSelected>>", self.refresh_log_view)
        
        ttk.Checkbutton(log_toolbar, text="自动滚动", variable=self.log_auto_scroll).pack(side=tk.LEFT, padx=15)
        
        ttk.Button(log_toolbar, text="导出日志", command=self.export_logs).pack(side=tk.RIGHT, padx=5)
        ttk.Button(log_toolbar, text="清空日志", command=self.clear_logs).pack(side=tk.RIGHT, padx=5)
        
        self.text_log = scrolledtext.ScrolledText(frame_log, height=10, state="disabled", font=("Consolas", 9))
        self.text_log.pack(fill=tk.BOTH, expand=True)
        
        # Tags
        self.text_log.tag_config("DEBUG", foreground="gray")
        self.text_log.tag_config("INFO", foreground="black")
        self.text_log.tag_config("WARN", foreground="orange")
        self.text_log.tag_config("ERROR", foreground="red")
        self.text_log.tag_config("SUCCESS", foreground="green")

    def on_canvas_configure(self, event):
        """Ensure inner frame matches canvas width and handles responsive layout"""
        # 1. Width Adaptation
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        self.adapt_ui_size(event.width)
        
        # 2. Dynamic Height & Scrollbar Management
        # Calculate minimum required height for content
        # Note: We need to force update to get accurate reqheight
        self.scrollable_frame.update_idletasks() 
        min_req_height = self.scrollable_frame.winfo_reqheight()
        
        # Logic:
        # If window height (event.height) > min_req_height:
        #   - Content fits comfortably.
        #   - We expand the inner frame to fill the window height.
        #   - This triggers the row with weight=1 (Log Frame) to expand.
        #   - We hide the scrollbar.
        # If window height < min_req_height:
        #   - Content does not fit.
        #   - We set inner frame height to natural reqheight (or let it be).
        #   - We show the scrollbar.
        
        if event.height >= min_req_height:
             self.canvas.itemconfig(self.canvas_window, height=event.height)
             self.scrollbar.grid_remove()
             # Update scrollregion to avoid scrolling behavior even if hidden
             self.canvas.configure(scrollregion=(0, 0, event.width, event.height))
        else:
             # Reset height to auto (None doesn't work directly in itemconfig for window, 
             # but setting it to reqheight works)
             self.canvas.itemconfig(self.canvas_window, height=min_req_height)
             
             # Show scrollbar
             self.scrollbar.grid(row=0, column=1, sticky="ns")
             self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def adapt_ui_size(self, width):
        """根据屏幕宽度自适应调整字体和组件尺寸"""
        style = ttk.Style()
        
        # Requirements:
        # - Button Height ~32px (Managed by padding + font)
        # - Font Size >= 14px (Tkinter negative value = pixels)
        # - Padding: 8px horizontal, 4px vertical
        
        # Determine base font size based on requirements, but can still scale slightly for very small screens if needed?
        # User said "Unified reduction... ensure font >= 14px".
        # Let's use 14px as base.
        
        base_font_size = -14 # 14px
        btn_pad = (8, 4) # (Horizontal, Vertical)
        
        # We can still have some responsiveness if needed, but user emphasized "Unified...".
        # Let's stick to the requested spec as the "Standard", maybe slight adjust for mobile?
        # User: "Ensure readability... no overflow".
        
        if width < 768: # Mobile
             # Maybe slightly smaller if 14px is too big? 
             # But user said "not less than 14px". So we stick to -14.
             pass 

        # Update styles
        # Note: We use 'Microsoft YaHei' as consistent font
        style.configure('.', font=('Microsoft YaHei', base_font_size))
        
        # TButton configuration
        # width parameter in style is character width, which is not what we want for "min 80px".
        # We can use "width" in the widget creation if needed, or rely on padding.
        # But 'min width 80px' is hard to enforce strictly via style alone in ttk without a layout wrapper or fixed width.
        # However, we can ensure enough padding.
        # To strictly enforce min-width 80px, we might need to use a custom layout or ensure text + padding >= 80px.
        # For now, we apply the requested padding.
        
        style.configure('TButton', font=('Microsoft YaHei', base_font_size), padding=btn_pad)
        
        style.configure('TLabelframe.Label', font=('Microsoft YaHei', base_font_size, 'bold'))
        style.configure('Treeview.Heading', font=('Microsoft YaHei', base_font_size))
        style.configure('Treeview', font=('Microsoft YaHei', base_font_size), rowheight=30) # Adjust row height for 14px font

    def set_status(self, status, color, url=""):
        self.status_var.set(status)
        self.lbl_status.config(foreground=color)
        self.canvas_status.itemconfig(self.status_circle, fill=color, outline=color)
        self.service_url_var.set(url)

    def refresh_log_view(self, event=None):
        """Refilter logs based on level"""
        self.text_log.config(state="normal")
        self.text_log.delete(1.0, tk.END)
        
        min_level = self.log_level_var.get()
        levels = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        min_val = levels.get(min_level, 1)
        
        for level, msg in self.log_buffer:
            msg_val = levels.get(level, 1)
            if msg_val >= min_val:
                self.text_log.insert("end", msg + "\n", level)
                
        if self.log_auto_scroll.get():
            self.text_log.see("end")
        self.text_log.config(state="disabled")

    def log(self, message, level="INFO"):
        # Normalize level
        level = level.upper()
        if level not in ["DEBUG", "INFO", "WARN", "ERROR", "SUCCESS"]:
            level = "INFO"
            
        # Add to buffer
        self.log_buffer.append((level, message))
        if len(self.log_buffer) > self.max_log_buffer:
            self.log_buffer.pop(0)
            
        # Display if meets criteria
        min_level = self.log_level_var.get()
        levels_map = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        
        # Map SUCCESS to INFO for filtering purposes, or treat as INFO
        msg_val = levels_map.get(level if level != "SUCCESS" else "INFO", 1)
        min_val = levels_map.get(min_level, 1)
        
        if msg_val >= min_val:
            self.text_log.config(state="normal")
            self.text_log.insert("end", message + "\n", level)
            if self.log_auto_scroll.get():
                self.text_log.see("end")
            self.text_log.config(state="disabled")

    def clear_logs(self):
        if messagebox.askyesno("确认", "确定要清空日志吗？"):
            self.log_buffer = []
            self.text_log.config(state="normal")
            self.text_log.delete(1.0, tk.END)
            self.text_log.config(state="disabled")

    def export_logs(self):
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("Log Files", "*.log"), ("All Files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    for _, msg in self.log_buffer:
                        f.write(msg + "\n")
                messagebox.showinfo("成功", "日志已导出")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {e}")

    def scan_pythons(self):
        if getattr(self, 'is_scanning', False):
            return
        self.is_scanning = True
        self.btn_refresh.config(state="disabled")
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
        self.combo_python['values'] = values
        
        # Restore selection or default to first
        current = self.python_path_var.get()
        if current and current in values:
            self.combo_python.current(values.index(current))
        elif values:
            self.combo_python.current(0)
            
        self.log(f"扫描完成，发现 {len(interpreters)} 个解释器。")
        
        # Re-enable UI if service not running
        if not self.service_process:
            self.btn_refresh.config(state="normal")
            self.combo_python.config(state="readonly")

    def _on_scan_error(self, error_msg):
        self.is_scanning = False
        self.log(f"扫描出错: {error_msg}", "error")
        # Re-enable UI if service not running
        if not self.service_process:
            self.btn_refresh.config(state="normal")
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
        self.combo_python.config(state=readonly)
        self.btn_refresh.config(state=state)
        
        # Config
        self.entry_port.config(state=state)
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
            label = tk.Label(toast, text=message, bg="#333333", fg="white", 
                             padx=15, pady=8, font=("Microsoft YaHei", 9))
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
                self.entry_port.config(foreground="black")
                self.btn_save.config(state="normal")
                return True
            else:
                raise ValueError
        except ValueError:
            self.entry_port.config(foreground="red")
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
            "selection_label": selection # 保存完整标签以便回显
        }
        
        try:
            self.config_mgr.save_launcher_config(config_data)
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
            host_value = config.get("host", "127.0.0.1")
            allow_external = config.get("allow_external_access", False)
            selection_label = config.get("selection_label", "")
            
            self.port_var.set(str(port))
            self.allow_external_var.set(bool(allow_external))
            if self.allow_external_var.get():
                self.host_var.set("0.0.0.0")
            else:
                self.host_var.set("127.0.0.1")
            if not self.allow_external_var.get() and host_value not in ("0.0.0.0", "::"):
                self.host_var.set(str(host_value))
            
            if selection_label:
                self.python_path_var.set(selection_label)
            elif path:
                    self.python_path_var.set(path)
        except Exception:
            self.logger.exception("读取配置失败")

    def start_service(self):
        if self.service_process:
            return

        if not self.validate_port_input():
            return

        # 验证 MapProxy 配置
        try:
            self.config_mgr.validate_mapproxy_config()
        except Exception as e:
            if not messagebox.askyesno("配置验证警告", f"MapProxy 配置验证失败:\n{e}\n\n是否仍要尝试启动服务?"):
                return
            
        port = int(self.port_var.get())
        self.update_host_from_access()
        host_value = self.host_var.get().strip()
        
        if is_port_in_use(port, host_value):
             messagebox.showerror("错误", f"端口 {port} 已被占用")
             return
        
        selection = self.python_path_var.get()
        if " - " in selection:
            python_path = selection.split(" - ")[-1]
        else:
            python_path = selection
            
        work_dir = get_work_dir()
        script_path = os.path.join(work_dir, "main.py")
        
        # 构造命令
        cmd = []
        
        # 判断是 Internal 还是 External
        if "Internal" in selection or python_path == sys.executable:
            # Internal Mode
            # 直接调用当前可执行文件（或 python），并传递 --service 参数
            # 由于我们在 main block 添加了参数分发，这将启动服务而不是 GUI
            cmd = [sys.executable, '--service']
        else:
            # External Mode
            if not os.path.exists(python_path):
                 messagebox.showerror("错误", "Python 路径无效")
                 return
            if not os.path.exists(script_path):
                 messagebox.showerror("错误", f"找不到 main.py: {script_path}")
                 return
            
            # 使用 --python-path 明确传递所选 Python 路径给 main.py
            cmd = [python_path, script_path, '--service', '--python-path', python_path]

        # 添加通用参数
        cmd.extend(['--port', str(port), '--host', host_value, '--work-dir', work_dir])
        self.current_host = host_value
        
        self.log(f"正在启动服务: {' '.join(cmd)}")
        self.set_status("正在初始化环境配置...", "orange") # 状态更新
        
        try:
            # Prepare Environment Variables
            env = os.environ.copy()
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

        # 停止时不读取 server.log 以避免误判
        if self.service_process:
            self.read_server_log()
        
        self.root.after(100, self.update_logs)

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

    def stop_service(self):
        """停止服务，仅终止由当前实例启动的进程"""
        self.btn_stop.config(state="disabled") # 防止重复点击
        
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
            if messagebox.askokcancel("退出", "服务正在运行，确定要停止服务并退出吗？"):
                self.stop_service()
                self.root.destroy()
        else:
            self.root.destroy()

    def open_advanced_settings(self):
        if self.service_process:
            messagebox.showwarning("警告", "服务正在运行，高级设置暂不可用。")
            return

        AdvancedSettingsDialog(self.root, self.config_mgr, lambda msg: self.show_toast(msg))

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

    try:
        # High DPI support
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
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

