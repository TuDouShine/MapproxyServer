# MapproxyServer Linux 生产部署手册

## 1. 文档目标

本文档面向 Linux 服务器部署场景，说明如何以源码方式部署、启动、托管和排查 MapproxyServer。

适用场景：

- 服务器无图形界面，仅以后台服务方式运行
- 需要通过 systemd 托管进程
- 需要通过 Nginx 反向代理对外提供访问
- 需要支持在线部署或离线部署

## 2. 项目运行方式概览

当前项目的 Linux 生产启动链路如下：

1. 使用 `main.py --service` 进入无界面服务模式
2. 初始化工作目录
3. 生成 `mapproxy.yaml` 与 `mapproxy-seed.yaml`
4. 检查并安装 Python 依赖
5. 启动 Seed 任务
6. 使用 Waitress 启动 MapProxy WSGI 服务

建议在生产环境中始终使用 `--service` 模式，不要直接启动 GUI。

## 3. 推荐部署拓扑

推荐将源码、运行数据和日志分离：

- 源码目录：`/opt/MapproxyServer`
- 运行数据目录：`/var/lib/mapproxy-server`
- 日志目录：`/var/log/mapproxy-server`
- 反向代理：Nginx
- 服务监听：`127.0.0.1:8080`

推荐这样部署的原因：

- 便于权限隔离
- 便于备份与迁移
- 避免运行时文件混入源码目录
- 便于 systemd 和日志系统统一管理

## 4. 系统要求

### 4.1 基础要求

- Linux x86_64
- Python 3.8 及以上
- 可用的 `venv` 模块
- 可写的运行数据目录
- 可访问的本地或外部地图源

### 4.2 依赖说明

项目主要 Python 依赖如下：

- MapProxy
- Waitress
- Pillow
- PyYAML
- psutil

说明：

- GUI 依赖的 `tkinter` 在服务模式下不是必需
- 若服务器仅部署后台服务，可以不启用 GUI

## 5. 部署前准备

### 5.1 Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv nginx
```

### 5.2 Rocky / RHEL / CentOS

```bash
sudo dnf install -y python3 python3-pip python3-virtualenv nginx
```

### 5.3 创建运行用户与目录

```bash
sudo useradd --system --home /var/lib/mapproxy-server --shell /sbin/nologin mapproxy || true
sudo mkdir -p /opt/MapproxyServer
sudo mkdir -p /var/lib/mapproxy-server
sudo mkdir -p /var/log/mapproxy-server
sudo chown -R mapproxy:mapproxy /var/lib/mapproxy-server /var/log/mapproxy-server
sudo chmod -R 755 /opt/MapproxyServer
```

## 6. 源码部署

将项目源码复制到服务器目标目录：

```bash
sudo rsync -av --delete ./ /opt/MapproxyServer/
sudo chmod +x /opt/MapproxyServer/scripts/run.sh
```

部署后建议确认以下关键文件存在：

- `main.py`
- `requirements.txt`
- `scripts/run.sh`
- `scripts/mapproxy.service`
- `configs/mapproxy.yaml`
- `configs/mapproxy-seed.yaml`

## 7. 首次手动启动

在正式接入 systemd 前，建议先手动启动一次，以验证环境、依赖和配置生成流程。

```bash
cd /opt/MapproxyServer
sudo -u mapproxy python3 main.py \
  --service \
  --host 127.0.0.1 \
  --port 8080 \
  --work-dir /var/lib/mapproxy-server \
  --python-path /usr/bin/python3
```

成功后可通过以下地址验证：

```bash
curl http://127.0.0.1:8080/demo/
```

## 8. systemd 托管部署

虽然仓库已提供 `scripts/mapproxy.service` 模板，但生产环境建议使用独立的部署版配置，并显式指定：

- 运行用户
- 监听地址
- 工作目录
- 日志位置

### 8.1 推荐服务文件

将以下内容保存为 `/etc/systemd/system/mapproxy.service`：

```ini
[Unit]
Description=MapProxy Server
After=network.target

[Service]
Type=simple
User=mapproxy
Group=mapproxy
WorkingDirectory=/opt/MapproxyServer

ExecStart=/usr/bin/python3 /opt/MapproxyServer/main.py --service --host 127.0.0.1 --port 8080 --work-dir /var/lib/mapproxy-server --python-path /usr/bin/python3

Restart=always
RestartSec=5

StandardOutput=append:/var/log/mapproxy-server/server.log
StandardError=append:/var/log/mapproxy-server/error.log

[Install]
WantedBy=multi-user.target
```

### 8.2 启用服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable mapproxy
sudo systemctl start mapproxy
sudo systemctl status mapproxy
```

### 8.3 查看日志

```bash
sudo journalctl -u mapproxy -f
tail -f /var/log/mapproxy-server/server.log
tail -f /var/log/mapproxy-server/error.log
```

## 9. Nginx 反向代理

生产环境不建议直接将应用监听在 `0.0.0.0` 并暴露公网端口。建议应用仅监听本机，再由 Nginx 统一对外提供访问与后续 HTTPS 接入能力。

将以下内容保存为 `/etc/nginx/conf.d/mapproxy.conf`：

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

启用 Nginx：

```bash
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

验证：

```bash
curl http://127.0.0.1/
```

## 10. 工作目录说明

通过 `--work-dir` 指定的目录将承载项目运行期文件。建议使用独立目录，例如：

- `/var/lib/mapproxy-server`

首次运行后，常见内容包括：

- `mapproxy_config/`
- `packages/`
- `logs/`
- `cache_data/`

其中：

- `mapproxy_config/mapproxy.yaml`：运行时 MapProxy 配置
- `mapproxy_config/mapproxy-seed.yaml`：Seed 配置
- `mapproxy_config/map_config.json`：主配置文件
- `mapproxy_config/seed_status.json`：Seed 状态记录

## 11. 离线部署

如果服务器不能访问外网，建议使用离线包目录进行部署。

### 11.1 在有网机器下载依赖

```bash
mkdir packages
python3 -m pip download -r requirements.txt -d packages
```

### 11.2 拷贝到目标服务器

推荐将下载后的依赖目录拷贝到工作目录下：

```text
/var/lib/mapproxy-server/packages
```

### 11.3 启动安装

首次执行服务启动时，程序会优先尝试从 `packages/` 中离线安装依赖：

```bash
cd /opt/MapproxyServer
sudo -u mapproxy python3 main.py \
  --service \
  --host 127.0.0.1 \
  --port 8080 \
  --work-dir /var/lib/mapproxy-server \
  --python-path /usr/bin/python3
```

## 12. 配置与地图源注意事项

### 12.1 默认地图源

当前默认配置中包含在线地图源地址。如果服务器无法访问外网，而又没有提前准备本地缓存或替代源，服务能力会受到影响。

### 12.2 离线模式说明

配置中的 `offline_mode` 主要影响缓存与使用策略，不等价于“完全不访问外部地图源”。若要实现真正的离线部署，需要同时满足以下条件：

- 已准备可用的本地数据源或内网地图源
- 已调整对应配置文件
- 已完成必要的缓存预热

### 12.3 缓存与权限

缓存目录和 MBTiles 文件必须对运行用户具备足够权限，否则可能出现：

- SQLite database is locked
- Could not load MBTiles
- 种子任务执行失败

## 13. 生产环境注意事项

### 13.1 不建议直接暴露 `0.0.0.0`

现有脚本和模板中存在默认绑定 `0.0.0.0` 的情况，但生产建议统一改为：

- 应用监听：`127.0.0.1`
- 外部访问：通过 Nginx 代理

### 13.2 显式指定 `--work-dir`

建议始终显式指定：

```bash
--work-dir /var/lib/mapproxy-server
```

这样可以避免运行数据进入源码目录，也可以避免不同启动方式下的路径差异。

### 13.3 统一离线依赖目录

文档和代码中存在不同命名方式。生产环境建议统一使用：

- `packages/`

并放在 `--work-dir` 目录下。

### 13.4 虚拟环境目录差异

当前实现会优先使用 `.venv`，否则回退到 `venv`。生产环境中不建议依赖目录名猜测，应以实际启动日志和服务结果为准。

### 13.5 不要在服务器上使用 GUI 入口

无图形环境下启动 GUI 会触发显示环境相关错误。服务器部署应始终使用：

```bash
python3 main.py --service
```

## 14. 常见检查命令

### 14.1 Python 与 venv 检查

```bash
python3 --version
python3 -m venv /tmp/test-venv
```

### 14.2 端口检查

```bash
ss -lntp | grep 8080
```

### 14.3 服务检查

```bash
sudo systemctl status mapproxy
sudo journalctl -u mapproxy -n 200 --no-pager
```

### 14.4 页面访问检查

```bash
curl http://127.0.0.1:8080/demo/
curl http://127.0.0.1/
```

## 15. 常见故障排查

### 15.1 无法创建虚拟环境

现象：

- 提示 `ensurepip` 缺失
- `python3 -m venv` 执行失败

处理：

- Ubuntu / Debian：安装 `python3-venv`
- Rocky / RHEL / CentOS：安装 `python3-virtualenv`

### 15.2 服务启动失败

处理顺序：

1. 查看 `systemctl status mapproxy`
2. 查看 `journalctl -u mapproxy -f`
3. 查看 `/var/log/mapproxy-server/error.log`
4. 手动执行一次 `main.py --service` 复现

### 15.3 页面无法访问

排查顺序：

1. 检查应用本地端口是否已监听
2. 检查 `curl http://127.0.0.1:8080/demo/`
3. 检查 Nginx 配置是否生效
4. 检查防火墙与安全组

### 15.4 端口占用

现象：

- 启动时报 `Address already in use`

处理：

- 修改服务端口
- 结束占用进程

### 15.5 SQLite / MBTiles 锁问题

现象：

- `database is locked`
- MBTiles 加载失败

处理：

- 检查缓存目录权限
- 检查 mbtiles 文件权限
- 避免多个进程同时写入同一份数据

## 16. 最小上线流程

推荐最小上线步骤如下：

1. 安装 `python3`、`python3-venv`、`nginx`
2. 拷贝源码到 `/opt/MapproxyServer`
3. 创建 `/var/lib/mapproxy-server` 与 `/var/log/mapproxy-server`
4. 手动执行一次 `main.py --service`
5. 写入并启用 `mapproxy.service`
6. 写入并启用 Nginx 配置
7. 验证本机访问与反向代理访问

完成后，浏览器可通过 Nginx 对外入口访问服务。
