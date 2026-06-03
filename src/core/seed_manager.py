import os
import subprocess
import threading
import time
import json
import logging
import uuid
import yaml
import shutil
from datetime import datetime
from collections import deque

logger = logging.getLogger("SeedManager")

class SeedTask:
    def __init__(self, name, command, retries=0, max_retries=3):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.command = command
        self.status = "pending"  # pending, running, completed, failed, cancelled
        self.progress = "0 tiles"
        self.message = ""
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.ended_at = None
        self.process = None
        self.retries = retries
        self.max_retries = max_retries
        self.log_buffer = deque(maxlen=50)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "retries": self.retries,
            "max_retries": self.max_retries
        }

    @classmethod
    def from_dict(cls, data):
        # Reconstruct task, but command logic needs to be re-applied by manager if needed
        # For simplicity, we might not fully restore 'command' here if it depends on runtime paths
        # So we mainly use this for display history. 
        # Active tasks restoration requires re-generating command.
        task = cls(data['name'], [], data.get('retries', 0), data.get('max_retries', 3))
        task.id = data['id']
        task.status = data['status']
        task.progress = data.get('progress', "")
        task.message = data.get('message', "")
        task.created_at = data.get('created_at')
        task.started_at = data.get('started_at')
        task.ended_at = data.get('ended_at')
        return task

class SeedManager:
    def __init__(self, project_root, config=None):
        self.project_root = project_root
        self.config = config or {}
        self.mapproxy_conf = os.path.join(project_root, 'configs', 'mapproxy.yaml')
        self.seed_conf = os.path.join(project_root, 'configs', 'mapproxy-seed.yaml')
        self.status_file = os.path.join(project_root, 'seed_status.json')
        
        self.max_concurrency = self.config.get('concurrency', 2)
        self.max_retries = self.config.get('seed_retries', 3)
        self.seed_timeout = self.config.get('seed_timeout', 3600) # Default 1 hour
        
        # Detect seed executable
        self.seed_cmd = self._detect_seed_cmd()
        
        self.tasks = {} # id -> Task
        self.queue = deque()
        self.running_tasks = {} # id -> Task
        self.lock = threading.RLock()
        
        self.should_exit = False
        self.worker_thread = None
        
        # Load previous status
        self.load_status()
        
        # Start worker
        self.start_worker()

    def _detect_seed_cmd(self):
        win_path = os.path.join(self.project_root, "venv", "Scripts", "mapproxy-seed.exe")
        unix_path = os.path.join(self.project_root, "venv", "bin", "mapproxy-seed")
        
        if os.path.exists(win_path):
            return win_path
        elif os.path.exists(unix_path):
            return unix_path
        
        # Fallback to system path check
        if shutil.which("mapproxy-seed"):
            return "mapproxy-seed"
            
        return "mapproxy-seed" # Hope for the best

    def get_available_seeds(self):
        """Parse mapproxy-seed.yaml to find defined seeds"""
        seeds = ["ALL"]
        if os.path.exists(self.seed_conf):
            try:
                with open(self.seed_conf, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if 'seeds' in data:
                        seeds.extend(list(data['seeds'].keys()))
            except Exception as e:
                logger.error(f"Failed to parse seed config: {e}")
        return seeds

    def add_task(self, seed_name="ALL"):
        with self.lock:
            # Construct command
            cmd = [
                self.seed_cmd,
                '-f', self.mapproxy_conf,
                '-s', self.seed_conf,
                '--continue', # Always try to continue
                '--quiet'
            ]
            
            if seed_name != "ALL":
                cmd.extend(['--seed', seed_name])
            
            task = SeedTask(seed_name, cmd, max_retries=self.max_retries)
            self.tasks[task.id] = task
            
            # If "ALL" and already running "ALL", maybe don't add? 
            # For now, allow user to do whatever they want.
            
            self.queue.append(task.id)
            self.save_status()
            logger.info(f"Added seed task: {seed_name} (ID: {task.id})")
            return task.id

    def cancel_task(self, task_id):
        with self.lock:
            if task_id in self.queue:
                self.queue.remove(task_id)
                self.tasks[task_id].status = "cancelled"
                self.save_status()
                return True
            elif task_id in self.running_tasks:
                task = self.tasks[task_id]
                if task.process:
                    logger.info(f"Terminating task {task_id}")
                    task.process.terminate() # This will raise exception in worker loop or return code
                task.status = "cancelled"
                return True
        return False

    def stop_all(self):
        self.should_exit = True
        with self.lock:
            for tid in list(self.running_tasks.keys()):
                self.cancel_task(tid)

    def _worker_loop(self):
        while not self.should_exit:
            # Check if we can run more tasks
            with self.lock:
                active_count = len(self.running_tasks)
                if active_count < self.max_concurrency and self.queue:
                    task_id = self.queue.popleft()
                    task = self.tasks[task_id]
                    self.running_tasks[task_id] = task
                    # Start task in a separate thread to avoid blocking the loop
                    threading.Thread(target=self._run_task, args=(task,), daemon=True).start()
            
            time.sleep(1)

    def _run_task(self, task):
        logger.info(f"Starting task {task.id} ({task.name})")
        task.status = "running"
        task.started_at = datetime.now().isoformat()
        self.save_status()
        
        try:
            # Validate executable
            exe = task.command[0]
            if not os.path.isabs(exe) and shutil.which(exe) is None:
                raise FileNotFoundError(f"Command not found: {exe}")

            # Run process
            # On Windows, hide window
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
                
            task.process = subprocess.Popen(
                task.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
                cwd=self.project_root
            )
            
            # Read output
            while True:
                line = task.process.stdout.readline()
                if not line and task.process.poll() is not None:
                    break
                if line:
                    line = line.strip()
                    task.log_buffer.append(line)
                    # Try to parse progress
                    # MapProxy output example: "[10:11:12] 100 tiles (10.1 t/s)"
                    if "tiles" in line:
                         task.progress = line
            
            rc = task.process.poll()
            task.ended_at = datetime.now().isoformat()
            
            if rc == 0:
                task.status = "completed"
                task.progress = "Completed"
                logger.info(f"Task {task.id} completed successfully.")
            else:
                if task.status != "cancelled": # Don't overwrite cancelled status
                    task.status = "failed"
                    task.message = f"Process exited with code {rc}"
                    logger.error(f"Task {task.id} failed: {task.message}")
                    
                    # Retry logic
                    if task.retries < task.max_retries:
                        logger.info(f"Retrying task {task.id} ({task.retries + 1}/{task.max_retries})")
                        task.retries += 1
                        task.status = "pending"
                        task.process = None
                        with self.lock:
                            del self.running_tasks[task.id]
                            self.queue.appendleft(task.id) # Re-queue at front
                        self.save_status()
                        return # Exit this thread, let worker pick it up again

        except Exception as e:
            logger.error(f"Task {task.id} exception: {e}")
            task.status = "error"
            task.message = str(e)
            task.ended_at = datetime.now().isoformat()
        
        finally:
            with self.lock:
                if task.id in self.running_tasks:
                    del self.running_tasks[task.id]
            self.save_status()

    def start_worker(self):
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

    def start_background_seed(self):
        """Legacy method for main.py compatibility"""
        # Auto-start a full seed if no tasks exist
        if not self.tasks:
             self.add_task("ALL")

    def load_status(self):
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for t_data in data.get('tasks', []):
                        task = SeedTask.from_dict(t_data)
                        # If it was running when we saved (crash/exit), mark as failed or pending?
                        if task.status == 'running':
                            task.status = 'failed' 
                            task.message = "Interrupted by system restart"
                        self.tasks[task.id] = task
            except Exception as e:
                logger.error(f"Failed to load status: {e}")

    def save_status(self):
        # We don't want to save continuously on every log line, maybe debounce?
        # For simplicity, we save on state changes.
        data = {
            "tasks": [t.to_dict() for t in self.tasks.values()]
        }
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save status: {e}")

    def get_summary(self):
        total = len(self.tasks)
        pending = len(self.queue)
        running = len(self.running_tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == 'completed')
        failed = sum(1 for t in self.tasks.values() if t.status in ('failed', 'error'))
        return {
            "total": total,
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed
        }
