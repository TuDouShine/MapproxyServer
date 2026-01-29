import os
import subprocess
import logging
from utils import calculate_file_hash, load_json, save_json

REQUIREMENTS_CONTENT = """MapProxy>=1.15.1
Waitress>=2.1.2
Pillow
PyYAML
"""

MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

class DependencyManager:
    def __init__(self, work_dir, venv_python):
        self.work_dir = work_dir
        self.venv_python = venv_python
        self.logger = logging.getLogger("DependencyManager")
        
        self.packages_dir = os.path.join(self.work_dir, "packages")
        self.req_file = os.path.join(self.work_dir, "requirements.txt")
        self.deps_status_file = os.path.join(self.work_dir, "deps_status.json")
        
        # Initialize directories
        os.makedirs(self.packages_dir, exist_ok=True)
        self._ensure_requirements_file()

    def _ensure_requirements_file(self):
        if not os.path.exists(self.req_file):
            self.logger.info(f"生成依赖配置文件: {self.req_file}")
            with open(self.req_file, 'w', encoding='utf-8') as f:
                f.write(REQUIREMENTS_CONTENT)

    def _deps_are_satisfied(self):
        requirements_hash = calculate_file_hash(self.req_file)
        if not requirements_hash:
            return False
        status = load_json(self.deps_status_file)
        if status.get("requirements_hash") != requirements_hash:
            return False
        try:
            result = subprocess.run([self.venv_python, '-m', 'pip', 'check'], capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.info(f"依赖检查发现问题:\n{result.stdout}{result.stderr}")
                return False
        except Exception:
            self.logger.exception("依赖检查失败")
            return False
        return True

    def _save_deps_status(self):
        requirements_hash = calculate_file_hash(self.req_file)
        if requirements_hash:
            save_json(self.deps_status_file, {"requirements_hash": requirements_hash})

    def install_dependencies(self):
        """依赖检查、下载与安装"""
        if self._deps_are_satisfied():
            self.logger.info("依赖已满足，跳过安装。")
            return True

        self.logger.info("尝试从本地 packages 安装依赖...")
        install_cmd = [
            self.venv_python, '-m', 'pip', 'install',
            '--no-index',
            '--find-links', self.packages_dir,
            '-r', self.req_file
        ]
        
        try:
            subprocess.run(install_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.logger.info("依赖已满足或安装成功。")
            self._save_deps_status()
            return True
        except subprocess.CalledProcessError:
            self.logger.info("本地安装失败或依赖缺失，准备下载依赖...")

        self.logger.info("正在从镜像源下载依赖到本地 packages 目录...")
        try:
            download_cmd = [
                self.venv_python, '-m', 'pip', 'download',
                '-d', self.packages_dir,
                '-r', self.req_file,
                '-i', MIRROR_URL
            ]
            subprocess.run(download_cmd, check=True)
            self.logger.info("依赖下载完成。")
        except subprocess.CalledProcessError:
            self.logger.exception("下载依赖失败")
            return False
            
        self.logger.info("\n正在从本地 packages 目录安装依赖...")
        try:
            subprocess.run(install_cmd, check=True)
            self.logger.info("依赖安装成功。")
            self._save_deps_status()
            return True
        except subprocess.CalledProcessError:
            self.logger.exception("安装依赖失败")
            return False
