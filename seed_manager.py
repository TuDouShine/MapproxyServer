import os
import subprocess
import threading
import time
import json
import logging
import hashlib
import queue
import re
from datetime import datetime

# 配置日志
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

class SeedContextFilter(logging.Filter):
    """Ensures 'seed_name' is present in the record."""
    def filter(self, record):
        if not hasattr(record, 'seed_name'):
            record.seed_name = '-'
        return True

class StrictInfoFilter(logging.Filter):
    """Filters only INFO level records."""
    def filter(self, record):
        return record.levelno == logging.INFO

logger = logging.getLogger("SeedManager")
logger.setLevel(logging.INFO)
logger.addFilter(SeedContextFilter())

# Clear existing handlers to avoid duplicates during reload
if logger.handlers:
    logger.handlers.clear()

# File Handler (Captures all levels, uses unified format)
file_handler = logging.FileHandler(os.path.join(log_dir, "seed.log"), encoding='utf-8')
# Removed StrictInfoFilter to allow WARNING/ERROR
# Standardized Format: Timestamp | Level | SeedName | Module | Message
formatter = logging.Formatter('%(asctime)s | %(levelname)-2s | %(name)s | %(seed_name)s | %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Stream Handler (Standard)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

logger.propagate = False

class ProgressMonitor:
    def __init__(self, callback=None, progress_queue=None):
        self.callback = callback
        self.progress_queue = progress_queue if progress_queue else queue.Queue()
        self.start_time = time.time()
        self.total_tiles = 0
        self.processed_tiles = 0
        self.last_update_time = 0
        self.update_interval = 1.0 # 1 second
        self.current_task = None
        
    def reset(self) -> None:
        """重置进度计时与累计值，适配多任务 seed 任务切换场景。"""
        self.start_time = time.time()
        self.total_tiles = 0
        self.processed_tiles = 0
        self.last_update_time = 0

    def parse_line(self, line: str, seed_name: str | None = None) -> bool:
        """解析 mapproxy-seed 输出行并上报进度（可选携带 seed 任务名）。"""
        # 1. Try standard format: [15:20:00] 10.50% 100/1000 (15 tiles/s)
        match = re.search(r'\[(.*?)\].*?\s+([0-9.]+)%\s+([0-9]+)\s*/\s*([0-9]+)\s+\(\s*([0-9]+)\s+tiles/s\)', line)
        if match:
            _, percent, processed, total, rate = match.groups()
            self.update(float(percent), int(processed), int(total), int(rate), seed_name=seed_name)
            return True
            
        # 2. Try format without total/rate (observed in logs): 
        # [10:55:50]  4   3.12% -20037508.34279, ... (42 tiles)
        match_alt = re.search(r'\[(.*?)\].*?\s+([0-9.]+)%.*?\(\s*([0-9]+)\s+tiles\)', line)
        if match_alt:
            _, percent, processed = match_alt.groups()
            # Calculate total and rate internally
            self.update_alt(float(percent), int(processed), seed_name=seed_name)
            return True
            
        # 3. Detect Retry/Error messages for status updates
        if "Retries left" in line or "Retry in" in line:
            self.report_status("retrying", line, seed_name=seed_name)
            return True
            
        return False

    def update_alt(self, percent: float, processed: int, seed_name: str | None = None) -> None:
        """处理缺少 total/rate 的输出格式并推断缺失字段。"""
        now = time.time()
        
        # Calculate rate based on processed difference
        rate = 0
        if self.last_update_time > 0 and now > self.last_update_time:
            diff_processed = processed - self.processed_tiles
            diff_time = now - self.last_update_time
            if diff_time > 0 and diff_processed >= 0:
                rate = int(diff_processed / diff_time)
                
        # Estimate total based on percent
        total = 0
        if percent > 0:
            total = int(processed / (percent / 100.0))
            
        self.update(percent, processed, total, rate, seed_name=seed_name)

    def report_status(self, status_code: str, message: str, seed_name: str | None = None) -> None:
        """上报非进度类状态（如重试/告警信息），并可关联到当前 seed 任务。"""
        info = {
            "task": seed_name,
            "status": status_code,
            "message": message,
            "last_update": datetime.now().isoformat()
        }
        if self.progress_queue:
            self.progress_queue.put(info)

    def update(self, percent: float, processed: int, total: int, rate: int, seed_name: str | None = None) -> None:
        """上报进度更新（可选关联到当前 seed 任务）。"""
        now = time.time()
        if now - self.last_update_time < self.update_interval and percent < 100:
            return

        self.last_update_time = now
        self.processed_tiles = processed
        self.total_tiles = total
        
        elapsed = now - self.start_time
        eta_seconds = 0
        
        # If rate is 0 (start or stalled), try to calculate avg rate from start
        if rate == 0 and processed > 0 and elapsed > 0:
             # Use overall average rate as fallback
             rate = int(processed / elapsed)

        if rate > 0:
            remaining = total - processed
            eta_seconds = remaining / rate
        
        info = {
            "task": seed_name,
            "processed": processed,
            "total": total,
            "percent": percent,
            "rate": rate,
            "eta": self.format_time(eta_seconds),
            "status": "running"
        }
        
        if self.progress_queue:
            self.progress_queue.put(info)
            
    def finish(self, seed_name: str | None = None) -> None:
        """上报当前任务/运行结束信息。"""
        total_time = time.time() - self.start_time
        avg_time = (total_time / self.processed_tiles) if self.processed_tiles > 0 else 0
        
        result = {
            "task": seed_name,
            "total_time": total_time,
            "total_tiles": self.processed_tiles,
            "avg_time_per_tile": avg_time,
            "status": "finished"
        }
        
        if self.progress_queue:
            self.progress_queue.put(result)
            
        if self.callback:
            self.callback(result)

    def format_time(self, seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return "{:02d}:{:02d}:{:02d}".format(h, m, s)

class SeedManager:
    def __init__(self, project_root, venv_dir=None, progress_callback=None):
        self.project_root = project_root
        self.progress_callback = progress_callback
        self.progress_queue = queue.Queue()
        self.mapproxy_config_dir = os.path.join(project_root, 'mapproxy_config')
        self.mapproxy_conf = os.path.join(self.mapproxy_config_dir, 'mapproxy.yaml')
        self.seed_conf = os.path.join(self.mapproxy_config_dir, 'mapproxy-seed.yaml')
        self.status_file = os.path.join(self.mapproxy_config_dir, 'seed_status.json')
        try:
            os.makedirs(self.mapproxy_config_dir, exist_ok=True)
        except Exception:
            logger.exception("创建 mapproxy_config 目录失败")
        try:
            legacy_status = os.path.join(project_root, 'seed_status.json')
            if os.path.exists(legacy_status):
                if not os.path.exists(self.status_file):
                    os.replace(legacy_status, self.status_file)
                else:
                    legacy_mtime = os.path.getmtime(legacy_status)
                    migrated_mtime = os.path.getmtime(self.status_file)
                    if legacy_mtime > migrated_mtime:
                        os.replace(legacy_status, self.status_file)
                    else:
                        os.remove(legacy_status)
        except Exception:
            logger.exception("迁移 seed_status.json 失败")
        self.seed_concurrency = self._get_seed_concurrency()
        self.seed_max_retries, self.seed_retry_backoff = self._get_seed_retry_config()
        self.alert_enabled, self.alert_threshold, self.alert_email = self._get_seed_alert_config()
        
        # Start status writer thread
        self._stop_writer = threading.Event()
        self._writer_thread = threading.Thread(target=self._status_writer_loop, daemon=True)
        self._writer_thread.start()

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

    def _status_writer_loop(self):
        """
        Background thread to write status updates to file.
        Consumes from progress_queue and writes to seed_status.json.
        """
        while not self._stop_writer.is_set():
            try:
                # Get latest update (drain queue to get the most recent one if multiple)
                item = None
                try:
                    while True:
                        item = self.progress_queue.get_nowait()
                except queue.Empty:
                    pass
                
                if item:
                    # Update status file
                    status = self.load_status()
                    status = self._merge_status_update(status, item)
                    status['last_update'] = datetime.now().isoformat()
                    self.save_status(status)
                
                time.sleep(1.0)
            except Exception:
                # Avoid crashing the thread
                time.sleep(1.0)

    def _merge_status_update(self, status: dict, item: dict) -> dict:
        """合并单次进度/状态更新到 seed_status.json 的结构中（支持按任务聚合）。"""
        base: dict = status if isinstance(status, dict) else {}
        upd: dict = item if isinstance(item, dict) else {}

        task = upd.get("task")
        if task:
            task_name = str(task)
            tasks = base.get("tasks")
            if not isinstance(tasks, dict):
                tasks = {}

            payload = dict(upd)
            payload.pop("task", None)
            tasks[task_name] = payload
            base["tasks"] = tasks
            base["current_task"] = task_name

        for k, v in upd.items():
            if k == "task":
                continue
            base[k] = v

        return base

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

        threshold_raw = os.environ.get("MAPPROXY_SEED_ALERT_THRESHOLD", "").strip()
        threshold = 0
        if threshold_raw:
            try:
                threshold = int(threshold_raw)
            except ValueError:
                logger.warning(f"Invalid MAPPROXY_SEED_ALERT_THRESHOLD: {threshold_raw}, using default 0")
                threshold = 0
        if threshold < 0:
            threshold = 0

        email = os.environ.get("MAPPROXY_SEED_ALERT_EMAIL", "").strip()
        return enabled, threshold, email

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
        status['status'] = 'starting'
        self.save_status(status)

        try:
            current_hash = self._compute_seed_hash()
            
            cmd = [
                self.seed_cmd,
                '-f', self.mapproxy_conf,
                '-s', self.seed_conf,
                '--concurrency', str(self.seed_concurrency)
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

            # Prepare environment to force unbuffered output
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            monitor = ProgressMonitor(callback=self.progress_callback, progress_queue=self.progress_queue)
            
            # 使用 Popen 替代 run 以便更好地控制窗口
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
                bufsize=1,
                env=env
            )
            
            logger.info("Seed 进程已启动，开始监听输出...")
            
            current_seed_name = None
            last_seed_name = None
            
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    # Strip ANSI color codes just in case
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    clean_line = ansi_escape.sub('', line)
                    
                    # DEBUG: Log raw line to verify what we are receiving
                    logger.debug(f"RAW: {clean_line}")

                    # Detect seed name change
                    # Format 1: Seeding 'seed_name' with ... (Standard/Old)
                    seed_match = re.search(r"Seeding '(.+?)'", clean_line)
                    if seed_match:
                        current_seed_name = seed_match.group(1)
                        logger.debug(f"Detected Seed Name (Format 1): {current_seed_name}", extra={'seed_name': f"[{current_seed_name}]"})
                    
                    # Format 2: task_name: (Observed in current environment)
                    # We look for a line that is just "name:" but exclude common info lines.
                    else:
                        task_match = re.match(r"^([a-zA-Z0-9_]+):$", clean_line)
                        if task_match:
                            candidate = task_match.group(1)
                            # Filter out known keywords that look like tasks
                            ignored_keywords = {'Levels', 'Overwriting', 'Check', 'Removing', 'Skipping'}
                            if candidate not in ignored_keywords:
                                current_seed_name = candidate
                                logger.debug(f"Detected Seed Name (Format 2): {current_seed_name}", extra={'seed_name': f"[{current_seed_name}]"})

                    if current_seed_name and current_seed_name != last_seed_name:
                        try:
                            monitor.reset()
                            monitor.current_task = str(current_seed_name)
                        except Exception:
                            pass
                        last_seed_name = current_seed_name

                    # Format log line with seed name
                    # User requirement: Ensure seed_name is correctly populated in the log column (extra)
                    # and matches the configuration.
                    
                    # 1. Prepare formatter extra
                    # If current_seed_name is known, use it; otherwise use '-'
                    seed_col_val = f"[{current_seed_name}]" if current_seed_name else '-'
                    formatter_extra = {'seed_name': seed_col_val}
                    
                    # 2. Construct enhanced message
                    # We keep the inline injection logic as it provides good context in the message body too,
                    # especially if the column is narrow or for tools that just read the message.
                    # However, if the user thinks 'seed_name' = '-' is an issue, they primarily mean the column.
                    
                    log_message = clean_line
                    
                    if current_seed_name:
                         # Check for timestamp pattern at start (e.g., [15:20:00])
                         ts_match = re.match(r"^(\[.*?\])(.*)", clean_line)
                         if ts_match:
                             # Insert seed name after timestamp: [Time] SeedName ...
                             timestamp_part = ts_match.group(1)
                             rest_part = ts_match.group(2)
                             # Ensure spacing
                             log_message = f"{timestamp_part} {current_seed_name}{rest_part}"
                         else:
                             # Fallback if no timestamp, check if we should prepend
                             # If the line is just "Seeding 'task'...", prepending makes it "[task] Seeding 'task'..." which is fine.
                             log_message = f"[{current_seed_name}] {clean_line}"
                    
                    # Special handling for Tile Errors and SSL Errors to extract more context
                    tile_err_match = re.search(r"could not retrieve tile \((?P<x>\d+),\s*(?P<y>\d+),\s*(?P<z>\d+)\)", clean_line)
                    ssl_err_match = re.search(r"ssl\.SSLEOFError", clean_line)
                    
                    if tile_err_match:
                         x, y, z = tile_err_match.group('x'), tile_err_match.group('y'), tile_err_match.group('z')
                         msg = f"Task: Seeding | Failed Tile: z={z}/x={x}/y={y} | Error: {clean_line}"
                         # For errors, we might still want the seed name visible if not in timestamp format
                         if current_seed_name and current_seed_name not in msg:
                              msg = f"[{current_seed_name}] {msg}"
                         logger.warning(msg, extra=formatter_extra)
                         continue 
                         
                    if ssl_err_match:
                         msg = f"Task: Seeding | Network Error: SSL Handshake Failed | {clean_line}"
                         if current_seed_name and current_seed_name not in msg:
                              msg = f"[{current_seed_name}] {msg}"
                         logger.error(msg, extra=formatter_extra)
                         continue
                    
                    parsed = monitor.parse_line(clean_line, seed_name=str(current_seed_name) if current_seed_name else None)
                    if parsed:
                        # Log the progress line so it appears in stdout (for GUI capture) and log file
                        logger.info(log_message, extra=formatter_extra)
                    elif not parsed:
                        # Log unparsed lines to debug why we are missing them, but avoid spamming too much
                        # Only log if it looks like progress but failed, or is an error
                        if "error" in clean_line.lower() or "exception" in clean_line.lower():
                            logger.error(log_message, extra=formatter_extra)
                        elif "%" in clean_line or "tiles/s" in clean_line:
                            logger.warning(f"Seed Output (Unparsed Progress): {log_message}", extra=formatter_extra)
                        else:
                            # Log other info at debug level
                            # Also log "Seeding ..." lines here as INFO or DEBUG to keep context
                            if "Seeding" in clean_line:
                                logger.info(log_message, extra=formatter_extra)
                            else:
                                logger.debug(log_message, extra=formatter_extra)
            
            process.wait()
            
            if process.returncode == 0:
                logger.info("Seed 任务完成。")
                try:
                    monitor.finish(seed_name=str(current_seed_name) if current_seed_name else None)
                except Exception:
                    monitor.finish()
                status['last_success'] = datetime.now().isoformat()
                status['status'] = 'completed'
                status['message'] = "All tasks finished successfully."
                if current_hash:
                    status['seed_hash'] = current_hash
            else:
                logger.error(f"Seed 任务失败，返回码: {process.returncode}")
                status['status'] = 'failed'
                status['error'] = f"Process exited with code {process.returncode}"
                
        except Exception as e:
            logger.exception("Seed 执行异常")
            status['status'] = 'error'
            status['error'] = str(e)
        finally:
            status['last_run_end'] = datetime.now().isoformat()
            try:
                final_status = self.load_status()
                if not isinstance(final_status, dict):
                    final_status = {}
                final_status.update(status)
                self.save_status(final_status)
            except Exception:
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
