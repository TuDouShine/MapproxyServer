import os
import subprocess
import threading
import time
import json
import logging
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
    def __init__(self, project_root):
        self.project_root = project_root
        self.mapproxy_conf = os.path.join(project_root, 'mapproxy.yaml')
        self.seed_conf = os.path.join(project_root, 'mapproxy-seed.yaml')
        self.status_file = os.path.join(project_root, 'seed_status.json')
        
        # 探测 mapproxy-seed 路径
        # 1. Windows venv
        win_path = os.path.join(project_root, "venv", "Scripts", "mapproxy-seed.exe")
        # 2. Linux/Unix venv
        unix_path = os.path.join(project_root, "venv", "bin", "mapproxy-seed")
        
        if os.path.exists(win_path):
            self.seed_cmd = win_path
            logger.info(f"Using mapproxy-seed at: {self.seed_cmd}")
        elif os.path.exists(unix_path):
            self.seed_cmd = unix_path
            logger.info(f"Using mapproxy-seed at: {self.seed_cmd}")
        else:
            # Fallback: 假设在 PATH 中
            self.seed_cmd = "mapproxy-seed"
            logger.warning(f"mapproxy-seed not found in venv, assuming it is in PATH.")

    def load_status(self):
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_status(self, status):
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2, ensure_ascii=False)

    def is_seeded(self):
        """
        检查是否已经完成过 Seed。
        为了满足 '跳过时间小于5秒' 的要求，我们依赖状态文件。
        """
        status = self.load_status()
        last_success = status.get('last_success')
        
        if not last_success:
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
                '--concurrency', '2',
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

            # 这里我们同步运行，因为是在后台线程中调用的
            process = subprocess.run(cmd, capture_output=True, text=True)
            
            if process.returncode == 0:
                logger.info("Seed 任务完成。")
                status['last_success'] = datetime.now().isoformat()
                status['status'] = 'completed'
                status['message'] = "All tasks finished successfully."
            else:
                logger.error(f"Seed 任务失败: {process.stderr}")
                status['status'] = 'failed'
                status['error'] = process.stderr
                
        except Exception as e:
            logger.error(f"Seed 执行异常: {e}")
            status['status'] = 'error'
            status['error'] = str(e)
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
