# config.py
import os
import yaml
import tempfile
import atexit
from mapproxy.wsgiapp import make_wsgi_app

# 配置文件路径
# config.py 在 src/core/ 目录下，所以项目根目录是上上级目录
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
mapproxy_conf = os.path.join(project_root, 'configs', 'mapproxy.yaml')

# 检查是否进入离线模式
if os.environ.get('MAPPROXY_OFFLINE_MODE') == '1':
    try:
        with open(mapproxy_conf, 'r', encoding='utf-8') as f:
            conf_dict = yaml.safe_load(f)
            
        # 将所有 caches 的 sources 设为空列表
        if conf_dict and 'caches' in conf_dict:
            for cache_name, cache_def in conf_dict['caches'].items():
                if 'sources' in cache_def:
                    cache_def['sources'] = []
                    
        # 使用 tempfile 创建临时的离线配置文件，并在程序退出时自动删除
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8')
        yaml.dump(conf_dict, temp_file, allow_unicode=True)
        temp_file.close()
        
        mapproxy_conf = temp_file.name
        print(f"Using offline mode configuration: {mapproxy_conf}")
        
        # 注册清理函数
        def _cleanup():
            if os.path.exists(mapproxy_conf):
                try:
                    os.remove(mapproxy_conf)
                except:
                    pass
        atexit.register(_cleanup)
        
    except Exception as e:
        print("\n" + "!"*60)
        print(f" WARNING: Failed to generate offline configuration: {e}")
        print(" Offline mode could NOT be activated. Falling back to original config.")
        print("!"*60 + "\n")

# 创建 MapProxy WSGI 应用
application = make_wsgi_app(mapproxy_conf)

if __name__ == '__main__':
    from waitress import serve
    # 也可以直接运行此脚本启动，但在本系统中将由 main.py 通过 waitress-serve 启动
    serve(application, host='0.0.0.0', port=8080)
