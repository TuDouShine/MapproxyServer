import os
import sys
import socket
import logging
import hashlib
import json

# Constants
LAUNCHER_DIR_NAME = "MapProxyLauncher"

def get_base_dir():
    """获取程序所在的基准目录"""
    if getattr(sys, 'frozen', False):
        # 如果是打包后的 exe，基准目录是 exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是脚本运行，基准目录是脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))

def get_work_dir(base_dir=None):
    """获取工作目录（数据存储目录）"""
    if base_dir is None:
        base_dir = get_base_dir()
    return os.path.join(base_dir, LAUNCHER_DIR_NAME)

def is_port_in_use(port, host='127.0.0.1'):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def calculate_file_hash(path):
    """计算文件 SHA256 哈希"""
    if not os.path.exists(path):
        return None
    try:
        hasher = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        logging.exception(f"计算文件哈希失败: {path}")
        return None

def load_json(path):
    """读取 JSON 文件"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logging.exception(f"读取 JSON 失败: {path}")
        return {}

def save_json(path, data):
    """写入 JSON 文件"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        logging.exception(f"写入 JSON 失败: {path}")

def setup_logging(log_file_path, logger_name="MapProxy"):
    """配置日志"""
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
