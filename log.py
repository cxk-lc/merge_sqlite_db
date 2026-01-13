import logging
import os
import sys
import uuid
import threading
from logging import FileHandler, StreamHandler
from datetime import datetime
from typing import Optional, TextIO
from tool import get_path

# 创建线程局部存储来存储每个请求的ID
_request_context = threading.local()

logger = logging.getLogger(os.path.basename(__file__).split('.')[0])


class RequestIDFilter(logging.Filter):
    """日志过滤器，添加request id到日志记录"""

    def filter(self, record: logging.LogRecord) -> bool:
        """添加request_id属性到日志记录"""
        request_id = getattr(_request_context, 'request_id', None)
        if not request_id:
            # 如果不在请求上下文中，则使用线程ID作为备选
            request_id = f"THREAD-{threading.get_ident()}"
        record.request_id = request_id
        return True


class DailyFileHandler(FileHandler):
    """自动按日期创建日志文件的处理器"""

    def __init__(self, filename_pattern, encoding=None):
        # 首先生成初始文件名
        self.filename_pattern = filename_pattern
        self.current_date = datetime.now().date()
        initial_filename = self._get_filename()

        # 创建目录（如果需要）
        os.makedirs(os.path.dirname(initial_filename), exist_ok=True)

        # 调用父类初始化
        super().__init__(
            filename=initial_filename,
            mode='a',  # 追加模式
            encoding=encoding,
            delay=False
        )

    def _get_filename(self):
        """生成带日期的文件名，如：app-2023-10-20.log"""
        return self.filename_pattern.format(
            date=datetime.now().strftime("%Y-%m-%d"))

    def _check_date_change(self):
        """检查日期是否变化"""
        return datetime.now().date() != self.current_date

    def emit(self, record):
        """记录日志前检查日期变化"""
        if self._check_date_change():
            self._rotate_file()
        super().emit(record)

    def _rotate_file(self):
        """执行文件轮转"""
        # 关闭旧文件流
        self.stream.flush()
        self.stream.close()

        # 生成新文件名
        new_filename = self._get_filename()
        os.makedirs(os.path.dirname(new_filename), exist_ok=True)

        # 更新基础文件名
        self.baseFilename = new_filename
        self.current_date = datetime.now().date()

        # 打开新文件流
        self.stream = self._open()


class ColorFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    # ANSI颜色代码
    COLORS = {
        logging.DEBUG: "\033[94m",  # 蓝色
        logging.INFO: "\033[92m",  # 绿色
        logging.WARNING: "\033[93m",  # 黄色
        logging.ERROR: "\033[91m",  # 红色
        logging.CRITICAL: "\033[95m"  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，添加颜色"""
        message = super().format(record)
        color = self.COLORS.get(record.levelno, self.RESET)
        return f"{color}{message}{self.RESET}"


class ColorStreamHandler(StreamHandler):
    """支持颜色的控制台日志处理器"""

    def __init__(self, stream: Optional[TextIO] = None):
        super().__init__(stream)
        # 添加request_id到日志格式
        self.color_formatter = ColorFormatter(
            '%(asctime)s - [%(levelname)s] [%(request_id)s] - %(message)s - %(name)s - %(filename)s:%(lineno)d'
        )
        self.setFormatter(self.color_formatter)

    def emit(self, record: logging.LogRecord) -> None:
        """确保彩色输出仅用于控制台"""
        try:
            # 如果输出目标是终端，才使用颜色格式
            if self.stream.isatty():
                msg = self.color_formatter.format(record)
                stream = self.stream
                stream.write(msg + self.terminator)
                self.flush()
            else:
                super().emit(record)
        except Exception:
            self.handleError(record)


# 请求上下文管理器
class RequestContext:
    """管理请求ID的生命周期"""

    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())
        self._prev_request_id = None

    def __enter__(self):
        # 保存旧的request_id并设置新的
        self._prev_request_id = getattr(_request_context, 'request_id', None)
        _request_context.request_id = self.request_id
        return self.request_id

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 恢复旧的request_id
        if self._prev_request_id is not None:
            _request_context.request_id = self._prev_request_id
        else:
            delattr(_request_context, 'request_id')


# 配置基础日志记录
def setup_logging() -> None:
    """设置日志记录系统"""

    # 创建不同处理器的不同格式
    file_formatter = logging.Formatter(
        '%(asctime)s - [%(levelname)s] [%(request_id)s] - %(message)s - %(name)s - %(filename)s:%(lineno)d'
    )

    # 创建request_id过滤器
    request_id_filter = RequestIDFilter()

    # 创建处理器
    file_handler = DailyFileHandler(get_path('logs/flask_log_{date}.log'),
                                    encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)  # 文件日志记录更详细
    file_handler.addFilter(request_id_filter)  # 添加过滤器

    console_handler = ColorStreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)  # 控制台只显示INFO及以上
    console_handler.addFilter(request_id_filter)  # 添加过滤器

    # 配置根记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 第三方库的日志级别配置
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)


# 初始化日志系统
setup_logging()


# 辅助函数
def get_current_request_id() -> Optional[str]:
    """获取当前请求的ID"""
    return getattr(_request_context, 'request_id', None)


def generate_request_id() -> str:
    """生成新的请求ID"""
    return str(uuid.uuid4())