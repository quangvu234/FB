"""Nguồn cá nhân/Trang/nhóm; thông tin giới thiệu và lịch sử tìm kiếm nằm trong metadata."""
import json
from urllib.parse import urlparse

from fb_scraper.common.models import ENTITY_MODELS, SearchResult
from fb_scraper.common.urls import canonical_entity_url
from fb_scraper.storage.schema import as_dict, json_text, now


def get_source(db, source_id):
    cursor = db.execute("SELECT * FROM sources WHERE id=?", (source_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    record = as_dict(cursor, row)
    record["metadata"] = json.loads(record["metadata"] or "{}")
    return record


def write_source(db, kind, label, reference, metadata=None):
    if kind not in {"profile", "page", "group"}:
        raise ValueError("source_type phải là profile, page hoặc group.")
    row = db.execute("SELECT id FROM sources WHERE source_ref=?", (reference,)).fetchone() if reference else None
    if row:
        previous = get_source(db, row[0])
        combined = {**previous["metadata"], **(metadata or {})}
        # Trang đã được nhận diện không bị hạ về profile khi đọc một thẻ tìm kiếm.
        if previous["source_type"] == "page" and kind == "profile":
            kind = "page"
        db.execute("UPDATE sources SET source_type=?, source_label=?, last_checked_at=?, metadata=? WHERE id=?",
                   (kind, label or previous["source_label"], now(), json_text(combined), row[0]))
        return row[0]
    cursor = db.execute("INSERT INTO sources(source_type,source_label,source_ref,created_at,last_checked_at,metadata) VALUES(?,?,?,?,?,?)",
                        (kind, label or "Chưa rõ nguồn", reference, now(), now(), json_text(metadata or {})))
    return cursor.lastrowid


def source_for_post(db, record):
    if record.get("source_id") is not None:
        source = get_source(db, record["source_id"])
        if source is None:
            raise ValueError("source_id không tồn tại.")
        db.execute("UPDATE sources SET last_checked_at=? WHERE id=?", (now(), source["id"]))
        return source["id"]
    kind = record.get("source_type") or record.get("entity_type") or "profile"
    url = record.get("source_ref") or record.get("url") or ""
    if "/groups/" in urlparse(url).path:
        kind = "group"
        path = urlparse(url).path.split("/")
        url = "https://www.facebook.com/groups/" + path[2]
    reference = canonical_entity_url(url, "group" if kind == "group" else "profile")
    if not reference:
        reference = canonical_entity_url(record.get("author_url", ""), "profile")
    if not reference and record.get("entity_id"):
        cursor = db.execute("SELECT id, metadata FROM sources")
        for identity, metadata in cursor:
            entity = json.loads(metadata or "{}").get("entity", {})
            if entity.get("entity_id") == record["entity_id"]:
                return identity
    if not reference:
        path = urlparse(record.get("url", "")).path
        owner = path.split("/posts/", 1)[0]
        reference = canonical_entity_url("https://www.facebook.com" + owner, "profile") if "/posts/" in path else ""
    metadata = {"entity_id": record.get("entity_id")}
    if not reference:
        reference = "unresolved:" + record["post_id"]
        metadata["classification_pending"] = True
    return write_source(db, kind, record.get("source_label") or record.get("author"), reference, metadata)


def write_entity(db, kind, entity):
    record = ENTITY_MODELS[kind].model_validate(entity).model_dump()
    source_type = "page" if record.get("account_type") == "page" else kind
    existing = db.execute("SELECT id FROM sources WHERE source_ref=?", (record["url"],)).fetchone()
    if existing and record["collection_status"] != "ok":
        previous = get_source(db, existing[0])["metadata"].get("entity", {})
        record = {**previous, **{key: value for key, value in record.items() if value is not None}}
    record["collected_at"] = now()
    record["entity_type"] = kind
    return write_source(db, source_type, record.get("name"), record["url"], {"entity": record})


def save_entity(db, kind, entity):
    with db:
        return write_entity(db, kind, entity)


def write_search_result(db, result):
    record = SearchResult.model_validate(result).model_dump()
    identity = write_source(db, record["entity_type"], record["name"], record["url"])
    source = get_source(db, identity)
    metadata = source["metadata"]
    metadata.setdefault("search_history", []).append(record)
    db.execute("UPDATE sources SET metadata=? WHERE id=?", (json_text(metadata), identity))
    return identity
