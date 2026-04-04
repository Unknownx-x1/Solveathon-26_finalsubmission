from datetime import datetime

from app import app
from models import db, Student, RoomSchedule, Announcement


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def seed_students():
    students = [
        {
            "name": "Aarav Sharma",
            "reg_no": "2024001",
            "floor": 1,
            "room_number": "101",
            "phone_number": "9000000001",
            "token": None,
        },
        {
            "name": "Diya Mehta",
            "reg_no": "2024002",
            "floor": 2,
            "room_number": "204",
            "phone_number": "9000000002",
            "token": None,
        },
        {
            "name": "Kabir Patel",
            "reg_no": "2024003",
            "floor": 3,
            "room_number": "309",
            "phone_number": "9000000003",
            "token": None,
        },
    ]

    created = 0
    for data in students:
        existing = Student.query.filter_by(reg_no=data["reg_no"]).first()
        if existing:
            continue
        db.session.add(Student(**data))
        created += 1
    return created


def seed_schedules():
    today = _today_str()
    schedules = [
        {"date": today, "room_start": 101, "room_end": 120},
        {"date": today, "room_start": 201, "room_end": 220},
        {"date": today, "room_start": 301, "room_end": 320},
    ]

    created = 0
    for data in schedules:
        existing = RoomSchedule.query.filter_by(
            date=data["date"],
            room_start=data["room_start"],
            room_end=data["room_end"],
        ).first()
        if existing:
            continue
        db.session.add(RoomSchedule(**data))
        created += 1
    return created


def seed_announcements():
    existing_count = Announcement.query.count()
    if existing_count > 0:
        return 0

    announcements = [
        {
            "title": "Laundry Collection Window",
            "message": "Laundry collection is open today from 9:00 AM to 5:00 PM.",
        },
        {
            "title": "Token Reminder",
            "message": "Please keep your token ready when handing over laundry.",
        },
    ]

    for data in announcements:
        db.session.add(Announcement(**data))
    return len(announcements)


def seed_all():
    with app.app_context():
        created_students = seed_students()
        created_schedules = seed_schedules()
        created_announcements = seed_announcements()
        db.session.commit()

    print("Seed complete.")
    print(f"Students added: {created_students}")
    print(f"Schedules added: {created_schedules}")
    print(f"Announcements added: {created_announcements}")


if __name__ == "__main__":
    seed_all()
