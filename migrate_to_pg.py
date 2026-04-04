import os
from app import app, db
from models import Student, LaundryBatch, RoomSchedule, SystemSettings, StudentInvite, Notification, Announcement, Complaint, DailyLaundryDetail
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def migrate():
    # 1. Configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    sqlite_student_uri = 'sqlite:///' + os.path.join(basedir, 'student.db')
    sqlite_daily_uri = 'sqlite:///' + os.path.join(basedir, 'daily.db')
    
    pg_uri = os.environ.get('DATABASE_URL')
    if not pg_uri:
        print("Error: DATABASE_URL not found in environment.")
        return
    
    if pg_uri.startswith("postgres://"):
        pg_uri = pg_uri.replace("postgres://", "postgresql://", 1)

    print(f"Migrating from SQLite to {pg_uri.split('@')[-1] if '@' in pg_uri else 'PostgreSQL'}...")

    # 2. Setup Engines and Sessions
    engine_student = create_engine(sqlite_student_uri)
    SessionStudent = sessionmaker(bind=engine_student)
    session_student = SessionStudent()

    engine_daily = create_engine(sqlite_daily_uri)
    SessionDaily = sessionmaker(bind=engine_daily)
    session_daily = SessionDaily()

    # 3. Initialize PostgreSQL Tables
    # We use the app's db object configured for PG
    app.config['SQLALCHEMY_DATABASE_URI'] = pg_uri
    with app.app_context():
        print("Creating tables in PostgreSQL...")
        db.create_all()

        # 4. Migrate Data
        # Order matters for foreign keys: Student -> Others
        
        # --- Students ---
        print("Migrating Students...")
        students = session_student.execute(db.select(Student)).scalars().all()
        for s in students:
            # Create a new instance to avoid session conflicts
            new_s = Student(
                id=s.id, name=s.name, reg_no=s.reg_no, floor=s.floor,
                room_number=s.room_number, phone_number=s.phone_number,
                token=s.token, created_at=s.created_at, updated_at=s.updated_at
            )
            db.session.merge(new_s)
        db.session.commit()

        # --- RoomSchedules ---
        print("Migrating RoomSchedules...")
        schedules = session_student.execute(db.select(RoomSchedule)).scalars().all()
        for r in schedules:
            new_r = RoomSchedule(
                id=r.id, date=r.date, room_start=r.room_start,
                room_end=r.room_end, created_at=r.created_at
            )
            db.session.merge(new_r)
        
        # --- SystemSettings ---
        print("Migrating SystemSettings...")
        settings = session_student.execute(db.select(SystemSettings)).scalars().all()
        for st in settings:
            new_st = SystemSettings(
                id=st.id, edit_window_open=st.edit_window_open, updated_at=st.updated_at
            )
            db.session.merge(new_st)

        # --- StudentInvites ---
        print("Migrating StudentInvites...")
        invites = session_student.execute(db.select(StudentInvite)).scalars().all()
        for i in invites:
            new_i = StudentInvite(
                id=i.id, token=i.token, used_at=i.used_at,
                used_by_student_id=i.used_by_student_id, created_at=i.created_at
            )
            db.session.merge(new_i)

        # --- Announcements ---
        print("Migrating Announcements...")
        announcements = session_student.execute(db.select(Announcement)).scalars().all()
        for a in announcements:
            new_a = Announcement(
                id=a.id, title=a.title, message=a.message, created_at=a.created_at
            )
            db.session.merge(new_a)
        
        db.session.commit()

        # --- LaundryBatches ---
        print("Migrating LaundryBatches...")
        batches = session_student.execute(db.select(LaundryBatch)).scalars().all()
        for b in batches:
            new_b = LaundryBatch(
                id=b.id, student_id=b.student_id, token=b.token, status=b.status,
                notes=b.notes, collected_at=b.collected_at, washed_at=b.washed_at,
                picked_up_at=b.picked_up_at, created_at=b.created_at, updated_at=b.updated_at
            )
            db.session.merge(new_b)
        db.session.commit()

        # --- Notifications ---
        print("Migrating Notifications...")
        notifications = session_student.execute(db.select(Notification)).scalars().all()
        for n in notifications:
            new_n = Notification(
                id=n.id, student_id=n.student_id, batch_id=n.batch_id,
                status=n.status, message=n.message, read_at=n.read_at, created_at=n.created_at
            )
            db.session.merge(new_n)

        # --- Complaints ---
        print("Migrating Complaints...")
        complaints = session_student.execute(db.select(Complaint)).scalars().all()
        for c in complaints:
            new_c = Complaint(
                id=c.id, student_id=c.student_id, subject=c.subject,
                message=c.message, status=c.status, created_at=c.created_at, resolved_at=c.resolved_at
            )
            db.session.merge(new_c)

        # --- DailyLaundryDetails (From daily.db) ---
        print("Migrating DailyLaundryDetails...")
        details = session_daily.execute(db.select(DailyLaundryDetail)).scalars().all()
        for d in details:
            new_d = DailyLaundryDetail(
                id=d.id, date=d.date, student_id=d.student_id, batch_id=d.batch_id,
                status=d.status, room_number=d.room_number, notes=d.notes, created_at=d.created_at
            )
            db.session.merge(new_d)

        db.session.commit()
        print("Migration completed successfully!")

    session_student.close()
    session_daily.close()

if __name__ == "__main__":
    migrate()
