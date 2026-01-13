import configparser
import sqlite3
import shutil

from log import logger
from tool import get_path


def merge_databases(db1_path, db2_path):
    """
    将db2中RealTime表的数据（排除ID列）合并到db1中
    """
    try:
        # 连接到第一个数据库
        conn1 = sqlite3.connect(db1_path)
        cursor1 = conn1.cursor()

        # 连接到第二个数据库
        conn2 = sqlite3.connect(db2_path)
        cursor2 = conn2.cursor()

        # 获取RealTime表的列信息
        cursor1.execute("PRAGMA table_info(RealTime)")
        columns_info = cursor1.fetchall()

        # 提取列名（排除ID列）
        column_names = [col[1] for col in columns_info if col[1].upper() != 'ID']

        if not column_names:
            logger.info("错误：未找到除ID之外的列")
            return False

        # 构建列名字符串
        columns_str = ', '.join(column_names)

        # 构建占位符字符串
        placeholders = ', '.join(['?' for _ in column_names])

        # 从第二个数据库读取数据（排除ID列）
        cursor2.execute(f"SELECT {columns_str} FROM RealTime")
        rows = cursor2.fetchall()

        # 插入数据到第一个数据库
        insert_sql = f"INSERT INTO RealTime ({columns_str}) VALUES ({placeholders})"

        count = 0
        for row in rows:
            cursor1.execute(insert_sql, row)
            count += 1

        # 提交事务
        conn1.commit()

        logger.info(f"成功合并 {count} 条记录")

        # 显示合并后的总记录数
        cursor1.execute("SELECT COUNT(*) FROM RealTime")
        total = cursor1.fetchone()[0]
        logger.info(f"合并后总记录数: {total}")

        return True

    except Exception as e:
        logger.error(f"合并过程中发生错误: {e}")
        return False
    finally:
        if 'conn1' in locals():
            conn1.close()
        if 'conn2' in locals():
            conn2.close()


def backup_file(file_path):
    backup_file = f"{file_path}.backup"
    shutil.copy2(file_path, backup_file)
    logger.info(f"已创建备份文件: {backup_file}")


def rename_with_shutil(src_path, dst_path):
    """
    使用 shutil.move() 重命名文件，支持覆盖
    """
    try:
        # shutil.move() 会自动处理目标文件已存在的情况
        shutil.move(src_path, dst_path)
        logger.info(f"文件已重命名: {src_path} -> {dst_path}")
    except FileNotFoundError:
        logger.error(f"源文件不存在: {src_path}")
        raise FileNotFoundError
    except Exception as e:
        logger.error(f"重命名失败: {e}")
        raise e


def get_config():
    config = configparser.ConfigParser()
    config.read(get_path(), encoding="utf-8")
    return config.get('merge_db', 'src_db'), config.get('merge_db', 'dst_db')


if __name__ == "__main__":

    try:
        # 数据库文件路径
        db1, db2 = get_config()

        # 备份原始文件（可选但推荐）
        backup_file(db1)
        backup_file(db2)

        # 合并数据库
        if merge_databases(db1, db2):
            logger.info("数据库合并完成！")
        else:
            err_msg = "数据库合并失败，已保留备份文件"
            logger.error(err_msg)
            raise err_msg

        rename_with_shutil(db1, db2)
    except Exception as e:
        import traceback
        logger.error(traceback.format_exc())
