import tkinter as tk
from tkinter import ttk, messagebox
import copy
from modules.ui.ui_utils import block_main_interaction, unblock_main_interaction

class AdvancedSettingsDialog:
    def __init__(self, parent, config_mgr, on_save_callback):
        self.parent = parent
        self.top = tk.Toplevel(parent)
        self.top.title("高级设置")
        
        self.config_mgr = config_mgr
        self.on_save_callback = on_save_callback
        
        # Load current settings from map_config.json
        self.map_config = self.config_mgr.load_map_config()
        self.advanced_config = self.map_config.get("advanced_settings", {})
        self.system_config = self.map_config.get("system", {})
        self.sources_config = self.map_config.get("sources", {})
        self.features_config = self.map_config.get("features", {})
        
        self.init_vars()
        self.initial_config = self.get_current_settings()
        
        self.create_widgets()
        
        # Center window and Make modal
        self.center_window()
        block_main_interaction(self.parent, self.top)
        
        self.top.protocol("WM_DELETE_WINDOW", self.on_cancel)

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
        self.offline_mode_var = tk.BooleanVar(value=self.features_config.get("offline_mode", False))
        self.cache_dir_var = tk.StringVar(value=self.features_config.get("cache_dir", "./cache_data"))

    def close(self):
        """Close dialog and re-enable parent"""
        unblock_main_interaction(self.parent, self.top)
        self.top.destroy()
        
    def center_window(self):
        """居中窗口"""
        width = 650
        height = 500
        
        # Ensure parent info is available
        self.parent.update_idletasks()
        
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() // 2) - (width // 2)
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() // 2) - (height // 2)
        
        if x < 0: x = 0
        if y < 0: y = 0
            
        self.top.geometry(f"{width}x{height}+{x}+{y}")
        self.top.minsize(550, 450)

    def create_widgets(self):
        """创建界面组件"""
        main_frame = ttk.Frame(self.top, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Buttons (Pack at bottom first to ensure visibility)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        ttk.Button(btn_frame, text="保存", command=self.save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="还原默认值", command=self.restore_defaults).pack(side=tk.LEFT, padx=5)

        # Notebook
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 1. 性能与基础
        tab_perf = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab_perf, text="性能与基础")
        self.create_perf_tab(tab_perf)

        # 2. 地图源与功能
        tab_map = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab_map, text="地图源与功能")
        self.create_map_tab(tab_map)

    def create_perf_tab(self, parent):
        """创建性能与基础选项卡"""
        # Seed Concurrency
        grp_seed = ttk.LabelFrame(parent, text="Seed 服务管理配置", padding="16")
        grp_seed.pack(fill=tk.X, pady=5)
        
        ttk.Label(grp_seed, text="并发进程数 (1-16):").grid(row=0, column=0, sticky=tk.W, pady=5)
        sp_conc = ttk.Spinbox(grp_seed, from_=1, to=16, textvariable=self.concurrency_var, width=10)
        sp_conc.grid(row=0, column=1, padx=10, sticky=tk.W, pady=5)
        
        # Retry Policy
        grp_retry = ttk.LabelFrame(parent, text="失败重试策略", padding="16")
        grp_retry.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(grp_retry, text="启用自动重试", variable=self.retry_enabled_var).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(grp_retry, text="最大重试次数:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=10, textvariable=self.max_retries_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(grp_retry, text="重试间隔 (秒):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(grp_retry, from_=1, to=60, textvariable=self.retry_interval_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        # Alert Policy
        grp_alert = ttk.LabelFrame(parent, text="失败告警配置", padding="16")
        grp_alert.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(grp_alert, text="启用失败告警", variable=self.alert_enabled_var).grid(row=0, column=0, sticky=tk.W)

    def create_map_tab(self, parent):
        """创建地图源与功能选项卡"""
        grp_src = ttk.LabelFrame(parent, text="地图源配置", padding="16")
        grp_src.pack(fill=tk.X, pady=5)

        ttk.Label(grp_src, text="Global URL:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_src, textvariable=self.global_url_var, width=50).grid(row=0, column=1, sticky=tk.W, padx=10)

        ttk.Label(grp_src, text="China URL:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_src, textvariable=self.china_url_var, width=50).grid(row=1, column=1, sticky=tk.W, padx=10)

        grp_feat = ttk.LabelFrame(parent, text="地图功能配置", padding="16")
        grp_feat.pack(fill=tk.X, pady=5)

        ttk.Checkbutton(grp_feat, text="启用智能切换 (国内天地图，国外Global)", variable=self.smart_switch_var).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=5)
        ttk.Checkbutton(grp_feat, text="启用离线模式", variable=self.offline_mode_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=5)

        ttk.Label(grp_feat, text="数据缓存根目录:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(grp_feat, textvariable=self.cache_dir_var, width=50).grid(row=2, column=1, sticky=tk.W, padx=10)

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
            self.offline_mode_var.set(False)
            self.cache_dir_var.set("./cache_data")
            
            messagebox.showinfo("提示", "已恢复默认设置，点击保存后生效", parent=self.top)

    def has_changes(self):
        """检查是否有未保存的更改"""
        current = self.get_current_settings()
        return current != self.initial_config

    def on_cancel(self):
        """取消操作时的处理"""
        if self.has_changes():
            if not messagebox.askyesno("确认", "有未保存的更改，确定要取消吗？", parent=self.top):
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
            
            # Update via config_manager
            self.config_mgr.update_map_config(
                advanced_update=new_settings["advanced"],
                sources_update=new_settings["sources"],
                features_update=new_settings["features"],
                source="gui_advancedsetting_manager.save"
            )
            
            if self.on_save_callback:
                self.on_save_callback("高级设置已保存")
            else:
                messagebox.showinfo("成功", "设置已保存", parent=self.top)
            
            self.close()
            
        except Exception as e:
            messagebox.showerror("保存失败", f"保存失败，请重试: {e}", parent=self.top)


def show_advanced_settings_dialog(parent, config_mgr, on_save_callback=None):
    """
    Shows the Advanced Settings Dialog.
    
    Args:
        parent: The parent window.
        config_mgr: The ConfigManager instance.
        on_save_callback: Optional callback function to be called when settings are saved.
                          It receives a success message string.
    """
    AdvancedSettingsDialog(parent, config_mgr, on_save_callback)
