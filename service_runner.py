import os
import sys
import subprocess
import logging

class ServiceRunner:
    def __init__(self, work_dir, venv_dir=None):
        self.work_dir = work_dir
        self.venv_dir = venv_dir
        self.logger = logging.getLogger("ServiceRunner")
        self.is_frozen = getattr(sys, 'frozen', False)
        
        # Windows specific paths if venv is provided
        self.venv_python = None
        self.venv_waitress = None
        
        if self.venv_dir:
            if os.name == 'nt':
                self.venv_python = os.path.join(self.venv_dir, "Scripts", "python.exe")
                self.venv_waitress = os.path.join(self.venv_dir, "Scripts", "waitress-serve.exe")
            else:
                self.venv_python = os.path.join(self.venv_dir, "bin", "python")
                self.venv_waitress = os.path.join(self.venv_dir, "bin", "waitress-serve")

    def run_service(self, host, port, python_cmd=None, threads=16):
        """Start the MapProxy service"""
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        
        # Ensure we are in work_dir so logs/config paths are consistent
        os.chdir(self.work_dir)

        if self.is_frozen:
            self._run_frozen(host, port, display_host, threads)
        else:
            self._run_venv(host, port, display_host, python_cmd, threads)

    def _run_frozen(self, host, port, display_host, threads=16):
        self.logger.info("使用内置环境启动 Waitress...")
        self.logger.info(f"监听: http://{display_host}:{port}/demo/")
        self.logger.info(f"工作线程数: {threads}")
        self.logger.info("按 Ctrl+C 停止服务")
        try:
            from waitress import serve
            from mapproxy.wsgiapp import make_wsgi_app

            mapproxy_conf = os.path.join(self.work_dir, "mapproxy_config", "mapproxy.yaml")
            if not os.path.exists(mapproxy_conf):
                raise FileNotFoundError(f"MapProxy 配置文件不存在: {mapproxy_conf}")

            application = make_wsgi_app(mapproxy_conf)
            print(f"INFO:waitress:Serving on http://{display_host}:{port}")
            serve(application, host=host, port=port, threads=threads)
        except ImportError:
            self.logger.exception("无法导入 Waitress 或配置")
        except Exception:
            self.logger.exception("服务运行出错")

    def _run_venv(self, host, port, display_host, python_cmd=None, threads=16):
        cmd_prefix = None
        if python_cmd:
            if isinstance(python_cmd, str):
                cmd_prefix = [python_cmd]
            elif isinstance(python_cmd, list):
                cmd_prefix = python_cmd
            else:
                cmd_prefix = [str(python_cmd)]
        elif self.venv_dir:
            if not os.path.exists(self.venv_python):
                self.logger.warning(f"Venv python not found at {self.venv_python}")
            cmd_prefix = [self.venv_python]
        else:
            self.logger.error("No python environment available (venv_dir not set and python_cmd not provided).")
            return

        import json
        py_work_dir = json.dumps(self.work_dir)
        py_host = json.dumps(str(host))
        py_port = int(port)
        py_threads = int(threads)

        code = (
            "import os, sys\n"
            "try:\n"
            "    from waitress import serve\n"
            "    from mapproxy.wsgiapp import make_wsgi_app\n"
            f"    conf = os.path.join({py_work_dir}, 'mapproxy_config', 'mapproxy.yaml')\n"
            "    if not os.path.exists(conf):\n"
            "        raise FileNotFoundError(f'MapProxy 配置文件不存在: {conf}')\n"
            "    app = make_wsgi_app(conf)\n"
            f"    print('INFO:waitress:Serving on http://{display_host}:{py_port}')\n"
            f"    serve(app, host={py_host}, port={py_port}, threads={py_threads})\n"
            "except Exception as e:\n"
            "    sys.stderr.write(str(e) + '\\n')\n"
            "    raise\n"
        )

        run_cmd = cmd_prefix + ['-c', code]

        self.logger.info(f"启动命令: {' '.join(run_cmd)}")
        self.logger.info(f"服务启动中... 请访问 http://{display_host}:{port}/demo/")
        self.logger.info("按 Ctrl+C 停止服务")

        try:
            subprocess.run(run_cmd, cwd=self.work_dir)
        except KeyboardInterrupt:
            self.logger.info("\n服务已停止。")
        except Exception:
            self.logger.exception("服务运行出错")
