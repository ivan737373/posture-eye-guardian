"""main.py —— 程序入口（B 负责线程启动，C 负责调起界面）"""
import sys
from PySide6.QtWidgets import QApplication
from data import database
from data.worker import start_monitor
from ui.main_window import MainWindow

def main():
    # 初始化数据库
    database.init_db()
    
    # 启动 B 的后台监控线程
    worker, result_q = start_monitor()
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 调起 C 的主界面，把后台数据传进去
    win = MainWindow(worker, result_q)
    win.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()