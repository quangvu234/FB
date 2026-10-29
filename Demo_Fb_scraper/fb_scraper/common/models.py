"""Mẫu dữ liệu chung cho collector, agent và storage.

BaseModel thuộc Pydantic: kiểm tra dữ liệu có đúng kiểu trước khi sử dụng.
Ví dụ: "str | None" cho phép chuỗi hoặc None (chưa biết giá trị);
"list[str]" là danh sách các chuỗi, còn Literal giới hạn những giá trị được phép.
"""
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

EntityKind = Literal["profile", "group"]


class Post(BaseModel):
    """Một bài viết. Mỗi thuộc tính bên dưới là một trường dữ liệu."""
    model_config = ConfigDict(populate_by_name=True)

    post_id: str | None = None
    url: str = ""
    source: str = ""
    author: str = ""
    text: str = ""
    posted_raw: str | None = None
    posted_at: str | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    # default_factory=list tạo danh sách MỚI cho mỗi bài, không dùng chung danh sách.
    # AliasChoices chấp nhận cả tên trường mới và tên cũ do agent từng sử dụng.
    images: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("images", "image_urls"),
    )
    links: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("links", "external_links"),
    )
    image_files: list[str] = Field(default_factory=list)
    ocr: list[dict] = Field(default_factory=list)
    top_comments: list[str] = Field(default_factory=list)
    entity_type: EntityKind | None = None
    entity_id: str | None = None
    collected_at: str | None = None


class PostBatch(BaseModel):
    """Kết quả của agent là một object có trường posts chứa nhiều bài."""
    posts: list[Post]


class Entity(BaseModel):
    """Các trường dùng chung cho cả cá nhân/Trang và nhóm."""
    entity_id: str
    url: str
    source_url: str
    about_url: str
    name: str | None = None
    collection_status: Literal["ok", "partial", "unavailable", "login_required"] = "ok"
    collected_at: str | None = None


class Profile(Entity):
    """Kế thừa các trường của Entity rồi bổ sung thông tin cá nhân/Trang."""
    profile_id: str | None = None
    account_type: str | None = None
    bio: str | None = None
    followers_count: int | None = None
    followers_raw: str | None = None
    work: list[str] | None = None
    education: list[str] | None = None
    current_city: str | None = None
    hometown: str | None = None


class Group(Entity):
    """Kế thừa các trường của Entity rồi bổ sung thông tin nhóm."""
    group_id: str | None = None
    description: str | None = None
    privacy: Literal["public", "private"] | None = None
    members_count: int | None = None
    members_raw: str | None = None
    rules: list[str] | None = None


# Bên gọi chọn class theo loại dữ liệu, ví dụ ENTITY_MODELS["group"] là class Group.
ENTITY_MODELS = {"profile": Profile, "group": Group}


class SearchResult(BaseModel):
    """Một lần tìm thấy URL; cùng URL có thể xuất hiện ở nhiều từ khóa."""
    keyword: str
    entity_type: EntityKind
    name: str
    url: str
    search_url: str
    found_at: str


class CollectionOptions(BaseModel):
    """Tùy chọn thu thập. ge=0 nghĩa là số phải lớn hơn hoặc bằng 0."""
    info_only: bool = False
    max_posts: int = Field(default=20, ge=0)
    comments: int = Field(default=0, ge=0)
    ocr: bool = False
    gpu: bool = False
