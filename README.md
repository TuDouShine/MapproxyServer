# MapProxy Server Launcher

## 1. 项目概述

**项目名称**：MapProxy Server Launcher  
**版本**：1.1.0

本项目是一个基于 **Python**、**MapProxy** 和 **Waitress** 的轻量级地图服务发布程序，提供直观的 **GUI 图形界面**。它旨在简化地图服务的部署流程，提供“开箱即用”的体验。

### 核心特性

*   **可视化管理界面 (GUI)**：提供友好的图形界面，轻松配置 Python 环境、服务端口，并实时监控运行状态。
*   **实时状态监控**：界面实时显示服务初始化、运行成功、失败等状态，并提供详细的运行日志。
*   **快捷交互操作**：支持一键复制服务地址、在浏览器打开服务、打开工作目录等快捷操作。
*   **图层信息面板**：自动解析 `mapproxy.yaml` 配置文件，列出所有可用图层及其缓存格式，支持点击一键复制图层名称和格式。
*   **自动化环境管理**：自动检测系统 Python 版本，创建独立的虚拟环境（venv），避免污染系统环境。
*   **离线依赖支持**：支持自动下载依赖包到本地 `packages/` 目录，实现依赖的离线化归档与安装，便于在无外网环境迁移部署。
*   **高性能服务**：集成 Waitress WSGI 服务器，提供稳定、快速的瓦片地图服务。
*   **动态缓存**：基于 MapProxy 实现全球影像地图的动态缓存与切片服务，支持 WMS、TMS 等标准协议。

**技术栈**：
*   **界面**：Python Tkinter
*   **核心引擎**：MapProxy
*   **WSGI 服务器**：Waitress
*   **打包**：PyInstaller

---

## 2. 快速开始

### 2.1 运行方式

#### 方式一：GUI 启动器 (推荐)
直接运行根目录下的 **`MapProxyLauncher.exe`** (如果是源码运行则为 `python gui_launcher.py`)。

1.  **Python 环境设置**：程序会自动扫描系统的 Python 解释器，在下拉列表中选择一个可用的 Python 版本（推荐 3.8+）。
2.  **服务设置**：输入服务端口（默认为 7001）。
3.  **图层信息**：在界面中部可以查看当前配置的地图图层信息。
4.  **启动服务**：点击“启动服务”按钮。
    *   状态栏将显示“正在初始化...” -> “运行成功”。
    *   成功后会显示访问地址（如 `http://127.0.0.1:7001`）。
5.  **访问地图**：点击“浏览器打开”按钮即可访问服务演示页面。

#### 方式二：命令行 (高级)
如果你偏好命令行或需要调试，可以直接运行 `main.py`：

```powershell
python main.py
```

### 2.2 离线部署（迁移至内网）

1.  **准备**：在有网环境运行一次程序，确保 `packages/` 目录下已自动下载所有依赖文件。
2.  **迁移**：将整个 `MapproxyServer` 文件夹拷贝到无网的目标机器。
3.  **运行**：在目标机器上直接运行 `MapProxyLauncher.exe`。程序会自动检测离线包并完成环境安装。

### 2.3 Linux 服务器部署 (无 GUI)

本项目完全支持在 Linux 服务器（如 Ubuntu/CentOS）上以无头模式运行。

#### 方式一：Shell 脚本启动
适合开发调试或简单部署。

1.  **环境准备**：
    ```bash
    # Ubuntu/Debian 需确保安装 python3-venv
    sudo apt-get update && sudo apt-get install python3 python3-venv xdg-utils
    ```
2.  **启动服务**：
    ```bash
    chmod +x run.sh
    ./run.sh 8080
    ```
    脚本会自动检测 Python 环境、创建虚拟环境（venv）、安装 `requirements.txt` 中的依赖，并启动服务。

#### 方式二：Systemd 系统服务 (推荐)
适合生产环境，支持开机自启和后台运行。

1.  修改 `mapproxy.service` 文件中的路径配置（默认为 `/opt/MapproxyServer`）。
2.  安装并启动服务：
    ```bash
    sudo cp mapproxy.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable mapproxy
    sudo systemctl start mapproxy
    ```
3.  查看日志：
    ```bash
    tail -f /var/log/mapproxy.log
    ```

### 2.4 Linux 服务器离线部署指南 (内网环境)

针对无法连接外网的 Linux 服务器，请严格按照以下步骤进行部署。

#### 第一阶段：在线环境准备 (依赖打包)
**关键提示**：为了确保依赖包（特别是包含 C 扩展的库，如 Pillow）与目标 Linux 服务器架构兼容，**必须在与目标服务器架构相同或兼容的 Linux 环境下**（如本地 Linux 虚拟机、WSL 或相同系统的测试机）执行下载操作。**切勿在 Windows 下下载 Linux 的依赖包**。

1.  **准备环境**：
    在有一台可联网的 Linux 机器上，确保安装了 Python 3 (建议 3.8+)。

2.  **下载依赖**：
    进入项目根目录，执行以下命令将所有依赖下载到 `packages` 目录：
    直接运行启动脚本。程序会自动下载检测 `packages` 目录下的依赖包并完成虚拟环境的构建与依赖安装。
    ```bash
    chmod +x run.sh
    ./run.sh 8080

3.  **打包项目**：
    确认 `packages` 目录已包含所有 `.whl` 或 `.tar.gz` 文件后，将整个项目目录打包：
    ```bash
    # 返回上级目录打包
    cd ..
    tar -czvf mapproxy-offline.tar.gz MapproxyServer/
    ```

#### 第二阶段：离线环境部署

1.  **环境检查**：
    确保目标内网服务器已安装 Python 3 和 venv 模块。
    ```bash
    python3 --version
    # 检查 venv 模块 (Debian/Ubuntu 可能需要离线安装 python3-venv deb包)
    python3 -m venv --help
    ```
    *如果缺少 venv，需从 OS 安装盘或镜像源获取对应的 `python3-venv` 软件包进行安装。*

2.  **解压安装**：
    将 `mapproxy-offline.tar.gz` 上传至目标服务器并解压：
    ```bash
    tar -xzvf mapproxy-offline.tar.gz
    cd MapproxyServer
    ```

3.  **配置调整 (重要)**：
    内网环境通常无法访问互联网地图源（如默认配置中的 ArcGIS Online）。需修改 `mapproxy.yaml`：
    *   将 `sources` 中的 `url` 指向内网发布的 GIS 服务地址。
    *   或者确保 `cache_data` 目录中已包含完整的预生成瓦片缓存。

4.  **启动服务**：
    直接运行启动脚本。程序会自动检测 `packages` 目录下的离线包并完成虚拟环境的构建与依赖安装，全程无需联网。
    ```bash
    chmod +x run.sh
    ./run.sh 8080
    ```

5.  **验证部署**：
    使用 `curl` 验证服务是否正常响应：
    ```bash
    curl -I http://127.0.0.1:8080/demo/
    ```
    若返回 `HTTP/1.1 200 OK`，则服务启动成功。

#### 常见问题排查

*   **Q: 安装时提示 `No matching distribution found`？**
    *   **原因**：`packages` 目录下的依赖包与当前系统架构或 Python 版本不匹配。
    *   **解决**：请务必在与目标服务器环境尽可能一致的在线机器上重新执行下载步骤。

*   **Q: 提示 `ModuleNotFoundError: No module named 'venv'`？**
    *   **原因**：部分 Linux 发行版（如 Ubuntu）默认精简了 venv 模块。
    *   **解决**：需联系运维人员安装 `python3-venv`。

---

## 3. 打包与发布

本章详细说明如何将 MapProxyLauncher 打包为独立的可执行程序 (`.exe`)，以便在未安装 Python 环境的 Windows 机器上直接运行。

### 3.1 打包前提条件

确保开发环境已安装以下工具和库：

*   **Python 3.8+** (建议与目标运行环境一致)
*   **PyInstaller**: 核心打包工具
    ```bash
    pip install pyinstaller
    ```
*   **UPX** (可选): 用于压缩可执行文件体积。如果安装，PyInstaller 会自动检测。

### 3.2 配置文件说明

项目根目录下已包含 `build.spec` 配置文件，用于定义打包规则。该文件已针对 MapProxy 的特殊结构进行了预配置。

**关键配置解析 (`build.spec`)**:

```python
# 数据文件 (datas): 将非代码资源打包进 exe
datas = [
    ('main.py', '.'),              # 核心服务逻辑
    ('mapproxy.yaml', '.'),        # 默认配置
    ('requirements.txt', '.'),     # 依赖列表
    # ... MapProxy 内部模板和配置
    (os.path.join(mapproxy_path, 'config', 'config-schema.json'), 'mapproxy/config'),
]

# 隐藏导入 (hiddenimports): 显式声明动态加载的模块
hiddenimports = [
    'waitress', 'mapproxy', 'PIL', 'mapproxy.wsgiapp'
]

# 打包模式: 
# console=False (不显示控制台窗口，仅 GUI)
# EXE(...) 中包含了 a.binaries, a.zipfiles, a.datas (单文件模式)
```

### 3.3 分步打包指南
 
 #### 方式一：使用自动化构建脚本 (推荐)
 
 我们提供了一个跨平台的构建脚本 `build.py`，它会自动检测当前系统并在 `dist/` 目录下生成对应的可执行文件。
 
 1.  **准备环境**: 确保已安装 PyInstaller。
     ```bash
     pip install pyinstaller
     ```
 2.  **运行构建**:
     ```bash
     python build.py
     ```
 3.  **获取产物**:
     *   **Windows**: 生成 `dist/MapProxyLauncher.exe`
     *   **Linux**: 生成 `dist/MapProxyLauncher` (无后缀单文件)
 
 #### 方式二：手动执行 PyInstaller
 
 如果你需要手动控制参数，可以直接使用 PyInstaller。
 
 **Windows 构建**:
 ```bash
 pyinstaller build.spec
 ```
 
 **Linux 构建**:
 在 Linux 环境下（无法在 Windows 上交叉编译 Linux 程序），执行相同的命令：
 ```bash
 pyinstaller build.spec
 ```
 
 *注：`build.spec` 已配置为根据运行平台自动调整参数（如文件后缀、路径分隔符等）。*
 
 ### 3.4 依赖处理与资源打包

由于 MapProxy 包含大量非 Python 资源（如模板、配置 schema），我们采用了以下策略确保其在打包后可用：

1.  **静态资源嵌入**: 在 `build.spec` 的 `datas` 列表中，显式指定了 `mapproxy.yaml`, `templates` 等文件的包含路径。
2.  **运行时资源释放**: `gui_launcher.py` 检测到运行在 Frozen (打包) 模式下时，会利用 `sys._MEIPASS` 访问临时目录，并将必要的文件（如 `mapproxy.yaml`, `config.py`）部署到用户的**工作目录** (`MapProxyLauncher/`) 中。
    *   *机制*: 首次运行时，程序会自动将内嵌的配置文件复制到 exe 同级目录下的 `MapProxyLauncher` 文件夹，确保用户可以修改配置。

### 3.5 测试与验证

打包完成后，请按以下步骤验证：

1.  **环境清理**: 将 `dist/MapProxyLauncher.exe` 复制到一个**没有安装 Python** 的干净 Windows 虚拟机或沙箱中。
2.  **初次运行**: 双击运行 exe。
    *   *验证*: 检查是否在 exe 旁边自动生成了 `MapProxyLauncher` 文件夹。
3.  **功能测试**:
    *   在 GUI 中点击“启动服务”。
    *   点击“浏览器打开”，确认地图服务页面能正常加载。
    *   检查“图层信息”面板是否正确显示图层列表。
4.  **常见问题排查**:
    *   *错误 "Failed to execute script gui_launcher"*: 通常是因为缺少隐藏导入。尝试在 `build.spec` 的 `hiddenimports` 中添加缺失的模块，然后重新打包。
    *   *地图无法加载*: 检查工作目录下的 `mapproxy.yaml` 是否正确生成。

### 3.6 高级选项

*   **调试模式**: 如果遇到启动报错但看不到日志，可以修改 `build.spec` 中的 `console=False` 为 `console=True`，重新打包后运行，即可看到控制台输出的详细错误信息。
*   **目录模式 (One-Directory)**: 如果希望加快启动速度，可以将打包模式改为目录模式（修改 `EXE` 参数并添加 `COLLECT` 步骤），但这需要分发整个文件夹。

### 3.7 版本管理与发布

建议在发布新版本时：
1.  在 `gui_launcher.py` 或 `README.md` 中更新版本号。
2.  运行打包命令生成 exe。
3.  将 exe 文件重命名为 `MapProxyLauncher_vX.X.X.exe` 进行分发。

---

## 4. 界面功能详解

### 4.1 主界面布局
*   **Python 环境设置**：只读下拉列表，展示检测到的 Python 解释器路径。
*   **服务设置**：端口配置，支持 1-65535 范围。
*   **图层信息**：
    *   **图层名称**：显示 `mapproxy.yaml` 中定义的图层，**点击即可复制**。
    *   **缓存格式**：显示对应的瓦片格式（如 `image/png`），**点击即可复制**。
*   **控制按钮**：
    *   `确认设置`：保存当前配置到 `config.json`。
    *   `启动服务` / `停止服务`：控制服务生命周期。
*   **运行状态**：
    *   显示当前状态（就绪、运行中、失败）。
    *   显示服务访问地址。
    *   提供 **复制地址**、**浏览器打开**、**打开工作目录** 等快捷按钮。
*   **运行日志**：实时输出后端服务的控制台日志，支持不同颜色高亮（错误标红、成功标绿）。

---
 
 ## 5. 项目结构说明

```text
MapproxyServer/
├── MapProxyLauncher.exe      # [入口] GUI 启动程序（打包版）
├── gui_launcher.py           # [源码] GUI 启动程序源码
├── main.py                   # [核心] 服务主逻辑，负责环境构建与服务启动
├── config.py                 # [配置] Waitress 服务器启动脚本
├── mapproxy.yaml             # [配置] MapProxy 核心配置文件（图层、源、缓存规则）
├── requirements.txt          # [配置] 项目依赖列表
├── venv/                     # [自动生成] Python 虚拟环境目录
├── packages/                 # [自动生成] 离线依赖包存放目录
├── MapProxyLauncher/         # [数据] GUI 模式下的工作目录（存放日志、配置副本等）
│   ├── config.json           # GUI 用户配置文件
│   ├── logs/                 # 服务运行日志
│   └── ...
└── cache_data/               # [自动生成] 地图瓦片缓存数据目录
```

---
 
 ## 6. 常见问题解答 (FAQ)

**Q: 启动时提示 "PermissionError"？**
A: 请尝试以管理员身份运行程序，或检查端口是否被其他程序占用。

**Q: 为什么图层列表是空的？**
A: 请检查 `mapproxy.yaml` 文件是否配置正确，且位于正确的位置（源码模式在根目录，GUI 模式在 `MapProxyLauncher` 目录下）。

**Q: 如何修改地图源？**
A: 编辑 `mapproxy.yaml` 文件，修改 `sources` 和 `layers` 部分。修改后重启服务即可生效。

**Q: 如何清理缓存和重置环境？**
A: 直接删除 `cache_data/` 目录下的所有文件即可。MapProxy 会在下次访问时自动重新生成。

**Q: 如何重置环境？**
A: 如果遇到环境问题，可以直接删除 `venv/` 目录。下次运行时会自动重建。

**Q: GUI 中的 Python 列表无法手动输入？**
A: 为了保证稳定性，列表被设计为只读。如果你的 Python 未被检测到，请确保它已添加到系统环境变量 PATH 中，或点击“刷新列表”重试。

---

## 7. 更新日志

### v1.3.0 (2026-01-27)
*   **新增**：增强的服务停止机制。GUI 关闭时会自动终止服务进程，并基于端口检测确保服务彻底停止，防止端口占用残留。
*   **新增**：引入 `psutil` 库进行跨平台的进程管理。
*   **新增**：跨平台打包构建脚本 `build.py`，支持一键生成 Windows (.exe) 和 Linux 可执行文件。
*   **优化**：更新打包配置 `build.spec` 以支持跨平台路径处理。

### v1.2.0 (2026-01-26)
*   **新增**：Linux 服务器离线部署指南，支持内网环境迁移。
*   **新增**：`run.sh` 启动脚本，集成环境检测与自动化启动。
*   **新增**：`mapproxy.service` 配置文件，支持 Systemd 服务化部署。

### v1.1.0 (2026-01-26)
*   **新增**：GUI 状态显示区域，支持显示初始化、成功、失败状态。
*   **新增**：图层信息面板，支持点击复制图层名称和缓存格式。
*   **优化**：Python 版本选择列表改为只读模式，并优化了视觉样式（移除选中时的蓝色背景）。
*   **优化**：完善了“打开工作目录”功能，直接打开文件夹而非运行程序。
*   **优化**：添加了 Toast 提示消息，提升交互体验。

### v1.0.0
*   初始版本发布，支持基础的地图服务发布与离线环境构建。
