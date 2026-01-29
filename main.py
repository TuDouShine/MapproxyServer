import os
import sys
import subprocess
import platform
import shutil
import time
import argparse
import json
import hashlib
import logging

# 配置
REQUIREMENTS_CONTENT = """MapProxy>=1.15.1
Waitress>=2.1.2
Pillow
PyYAML
"""

MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

class MapProxyServer:
    def __init__(self, work_dir=None):
        # 基础目录：代码和资源文件所在目录
        if getattr(sys, 'frozen', False):
             self.project_root = sys._MEIPASS
        else:
             self.project_root = os.path.dirname(os.path.abspath(__file__))
        
        # 工作目录：数据和运行时配置目录
        if work_dir:
            self.work_dir = os.path.abspath(work_dir)
        else:
            self.work_dir = self.project_root
            
        # 确保工作目录存在
        os.makedirs(self.work_dir, exist_ok=True)
        
        # 定义路径 (全部基于 work_dir)
        self.venv_dir = os.path.join(self.work_dir, "venv")
        self.packages_dir = os.path.join(self.work_dir, "packages")
        self.req_file = os.path.join(self.work_dir, "requirements.txt")
        self.cache_dir = os.path.join(self.work_dir, "cache_data")
        self.logs_dir = os.path.join(self.work_dir, "logs")
        self.deps_status_file = os.path.join(self.work_dir, "deps_status.json")
        
        # Windows 特定路径
        if os.name == 'nt':
            self.venv_python = os.path.join(self.venv_dir, "Scripts", "python.exe")
            self.venv_pip = os.path.join(self.venv_dir, "Scripts", "pip.exe")
            self.venv_waitress = os.path.join(self.venv_dir, "Scripts", "waitress-serve.exe")
        else:
            self.venv_python = os.path.join(self.venv_dir, "bin", "python")
            self.venv_pip = os.path.join(self.venv_dir, "bin", "pip")
            self.venv_waitress = os.path.join(self.venv_dir, "bin", "waitress-serve")

        self.selected_python = None
        self.logger = None
        
        # 判断运行模式
        self.is_frozen = getattr(sys, 'frozen', False)

    def print_step(self, msg):
        self._log_info(f"\n{'='*50}")
        self._log_info(f"[*] {msg}")
        self._log_info(f"{'='*50}")

    def print_error(self, msg):
        self._log_error(f"\n[!] 错误: {msg}")

    def _init_logging(self):
        os.makedirs(self.logs_dir, exist_ok=True)
        logger = logging.getLogger("MapProxyServer")
        if logger.handlers:
            self.logger = logger
            return
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        file_handler = logging.FileHandler(os.path.join(self.logs_dir, "server.log"), encoding='utf-8')
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        self.logger = logger

    def _log_info(self, msg):
        if self.logger:
            self.logger.info(msg)
        else:
            print(msg)

    def _log_error(self, msg):
        if self.logger:
            self.logger.error(msg)
        else:
            print(msg)

    def _log_exception(self, msg):
        """记录异常并保留堆栈信息"""
        if self.logger:
            self.logger.exception(msg)
        else:
            logging.exception(msg)

    def _load_json(self, path):
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            self._log_exception(f"读取 JSON 失败: {path}")
            return {}

    def _save_json(self, path, data):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            self._log_exception(f"写入 JSON 失败: {path}")

    def _file_hash(self, path):
        if not os.path.exists(path):
            return None
        try:
            hasher = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            self._log_exception(f"计算文件哈希失败: {path}")
            return None

    def _deps_are_satisfied(self):
        requirements_hash = self._file_hash(self.req_file)
        if not requirements_hash:
            return False
        status = self._load_json(self.deps_status_file)
        if status.get("requirements_hash") != requirements_hash:
            return False
        try:
            result = subprocess.run([self.venv_python, '-m', 'pip', 'check'], capture_output=True, text=True)
            if result.returncode != 0:
                self._log_info(f"依赖检查发现问题:\n{result.stdout}{result.stderr}")
                return False
        except Exception:
            self._log_exception("依赖检查失败")
            return False
        return True

    def _save_deps_status(self):
        requirements_hash = self._file_hash(self.req_file)
        if not requirements_hash:
            return
        self._save_json(self.deps_status_file, {"requirements_hash": requirements_hash})

    def check_directories(self):
        """确保必要的目录结构存在，并初始化配置"""
        self.print_step(f"初始化工作目录: {self.work_dir}")
        dirs = [self.packages_dir, self.cache_dir, self.logs_dir]
        for d in dirs:
            if not os.path.exists(d):
                self._log_info(f"创建目录: {d}")
                os.makedirs(d, exist_ok=True)
        
        # 生成/复制 requirements.txt
        if not os.path.exists(self.req_file):
            self._log_info(f"生成依赖配置文件: {self.req_file}")
            with open(self.req_file, 'w', encoding='utf-8') as f:
                f.write(REQUIREMENTS_CONTENT)
        
        # 确保 config.py, mapproxy.yaml 等在工作目录
        # (如果在 GUI 模式下已经 deploy 过，这里是双重保险；如果直接运行 main.py，这里是必须的)
        for filename in ["mapproxy.yaml", "mapproxy-seed.yaml", "config.py", "seed_manager.py"]:
            src = os.path.join(self.project_root, filename)
            dst = os.path.join(self.work_dir, filename)
            if os.path.exists(src) and not os.path.exists(dst):
                 try:
                     shutil.copy2(src, dst)
                     self._log_info(f"已复制默认配置: {filename}")
                 except Exception:
                     self._log_exception(f"复制默认配置失败: {filename}")

    def get_available_pythons(self):
        """获取系统可用的 Python 版本"""
        python_list = []
        if os.name == 'nt':
            try:
                result = subprocess.run(['py', '-0'], capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().splitlines()
                    for line in lines:
                        parts = line.strip().split()
                        if parts:
                            ver_str = parts[0].lstrip('-').lstrip('V:')
                            try:
                                v_res = subprocess.run(['py', f'-{ver_str}', '--version'], capture_output=True, text=True)
                                detailed_ver = v_res.stdout.strip()
                                python_list.append({'cmd': ['py', f'-{ver_str}'], 'desc': f"{detailed_ver} (via py launcher {ver_str})"})
                            except Exception:
                                self._log_exception("读取 Python 版本失败")
            except FileNotFoundError:
                self._log_exception("Python 启动器不可用")

        if not python_list:
            candidates = ['python', 'python3']
            for cmd in candidates:
                try:
                    res = subprocess.run([cmd, '--version'], capture_output=True, text=True)
                    if res.returncode == 0:
                        python_list.append({'cmd': [cmd], 'desc': f"{res.stdout.strip()} (via PATH)"})
                except FileNotFoundError:
                    self._log_exception("PATH 中的 Python 不可用")
                    continue
        
        return python_list

    def select_python(self, auto_select=False, python_path=None):
        """
        用户选择 Python 版本
        auto_select: 是否跳过交互，自动选择默认
        python_path: 显式指定的 Python 路径
        """
        self.print_step("Python 版本选择")
        
        # 如果指定了具体路径，优先使用
        if python_path:
            if os.path.exists(python_path):
                self.selected_python = [python_path]
                self._log_info(f"使用指定的 Python: {python_path}")
                return
            else:
                self._log_info(f"警告: 指定的 Python 路径 {python_path} 不存在，尝试自动检测...")

        pythons = self.get_available_pythons()
        if not pythons:
            self.print_error("未检测到可用的 Python 环境，请先安装 Python。")
            sys.exit(1)

        self._log_info("检测到以下 Python 版本：")
        for idx, py in enumerate(pythons):
            self._log_info(f" [{idx + 1}] {py['desc']}")

        # 自动选择逻辑
        if auto_select:
            self._log_info("非交互模式：自动选择第一个可用版本。")
            self.selected_python = pythons[0]['cmd']
            self._log_info(f"已选择: {pythons[0]['desc']}")
            return

        while True:
            try:
                choice = input("\n请选择要使用的 Python 版本序号 (默认 1): ").strip()
                if not choice:
                    choice = 1
                else:
                    choice = int(choice)
                
                if 1 <= choice <= len(pythons):
                    self.selected_python = pythons[choice - 1]['cmd']
                    self._log_info(f"已选择: {pythons[choice - 1]['desc']}")
                    break
                else:
                    self._log_info("无效的选择，请重试。")
            except ValueError:
                self._log_exception("输入解析失败")
                self._log_info("请输入数字。")
            except (EOFError, KeyboardInterrupt):
                # 捕获 EOFError，这通常发生在服务模式下没有 stdin 时
                self._log_exception("读取输入失败")
                self._log_info("\n警告: 无法读取输入 (EOF)，回退到默认选择。")
                self.selected_python = pythons[0]['cmd']
                self._log_info(f"已选择: {pythons[0]['desc']}")
                break

    def setup_venv(self):
        """创建虚拟环境"""
        self.print_step("虚拟环境检查与创建")
        if os.path.exists(self.venv_dir):
            self._log_info("虚拟环境目录 'venv' 已存在，跳过创建。")
        else:
            self._log_info(f"正在使用 {self.selected_python} 创建虚拟环境...")
            try:
                # 确保父目录存在
                os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)
                
                cmd = self.selected_python + ['-m', 'venv', self.venv_dir]
                subprocess.run(cmd, check=True)
                self._log_info("虚拟环境创建成功。")
            except subprocess.CalledProcessError:
                self._log_exception("创建虚拟环境失败")
                sys.exit(1)

    def manage_dependencies(self):
        """依赖检查、下载与安装"""
        self.print_step("依赖管理")
        if self._deps_are_satisfied():
            self._log_info("依赖已满足，跳过安装。")
            return
        self._log_info("尝试从本地 packages 安装依赖...")
        install_cmd = [
            self.venv_python, '-m', 'pip', 'install',
            '--no-index',
            '--find-links', self.packages_dir,
            '-r', self.req_file
        ]
        
        try:
            subprocess.run(install_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self._log_info("依赖已满足或安装成功。")
            self._save_deps_status()
            return
        except subprocess.CalledProcessError:
            self._log_exception("本地安装失败或依赖缺失")
            self._log_info("本地安装失败或依赖缺失，准备下载依赖...")

        self._log_info("正在从镜像源下载依赖到本地 packages 目录...")
        try:
            download_cmd = [
                self.venv_python, '-m', 'pip', 'download',
                '-d', self.packages_dir,
                '-r', self.req_file,
                '-i', MIRROR_URL
            ]
            subprocess.run(download_cmd, check=True)
            self._log_info("依赖下载完成。")
        except subprocess.CalledProcessError:
            self._log_exception("下载依赖失败")
            
        self._log_info("\n正在从本地 packages 目录安装依赖...")
        try:
            subprocess.run(install_cmd, check=True)
            self._log_info("依赖安装成功。")
            self._save_deps_status()
        except subprocess.CalledProcessError:
            self._log_exception("安装依赖失败")
            sys.exit(1)

    def start_service(self, port=8080, host="127.0.0.1"):
        """启动服务"""
        self.print_step("启动 MapProxy 服务")
        
        # 切换到工作目录，确保 waitress 能找到 config.py 和 mapproxy.yaml
        os.chdir(self.work_dir)
        sys.path.insert(0, self.work_dir) # 确保能 import config
        
        # 集成 Seed Manager
        try:
            # 动态导入，因为 seed_manager 已经在 work_dir
            import seed_manager
            # 重新加载以防万一
            import importlib
            importlib.reload(seed_manager)
            
            # 初始化时传入 work_dir 作为 project_root
            seed_mgr = seed_manager.SeedManager(self.work_dir)
            seed_mgr.start_background_seed()
        except Exception:
            self._log_exception("警告: Seed 管理器启动失败")

        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        
        # 启动逻辑分支
        if self.is_frozen:
            # Frozen 模式：使用内嵌的 waitress
            self._log_info("使用内置环境启动 Waitress...")
            self._log_info(f"监听: http://{display_host}:{port}/demo/")
            self._log_info("按 Ctrl+C 停止服务")
            try:
                from waitress import serve
                # 导入 config.py 中的 application
                # 注意：config.py 必须在 sys.path 中 (已通过 sys.path.insert(0, work_dir) 确保)
                import config
                serve(config.application, host=host, port=port)
            except ImportError:
                self._log_exception("无法导入 Waitress 或配置")
            except Exception:
                self._log_exception("服务运行出错")
        else:
            # 普通模式：使用 venv 中的 waitress
            # 检查 Waitress 是否存在
            if not os.path.exists(self.venv_waitress):
                run_cmd = [self.venv_python, '-m', 'waitress', f'--host={host}', f'--port={port}', 'config:application']
            else:
                run_cmd = [self.venv_waitress, f'--host={host}', f'--port={port}', 'config:application']

            self._log_info(f"启动命令: {' '.join(run_cmd)}")
            self._log_info(f"服务启动中... 请访问 http://{display_host}:{port}/demo/")
            self._log_info("按 Ctrl+C 停止服务")

            try:
                subprocess.run(run_cmd, cwd=self.work_dir)
            except KeyboardInterrupt:
                self._log_exception("服务收到中断信号")
                self._log_info("\n服务已停止。")
            except Exception:
                self._log_exception("服务运行出错")

    def run(self):
        # 解析命令行参数
        parser = argparse.ArgumentParser(description='MapProxy Server')
        parser.add_argument('--port', type=int, default=8080, help='Service port')
        parser.add_argument('--host', type=str, default="127.0.0.1", help='Service host')
        parser.add_argument('--service', action='store_true', help='Run in service mode (non-interactive)')
        parser.add_argument('--work-dir', type=str, default=None, help='Working directory for data and configs')
        parser.add_argument('--python-path', type=str, default=None, help='Path to Python interpreter to use')
        parser.add_argument('--skip-venv', action='store_true', help='Skip virtual environment creation')
        args, unknown = parser.parse_known_args()

        self._init_logging()
        self._log_info("MapProxy 服务发布程序启动...")
        
        # 如果指定了 work_dir，更新实例
        if args.work_dir:
            self.work_dir = os.path.abspath(args.work_dir)
            # 重新初始化路径
            self.__init__(work_dir=args.work_dir)
            self._init_logging()
        
        self.check_directories()
        
        if self.is_frozen:
            # Frozen 模式：跳过环境配置，直接启动
            self._log_info("运行于独立打包环境。")
            self.start_service(port=args.port, host=args.host)
        else:
            # 普通模式：检查 venv
            # 如果是 GUI 调用并通过外部 Python 运行，通常也希望自动化
            # 检查 venv 是否已存在且完好
            
            # 判断是否需要交互式选择
            is_interactive = not args.service
            
            if not args.skip_venv:
                if os.path.exists(self.venv_dir) and os.path.exists(self.venv_python):
                     self._log_info("检测到已有虚拟环境。")
                     self.selected_python = [sys.executable] # 仅用于日志
                else:
                     self.select_python(auto_select=not is_interactive, python_path=args.python_path)
                     self.setup_venv()
                     self.manage_dependencies()
            else:
                # Skip venv mode: assume using the current python or specified python
                self._log_info("跳过虚拟环境创建。")
                if args.python_path:
                    self.venv_python = args.python_path
                else:
                    self.venv_python = sys.executable
                # 同时也调整 waitress 路径
                # 简单假设 waitress 也在同一路径下 (或者在 PATH)
                self.venv_waitress = "waitress-serve" 
                 
            self.start_service(port=args.port, host=args.host)

if __name__ == "__main__":
    server = MapProxyServer()
    server.run()
