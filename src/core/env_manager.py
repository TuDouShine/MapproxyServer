import os
import sys
import subprocess
import logging

class EnvManager:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        # Check for .venv first, then venv
        if os.path.exists(os.path.join(self.work_dir, ".venv")):
             self.venv_dir = os.path.join(self.work_dir, ".venv")
        else:
             self.venv_dir = os.path.join(self.work_dir, "venv")
             
        self.logger = logging.getLogger("EnvManager")
        
        # Windows specific paths
        if os.name == 'nt':
            self.venv_python = os.path.join(self.venv_dir, "Scripts", "python.exe")
        else:
            self.venv_python = os.path.join(self.venv_dir, "bin", "python")

    def get_venv_python(self):
        return self.venv_python

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
                                self.logger.exception("读取 Python 版本失败")
            except FileNotFoundError:
                self.logger.warning("Python 启动器 (py.exe) 不可用")

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

    def setup_venv(self, base_python_cmd):
        """创建虚拟环境"""
        if os.path.exists(self.venv_dir):
            self.logger.info("虚拟环境目录 'venv' 已存在，跳过创建。")
            return True

        self.logger.info(f"正在使用 {base_python_cmd} 创建虚拟环境...")
        try:
            os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)
            cmd = base_python_cmd + ['-m', 'venv', self.venv_dir]
            subprocess.run(cmd, check=True)
            self.logger.info("虚拟环境创建成功。")
            return True
        except subprocess.CalledProcessError:
            self.logger.exception("创建虚拟环境失败")
            return False
