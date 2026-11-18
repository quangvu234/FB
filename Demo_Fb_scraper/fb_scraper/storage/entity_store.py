"""Schema cột và thao tác SQLite cho bảng profiles/groups."""
import json
from datetime import datetime, timezone

from fb_scraper.common.models import ENTITY_MODELS
from fb_scraper.storage.sql import row_to_dict, upsert

ENTITY_TABLES = {"profile": "profiles", "group": "groups"}
ENTITY_COLUMNS = {
    "profile": ("entity_id", "profile_id", "url", "source_url", "about_url", "name", "account_type",
                "bio", "followers_count", "followers_raw", "work", "education", "current_city", "hometown",
                "collection_status", "collected_at"),
    "group": ("entity_id", "group_id", "url", "source_url", "about_url", "name", "description", "privacy",
              "members_count", "members_raw", "rules", "collection_status", "collected_at"),
}
ENTITY_JSON_FIELDS = {"profile": ("work", "education"), "group": ("rules",)}


def entity_table(kind):
    """Đổi loại đối tượng thành tên bảng; báo lỗi nếu loại không hợp lệ."""
    if kind not in ENTITY_TABLES:
        raise ValueError("Loại đối tượng phải là profile hoặc group.")
    return ENTITY_TABLES[kind]


def _load_entity(db, table, kind, entity_id):
    """Đọc bản ghi đã lưu và đổi các cột JSON về danh sách Python."""
    cursor = db.execute(f"SELECT * FROM {table} WHERE entity_id = ?", (entity_id,))
    row = cursor.fetchone()
    if row is None:
        return None

    record = row_to_dict(cursor, row)
    for field in ENTITY_JSON_FIELDS[kind]:
        if record.get(field) is not None:
            record[field] = json.loads(record[field])
    return record


# Thêm/cập nhật đối tượng theo entity_id; commit SQLite, chưa xuất snapshot.
def save_entity(db, kind, entity):
    """Lưu thông tin một cá nhân/nhóm; lỗi đọc trang không xóa thông tin cũ đã biết."""
    table = entity_table(kind)
    validated_entity = ENTITY_MODELS[kind].model_validate(entity)
    record = validated_entity.model_dump()
    record["collected_at"] = datetime.now(timezone.utc).isoformat()

    if record["collection_status"] != "ok":
        old_record = _load_entity(db, table, kind, record["entity_id"])
        if old_record:
            # Chỉ ghi đè bằng giá trị mới đã đọc được; giữ lại giá trị cũ nếu mới là None.
            for field, value in record.items():
                if value is not None:
                    old_record[field] = value
            record = old_record

    for field in ENTITY_JSON_FIELDS[kind]:
        if record.get(field) is not None:
            record[field] = json.dumps(record[field], ensure_ascii=False)

    upsert(db, table, ENTITY_COLUMNS[kind], "entity_id", record)
