-- Bốn bảng chính; các cột bổ sung giữ tên, URL và metadata đã thu thập.
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK(source_type IN ('profile', 'page', 'group')),
    source_label TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS sources_ref_unique ON sources(source_ref) WHERE source_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    post_key TEXT NOT NULL UNIQUE,
    content TEXT,
    posted_at TEXT,
    is_shared INTEGER NOT NULL DEFAULT 0 CHECK(is_shared IN (0, 1)),
    original_post_key TEXT,
    collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT,
    url TEXT,
    author TEXT,
    author_url TEXT,
    posted_raw TEXT,
    reaction_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (source_id) REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS posts_source_idx ON posts(source_id);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    parent_comment_id INTEGER,
    comment_key TEXT NOT NULL UNIQUE,
    content TEXT,
    created_at TEXT,
    reaction_count INTEGER DEFAULT 0,
    collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
    author TEXT,
    author_url TEXT,
    url TEXT,
    created_raw TEXT,
    parent_comment_key TEXT,
    root_comment_key TEXT,
    is_reply INTEGER CHECK(is_reply IN (0, 1) OR is_reply IS NULL),
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (parent_comment_id) REFERENCES comments(id)
);
CREATE INDEX IF NOT EXISTS comments_post_idx ON comments(post_id);
CREATE INDEX IF NOT EXISTS comments_parent_idx ON comments(parent_comment_id);
CREATE TRIGGER IF NOT EXISTS comments_parent_insert BEFORE INSERT ON comments
WHEN NEW.parent_comment_id IS NOT NULL BEGIN
    SELECT RAISE(ABORT, 'Comment parent must belong to the same post')
    WHERE NOT EXISTS (SELECT 1 FROM comments WHERE id=NEW.parent_comment_id AND post_id=NEW.post_id);
END;
CREATE TRIGGER IF NOT EXISTS comments_parent_update BEFORE UPDATE OF parent_comment_id, post_id ON comments
WHEN NEW.parent_comment_id IS NOT NULL BEGIN
    SELECT RAISE(ABORT, 'Comment parent must belong to the same post')
    WHERE NOT EXISTS (SELECT 1 FROM comments WHERE id=NEW.parent_comment_id AND post_id=NEW.post_id);
    SELECT RAISE(ABORT, 'Comment cycle') WHERE NEW.parent_comment_id=NEW.id OR EXISTS (
        WITH RECURSIVE ancestors(id) AS (
            SELECT NEW.parent_comment_id UNION
            SELECT c.parent_comment_id FROM comments c JOIN ancestors a ON c.id=a.id
            WHERE c.parent_comment_id IS NOT NULL
        ) SELECT 1 FROM ancestors WHERE id=NEW.id
    );
END;
CREATE TRIGGER IF NOT EXISTS comments_post_update BEFORE UPDATE OF post_id ON comments
WHEN NEW.post_id != OLD.post_id BEGIN
    SELECT RAISE(ABORT, 'Comment children must belong to the same post')
    WHERE EXISTS (SELECT 1 FROM comments WHERE parent_comment_id=OLD.id AND post_id != NEW.post_id);
END;

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    comment_id INTEGER,
    media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video', 'gif')),
    file_path TEXT,
    file_hash TEXT,
    ocr_text TEXT,
    position INTEGER DEFAULT 0,
    media_url TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (comment_id) REFERENCES comments(id),
    CHECK ((post_id IS NOT NULL AND comment_id IS NULL) OR (post_id IS NULL AND comment_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS media_post_idx ON media(post_id);
CREATE INDEX IF NOT EXISTS media_comment_idx ON media(comment_id);
CREATE UNIQUE INDEX IF NOT EXISTS media_post_url_unique ON media(post_id,media_url) WHERE post_id IS NOT NULL AND media_url IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS media_comment_url_unique ON media(comment_id,media_url) WHERE comment_id IS NOT NULL AND media_url IS NOT NULL;
