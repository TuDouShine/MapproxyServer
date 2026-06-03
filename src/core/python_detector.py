import os
import sys
import subprocess
import glob

def get_python_version(path):
    """获取指定 Python 解释器的版本信息"""
    try:
        # 使用 -V 获取版本，例如 "Python 3.9.13"
        result = subprocess.run([path, '-V'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

def find_python_interpreters():
    """扫描系统中的 Python 解释器"""
    interpreters = []
    
    # 1. 扫描 PATH 环境变量
    paths = os.environ.get('PATH', '').split(os.pathsep)
    for p in paths:
        if not os.path.isdir(p):
            continue
            
        if os.name == 'nt':
            exe_path = os.path.join(p, 'python.exe')
        else:
            exe_path = os.path.join(p, 'python3')
            if not os.path.exists(exe_path):
                exe_path = os.path.join(p, 'python')

        if os.path.exists(exe_path) and os.access(exe_path, os.X_OK):
            version = get_python_version(exe_path)
            if version:
                interpreters.append({'path': exe_path, 'version': version, 'source': 'PATH'})

    # 2. 常见安装路径 (Windows)
    if os.name == 'nt':
        # C:\Python*
        for p in glob.glob(r"C:\Python*"):
             exe_path = os.path.join(p, 'python.exe')
             if os.path.exists(exe_path):
                 version = get_python_version(exe_path)
                 if version:
                     interpreters.append({'path': exe_path, 'version': version, 'source': 'System'})
        
        # AppData Local Programs
        user_programs = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*")
        for p in glob.glob(user_programs):
             exe_path = os.path.join(p, 'python.exe')
             if os.path.exists(exe_path):
                 version = get_python_version(exe_path)
                 if version:
                     interpreters.append({'path': exe_path, 'version': version, 'source': 'User'})
    
    # 3. 常见安装路径 (Linux/Unix)
    else:
        common_dirs = ['/usr/bin', '/usr/local/bin', '/opt/python/bin']
        for d in common_dirs:
            if not os.path.isdir(d):
                continue
            for item in os.listdir(d):
                if item.startswith('python3.') or item == 'python3':
                    exe_path = os.path.join(d, item)
                    if os.access(exe_path, os.X_OK):
                        version = get_python_version(exe_path)
                        if version:
                            interpreters.append({'path': exe_path, 'version': version, 'source': 'System'})

    # 4. 当前项目虚拟环境
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    venv_patterns = ['venv', '.venv', 'env']
    for venv_name in venv_patterns:
        if os.name == 'nt':
            exe_path = os.path.join(project_root, venv_name, 'Scripts', 'python.exe')
        else:
            exe_path = os.path.join(project_root, venv_name, 'bin', 'python')
            
        if os.path.exists(exe_path):
             version = get_python_version(exe_path)
             if version:
                 interpreters.append({'path': exe_path, 'version': version, 'source': 'Project Venv'})

    # 去重
    unique_interpreters = []
    seen_paths = set()
    for item in interpreters:
        # 规范化路径以便去重
        norm_path = os.path.normpath(item['path'])
        if os.name == 'nt':
            norm_path = norm_path.lower()
            
        if norm_path not in seen_paths:
            seen_paths.add(norm_path)
            unique_interpreters.append(item)

    return unique_interpreters

if __name__ == "__main__":
    # 测试
    pythons = find_python_interpreters()
    for py in pythons:
        print(f"[{py['source']}] {py['version']} -> {py['path']}")
