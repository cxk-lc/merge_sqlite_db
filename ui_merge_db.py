import sys
import os
import configparser
import sqlite3
import shutil
import traceback
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QGroupBox, QFileDialog, QMessageBox,
                             QGridLayout, QCheckBox, QTableWidget,
                             QTableWidgetItem,
                             QHeaderView, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QColor

# 导入您原有的模块
from log import logger
from tool import get_path


class DatabaseTester(QThread):
    """数据库连接测试线程"""
    log_signal = pyqtSignal(str)
    table_info_signal = pyqtSignal(list)  # 发送表结构信息
    test_result_signal = pyqtSignal(bool, str)

    def __init__(self, db_path, table_name):
        super().__init__()
        self.db_path = db_path
        self.table_name = table_name

    def run(self):
        try:
            self.log_signal.emit(f"开始测试数据库连接: {self.db_path}")

            # 检查文件是否存在
            if not os.path.exists(self.db_path):
                error_msg = f"数据库文件不存在: {self.db_path}"
                self.log_signal.emit(error_msg)
                self.test_result_signal.emit(False, error_msg)
                return

            # 尝试连接数据库
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                self.log_signal.emit("数据库连接成功")
            except Exception as e:
                error_msg = f"数据库连接失败: {str(e)}"
                self.log_signal.emit(error_msg)
                self.test_result_signal.emit(False, error_msg)
                return

            # 检查表是否存在
            try:
                cursor.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (self.table_name,))
                table_exists = cursor.fetchone()

                if not table_exists:
                    error_msg = f"表 '{self.table_name}' 不存在于数据库中"
                    self.log_signal.emit(error_msg)
                    self.test_result_signal.emit(False, error_msg)
                    conn.close()
                    return

                self.log_signal.emit(f"表 '{self.table_name}' 存在")
            except Exception as e:
                error_msg = f"检查表存在性失败: {str(e)}"
                self.log_signal.emit(error_msg)
                self.test_result_signal.emit(False, error_msg)
                conn.close()
                return

            # 获取表结构信息
            try:
                cursor.execute(f"PRAGMA table_info({self.table_name})")
                columns_info = cursor.fetchall()

                table_info = []
                for col in columns_info:
                    # col[1]是列名，col[2]是数据类型，col[3]是是否允许NULL，col[4]是默认值，col[5]是主键
                    table_info.append({
                        'cid': col[0],
                        'name': col[1],
                        'type': col[2],
                        'notnull': col[3],
                        'dflt_value': col[4],
                        'pk': col[5]
                    })

                self.log_signal.emit(
                    f"成功获取表结构，共 {len(table_info)} 个字段")
                self.table_info_signal.emit(table_info)
                self.test_result_signal.emit(True, "数据库连接测试成功")

            except Exception as e:
                error_msg = f"获取表结构失败: {str(e)}"
                self.log_signal.emit(error_msg)
                self.test_result_signal.emit(False, error_msg)

            finally:
                conn.close()

        except Exception as e:
            error_msg = f"测试过程中发生未知错误: {str(e)}"
            self.log_signal.emit(error_msg)
            self.test_result_signal.emit(False, error_msg)


class MergeWorker(QThread):
    """后台合并工作线程"""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, src_db, dst_db, table_name, exclude_columns):
        super().__init__()
        self.src_db = src_db
        self.dst_db = dst_db
        self.table_name = table_name
        self.exclude_columns = exclude_columns

    def log_message(self, message):
        """同时输出到UI和logger模块"""
        self.log_signal.emit(message)
        logger.info(message)

    def run(self):
        try:
            self.log_message("开始数据库合并操作...")

            # 备份文件
            self.backup_files()

            # 合并数据库
            success = self.merge_databases()

            if success:
                # 重命名文件
                self.rename_files()
                self.log_message("数据库合并完成！")
                self.finished_signal.emit(True, "数据库合并成功完成！")
            else:
                self.finished_signal.emit(False, "数据库合并失败，请检查日志！")

        except Exception as e:
            error_msg = f"合并过程中发生错误: {str(e)}"
            self.log_message(error_msg)
            logger.error(traceback.format_exc())
            self.finished_signal.emit(False, error_msg)

    def backup_files(self):
        """备份文件"""
        for file_path in [self.dst_db, self.src_db]:
            if os.path.exists(file_path):
                backup_file = f"{file_path}.backup"
                shutil.copy2(file_path, backup_file)
                self.log_message(f"已创建备份文件: {backup_file}")

    def merge_databases(self):
        """合并数据库（基于原有逻辑修改）"""
        try:
            # 连接到第一个数据库
            conn1 = sqlite3.connect(self.dst_db)
            cursor1 = conn1.cursor()

            # 连接到第二个数据库
            conn2 = sqlite3.connect(self.src_db)
            cursor2 = conn2.cursor()

            # 获取表的列信息
            cursor1.execute(f"PRAGMA table_info({self.table_name})")
            columns_info = cursor1.fetchall()

            # 提取列名（排除指定列）
            column_names = [col[1] for col in columns_info if
                            col[1] not in self.exclude_columns]

            if not column_names:
                self.log_message("错误：未找到有效的列")
                return False

            # 构建列名字符串
            columns_str = ', '.join(column_names)
            placeholders = ', '.join(['?' for _ in column_names])

            # 从源数据库读取数据
            cursor2.execute(f"SELECT {columns_str} FROM {self.table_name}")
            rows = cursor2.fetchall()

            # 插入数据到目标数据库
            insert_sql = f"INSERT INTO {self.table_name} ({columns_str}) VALUES ({placeholders})"

            count = 0
            for row in rows:
                cursor1.execute(insert_sql, row)
                count += 1

            # 提交事务
            conn1.commit()

            self.log_message(f"成功合并 {count} 条记录")

            # 显示合并后的总记录数
            cursor1.execute(f"SELECT COUNT(*) FROM {self.table_name}")
            total = cursor1.fetchone()[0]
            self.log_message(f"合并后总记录数: {total}")

            conn1.close()
            conn2.close()

            return True

        except Exception as e:
            self.log_message(f"合并过程中发生错误: {e}")
            logger.error(traceback.format_exc())
            return False

    def rename_files(self):
        """重命名文件"""
        try:
            shutil.move(self.dst_db, self.src_db)
            self.log_message(f"文件已重命名: {self.dst_db} -> {self.src_db}")
        except Exception as e:
            self.log_message(f"重命名失败: {e}")
            raise e


class DatabaseMergerUI(QMainWindow):
    """SQLite数据库合并工具主界面"""

    def __init__(self):
        super().__init__()
        self.worker = None
        self.tester = None
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("SQLite数据库合并工具")
        self.setGeometry(100, 100, 750, 400)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        layout = QVBoxLayout(central_widget)

        # 创建选项卡
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # 配置选项卡
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)

        # 参数配置组
        config_group = QGroupBox("数据库合并配置")
        config_grid = QGridLayout()

        # 源数据库路径
        config_grid.addWidget(QLabel("源数据库路径:"), 0, 0)
        self.src_db_edit = QLineEdit()
        self.src_db_edit.setPlaceholderText("请选择源数据库文件路径")
        config_grid.addWidget(self.src_db_edit, 0, 1)
        self.src_browse_btn = QPushButton("浏览...")
        self.src_browse_btn.clicked.connect(self.browse_src_db)
        config_grid.addWidget(self.src_browse_btn, 0, 2)
        self.src_test_btn = QPushButton("测试连接")
        self.src_test_btn.clicked.connect(lambda: self.test_connection('src'))
        config_grid.addWidget(self.src_test_btn, 0, 3)

        # 目标数据库路径
        config_grid.addWidget(QLabel("目标数据库路径:"), 1, 0)
        self.dst_db_edit = QLineEdit()
        self.dst_db_edit.setPlaceholderText("请选择目标数据库文件路径")
        config_grid.addWidget(self.dst_db_edit, 1, 1)
        self.dst_browse_btn = QPushButton("浏览...")
        self.dst_browse_btn.clicked.connect(self.browse_dst_db)
        config_grid.addWidget(self.dst_browse_btn, 1, 2)
        self.dst_test_btn = QPushButton("测试连接")
        self.dst_test_btn.clicked.connect(lambda: self.test_connection('dst'))
        config_grid.addWidget(self.dst_test_btn, 1, 3)

        # 表名
        config_grid.addWidget(QLabel("合并的表名:"), 2, 0)
        self.table_edit = QLineEdit()
        self.table_edit.setPlaceholderText("请输入要合并的表名（默认：RealTime）")
        self.table_edit.setText("RealTime")
        config_grid.addWidget(self.table_edit, 2, 1)

        # 排除列名
        config_grid.addWidget(QLabel("排除的列名:"), 3, 0)
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText(
            "请输入要排除的列名，用逗号分隔（默认：ID）")
        self.exclude_edit.setText("ID")
        config_grid.addWidget(self.exclude_edit, 3, 1)

        config_group.setLayout(config_grid)
        config_layout.addWidget(config_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.merge_btn = QPushButton("开始合并")
        self.merge_btn.clicked.connect(self.start_merge)
        self.merge_btn.setStyleSheet(
            "QPushButton{background-color: #4CAF50; color: white; font-weight: bold;}")

        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.clear_log)

        self.save_config_btn = QPushButton("保存配置")
        self.save_config_btn.clicked.connect(self.save_config)

        btn_layout.addWidget(self.merge_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addWidget(self.save_config_btn)
        btn_layout.addStretch()

        config_layout.addLayout(btn_layout)
        config_layout.addStretch()

        # 源数据库表结构选项卡
        src_structure_tab = QWidget()
        src_structure_layout = QVBoxLayout(src_structure_tab)

        # 源数据库表结构标题和刷新按钮
        src_header_layout = QHBoxLayout()
        src_header_layout.addWidget(QLabel("源数据库表结构"))
        src_header_layout.addStretch()
        self.src_refresh_btn = QPushButton("刷新表结构")
        self.src_refresh_btn.clicked.connect(
            lambda: self.refresh_structure('src'))
        src_header_layout.addWidget(self.src_refresh_btn)

        src_structure_layout.addLayout(src_header_layout)

        # 源数据库表结构表格
        self.src_table_widget = QTableWidget()
        self.src_table_widget.setColumnCount(6)
        self.src_table_widget.setHorizontalHeaderLabels(
            ['CID', '列名', '数据类型', '非空', '默认值', '主键'])
        self.src_table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        src_structure_layout.addWidget(self.src_table_widget)

        # 目标数据库表结构选项卡
        dst_structure_tab = QWidget()
        dst_structure_layout = QVBoxLayout(dst_structure_tab)

        # 目标数据库表结构标题和刷新按钮
        dst_header_layout = QHBoxLayout()
        dst_header_layout.addWidget(QLabel("目标数据库表结构"))
        dst_header_layout.addStretch()
        self.dst_refresh_btn = QPushButton("刷新表结构")
        self.dst_refresh_btn.clicked.connect(
            lambda: self.refresh_structure('dst'))
        dst_header_layout.addWidget(self.dst_refresh_btn)

        dst_structure_layout.addLayout(dst_header_layout)

        # 目标数据库表结构表格
        self.dst_table_widget = QTableWidget()
        self.dst_table_widget.setColumnCount(6)
        self.dst_table_widget.setHorizontalHeaderLabels(
            ['CID', '列名', '数据类型', '非空', '默认值', '主键'])
        self.dst_table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        dst_structure_layout.addWidget(self.dst_table_widget)

        # 添加选项卡
        tab_widget.addTab(config_tab, "配置和操作")
        tab_widget.addTab(src_structure_tab, "源数据库表结构")
        tab_widget.addTab(dst_structure_tab, "目标数据库表结构")

        # 日志显示区域
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # 状态栏
        self.statusBar().showMessage("就绪")

    def browse_src_db(self):
        """浏览源数据库文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择源数据库文件", "",
            "SQLite数据库文件 (*.db *.sqlite *.sqlite3)")
        if file_path:
            self.src_db_edit.setText(file_path)

    def browse_dst_db(self):
        """浏览目标数据库文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择目标数据库文件", "",
            "SQLite数据库文件 (*.db *.sqlite *.sqlite3)")
        if file_path:
            self.dst_db_edit.setText(file_path)

    def test_connection(self, db_type):
        """测试数据库连接"""
        if db_type == 'src':
            db_path = self.src_db_edit.text().strip()
            table_widget = self.src_table_widget
            test_btn = self.src_test_btn
        else:
            db_path = self.dst_db_edit.text().strip()
            table_widget = self.dst_table_widget
            test_btn = self.dst_test_btn

        table_name = self.table_edit.text().strip()

        if not db_path:
            QMessageBox.warning(self, "输入错误", f"请选择{db_type}数据库路径")
            return

        if not table_name:
            QMessageBox.warning(self, "输入错误", "请输入要测试的表名")
            return

        # 清空表结构显示
        table_widget.setRowCount(0)

        # 创建并启动测试线程
        self.tester = DatabaseTester(db_path, table_name)
        self.tester.log_signal.connect(self.append_log)
        self.tester.table_info_signal.connect(
            lambda table_info: self.display_table_info(table_info,
                                                       table_widget))
        self.tester.test_result_signal.connect(
            lambda success, msg: self.test_finished(success, msg, db_type,
                                                    test_btn))
        self.tester.start()

        # 更新按钮状态
        test_btn.setEnabled(False)
        test_btn.setText("测试中...")

    def refresh_structure(self, db_type):
        """刷新表结构"""
        if db_type == 'src':
            db_path = self.src_db_edit.text().strip()
            refresh_btn = self.src_refresh_btn
        else:
            db_path = self.dst_db_edit.text().strip()
            refresh_btn = self.dst_refresh_btn

        table_name = self.table_edit.text().strip()

        if not db_path:
            QMessageBox.warning(self, "输入错误", f"请选择{db_type}数据库路径")
            return

        if not table_name:
            QMessageBox.warning(self, "输入错误", "请输入要查看的表名")
            return

        # 创建并启动测试线程
        self.tester = DatabaseTester(db_path, table_name)
        self.tester.log_signal.connect(self.append_log)

        if db_type == 'src':
            self.tester.table_info_signal.connect(
                lambda table_info: self.display_table_info(table_info,
                                                           self.src_table_widget))
        else:
            self.tester.table_info_signal.connect(
                lambda table_info: self.display_table_info(table_info,
                                                           self.dst_table_widget))

        self.tester.test_result_signal.connect(
            lambda success, msg: self.refresh_finished(success, msg,
                                                       refresh_btn))
        self.tester.start()

        # 更新按钮状态
        refresh_btn.setEnabled(False)
        refresh_btn.setText("刷新中...")

    def display_table_info(self, table_info, table_widget):
        """显示表结构信息"""
        table_widget.setRowCount(len(table_info))

        for row, col_info in enumerate(table_info):
            table_widget.setItem(row, 0, QTableWidgetItem(str(col_info['cid'])))
            table_widget.setItem(row, 1, QTableWidgetItem(col_info['name']))
            table_widget.setItem(row, 2, QTableWidgetItem(col_info['type']))
            table_widget.setItem(row, 3,
                                 QTableWidgetItem(str(col_info['notnull'])))
            table_widget.setItem(row, 4,
                                 QTableWidgetItem(str(col_info['dflt_value'])))
            table_widget.setItem(row, 5, QTableWidgetItem(str(col_info['pk'])))

            # 主键列高亮显示
            if col_info['pk'] == 1:
                for col in range(6):
                    table_widget.item(row, col).setBackground(
                        QColor(255, 255, 200))

    def test_finished(self, success, message, db_type, test_btn):
        """测试完成回调"""
        # 恢复按钮状态
        test_btn.setEnabled(True)
        test_btn.setText("测试连接")

        if success:
            self.statusBar().showMessage(f"{db_type.upper()}数据库测试成功")
            QMessageBox.information(self, "测试成功", message)
        else:
            self.statusBar().showMessage(f"{db_type.upper()}数据库测试失败")
            QMessageBox.critical(self, "测试失败", message)

    def refresh_finished(self, success, message, refresh_btn):
        """刷新完成回调"""
        # 恢复按钮状态
        refresh_btn.setEnabled(True)
        refresh_btn.setText("刷新表结构")

        if success:
            self.statusBar().showMessage("表结构刷新成功")
        else:
            self.statusBar().showMessage("表结构刷新失败")
            QMessageBox.critical(self, "刷新失败", message)

    def validate_inputs(self):
        """验证输入参数"""
        if not self.src_db_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "请选择源数据库路径")
            return False

        if not self.dst_db_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "请选择目标数据库路径")
            return False

        if not self.table_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "请输入要合并的表名")
            return False

        src_path = self.src_db_edit.text().strip()
        dst_path = self.dst_db_edit.text().strip()

        if not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在",
                                f"源数据库文件不存在:\n{src_path}")
            return False

        if not os.path.exists(dst_path):
            QMessageBox.warning(self, "文件不存在",
                                f"目标数据库文件不存在:\n{dst_path}")
            return False

        return True

    def start_merge(self):
        """开始合并操作"""
        if not self.validate_inputs():
            return

        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示",
                                    "合并操作正在进行中，请等待完成")
            return

        # 获取参数
        src_db = self.src_db_edit.text().strip()
        dst_db = self.dst_db_edit.text().strip()
        table_name = self.table_edit.text().strip()
        exclude_columns = [col.strip() for col in
                           self.exclude_edit.text().split(",") if col.strip()]

        self.append_log("=" * 50)
        self.append_log("开始数据库合并操作")
        self.append_log(f"源数据库: {src_db}")
        self.append_log(f"目标数据库: {dst_db}")
        self.append_log(f"合并表名: {table_name}")
        self.append_log(f"排除列: {exclude_columns}")
        self.append_log("=" * 50)

        # 禁用合并按钮
        self.merge_btn.setEnabled(False)
        self.merge_btn.setText("合并中...")
        self.statusBar().showMessage("数据库合并操作进行中...")

        # 创建并启动工作线程
        self.worker = MergeWorker(src_db, dst_db, table_name, exclude_columns)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.merge_finished)
        self.worker.start()

    def append_log(self, message):
        """添加日志信息到UI和logger模块"""
        self.log_text.append(message)
        # 自动滚动到底部
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

        # 同时记录到logger模块
        logger.info(message)

    def merge_finished(self, success, message):
        """合并完成回调"""
        self.merge_btn.setEnabled(True)
        self.merge_btn.setText("开始合并")

        if success:
            self.statusBar().showMessage("数据库合并完成")
            QMessageBox.information(self, "完成", message)
        else:
            self.statusBar().showMessage("数据库合并失败")
            QMessageBox.critical(self, "错误", message)

    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.statusBar().showMessage("日志已清空")

    def load_config(self):
        """加载配置文件"""
        try:
            config_path = get_path()
            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path, encoding="utf-8")

                if config.has_section('merge_db'):
                    if config.has_option('merge_db', 'src_db'):
                        self.src_db_edit.setText(
                            config.get('merge_db', 'src_db'))
                    if config.has_option('merge_db', 'dst_db'):
                        self.dst_db_edit.setText(
                            config.get('merge_db', 'dst_db'))

                self.append_log(f"配置文件加载成功: {config_path}")
        except Exception as e:
            self.append_log(f"加载配置文件失败: {str(e)}")

    def save_config(self):
        """保存配置到文件"""
        try:
            config_path = get_path()
            config = configparser.ConfigParser()

            config['merge_db'] = {
                'src_db': self.src_db_edit.text().strip(),
                'dst_db': self.dst_db_edit.text().strip()
            }

            with open(config_path, 'w', encoding='utf-8') as f:
                config.write(f)

            self.append_log(f"配置已保存到: {config_path}")
            QMessageBox.information(self, "成功", "配置保存成功！")

        except Exception as e:
            error_msg = f"保存配置失败: {str(e)}"
            self.append_log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("SQLite数据库合并工具")
    app.setApplicationVersion("1.0")

    # 创建并显示主窗口
    window = DatabaseMergerUI()
    window.show()

    # 启动事件循环
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()