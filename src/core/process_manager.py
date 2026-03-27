import psutil
import socket
import time
import logging
import signal
import os
from typing import Tuple

logger = logging.getLogger(__name__)

def is_port_in_use(port: int) -> bool:
    """
    检查端口是否被占用
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def kill_process_tree(pid: int, timeout: int = 3) -> Tuple[bool, str]:
    """
    终止指定 PID 及其所有子进程。
    
    Args:
        pid (int): 目标进程 ID
        timeout (int): 等待超时时间
        
    Returns:
        tuple: (success (bool), message (str))
    """
    try:
        if not psutil.pid_exists(pid):
            return False, f"进程 {pid} 不存在"
            
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        # 记录信息以便日志
        proc_name = parent.name()
        count = len(children) + 1
        
        logger.info(f"Terminating process {proc_name} (PID: {pid}) and {len(children)} children...")
        
        # 先尝试温和终止所有子进程
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
                
        # 终止父进程
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
            
        # 等待结束
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        
        # 如果还有活着的，强制杀死
        if alive:
            logger.warning(f"Force killing {len(alive)} processes...")
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
            # 再次等待确认
            psutil.wait_procs(alive, timeout=1)
            
        return True, f"已终止进程 {proc_name} (PID: {pid}) 及其子进程"
        
    except psutil.NoSuchProcess:
        logger.exception(f"进程 {pid} 已不存在")
        return True, f"进程 {pid} 已不存在"
    except Exception:
        logger.exception(f"终止进程 {pid} 失败")
        return False, f"终止进程 {pid} 失败"

def verify_port_release(port: int, timeout: int = 3) -> bool:
    """
    验证端口是否已释放
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False
