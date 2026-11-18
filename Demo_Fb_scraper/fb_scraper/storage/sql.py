"""Hàm SQLite dùng chung: đổi dòng thành dict và thêm/cập nhật theo khóa chính."""


def row_to_dict(cursor, row):
    """Ghép tên cột trong cursor.description với giá trị của một dòng."""
    record = {}
    for index, column in enumerate(cursor.description):
        record[column[0]] = row[index]
    return record


def upsert(db, table, columns, key, record):
    """INSERT một dòng; nếu trùng khóa chính thì UPDATE các cột còn lại rồi commit.

    Tên bảng/cột lấy từ hằng số của project; dữ liệu đi qua dấu ? để SQLite tự xử lý.
    """
    values = []
    for column in columns:
        values.append(record.get(column))

    updates = []
    for column in columns:
        if column != key:
            updates.append(f"{column}=excluded.{column}")

    query = (
        f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) "
        f"ON CONFLICT({key}) DO UPDATE SET {','.join(updates)}"
    )

    # with db commit khi thành công, rollback khi có lỗi; không đóng kết nối db.
    with db:
        db.execute(query, values)
