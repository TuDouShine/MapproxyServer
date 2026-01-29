import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sys
import os
import json
import subprocess
import threading
import queue
import socket
import shutil
import webbrowser
import yaml
import logging
try:
    import process_manager
except ImportError:
    process_manager = None
from python_detector import find_python_interpreters

# 工作目录名称
LAUNCHER_DIR_NAME = "MapProxyLauncher"

def get_base_dir():
    """获取程序所在的基准目录"""
    if getattr(sys, 'frozen', False):
        # 如果是打包后的 exe，基准目录是 exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是脚本运行，基准目录是脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))

def get_work_dir():
    """获取工作目录（数据存储目录）"""
    return os.path.join(get_base_dir(), LAUNCHER_DIR_NAME)

def get_config_file():
    return os.path.join(get_work_dir(), "config.json")

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
    files_to_copy = [
        "main.py",
        "config.py",
        "seed_manager.py",
        "mapproxy.yaml",
        "mapproxy-seed.yaml",
        "requirements.txt"
    ]
    
    for filename in files_to_copy:
        src = os.path.join(source_dir, filename)
        dst = os.path.join(work_dir, filename)
        
        # 如果源文件存在且目标文件不存在（或者强制覆盖逻辑），则复制
        # 这里为了简单，且为了支持升级，如果源文件存在，我们检查目标是否存在
        # 配置文件如果用户改过，最好不要覆盖。但是代码文件必须覆盖。
        
        if os.path.exists(src):
            if filename.endswith(".yaml") or filename.endswith(".json") or filename == "requirements.txt":
                # 配置文件/数据文件：仅当不存在时复制，以免覆盖用户配置
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
                    # print(f"Deploying code: {filename}")
                except Exception as e:
                    logging.exception(f"Failed to deploy {filename}")

class LauncherApp:
    def __init__(self, root):
        logging.basicConfig(level=logging.INFO)
        self.root = root
        self.root.title("MapProxy Server Launcher")
        self.root.geometry("700x650")
        
        # 变量
        self.python_path_var = tk.StringVar()
        self.port_var = tk.StringVar(value="8080")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.allow_external_var = tk.BooleanVar(value=False)
        self.service_process = None
        self.log_queue = queue.Queue()
        self.server_log_path = os.path.join(get_work_dir(), "logs", "server.log")
        self.server_log_pos = 0
        self.current_host = "127.0.0.1"
        self.logger = logging.getLogger("Launcher")
        
        # 新增状态变量
        self.status_var = tk.StringVar(value="就绪")
        self.service_url_var = tk.StringVar(value="")
        self.status_color = "gray" # 默认颜色
        
        # 部署资源
        deploy_resources()

        # 配置样式
        style = ttk.Style()
        # 移除只读 Combobox 选中时的蓝色背景
        # 尝试覆盖所有可能的状态组合，特别是 focus 和 background 属性
        style.map('TCombobox', 
                  fieldbackground=[('readonly', 'focus', 'white'), ('readonly', 'white')],
                  selectbackground=[('readonly', 'focus', 'white'), ('readonly', 'white')],
                  selectforeground=[('readonly', 'focus', 'black'), ('readonly', 'black')],
                  background=[('readonly', 'focus', 'white'), ('readonly', 'white')])
        
        self.create_widgets()
        self.load_config()
        self.scan_pythons()
        
        # 启动日志更新定时器
        self.root.after(100, self.update_logs)
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

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

    def scan_pythons(self):
        self.log("正在扫描 Python 解释器...")
        interpreters = find_python_interpreters()
        
        # 如果是 Frozen 环境，添加内置 Python 选项
        if getattr(sys, 'frozen', False):
            # 添加一个特殊的标识，或者直接用 sys.executable (但标记为 Internal)
            internal_entry = {'path': sys.executable, 'version': 'Internal (Bundled)', 'source': 'Internal'}
            interpreters.insert(0, internal_entry)
            
        values = [f"{i['version']} - {i['path']}" for i in interpreters]
        self.combo_python['values'] = values
        
        # 尝试恢复之前的选择，或者默认选中第一个
        current = self.python_path_var.get()
        if current and current in values:
            self.combo_python.current(values.index(current))
        elif values:
            self.combo_python.current(0)
            
        self.log(f"扫描完成，找到 {len(interpreters)} 个解释器。")

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

    def is_port_in_use(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0

    def save_config(self):
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

        config = {
            "python_path": python_path,
            "port": int(self.port_var.get()),
            "host": host_value,
            "allow_external_access": bool(self.allow_external_var.get()),
            "selection_label": selection # 保存完整标签以便回显
        }
        
        try:
            with open(get_config_file(), 'w') as f:
                json.dump(config, f)
            self.log("配置已保存。")
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
                logging.exception("保存配置失败")
                messagebox.showerror("错误", f"保存配置失败: {e}")

    def load_config(self):
        config_file = get_config_file()
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
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
                logging.exception("读取配置失败")

    def start_service(self):
        if self.service_process:
            return

        if not self.validate_port_input():
            return
            
        port = int(self.port_var.get())
        self.update_host_from_access()
        host_value = self.host_var.get().strip()
        if self.is_port_in_use(port):
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
            # Internal Mode: 调用 exe 本身进入 service 模式
            # 注意：sys.executable 在 frozen 模式下是 exe 路径
            cmd = [sys.executable, '--service']
        else:
            # External Mode: 调用外部 Python 运行部署好的 main.py
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
                cwd=work_dir 
            )
            
            # 启动线程读取输出
            threading.Thread(target=self.read_process_output, args=(self.service_process,), daemon=True).start()
            
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            
        except Exception as e:
            logging.exception("启动失败")
            self.log(f"启动失败: {e}", "error")
            self.set_status("启动失败", "red")

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

    def on_closing(self):
        """窗口关闭事件处理"""
        # 仅当持有服务进程句柄时才提示停止
        if self.service_process:
            if messagebox.askokcancel("退出", "服务正在运行，确定要停止服务并退出吗？"):
                self.stop_service()
                self.root.destroy()
        else:
            self.root.destroy()

    def show_advanced(self):
        messagebox.showinfo("提示", "高级设置功能开发中...")

    def copy_url(self):
        url = self.service_url_var.get()
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            messagebox.showinfo("提示", "地址已复制到剪贴板")

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

    def get_layer_info(self):
        """解析 mapproxy.yaml 获取图层信息"""
        yaml_path = os.path.join(get_work_dir(), "mapproxy.yaml")
        if not os.path.exists(yaml_path):
            return []
        
        layers_info = []
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                conf = yaml.safe_load(f)
                
            layers = conf.get('layers', [])
            caches = conf.get('caches', {})
            
            for layer in layers:
                name = layer.get('name')
                title = layer.get('title', name)
                sources = layer.get('sources', [])
                
                # 尝试查找缓存格式
                fmt = "Unknown"
                if sources:
                    cache_name = sources[0] # 假设第一个 source 是 cache
                    if cache_name in caches:
                        cache_conf = caches[cache_name]
                        # 查找 format
                        # 通常在 cache -> grids (implicit) -> format? 
                        # 或者 cache -> cache (file) -> ...
                        # 简化：查看 cache 的 source 的 format? 不对，cache 是输出
                        # 查找 cache 的 image options?
                        # 简单起见，查看 cache 定义是否有 image format
                        # 实际上 MapProxy 默认 png 或 jpeg
                        
                        # 尝试从 grids 猜测? 不太准
                        # 尝试直接读取 cache 配置中的 request_format 或 format
                        fmt = cache_conf.get('request_format') or cache_conf.get('format')
                        
                        if not fmt:
                            # 再次深入：如果 cache 的 source 是 demo_source
                            pass
                        
                        if not fmt:
                            fmt = "image/png (Default)"

                layers_info.append({
                    'name': name,
                    'title': title,
                    'format': fmt
                })
        except Exception as e:
            logging.exception("解析 mapproxy.yaml 失败")
            
        return layers_info

    def show_toast(self, message):
        """显示一个无阻塞的浮动提示"""
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True) # 无边框
        
        # 获取主窗口位置，计算居中位置
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        
        # 简单估算 toast 大小
        toast_w = 200
        toast_h = 40
        x = root_x + (root_w - toast_w) // 2
        y = root_y + (root_h - toast_h) // 2
        
        toast.geometry(f"{toast_w}x{toast_h}+{x}+{y}")
        
        label = tk.Label(toast, text=message, bg="#333333", fg="white", padx=10, pady=5, font=("Arial", 10))
        label.pack(fill="both", expand=True)
        
        # 自动关闭
        toast.after(1500, toast.destroy)

    def copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.show_toast(f"已复制: {text}")

    def create_layer_info_widgets(self):
        """创建图层信息显示区域"""
        frame_layers = ttk.LabelFrame(self.root, text="图层信息", padding=10)
        frame_layers.pack(fill="x", padx=10, pady=5)
        
        layers = self.get_layer_info()
        
        if not layers:
            ttk.Label(frame_layers, text="未找到图层配置").pack()
            return
            
        # 表头
        headers_frame = ttk.Frame(frame_layers)
        headers_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(headers_frame, text="图层名称 (点击复制 📋)", font=("Arial", 9), width=35).pack(side="left")
        ttk.Label(headers_frame, text="缓存格式 (点击复制 📋)", font=("Arial", 9), width=20).pack(side="left")
        
        # 列表内容
        content_frame = ttk.Frame(frame_layers)
        content_frame.pack(fill="x")
        
        def on_enter(e):
            e.widget['foreground'] = 'blue'
            e.widget['cursor'] = 'hand2'

        def on_leave(e):
            e.widget['foreground'] = 'black'
            e.widget['cursor'] = 'arrow'

        for layer in layers:
            row = ttk.Frame(content_frame)
            row.pack(fill="x", pady=2)
            
            name = layer['name']
            fmt = layer['format']
            
            # 图层名称 Label
            # 增加一个 📋 图标或者只是文本提示
            lbl_name = tk.Label(row, text=f"{name} 📋", bg="#f0f0f0", fg="black", anchor="w", width=35)
            lbl_name.pack(side="left")
            lbl_name.bind("<Button-1>", lambda e, t=name: self.copy_text(t))
            lbl_name.bind("<Enter>", on_enter)
            lbl_name.bind("<Leave>", on_leave)
            
            # 缓存格式 Label (非粗体)
            lbl_fmt = tk.Label(row, text=f"{fmt} 📋", bg="#f0f0f0", fg="black", anchor="w", width=20, font=("Arial", 9))
            lbl_fmt.pack(side="left", padx=5)
            lbl_fmt.bind("<Button-1>", lambda e, t=fmt: self.copy_text(t))
            lbl_fmt.bind("<Enter>", on_enter)
            lbl_fmt.bind("<Leave>", on_leave)

    def create_widgets(self):
        # 1. Python 选择区域
        frame_py = ttk.LabelFrame(self.root, text="Python 环境设置", padding=10)
        frame_py.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(frame_py, text="Python 版本:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.combo_python = ttk.Combobox(frame_py, textvariable=self.python_path_var, width=60, state="readonly")
        self.combo_python.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # 绑定事件以清除选中高亮，作为双重保险
        def clear_selection(event):
            try:
                # 移除焦点，从而彻底移除高亮
                self.root.focus_set()
                event.widget.selection_clear()
            except:
                pass
        
        self.combo_python.bind("<<ComboboxSelected>>", clear_selection)
        # 注意：FocusIn 事件如果也移除焦点，会导致无法再次点击选择，所以这里只在选中后移除
        # self.combo_python.bind("<FocusIn>", clear_selection)
        
        ttk.Button(frame_py, text="刷新列表", command=self.scan_pythons).grid(row=0, column=2, padx=5, pady=5)

        # 2. 端口设置区域
        frame_port = ttk.LabelFrame(self.root, text="服务设置", padding=10)
        frame_port.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(frame_port, text="服务端口:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_port = ttk.Entry(frame_port, textvariable=self.port_var, width=10)
        self.entry_port.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.entry_port.bind('<KeyRelease>', self.validate_port_input)
        ttk.Label(frame_port, text="(范围: 1-65535)").grid(row=0, column=2, padx=5, pady=5, sticky="w")

        ttk.Label(frame_port, text="绑定 Host:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_host = ttk.Entry(frame_port, textvariable=self.host_var, width=20, state="readonly")
        self.entry_host.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(frame_port, text="(勾选外部访问后将自动绑定 0.0.0.0)").grid(row=1, column=2, padx=5, pady=5, sticky="w")
        chk = ttk.Checkbutton(frame_port, text="允许外部访问（绑定到所有网卡）", variable=self.allow_external_var, command=self.update_host_from_access)
        chk.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="w")

        # 3. 图层信息区域 (新增)
        self.create_layer_info_widgets()

        # 4. 控制按钮区域
        frame_ctrl = ttk.Frame(self.root, padding=10)
        frame_ctrl.pack(fill="x", padx=10)
        
        self.btn_save = ttk.Button(frame_ctrl, text="确认设置", command=self.save_config)
        self.btn_save.pack(side="left", padx=5)
        
        self.btn_start = ttk.Button(frame_ctrl, text="启动服务", command=self.start_service)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ttk.Button(frame_ctrl, text="停止服务", command=self.stop_service, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        
        ttk.Button(frame_ctrl, text="高级设置", command=self.show_advanced).pack(side="right", padx=5)

        # 5. 状态与快捷操作区域
        self.frame_status = ttk.LabelFrame(self.root, text="运行状态", padding=10)
        self.frame_status.pack(fill="x", padx=10, pady=5)
        
        # 状态指示
        frame_status_indicator = ttk.Frame(self.frame_status)
        frame_status_indicator.pack(fill="x", pady=(0, 5))
        
        ttk.Label(frame_status_indicator, text="当前状态:").pack(side="left")
        self.lbl_status = tk.Label(frame_status_indicator, textvariable=self.status_var, font=("Arial", 10, "bold"), fg="gray")
        self.lbl_status.pack(side="left", padx=5)
        
        # 地址与按钮
        frame_actions = ttk.Frame(self.frame_status)
        frame_actions.pack(fill="x")
        
        ttk.Label(frame_actions, text="访问地址:").pack(side="left")
        self.entry_url = ttk.Entry(frame_actions, textvariable=self.service_url_var, width=30, state="readonly")
        self.entry_url.pack(side="left", padx=5)
        
        self.btn_copy = ttk.Button(frame_actions, text="复制", command=self.copy_url, state="disabled")
        self.btn_copy.pack(side="left", padx=2)
        
        self.btn_browser = ttk.Button(frame_actions, text="浏览器打开", command=self.open_browser, state="disabled")
        self.btn_browser.pack(side="left", padx=2)
        
        self.btn_logdir = ttk.Button(frame_actions, text="打开工作目录", command=self.open_work_dir)
        self.btn_logdir.pack(side="left", padx=2)

        # 6. 日志区域
        frame_log = ttk.LabelFrame(self.root, text="运行日志", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.text_log = scrolledtext.ScrolledText(frame_log, height=12, state="disabled")
        self.text_log.pack(fill="both", expand=True)
        self.text_log.tag_config("error", foreground="red")
        self.text_log.tag_config("info", foreground="black")
        self.text_log.tag_config("success", foreground="green")

    def set_status(self, status, color="gray", url=""):
        self.status_var.set(status)
        self.lbl_status.config(fg=color)
        self.service_url_var.set(url)
        
        if url:
            self.btn_copy.config(state="normal")
            self.btn_browser.config(state="normal")
        else:
            self.btn_copy.config(state="disabled")
            self.btn_browser.config(state="disabled")

if __name__ == "__main__":
    # 命令行参数检查，决定运行模式
    if '--service' in sys.argv:
        # Service 模式：调用 main.py 的服务逻辑
        # 注意：这里我们需要从 main.py 导入 MapProxyServer
        # 如果是打包环境，main 模块应该可以直接导入（因为它被打包了）
        # 如果是脚本环境，main.py 就在旁边
        try:
            from main import MapProxyServer
            server = MapProxyServer()
            server.run()
        except Exception as e:
            # 如果出错，写到 stderr，会被父进程（GUI）捕获
            print(f"Service startup failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # GUI 模式
        root = tk.Tk()
        app = LauncherApp(root)
        root.mainloop()
