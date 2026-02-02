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
        
        # Load current settings
        self.config = self.config_mgr.load_advanced_config()
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
        block_main_interaction(self.parent, self.top)
        
        self.top.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def close(self):
        """Close dialog and re-enable parent"""
        unblock_main_interaction(self.parent, self.top)
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
