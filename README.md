# 健康坐姿助手

基于 MediaPipe 的桌面端坐姿监测应用：实时检测驼背、离屏过近和久坐，通过弹窗与语音提醒用户，并记录每日不良姿势统计。

## 环境要求
- Windows 10/11
- Python 3.11.9（必须，不要用 3.12 及以上）
- PySide6 6.12.0

## 项目结构与分工

| 路径 | 负责模块 | 内容说明 |
|---|---|---|
| vision/ | A (视觉) | MediaPipe 检测、几何计算、校准算法 |
| models/ | A (视觉) | 两个 .task 模型文件 |
| data/ | B (后台) | 数据库、后台线程、5秒判定、队列 |
| ui/main_window.py | C (界面) | 主窗口、托盘、弹窗、设置面板 |
| ui/charts.py | D (数据) | 图表绘制、健康报告导出 |
| main.py | C + B | 程序入口与线程控制 |

核心贡献：
- A：MediaPipe 双模型、坐标系转换、几何判定、防抖。
- B：多线程架构、队列通信、SQLite 建表、久坐计时。
- C：PySide6 界面、托盘常驻、气泡弹窗、语音播报。
- D：数据图表、健康报告导出、架构图/测试用例、PyInstaller 打包。

## 演示顺序
1. 启动程序，等摄像头画面出现。
2. 点击「校准坐姿」，坐正保持 3 秒，等提示「校准完成」。
3. 点击「校准距离」，正对镜头保持 3 秒（参考距离 60cm，需提前量好）。
4. 开始演示各项功能。

> 注意：不校准的话所有判定的结果都是"未知"，功能看起来完全不工作。每次启动程序都需要重新校准一次。

## 源码获取与运行指南

代码托管于 GitHub：https://github.com/ivan737373/posture-eye-guardian

请在终端（推荐使用 CMD 或 PowerShell）中按顺序执行以下命令：

# 1. 克隆项目并进入目录
git clone https://github.com/ivan737373/posture-eye-guardian.git
cd posture-eye-guardian

# 2. 创建并激活 Python 3.11 虚拟环境
py -3.11 -m venv .venv
.venv\Scripts\activate

# 3. 安装依赖 (使用清华源加速)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 启动程序
python main.py

## 打包与独立运行说明

- 独立运行：本项目已使用 PyInstaller 成功打包为 Windows 可执行文件（.exe）。无需配置 Python 环境，直接双击 `健康坐姿助手.exe` 即可运行。
- 图表导出：在程序界面右侧点击紫色的“查看健康报告”按钮。在弹出的窗口点击“导出健康报告 (PNG图片)”，会在同级目录生成 `健康报告图表.png` 并弹窗提示保存路径。
- 数据说明：首次运行会在同级目录自动生成 `health.db` 本地数据库和 `logging.txt` 日志文件。