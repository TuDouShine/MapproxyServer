import os
import subprocess
import threading
import time
import json
import logging
import hashlib
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/seed.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SeedManager")

class SeedManager:
    def __init__(self, project_root, venv_dir=None):
        self.project_root = project_root
        self.mapproxy_conf = os.path.join(project_root, 'mapproxy.yaml')
        self.seed_conf = os.path.join(project_root, 'mapproxy-seed.yaml')
        self.status_file = os.path.join(project_root, 'seed_status.json')
        self.seed_concurrency = self._get_seed_concurrency()
        self.seed_max_retries, self.seed_retry_backoff = self._get_seed_retry_config()
        self.alert_enabled = self._get_seed_alert_config()
        
        # 探测 mapproxy-seed 路径
        self.seed_cmd = "mapproxy-seed"
        
        # Determine venv path
        search_dirs = []
        if venv_dir:
            search_dirs.append(venv_dir)
        
        search_dirs.append(os.path.join(project_root, ".venv"))
        search_dirs.append(os.path.join(project_root, "venv"))
        
        found = False
        for v_dir in search_dirs:
            if os.name == 'nt':
                path = os.path.join(v_dir, "Scripts", "mapproxy-seed.exe")
            else:
                path = os.path.join(v_dir, "bin", "mapproxy-seed")
            
            if os.path.exists(path):
                self.seed_cmd = path
                logger.info(f"Using mapproxy-seed at: {self.seed_cmd}")
                found = True
                break
        
        if not found:
            logger.warning(f"mapproxy-seed not found in venv(s), assuming it is in PATH.")

    def _get_seed_concurrency(self):
        raw_value = os.environ.get("MAPPROXY_SEED_CONCURRENCY", "").strip()
        if not raw_value:
            return 2
        try:
            value = int(raw_value)
        except ValueError:
            logger.warning(f"Invalid MAPPROXY_SEED_CONCURRENCY: {raw_value}, using default 2")
            return 2
        if value < 1 or value > 16:
            logger.warning(f"MAPPROXY_SEED_CONCURRENCY out of range: {value}, using default 2")
            return 2
        return value

    def _compute_seed_hash(self):
        if not os.path.exists(self.mapproxy_conf) or not os.path.exists(self.seed_conf):
            return None
        try:
            hasher = hashlib.sha256()
            for path in [self.mapproxy_conf, self.seed_conf]:
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        hasher.update(chunk)
                hasher.update(b'|')
            return hasher.hexdigest()
        except Exception:
            logger.exception("Failed to compute seed hash")
            return None

    def _get_seed_retry_config(self):
        raw_retries = os.environ.get("MAPPROXY_SEED_MAX_RETRIES", "").strip()
        raw_backoff = os.environ.get("MAPPROXY_SEED_RETRY_BACKOFF", "").strip()
        max_retries = 2
        backoff = 5
        if raw_retries:
            try:
                max_retries = int(raw_retries)
            except ValueError:
                logger.warning(f"Invalid MAPPROXY_SEED_MAX_RETRIES: {raw_retries}, using default 2")
                max_retries = 2
        if raw_backoff:
            try:
                backoff = int(raw_backoff)
            except ValueError:
                logger.warning(f"Invalid MAPPROXY_SEED_RETRY_BACKOFF: {raw_backoff}, using default 5")
                backoff = 5
        if max_retries < 0:
            max_retries = 0
        if backoff < 0:
            backoff = 0
        return max_retries, backoff

    def _get_seed_alert_config(self):
        enabled = os.environ.get("MAPPROXY_SEED_ALERT_ENABLED", "false").lower() == "true"
        return enabled

    def send_alert(self, message):
        if not self.alert_enabled:
            return
        logger.warning(f"[ALERT] Seed Failure: {message}")

    def load_status(self):
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                logger.exception("Failed to load status file")
        return {}

    def save_status(self, status):
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to save status file")

    def is_seeded(self):
        """
        检查是否已经完成过 Seed。
        为了满足 '跳过时间小于5秒' 的要求，我们依赖状态文件。
        """
        status = self.load_status()
        last_success = status.get('last_success')
        current_hash = self._compute_seed_hash()

        if not last_success:
            return False
        if not current_hash:
            return False
        if status.get('seed_hash') != current_hash:
            logger.info("Seed 配置已变更，需重新执行。")
            return False
        
        # 这里可以加入更复杂的逻辑，比如检查配置文件是否修改
        # 简单起见，如果状态显示成功，我们假设已完成
        logger.info(f"检测到上次 Seed 成功时间: {last_success}，跳过全面检查。")
        return True

    def run_seed_process(self):
        """
        执行实际的 seed 命令
        """
        logger.info("开始执行 Seed 任务...")
        status = self.load_status()
        status['last_run_start'] = datetime.now().isoformat()
        status['status'] = 'running'
        self.save_status(status)

        try:
            current_hash = self._compute_seed_hash()
            # 构造命令
            # --concurrency 2: 控制并发
            # --quiet: 减少输出
            # --continue: 继续之前的进度 (如果支持) - mapproxy-seed 默认行为就是跳过存在的
            # 注意: mapproxy-seed 没有 --reseed 参数，那是 cleanup 用的。
            # 我们使用默认模式，它会计算瓦片，如果文件存在且比 refresh_before 新，则跳过。
            
            cmd = [
                self.seed_cmd,
                '-f', self.mapproxy_conf,
                '-s', self.seed_conf,
                '--concurrency', str(self.seed_concurrency),
                '--quiet'
            ]
            
            # 使用 Popen 以便实时获取输出或后台运行
            logger.info(f"执行命令: {' '.join(cmd)}")
            
            # 验证可执行文件是否存在
            executable = cmd[0]
            if not os.path.isabs(executable):
                import shutil
                if shutil.which(executable) is None:
                     raise FileNotFoundError(f"命令 '{executable}' 未在系统路径中找到。请检查依赖是否安装。")
            elif not os.path.exists(executable):
                 raise FileNotFoundError(f"可执行文件不存在: {executable}")

            # Windows 下隐藏控制台窗口
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            attempt = 0
            while True:
                # 使用 Popen 替代 run 以便更好地控制窗口
                process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
                stdout, stderr = process.communicate()
                
                if process.returncode == 0:
                    logger.info("Seed 任务完成。")
                    status['last_success'] = datetime.now().isoformat()
                    status['status'] = 'completed'
                    status['message'] = "All tasks finished successfully."
                    if current_hash:
                        status['seed_hash'] = current_hash
                    break
                
                logger.error(f"Seed 任务失败: {stderr}")
                status['status'] = 'failed'
                status['error'] = stderr
                if attempt >= self.seed_max_retries:
                    self.send_alert(f"Seed 任务在重试 {self.seed_max_retries} 次后仍然失败。最后一次错误: {stderr}")
                    break
                attempt += 1
                if self.seed_retry_backoff > 0:
                    time.sleep(self.seed_retry_backoff)
                
        except Exception:
            logger.exception("Seed 执行异常")
            status['status'] = 'error'
            status['error'] = "Seed 执行异常"
        finally:
            status['last_run_end'] = datetime.now().isoformat()
            self.save_status(status)

    def start_background_seed(self):
        """
        启动后台线程进行 Seed
        """
        if self.is_seeded():
            logger.info("预缓存已就绪，无需重复执行。")
            return

        logger.info("检测到预缓存未完成或需要更新，启动后台 Seed 任务...")
        thread = threading.Thread(target=self.run_seed_process)
        thread.daemon = True  # 设置为守护线程，主程序退出时它也会退出（或者设为 False 保证跑完）
        # 考虑到 seed 可能很慢，设为 Daemon 意味着如果用户 Ctrl+C 停止服务，seed 也会停。
        # 这符合 '--continue' 的使用场景，下次启动会继续。
        thread.start()

# 简单的测试入口
if __name__ == "__main__":
    manager = SeedManager(os.path.dirname(os.path.abspath(__file__)))
    manager.start_background_seed()
    # 模拟主进程运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
