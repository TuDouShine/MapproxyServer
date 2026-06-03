# config.py
import os
import yaml
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
                    
        # 写入临时的离线配置文件
        offline_conf = os.path.join(project_root, 'configs', 'mapproxy_offline.yaml')
        with open(offline_conf, 'w', encoding='utf-8') as f:
            yaml.dump(conf_dict, f, allow_unicode=True)
            
        mapproxy_conf = offline_conf
        print("Using offline mode configuration (sources disabled).")
    except Exception as e:
        print(f"Failed to generate offline configuration: {e}")

# 创建 MapProxy WSGI 应用
application = make_wsgi_app(mapproxy_conf)

if __name__ == '__main__':
    from waitress import serve
    # 也可以直接运行此脚本启动，但在本系统中将由 main.py 通过 waitress-serve 启动
    serve(application, host='0.0.0.0', port=8080)
