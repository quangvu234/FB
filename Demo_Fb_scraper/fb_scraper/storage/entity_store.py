"""Thông tin cá nhân/Trang/nhóm được lưu tại sources, không có bảng entities riêng."""
from fb_scraper.storage.source_store import save_entity

ENTITY_TABLES = {"profile": "sources", "group": "sources"}


def entity_table(kind):
    if kind not in ENTITY_TABLES:
        raise ValueError("Loại đối tượng phải là profile hoặc group.")
    return "sources"
