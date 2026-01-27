# config.py
import os
from mapproxy.wsgiapp import make_wsgi_app

# 配置文件路径
mapproxy_conf = os.path.join(os.path.dirname(__file__), 'mapproxy.yaml')

# 创建 MapProxy WSGI 应用
application = make_wsgi_app(mapproxy_conf)

if __name__ == '__main__':
    from waitress import serve
    # 也可以直接运行此脚本启动，但在本系统中将由 main.py 通过 waitress-serve 启动
    serve(application, host='0.0.0.0', port=8080)
