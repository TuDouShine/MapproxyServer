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
        self.root.geometry("850x800")
        
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
        # 修复 Combobox 在 Windows 下的样式问题：
        # 移除 selectbackground 的强制设置，避免与系统主题冲突导致"蓝白"混合显示
        # 仅确保 readonly 状态下的基础背景为白色，选中时不改变背景色(看起来像普通输入框)
        style.map('TCombobox', 
                  fieldbackground=[('readonly', 'white'), ('!disabled', 'white')],
                  background=[('readonly', 'white'), ('!disabled', 'white')],
                  selectbackground=[('readonly', 'white'), ('!disabled', 'white')],
                  selectforeground=[('readonly', 'black'), ('!disabled', 'black')])
        
        self.create_widgets()
        self.load_config()
        self.scan_pythons()
        self.load_layers()
        
        # 启动日志更新定时器
        self.root.after(100, self.update_logs)
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        # ... (Same as before, I will rely on previous content or assume I don't need to rewrite this method if I use SearchReplace, 
        # but since I am rewriting the file, I must include it.
        # To save space and time, I will include the full method content from the previous read.)
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. Python 环境选择
        frame_env = ttk.LabelFrame(main_frame, text="运行环境", padding="5")
        frame_env.pack(fill=tk.X, pady=5)
        
        ttk.Label(frame_env, text="Python 解释器:").pack(side=tk.LEFT)
        self.combo_python = ttk.Combobox(frame_env, textvariable=self.python_path_var, state="readonly", width=50)
        self.combo_python.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.btn_refresh = ttk.Button(frame_env, text="刷新", command=self.scan_pythons)
        self.btn_refresh.pack(side=tk.LEFT)

        # 2. 服务配置
        frame_config = ttk.LabelFrame(main_frame, text="服务配置", padding="5")
        frame_config.pack(fill=tk.X, pady=5)
        
        # Grid 布局
        ttk.Label(frame_config, text="端口 (Port):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.entry_port = ttk.Entry(frame_config, textvariable=self.port_var, width=10)
        self.entry_port.grid(row=0, column=1, sticky=tk.W, pady=5)
        self.entry_port.bind('<KeyRelease>', self.validate_port_input)
        
        ttk.Label(frame_config, text="允许外部访问:").grid(row=0, column=2, sticky=tk.W, padx=10, pady=5)
        self.chk_external = ttk.Checkbutton(frame_config, variable=self.allow_external_var, command=self.update_host_from_access)
        self.chk_external.grid(row=0, column=3, sticky=tk.W, pady=5)
        
        ttk.Label(frame_config, text="监听地址 (Host):").grid(row=0, column=4, sticky=tk.W, padx=10, pady=5)
        self.lbl_host = ttk.Label(frame_config, textvariable=self.host_var)
        self.lbl_host.grid(row=0, column=5, sticky=tk.W, pady=5)

        self.btn_save = ttk.Button(frame_config, text="保存配置", command=self.save_config)
        self.btn_save.grid(row=0, column=6, sticky=tk.E, padx=20)
        
        # 3. 控制面板
        frame_control = ttk.Frame(main_frame, padding="5")
        frame_control.pack(fill=tk.X, pady=10)
        
        self.btn_start = ttk.Button(frame_control, text="启动服务", command=self.start_service)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        
        self.btn_stop = ttk.Button(frame_control, text="停止服务", command=self.stop_service, state="disabled")
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        self.btn_browser = ttk.Button(frame_control, text="在浏览器打开", command=self.open_browser)
        self.btn_browser.pack(side=tk.LEFT, padx=20)

        self.btn_dir = ttk.Button(frame_control, text="打开工作目录", command=self.open_work_dir)
        self.btn_dir.pack(side=tk.LEFT, padx=5)

        self.btn_advanced = ttk.Button(frame_control, text="高级设置", command=self.open_advanced_settings)
        self.btn_advanced.pack(side=tk.LEFT, padx=5)
        
        # 状态显示
        frame_status = ttk.Frame(main_frame)
        frame_status.pack(fill=tk.X, pady=5)
        ttk.Label(frame_status, text="状态: ").pack(side=tk.LEFT)
        self.lbl_status = ttk.Label(frame_status, textvariable=self.status_var, foreground="gray")
        self.lbl_status.pack(side=tk.LEFT)
        
        ttk.Label(frame_status, text="  |  访问地址: ").pack(side=tk.LEFT, padx=(10,0))
        entry_url = ttk.Entry(frame_status, textvariable=self.service_url_var, state="readonly", width=30)
        entry_url.pack(side=tk.LEFT)
        ttk.Button(frame_status, text="复制", command=self.copy_url, width=4).pack(side=tk.LEFT, padx=2)

        # 4. 图层信息
        frame_layers = ttk.LabelFrame(main_frame, text="图层信息 (单击单元格复制内容)", padding="5")
        frame_layers.pack(fill=tk.BOTH, expand=True, pady=5)
        
        columns = ("name", "title", "format")
        self.tree_layers = ttk.Treeview(frame_layers, columns=columns, show="headings", height=6, selectmode="none")
        
        self.tree_layers.heading("name", text="图层名称 (Name)")
        self.tree_layers.heading("title", text="标题 (Title)")
        self.tree_layers.heading("format", text="格式 (Format)")
        
        self.tree_layers.column("name", width=200, anchor=tk.W)
        self.tree_layers.column("title", width=300, anchor=tk.W)
        self.tree_layers.column("format", width=100, anchor=tk.CENTER)
        
        # 配置 hover tag
        self.tree_layers.tag_configure("hover", background="#f5f5f5")
        
        scrollbar_layers = ttk.Scrollbar(frame_layers, orient=tk.VERTICAL, command=self.tree_layers.yview)
        self.tree_layers.configure(yscroll=scrollbar_layers.set)
        
        self.tree_layers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_layers.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree_layers.bind("<Button-1>", self.on_layer_click)
        self.tree_layers.bind("<Motion>", self.on_tree_hover)

        # 5. 日志区域
        frame_log = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        frame_log.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.text_log = scrolledtext.ScrolledText(frame_log, height=15, state="disabled")
        self.text_log.pack(fill=tk.BOTH, expand=True)
        
        # 配置日志 Tag 颜色
        self.text_log.tag_config("info", foreground="black")
        self.text_log.tag_config("error", foreground="red")
        self.text_log.tag_config("warning", foreground="orange")
        self.text_log.tag_config("success", foreground="green")

    def set_status(self, status, color, url=""):
        self.status_var.set(status)
        self.lbl_status.config(foreground=color)
        self.service_url_var.set(url)

    def log(self, message, level="info"):
        self.text_log.config(state="normal")
        self.text_log.insert("end", message + "\n", level)
        self.text_log.see("end")
        self.text_log.config(state="disabled")

    def update_host_from_access(self):
        if self.allow_external_var.get():
            self.host_var.set("0.0.0.0")
        else:
            self.host_var.set("127.0.0.1")

    def update_controls_state(self, is_running):
        """Update UI controls based on service state"""
        state = "disabled" if is_running else "normal"
        readonly_state = "disabled" if is_running else "readonly" # Combobox readonly vs disabled
        
        # 1. Interpreter Selection
        self.combo_python.config(state=readonly_state if not is_running else "disabled")
        self.btn_refresh.config(state=state)
        
        # 2. Service Config
        self.entry_port.config(state=state)
        self.chk_external.config(state=state)
        self.btn_save.config(state=state)
        
        # 3. Advanced Settings
        self.btn_advanced.config(state=state)

    def scan_pythons(self):
        # Prevent concurrent scans
        if hasattr(self, 'is_scanning') and self.is_scanning:
            return
        self.is_scanning = True

        # Disable UI controls to prevent interference
        self.log("正在扫描 Python 解释器...")
        self.btn_refresh.config(state="disabled")
        self.combo_python.config(state="disabled")
        
        # Start background thread
        threading.Thread(target=self._run_scan_thread, daemon=True).start()

    def _run_scan_thread(self):
        try:
            interpreters = find_python_interpreters()
            # Post result to main thread
            self.root.after(0, lambda: self._on_scan_complete(interpreters))
        except Exception as e:
            self.root.after(0, lambda: self._on_scan_error(str(e)))

    def _on_scan_complete(self, interpreters):
        self.is_scanning = False
        
        # Frozen check logic (Removed as per requirements)
        # ...

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
                layer.get('title', ''),
                layer.get('format', '')
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
            os.startfile(work_dir)
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

