"""观测适宜性分析、冲突检测与自动排序。

时间约定：夜间时段可能跨午夜，统一把中午 12:00 之前的时间视为次日凌晨，
即 22:00 -> 1320 分钟，02:00 -> 1560 分钟，便于直接比较大小。
"""

TYPE_LABEL = {
    "planet": "行星", "dso": "深空天体", "lunar": "月球", "double": "双星",
    "comet": "彗星", "star": "恒星", "other": "其他",
}
MOON_LABEL = {"none": "无影响", "low": "轻微", "medium": "中等", "high": "敏感"}


def norm(t):
    """'HH:MM' -> 夜间分钟数；空值/非法值返回 None。"""
    if not t:
        return None
    try:
        parts = str(t).split(":")
        mins = int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None
    return mins + 1440 if mins < 720 else mins


def denorm(mins):
    mins = int(round(mins)) % 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


def overlaps(a_s, a_e, b_s, b_e):
    return None not in (a_s, a_e, b_s, b_e) and a_s < b_e and b_s < a_e


def fmt(s, e):
    return f"{s}–{e}" if s and e else "未排时间"


def record_sort_key(rec):
    """观测记录的夜间排序键：actual_start 按夜间分钟数（凌晨归次日），未填时间的排最后。"""
    n = norm(rec.get("actual_start"))
    rid = rec.get("id") or 0
    return (0, n, rid) if n is not None else (1, 0, rid)


def analyze_session(session, items, eq_map):
    """分析一次观测活动。

    session: dict；items: [dict]（plan_item 已 JOIN 目标字段，equipment_ids 已解析为列表）；
    eq_map: {equipment_id: name}。
    返回 {"items": {item_id: {...}}, "conflicts": [...], "summary": {...}}。
    """
    slot_s, slot_e = norm(session.get("slot_start")), norm(session.get("slot_end"))
    moon_s, moon_e = norm(session.get("moon_up_start")), norm(session.get("moon_up_end"))
    illum = session.get("moon_illumination")
    transparency = session.get("transparency")
    seeing = session.get("seeing")
    cloud = session.get("cloud_cover")

    reports = {}
    timed = []  # 已排时间的条目，用于冲突检测

    for it in items:
        messages = []
        level = "ok"

        def add(lv, text):
            nonlocal level
            messages.append({"level": lv, "text": text})
            rank = {"ok": 0, "warning": 1, "error": 2}
            if rank[lv] > rank[level]:
                level = lv

        s, e = norm(it.get("planned_start")), norm(it.get("planned_end"))
        if s is None or e is None:
            add("error", "尚未安排观测时段，请填写计划时间或使用「自动排序」")
        else:
            timed.append((it, s, e))

            # 1. 是否落在当晚可用时段内
            if slot_s is not None and slot_e is not None and (s < slot_s or e > slot_e):
                add("warning",
                    f"计划时段 {fmt(it.get('planned_start'), it.get('planned_end'))} "
                    f"超出当晚可用时段 {fmt(session.get('slot_start'), session.get('slot_end'))}")

            # 2. 是否在目标预计出现窗口内
            vs, ve = norm(it.get("visible_start")), norm(it.get("visible_end"))
            if vs is not None and ve is not None and (s < vs or e > ve):
                add("warning",
                    f"该时段目标尚未升起或已经落下"
                    f"（预计出现 {fmt(it.get('visible_start'), it.get('visible_end'))}）")

            # 3. 月光影响
            sens = it.get("moon_sensitivity") or "none"
            if illum is not None:
                if sens == "high" and illum >= 40:
                    add("warning",
                        f"目标对月光敏感，当晚月相照明 {illum:.0f}%，对比度会明显下降，建议改期")
                elif sens == "medium" and illum >= 70:
                    add("warning", f"月相照明 {illum:.0f}%，对目标有一定影响")
            if sens in ("medium", "high") and overlaps(s, e, moon_s, moon_e):
                add("warning", "观测时段内月亮在天上，注意让望远镜避开月光方向")

            # 4. 目标高度
            alt = it.get("best_altitude")
            if alt is not None and alt < 25:
                add("warning", f"目标最高高度仅 {alt:.0f}°，低空大气消光与视宁度影响较大")

            # 5. 天气记录
            if transparency is not None and transparency <= 2 and it.get("type") == "dso":
                add("warning",
                    f"透明度记录较差（{transparency}/5），深空目标效果会受影响，建议改期或改测亮目标")
            if seeing is not None and seeing <= 2 and it.get("type") in ("planet", "lunar", "double"):
                add("warning",
                    f"视宁度记录较差（{seeing}/5），高倍观测{TYPE_LABEL.get(it.get('type'), '目标')}细节受限")

        if cloud is not None and cloud >= 50:
            add("warning", f"云量记录 {cloud}%，存在遮挡风险，请准备备选目标")

        if not messages:
            messages.append({"level": "ok", "text": "时段合适，可以观测"})
        reports[str(it["id"])] = {"level": level, "messages": messages}

    # ---- 冲突检测：目标同时出现 / 设备冲突 ----
    conflicts = []
    for i in range(len(timed)):
        for j in range(i + 1, len(timed)):
            a, a_s, a_e = timed[i]
            b, b_s, b_e = timed[j]
            if not overlaps(a_s, a_e, b_s, b_e):
                continue
            conflicts.append({
                "type": "overlap",
                "message": f"时间重叠：「{a['target_name']}」{fmt(a['planned_start'], a['planned_end'])} 与 "
                           f"「{b['target_name']}」{fmt(b['planned_start'], b['planned_end'])} 同时出现，请错开时段",
            })
            shared = set(a.get("equipment_ids") or []) & set(b.get("equipment_ids") or [])
            for eq_id in shared:
                conflicts.append({
                    "type": "equipment",
                    "message": f"设备冲突：「{eq_map.get(eq_id, '#' + str(eq_id))}」同时分配给 "
                               f"「{a['target_name']}」和「{b['target_name']}」",
                })

    summary = {"ok": 0, "warning": 0, "error": 0, "conflicts": len(conflicts)}
    for rep in reports.values():
        summary[rep["level"]] += 1
    return {"items": reports, "conflicts": conflicts, "summary": summary}


def auto_schedule(session, items, default_duration=30):
    """按目标预计出现时间先后，在当晚可用时段内顺序排布（顺序排布天然避免设备冲突）。

    保留各条目已有的计划时长，未排时间的条目按 default_duration 分钟计。
    返回 [{id, planned_start, planned_end, position}]。
    """
    slot_s, slot_e = norm(session.get("slot_start")), norm(session.get("slot_end"))
    if slot_s is None or slot_e is None or slot_e <= slot_s:
        raise ValueError("请先填写有效的当晚可用时段")

    def vis_start(it):
        v = norm(it.get("visible_start"))
        return v if v is not None else slot_s

    ordered = sorted(items, key=lambda it: (vis_start(it), it.get("position") or 999, it["id"]))
    cursor = slot_s
    updates = []
    for pos, it in enumerate(ordered, 1):
        s0, e0 = norm(it.get("planned_start")), norm(it.get("planned_end"))
        dur = e0 - s0 if (s0 is not None and e0 is not None and e0 > s0) else default_duration
        s = max(cursor, vis_start(it))
        updates.append({
            "id": it["id"],
            "planned_start": denorm(s),
            "planned_end": denorm(s + dur),
            "position": pos,
        })
        cursor = s + dur
    return updates
