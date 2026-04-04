from flask import Flask, request, jsonify, render_template, make_response, send_from_directory, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from models import db, ma, Student, LaundryBatch, RoomSchedule, SystemSettings, StaffUser, StudentInvite, Notification, Announcement, Complaint, DailyLaundryDetail, LaundryRecord, LostFoundItem, BucketRequest, BucketRequestRecipient, StudentSchema, LaundryBatchSchema, RoomScheduleSchema, SystemSettingsSchema, StudentInviteSchema, NotificationSchema, DailyLaundryDetailSchema, AnnouncementSchema, ComplaintSchema, LaundryRecordSchema, LostFoundItemSchema, BucketRequestSchema, BucketRequestRecipientSchema
from schedule_ocr import process_schedule_image, process_schedule_pdf
from token_ocr import allowed_image, cleanup_file, extract_token_number, save_temp_upload
from lost_and_found import delete_image_if_exists, mark_lost_item_found, save_lost_found_image
from datetime import datetime, timedelta
import uuid
import os
import random
from marshmallow import ValidationError
from sqlalchemy import func, inspect, text, or_, and_
import re
from functools import wraps
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

from vtop.auth import auth_bp
from vtop.session_manager import session_storage
from vtop.parsers.profile_parser import parse_profile
import requests

VTOP_BASE_URL = "https://vtopcc.vit.ac.in/vtop/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0'
}

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key')
BOOT_ID = str(uuid.uuid4())

# Register VTOP auth blueprint
app.register_blueprint(auth_bp, url_prefix='/vtop')

# Database setup
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

basedir = os.path.abspath(os.path.dirname(__file__))
sqlite_main = 'sqlite:///' + os.path.join(basedir, 'student.db')
sqlite_daily = 'sqlite:///' + os.path.join(basedir, 'daily.db')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or sqlite_main
app.config['SQLALCHEMY_BINDS'] = {
    'daily': database_url or sqlite_daily
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
ma.init_app(app)

# Schemas
student_schema = StudentSchema()
students_schema = StudentSchema(many=True)
batch_schema = LaundryBatchSchema()
batches_schema = LaundryBatchSchema(many=True)
schedule_schema = RoomScheduleSchema()
schedules_schema = RoomScheduleSchema(many=True)
settings_schema = SystemSettingsSchema()
invite_schema = StudentInviteSchema()
invites_schema = StudentInviteSchema(many=True)
notification_schema = NotificationSchema()
notifications_schema = NotificationSchema(many=True)
daily_detail_schema = DailyLaundryDetailSchema()
daily_details_schema = DailyLaundryDetailSchema(many=True)
announcement_schema = AnnouncementSchema()
announcements_schema = AnnouncementSchema(many=True)
complaint_schema = ComplaintSchema()
complaints_schema = ComplaintSchema(many=True)
laundry_record_schema = LaundryRecordSchema()
laundry_records_schema = LaundryRecordSchema(many=True)
lost_found_item_schema = LostFoundItemSchema()
lost_found_items_schema = LostFoundItemSchema(many=True)
bucket_request_schema = BucketRequestSchema()
bucket_requests_schema = BucketRequestSchema(many=True)
bucket_request_recipient_schema = BucketRequestRecipientSchema()
bucket_request_recipients_schema = BucketRequestRecipientSchema(many=True)

def _ensure_sqlite_column(table_name, column_name, column_sql):
    inspector = inspect(db.engine)
    try:
        existing_columns = {column['name'] for column in inspector.get_columns(table_name)}
    except Exception:
        existing_columns = set()
    if column_name in existing_columns:
        return
    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))
    db.session.commit()

def _run_lightweight_migrations():
    if db.engine.url.get_backend_name() != 'sqlite':
        return

    table_names = set(inspect(db.engine).get_table_names())
    if 'laundry_records' in table_names:
        _ensure_sqlite_column('laundry_records', 'batch_id', 'INTEGER')
        _ensure_sqlite_column('laundry_records', 'student_name', 'VARCHAR')
        _ensure_sqlite_column('laundry_records', 'reg_no', 'VARCHAR')
        _ensure_sqlite_column('laundry_records', 'floor', 'INTEGER')
        _ensure_sqlite_column('laundry_records', 'room_number', 'VARCHAR')
        _ensure_sqlite_column('laundry_records', 'phone_number', 'VARCHAR')
    if 'lost_found_items' in table_names:
        _ensure_sqlite_column('lost_found_items', 'archived_at', 'DATETIME')
    if 'announcements' in table_names:
        _ensure_sqlite_column('announcements', 'audience', "VARCHAR NOT NULL DEFAULT 'all'")
        _ensure_sqlite_column('announcements', 'target_student_id', 'INTEGER')
        _ensure_sqlite_column('announcements', 'category', "VARCHAR NOT NULL DEFAULT 'general'")
        _ensure_sqlite_column('announcements', 'is_urgent', 'BOOLEAN NOT NULL DEFAULT 0')

def _ensure_default_staff_user():
    if StaffUser.query.filter(func.lower(StaffUser.username) == 'test').first():
        return
    db.session.add(
        StaffUser(
            username='Test',
            password_hash=generate_password_hash('1234')
        )
    )

# Create database tables
with app.app_context():
    db.create_all()
    db.create_all(bind_key='daily')
    _run_lightweight_migrations()
    # Initialize settings if not exists
    if not SystemSettings.query.first():
        db.session.add(SystemSettings(edit_window_open=False))
    _ensure_default_staff_user()
    if db.session.new:
        db.session.commit()

VALID_STATUSES = ["booked", "pending", "collected", "washing", "washed", "pickedUp", "cancelled"]
LAUNDRY_RECORD_STATUSES = {"received", "washing", "ready", "delivered"}
LOST_FOUND_STATUSES = {"tracked", "lost", "found"}
LOST_FOUND_CREATORS = {"student", "staff"}
UPLOADS_DIR = (
    os.environ.get('UPLOADS_ROOT')
    or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    or os.path.join(basedir, 'static', 'uploads')
)
OCR_UPLOADS_DIR = os.path.join(UPLOADS_DIR, 'ocr')
LOST_FOUND_UPLOADS_DIR = os.path.join(UPLOADS_DIR, 'lost_found')

def _today_str():
    return datetime.now().strftime('%Y-%m-%d')

def _parse_room_number(room_value):
    if room_value is None:
        return None
    room_str = str(room_value).strip()
    digits = ''.join([c for c in room_str if c.isdigit()])
    if not digits:
        return None
    return int(digits)

def _derive_floor_from_room(room_value):
    room_number = _parse_room_number(room_value)
    if room_number is None:
        return None
    room_digits = str(room_number)
    if len(room_digits) <= 2:
        return 0
    return int(room_digits[:-2])

def _normalize_student_floor(student):
    if not student:
        return False
    derived_floor = _derive_floor_from_room(student.room_number)
    if derived_floor is None or student.floor == derived_floor:
        return False
    student.floor = derived_floor
    return True

def _normalize_students(students):
    changed = False
    for student in students:
        changed = _normalize_student_floor(student) or changed
    if changed:
        db.session.commit()
    return changed

with app.app_context():
    students = Student.query.all()
    normalized = False
    for student in students:
        normalized = _normalize_student_floor(student) or normalized
    if normalized:
        db.session.commit()

AVAILABLE_SLOTS = [
    "08:00 - 09:00",
    "09:00 - 10:00",
    "10:00 - 11:00",
    "11:00 - 12:00",
    "12:00 - 13:00",
    "13:00 - 14:00",
    "18:00 - 19:00",
    "19:00 - 20:00"
]
MAX_PER_SLOT = 25
MONTHLY_SLOT_LIMIT = 4
MISSED_SLOT_LOOKAHEAD_DAYS = 21
PERSONAL_ANNOUNCEMENT_ELIGIBLE_STATUSES = {'collected', 'washing', 'washed'}

def _is_staff_logged_in():
    return bool(session.get('staff_user_id'))

def _staff_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _is_staff_logged_in():
            return redirect(url_for('staff_login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

def _latest_batch_for_student(student_id):
    if not student_id:
        return None
    return LaundryBatch.query.filter_by(student_id=student_id).order_by(LaundryBatch.created_at.desc()).first()

def _student_eligible_for_personal_announcement(student_id):
    latest_batch = _latest_batch_for_student(student_id)
    return bool(latest_batch and latest_batch.status in PERSONAL_ANNOUNCEMENT_ELIGIBLE_STATUSES)

def _announcement_payload_for_student_query(student_id=None):
    query = Announcement.query
    if student_id is not None:
        query = query.filter(
            or_(
                Announcement.audience == 'all',
                and_(
                    Announcement.audience == 'student',
                    Announcement.target_student_id == student_id
                )
            )
        )
    return query.order_by(Announcement.created_at.desc())

def _create_announcement_record(title, message, audience='all', target_student_id=None, category='general', is_urgent=False):
    announcement = Announcement(
        title=title,
        message=message,
        audience=audience,
        target_student_id=target_student_id,
        category=category,
        is_urgent=is_urgent
    )
    db.session.add(announcement)
    return announcement

def _create_slot_added_announcement(batch, previous_date, previous_slot):
    if not batch or not batch.scheduled_date or not batch.time_slot:
        return None
    title = "Urgent Slot Added"
    message = (
        f"An overflow laundry slot was added on {batch.scheduled_date} at {batch.time_slot} "
        f"after a missed submission from {previous_date} {previous_slot}."
    )
    existing = Announcement.query.filter_by(
        category='slot_added',
        title=title,
        message=message
    ).first()
    if existing:
        return existing
    return _create_announcement_record(
        title=title,
        message=message,
        audience='all',
        category='slot_added',
        is_urgent=True
    )

def _count_bookings_for_slot(date_value, time_slot):
    return LaundryBatch.query.filter_by(scheduled_date=date_value, time_slot=time_slot).count()

def _find_best_reassignment_slot():
    start_date = datetime.now().date()
    best_choice = None
    for offset in range(2, MISSED_SLOT_LOOKAHEAD_DAYS + 2):
        candidate_date = start_date.fromordinal(start_date.toordinal() + offset)
        date_value = candidate_date.strftime('%Y-%m-%d')
        for slot in AVAILABLE_SLOTS:
            booking_count = _count_bookings_for_slot(date_value, slot)
            remaining = MAX_PER_SLOT - booking_count
            score = (remaining, -offset, -AVAILABLE_SLOTS.index(slot))
            if best_choice is None or score > best_choice['score']:
                best_choice = {
                    'date': date_value,
                    'slot': slot,
                    'remaining': remaining,
                    'score': score,
                }
    return best_choice

def _slot_end_datetime(batch):
    if not batch or not batch.scheduled_date or not batch.time_slot:
        return None
    try:
        end_part = str(batch.time_slot).split('-')[-1].strip()
        return datetime.strptime(f"{batch.scheduled_date} {end_part}", '%Y-%m-%d %H:%M')
    except Exception:
        return None

def _cancel_legacy_auto_reassigned_bookings():
    changed = False
    legacy_batches = LaundryBatch.query.filter_by(status='booked').all()
    for batch in legacy_batches:
        notes = str(batch.notes or '')
        if 'Auto-reassigned after missed slot' not in notes:
            continue
        batch.status = 'cancelled'
        suffix = "Automatic reassignment removed. Please create a new booking manually."
        if suffix not in notes:
            batch.notes = (notes.strip() + ' | ' if notes.strip() else '') + suffix
        _create_notification(batch.student_id, batch.id, 'cancelled')
        changed = True
    return changed

def _process_missed_bookings():
    now = datetime.now()
    changed = _cancel_legacy_auto_reassigned_bookings()
    booked_batches = LaundryBatch.query.filter_by(status='booked').all()
    for batch in booked_batches:
        slot_end = _slot_end_datetime(batch)
        if not slot_end or slot_end >= now:
            continue
        previous_date = batch.scheduled_date
        previous_slot = batch.time_slot
        batch.status = 'cancelled'
        note = f"Missed slot on {previous_date} {previous_slot}. Booking cancelled."
        batch.notes = ((batch.notes or '').strip() + ' | ' if (batch.notes or '').strip() else '') + note
        _create_notification(batch.student_id, batch.id, 'cancelled')
        changed = True
    if changed:
        db.session.commit()
    return changed

def _booking_spacing_conflict(student_id, date_val):
    return None

def _student_booking_count_current_month(student_id):
    now = datetime.now()
    month_prefix = now.strftime('%Y-%m')
    return LaundryBatch.query.filter(
        LaundryBatch.student_id == student_id,
        LaundryBatch.scheduled_date.like(f"{month_prefix}-%")
    ).count()

def _student_has_bucket_access(student_id):
    return _student_booking_count_current_month(student_id) >= MONTHLY_SLOT_LIMIT

def _students_with_slots_next_7_days():
    today = datetime.now().date()
    end_date = today + timedelta(days=7)
    students = Student.query.join(LaundryBatch, LaundryBatch.student_id == Student.id).filter(
        LaundryBatch.status == 'booked'
    ).all()
    eligible = []
    seen = set()
    for s in students:
        for b in s.batches:
            if b.status != 'booked' or not b.scheduled_date:
                continue
            try:
                d = datetime.strptime(b.scheduled_date, '%Y-%m-%d').date()
            except Exception:
                continue
            if today < d <= end_date and s.id not in seen:
                seen.add(s.id)
                eligible.append(s)
                break
    return eligible

def _create_notification(student_id, batch_id, status):
    messages = {
        "booked": "Your laundry slot has been booked.",
        "pending": "Your laundry request is pending.",
        "collected": "Your laundry has been submitted.",
        "washing": "Your laundry is being washed.",
        "washed": "Your laundry has been washed and is ready for pickup.",
        "pickedUp": "Your laundry has been picked up. Thank you!",
        "cancelled": "Your booking was cancelled because the laundry date was missed."
    }
    message = messages.get(status)
    if not message:
        return None
    notification = Notification(
        student_id=student_id,
        batch_id=batch_id,
        status=status,
        message=message
    )
    db.session.add(notification)
    return notification

def _upsert_daily_detail(student_id, batch_id, status, room_number, notes=None):
    today = _today_str()
    detail = DailyLaundryDetail.query.filter_by(date=today, student_id=student_id).first()
    if not detail:
        detail = DailyLaundryDetail(
            date=today,
            student_id=student_id,
            batch_id=batch_id,
            status=status,
            room_number=room_number,
            notes=notes
        )
        db.session.add(detail)
    else:
        detail.batch_id = batch_id
        detail.status = status
        detail.room_number = room_number
        if notes:
            detail.notes = notes
    return detail

def _clear_daily_detail(student_id):
    DailyLaundryDetail.query.filter_by(date=_today_str(), student_id=student_id).delete()

def _get_laundry_record_by_token(token):
    token_query = str(token).strip()
    if not token_query:
        return None

    batch = LaundryBatch.query.filter_by(token=token_query).first()
    if not batch:
        return None

    return {
        "id": batch.id,
        "token": batch.token,
        "name": batch.student.name if batch.student else "Unknown",
        "block": batch.student.floor if batch.student else "-",
        "room_number": batch.student.room_number if batch.student else "-",
        "date_given": batch.created_at.strftime("%Y-%m-%d") if batch.created_at else "",
        "status": batch.status,
    }

def _update_laundry_record_status(token, status):
    token_query = str(token).strip()
    next_status = str(status).strip().lower()

    if not token_query:
        raise ValueError("Token is required")
    if next_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status. Valid statuses: {', '.join(VALID_STATUSES)}")

    batch = LaundryBatch.query.filter_by(token=token_query).first()
    if not batch:
        return None

    batch.status = next_status
    now = datetime.now()

    if next_status == "collected":
        batch.collected_at = now
    elif next_status == "washed":
        batch.washed_at = now
    elif next_status == "pickedUp":
        batch.picked_up_at = now
        _detach_token_from_batch_student(batch)

    db.session.commit()

    return {
        "id": batch.id,
        "token": batch.token,
        "name": batch.student.name if batch.student else "Unknown",
        "block": batch.student.floor if batch.student else "-",
        "room_number": batch.student.room_number if batch.student else "-",
        "date_given": batch.created_at.strftime("%Y-%m-%d") if batch.created_at else "",
        "status": batch.status,
    }

def _extract_month_year(month_label):
    """
    Parse month label like "September 2026" and return (year, month_num).
    Falls back to current year/month when parsing fails.
    """
    now = datetime.now()
    year_match = re.search(r"(\d{4})", month_label or "")
    year = int(year_match.group(1)) if year_match else now.year

    month_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        month_label or "",
        re.IGNORECASE,
    )
    if not month_match:
        return year, now.month

    month_name = month_match.group(1).capitalize()
    month_num = datetime.strptime(month_name, "%B").month
    return year, month_num

def _sanitize_holidays(holidays, date_str):
    if not isinstance(holidays, list):
        return []
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except Exception:
        return []
    days_in_month = int((datetime(dt.year + (1 if dt.month == 12 else 0), 1 if dt.month == 12 else dt.month + 1, 1) - datetime(dt.year, dt.month, 1)).days)
    clean = []
    for day in holidays:
        try:
            d = int(day)
        except Exception:
            continue
        if 1 <= d <= days_in_month and d not in clean:
            clean.append(d)
    clean.sort()
    return clean

def _serialize_laundry_record(record):
    if not record:
        return None
    payload = laundry_record_schema.dump(record)
    payload["token_number"] = payload["tokenNumber"]
    payload["batch_id"] = payload["batchId"]
    payload["student_id"] = payload["studentId"]
    payload["student_name"] = payload["studentName"]
    payload["reg_no"] = payload["regNo"]
    payload["floor"] = record.floor
    payload["room_number"] = payload["roomNumber"]
    payload["phone_number"] = payload["phoneNumber"]
    payload["clothes_count"] = payload["clothesCount"]
    payload["created_at"] = payload["createdAt"]
    payload["updated_at"] = payload["updatedAt"]
    payload["studentRegNo"] = payload["reg_no"]
    return payload

def _parse_int_field(value, field_name):
    if value is None or str(value).strip() == '':
        raise ValueError(f"{field_name} is required")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer")

def _parse_optional_int_field(value, field_name):
    if value is None or str(value).strip() == '':
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer")

def _parse_optional_float_field(value, field_name):
    if value is None or str(value).strip() == '':
        return 0.0
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number")

def _coerce_archive_flag(value):
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

def _build_lost_found_image_url(filename):
    return f"/uploads/lost_found/{filename}"

def _resolve_storage_path_from_url(image_url):
    if not image_url:
        return None
    normalized = str(image_url).strip()
    if normalized.startswith('/uploads/'):
        relative_path = normalized[len('/uploads/'):].replace('/', os.sep)
        return os.path.join(UPLOADS_DIR, relative_path)
    if normalized.startswith('/static/uploads/'):
        relative_path = normalized[len('/static/uploads/'):].replace('/', os.sep)
        return os.path.join(UPLOADS_DIR, relative_path)
    relative_path = normalized.lstrip('/').replace('/', os.sep)
    return os.path.join(basedir, relative_path)

def _map_batch_status_to_laundry_status(batch_status):
    mapping = {
        'pending': 'received',
        'booked': 'received',
        'collected': 'received',
        'washing': 'washing',
        'washed': 'ready',
        'pickedUp': 'delivered',
        'cancelled': 'cancelled',
    }
    return mapping.get((batch_status or '').strip(), 'received')

def _get_latest_batch_for_token_number(token_number):
    return LaundryBatch.query.filter_by(token=str(token_number)).order_by(LaundryBatch.created_at.desc()).first()

def _sync_laundry_record_from_batch(batch, clothes_count=None, weight=None):
    if not batch:
        return None
    token_text = str(batch.token or '').strip()
    if not token_text.isdigit():
        return None

    token_number = int(token_text)
    record = LaundryRecord.query.filter_by(token_number=token_number).first()
    if not record:
        record = LaundryRecord(token_number=token_number)
        db.session.add(record)

    student = batch.student
    record.batch_id = batch.id
    record.student_id = student.id if student else None
    record.student_name = student.name if student else None
    record.reg_no = student.reg_no if student else None
    record.floor = student.floor if student else None
    record.room_number = student.room_number if student else None
    record.phone_number = student.phone_number if student else None
    if clothes_count is not None:
        record.clothes_count = clothes_count
    elif record.clothes_count is None:
        record.clothes_count = 0
    if weight is not None:
        record.weight = weight
    elif record.weight is None:
        record.weight = 0.0
    record.status = _map_batch_status_to_laundry_status(batch.status)
    return record

def _get_student_loss_eligible_batch(student_id):
    return LaundryBatch.query.filter(
        LaundryBatch.student_id == student_id,
        LaundryBatch.status.in_(['collected', 'washing', 'washed'])
    ).order_by(LaundryBatch.created_at.desc()).first()

def _get_active_batch_for_student(student_id):
    return LaundryBatch.query.filter(
        LaundryBatch.student_id == student_id,
        LaundryBatch.status.notin_(['pickedUp', 'cancelled'])
    ).order_by(LaundryBatch.created_at.desc()).first()

def _can_generate_token_for_batch(batch):
    if not batch:
        return False, "Book a laundry slot before generating a token."
    if _has_generated_token(batch):
        return False, "A token already exists for your current laundry. You can generate a new one only after pickup."
    if batch.scheduled_date and batch.scheduled_date != _today_str():
        return False, "Token can be generated only on the scheduled booking date."
    return True, ""

def _has_generated_token(batch):
    if not batch:
        return False
    return batch.status not in ('booked', 'pending') and bool(str(batch.token or '').strip())

def _build_archived_batch_token(batch):
    token_text = str(batch.token or '').strip() or f"BATCH-{batch.id}"
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    return f"{token_text}-archived-{batch.id}-{timestamp}"

def _detach_token_from_batch_student(batch):
    if not batch:
        return
    original_token = str(batch.token or '').strip()
    if batch.student and original_token and str(batch.student.token or '').strip() == original_token:
        batch.student.token = None
    if batch.status == 'pickedUp' and original_token:
        batch.token = _build_archived_batch_token(batch)

def _resolve_batch_token_conflict(student, token, active_batch=None):
    existing_batch = LaundryBatch.query.filter_by(token=token).first()
    if not existing_batch:
        return None, None
    if active_batch and existing_batch.id == active_batch.id:
        return existing_batch, None
    if existing_batch.student_id != student.id:
        return existing_batch, "Token number already in use"
    if existing_batch.status not in ('pickedUp', 'cancelled'):
        return existing_batch, "This token is already linked to another active laundry batch."

    existing_batch.token = _build_archived_batch_token(existing_batch)
    # Flush the archived token immediately so the active batch can safely reuse
    # the original numeric token without hitting the unique index during autoflush.
    db.session.flush()
    return existing_batch, None

def _get_booking_number(batch):
    if not batch:
        return None
    query = LaundryBatch.query.filter(LaundryBatch.created_at <= batch.created_at)
    if batch.scheduled_date:
        query = query.filter(LaundryBatch.scheduled_date == batch.scheduled_date)
    if batch.time_slot:
        query = query.filter(LaundryBatch.time_slot == batch.time_slot)
    return query.count()

def _get_active_lost_found_item(student_id=None, token_number=None):
    query = LostFoundItem.query.filter(LostFoundItem.archived_at.is_(None))
    if student_id is not None:
        query = query.filter(LostFoundItem.student_id == student_id)
    if token_number is not None:
        query = query.filter(LostFoundItem.token_number == token_number)
    return query.order_by(LostFoundItem.created_at.desc()).first()

def _get_tracked_lost_found_item(student_id=None, token_number=None):
    query = LostFoundItem.query.filter(
        LostFoundItem.archived_at.is_(None),
        LostFoundItem.status == 'tracked'
    )
    if student_id is not None:
        query = query.filter(LostFoundItem.student_id == student_id)
    if token_number is not None:
        query = query.filter(LostFoundItem.token_number == token_number)
    return query.order_by(LostFoundItem.created_at.desc()).first()

def _archive_lost_found_items_for_batch(batch):
    if not batch:
        return
    token_text = str(batch.token or '').strip()
    if not token_text.isdigit():
        return
    now = datetime.utcnow()
    LostFoundItem.query.filter(
        LostFoundItem.student_id == batch.student_id,
        LostFoundItem.token_number == int(token_text),
        LostFoundItem.archived_at.is_(None)
    ).update({"archived_at": now}, synchronize_session=False)

def _ensure_lost_found_tracking(student, batch, image):
    token_text = str(batch.token or '').strip()
    if not token_text.isdigit():
        return None

    token_number = int(token_text)
    if hasattr(image, 'stream'):
        image.stream.seek(0)
    filename, _ = save_lost_found_image(image, LOST_FOUND_UPLOADS_DIR)
    image_url = _build_lost_found_image_url(filename)

    item = _get_active_lost_found_item(student_id=student.id, token_number=token_number)
    old_image_path = None
    if item:
        if item.image_url and item.image_url != image_url:
            old_image_path = _resolve_storage_path_from_url(item.image_url)
        item.image_url = image_url
        item.status = 'tracked'
        item.description = item.description or 'Laundry bag registered from token generation.'
        item.created_by = 'student'
    else:
        item = LostFoundItem(
            token_number=token_number,
            student_id=student.id,
            image_url=image_url,
            description='Laundry bag registered from token generation.',
            status='tracked',
            created_by='student',
        )
        db.session.add(item)

    if old_image_path:
        delete_image_if_exists(old_image_path)
    return item

def _upsert_laundry_record(payload):
    token_number = _parse_int_field(payload.get('tokenNumber', payload.get('token_number')), 'tokenNumber')
    clothes_count = _parse_int_field(payload.get('clothesCount', payload.get('clothes_count', 0)), 'clothesCount')
    weight = _parse_optional_float_field(payload.get('weight', 0), 'weight')
    status = str(payload.get('status', 'received')).strip().lower()
    student_id = _parse_optional_int_field(payload.get('studentId', payload.get('student_id')), 'studentId')

    if status not in LAUNDRY_RECORD_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(LAUNDRY_RECORD_STATUSES))}")

    student = None
    if student_id is not None:
        student = Student.query.get(student_id)
        if not student:
            raise LookupError("Student not found")

    batch = _get_latest_batch_for_token_number(token_number)
    record = _sync_laundry_record_from_batch(batch, clothes_count=clothes_count, weight=weight)
    created = False
    if not record:
        record = LaundryRecord.query.filter_by(token_number=token_number).first()
        if not record:
            record = LaundryRecord(token_number=token_number)
            db.session.add(record)
            created = True
    elif record.id is None:
        created = True

    if student:
        record.student_id = student.id
        record.student_name = student.name
        record.reg_no = student.reg_no
        record.floor = student.floor
        record.room_number = student.room_number
        record.phone_number = student.phone_number

    record.clothes_count = clothes_count
    record.weight = weight
    record.status = status
    db.session.commit()
    return record, created

def _serialize_lost_found_item(item):
    if not item:
        return None
    payload = lost_found_item_schema.dump(item)
    payload["token_number"] = payload["tokenNumber"]
    payload["student_id"] = payload["studentId"]
    payload["image_url"] = payload["imageUrl"]
    payload["created_by"] = payload["createdBy"]
    payload["archived_at"] = payload["archivedAt"]
    payload["created_at"] = payload["createdAt"]
    payload["studentName"] = item.student.name if item.student else None
    payload["studentRegNo"] = item.student.reg_no if item.student else None
    return payload

def _extract_token_from_image_file(image):
    if not image or not image.filename:
        raise ValueError("image is required")
    if not allowed_image(image.filename):
        raise ValueError("Unsupported image format")

    if hasattr(image, 'stream'):
        image.stream.seek(0)
    temp_path = None
    try:
        temp_path = save_temp_upload(image, OCR_UPLOADS_DIR)
        return extract_token_number(temp_path)
    finally:
        cleanup_file(temp_path)

def _is_manual_token_fallback_error(message):
    text = str(message or "").strip().lower()
    return "no numeric token detected" in text

def _token_generation_response(message, token_number, details, batch, status_code):
    record = LaundryRecord.query.filter_by(token_number=token_number).first()
    if not record and batch:
        record = _sync_laundry_record_from_batch(batch)
        db.session.commit()
    item = _get_active_lost_found_item(
        student_id=batch.student_id if batch else None,
        token_number=token_number
    )
    return jsonify({
        "message": message,
        "tokenNumber": token_number,
        "token_number": token_number,
        "details": details,
        "batch": batch_schema.dump(batch) if batch else None,
        "record": _serialize_laundry_record(record),
        "lostFoundItem": _serialize_lost_found_item(item),
    }), status_code

# --- Frontend Routes ---
@app.route('/', methods=['GET'])
def index():
    return render_template('landing.html')

@app.route('/staff/login', methods=['GET', 'POST'])
def staff_login():
    if _is_staff_logged_in():
        return redirect(url_for('staff_portal'))

    error = None
    if request.method == 'POST':
        username = str(request.form.get('username', '')).strip()
        password = str(request.form.get('password', '')).strip()
        user = StaffUser.query.filter(func.lower(StaffUser.username) == username.lower()).first() if username else None
        if user and check_password_hash(user.password_hash, password):
            session['staff_user_id'] = user.id
            session['staff_username'] = user.username
            next_url = request.args.get('next') or url_for('staff_portal')
            return redirect(next_url)
        error = 'Invalid username or password.'
    return render_template('staff/login.html', error=error)

@app.route('/staff/signup', methods=['GET', 'POST'])
def staff_signup():
    if _is_staff_logged_in():
        return redirect(url_for('staff_portal'))

    error = None
    success = None
    if request.method == 'POST':
        username = str(request.form.get('username', '')).strip()
        password = str(request.form.get('password', '')).strip()
        confirm_password = str(request.form.get('confirm_password', '')).strip()

        if not username or not password:
            error = 'Username and password are required.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif StaffUser.query.filter(func.lower(StaffUser.username) == username.lower()).first():
            error = 'Username already exists.'
        else:
            db.session.add(
                StaffUser(
                    username=username,
                    password_hash=generate_password_hash(password)
                )
            )
            db.session.commit()
            success = 'Staff account created successfully. You can sign in now.'

    return render_template('staff/signup.html', error=error, success=success)

@app.route('/staff/logout', methods=['GET'])
def staff_logout():
    session.pop('staff_user_id', None)
    session.pop('staff_username', None)
    return redirect(url_for('staff_login'))

@app.route('/staff', methods=['GET'])
@_staff_login_required
def staff_portal():
    return render_template('staff/dashboard.html')

@app.route('/student', methods=['GET'])
def student_portal():
    return render_template('student/home.html')

@app.route('/student/status', methods=['GET'])
def student_status_page():
    return render_template('student/status.html')

@app.route('/student/token-generation', methods=['GET'])
def student_token_generation_page():
    return render_template('student/token_generation_v2.html')

@app.route('/student/schedule', methods=['GET'])
def student_schedule_page():
    return render_template('student/schedule.html')

@app.route('/student/notifications', methods=['GET'])
def student_notifications_page():
    return render_template('student/notifications.html')

@app.route('/student/complaints', methods=['GET'])
def student_complaints_page():
    return render_template('student/complaints.html')

@app.route('/student/bucket', methods=['GET'])
def student_bucket_page():
    return render_template('student/bucket.html')

@app.route('/student/lost-found', methods=['GET'])
def student_lost_found_page():
    return render_template('student/lost_found_v2.html')

@app.route('/student/register', methods=['GET'])
def student_register():
    return render_template('student/register.html')

@app.route('/student/login', methods=['GET'])
def student_login():
    return render_template('student/register.html')

@app.route('/uploads/<path:subpath>', methods=['GET'])
def serve_uploaded_file(subpath):
    return send_from_directory(UPLOADS_DIR, subpath)

@app.route('/api/dashboard/summary', methods=['GET'])
def get_dashboard_summary():
    _process_missed_bookings()
    total_students = Student.query.count()
    active_batches = LaundryBatch.query.filter(LaundryBatch.status.notin_(['pickedUp', 'cancelled'])).count()
    submitted_batches = LaundryBatch.query.filter_by(status='collected').count()
    in_washing = LaundryBatch.query.filter_by(status='washing').count()
    ready_for_pickup = LaundryBatch.query.filter_by(status='washed').count()
    
    today = _today_str()
    completed_today = LaundryBatch.query.filter(
        LaundryBatch.status == 'pickedUp',
        func.date(LaundryBatch.picked_up_at) == today
    ).count()

    return jsonify({
        "totalStudents": total_students,
        "activeBatches": active_batches,
        "submittedBatches": submitted_batches,
        "inWashing": in_washing,
        "readyForPickup": ready_for_pickup,
        "completedToday": completed_today
    })

@app.route('/api/stats', methods=['GET'])
def get_stats_alias():
    return get_dashboard_summary()

@app.route('/api/slots/available', methods=['GET'])
def get_available_slots():
    _process_missed_bookings()
    date_val = request.args.get('date')
    if not date_val:
        return jsonify({"error": "Date is required"}), 400
    
    # Get all bookings for this date
    batches = LaundryBatch.query.filter_by(scheduled_date=date_val).all()
    
    # Count them
    counts = {slot: 0 for slot in AVAILABLE_SLOTS}
    for b in batches:
        if b.time_slot in counts:
            counts[b.time_slot] += 1
    
    slots_info = []
    try:
        booking_date = datetime.strptime(date_val, '%Y-%m-%d')
        today = datetime.now().date()
        booking_date_only = booking_date.date()
        current_time = datetime.now().time()
        
        for slot in AVAILABLE_SLOTS:
            # Skip past slots
            if booking_date_only < today:
                continue
            
            # If booking is for today, skip slots that have already passed
            if booking_date_only == today:
                slot_end_str = slot.split(' - ')[1]
                slot_end_time = datetime.strptime(slot_end_str, '%H:%M').time()
                if current_time > slot_end_time:
                    continue
            
            slots_info.append({
                "slot": slot,
                "booked": counts[slot],
                "available": MAX_PER_SLOT - counts[slot],
                "total": MAX_PER_SLOT
            })
    except ValueError:
        pass
    
    return jsonify(slots_info)

@app.route('/api/daily-loads', methods=['GET'])
def get_daily_loads():
    details = DailyLaundryDetail.query.filter_by(date=_today_str()).order_by(DailyLaundryDetail.created_at.desc()).all()
    payload = daily_details_schema.dump(details)
    student_ids = [d["studentId"] for d in payload if d.get("studentId")]
    students = Student.query.filter(Student.id.in_(student_ids)).all() if student_ids else []
    student_map = {s.id: student_schema.dump(s) for s in students}
    for item in payload:
        item["student"] = student_map.get(item.get("studentId"))
    return jsonify(payload)

@app.route('/student/profile', methods=['GET'])
def student_profile():
    return render_template('student/profile.html')

@app.route('/student/submit', methods=['GET'])
def student_submit():
    return render_template('student/submit_laundry.html')

@app.route('/student/batches/<int:id>', methods=['GET'])
def student_batch_detail(id):
    return render_template('student/batch_detail.html', batch_id=id)

@app.route('/staff/students', methods=['GET'])
@_staff_login_required
def staff_students():
    return render_template('staff/students.html')

@app.route('/staff/students/<int:id>', methods=['GET'])
@_staff_login_required
def staff_student_detail(id):
    return render_template('staff/student_detail.html', student_id=id)

@app.route('/staff/scan', methods=['GET'])
@_staff_login_required
def staff_scan():
    return render_template('staff/scan.html')

@app.route('/staff/schedules', methods=['GET'])
@_staff_login_required
def staff_schedules():
    return render_template('staff/schedules.html')

@app.route('/staff/settings', methods=['GET'])
@_staff_login_required
def staff_settings():
    return render_template('staff/settings.html')

@app.route('/staff/notifications', methods=['GET'])
@_staff_login_required
def staff_notifications():
    """Route for announcement management as in friend's repo"""
    return render_template('staff/notifications.html')

@app.route('/staff/complaints', methods=['GET'])
@_staff_login_required
def staff_complaints_page():
    return render_template('staff/complaints.html')

@app.route('/staff/lost-found', methods=['GET'])
@_staff_login_required
def staff_lost_found_page():
    return render_template('staff/lost_found_v2.html')

@app.route('/api/students/<int:id>', methods=['DELETE'])
def delete_student(id):
    student = Student.query.get_or_404(id)
    # Clean up related records to avoid FK issues in SQLite
    StudentInvite.query.filter_by(used_by_student_id=student.id).update(
        {"used_by_student_id": None, "used_at": None}
    )
    Complaint.query.filter_by(student_id=student.id).delete()
    Notification.query.filter_by(student_id=student.id).delete()
    BucketRequestRecipient.query.filter_by(recipient_student_id=student.id).delete()
    BucketRequest.query.filter_by(requester_student_id=student.id).delete()
    BucketRequest.query.filter_by(accepted_by_student_id=student.id).update({"accepted_by_student_id": None})
    DailyLaundryDetail.query.filter_by(student_id=student.id).delete()
    LaundryBatch.query.filter_by(student_id=student.id).delete()
    db.session.delete(student)
    db.session.commit()
    return '', 204

import csv
from io import StringIO
from flask import make_response

@app.route('/api/students/export/csv', methods=['GET'])
def export_students_csv():
    students = Student.query.all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Name', 'Reg No', 'Floor', 'Room', 'Phone', 'Token'])
    for s in students:
        cw.writerow([s.id, s.name, s.reg_no, s.floor, s.room_number, s.phone_number, s.token])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=students.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# --- Routes: Health ---
@app.route('/api/healthz', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "bootId": BOOT_ID})

# --- Routes: Socket.IO placeholder (prevents noisy 404s if a client still pings) ---
@app.route('/socket.io/', methods=['GET', 'POST'])
@app.route('/socket.io', methods=['GET', 'POST'])
def socketio_placeholder():
    return make_response('', 204)

# --- Routes: Students ---
@app.route('/api/students', methods=['GET'])
def list_students():
    students = Student.query.all()
    _normalize_students(students)
    return jsonify(students_schema.dump(students))

@app.route('/api/students', methods=['POST'])
def create_student():
    try:
        data = request.json
        token = data.get('token')
        
        if not token:
            return jsonify({"error": "Token is required"}), 400
        
        # Check if token already exists
        existing_by_token = Student.query.filter_by(token=token).first()
        if existing_by_token:
            return jsonify({"error": "Token already assigned to another student"}), 400
        
        room_number = str(data['roomNumber']).strip()
        floor = _derive_floor_from_room(room_number)
        if floor is None:
            return jsonify({"error": "Valid room number is required to derive floor"}), 400

        new_student = Student(
            name=data['name'],
            reg_no=data['regNo'],
            floor=floor,
            room_number=room_number,
            phone_number=data['phoneNumber'],
            token=token
        )
        db.session.add(new_student)
        db.session.commit()
        return jsonify(student_schema.dump(new_student)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Removed manual registration (register_student deleted)

@app.route('/api/register/vtop', methods=['POST'])
def register_vtop_student():
    """Register student using data from VTOP session"""
    session_id = request.cookies.get('session_id')
    if not session_id or session_id not in session_storage:
        return jsonify({'status': 'failure', 'message': 'Invalid session.'}), 400

    api_session = session_storage[session_id]['session']
    try:
        profile_url = VTOP_BASE_URL + "studentsRecord/StudentProfileAllView"
        csrf_token = session_storage[session_id].get('csrf_token')
        authorized_id = session_storage[session_id].get('authorized_id') or session_storage[session_id].get('username')

        headers = HEADERS.copy()
        headers['Referer'] = VTOP_BASE_URL + "home"

        response = api_session.post(
            profile_url,
            data={'_csrf': csrf_token, 'authorizedID': authorized_id},
            headers=headers, verify=False, timeout=20
        )
        response.raise_for_status()

        data = parse_profile(response.text)
        if not data:
            return jsonify({"error": "Failed to fetch student profile from VTOP"}), 400

        name = (data.get('personal') or {}).get('name') or 'Student'
        parsed_reg_no = (data.get('educational') or {}).get('reg_no') or (data.get('personal') or {}).get('reg_no')
        reg_no = (session_storage[session_id].get('username') or authorized_id or parsed_reg_no or '').strip()
        if not reg_no:
            return jsonify({"error": "Could not determine registration number from VTOP login"}), 400
        room_number = (data.get('hostel') or {}).get('room') or ''
        phone_number = (data.get('personal') or {}).get('mobile') or ''
        floor = _derive_floor_from_room(room_number)
        if floor is None:
            return jsonify({"error": "Could not determine floor from room number"}), 400

        student = Student.query.filter_by(reg_no=reg_no).first()
        if not student and parsed_reg_no and parsed_reg_no != reg_no:
            student = Student.query.filter_by(reg_no=parsed_reg_no).first()
        if not student:
            student = Student(
                name=name,
                reg_no=reg_no,
                floor=floor,
                room_number=str(room_number),
                phone_number=str(phone_number),
                token=None
            )
            db.session.add(student)
            message = "Student registered via VTOP."
        else:
            student.name = name
            student.reg_no = reg_no
            student.floor = floor
            student.room_number = str(room_number)
            if phone_number:
                student.phone_number = str(phone_number)
            message = "Student details updated via VTOP."

        db.session.commit()
        return jsonify({
            "status": "success",
            "message": message,
            "student": student_schema.dump(student)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/student-invites', methods=['POST'])
def create_student_invite():
    data = request.json or {}
    token = data.get('token')
    
    if not token:
        return jsonify({"error": "Token is required"}), 400
    
    # Check if token already exists
    existing_student = Student.query.filter_by(token=token).first()
    if existing_student:
        return jsonify({"error": "Token already assigned to a student"}), 400
    
    existing_invite = StudentInvite.query.filter_by(token=token).first()
    if existing_invite:
        return jsonify({"error": "Token already exists as an invite"}), 400
    
    invite = StudentInvite(token=token)
    db.session.add(invite)
    db.session.commit()
    return jsonify(invite_schema.dump(invite)), 201

@app.route('/api/student-invites/by-token/<token>', methods=['GET'])
def get_invite_by_token(token):
    invite = StudentInvite.query.filter_by(token=token).first()
    if not invite or invite.used_at:
        return jsonify({"error": "Invite not found or already used"}), 404
    return jsonify(invite_schema.dump(invite))

@app.route('/api/student-invites/claim', methods=['POST'])
def claim_student_invite():
    data = request.json
    token = data.get('token')
    invite = StudentInvite.query.filter_by(token=token).first()
    if not invite or invite.used_at:
        return jsonify({"error": "Invite not found or already used"}), 404

    existing = Student.query.filter_by(reg_no=data.get('regNo')).first()
    if existing:
        return jsonify({"error": "Reg No already exists"}), 400

    room_number = str(data['roomNumber']).strip()
    floor = _derive_floor_from_room(room_number)
    if floor is None:
        return jsonify({"error": "Valid room number is required to derive floor"}), 400

    student = Student(
        name=data['name'],
        reg_no=data['regNo'],
        floor=floor,
        room_number=room_number,
        phone_number=data['phoneNumber'],
        token=token
    )
    db.session.add(student)
    db.session.flush()

    invite.used_at = datetime.now()
    invite.used_by_student_id = student.id

    db.session.commit()
    return jsonify(student_schema.dump(student)), 201

@app.route('/api/students/<int:id>', methods=['GET'])
def get_student(id):
    student = Student.query.get_or_404(id)
    _normalize_student_floor(student)
    db.session.commit()
    return jsonify(student_schema.dump(student))

@app.route('/api/students/<int:id>/assign-token', methods=['POST'])
def assign_student_token(id):
    """Assign a token to a student (staff/admin only)"""
    student = Student.query.get_or_404(id)
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"error": "Token is required"}), 400
    
    # Check if token already assigned to another student
    existing = Student.query.filter_by(token=token).first()
    if existing and existing.id != id:
        return jsonify({"error": "Token already assigned to another student"}), 400
    
    student.token = token
    db.session.commit()
    return jsonify(student_schema.dump(student)), 200

@app.route('/api/students/<int:id>/claim-token', methods=['POST'])
def claim_student_token(id):
    """Allow student to manually claim/update their own token number."""
    student = Student.query.get_or_404(id)
    data = request.json or {}
    token = str(data.get('token', '')).strip()

    if not token:
        return jsonify({"error": "Token is required"}), 400

    student_room = _parse_room_number(student.room_number)
    if student_room is None:
        return jsonify({"error": "Student room number is invalid."}), 400

    active_batch = LaundryBatch.query.filter(
        LaundryBatch.student_id == student.id,
        LaundryBatch.status.notin_(['pickedUp', 'cancelled'])
    ).order_by(LaundryBatch.created_at.desc()).first()

    existing_student = Student.query.filter_by(token=token).first()
    if existing_student and existing_student.id != id:
        return jsonify({"error": "Token already assigned to another student"}), 400

    _, conflict_error = _resolve_batch_token_conflict(student, token, active_batch)
    if conflict_error:
        return jsonify({"error": conflict_error}), 400

    student.token = token

    created_batch = None
    now = datetime.now()

    if active_batch:
        # Keep active workflow alive and ensure token consistency.
        active_batch.token = token
        if active_batch.status in ('pending', 'booked'):
            can_generate, reason = _can_generate_token_for_batch(active_batch)
            if not can_generate:
                return jsonify({"error": reason}), 400
            active_batch.status = 'collected'
            active_batch.collected_at = now
            _create_notification(student.id, active_batch.id, "collected")
            _upsert_daily_detail(student.id, active_batch.id, "collected", student_room)
        _sync_laundry_record_from_batch(active_batch)
    else:
        created_batch = LaundryBatch(
            student_id=student.id,
            token=token,
            status='collected',
            notes='Submitted by student token claim',
            collected_at=now
        )
        db.session.add(created_batch)
        db.session.flush()
        _sync_laundry_record_from_batch(created_batch)
        _create_notification(student.id, created_batch.id, "collected")
        _upsert_daily_detail(student.id, created_batch.id, "collected", student_room)

    db.session.commit()
    payload = student_schema.dump(student)
    if created_batch:
        payload["batchId"] = created_batch.id
    return jsonify(payload), 200

@app.route('/api/students/by-token/<token>', methods=['GET'])
def get_student_by_token(token):
    student = Student.query.filter_by(token=token).first_or_404()
    return jsonify(student_schema.dump(student))

# Removed manual student login (api_student_login deleted)

@app.route('/api/students/<int:id>', methods=['PATCH'])
def update_student(id):
    settings = SystemSettings.query.first()
    if not settings.edit_window_open:
        return jsonify({"error": "Profile editing is currently closed by staff."}), 403
    
    student = Student.query.get_or_404(id)
    data = request.json
    
    if 'name' in data: student.name = data['name']
    if 'regNo' in data: student.reg_no = data['regNo']
    if 'roomNumber' in data:
        room_number = str(data['roomNumber']).strip()
        floor = _derive_floor_from_room(room_number)
        if floor is None:
            return jsonify({"error": "Valid room number is required to derive floor"}), 400
        student.room_number = room_number
        student.floor = floor
    elif 'floor' in data:
        student.floor = data['floor']
    if 'phoneNumber' in data: student.phone_number = data['phoneNumber']
    
    db.session.commit()
    return jsonify(student_schema.dump(student))

# --- Routes: Batches ---
@app.route('/api/batches', methods=['GET'])
def list_batches():
    _process_missed_bookings()
    status = request.args.get('status')
    student_id = request.args.get('studentId')
    query = LaundryBatch.query
    if status:
        query = query.filter_by(status=status)
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    batches = query.order_by(LaundryBatch.created_at).all()
    students = [batch.student for batch in batches if batch.student]
    if students:
        _normalize_students(students)
    return jsonify(batches_schema.dump(batches))

@app.route('/api/batches', methods=['POST'])
def create_batch():
    data = request.json or {}
    student_id = data.get('studentId')
    batch_token = data.get('token')
    
    if not batch_token:
        return jsonify({"error": "Token number is required"}), 400
    
    # Check if token number already exists
    existing_batch = LaundryBatch.query.filter_by(token=batch_token).first()
    if existing_batch:
        return jsonify({"error": "Token number already in use"}), 400
    
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_room = _parse_room_number(student.room_number)
    if student_room is None:
        return jsonify({"error": "Student room number is invalid."}), 400

    
    new_batch = LaundryBatch(
        student_id=student.id,
        token=batch_token,
        notes=data.get('notes'),
        status='collected',
        collected_at=datetime.now()
    )
    db.session.add(new_batch)
    db.session.flush()
    _sync_laundry_record_from_batch(new_batch)
    _upsert_daily_detail(student.id, new_batch.id, "collected", student_room, notes=data.get('notes'))
    _create_notification(student.id, new_batch.id, "collected")
    db.session.commit()
    return jsonify(batch_schema.dump(new_batch)), 201

@app.route('/api/batches/by-token/<token>', methods=['GET'])
def get_batch_by_token(token):
    batch = LaundryBatch.query.filter_by(token=token).first_or_404()
    if batch.status == 'pickedUp':
        return jsonify({"error": "Token not found"}), 404
    return jsonify(batch_schema.dump(batch))

@app.route('/api/batches/<int:id>', methods=['GET'])
def get_batch(id):
    batch = LaundryBatch.query.get_or_404(id)
    return jsonify(batch_schema.dump(batch))

@app.route('/api/token/resolve/<token>', methods=['GET'])
def resolve_token(token):
    batch = LaundryBatch.query.filter_by(token=token).first()
    if batch and batch.status != 'pickedUp':
        return jsonify({"type": "batch", "batch": batch_schema.dump(batch)}), 200

    student = Student.query.filter_by(token=token).first()
    if student:
        return jsonify({"type": "student", "student": student_schema.dump(student)}), 200

    invite = StudentInvite.query.filter_by(token=token).first()
    if invite and not invite.used_at:
        return jsonify({"type": "invite", "invite": invite_schema.dump(invite)}), 200

    return jsonify({"error": "Token not found"}), 404

@app.route('/api/batches/create-by-token', methods=['POST'])
def create_batch_by_token():
    """Create a new laundry batch by student token (old endpoint - kept for compatibility)"""
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"error": "Token is required"}), 400
    
    # Find student by token
    student = Student.query.filter_by(token=token).first()
    if not student:
        return jsonify({"error": "Student token not found"}), 404
    
    # Create batch token (unique identifier for this batch)
    while True:
        batch_token = f"BATCH{random.randint(100000, 999999)}"
        if not LaundryBatch.query.filter_by(token=batch_token).first():
            break
    
    # Create new batch with status 'pending'
    batch = LaundryBatch(
        student_id=student.id,
        token=batch_token,
        status='pending'
    )
    db.session.add(batch)
    db.session.flush()
    _sync_laundry_record_from_batch(batch)
    db.session.commit()
    
    # Return batch with student data
    result = batch_schema.dump(batch)
    return jsonify(result), 201

@app.route('/api/bookings', methods=['POST'])
def create_booking():
    _process_missed_bookings()
    data = request.json or {}
    student_id = data.get('studentId')
    date_val = data.get('date')
    time_slot = data.get('timeSlot')

    if not student_id or not date_val or not time_slot:
        return jsonify({"error": "Student ID, date, and timeSlot are required"}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    if time_slot not in AVAILABLE_SLOTS:
        return jsonify({"error": "Invalid time slot"}), 400

    # Validate booking date and time (cannot book past slots)
    try:
        booking_date = datetime.strptime(date_val, '%Y-%m-%d')
        today = datetime.now().date()
        booking_date_only = booking_date.date()
        
        # Reject if date is in the past
        if booking_date_only < today:
            return jsonify({"error": "Cannot book slots in the past"}), 400
        
        # If booking is for today, check if slot has passed
        if booking_date_only == today:
            # Extract slot end time
            slot_end_str = time_slot.split(' - ')[1]  # e.g., "09:00"
            slot_end_time = datetime.strptime(slot_end_str, '%H:%M').time()
            current_time = datetime.now().time()
            
            # Reject if slot has already ended
            if current_time > slot_end_time:
                return jsonify({"error": "This slot has already passed"}), 400
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # Ensure max 25
    current_bookings = LaundryBatch.query.filter_by(scheduled_date=date_val, time_slot=time_slot).count()
    if current_bookings >= MAX_PER_SLOT:
        return jsonify({"error": "This slot is full"}), 400

    # Prevent multiple ACTIVE laundry batches (bookings are allowed)
    active = LaundryBatch.query.filter(
        LaundryBatch.student_id == student.id,
        LaundryBatch.status.in_(["booked", "pending", "collected", "washing", "washed"])
    ).first()

    if active:
        return jsonify({"error": "You already have an active booking. Please complete your current request first."}), 400

    # Enforce monthly limit
    try:
        booking_date = datetime.strptime(date_val, '%Y-%m-%d')
        month_prefix = booking_date.strftime('%Y-%m')
        monthly_count = LaundryBatch.query.filter(
            LaundryBatch.student_id == student.id,
            LaundryBatch.scheduled_date.like(f"{month_prefix}-%")
        ).count()
        if monthly_count >= MONTHLY_SLOT_LIMIT:
            return jsonify({"error": f"You have reached your limit of {MONTHLY_SLOT_LIMIT} laundry slots for this month."}), 400
    except Exception:
        return jsonify({"error": "Invalid date format"}), 400

    batch = LaundryBatch(
        student_id=student.id,
        token=f"BOOK-{date_val}-{time_slot}-{student.id}",
        status='booked',
        scheduled_date=date_val,
        time_slot=time_slot
    )
    db.session.add(batch)
    db.session.flush()
    _create_notification(student.id, batch.id, "booked")
    db.session.commit()
    
    return jsonify(batch_schema.dump(batch)), 201

@app.route('/api/batches/create-by-own-token', methods=['POST'])
def create_batch_by_own_token():
    """Create a new laundry batch when student submits with their own token"""
    data = request.json or {}
    student_id = data.get('studentId')
    token = str(data.get('token', '')).strip()

    if not student_id or not token:
        return jsonify({"error": "Student ID and token are required"}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_room = _parse_room_number(student.room_number)
    if student_room is None:
        return jsonify({"error": "Student room number is invalid."}), 400

    active_batch = LaundryBatch.query.filter(
        LaundryBatch.student_id == student.id,
        LaundryBatch.status.notin_(['pickedUp', 'cancelled'])
    ).order_by(LaundryBatch.created_at.desc()).first()

    existing_student = Student.query.filter_by(token=token).first()
    if existing_student and existing_student.id != student.id:
        return jsonify({"error": "Token already assigned to another student"}), 400

    _, conflict_error = _resolve_batch_token_conflict(student, token, active_batch)
    if conflict_error:
        return jsonify({"error": conflict_error}), 400

    student.token = token
    now = datetime.now()

    if active_batch:
        active_batch.token = token
        if active_batch.status in ('pending', 'booked'):
            can_generate, reason = _can_generate_token_for_batch(active_batch)
            if not can_generate:
                return jsonify({"error": reason}), 400
            active_batch.status = 'collected'
            active_batch.collected_at = now
            _create_notification(student.id, active_batch.id, "collected")
            _upsert_daily_detail(student.id, active_batch.id, "collected", student_room)
        _sync_laundry_record_from_batch(active_batch)
        db.session.commit()
        return jsonify(batch_schema.dump(active_batch)), 200

    batch = LaundryBatch(
        student_id=student.id,
        token=token,
        status='collected',
        notes='Submitted by student token claim',
        collected_at=now
    )
    db.session.add(batch)
    db.session.flush()
    _sync_laundry_record_from_batch(batch)
    _create_notification(student.id, batch.id, "collected")
    _upsert_daily_detail(student.id, batch.id, "collected", student_room)
    db.session.commit()
    return jsonify(batch_schema.dump(batch)), 201

@app.route('/api/batches/<int:id>/status', methods=['PATCH'])
def update_batch_status(id):
    batch = LaundryBatch.query.get_or_404(id)
    data = request.json or {}
    new_status = str(data.get('status', '')).strip()
    override = data.get('override', False)
    auto_reset = bool(data.get('autoResetToCollected', False))

    if new_status not in VALID_STATUSES:
        return jsonify({"error": f"Invalid status. Valid statuses: {', '.join(VALID_STATUSES)}"}), 400

    if new_status == "collected" and not override:
        student_room = _parse_room_number(batch.student.room_number)
        if student_room is None:
            return jsonify({"error": "Student room number is invalid."}), 400

    now = datetime.now()
    batch.status = new_status
    if new_status == "collected": batch.collected_at = now
    if new_status == "washing": pass
    if new_status == "washed": batch.washed_at = now
    if new_status == "pickedUp":
        batch.picked_up_at = now
        if auto_reset:
            batch.status = "collected"
            batch.collected_at = now
            batch.washed_at = None
            batch.picked_up_at = None
        else:
            _detach_token_from_batch_student(batch)
    
    _create_notification(batch.student_id, batch.id, new_status)
    student_room = _parse_room_number(batch.student.room_number) or 0
    _upsert_daily_detail(batch.student_id, batch.id, new_status, student_room)
    if new_status == "pickedUp" and not auto_reset:
        _clear_daily_detail(batch.student_id)
        _archive_lost_found_items_for_batch(batch)
    _sync_laundry_record_from_batch(batch)
    db.session.commit()
    return jsonify(batch_schema.dump(batch))

# --- Routes: Schedules ---
@app.route('/api/schedules', methods=['GET'])
def list_schedules():
    schedules = RoomSchedule.query.all()
    return jsonify(schedules_schema.dump(schedules))

@app.route('/api/schedules/by-date', methods=['GET'])
def get_schedule_by_date():
    date = request.args.get('date')
    if not date:
        return jsonify({"error": "date query param is required"}), 400
    schedules = RoomSchedule.query.filter_by(date=date).all()
    return jsonify(schedules_schema.dump(schedules))

@app.route('/api/schedule/by-date', methods=['GET'])
def get_schedule_by_date_alias():
    return get_schedule_by_date()

@app.route('/api/schedules/today', methods=['GET'])
def get_today_schedule():
    today = _today_str()
    schedules = RoomSchedule.query.filter_by(date=today).all()
    return jsonify(schedules_schema.dump(schedules))

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    data = request.json or {}
    date_value = data.get('date')
    room_start = data.get('roomStart')
    room_end = data.get('roomEnd')

    if not date_value or room_start is None or room_end is None:
        return jsonify({"error": "date, roomStart and roomEnd are required"}), 400

    try:
        room_start = int(room_start)
        room_end = int(room_end)
    except (ValueError, TypeError):
        return jsonify({"error": "roomStart and roomEnd must be numbers"}), 400

    if room_start > room_end:
        return jsonify({"error": "roomStart cannot be greater than roomEnd"}), 400

    existing = RoomSchedule.query.filter_by(
        date=date_value,
        room_start=room_start,
        room_end=room_end
    ).first()
    if existing:
        return jsonify(schedule_schema.dump(existing)), 200

    new_schedule = RoomSchedule(
        date=date_value,
        room_start=room_start,
        room_end=room_end
    )
    db.session.add(new_schedule)
    db.session.commit()
    return jsonify(schedule_schema.dump(new_schedule)), 201

@app.route('/api/schedules/<int:id>', methods=['DELETE'])
def delete_schedule(id):
    schedule = RoomSchedule.query.get_or_404(id)
    db.session.delete(schedule)
    db.session.commit()
    return '', 204

@app.route('/api/schedules/month/<month_key>', methods=['DELETE'])
def delete_schedule_month(month_key):
    if not re.match(r'^\d{4}-\d{2}$', str(month_key or '')):
        return jsonify({"error": "month_key must be YYYY-MM"}), 400
    deleted = RoomSchedule.query.filter(RoomSchedule.date.like(f"{month_key}-%")).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True, "deleted": deleted}), 200

# --- Routes: Schedule OCR Upload ---
@app.route('/api/schedules/upload-image', methods=['POST'])
def upload_schedule_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        file_bytes = file.read()
        result = process_schedule_image(file_bytes, file.filename)
        
        if not result.get('success', False):
            return jsonify({"error": result.get('error', 'Failed to process image')}), 400

        year, month_num = _extract_month_year(result.get('month', ''))
        schedules_created = []
        for schedule in result.get('schedules', []):
            date_str = f"{year}-{month_num:02d}-{int(schedule['date']):02d}"
            schedules_created.append({
                'date': date_str,
                'roomStart': int(schedule['room_start']),
                'roomEnd': int(schedule['room_end'])
            })
        
        return jsonify({
            'success': True,
            'month': result['month'],
            'schedules': schedules_created,
            'holidays': result.get('holidays', [])
        }), 201
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 400

@app.route('/api/schedules/upload-pdf', methods=['POST'])
def upload_schedule_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        file_bytes = file.read()
        result = process_schedule_pdf(file_bytes)
        
        if not result.get('success', False):
            return jsonify({"error": result.get('error', 'Failed to process PDF')}), 400

        year, month_num = _extract_month_year(result.get('month', ''))
        schedules_created = []
        for schedule in result.get('schedules', []):
            date_str = f"{year}-{month_num:02d}-{int(schedule['date']):02d}"
            schedules_created.append({
                'date': date_str,
                'roomStart': int(schedule['room_start']),
                'roomEnd': int(schedule['room_end'])
            })
        
        return jsonify({
            'success': True,
            'month': result['month'],
            'schedules': schedules_created,
            'holidays': result.get('holidays', [])
        }), 201
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 400

@app.route('/api/schedules/replace-month', methods=['POST'])
def replace_month_schedules():
    data = request.json or {}
    schedules = data.get('schedules') or []
    holidays = data.get('holidays') or []
    if not isinstance(schedules, list) or len(schedules) == 0:
        return jsonify({"error": "schedules must be a non-empty list"}), 400

    first_date = schedules[0].get('date')
    try:
        month_prefix = datetime.strptime(first_date, '%Y-%m-%d').strftime('%Y-%m')
    except Exception:
        return jsonify({"error": "Invalid schedule date format"}), 400

    incoming = {}
    for row in schedules:
        date_value = row.get('date')
        room_start = row.get('roomStart')
        room_end = row.get('roomEnd')
        if not date_value or room_start is None or room_end is None:
            continue
        try:
            room_start = int(room_start)
            room_end = int(room_end)
            if room_start > room_end:
                continue
            datetime.strptime(date_value, '%Y-%m-%d')
        except Exception:
            continue
        incoming[(date_value, room_start, room_end)] = True

    if not incoming:
        return jsonify({"error": "No valid schedules to save"}), 400

    try:
        to_delete = RoomSchedule.query.filter(RoomSchedule.date.like(f"{month_prefix}-%")).all()
        deleted_count = len(to_delete)
        for row in to_delete:
            db.session.delete(row)

        created = 0
        for date_value, room_start, room_end in incoming.keys():
            db.session.add(RoomSchedule(date=date_value, room_start=room_start, room_end=room_end))
            created += 1

        clean_holidays = _sanitize_holidays(holidays, first_date)

        db.session.commit()
        return jsonify({"success": True, "deleted": deleted_count, "created": created, "holidays": clean_holidays}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route('/api/schedules/holidays-map', methods=['GET'])
def get_schedule_holidays_map():
    # Kept for frontend compatibility. Holidays are inferred client-side with OCR/fallback logic.
    return jsonify({"holidayMap": {}}), 200

@app.route('/api/schedules/current-month', methods=['GET'])
def get_current_month_schedule():
    try:
        all_schedules = RoomSchedule.query.all()
        if not all_schedules:
            return jsonify({
                'success': False,
                'message': 'No schedule uploaded yet'
            }), 404

        parsed = []
        for sch in all_schedules:
            try:
                parsed.append((datetime.strptime(sch.date, '%Y-%m-%d'), sch))
            except ValueError:
                continue

        if not parsed:
            return jsonify({
                'success': False,
                'message': 'No valid schedule dates found'
            }), 404

        latest_date = max([d for d, _ in parsed])
        target_year = latest_date.year
        target_month = latest_date.month

        month_schedules = [
            sch for dt_obj, sch in parsed
            if dt_obj.year == target_year and dt_obj.month == target_month
        ]

        schedules_by_date = {}
        seen = set()
        for sch in month_schedules:
            unique_key = (sch.date, sch.room_start, sch.room_end)
            if unique_key in seen:
                continue
            seen.add(unique_key)
            if sch.date not in schedules_by_date:
                schedules_by_date[sch.date] = []
            schedules_by_date[sch.date].append({
                'id': sch.id,
                'roomStart': sch.room_start,
                'roomEnd': sch.room_end
            })

        return jsonify({
            'success': True,
            'month': latest_date.strftime('%B %Y'),
            'schedulesByDate': schedules_by_date
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- Routes: Settings ---
@app.route('/api/settings', methods=['GET'])
def get_settings():
    settings = SystemSettings.query.first()
    return jsonify(settings_schema.dump(settings))

@app.route('/api/settings', methods=['PATCH'])
def update_settings():
    settings = SystemSettings.query.first()
    data = request.json
    if 'editWindowOpen' in data:
        settings.edit_window_open = data['editWindowOpen']
    db.session.commit()
    return jsonify(settings_schema.dump(settings))

def _serialize_bucket_request(req, viewer_student_id=None):
    my_row = None
    if viewer_student_id is not None:
        my_row = BucketRequestRecipient.query.filter_by(
            request_id=req.id,
            recipient_student_id=viewer_student_id
        ).first()

    return {
        "id": req.id,
        "clothesCount": req.clothes_count,
        "status": req.status,
        "createdAt": req.created_at.isoformat() if req.created_at else None,
        "acceptedAt": req.accepted_at.isoformat() if req.accepted_at else None,
        "requester": student_schema.dump(req.requester) if req.requester else None,
        "acceptedBy": student_schema.dump(req.accepted_by) if req.accepted_by else None,
        "myResponse": my_row.response if my_row else None,
        "canRespond": bool(req.status == 'open' and my_row and my_row.response == 'pending')
    }

@app.route('/api/bucket/eligibility', methods=['GET'])
def bucket_eligibility():
    student_id = request.args.get('studentId', type=int)
    if not student_id:
        return jsonify({"error": "studentId is required"}), 400

    Student.query.get_or_404(student_id)
    booking_count = _student_booking_count_current_month(student_id)
    incoming_open_count = BucketRequestRecipient.query.join(
        BucketRequest, BucketRequestRecipient.request_id == BucketRequest.id
    ).filter(
        BucketRequestRecipient.recipient_student_id == student_id,
        BucketRequest.status == 'open',
        BucketRequestRecipient.response == 'pending'
    ).count()
    return jsonify({
        "eligible": booking_count >= MONTHLY_SLOT_LIMIT,
        "bookingCount": booking_count,
        "requiredCount": MONTHLY_SLOT_LIMIT,
        "hasIncomingRequests": incoming_open_count > 0
    })

@app.route('/api/bucket/requests', methods=['GET'])
def list_bucket_requests():
    student_id = request.args.get('studentId', type=int)
    if not student_id:
        return jsonify({"error": "studentId is required"}), 400
    Student.query.get_or_404(student_id)

    recipient_rows = BucketRequestRecipient.query.filter_by(recipient_student_id=student_id).all()
    recipient_request_ids = [r.request_id for r in recipient_rows]

    relevant = BucketRequest.query.filter(
        (BucketRequest.requester_student_id == student_id) |
        (BucketRequest.accepted_by_student_id == student_id) |
        (BucketRequest.id.in_(recipient_request_ids))
    ).order_by(BucketRequest.created_at.desc()).all()

    visible = []
    for req in relevant:
        if req.status == 'accepted' and req.requester_student_id != student_id and req.accepted_by_student_id != student_id:
            continue
        visible.append(_serialize_bucket_request(req, student_id))
    return jsonify(visible)

@app.route('/api/bucket/requests', methods=['POST'])
def create_bucket_request():
    data = request.json or {}
    student_id = data.get('studentId')
    clothes_count = data.get('clothesCount')

    if not student_id:
        return jsonify({"error": "studentId is required"}), 400
    try:
        clothes_count = int(clothes_count)
    except Exception:
        return jsonify({"error": "clothesCount must be a number"}), 400
    if clothes_count < 1 or clothes_count > 5:
        return jsonify({"error": "Number of clothes must be between 1 and 5"}), 400

    student = Student.query.get_or_404(int(student_id))
    if not _student_has_bucket_access(student.id):
        return jsonify({"error": "Bucket request is available only after 4 bookings are exhausted."}), 403

    existing_open = BucketRequest.query.filter_by(requester_student_id=student.id, status='open').first()
    if existing_open:
        return jsonify({"error": "You already have an open bucket request."}), 400

    candidates = [s for s in _students_with_slots_next_7_days() if s.id != student.id]
    if not candidates:
        return jsonify({"error": "No students found with slots in the next 7 days."}), 400

    req = BucketRequest(
        requester_student_id=student.id,
        clothes_count=clothes_count,
        status='open'
    )
    db.session.add(req)
    db.session.flush()

    for cand in candidates:
        db.session.add(BucketRequestRecipient(
            request_id=req.id,
            recipient_student_id=cand.id,
            response='pending'
        ))
        db.session.add(Notification(
            student_id=cand.id,
            status='bucket',
            message=f"Urgent bucket request from {student.name}: {clothes_count} clothes. Please accept or decline."
        ))

    db.session.commit()
    return jsonify(_serialize_bucket_request(req, student.id)), 201

@app.route('/api/bucket/requests/<int:request_id>/respond', methods=['POST'])
def respond_bucket_request(request_id):
    data = request.json or {}
    student_id = data.get('studentId')
    action = str(data.get('action', '')).strip().lower()

    if not student_id:
        return jsonify({"error": "studentId is required"}), 400
    if action not in ['accept', 'decline']:
        return jsonify({"error": "action must be accept or decline"}), 400

    student = Student.query.get_or_404(int(student_id))
    req = BucketRequest.query.get_or_404(request_id)

    recipient_row = BucketRequestRecipient.query.filter_by(
        request_id=req.id,
        recipient_student_id=student.id
    ).first()
    if not recipient_row:
        return jsonify({"error": "You are not eligible to respond to this request."}), 403
    if req.status != 'open':
        return jsonify({"error": "This request is no longer open."}), 400
    if recipient_row.response != 'pending':
        return jsonify({"error": "You have already responded to this request."}), 400

    now = datetime.now()
    if action == 'decline':
        recipient_row.response = 'declined'
        recipient_row.responded_at = now
        db.session.commit()
        return jsonify(_serialize_bucket_request(req, student.id)), 200

    req.status = 'accepted'
    req.accepted_by_student_id = student.id
    req.accepted_at = now
    recipient_row.response = 'accepted'
    recipient_row.responded_at = now

    others = BucketRequestRecipient.query.filter(
        BucketRequestRecipient.request_id == req.id,
        BucketRequestRecipient.id != recipient_row.id,
        BucketRequestRecipient.response == 'pending'
    ).all()
    for row in others:
        row.response = 'declined'
        row.responded_at = now

    requester = Student.query.get(req.requester_student_id)
    if requester:
        db.session.add(Notification(
            student_id=requester.id,
            status='bucket',
            message=f"{student.name} accepted your bucket request."
        ))
    db.session.add(Notification(
        student_id=student.id,
        status='bucket',
        message=f"You accepted {requester.name if requester else 'a student'}'s bucket request."
    ))

    db.session.commit()
    return jsonify(_serialize_bucket_request(req, student.id)), 200

@app.route('/api/notifications', methods=['GET'])
def list_notifications():
    student_id = request.args.get('studentId')
    query = Notification.query
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    notifications = query.order_by(Notification.created_at.desc()).all()
    return jsonify(notifications_schema.dump(notifications))

@app.route('/api/notifications', methods=['POST'])
def create_notification():
    data = request.json
    student_id = data.get('studentId')
    batch_id = data.get('batchId')
    status = data.get('status')
    message = data.get('message')
    
    if not all([student_id, status, message]):
        return jsonify({"error": "studentId, status, and message are required"}), 400
    
    notification = Notification(
        student_id=student_id,
        batch_id=batch_id,
        status=status,
        message=message
    )
    db.session.add(notification)
    db.session.commit()
    return jsonify(notification_schema.dump(notification)), 201

@app.route('/api/complaints', methods=['GET'])
def list_complaints():
    student_id = request.args.get('studentId')
    status = request.args.get('status')
    query = Complaint.query
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    if status:
        query = query.filter_by(status=str(status))
    rows = query.order_by(Complaint.created_at.desc()).all()
    return jsonify(complaints_schema.dump(rows))

@app.route('/api/complaints', methods=['POST'])
def create_complaint():
    data = request.json or {}
    student_id = data.get('studentId')
    subject = str(data.get('subject', '')).strip()
    message = str(data.get('message', '')).strip()
    if not student_id or not subject or not message:
        return jsonify({"error": "studentId, subject and message are required"}), 400
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404
    row = Complaint(student_id=student.id, subject=subject, message=message, status='open')
    db.session.add(row)
    db.session.commit()
    return jsonify(complaint_schema.dump(row)), 201

@app.route('/api/complaints/<int:id>', methods=['PATCH'])
def update_complaint(id):
    row = Complaint.query.get_or_404(id)
    data = request.json or {}
    next_status = str(data.get('status', '')).strip().lower()
    if next_status not in ('open', 'resolved'):
        return jsonify({"error": "status must be open or resolved"}), 400
    row.status = next_status
    row.resolved_at = datetime.now() if next_status == 'resolved' else None
    db.session.commit()
    return jsonify(complaint_schema.dump(row)), 200

@app.route('/api/laundry', methods=['GET'])
def list_laundry_records():
    block = request.args.get('block')
    status = request.args.get('status')
    query = LaundryBatch.query
    if status:
        query = query.filter_by(status=status)
    if block:
        query = query.join(Student).filter(Student.floor == block)
    batches = query.order_by(LaundryBatch.created_at.desc()).all()
    records = []
    for batch in batches:
        records.append({
            "id": batch.id,
            "token": batch.token,
            "name": batch.student.name if batch.student else "Unknown",
            "block": batch.student.floor if batch.student else "-",
            "room_number": batch.student.room_number if batch.student else "-",
            "date_given": batch.created_at.strftime("%Y-%m-%d") if batch.created_at else "",
            "status": batch.status,
        })
    return jsonify(records)

@app.route('/extract-token', methods=['POST'])
def post_extract_token():
    image = request.files.get('image')
    try:
        token_number, details = _extract_token_from_image_file(image)
        return jsonify({
            "tokenNumber": token_number,
            "token_number": token_number,
            "details": details,
        }), 200
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception:
        return jsonify({"error": "Failed to process image"}), 500

@app.route('/api/token-generation', methods=['POST'])
def generate_student_token_from_ocr():
    image = request.files.get('image')
    form = request.form
    manual_token = str(form.get('manualToken', '')).strip()

    try:
        student_id = _parse_int_field(form.get('studentId'), 'studentId')
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    if manual_token:
        try:
            token_number = _parse_int_field(manual_token, 'manualToken')
        except ValueError as error:
            return jsonify({"error": str(error), "allowManualEntry": True}), 400
        details = {
            "rawText": manual_token,
            "matchedText": manual_token,
            "confidence": "manual",
            "candidates": [token_number],
            "source": "manual",
        }
    else:
        try:
            token_number, details = _extract_token_from_image_file(image)
        except ValueError as error:
            payload = {"error": str(error)}
            if _is_manual_token_fallback_error(str(error)):
                payload["allowManualEntry"] = True
            return jsonify(payload), 422 if payload.get("allowManualEntry") else 400
        except Exception:
            return jsonify({"error": "Failed to process image"}), 500

    token = str(token_number)
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_room = _parse_room_number(student.room_number)
    if student_room is None:
        return jsonify({"error": "Student room number is invalid."}), 400

    existing_active_batch = _get_active_batch_for_student(student.id)
    can_generate, reason = _can_generate_token_for_batch(existing_active_batch)
    if not can_generate:
        return jsonify({"error": reason}), 409

    active_batch = existing_active_batch

    existing_student = Student.query.filter_by(token=token).first()
    if existing_student and existing_student.id != student.id:
        return jsonify({"error": "Token already assigned to another student"}), 400

    _, conflict_error = _resolve_batch_token_conflict(student, token, active_batch)
    if conflict_error:
        return jsonify({"error": conflict_error}), 400

    student.token = token
    now = datetime.now()

    if active_batch:
        active_batch.token = token
        if active_batch.status in ('pending', 'booked'):
            active_batch.status = 'collected'
            active_batch.collected_at = now
            _create_notification(student.id, active_batch.id, "collected")
            _upsert_daily_detail(student.id, active_batch.id, "collected", student_room)
        _sync_laundry_record_from_batch(active_batch)
        _ensure_lost_found_tracking(student, active_batch, image)
        db.session.commit()
        return _token_generation_response(
            "Token extracted and linked to active laundry batch",
            token_number,
            details,
            active_batch,
            200,
        )

    batch = LaundryBatch(
        student_id=student.id,
        token=token,
        status='collected',
        notes='Submitted via OCR token generation',
        collected_at=now
    )
    db.session.add(batch)
    db.session.flush()
    _sync_laundry_record_from_batch(batch)
    _create_notification(student.id, batch.id, "collected")
    _upsert_daily_detail(student.id, batch.id, "collected", student_room)
    _ensure_lost_found_tracking(student, batch, image)
    db.session.commit()
    return _token_generation_response(
        "Token extracted and new laundry batch created",
        token_number,
        details,
        batch,
        201,
    )

@app.route('/api/token-generation/current', methods=['GET'])
def get_current_token_generation_state():
    student_id = request.args.get('studentId')
    try:
        student_id = _parse_int_field(student_id, 'studentId')
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    active_batch = _get_active_batch_for_student(student.id)
    can_generate, lock_reason = _can_generate_token_for_batch(active_batch)
    token_number = None
    if active_batch and _has_generated_token(active_batch) and str(active_batch.token or '').strip().isdigit():
        token_number = int(str(active_batch.token).strip())

    record = LaundryRecord.query.filter_by(token_number=token_number).first() if token_number is not None else None
    item = _get_tracked_lost_found_item(student_id=student.id, token_number=token_number) if token_number is not None else None

    return jsonify({
        "hasActiveLaundry": bool(active_batch),
        "canGenerate": can_generate,
        "lockReason": lock_reason,
        "bookingNo": _get_booking_number(active_batch),
        "batch": batch_schema.dump(active_batch) if active_batch else None,
        "record": _serialize_laundry_record(record),
        "currentLaundryItem": _serialize_lost_found_item(item),
    }), 200

@app.route('/laundry', methods=['POST'])
def create_or_update_laundry_record():
    data = request.get_json(silent=True) or {}
    try:
        record, created = _upsert_laundry_record(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except LookupError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify({
        "message": "Laundry record created" if created else "Laundry record updated",
        "record": _serialize_laundry_record(record),
    }), 201 if created else 200

@app.route('/lost-found/report', methods=['POST'])
def report_lost_item():
    form = request.form
    try:
        student_id = _parse_int_field(form.get('studentId'), 'studentId')
        token_number, _ = _extract_token_from_image_file(request.files.get('image'))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        return jsonify({"error": "Failed to process image"}), 500

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    eligible_batch = _get_student_loss_eligible_batch(student.id)
    if not eligible_batch:
        return jsonify({"error": "You can report a bag as lost only after it has been submitted or is in washing/ready status"}), 403
    if str(eligible_batch.token or '').strip() != str(token_number):
        return jsonify({"error": "The scanned tag does not match your active laundry bag"}), 403
    existing_open_report = LostFoundItem.query.filter_by(
        token_number=token_number,
        student_id=student.id,
        status='lost'
    ).first()
    if existing_open_report:
        return jsonify({
            "message": "An active lost report already exists for this token",
            "item": _serialize_lost_found_item(existing_open_report),
        }), 200

    image = request.files.get('image')
    if hasattr(image, 'stream'):
        image.stream.seek(0)
    filename, _ = save_lost_found_image(image, LOST_FOUND_UPLOADS_DIR)
    item = LostFoundItem(
        token_number=token_number,
        student_id=student.id,
        image_url=_build_lost_found_image_url(filename),
        description=(form.get('description') or '').strip() or None,
        status='lost',
        created_by='student',
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({
        "message": "Lost item reported",
        "item": _serialize_lost_found_item(item),
    }), 201

@app.route('/lost-found/found', methods=['POST'])
def mark_item_found():
    form = request.form
    try:
        token_number, _ = _extract_token_from_image_file(request.files.get('image'))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        return jsonify({"error": "Failed to process image"}), 500

    archive = _coerce_archive_flag(form.get('archive'))
    description = (form.get('description') or '').strip() or None
    image = request.files.get('image')
    if hasattr(image, 'stream'):
        image.stream.seek(0)
    filename, _ = save_lost_found_image(image, LOST_FOUND_UPLOADS_DIR)
    image_url = _build_lost_found_image_url(filename)

    match_result = mark_lost_item_found(
        token_number=token_number,
        new_image_url=image_url,
        description=description,
        archive=archive,
    )

    if match_result:
        old_image_path = _resolve_storage_path_from_url(match_result["old_image_url"])
        delete_image_if_exists(old_image_path)
        db.session.commit()
        item = match_result["item"]
        return jsonify({
            "message": "Lost item matched and marked as found",
            "matched": True,
            "item": _serialize_lost_found_item(item),
        }), 200

    item = LostFoundItem(
        token_number=token_number,
        image_url=image_url,
        description=description,
        status='found',
        created_by='staff',
        archived_at=datetime.utcnow() if archive else None,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({
        "message": "Found item recorded",
        "matched": False,
        "item": _serialize_lost_found_item(item),
    }), 201

@app.route('/lost-found', methods=['GET'])
def list_lost_found_items():
    status = (request.args.get('status') or '').strip().lower()
    token_number = request.args.get('tokenNumber')
    created_by = (request.args.get('createdBy') or '').strip().lower()

    query = LostFoundItem.query.filter(LostFoundItem.archived_at.is_(None))
    if status:
        if status not in LOST_FOUND_STATUSES:
            return jsonify({"error": f"status must be one of {', '.join(sorted(LOST_FOUND_STATUSES))}"}), 400
        query = query.filter_by(status=status)
    else:
        query = query.filter(LostFoundItem.status.in_(['lost', 'found']))
    if created_by:
        if created_by not in LOST_FOUND_CREATORS:
            return jsonify({"error": f"createdBy must be one of {', '.join(sorted(LOST_FOUND_CREATORS))}"}), 400
        query = query.filter_by(created_by=created_by)
    if token_number:
        try:
            query = query.filter_by(token_number=_parse_int_field(token_number, 'tokenNumber'))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

    items = query.order_by(LostFoundItem.created_at.desc()).all()
    return jsonify([_serialize_lost_found_item(item) for item in items]), 200

@app.route('/lost-found/<int:item_id>/status', methods=['PATCH'])
def update_lost_found_status(item_id):
    item = LostFoundItem.query.get_or_404(item_id)
    data = request.get_json(silent=True) or {}
    next_status = str(data.get('status', '')).strip().lower()

    if next_status not in {'lost', 'found'}:
        return jsonify({"error": "status must be lost or found"}), 400
    if item.archived_at is not None:
        return jsonify({"error": "This laundry item is already closed"}), 400

    if next_status == 'lost':
        student_id = data.get('studentId')
        try:
            student_id = _parse_int_field(student_id, 'studentId')
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        if item.student_id != student_id:
            return jsonify({"error": "You can only mark your own laundry item as lost"}), 403
        eligible_batch = _get_student_loss_eligible_batch(student_id)
        if not eligible_batch:
            return jsonify({"error": "You can report a bag as lost only while the laundry is active"}), 403
        if str(eligible_batch.token or '').strip() != str(item.token_number):
            return jsonify({"error": "The selected token does not match your active laundry bag"}), 403

    item.status = next_status
    db.session.commit()
    return jsonify({
        "message": f"Item marked as {next_status}",
        "item": _serialize_lost_found_item(item),
    }), 200

@app.route('/api/laundry/<token>', methods=['GET'])
def get_laundry_record(token):
    record = _get_laundry_record_by_token(token)
    if not record:
        return jsonify({"error": "Laundry record not found"}), 404
    return jsonify(record)

@app.route('/api/laundry/<token>/status', methods=['PATCH'])
def update_laundry_record_status(token):
    data = request.json or {}
    status = data.get('status')

    try:
        record = _update_laundry_record_status(token, status)
    except ValueError as error:
        return jsonify({"error": str(error), "validStatuses": VALID_STATUSES}), 400

    if not record:
        return jsonify({"error": "Laundry record not found"}), 404

    return jsonify(record)

@app.route('/api/announcements', methods=['GET'])
def list_announcements():
    _process_missed_bookings()
    student_id = request.args.get('studentId', type=int)
    announcements = _announcement_payload_for_student_query(student_id).all()
    return jsonify(announcements_schema.dump(announcements))

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    data = request.json or {}
    title = (data.get('title') or '').strip()
    message = (data.get('message') or '').strip()
    audience = (data.get('audience') or 'all').strip().lower()
    category = (data.get('category') or 'general').strip().lower()
    target_student_id = data.get('targetStudentId')
    is_urgent = bool(data.get('isUrgent', False))

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not message:
        return jsonify({"error": "Message is required"}), 400
    if audience not in ('all', 'student'):
        return jsonify({"error": "Audience must be all or student"}), 400

    if audience == 'student':
        try:
            target_student_id = _parse_int_field(target_student_id, 'targetStudentId')
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        target_student = Student.query.get(target_student_id)
        if not target_student:
            return jsonify({"error": "Target student not found"}), 404
        if not _student_eligible_for_personal_announcement(target_student_id):
            return jsonify({"error": "Personal messages can be sent only to students in submitted, washing, or ready status."}), 400
        category = 'personal'
        is_urgent = True

    announcement = _create_announcement_record(
        title=title,
        message=message,
        audience=audience,
        target_student_id=target_student_id if audience == 'student' else None,
        category=category,
        is_urgent=is_urgent
    )
    db.session.commit()
    return jsonify(announcement_schema.dump(announcement)), 201

@app.route('/api/announcements/eligible-students', methods=['GET'])
def list_announcement_eligible_students():
    _process_missed_bookings()
    rows = []
    for student in Student.query.order_by(Student.name.asc()).all():
        latest_batch = _latest_batch_for_student(student.id)
        if not latest_batch or latest_batch.status not in PERSONAL_ANNOUNCEMENT_ELIGIBLE_STATUSES:
            continue
        rows.append({
            "id": student.id,
            "name": student.name,
            "regNo": student.reg_no,
            "floor": student.floor,
            "roomNumber": student.room_number,
            "status": latest_batch.status
        })
    return jsonify(rows), 200

@app.route('/api/urgent-alerts', methods=['GET'])
def list_urgent_alerts():
    _process_missed_bookings()
    student_id = request.args.get('studentId', type=int)
    audience = (request.args.get('audience') or '').strip().lower()
    query = Announcement.query.filter(Announcement.is_urgent.is_(True))
    if student_id is not None:
        query = query.filter(
            or_(
                Announcement.audience == 'all',
                and_(Announcement.audience == 'student', Announcement.target_student_id == student_id)
            )
        )
    elif audience == 'staff':
        query = query.filter(Announcement.audience == 'all')
    alerts = query.order_by(Announcement.created_at.desc()).limit(8).all()
    return jsonify(announcements_schema.dump(alerts)), 200

@app.route('/api/announcements/<int:id>', methods=['DELETE'])
def delete_announcement(id):
    announcement = Announcement.query.get_or_404(id)
    db.session.delete(announcement)
    db.session.commit()
    return '', 204

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'False').lower() == 'true')
