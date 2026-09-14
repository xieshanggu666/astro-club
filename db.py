"""SQLite 数据层：建表与连接。"""
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "astro.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT DEFAULT '',
  notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  type TEXT DEFAULT 'other',            -- planet/dso/lunar/double/comet/star/other
  constellation TEXT DEFAULT '',
  best_altitude REAL,                   -- 目标高度（当晚最高/典型高度角，度）
  min_altitude REAL DEFAULT 15,         -- 可观测的最低高度角
  visible_start TEXT DEFAULT '',        -- 预计出现时间窗口 HH:MM
  visible_end TEXT DEFAULT '',
  moon_sensitivity TEXT DEFAULT 'medium', -- 月光影响 none/low/medium/high
  equipment_needed TEXT DEFAULT '[]',   -- JSON: [equipment_id, ...]
  description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT DEFAULT '',
  date TEXT NOT NULL,
  location TEXT DEFAULT '',
  slot_start TEXT DEFAULT '',           -- 当晚可用时段 HH:MM
  slot_end TEXT DEFAULT '',
  moon_illumination REAL,               -- 月相照明百分比 0-100
  moon_up_start TEXT DEFAULT '',        -- 月亮在天时段（可空）
  moon_up_end TEXT DEFAULT '',
  transparency INTEGER,                 -- 天气记录：透明度 1-5
  seeing INTEGER,                       -- 视宁度 1-5
  cloud_cover INTEGER,                  -- 云量 0-100
  weather_notes TEXT DEFAULT '',
  status TEXT DEFAULT 'planning'        -- planning/active/completed
);

CREATE TABLE IF NOT EXISTS plan_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  target_id INTEGER NOT NULL REFERENCES targets(id),
  planned_start TEXT DEFAULT '',
  planned_end TEXT DEFAULT '',
  position INTEGER DEFAULT 0,
  equipment_ids TEXT DEFAULT '[]',      -- JSON: [equipment_id, ...]
  notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  target_id INTEGER NOT NULL REFERENCES targets(id),
  plan_item_id INTEGER REFERENCES plan_items(id) ON DELETE SET NULL,
  actual_start TEXT DEFAULT '',
  actual_end TEXT DEFAULT '',
  limiting_magnitude REAL,              -- 目视条件：极限星等
  transparency INTEGER,
  seeing INTEGER,
  filters TEXT DEFAULT '',              -- 滤镜
  exposure TEXT DEFAULT '{}',           -- 曝光参数 JSON {iso, shutter, frames, gain}
  impressions TEXT DEFAULT '',          -- 文字感受
  created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  caption TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_session ON plan_items(session_id);
CREATE INDEX IF NOT EXISTS idx_records_session ON records(session_id);
CREATE INDEX IF NOT EXISTS idx_records_target ON records(target_id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
