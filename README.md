# MapProxy Server Launcher

## 1. 项目概述

MapProxy Server Launcher 是一个基于 Python + Tkinter 的地图服务启动器，提供：

- 图形化配置与一键启停 MapProxy 服务
- `.venv` 虚拟环境优先的依赖管理
- `map_config.json` 统一配置存储与旧配置兼容迁移
- Seed 任务日志与进度监控、缓存打包

当前仓库已完成目录重构，核心源码统一位于 `src/`，默认配置模板位于 `configs/`，构建脚本位于 `scripts/`。

## 2. 快速开始（Windows）

以下命令均在项目根目录执行。

### 2.1 创建并启用 `.venv`

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2.2 启动 GUI（推荐）

```powershell
.\.venv\Scripts\python.exe .\src\ui\gui_launcher.py
```

### 2.3 启动服务模式（无 GUI）

```powershell
.\.venv\Scripts\python.exe .\main.py --service --port 8080 --host 127.0.0.1
```

常用参数：

- `--port`：服务端口（默认 8080）
- `--host`：绑定地址（默认 127.0.0.1，外网访问可用 0.0.0.0）
- `--work-dir`：指定工作目录（默认 `<项目目录>\MapProxyLauncher`）
- `--python-path`：指定 Python 解释器
- `--skip-venv`：跳过自动创建虚拟环境

## 3. 测试与验证

### 3.1 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

### 3.2 运行单个测试文件

```powershell
.\.venv\Scripts\python.exe .\tests\test_advanced_settings.py
.\.venv\Scripts\python.exe .\tests\test_advanced_settings_dialog_animation.py
```

## 4. 目录结构（当前版本）

```text
MapproxyServer/
├── configs/                          # 默认配置模板（启动时复制到工作目录）
│   ├── mapproxy.yaml
│   └── mapproxy-seed.yaml
├── docs/
│   └── UI_Design_Spec.md
├── scripts/
│   ├── build.py                      # 跨平台构建入口
│   ├── build.spec                    # PyInstaller 规则
│   ├── mapproxy.service              # Linux systemd 示例
│   └── run.sh                        # Linux 启动脚本
├── src/
│   ├── core/                         # 配置、环境、服务与 seed 编排
│   ├── ui/                           # GUI 与高级设置面板
│   └── utils/                        # 通用工具函数
├── tests/                            # 单元测试
├── main.py                           # 服务主入口
├── requirements.txt
└── README.md
```

## 5. 运行时工作目录（MapProxyLauncher）

默认工作目录为 `<项目根目录>\MapProxyLauncher`（打包版优先使用 exe 同级目录，可回退到用户数据目录）。

主要内容：

- `mapproxy_config/mapproxy.yaml`
- `mapproxy_config/mapproxy-seed.yaml`
- `mapproxy_config/map_config.json`（唯一写入配置）
- `mapproxy_config/seed_status.json`
- `logs/server.log`
- `logs/seed.log`
- `logs/config_audit.log`
- `cache_data/`
- `packaged_tiles/`

## 6. 核心模块说明

- `src/ui/gui_launcher.py`：主界面，含运行环境、服务配置、状态、日志与监控页签。
- `src/ui/gui_advancedsetting_manager.py`：高级设置弹窗，包含“性能与基础”“地图源与功能”两组配置。
- `src/core/config_manager.py`：配置读写、迁移、校验、审计日志。
- `src/core/seed_orchestrator.py` / `src/core/seed_manager.py`：Seed 任务调度与状态输出。
- `src/core/service_runner.py`：Waitress 服务拉起。
- `src/core/env_manager.py`：虚拟环境与解释器检测（优先 `.venv`，兼容 `venv`）。

## 7. 打包

先安装 PyInstaller（在 `.venv` 中）：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe .\scripts\build.py
```

产物目录：`dist/`（Windows 下为 `MapProxyLauncher.exe`）。

## 8. Linux 服务器部署

在生产环境中，通常不需要 GUI，而是作为后台服务运行。

### 8.1 快速启动脚本

项目提供了一个便捷脚本 `scripts/run.sh`，可自动检测环境并拉起无 GUI 服务：

```bash
chmod +x scripts/run.sh
./scripts/run.sh 8080
```
*注：该脚本会自动将服务绑定至 `0.0.0.0`，并在当前目录进行配置初始化。*

### 8.2 systemd 服务化部署

推荐使用 systemd 将其作为常驻服务管理。

1. 复制服务文件模板：
   ```bash
   sudo cp scripts/mapproxy.service /etc/systemd/system/
   ```
2. 修改模板中的路径（编辑 `/etc/systemd/system/mapproxy.service`）：
   将 `WorkingDirectory` 和 `ExecStart` 中的 `/opt/MapproxyServer` 替换为实际的项目路径。
3. 重新加载并启动：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable mapproxy
   sudo systemctl start mapproxy
   ```
4. 查看服务日志：
   ```bash
   sudo journalctl -u mapproxy -f
   ```

## 9. 服务器离线部署

如果您的服务器无法访问外网，请按照以下步骤进行离线部署。

### 9.1 在有网机器上导出依赖（同 OS 架构）

找一台与目标服务器操作系统、Python 版本（如 Python 3.8+）一致的有网机器：

```bash
# 1. 创建打包目录
mkdir offline_packages
# 2. 下载所有依赖及 wheel 包
python3 -m pip download -r requirements.txt -d offline_packages
```

### 9.2 在无网服务器上安装

将整个项目源码与 `offline_packages` 目录拷贝至无网服务器：

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 离线安装依赖（不访问 PyPI）
python3 -m pip install --no-index --find-links=offline_packages -r requirements.txt
```

完成后，按照前述说明使用 `./scripts/run.sh` 或 `systemd` 启动服务即可。

## 10. 常见问题排查 (Troubleshooting)

**Q1: 启动报错 "Address already in use" 或 "端口被占用"**
- **原因**：指定的端口（如 8080）已被其他服务占用。
- **解决**：修改启动参数中的端口（如 `--port 8081`）或在 GUI 中修改端口配置；也可通过 `netstat -tulpn | grep 8080` 找出并结束冲突进程。

**Q2: Linux 下启动报错 "\_tkinter.TclError: no display name and no $DISPLAY environment variable"**
- **原因**：在无图形界面的 SSH 终端中直接运行了 GUI 启动器（`gui_launcher.py`）。
- **解决**：Linux 服务器环境请务必添加 `--service` 参数（如 `python main.py --service`）以无界面模式启动后台服务。

**Q3: Linux 下提示 "The 'ensurepip' module is missing" 或无法创建虚拟环境**
- **原因**：部分 Linux 发行版（如 Ubuntu）的默认 Python3 包阉割了 `venv` 模块。
- **解决**：根据系统安装完整包，如 Ubuntu 执行 `sudo apt-get install python3-venv`，CentOS 执行 `sudo dnf install python3-virtualenv`。

**Q4: 图层加载报错 "Could not load MBTiles / SQLite database is locked"**
- **原因**：SQLite 数据库存在并发读写锁或文件权限问题。
- **解决**：检查 `cache_data/` 目录和 mbtiles 文件的读写权限（确保服务运行用户拥有 `+w` 权限），或检查是否有其他进程正在独占写入该文件。

## 11. 版本现状与迁移提示

- 历史目录 `modules/ui/` 已统一迁移为 `src/ui/`。
- 历史配置 `config.json`、`advanced_settings.json` 仅用于兼容读取，不再作为持久化写入目标。
- 当前唯一持久化配置为 `MapProxyLauncher/mapproxy_config/map_config.json`。
- 历史 `seed_status.json`、`deps_status.json` 会迁移至 `mapproxy_config/` 下。
- 运行说明统一以 `.venv` 为标准；代码中仍保留对 `venv/` 的兼容探测。
