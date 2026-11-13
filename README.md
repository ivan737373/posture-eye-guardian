# 健康坐姿助手

基于 MediaPipe 的桌面端坐姿监测应用：实时检测驼背、离屏过近和久坐，
通过弹窗与语音提醒用户，并记录每日不良姿势统计。

## 环境要求

- Windows 10/11
- **Python 3.11.9**（必须，不要用 3.12 及以上）
- PySide6 6.12.0


## 文件归属

> **原则：只改自己文件夹里的东西，跨文件夹的改动先在群里说一句！！**

| 路径 | 负责人 | 别人能改吗 | 内容 |
|---|---|---|---|
| `vision/` | A | 不要动 | MediaPipe 检测、几何计算、校准算法 |
| `models/` | A | 不要动 | 两个 `.task` 模型文件 |
| `data/` | **B** | 不要动 | 数据库、后台线程、5 秒判定、队列 |
| `ui/main_window.py` | C | B、A 不改 | 主窗口、托盘、弹窗、设置面板 |
| `ui/charts.py` | D | B、A 不改 | 图表、报告导出 |
| `main.py` | C（主）+ B（线程部分） | 改前知会 | 程序入口 |
| `README.md` | D（主）+ B（技术部分） | 改前知会 | 项目说明 |
| `requirements.txt` | **B** | 加包先知会 | 依赖清单 |
| `.gitignore` | B | 不要动 | 排除规则 |

### `main.py` 内部划分

| 部分 | 归属 | 说明 |
|---|---|---|
| `_build_ui()` | C | 界面布局，可以整个重写 |
| `_apply()` / `_on_break()` / `_on_resume()` | C | 结果显示、休息提示 |
| `draw_overlay()` / `draw_face_box()` | C | 画面叠加，建议用 QPainter 重写 |
| `_poll()` 的队列读取 | B | 线程边界，写错会崩 |
| `closeEvent()` | B | 必须调 `stop_and_wait()` |
| `__init__` 启动 worker | B | `start_monitor()` 调用 |

### 各组员核心贡献

| 人 | 负责内容 |
|---|---|
| A | MediaPipe 双模型、坐标系转换、几何判定、校准算法、防抖 |
| B | 多线程架构、队列通信、5 秒积分判定、SQLite 三表、久坐计时、设置持久化 |
| C | PySide6 界面、托盘常驻、气泡弹窗、语音播报、全屏休息遮罩、设置面板 |
| D | 数据图表、健康报告导出、架构图/UML、测试用例、PyInstaller 打包 |

## 演示顺序

1. 启动程序，等摄像头画面出现
2. 点「校准坐姿」，坐正保持 3 秒，等提示「校准完成」
3. 点「校准距离」，正对镜头保持 3 秒（参考距离 60cm，需提前量好）
4. 开始演示各项功能

> **不校准的话所有判定的结果都是"未知"，功能看起来完全不工作。**
> 每次启动程序都需要重新校准一次。

## 协作方式（Gitee）
Gitee仓库同步代码非常方便！这是一些使用指南，大家可以参考一下❤

仓库地址：https://gitee.com/ivan73/python202611


### 一、第一次拉代码

**必须用 `git clone` 拉到一个新文件夹**，不要在自己已有的旧项目里操作。

```bash
cd D:\
git clone https://gitee.com/ivan73/python202611.git
cd python202611
py -3.11 -m venv .venv
```

激活虚拟环境：

| 终端类型 | 命令 |
|---|---|
| cmd | `.venv\Scripts\activate` |
| PowerShell | `.venv\Scripts\activate` |
| Git Bash | `source .venv/Scripts/activate` |

激活成功的标志：命令行前面出现 `(.venv)`。

安装依赖：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 路径请用纯英文（如 `D:\python202611`），中文路径会导致某些库和打包工具出错。

### 二、日常开发流程

**每次开始干活前，先拉一次最新代码：**

```bash
git pull
```

**改完代码，提交并推送：**

```bash
git add .
git commit -m "说明改了什么"
git push
```

**提交信息要写清楚**，例如：

- ✅ `修复久坐计时被断流清零的问题`
- ✅ `新增托盘图标和右键菜单`
- ❌ `更新`
- ❌ `改了一下`

> 本项目规模很小，**统一直接推 main 分支，不要开新分支**，减少合并成本。

### 三、PyCharm 里的操作

**1. 打开项目**

`File` → `Open`，选择 clone 下来的文件夹（选文件夹本身，不是里面的文件）。

**2. 设置解释器**

`Ctrl + Alt + S` → `Python` → `解释器` → 添加本地解释器 → 选择现有 → 类型选 `Python`
→ 路径填：

```
D:\python202611\.venv\Scripts\python.exe
```

成功后右下角显示 `Python 3.11.9`。

**3. 提交代码（图形界面）**

- `Ctrl + K` 打开提交面板
- 勾选要提交的文件（**确认没有 `.venv` 和 `health.db`**）
- 填提交信息 → 点「提交并推送」

**4. 拉取最新代码**

菜单 `Git` → `拉取`（Pull），或在提交面板点左上角的下载箭头。

**5. 使用终端**

`Alt + F12` 打开终端。**PyCharm 的终端会自动激活 venv**，提示符直接是 `(.venv)`。

### 四、VS Code 里的操作

**1. 装 Python 扩展**

`Ctrl + Shift + X` → 搜 `Python` → 装微软官方那个。

**2. 打开项目**

```bash
code D:\python202611
```

**3. 选择解释器**

`Ctrl + Shift + P` → 输入 `Python: Select Interpreter` → 选：

```
.\.venv\Scripts\python.exe
```

成功后右下角显示 `Python 3.11.9`。

**4. 终端要手动激活（重要）**

`Ctrl + ~` 打开终端后，**每次都要先执行**：

```bash
.venv\Scripts\activate
```

看到 `(.venv)` 前缀才算成功。**不激活的话 `pip install` 会装到系统 Python 里**，这是最常见的坑。

如果 PowerShell 提示「禁止运行脚本」，执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**5. 提交代码（图形界面）**

- `Ctrl + Shift + G` 打开源代码管理面板
- 改动会列在「更改」里，点 `+` 暂存
- 填消息 → 点 `✓` 提交
- 点 `...` → 「推送」

**6. 拉取最新代码**

源代码管理面板 → `...` → 「拉取」。

### 五、不要提交的文件

以下已在 `.gitignore` 中排除，**不要手动加进去**：

| 文件/目录 | 原因 |
|---|---|
| `.venv/` | 各人本地环境，几百 MB |
| `data/health.db`、`*.db-wal`、`*.db-shm` | 各人本地数据库 |
| `__pycache__/` | Python 编译缓存 |
| `.idea/` | PyCharm 项目配置 |

**要提交的**：`models/` 里的两个 `.task` 模型文件（9MB），必须入库，否则别人跑不了。
### 六、常用命令速查

| 目的 | 命令 |
|---|---|
| 拉最新代码 | `git pull` |
| 看改了哪些文件 | `git status` |
| 看具体改了什么 | `git diff` |
| 全部暂存 | `git add .` |
| 提交 | `git commit -m "说明"` |
| 推送 | `git push` |
| 查看提交历史 | `git log --oneline` |
| 查看远程地址 | `git remote -v` |
| 撤销未提交的改动 | `git checkout -- 文件名` |
## 七、打包与运行说明（组员 D 补充）
- 本项目已使用 PyInstaller 成功打包为 Windows 可执行文件（.exe）。
- 运行说明：直接双击 `健康坐姿助手.exe` 即可运行，无需配置 Python 环境。
- 图表导出：在程序界面点击“查看健康报告”，在弹窗中点击“导出健康报告 (PNG图片)”，会生成 `健康报告图表.png` 并弹窗提示保存路径。
- 数据说明：首次运行会在同级目录自动生成 `health.db` 数据库和 `logging.txt` 日志文件。