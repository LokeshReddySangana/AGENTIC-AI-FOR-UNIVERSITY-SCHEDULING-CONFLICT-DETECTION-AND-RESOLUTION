"""Generate a deterministic sample university dataset.

Builds a mostly-clean weekly timetable, then injects one deliberate conflict of
each class so the detector and resolver always have known ground truth.
Run: python data/generate_sample.py
"""
from __future__ import annotations

import json
import os
import random

random.seed(20260715)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_university.json")

# ---------------------------------------------------------------- time slots
SLOT_TIMES = [("09:00", "10:00"), ("10:00", "11:00"), ("11:00", "12:00"), ("14:00", "15:00"), ("15:00", "16:00")]
slots = []
sid = 1
for day in range(1, 6):
    for start, end in SLOT_TIMES:
        slots.append({"id": sid, "day": day, "start": start, "end": end, "is_exam": False})
        sid += 1
# exams sit in a separate Saturday window so they never overlap teaching slots
for start, end in [("09:00", "12:00"), ("13:00", "16:00")]:
    slots.append({"id": sid, "day": 6, "start": start, "end": end, "is_exam": True})
    sid += 1

slots_by_id = {s["id"]: s for s in slots}
TEACHING_SLOTS = [s["id"] for s in slots if not s["is_exam"]]
EXAM_SLOTS = [s["id"] for s in slots if s["is_exam"]]

# --------------------------------------------------------------------- rooms
rooms = [
    {"id": 1, "code": "L-101", "capacity": 60, "kind": "lecture", "features": ["projector"]},
    {"id": 2, "code": "L-102", "capacity": 60, "kind": "lecture", "features": ["projector"]},
    {"id": 3, "code": "L-103", "capacity": 70, "kind": "lecture", "features": ["projector"]},
    {"id": 4, "code": "L-201", "capacity": 90, "kind": "lecture", "features": ["projector", "smart_board"]},
    {"id": 5, "code": "S-01", "capacity": 30, "kind": "seminar", "features": ["projector"]},
    {"id": 6, "code": "S-02", "capacity": 30, "kind": "seminar", "features": []},
    {"id": 7, "code": "Lab-1", "capacity": 40, "kind": "lab", "features": ["computers"]},
    {"id": 8, "code": "Lab-2", "capacity": 40, "kind": "lab", "features": ["computers"]},
    {"id": 9, "code": "Lab-3", "capacity": 45, "kind": "lab", "features": ["computers"]},
    {"id": 10, "code": "E-1", "capacity": 220, "kind": "exam_hall", "features": ["projector"]},
]

# ------------------------------------------------------------------- faculty
faculty = [
    {"id": 1, "name": "Dr. A. Rao", "email": "rao@uni.edu", "max_hours_week": 18},
    {"id": 2, "name": "Dr. S. Iyer", "email": "iyer@uni.edu", "max_hours_week": 16},
    {"id": 3, "name": "Prof. M. Khan", "email": "khan@uni.edu", "max_hours_week": 20},
    {"id": 4, "name": "Dr. P. Nair", "email": "nair@uni.edu", "max_hours_week": 18},
    {"id": 5, "name": "Dr. R. Menon", "email": "menon@uni.edu", "max_hours_week": 16},
    {"id": 6, "name": "Prof. K. Bose", "email": "bose@uni.edu", "max_hours_week": 20},
    {"id": 7, "name": "Dr. T. Sharma", "email": "sharma@uni.edu", "max_hours_week": 18},
    {"id": 8, "name": "Dr. N. Pillai", "email": "pillai@uni.edu", "max_hours_week": 16},
]

groups = [
    {"id": 1, "name": "CSE-3A", "strength": 38, "programme": "CSE", "semester": 3},
    {"id": 2, "name": "CSE-3B", "strength": 36, "programme": "CSE", "semester": 3},
    {"id": 3, "name": "ECE-3A", "strength": 42, "programme": "ECE", "semester": 3},
    {"id": 4, "name": "CSE-5A", "strength": 34, "programme": "CSE", "semester": 5},
    {"id": 5, "name": "MECH-2A", "strength": 45, "programme": "MECH", "semester": 2},
    {"id": 6, "name": "ECE-5A", "strength": 30, "programme": "ECE", "semester": 5},
]

courses = [
    {"id": 1, "code": "CS301", "title": "Operating Systems", "credits": 4, "required_features": []},
    {"id": 2, "code": "CS302", "title": "Computer Networks", "credits": 4, "required_features": []},
    {"id": 3, "code": "CS303", "title": "Database Systems", "credits": 4, "required_features": []},
    {"id": 4, "code": "CS304", "title": "Software Engineering", "credits": 3, "required_features": []},
    {"id": 5, "code": "CS305", "title": "Algorithms", "credits": 4, "required_features": []},
    {"id": 6, "code": "EC301", "title": "Digital Signal Processing", "credits": 4, "required_features": []},
    {"id": 7, "code": "EC302", "title": "VLSI Design", "credits": 3, "required_features": []},
    {"id": 8, "code": "ME201", "title": "Thermodynamics", "credits": 4, "required_features": []},
    {"id": 9, "code": "MA201", "title": "Discrete Mathematics", "credits": 4, "required_features": []},
    {"id": 10, "code": "HU101", "title": "Technical Communication", "credits": 2, "required_features": []},
]

# two faculty per course: the second is the qualified substitute
course_faculty = {
    1: [1, 8], 2: [2, 7], 3: [3, 1], 4: [4, 6], 5: [5, 2],
    6: [6, 4], 7: [7, 3], 8: [8, 5], 9: [2, 5], 10: [4, 6],
}

# groups -> courses they take
curriculum = {
    1: [1, 2, 3, 5, 9],
    2: [1, 2, 3, 4, 9],
    3: [6, 7, 2, 9, 10],
    4: [3, 5, 4, 2, 10],
    5: [8, 9, 10, 4, 5],
    6: [6, 7, 3, 5, 10],
}

sessions = []
next_id = 1
room_busy = set()      # (room_id, slot_id)
faculty_busy = set()   # (faculty_id, slot_id)
group_busy = set()     # (group_id, slot_id)
day_count = {}         # (group_id, day) -> n
course_day = {}        # (group_id, course_id, day) -> n


def fits(gid, fid, room, slot_id, course_id):
    day = slots_by_id[slot_id]["day"]
    if (room["id"], slot_id) in room_busy or (fid, slot_id) in faculty_busy:
        return False
    if (gid, slot_id) in group_busy:
        return False
    if day_count.get((gid, day), 0) >= 4:
        return False
    if course_day.get((gid, course_id, day), 0) >= 2:
        return False
    strength = next(g["strength"] for g in groups if g["id"] == gid)
    return room["capacity"] >= strength


def place(gid, course_id, kind, required):
    global next_id
    fid = course_faculty[course_id][0]
    candidates = [r for r in rooms if r["kind"] != "exam_hall" and set(required) <= set(r["features"])
                  and r["capacity"] >= next(g["strength"] for g in groups if g["id"] == gid)]
    if kind == "lab":
        candidates = [r for r in candidates if r["kind"] == "lab"]
    if kind == "lecture":
        candidates = [r for r in candidates if r["kind"] in ("lecture", "seminar")]
    random.shuffle(candidates)
    slot_ids = TEACHING_SLOTS[:]
    random.shuffle(slot_ids)
    for slot_id in slot_ids:
        for room in candidates:
            if fits(gid, fid, room, slot_id, course_id):
                room_busy.add((room["id"], slot_id))
                faculty_busy.add((fid, slot_id))
                group_busy.add((gid, slot_id))
                day = slots_by_id[slot_id]["day"]
                day_count[(gid, day)] = day_count.get((gid, day), 0) + 1
                course_day[(gid, course_id, day)] = course_day.get((gid, course_id, day), 0) + 1
                sessions.append({
                    "id": next_id, "course_id": course_id, "faculty_id": fid,
                    "room_id": room["id"], "slot_id": slot_id, "kind": kind,
                    "group_ids": [gid], "required_features": required, "pinned": False,
                })
                next_id += 1
                return True
    return False


for gid, course_ids in curriculum.items():
    for course_id in course_ids:
        place(gid, course_id, "lecture", [])
        place(gid, course_id, "lecture", [])
        if course_id in (1, 3, 6, 7):
            place(gid, course_id, "lab", ["computers"])
        else:
            place(gid, course_id, "tutorial", [])

# exams: one per group, spread over the Saturday window across three halls
EXAM_HALLS = [10, 4, 3]  # E-1 (220), L-201 (90), L-103 (70)
for gid in curriculum:
    slot_id = EXAM_SLOTS[0] if gid <= 3 else EXAM_SLOTS[1]
    sessions.append({
        "id": next_id, "course_id": curriculum[gid][0], "faculty_id": gid,
        "room_id": EXAM_HALLS[(gid - 1) % 3], "slot_id": slot_id, "kind": "exam",
        "group_ids": [gid], "required_features": [], "pinned": True,
    })
    next_id += 1

# ------------------------------------------------- deliberate conflict injection
by_key = {}
for s in sessions:
    by_key.setdefault((s["group_ids"][0], s["course_id"], s["kind"]), []).append(s)

# 1. ROOM_DOUBLE_BOOKED: CS303 lecture of CSE-3B into a CSE-3A slot in the same room
a = next(s for s in sessions if s["group_ids"] == [2] and s["course_id"] == 3 and s["kind"] == "lecture")
b = next(s for s in sessions if s["group_ids"] == [1] and s["course_id"] == 3 and s["kind"] == "lecture")
a["room_id"], a["slot_id"] = b["room_id"], b["slot_id"]

# 2. FACULTY_CLASH: give a CS302 session of ECE-3A the same faculty and slot as Dr. Iyer's CS301
c = next(s for s in sessions if s["group_ids"] == [3] and s["course_id"] == 2)
d = next(s for s in sessions if s["group_ids"] == [1] and s["course_id"] == 1 and s["kind"] == "lecture")
c["faculty_id"], c["slot_id"] = d["faculty_id"], d["slot_id"]

# 3. GROUP_CLASH: CSE-5A elective moved onto a slot it already has
e = next(s for s in sessions if s["group_ids"] == [4] and s["course_id"] == 4 and s["kind"] == "tutorial")
f = next(s for s in sessions if s["group_ids"] == [4] and s["course_id"] == 5 and s["kind"] == "lecture")
e["slot_id"] = f["slot_id"]

# 4. CAPACITY_OVERFLOW: MECH-2A (45) into a 30-seat seminar
g = next(s for s in sessions if s["group_ids"] == [5] and s["course_id"] == 8 and s["kind"] == "lecture")
g["room_id"] = 5

# 5. EQUIPMENT_MISMATCH: lab moved into a lecture room
h = next(s for s in sessions if s["group_ids"] == [1] and s["kind"] == "lab")
h["room_id"] = 2

# 6. AVAILABILITY_VIOLATION: leave for Dr. Sharma overlapping his Tuesday sessions
availability = [{"faculty_id": 7, "day": 2, "start": "09:00", "end": "12:00", "kind": "leave"}]

# 7. EXAM_WINDOW: a lecture in an exam slot
i = next(s for s in sessions if s["group_ids"] == [6] and s["course_id"] == 7 and s["kind"] == "lecture")
other_exam_room = i["room_id"]
i["slot_id"] = EXAM_SLOTS[0]

# 8. CURRICULUM_VIOLATION: three CS305 sessions for CSE-5A on one day
day2_slots = [s["id"] for s in slots if s["day"] == 2 and not s["is_exam"]]
triple = [s for s in sessions if s["group_ids"] == [4] and s["course_id"] == 5]
for s, slot_id in zip(triple[:3], day2_slots[:3]):
    s["slot_id"] = slot_id

# ------------------------------------------------------- expanded university
faculty.extend([
    {"id": 9, "name": "Dr. A. Verma", "email": "verma@uni.edu", "max_hours_week": 18},
    {"id": 10, "name": "Prof. R. Kapoor", "email": "kapoor@uni.edu", "max_hours_week": 18},
    {"id": 11, "name": "Dr. S. Gill", "email": "gill@uni.edu", "max_hours_week": 18},
    {"id": 12, "name": "Prof. N. Bhatia", "email": "bhatia@uni.edu", "max_hours_week": 18},
])
groups.extend([
    {"id": 7, "name": "CSE-3C", "strength": 34, "programme": "CSE", "semester": 3},
    {"id": 8, "name": "ECE-3B", "strength": 32, "programme": "ECE", "semester": 3},
])

initial_expansion = [
    (1, 12, 2, 1, 7), (2, 9, 1, 6, 7), (3, 10, 1, 11, 7), (4, 11, 3, 16, 7),
    (5, 12, 3, 21, 7), (9, 9, 2, 2, 7), (10, 10, 1, 7, 7), (1, 11, 1, 12, 7),
    (2, 12, 1, 18, 7), (3, 9, 3, 22, 7), (5, 10, 1, 3, 7), (9, 11, 2, 8, 7),
    (6, 9, 2, 3, 8), (7, 10, 3, 6, 8), (1, 11, 2, 11, 8), (2, 12, 2, 19, 8),
    (9, 9, 4, 21, 8), (10, 10, 3, 4, 8), (6, 11, 2, 9, 8), (7, 12, 1, 13, 8),
    (1, 9, 2, 20, 8), (3, 10, 3, 23, 8), (9, 11, 2, 5, 8), (10, 12, 3, 10, 8),
]
for course_id, faculty_id, room_id, slot_id, group_id in initial_expansion:
    sessions.append({
        "id": next_id,
        "course_id": course_id,
        "faculty_id": faculty_id,
        "room_id": room_id,
        "slot_id": slot_id,
        "kind": "lecture",
        "group_ids": [group_id],
        "required_features": [],
        "pinned": False,
    })
    next_id += 1

programmes = ["CSE", "ECE", "MECH", "EEE", "CIVIL", "AIML"]
existing_group_names = {group["name"] for group in groups}
large_group_specs = []
for programme in programmes:
    for semester in (1, 3, 5, 7):
        for letter in "ABCDE":
            name = f"{programme}-{semester}{letter}"
            if name not in existing_group_names:
                large_group_specs.append((name, programme, semester, 32 + len(large_group_specs) % 14))
            if len(large_group_specs) == 90:
                break
        if len(large_group_specs) == 90:
            break
    if len(large_group_specs) == 90:
        break

for name, programme, semester, strength in large_group_specs:
    groups.append({
        "id": len(groups) + 1,
        "name": name,
        "strength": strength,
        "programme": programme,
        "semester": semester,
    })

first_names = ["Aarav", "Vivaan", "Aditya", "Ishita", "Ananya", "Kavya", "Rohan", "Meera", "Arjun", "Nisha", "Kabir", "Diya", "Rahul", "Sana", "Kiran", "Neha", "Dev", "Riya", "Aman", "Tara"]
last_names = ["Sharma", "Kapoor", "Singh", "Mehta", "Gupta", "Nair", "Reddy", "Bose", "Malhotra", "Iyer", "Bhatia", "Menon", "Rao", "Gill", "Chopra", "Sethi"]
new_faculty_ids = []
for index in range(308):
    faculty_id = len(faculty) + 1
    faculty.append({
        "id": faculty_id,
        "name": f"Dr. {first_names[index % len(first_names)]} {last_names[index // len(first_names)]}",
        "email": f"faculty{faculty_id}@lpu.edu",
        "max_hours_week": 18,
    })
    new_faculty_ids.append(faculty_id)

new_room_ids = []
for index in range(41):
    room_id = len(rooms) + 1
    rooms.append({
        "id": room_id,
        "code": f"L-{301 + index}",
        "capacity": 60,
        "kind": "lecture",
        "features": ["projector"],
    })
    new_room_ids.append(room_id)

slots_by_day = {
    day: sorted(
        [slot for slot in slots if slot["day"] == day and not slot["is_exam"]],
        key=lambda slot: slot["start"],
    )
    for day in range(1, 6)
}
room_load = {}
faculty_slots = {faculty_id: set() for faculty_id in new_faculty_ids}
faculty_load = {faculty_id: 0 for faculty_id in new_faculty_ids}
large_groups = groups[-90:]
for group_index, group in enumerate(large_groups):
    for day_index, day in enumerate(range(1, 6)):
        day_slots = slots_by_day[day]
        start_index = (group_index + day_index) % len(day_slots)
        selected_slots = (day_slots[start_index], day_slots[(start_index + 2) % len(day_slots)])
        for daily_index, slot in enumerate(selected_slots):
            occupied_rooms = room_load.setdefault(slot["id"], set())
            room_id = next(room_id for room_id in new_room_ids if room_id not in occupied_rooms)
            faculty_id = min(
                (fid for fid in new_faculty_ids if slot["id"] not in faculty_slots[fid]),
                key=lambda fid: (faculty_load[fid], fid),
            )
            course_id = ((day_index * 2 + daily_index + group_index) % len(courses)) + 1
            sessions.append({
                "id": next_id,
                "course_id": course_id,
                "faculty_id": faculty_id,
                "room_id": room_id,
                "slot_id": slot["id"],
                "kind": "lecture",
                "group_ids": [group["id"]],
                "required_features": [],
                "pinned": False,
            })
            occupied_rooms.add(room_id)
            faculty_slots[faculty_id].add(slot["id"])
            faculty_load[faculty_id] += 1
            next_id += 1

# Inject a bounded stress set into the expanded schedule: seven faculty clashes
# and seven distinct capacity violations, in addition to the baseline taxonomy.
large_sessions_by_slot = {}
for session in sessions:
    if session["id"] >= 121:
        large_sessions_by_slot.setdefault(session["slot_id"], []).append(session)

faculty_pairs = []
for slot_id in sorted(large_sessions_by_slot):
    slot_sessions = large_sessions_by_slot[slot_id]
    faculty_ids_in_slot = [session["faculty_id"] for session in slot_sessions]
    if len(set(faculty_ids_in_slot)) == len(faculty_ids_in_slot) and len(slot_sessions) >= 2:
        faculty_pairs.append((slot_sessions[0], slot_sessions[1]))
    if len(faculty_pairs) == 7:
        break

faculty_pair_ids = {session["id"] for pair in faculty_pairs for session in pair}
for first, second in faculty_pairs:
    second["faculty_id"] = first["faculty_id"]

group_by_id = {group["id"]: group for group in groups}
capacity_sessions = []
capacity_strengths = set()
capacity_slots = set()
for session in sessions:
    if session["id"] < 121 or session["id"] in faculty_pair_ids:
        continue
    strength = sum(group_by_id[group_id]["strength"] for group_id in session["group_ids"])
    slot_id = session["slot_id"]
    seminar_busy = any(
        other["id"] != session["id"]
        and other["room_id"] == 5
        and other["slot_id"] == slot_id
        for other in sessions
    )
    if strength <= 30 or strength in capacity_strengths or slot_id in capacity_slots or seminar_busy:
        continue
    capacity_sessions.append(session)
    capacity_strengths.add(strength)
    capacity_slots.add(slot_id)
    if len(capacity_sessions) == 7:
        break

for session in capacity_sessions:
    session["room_id"] = 5

payload = {
    "term": {"name": "Monsoon 2026", "starts_on": "2026-07-20", "ends_on": "2026-11-28"},
    "slots": slots,
    "rooms": rooms,
    "faculty": faculty,
    "groups": groups,
    "courses": courses,
    "availability": availability,
    "sessions": sessions,
}

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=1)
print(f"wrote {OUT}: {len(sessions)} sessions, {len(rooms)} rooms, {len(faculty)} faculty")
