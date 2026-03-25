import os
import sys
import subprocess
import shutil
import platform
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_requirements():
    """检查构建环境"""
    print("Checking build requirements...")
    
    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"  - PyInstaller: Found ({PyInstaller.__version__})")
    except ImportError:
        logger.exception("PyInstaller 未安装")
        logger.info("请安装: pip install pyinstaller")
        return False
        
    # 检查 Tkinter (Linux 需要 python3-tk)
    try:
        import tkinter
        print(f"  - Tkinter: Found ({tkinter.TkVersion})")
    except ImportError:
        logger.exception("Tkinter 未安装")
        if platform.system() == "Linux":
            logger.info("在 Linux 上可能需要: sudo apt-get install python3-tk")
        return False
        
    return True

def clean_build_artifacts():
    """清理之前的构建产物"""
    dirs_to_clean = ['build', 'dist']
    for d in dirs_to_clean:
        if os.path.exists(d):
            print(f"Cleaning {d}...")
            shutil.rmtree(d)

def build():
    """执行打包"""
    system = platform.system()
    print(f"\nStarting build for {system}...")
    
    # 基础命令
    # 使用 sys.executable 确保调用的是当前环境的 PyInstaller
    cmd = [sys.executable, '-m', 'PyInstaller', 'build.spec', '--clean', '--noconfirm']
    
    # 根据平台调整 (目前 build.spec 已包含大部分逻辑，这里作为扩展点)
    if system == 'Linux':
        print("  - Target: Linux Single File Executable")
        # Linux 特定检查或参数可以在这里添加
    elif system == 'Windows':
        print("  - Target: Windows Executable (.exe)")
    
    try:
        subprocess.check_call(cmd)
        print("\nBuild successful!")
        
        # 验证输出
        dist_dir = os.path.join(os.getcwd(), 'dist')
        exe_name = 'MapProxyLauncher'
        if system == 'Windows':
            exe_name += '.exe'
            
        exe_path = os.path.join(dist_dir, exe_name)
        if os.path.exists(exe_path):
            print(f"Artifact created: {exe_path}")
            print(f"Size: {os.path.getsize(exe_path) / 1024 / 1024:.2f} MB")
        else:
            print(f"Error: Expected artifact not found at {exe_path}")
            
    except subprocess.CalledProcessError:
        logger.exception("构建失败")
        sys.exit(1)

if __name__ == "__main__":
    if check_requirements():
        clean_build_artifacts()
        build()
    else:
        sys.exit(1)
