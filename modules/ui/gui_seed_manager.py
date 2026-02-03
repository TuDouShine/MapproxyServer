import tkinter as tk
from tkinter import ttk, messagebox
import os
import json
import threading
import shutil
import subprocess
from datetime import datetime
from utils import get_work_dir
from modules.ui.ui_utils import block_main_interaction, unblock_main_interaction

class SeedManagerDialog:
    def __init__(self, parent):
        self.parent = parent
        self.top = tk.Toplevel(parent)
        self.top.title("切片预生成任务监控")
        
        # Variables
        self.seed_status_path = os.path.join(get_work_dir(), "seed_status.json")
        self.seed_progress_var = tk.DoubleVar(value=0.0)
        self.seed_percent_text_var = tk.StringVar(value="0.00%")
        self.seed_rate_var = tk.StringVar(value="0 tiles/s")
        self.seed_eta_var = tk.StringVar(value="--:--:--")
        self.seed_status_text_var = tk.StringVar(value="等待中")
        self.seed_info_var = tk.StringVar(value="已生成: 0 / 0")
        
        self.create_widgets()

        # Initial geometry setup
        # Use initial size 640x400
        self.initial_width = 640
        self.initial_height = 400
        
        # Set geometry initially (will be adjusted by centering)
        self.top.geometry(f"{self.initial_width}x{self.initial_height}")

        # Modal setup with strict blocking
        block_main_interaction(self.parent, self.top)
        
        # Center relative to parent immediately
        self.center_window_relative()
        
        # Bind events for dynamic centering
        # Bind to parent configure to track parent movement/resize
        self.parent_configure_id = self.parent.bind("<Configure>", self.on_parent_configure, add="+")
        
        # Bind to dialog configure to track dialog resize (e.g. content change)
        self.top.bind("<Configure>", self.on_self_configure)
        
        # Bind close event
        self.top.protocol("WM_DELETE_WINDOW", self.on_close)
        self.top.bind("<Escape>", lambda e: self.on_close())
        
        # Start polling
        self.polling = True
        self.poll_seed_status()

    def center_window_relative(self):
        """Center the dialog relative to the parent window"""
        try:
            # Get parent geometry
            parent_x = self.parent.winfo_rootx()
            parent_y = self.parent.winfo_rooty()
            parent_w = self.parent.winfo_width()
            parent_h = self.parent.winfo_height()
            
            # Get dialog geometry
            # Note: winfo_width/height might be 1 if not mapped yet, fallback to reqwidth/reqheight
            dialog_w = self.top.winfo_width()
            dialog_h = self.top.winfo_height()
            
            if dialog_w <= 1: dialog_w = self.top.winfo_reqwidth()
            if dialog_h <= 1: dialog_h = self.top.winfo_reqheight()
            
            # If still 1 (unlikely if widgets packed), force initial default
            if dialog_w <= 1: dialog_w = self.initial_width
            if dialog_h <= 1: dialog_h = self.initial_height

            # Calculate center position
            x = parent_x + (parent_w - dialog_w) // 2
            y = parent_y + (parent_h - dialog_h) // 2
            
            # Ensure not off-screen (basic check)
            screen_w = self.top.winfo_screenwidth()
            screen_h = self.top.winfo_screenheight()
            
            # Adjust if title bar pushes it off top (y < 0)
            if y < 0: y = 0
            
            # Apply only if changed to avoid loop
            current_geo = self.top.geometry()
            # Geometry string format: WxH+X+Y
            # We only care about position update here mainly, but geometry() sets all.
            # Let's just set it. Tkinter handles redundancy well usually.
            self.top.geometry(f"+{x}+{y}")
            
        except Exception:
            pass

    def on_parent_configure(self, event):
        """Handle parent window resize/move"""
        if self.polling: # Only if dialog is active
            self.center_window_relative()

    def on_self_configure(self, event):
        """Handle dialog resize (content change)"""
        # Filter out events that are just moves (x, y change but w, h same) to avoid recursion
        # But since we use center_window_relative which calculates pos based on parent, 
        # moving the dialog won't change the calculation unless parent moved.
        # However, we only want to re-center if SIZE changed.
        # If we re-center on every move, we fight the user trying to drag the dialog.
        # So we should only re-center if the DIMENSIONS changed.
        
        # We need to store last dimensions to check
        if not hasattr(self, '_last_dims'):
            self.center_window_relative()
            self._last_dims = (event.width, event.height)
            return

        if (event.width, event.height) != self._last_dims:
            self._last_dims = (event.width, event.height)
            self.center_window_relative()

    def create_widgets(self):
        main_frame = ttk.Frame(self.top, padding="16")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title/Header (Optional, but dialog title is already set)
        
        # Progress Section
        frame_seed = ttk.LabelFrame(main_frame, text="任务进度", padding="12")
        frame_seed.pack(fill=tk.X, expand=True, pady=12)
        
        # Line 1: Progress Bar + Percentage
        line1 = ttk.Frame(frame_seed)
        line1.pack(fill=tk.X, pady=(0, 12))
        
        self.seed_progress_bar = ttk.Progressbar(line1, orient="horizontal", mode="determinate", variable=self.seed_progress_var)
        self.seed_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
        
        ttk.Label(line1, textvariable=self.seed_percent_text_var, width=8).pack(side=tk.RIGHT)
        
        # Line 2: Stats Grid
        line2 = ttk.Frame(frame_seed)
        line2.pack(fill=tk.X)
        
        stats_frame = ttk.Frame(line2)
        stats_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Grid layout for stats
        ttk.Label(stats_frame, text="状态:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(stats_frame, textvariable=self.seed_status_text_var, foreground="blue").grid(row=0, column=1, sticky=tk.W, padx=(8, 16))
        
        ttk.Label(stats_frame, text="速率:").grid(row=0, column=2, sticky=tk.W)
        ttk.Label(stats_frame, textvariable=self.seed_rate_var).grid(row=0, column=3, sticky=tk.W, padx=(8, 16))
        
        ttk.Label(stats_frame, text="预计剩余:").grid(row=0, column=4, sticky=tk.W)
        ttk.Label(stats_frame, textvariable=self.seed_eta_var).grid(row=0, column=5, sticky=tk.W, padx=(8, 16))
        
        ttk.Label(stats_frame, textvariable=self.seed_info_var).grid(row=0, column=6, sticky=tk.W, padx=(8, 0))
        
        # Actions Section
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=12)
        
        self.btn_package = ttk.Button(action_frame, text="打包结果", command=self.package_seed_output, state="disabled")
        self.btn_package.pack(side=tk.RIGHT)

    def poll_seed_status(self):
        """Poll seed_status.json for updates"""
        if not self.polling:
            return
            
        try:
            if os.path.exists(self.seed_status_path):
                try:
                    with open(self.seed_status_path, 'r', encoding='utf-8') as f:
                        status = json.load(f)
                    
                    # Check staleness (if no update for > 5 seconds, consider offline)
                    last_update_str = status.get("last_update")
                    is_stale = False
                    if last_update_str:
                        try:
                            last_update = datetime.fromisoformat(last_update_str)
                            if (datetime.now() - last_update).total_seconds() > 5:
                                is_stale = True
                        except ValueError:
                            pass
                    
                    if is_stale:
                         self.seed_status_text_var.set("离线")
                         self.btn_package.config(state="disabled")
                    else:
                        # Update Variables
                        percent = status.get("percent", 0.0)
                        self.seed_progress_var.set(percent)
                        self.seed_percent_text_var.set(f"{percent:.2f}%")
                        
                        rate = status.get("rate", 0)
                        self.seed_rate_var.set(f"{rate} tiles/s")
                        
                        eta = status.get("eta", "--:--:--")
                        self.seed_eta_var.set(eta)
                        
                        processed = status.get("processed", 0)
                        total = status.get("total", 0)
                        self.seed_info_var.set(f"已生成: {processed} / {total}")
                        
                        state = status.get("status", "unknown")
                        if state == "running":
                            self.seed_status_text_var.set("生成中")
                            self.btn_package.config(state="disabled")
                        elif state == "starting":
                            self.seed_status_text_var.set("启动中")
                            self.btn_package.config(state="disabled")
                        elif state == "completed" or state == "finished":
                            self.seed_status_text_var.set("已完成")
                            self.btn_package.config(state="normal")
                        elif state == "failed":
                            self.seed_status_text_var.set("失败")
                            self.btn_package.config(state="disabled")
                        elif state == "retrying":
                            self.seed_status_text_var.set("网络重试中")
                            self.btn_package.config(state="disabled")
                        elif state == "error":
                            self.seed_status_text_var.set("错误")
                            self.btn_package.config(state="disabled")
                        else:
                            self.seed_status_text_var.set("等待中")
                            self.btn_package.config(state="disabled")

                except (json.JSONDecodeError, IOError):
                    self.seed_status_text_var.set("读取错误")
            else:
                self.seed_status_text_var.set("未启动")
                self.btn_package.config(state="disabled")
                    
        except Exception:
            # Silent fail for polling
            pass
        
        if self.polling:
            self.top.after(1000, self.poll_seed_status)

    def package_seed_output(self):
        """Package the seed output (cache directory) into a zip file"""
        if not messagebox.askyesno("确认", "打包可能需要几分钟时间，确定要开始吗？", parent=self.top):
            return
            
        work_dir = get_work_dir()
        cache_dir = os.path.join(work_dir, "cache_data")
        output_dir = os.path.join(work_dir, "packaged_tiles")
        
        if not os.path.exists(cache_dir):
            messagebox.showerror("错误", "缓存目录不存在，无法打包。", parent=self.top)
            return
            
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"tiles_{timestamp}"
        zip_path = os.path.join(output_dir, zip_name)
        
        # Show status toast or label? 
        # Since we removed self.log/set_status from parent, we should use a local status or modal wait
        # For simplicity, we can disable the button and show a wait cursor or small label update
        self.seed_status_text_var.set("正在打包...")
        self.btn_package.config(state="disabled")
        
        def run_package():
            try:
                shutil.make_archive(zip_path, 'zip', cache_dir)
                self.top.after(0, lambda: self.on_package_complete(zip_path + ".zip", True))
            except Exception as e:
                self.top.after(0, lambda: self.on_package_complete(str(e), False))
                
        threading.Thread(target=run_package, daemon=True).start()

    def on_package_complete(self, result, success):
        self.btn_package.config(state="normal")
        if success:
            self.seed_status_text_var.set("打包完成")
            if messagebox.askyesno("打包成功", f"文件已保存至:\n{result}\n\n是否打开所在目录？", parent=self.top):
                try:
                    folder = os.path.dirname(result)
                    if os.name == 'nt':
                        subprocess.Popen(['explorer', os.path.abspath(folder)])
                    else:
                        subprocess.Popen(['xdg-open', folder])
                except Exception:
                    pass
        else:
            self.seed_status_text_var.set("打包失败")
            messagebox.showerror("打包失败", f"打包过程中出错:\n{result}", parent=self.top)

    def on_close(self):
        try:
            if hasattr(self, 'parent_configure_id'):
                self.parent.unbind("<Configure>", self.parent_configure_id)
        except Exception:
            pass
            
        # Restore main interaction
        unblock_main_interaction(self.parent, self.top)
        
        self.polling = False
        self.top.destroy()

def show_seed_manager_dialog(parent):
    SeedManagerDialog(parent)
