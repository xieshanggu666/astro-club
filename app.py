#!/usr/bin/env python3
"""星野日志 —— 天文社团观测计划与记录应用。

零依赖，仅需 Python 3：
    python3 app.py [端口]      # 默认 8000
然后浏览器打开 http://localhost:8000
"""
import json
import mimetypes
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db
import logic
import seed

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE, "static")
UPLOAD_DIR = os.path.join(BASE, "uploads")
MAX_UPLOAD = 25 * 1024 * 1024  # 25 MB
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

os.makedirs(UPLOAD_DIR, exist_ok=True)


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def one(conn, sql, args):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def clean_time(v):
    v = (v or "").strip()
    if v and not TIME_RE.match(v):
        raise ApiError(400, f"时间格式应为 HH:MM：{v}")
    return v


def num_or_none(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"应为数字：{v}")


def int_or_none(v):
    n = num_or_none(v)
    return None if n is None else int(n)


def json_list(v):
    if isinstance(v, list):
        return json.dumps([int(x) for x in v])
    return "[]"


def delete_photo_files(filenames):
    """从上传目录删除照片文件。文件名取自数据库，basename 防路径穿越；
    文件已不存在时静默跳过（幂等）。"""
    removed = 0
    for fn in filenames:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(fn)))
            removed += 1
        except OSError:
            pass
    return removed


# ---------- 数据组装 ----------

def target_dict(r):
    d = dict(r)
    d["equipment_needed"] = json.loads(d.get("equipment_needed") or "[]")
    return d


def load_session_full(conn, sid):
    session = one(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    if not session:
        raise ApiError(404, "观测活动不存在")
    items = rows(conn.execute(
        """SELECT p.*, t.name AS target_name, t.type, t.constellation, t.best_altitude,
                  t.min_altitude, t.visible_start, t.visible_end, t.moon_sensitivity
           FROM plan_items p JOIN targets t ON t.id = p.target_id
           WHERE p.session_id=? ORDER BY p.position, p.id""", (sid,)))
    for it in items:
        it["equipment_ids"] = json.loads(it["equipment_ids"] or "[]")
    equipment = rows(conn.execute("SELECT * FROM equipment ORDER BY name"))
    eq_map = {e["id"]: e["name"] for e in equipment}
    analysis = logic.analyze_session(session, items, eq_map)
    records = rows(conn.execute(
        """SELECT r.*, t.name AS target_name, t.type AS target_type
           FROM records r JOIN targets t ON t.id = r.target_id
           WHERE r.session_id=? ORDER BY r.id""", (sid,)))
    for r in records:
        r["exposure"] = json.loads(r["exposure"] or "{}")
        r["photos"] = rows(conn.execute("SELECT * FROM photos WHERE record_id=?", (r["id"],)))
    records.sort(key=logic.record_sort_key)  # 夜间排序：凌晨归次日，字符串排序会错乱
    return {"session": session, "items": items, "equipment": equipment,
            "analysis": analysis, "records": records}


# ---------- HTTP 处理 ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # --- 响应辅助 ---
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type=None):
        if not os.path.isfile(path):
            return self.send_json({"error": "文件不存在"}, 404)
        ctype = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def read_json(self):
        raw = self.read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError(400, "请求体不是合法 JSON")

    # --- 方法入口 ---
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if method == "GET" and path == "/":
                return self.send_file(os.path.join(STATIC_DIR, "index.html"),
                                      "text/html; charset=utf-8")
            m = re.fullmatch(r"/static/([\w.\-]+)", path)
            if method == "GET" and m:
                return self.send_file(os.path.join(STATIC_DIR, m.group(1)))
            m = re.fullmatch(r"/uploads/([\w.\-]+)", path)
            if method == "GET" and m:
                return self.send_file(os.path.join(UPLOAD_DIR, m.group(1)))
            if path.startswith("/api/"):
                conn = db.connect()
                try:
                    return self.route_api(method, path, qs, conn)
                finally:
                    conn.close()
            self.send_json({"error": "Not found"}, 404)
        except ApiError as e:
            self.send_json({"error": e.message}, e.status)
        except Exception as e:  # 兜底，避免连接悬挂
            self.send_json({"error": f"服务器错误: {e}"}, 500)

    # --- API 路由 ---
    def route_api(self, method, path, qs, conn):
        def m(pattern):
            return re.fullmatch(pattern, path)

        # ===== 目标库 =====
        if method == "GET" and path == "/api/targets":
            return self.send_json([target_dict(r) for r in conn.execute(
                "SELECT * FROM targets ORDER BY name").fetchall()])

        if method == "POST" and path == "/api/targets":
            b = self.read_json()
            name = (b.get("name") or "").strip()
            if not name:
                raise ApiError(400, "目标名称不能为空")
            cur = conn.execute(
                "INSERT INTO targets (name,type,constellation,best_altitude,min_altitude,"
                "visible_start,visible_end,moon_sensitivity,equipment_needed,description)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, b.get("type") or "other", (b.get("constellation") or "").strip(),
                 num_or_none(b.get("best_altitude")), num_or_none(b.get("min_altitude")),
                 clean_time(b.get("visible_start")), clean_time(b.get("visible_end")),
                 b.get("moon_sensitivity") or "medium", json_list(b.get("equipment_needed")),
                 (b.get("description") or "").strip()))
            conn.commit()
            return self.send_json(target_dict(one(conn, "SELECT * FROM targets WHERE id=?",
                                                  (cur.lastrowid,))), 201)

        if (mm := m(r"/api/targets/(\d+)")) and method == "PUT":
            tid = int(mm.group(1))
            if not one(conn, "SELECT * FROM targets WHERE id=?", (tid,)):
                raise ApiError(404, "目标不存在")
            b = self.read_json()
            name = (b.get("name") or "").strip()
            if not name:
                raise ApiError(400, "目标名称不能为空")
            conn.execute(
                "UPDATE targets SET name=?,type=?,constellation=?,best_altitude=?,min_altitude=?,"
                "visible_start=?,visible_end=?,moon_sensitivity=?,equipment_needed=?,description=?"
                " WHERE id=?",
                (name, b.get("type") or "other", (b.get("constellation") or "").strip(),
                 num_or_none(b.get("best_altitude")), num_or_none(b.get("min_altitude")),
                 clean_time(b.get("visible_start")), clean_time(b.get("visible_end")),
                 b.get("moon_sensitivity") or "medium", json_list(b.get("equipment_needed")),
                 (b.get("description") or "").strip(), tid))
            conn.commit()
            return self.send_json(target_dict(one(conn, "SELECT * FROM targets WHERE id=?", (tid,))))

        if (mm := m(r"/api/targets/(\d+)")) and method == "DELETE":
            tid = int(mm.group(1))
            if conn.execute("SELECT COUNT(*) FROM records WHERE target_id=?", (tid,)).fetchone()[0]:
                raise ApiError(400, "该目标已有观测记录，不能删除")
            conn.execute("DELETE FROM plan_items WHERE target_id=?", (tid,))
            conn.execute("DELETE FROM targets WHERE id=?", (tid,))
            conn.commit()
            return self.send_json({"ok": True})

        # ===== 设备 =====
        if method == "GET" and path == "/api/equipment":
            return self.send_json(rows(conn.execute("SELECT * FROM equipment ORDER BY name")))

        if method == "POST" and path == "/api/equipment":
            b = self.read_json()
            name = (b.get("name") or "").strip()
            if not name:
                raise ApiError(400, "设备名称不能为空")
            cur = conn.execute("INSERT INTO equipment (name,kind,notes) VALUES (?,?,?)",
                               (name, (b.get("kind") or "").strip(), (b.get("notes") or "").strip()))
            conn.commit()
            return self.send_json(one(conn, "SELECT * FROM equipment WHERE id=?",
                                      (cur.lastrowid,)), 201)

        if (mm := m(r"/api/equipment/(\d+)")) and method == "DELETE":
            conn.execute("DELETE FROM equipment WHERE id=?", (int(mm.group(1)),))
            conn.commit()
            return self.send_json({"ok": True})

        # ===== 观测活动 =====
        if method == "GET" and path == "/api/sessions":
            out = rows(conn.execute(
                """SELECT s.*, (SELECT COUNT(*) FROM plan_items p WHERE p.session_id=s.id) AS item_count,
                          (SELECT COUNT(*) FROM records r WHERE r.session_id=s.id) AS record_count
                   FROM sessions s ORDER BY s.date DESC, s.id DESC"""))
            return self.send_json(out)

        if method == "POST" and path == "/api/sessions":
            b = self.read_json()
            if not (b.get("date") or "").strip():
                raise ApiError(400, "日期不能为空")
            cur = conn.execute(
                "INSERT INTO sessions (title,date,location,slot_start,slot_end,moon_illumination,"
                "moon_up_start,moon_up_end,transparency,seeing,cloud_cover,weather_notes,status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ((b.get("title") or "").strip(), b["date"].strip(), (b.get("location") or "").strip(),
                 clean_time(b.get("slot_start")), clean_time(b.get("slot_end")),
                 num_or_none(b.get("moon_illumination")),
                 clean_time(b.get("moon_up_start")), clean_time(b.get("moon_up_end")),
                 int_or_none(b.get("transparency")), int_or_none(b.get("seeing")),
                 int_or_none(b.get("cloud_cover")), (b.get("weather_notes") or "").strip(),
                 b.get("status") or "planning"))
            conn.commit()
            return self.send_json(one(conn, "SELECT * FROM sessions WHERE id=?",
                                      (cur.lastrowid,)), 201)

        if (mm := m(r"/api/sessions/(\d+)")) and method == "PUT":
            sid = int(mm.group(1))
            if not one(conn, "SELECT * FROM sessions WHERE id=?", (sid,)):
                raise ApiError(404, "观测活动不存在")
            b = self.read_json()
            conn.execute(
                "UPDATE sessions SET title=?,date=?,location=?,slot_start=?,slot_end=?,"
                "moon_illumination=?,moon_up_start=?,moon_up_end=?,transparency=?,seeing=?,"
                "cloud_cover=?,weather_notes=?,status=? WHERE id=?",
                ((b.get("title") or "").strip(), (b.get("date") or "").strip(),
                 (b.get("location") or "").strip(),
                 clean_time(b.get("slot_start")), clean_time(b.get("slot_end")),
                 num_or_none(b.get("moon_illumination")),
                 clean_time(b.get("moon_up_start")), clean_time(b.get("moon_up_end")),
                 int_or_none(b.get("transparency")), int_or_none(b.get("seeing")),
                 int_or_none(b.get("cloud_cover")), (b.get("weather_notes") or "").strip(),
                 b.get("status") or "planning", sid))
            conn.commit()
            return self.send_json(one(conn, "SELECT * FROM sessions WHERE id=?", (sid,)))

        if (mm := m(r"/api/sessions/(\d+)")) and method == "DELETE":
            sid = int(mm.group(1))
            # 先收集该活动所有记录的照片文件名，删库提交后再删文件
            files = [r[0] for r in conn.execute(
                "SELECT p.filename FROM photos p JOIN records r ON r.id=p.record_id"
                " WHERE r.session_id=?", (sid,)).fetchall()]
            conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            conn.commit()
            delete_photo_files(files)
            return self.send_json({"ok": True, "photos_removed": len(files)})

        if (mm := m(r"/api/sessions/(\d+)/full")) and method == "GET":
            return self.send_json(load_session_full(conn, int(mm.group(1))))

        # ===== 计划条目 =====
        if (mm := m(r"/api/sessions/(\d+)/items")) and method == "POST":
            sid = int(mm.group(1))
            if not one(conn, "SELECT * FROM sessions WHERE id=?", (sid,)):
                raise ApiError(404, "观测活动不存在")
            b = self.read_json()
            tid = int(b.get("target_id") or 0)
            if not one(conn, "SELECT * FROM targets WHERE id=?", (tid,)):
                raise ApiError(400, "请选择有效的目标")
            cur = conn.execute(
                "INSERT INTO plan_items (session_id,target_id,planned_start,planned_end,position,equipment_ids,notes)"
                " VALUES (?,?,?,?,?,?,?)",
                (sid, tid, clean_time(b.get("planned_start")), clean_time(b.get("planned_end")),
                 int_or_none(b.get("position")) or 0, json_list(b.get("equipment_ids")),
                 (b.get("notes") or "").strip()))
            conn.commit()
            return self.send_json({"id": cur.lastrowid}, 201)

        if (mm := m(r"/api/items/(\d+)")) and method == "PUT":
            iid = int(mm.group(1))
            if not one(conn, "SELECT * FROM plan_items WHERE id=?", (iid,)):
                raise ApiError(404, "计划条目不存在")
            b = self.read_json()
            conn.execute(
                "UPDATE plan_items SET planned_start=?,planned_end=?,position=?,equipment_ids=?,notes=?"
                " WHERE id=?",
                (clean_time(b.get("planned_start")), clean_time(b.get("planned_end")),
                 int_or_none(b.get("position")) or 0, json_list(b.get("equipment_ids")),
                 (b.get("notes") or "").strip(), iid))
            conn.commit()
            return self.send_json({"ok": True})

        if (mm := m(r"/api/items/(\d+)")) and method == "DELETE":
            conn.execute("DELETE FROM plan_items WHERE id=?", (int(mm.group(1)),))
            conn.commit()
            return self.send_json({"ok": True})

        # ===== 自动排序 =====
        if (mm := m(r"/api/sessions/(\d+)/auto-schedule")) and method == "POST":
            sid = int(mm.group(1))
            full = load_session_full(conn, sid)
            if not full["items"]:
                raise ApiError(400, "请先添加计划目标")
            try:
                updates = logic.auto_schedule(full["session"], full["items"])
            except ValueError as e:
                raise ApiError(400, str(e))
            for u in updates:
                conn.execute(
                    "UPDATE plan_items SET planned_start=?,planned_end=?,position=? WHERE id=?",
                    (u["planned_start"], u["planned_end"], u["position"], u["id"]))
            conn.commit()
            return self.send_json(load_session_full(conn, sid))

        # ===== 观测记录 =====
        if method == "GET" and path == "/api/records":
            where, args = [], []
            if qs.get("session_id"):
                where.append("r.session_id=?")
                args.append(int(qs["session_id"][0]))
            if qs.get("target_id"):
                where.append("r.target_id=?")
                args.append(int(qs["target_id"][0]))
            sql = ("SELECT r.*, t.name AS target_name, s.date AS session_date, s.title AS session_title"
                   " FROM records r JOIN targets t ON t.id=r.target_id JOIN sessions s ON s.id=r.session_id")
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY s.date DESC, r.id"
            out = rows(conn.execute(sql, args))
            for r in out:
                r["exposure"] = json.loads(r["exposure"] or "{}")
                r["photos"] = rows(conn.execute("SELECT * FROM photos WHERE record_id=?", (r["id"],)))
            # 夜间排序：先按夜间时间（凌晨归次日），再按日期倒序（稳定排序保持组内顺序）
            out.sort(key=logic.record_sort_key)
            out.sort(key=lambda r: r["session_date"], reverse=True)
            return self.send_json(out)

        if method == "POST" and path == "/api/records":
            b = self.read_json()
            sid, tid = int(b.get("session_id") or 0), int(b.get("target_id") or 0)
            if not one(conn, "SELECT * FROM sessions WHERE id=?", (sid,)):
                raise ApiError(400, "观测活动不存在")
            if not one(conn, "SELECT * FROM targets WHERE id=?", (tid,)):
                raise ApiError(400, "目标不存在")
            cur = conn.execute(
                "INSERT INTO records (session_id,target_id,plan_item_id,actual_start,actual_end,"
                "limiting_magnitude,transparency,seeing,filters,exposure,impressions)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, tid, b.get("plan_item_id"),
                 clean_time(b.get("actual_start")), clean_time(b.get("actual_end")),
                 num_or_none(b.get("limiting_magnitude")),
                 int_or_none(b.get("transparency")), int_or_none(b.get("seeing")),
                 (b.get("filters") or "").strip(),
                 json.dumps(b.get("exposure") or {}, ensure_ascii=False),
                 (b.get("impressions") or "").strip()))
            conn.commit()
            return self.send_json({"id": cur.lastrowid}, 201)

        if (mm := m(r"/api/records/(\d+)")) and method == "DELETE":
            rid = int(mm.group(1))
            files = [r[0] for r in conn.execute(
                "SELECT filename FROM photos WHERE record_id=?", (rid,)).fetchall()]
            conn.execute("DELETE FROM records WHERE id=?", (rid,))
            conn.commit()
            delete_photo_files(files)
            return self.send_json({"ok": True, "photos_removed": len(files)})

        # 照片：原始字节上传，文件名走查询参数，避免 multipart 解析
        if (mm := m(r"/api/records/(\d+)/photos")) and method == "POST":
            rid = int(mm.group(1))
            if not one(conn, "SELECT * FROM records WHERE id=?", (rid,)):
                raise ApiError(404, "记录不存在")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                raise ApiError(400, "未收到文件内容")
            if n > MAX_UPLOAD:
                raise ApiError(400, "文件超过 25MB 限制")
            name = os.path.basename((qs.get("name") or ["photo"])[0]) or "photo"
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".jpg"
            fname = f"{rid}_{int(time.time() * 1000)}{ext}"
            data = self.read_body()
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(data)
            cur = conn.execute("INSERT INTO photos (record_id,filename,caption) VALUES (?,?,?)",
                               (rid, fname, (qs.get("caption") or [""])[0]))
            conn.commit()
            return self.send_json(one(conn, "SELECT * FROM photos WHERE id=?",
                                      (cur.lastrowid,)), 201)

        if (mm := m(r"/api/photos/(\d+)")) and method == "DELETE":
            pid = int(mm.group(1))
            ph = one(conn, "SELECT * FROM photos WHERE id=?", (pid,))
            if ph:
                conn.execute("DELETE FROM photos WHERE id=?", (pid,))
                conn.commit()
                delete_photo_files([ph["filename"]])
            return self.send_json({"ok": True})

        # ===== 观测日志 =====
        if method == "GET" and path == "/api/logbook":
            return self.send_json(rows(conn.execute(
                """SELECT t.id AS target_id, t.name, t.type, t.constellation,
                          COUNT(r.id) AS record_count, MAX(s.date) AS last_date
                   FROM records r JOIN targets t ON t.id=r.target_id JOIN sessions s ON s.id=r.session_id
                   GROUP BY t.id ORDER BY last_date DESC""")))

        if (mm := m(r"/api/targets/(\d+)/log")) and method == "GET":
            tid = int(mm.group(1))
            target = one(conn, "SELECT * FROM targets WHERE id=?", (tid,))
            if not target:
                raise ApiError(404, "目标不存在")
            recs = rows(conn.execute(
                """SELECT r.*, s.date AS session_date, s.title AS session_title, s.location
                   FROM records r JOIN sessions s ON s.id=r.session_id
                   WHERE r.target_id=? ORDER BY s.date, r.id""", (tid,)))
            for r in recs:
                r["exposure"] = json.loads(r["exposure"] or "{}")
                r["photos"] = rows(conn.execute("SELECT * FROM photos WHERE record_id=?", (r["id"],)))
            recs.sort(key=logic.record_sort_key)
            recs.sort(key=lambda r: r["session_date"])
            target["equipment_needed"] = json.loads(target["equipment_needed"] or "[]")
            return self.send_json({"target": target, "records": recs})

        raise ApiError(404, "接口不存在")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    db.init()
    conn = db.connect()
    seed.run(conn)
    conn.close()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"星野日志已启动：http://localhost:{port}  （Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
