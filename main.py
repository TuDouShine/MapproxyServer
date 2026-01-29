import os
import sys
import argparse
import logging
from utils import setup_logging, get_base_dir, get_work_dir
from env_manager import EnvManager
from dependency_manager import DependencyManager
from service_runner import ServiceRunner
from seed_orchestrator import SeedOrchestrator
from config_manager import ConfigManager

class MapProxyServer:
    def __init__(self, work_dir=None):
        # 1. Determine paths
        self.project_root = get_base_dir()
        if getattr(sys, 'frozen', False):
             self.project_root = sys._MEIPASS
        
        self.work_dir = work_dir if work_dir else get_work_dir(self.project_root)
        os.makedirs(self.work_dir, exist_ok=True)
        
        # 2. Setup Logging
        # Use persistent base dir for logs to match seed.log location
        base_dir = get_base_dir()
        self.logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.logger = setup_logging(os.path.join(self.logs_dir, "server.log"), "MapProxyServer")
        
        # 3. Initialize Managers
        self.config_mgr = ConfigManager(self.work_dir, self.project_root)
        self.env_mgr = EnvManager(self.work_dir)
        self.seed_orch = SeedOrchestrator(self.work_dir)
        # ServiceRunner and DependencyManager need more info later (python path) or initialized later

    def print_step(self, msg):
        self.logger.info(f"\n{'='*50}")
        self.logger.info(f"[*] {msg}")
        self.logger.info(f"{'='*50}")

    def interactive_select_python(self, pythons):
        """Interactive Python selection CLI"""
        self.logger.info("检测到以下 Python 版本：")
        for idx, py in enumerate(pythons):
            self.logger.info(f" [{idx + 1}] {py['desc']}")

        while True:
            try:
                choice = input("\n请选择要使用的 Python 版本序号 (默认 1): ").strip()
                if not choice:
                    choice = 1
                else:
                    choice = int(choice)
                
                if 1 <= choice <= len(pythons):
                    self.logger.info(f"已选择: {pythons[choice - 1]['desc']}")
                    return pythons[choice - 1]['cmd']
                else:
                    self.logger.info("无效的选择，请重试。")
            except ValueError:
                self.logger.info("请输入数字。")
            except (EOFError, KeyboardInterrupt):
                self.logger.info("\n警告: 无法读取输入 (EOF)，回退到默认选择。")
                return pythons[0]['cmd']

    def run(self):
        # Parse Args
        parser = argparse.ArgumentParser(description='MapProxy Server')
        parser.add_argument('--port', type=int, default=8080, help='Service port')
        parser.add_argument('--host', type=str, default="127.0.0.1", help='Service host')
        parser.add_argument('--service', action='store_true', help='Run in service mode (non-interactive)')
        parser.add_argument('--work-dir', type=str, default=None, help='Working directory for data and configs')
        parser.add_argument('--python-path', type=str, default=None, help='Path to Python interpreter to use')
        parser.add_argument('--skip-venv', action='store_true', help='Skip virtual environment creation')
        args, unknown = parser.parse_known_args()

        # Re-init if work-dir changed via args
        if args.work_dir:
            self.work_dir = os.path.abspath(args.work_dir)
            # Re-initialize managers with new work_dir
            self.config_mgr = ConfigManager(self.work_dir, self.project_root)
            self.env_mgr = EnvManager(self.work_dir)
            self.seed_orch = SeedOrchestrator(self.work_dir)
            # Update logging location - Keep logs in base_dir/logs as per requirement
            # self.logs_dir = os.path.join(self.work_dir, "logs")
            # self.logger = setup_logging(os.path.join(self.logs_dir, "server.log"), "MapProxyServer")

        self.logger.info("MapProxy 服务发布程序启动...")
        
        # 4. Initialize Configs
        self.print_step(f"初始化工作目录: {self.work_dir}")
        self.config_mgr.init_configs()
        
        # Load advanced settings and inject into environment for SeedManager
        try:
            adv_config = self.config_mgr.load_advanced_config()
            
            # Concurrency
            if "MAPPROXY_SEED_CONCURRENCY" not in os.environ:
                os.environ["MAPPROXY_SEED_CONCURRENCY"] = str(adv_config.get("concurrency", 2))
                
            # Retry
            retry = adv_config.get("retry", {})
            if retry.get("enabled", False):
                if "MAPPROXY_SEED_MAX_RETRIES" not in os.environ:
                    os.environ["MAPPROXY_SEED_MAX_RETRIES"] = str(retry.get("max_retries", 2))
                if "MAPPROXY_SEED_RETRY_BACKOFF" not in os.environ:
                    os.environ["MAPPROXY_SEED_RETRY_BACKOFF"] = str(retry.get("interval", 5))
            else:
                if "MAPPROXY_SEED_MAX_RETRIES" not in os.environ:
                     os.environ["MAPPROXY_SEED_MAX_RETRIES"] = "0"
                     
            # Alert
            alert = adv_config.get("alert", {})
            if "MAPPROXY_SEED_ALERT_ENABLED" not in os.environ:
                os.environ["MAPPROXY_SEED_ALERT_ENABLED"] = "true" if alert.get("enabled", False) else "false"
                
            self.logger.info("Advanced settings loaded into environment.")
        except Exception as e:
            self.logger.warning(f"Failed to load advanced settings: {e}")
        
        # Validate configs
        self.logger.info("Verifying mapproxy configuration...")
        try:
            self.config_mgr.validate_mapproxy_config()
            self.logger.info("Configuration verification passed.")
        except Exception as e:
            self.logger.error(f"Configuration verification failed: {e}")
            if getattr(sys, 'frozen', False):
                 # In GUI/Frozen mode, maybe we still want to continue or show error?
                 # But main.py is often CLI or backend. 
                 # If config is bad, service will likely fail.
                 # Let's just log for now, or exit if strict.
                 pass
            else:
                 # In CLI mode, we might want to exit?
                 # But let's keep it robust.
                 pass

        # 5. Environment & Dependencies
        selected_python_cmd = None
        venv_python = None
        
        if getattr(sys, 'frozen', False):
             self.logger.info("运行于独立打包环境。")
             # Frozen mode doesn't need venv setup for dependencies usually, as they are bundled?
             # Actually previous logic didn't setup venv in frozen mode.
        else:
            # Determine Python
            if args.skip_venv:
                self.logger.info("跳过虚拟环境创建。")
                venv_python = args.python_path if args.python_path else sys.executable
            else:
                if os.path.exists(self.env_mgr.venv_python):
                    self.logger.info("检测到已有虚拟环境。")
                    venv_python = self.env_mgr.venv_python
                else:
                    # Need to create venv
                    if args.python_path and os.path.exists(args.python_path):
                        selected_python_cmd = [args.python_path]
                        self.logger.info(f"使用指定的 Python: {args.python_path}")
                    else:
                        # Auto detect
                        pythons = self.env_mgr.get_available_pythons()
                        if not pythons:
                            self.logger.error("未检测到可用的 Python 环境，请先安装 Python。")
                            sys.exit(1)
                        
                        if args.service:
                            self.logger.info("非交互模式：自动选择第一个可用版本。")
                            selected_python_cmd = pythons[0]['cmd']
                        else:
                            selected_python_cmd = self.interactive_select_python(pythons)
                    
                    # Create Venv
                    if self.env_mgr.setup_venv(selected_python_cmd):
                        venv_python = self.env_mgr.venv_python
                    else:
                        sys.exit(1)

                # Install Dependencies
                if venv_python:
                    dep_mgr = DependencyManager(self.work_dir, venv_python)
                    if not dep_mgr.install_dependencies():
                         sys.exit(1)

        # 6. Start Seeding
        self.seed_orch.start_seeding(venv_dir=self.env_mgr.venv_dir)

        # 7. Start Service
        svc_runner = ServiceRunner(self.work_dir, self.env_mgr.venv_dir if not getattr(sys, 'frozen', False) else None)
        svc_runner.run_service(args.host, args.port, python_cmd=venv_python)

if __name__ == "__main__":
    server = MapProxyServer()
    server.run()
