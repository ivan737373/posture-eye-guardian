"""ui/charts.py —— D 组员负责的图表与报告导出"""

import os
import sys
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 解决中文显示乱码
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt

from data import database

class ChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("健康坐姿统计报告")
        self.resize(800, 600)
        self.setStyleSheet("background-color: #2c3e50; color: white;")

        layout = QVBoxLayout(self)

        self.title = QLabel("最近 7 天不良坐姿统计")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 24px; font-weight: bold; margin: 10px;")
        layout.addWidget(self.title)

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        btn_layout = QHBoxLayout()

        # 👇 修改点1：按钮文字改成了 PNG 图片
        self.btn_export = QPushButton("导出健康报告 (PNG图片)")
        self.btn_export.setStyleSheet("background-color: #2ecc71; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self.export_report)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setStyleSheet("background-color: #e74c3c; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.load_data_and_plot()

    def load_data_and_plot(self):
        try:
            stats_list = database.weekly_stats()
            dates = []
            counts = []
            for stat in stats_list:
                dates.append(stat["date"][5:])
                counts.append(stat["bad_posture_total"])
            self.plot_chart(dates, counts)
        except Exception as e:
            print("❌ 读取数据库失败:", e)
            self.plot_chart([], [])

    def plot_chart(self, dates, counts):
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        total_count = sum(counts)
        self.title.setText(f"最近 7 天不良坐姿统计 (总计: {total_count} 次)")

        if not dates or all(c == 0 for c in counts):
            ax.text(0.5, 0.5, "暂无不良姿势记录\n请保持不良坐姿5秒以上以产生数据",
                    horizontalalignment='center', verticalalignment='center',
                    transform=ax.transAxes, fontsize=14, color='gray')
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            ax.plot(dates, counts, marker='o', linestyle='-', color='#e74c3c', linewidth=2)
            ax.fill_between(dates, counts, color='#e74c3c', alpha=0.1)

            ax.set_xlabel("日期", fontsize=12)
            ax.set_ylabel("不良姿势次数", fontsize=12)
            ax.grid(True, linestyle='--', alpha=0.6)
            ax.set_ylim(bottom=0, top=max(counts) + 2)

            for i, v in enumerate(counts):
                ax.text(i, v + 0.2, str(v), ha='center', va='bottom', fontweight='bold', color='#e74c3c')

        self.figure.tight_layout()
        self.canvas.draw()

    # 👇 修改点2：完整的导出逻辑，带弹窗提示保存路径
    def export_report(self):
        try:
            # 获取当前 exe (或代码) 所在的绝对目录
            current_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            save_path = os.path.join(current_dir, "健康报告图表.png")

            # 保存高清图片
            self.figure.savefig(save_path, dpi=300, bbox_inches='tight')

            # 弹窗提示用户
            msg = QMessageBox(self)
            msg.setWindowTitle("导出成功")
            msg.setText(f"图表已成功导出为高清图片！\n\n保存位置：\n{save_path}")
            msg.setIcon(QMessageBox.Information)
            msg.exec()

        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"导出失败，原因：\n{str(e)}")