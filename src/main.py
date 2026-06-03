import os
import sys
# 确保可以导入 src.core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import platform
import shutil
import time
import argparse

# 配置
REQUIREMENTS_CONTENT = """MapProxy>=1.15.1
Waitress>=2.1.2
Pillow
PyYAML
psutil>=5.9.0
"""

MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

# 延迟导入 utils，防止在 work_dir 初始化前导入失败
utils = None

class MapProxyServer:
    def __init__(self, work_dir=None):
        # 源码目录 src/
        self.src_dir = os.path.dirname(os.path.abspath(__file__))
        # 项目根目录
        self.project_root = os.path.dirname(self.src_dir)
        if getattr(sys, 'frozen', False):
            # 打包环境下，project_root 是临时解压目录
            pass
            
        # 确定工作目录
        if work_dir:
            self.work_dir = work_dir
        elif getattr(sys, 'frozen', False):
            # Frozen GUI 模式：默认在 exe 同级目录下的 MapProxyLauncher
            exe_dir = os.path.dirname(sys.executable)
            self.work_dir = os.path.join(exe_dir, "MapProxyLauncher")
        else:
            # 源码模式：默认在当前目录的上一级 (项目根目录)
            self.work_dir = self.project_root

        # 路径定义
        self.venv_dir = os.path.join(self.work_dir, "venv")
        self.packages_dir = os.path.join(self.work_dir, "packages")
        self.cache_dir = os.path.join(self.work_dir, "cache_data")
        self.logs_dir = os.path.join(self.work_dir, "logs")
        self.req_file = os.path.join(self.work_dir, "requirements.txt")
        
        # 初始化日志 (集中式)
        if utils:
            try:
                utils.setup_logging(self.logs_dir)
            except AttributeError:
                # 可能导入了错误的 utils 模块 (例如 site-packages 中的同名模块)
                print("Warning: 'utils' module has no 'setup_logging'.")
        
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
        
        # 判断运行模式
        self.is_frozen = getattr(sys, 'frozen', False)

    def print_step(self, msg):
        print(f"\n{'='*50}")
        print(f"[*] {msg}")
        print(f"{'='*50}")

    def print_error(self, msg):
        print(f"\n[!] 错误: {msg}")

    def check_directories(self):
        """确保必要的目录结构存在，并初始化配置"""
        self.print_step(f"初始化工作目录: {self.work_dir}")
        dirs = [self.packages_dir, self.cache_dir, self.logs_dir]
        for d in dirs:
            if not os.path.exists(d):
                print(f"创建目录: {d}")
                os.makedirs(d, exist_ok=True)
        
        # 生成/复制 requirements.txt
        if not os.path.exists(self.req_file):
            print(f"生成依赖配置文件: {self.req_file}")
            with open(self.req_file, 'w', encoding='utf-8') as f:
                f.write(REQUIREMENTS_CONTENT)
        
        # 确保 config.py, mapproxy.yaml 等在工作目录
        # (如果在 GUI 模式下已经 deploy 过，这里是双重保险；如果直接运行 main.py，这里是必须的)
        items_to_copy = [
            ("src/core/config.py", "src/core/config.py"),
            ("src/core/seed_manager.py", "src/core/seed_manager.py"),
            ("src/core/utils.py", "src/core/utils.py"),
            ("configs/mapproxy.yaml", "configs/mapproxy.yaml"),
            ("configs/mapproxy-seed.yaml", "configs/mapproxy-seed.yaml"),
        ]
        
        for src_rel, dst_rel in items_to_copy:
            src = os.path.join(self.project_root, src_rel)
            dst = os.path.join(self.work_dir, dst_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(src) and not os.path.exists(dst):
                 try:
                     shutil.copy2(src, dst)
                     print(f"已复制默认配置: {dst_rel}")
                 except:
                     pass
        
        # 再次尝试导入 utils并配置日志 (如果之前失败)
        global utils
        if not utils:
            # 确保工作目录在 path 中
            if self.work_dir not in sys.path:
                sys.path.insert(0, self.work_dir)
                
            try:
                from src.core import utils
                utils.setup_logging(self.logs_dir)
                print("Utils module loaded and logging configured.")
            except ImportError as e:
                # 尝试从当前目录导入 (如果是在 dist 目录下运行)
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("utils", os.path.join(self.work_dir, "src", "core", "utils.py"))
                    if spec and spec.loader:
                        utils = importlib.util.module_from_spec(spec)
                        sys.modules["src.core.utils"] = utils
                        spec.loader.exec_module(utils)
                        utils.setup_logging(self.logs_dir)
                        print("Utils module loaded from work_dir.")
                except Exception as ex:
                    print(f"Warning: Could not import utils: {e}, {ex}")

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
                            except:
                                pass
            except FileNotFoundError:
                pass

        if not python_list:
            candidates = ['python', 'python3']
            for cmd in candidates:
                try:
                    res = subprocess.run([cmd, '--version'], capture_output=True, text=True)
                    if res.returncode == 0:
                        python_list.append({'cmd': [cmd], 'desc': f"{res.stdout.strip()} (via PATH)"})
                except FileNotFoundError:
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
                 print(f"使用指定的 Python: {python_path}")
                 return
             else:
                 print(f"警告: 指定的 Python 路径 {python_path} 不存在，尝试自动检测...")

        pythons = self.get_available_pythons()
        if not pythons:
            self.print_error("未检测到可用的 Python 环境，请先安装 Python。")
            sys.exit(1)

        print("检测到以下 Python 版本：")
        for idx, py in enumerate(pythons):
            print(f" [{idx + 1}] {py['desc']}")

        # 自动选择逻辑
        if auto_select:
            print("非交互模式：自动选择第一个可用版本。")
            self.selected_python = pythons[0]['cmd']
            print(f"已选择: {pythons[0]['desc']}")
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
                    print(f"已选择: {pythons[choice - 1]['desc']}")
                    break
                else:
                    print("无效的选择，请重试。")
            except ValueError:
                print("请输入数字。")
            except (EOFError, KeyboardInterrupt):
                # 捕获 EOFError，这通常发生在服务模式下没有 stdin 时
                print("\n警告: 无法读取输入 (EOF)，回退到默认选择。")
                self.selected_python = pythons[0]['cmd']
                print(f"已选择: {pythons[0]['desc']}")
                break

    def setup_venv(self):
        """创建虚拟环境"""
        self.print_step("虚拟环境检查与创建")
        if os.path.exists(self.venv_dir):
            print("虚拟环境目录 'venv' 已存在，跳过创建。")
        else:
            print(f"正在使用 {self.selected_python} 创建虚拟环境...")
            try:
                # 确保父目录存在
                os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)
                
                cmd = self.selected_python + ['-m', 'venv', self.venv_dir]
                subprocess.run(cmd, check=True)
                print("虚拟环境创建成功。")
            except subprocess.CalledProcessError as e:
                self.print_error(f"创建虚拟环境失败: {e}")
                sys.exit(1)

    def manage_dependencies(self):
        """依赖检查、下载与安装"""
        self.print_step("依赖管理")
        print("尝试从本地 packages 安装依赖...")
        install_cmd = [
            self.venv_python, '-m', 'pip', 'install',
            '--no-index',
            '--find-links', self.packages_dir,
            '-r', self.req_file
        ]
        
        try:
            subprocess.run(install_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            print("依赖已满足或安装成功。")
            return
        except subprocess.CalledProcessError:
            print("本地安装失败或依赖缺失，准备下载依赖...")

        print("正在从镜像源下载依赖到本地 packages 目录...")
        try:
            download_cmd = [
                self.venv_python, '-m', 'pip', 'download',
                '-d', self.packages_dir,
                '-r', self.req_file,
                '-i', MIRROR_URL
            ]
            subprocess.run(download_cmd, check=True)
            print("依赖下载完成。")
        except subprocess.CalledProcessError as e:
            self.print_error(f"下载依赖失败: {e}")
            
        print("\n正在从本地 packages 目录安装依赖...")
        try:
            subprocess.run(install_cmd, check=True)
            print("依赖安装成功。")
        except subprocess.CalledProcessError as e:
            self.print_error(f"安装依赖失败: {e}")
            sys.exit(1)

    def start_service(self, port=8080, enable_online_cache=False):
        """启动服务"""
        self.print_step("启动 MapProxy 服务")
        
        # 切换到工作目录，确保 waitress 能找到 src.core.config 和 mapproxy.yaml
        os.chdir(self.work_dir)
        sys.path.insert(0, self.work_dir) # 确保能 import src.core.config
        
        # 设置离线模式环境变量
        if not enable_online_cache:
            os.environ['MAPPROXY_OFFLINE_MODE'] = '1'
        else:
            os.environ.pop('MAPPROXY_OFFLINE_MODE', None)
        
        # 集成 Seed Manager
        if enable_online_cache:
            try:
                # 动态导入，因为 seed_manager 已经在 work_dir
                from src.core import seed_manager
                # 重新加载以防万一
                import importlib
                importlib.reload(seed_manager)
                
                # 初始化时传入 work_dir 作为 project_root
                seed_mgr = seed_manager.SeedManager(self.work_dir)
                seed_mgr.start_background_seed()
                print("已开启后台在线缓存(mapproxy-seed)。")
            except Exception as e:
                print(f"警告: Seed 管理器启动失败: {e}")
        else:
            print("未开启后台在线缓存。")

        host = '0.0.0.0'
        
        # 启动逻辑分支
        if self.is_frozen:
            # Frozen 模式：使用内嵌的 waitress
            print("使用内置环境启动 Waitress...")
            print(f"监听: http://{host}:{port}/demo/")
            print("按 Ctrl+C 停止服务")
            try:
                from waitress import serve
                # 导入 src.core.config 中的 application
                from src.core import config
                serve(config.application, host=host, port=port)
            except ImportError as e:
                self.print_error(f"无法导入 Waitress 或配置: {e}")
            except Exception as e:
                self.print_error(f"服务运行出错: {e}")
        else:
            # 普通模式：使用 venv 中的 waitress
            # 检查 Waitress 是否存在
            if not os.path.exists(self.venv_waitress):
                run_cmd = [self.venv_python, '-m', 'waitress', f'--host={host}', f'--port={port}', 'src.core.config:application']
            else:
                run_cmd = [self.venv_waitress, f'--host={host}', f'--port={port}', 'src.core.config:application']

            print(f"启动命令: {' '.join(run_cmd)}")
            print(f"服务启动中... 请访问 http://localhost:{port}/demo/")
            print("按 Ctrl+C 停止服务")

            try:
                subprocess.run(run_cmd, cwd=self.work_dir)
            except KeyboardInterrupt:
                print("\n服务已停止。")
            except Exception as e:
                self.print_error(f"服务运行出错: {e}")

    def run(self):
        # 解析命令行参数
        parser = argparse.ArgumentParser(description='MapProxy Server')
        parser.add_argument('--port', type=int, default=8080, help='Service port')
        parser.add_argument('--service', action='store_true', help='Run in service mode (non-interactive)')
        parser.add_argument('--work-dir', type=str, default=None, help='Working directory for data and configs')
        parser.add_argument('--python-path', type=str, default=None, help='Path to Python interpreter to use')
        parser.add_argument('--skip-venv', action='store_true', help='Skip virtual environment creation')
        parser.add_argument('--enable-online-cache', action='store_true', help='Enable background online caching (mapproxy-seed)')
        args, unknown = parser.parse_known_args()

        print("MapProxy 服务发布程序启动...")
        
        # 如果指定了 work_dir，更新实例
        if args.work_dir:
             self.work_dir = os.path.abspath(args.work_dir)
             # 重新初始化路径
             self.__init__(work_dir=args.work_dir)
        
        self.check_directories()
        
        if self.is_frozen:
            # Frozen 模式：跳过环境配置，直接启动
            print("运行于独立打包环境。")
            self.start_service(port=args.port, enable_online_cache=args.enable_online_cache)
        else:
            # 普通模式：检查 venv
            # 如果是 GUI 调用并通过外部 Python 运行，通常也希望自动化
            # 检查 venv 是否已存在且完好
            
            # 判断是否需要交互式选择
            is_interactive = not args.service
            
            if not args.skip_venv:
                if os.path.exists(self.venv_dir) and os.path.exists(self.venv_python):
                     print("检测到已有虚拟环境。")
                     self.selected_python = [sys.executable] # 仅用于日志
                else:
                     self.select_python(auto_select=not is_interactive, python_path=args.python_path)
                     self.setup_venv()
                     self.manage_dependencies()
            else:
                # Skip venv mode: assume using the current python or specified python
                print("跳过虚拟环境创建。")
                if args.python_path:
                    self.venv_python = args.python_path
                else:
                    self.venv_python = sys.executable
                # 同时也调整 waitress 路径
                # 简单假设 waitress 也在同一路径下 (或者在 PATH)
                self.venv_waitress = "waitress-serve" 
                 
            self.start_service(port=args.port, enable_online_cache=args.enable_online_cache)

if __name__ == "__main__":
    server = MapProxyServer()
    server.run()
