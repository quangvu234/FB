"""Schema cột và thao tác SQLite cho profile/nhóm."""
import json
from datetime import datetime, timezone

from fb_scraper.common.models import ENTITY_MODELS

ENTITY_COLUMNS = {
    "profile": ("entity_id", "profile_id", "url", "source_url", "about_url", "name", "account_type",
                "bio", "followers_count", "followers_raw", "work", "education", "current_city", "hometown",
                "collection_status", "collected_at"),
    "group": ("entity_id", "group_id", "url", "source_url", "about_url", "name", "description", "privacy",
              "members_count", "members_raw", "rules", "collection_status", "collected_at"),
}
ENTITY_JSON_FIELDS = {"profile": ("work", "education"), "group": ("rules",)}


# Thêm/cập nhật đối tượng theo entity_id; commit SQLite, chưa xuất snapshot.
def save_entity(db, kind, entity):
    """Lưu thông tin một cá nhân/nhóm; lỗi đọc trang không xóa thông tin cũ đã biết."""
    if kind not in ENTITY_COLUMNS:
        raise ValueError("Loại đối tượng phải là profile hoặc group.")

    if kind == "profile":
        table_name = "profiles"
    else:
        table_name = "groups"

    columns = ENTITY_COLUMNS[kind]
    entity_model = ENTITY_MODELS[kind]
    validated_entity = entity_model.model_validate(entity)
    record = validated_entity.model_dump()
    record["collected_at"] = datetime.now(timezone.utc).isoformat()

    if record["collection_status"] != "ok":
        query = f"SELECT * FROM {table_name} WHERE entity_id = ?"
        cursor = db.execute(query, (record["entity_id"],))
        previous_row = cursor.fetchone()

        if previous_row:
            old_record = {}
            for index in range(len(cursor.description)):
                column_name = cursor.description[index][0]
                old_record[column_name] = previous_row[index]

            for field in ENTITY_JSON_FIELDS[kind]:
                old_value = old_record.get(field)
                if old_value is not None:
                    old_record[field] = json.loads(old_value)
                else:
                    old_record[field] = None

            # Chỉ ghi đè bằng giá trị mới đã đọc được; giữ lại giá trị cũ nếu mới là None.
            for field, value in record.items():
                if value is not None:
                    old_record[field] = value
            record = old_record

    for field in ENTITY_JSON_FIELDS[kind]:
        value = record.get(field)
        if value is not None:
            record[field] = json.dumps(value, ensure_ascii=False)
        else:
            record[field] = None

    placeholders = []
    values = []
    update_assignments = []

    for column in columns:
        placeholders.append("?")
        values.append(record.get(column))

        if column != "entity_id":
            update_assignments.append(f"{column}=excluded.{column}")

    column_sql = ",".join(columns)
    placeholder_sql = ",".join(placeholders)
    update_sql = ",".join(update_assignments)
    query = (
        f"INSERT INTO {table_name}({column_sql}) VALUES({placeholder_sql}) "
        f"ON CONFLICT(entity_id) DO UPDATE SET {update_sql}"
    )

    with db:
        db.execute(query, values)
