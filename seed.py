"""首次启动时写入示例数据，便于直接体验；已有数据则跳过。"""
import json

EQUIPMENT = [
    ("80ED 折射望远镜", "望远镜", "80mm f/7.5，目视与导星"),
    ("信达 150/750 反射镜", "望远镜", "小黑，行星与目视主力"),
    ("10x50 双筒", "双筒", "巡天、亮彗星、疏散星团"),
    ("ASI533MC 相机", "相机", "深空冷冻相机"),
    ("EQ3 赤道仪", "赤道仪", "跟踪摄影用"),
]

# name, type, constellation, best_alt, min_alt, vis_start, vis_end, moon_sens, [设备名], 描述
TARGETS = [
    ("木星", "planet", "—", 45, 15, "22:00", "04:00", "none",
     ["80ED 折射望远镜", "信达 150/750 反射镜"], "云带、大红斑与伽利略卫星"),
    ("土星", "planet", "—", 38, 15, "19:30", "01:00", "none",
     ["信达 150/750 反射镜"], "光环倾角逐年变化"),
    ("M31 仙女座星系", "dso", "仙女座", 65, 20, "20:00", "04:30", "high",
     ["80ED 折射望远镜", "ASI533MC 相机", "EQ3 赤道仪"], "月光影响大，选无月夜"),
    ("M42 猎户座大星云", "dso", "猎户座", 40, 20, "03:00", "05:30", "medium",
     ["信达 150/750 反射镜", "80ED 折射望远镜"], "秋季后半夜升起"),
    ("M13 武仙座球状星团", "dso", "武仙座", 55, 20, "19:00", "01:00", "medium",
     ["信达 150/750 反射镜"], "北天最亮球状星团"),
    ("Albireo 辇道增七", "double", "天鹅座", 50, 15, "19:00", "23:30", "low",
     ["80ED 折射望远镜"], "金蓝双色双星，低倍即可"),
    ("月球", "lunar", "—", 50, 10, "19:00", "23:59", "none",
     ["80ED 折射望远镜", "10x50 双筒"], "注意选择晨昏线附近区域"),
]

# (title, date, location, slot, moon_illum, moon_up, transparency, seeing, cloud, notes, status)
SESSIONS = [
    ("夏末深空之夜", "2026-08-20", "郊外水库观景台", "20:00", "02:00", 35, "23:00", "02:00",
     4, 3, 10, "前半夜有薄云，后半夜转好", "completed"),
    ("行星观测夜", "2026-09-06", "学校操场", "19:30", "01:00", 60, "19:30", "23:00",
     3, 4, 20, "视宁度不错", "completed"),
    ("周末例行观测", "2026-09-14", "郊外水库观景台", "19:30", "02:00", 12, "", "",
     4, 3, 10, "接近新月，适合深空", "planning"),
]

# (session_date, target_name, planned_start, planned_end, position, [设备名])
PLAN_ITEMS = [
    ("2026-08-20", "M13 武仙座球状星团", "20:30", "21:10", 1, ["信达 150/750 反射镜"]),
    ("2026-08-20", "M31 仙女座星系", "21:30", "23:00", 2, ["80ED 折射望远镜", "ASI533MC 相机", "EQ3 赤道仪"]),
    ("2026-09-06", "木星", "21:00", "22:00", 1, ["信达 150/750 反射镜"]),
    ("2026-09-06", "M31 仙女座星系", "23:00", "00:30", 2, ["80ED 折射望远镜", "ASI533MC 相机", "EQ3 赤道仪"]),
    ("2026-09-14", "木星", "", "", 0, ["信达 150/750 反射镜"]),
    ("2026-09-14", "M31 仙女座星系", "", "", 0, ["80ED 折射望远镜", "ASI533MC 相机", "EQ3 赤道仪"]),
    ("2026-09-14", "M42 猎户座大星云", "", "", 0, ["信达 150/750 反射镜"]),
    ("2026-09-14", "Albireo 辇道增七", "", "", 0, ["80ED 折射望远镜"]),
]

# (session_date, target_name, start, end, mag, transp, seeing, filters, exposure, impressions)
RECORDS = [
    ("2026-08-20", "M13 武仙座球状星团", "20:35", "21:08", 5.0, 4, 3, "无",
     {}, "150 倍下边缘可分解出单颗恒星，核心呈颗粒感，非常震撼。"),
    ("2026-08-20", "M31 仙女座星系", "21:40", "23:05", 5.2, 4, 3, "UHC",
     {"iso": 1600, "shutter": "60s", "frames": 30, "gain": 100},
     "核心明亮，旋臂隐约可见，M110 勉强可辨。后半夜薄云散去后细节明显增多。"),
    ("2026-09-06", "木星", "21:05", "21:50", 5.0, 3, 4, "无",
     {}, "大红斑位于盘面中央，两条云带清晰，四颗伽利略卫星排成一线。"),
    ("2026-09-06", "M31 仙女座星系", "23:40", "00:30", 4.8, 3, 3, "无",
     {"iso": 800, "shutter": "120s", "frames": 12, "gain": 100},
     "透明度一般，核球明显但暗带难辨，月光升起后背景偏亮。"),
]


def run(conn):
    if conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] > 0:
        return
    cur = conn.cursor()
    eq_id = {}
    for name, kind, notes in EQUIPMENT:
        cur.execute("INSERT INTO equipment (name, kind, notes) VALUES (?,?,?)", (name, kind, notes))
        eq_id[name] = cur.lastrowid

    tgt_id = {}
    for name, typ, cons, alt, malt, vs, ve, sens, eqs, desc in TARGETS:
        cur.execute(
            "INSERT INTO targets (name,type,constellation,best_altitude,min_altitude,"
            "visible_start,visible_end,moon_sensitivity,equipment_needed,description)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, typ, cons, alt, malt, vs, ve, sens,
             json.dumps([eq_id[e] for e in eqs]), desc))
        tgt_id[name] = cur.lastrowid

    sess_id = {}
    for title, date, loc, ss, se, illum, ms, me, tr, see, cloud, notes, status in SESSIONS:
        cur.execute(
            "INSERT INTO sessions (title,date,location,slot_start,slot_end,moon_illumination,"
            "moon_up_start,moon_up_end,transparency,seeing,cloud_cover,weather_notes,status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (title, date, loc, ss, se, illum, ms, me, tr, see, cloud, notes, status))
        sess_id[date] = cur.lastrowid

    item_id = {}
    for date, tname, ps, pe, pos, eqs in PLAN_ITEMS:
        cur.execute(
            "INSERT INTO plan_items (session_id,target_id,planned_start,planned_end,position,equipment_ids)"
            " VALUES (?,?,?,?,?,?)",
            (sess_id[date], tgt_id[tname], ps, pe, pos, json.dumps([eq_id[e] for e in eqs])))
        item_id[(date, tname)] = cur.lastrowid

    for date, tname, s, e, mag, tr, see, filt, expo, impr in RECORDS:
        cur.execute(
            "INSERT INTO records (session_id,target_id,plan_item_id,actual_start,actual_end,"
            "limiting_magnitude,transparency,seeing,filters,exposure,impressions)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sess_id[date], tgt_id[tname], item_id.get((date, tname)), s, e, mag, tr, see,
             filt, json.dumps(expo, ensure_ascii=False), impr))

    conn.commit()
