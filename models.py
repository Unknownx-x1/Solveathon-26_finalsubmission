from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from marshmallow import fields
from datetime import datetime
from sqlalchemy import func

db = SQLAlchemy()
ma = Marshmallow()

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    reg_no = db.Column(db.String, nullable=False, unique=True)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    token = db.Column(db.String, nullable=True, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

class LaundryBatch(db.Model):
    __tablename__ = 'laundry_batches'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    token = db.Column(db.String, nullable=False, unique=True)
    status = db.Column(db.String, nullable=False, default='pending')
    notes = db.Column(db.String)
    scheduled_date = db.Column(db.String, nullable=True) # YYYY-MM-DD
    time_slot = db.Column(db.String, nullable=True) # e.g. "08:00 - 09:00"
    collected_at = db.Column(db.DateTime)
    washed_at = db.Column(db.DateTime)
    picked_up_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    student = db.relationship('Student', backref=db.backref('batches', lazy=True))

class RoomSchedule(db.Model):
    __tablename__ = 'room_schedules'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String, nullable=False)
    room_start = db.Column(db.Integer, nullable=False)
    room_end = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    edit_window_open = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

class StudentInvite(db.Model):
    __tablename__ = 'student_invites'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String, nullable=False, unique=True)
    used_at = db.Column(db.DateTime)
    used_by_student_id = db.Column(db.Integer, db.ForeignKey('students.id'))
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    used_by_student = db.relationship('Student', backref=db.backref('invite', uselist=False))

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String, nullable=False)
    message = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('laundry_batches.id', ondelete='SET NULL'))
    status = db.Column(db.String, nullable=False)
    message = db.Column(db.String, nullable=False)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    student = db.relationship('Student', backref=db.backref('notifications', lazy=True))
    batch = db.relationship('LaundryBatch', backref=db.backref('notifications', lazy=True))

class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    subject = db.Column(db.String, nullable=False)
    message = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default='open')
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    resolved_at = db.Column(db.DateTime)

    student = db.relationship('Student', backref=db.backref('complaints', lazy=True))

class DailyLaundryDetail(db.Model):
    __tablename__ = 'daily_laundry_details'
    __bind_key__ = 'daily'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String, nullable=False)
    student_id = db.Column(db.Integer, nullable=False)
    batch_id = db.Column(db.Integer)
    status = db.Column(db.String, nullable=False)
    room_number = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.String)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

class LaundryRecord(db.Model):
    __tablename__ = 'laundry_records'
    id = db.Column(db.Integer, primary_key=True)
    token_number = db.Column(db.Integer, nullable=False, unique=True, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('laundry_batches.id', ondelete='SET NULL'))
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='SET NULL'))
    student_name = db.Column(db.String)
    reg_no = db.Column(db.String)
    floor = db.Column(db.Integer)
    room_number = db.Column(db.String)
    phone_number = db.Column(db.String)
    clothes_count = db.Column(db.Integer, nullable=False, default=0)
    weight = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String, nullable=False, default='received')
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    student = db.relationship('Student', backref=db.backref('laundry_records', lazy=True))
    batch = db.relationship('LaundryBatch', backref=db.backref('laundry_records', lazy=True))

class LostFoundItem(db.Model):
    __tablename__ = 'lost_found_items'
    id = db.Column(db.Integer, primary_key=True)
    token_number = db.Column(db.Integer, nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='SET NULL'))
    image_url = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    status = db.Column(db.String, nullable=False, default='lost')
    created_by = db.Column(db.String, nullable=False)
    archived_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    student = db.relationship('Student', backref=db.backref('lost_found_items', lazy=True))

# Schemas for serialization
class StudentSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Student
        load_instance = True
        exclude = ('reg_no', 'room_number', 'phone_number', 'created_at', 'updated_at')
    
    regNo = fields.String(attribute='reg_no', data_key='regNo')
    roomNumber = fields.String(attribute='room_number', data_key='roomNumber')
    phoneNumber = fields.String(attribute='phone_number', data_key='phoneNumber')

class LaundryBatchSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = LaundryBatch
        load_instance = True
        include_fk = True
        exclude = ('scheduled_date', 'time_slot')
    
    student = ma.Nested(StudentSchema)
    scheduledDate = fields.String(attribute='scheduled_date', data_key='scheduledDate')
    timeSlot = fields.String(attribute='time_slot', data_key='timeSlot')

class RoomScheduleSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = RoomSchedule
        load_instance = True
        exclude = ('room_start', 'room_end', 'created_at')
    
    roomStart = fields.Integer(attribute='room_start', data_key='roomStart')
    roomEnd = fields.Integer(attribute='room_end', data_key='roomEnd')
    createdAt = fields.DateTime(attribute='created_at', data_key='createdAt')

class SystemSettingsSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = SystemSettings
        load_instance = True
        exclude = ('edit_window_open', 'updated_at')
        
    editWindowOpen = fields.Boolean(attribute='edit_window_open', data_key='editWindowOpen')
    updatedAt = fields.DateTime(attribute='updated_at', data_key='updatedAt')

class StudentInviteSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = StudentInvite
        load_instance = True
        exclude = ('used_at', 'used_by_student_id', 'created_at')
    
    token = fields.String(attribute='token', data_key='token')
    usedAt = fields.DateTime(attribute='used_at', data_key='usedAt')
    usedByStudentId = fields.Integer(attribute='used_by_student_id', data_key='usedByStudentId')
    createdAt = fields.DateTime(attribute='created_at', data_key='createdAt')

class AnnouncementSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Announcement
        load_instance = True
        exclude = ()

class NotificationSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Notification
        load_instance = True
        exclude = ()

class ComplaintSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Complaint
        load_instance = True
        exclude = ()

    student = ma.Nested(StudentSchema)

class DailyLaundryDetailSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = DailyLaundryDetail
        load_instance = True
        exclude = ()

class LaundryRecordSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = LaundryRecord
        load_instance = True
        exclude = ('token_number', 'batch_id', 'student_id', 'student_name', 'reg_no', 'floor', 'room_number', 'phone_number', 'clothes_count', 'created_at', 'updated_at')

    tokenNumber = fields.Integer(attribute='token_number', data_key='tokenNumber')
    batchId = fields.Integer(attribute='batch_id', data_key='batchId')
    studentId = fields.Integer(attribute='student_id', data_key='studentId')
    studentName = fields.String(attribute='student_name', data_key='studentName')
    regNo = fields.String(attribute='reg_no', data_key='regNo')
    roomNumber = fields.String(attribute='room_number', data_key='roomNumber')
    phoneNumber = fields.String(attribute='phone_number', data_key='phoneNumber')
    clothesCount = fields.Integer(attribute='clothes_count', data_key='clothesCount')
    createdAt = fields.DateTime(attribute='created_at', data_key='createdAt')
    updatedAt = fields.DateTime(attribute='updated_at', data_key='updatedAt')

class LostFoundItemSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = LostFoundItem
        load_instance = True
        exclude = ('token_number', 'student_id', 'image_url', 'created_by', 'archived_at', 'created_at')

    tokenNumber = fields.Integer(attribute='token_number', data_key='tokenNumber')
    studentId = fields.Integer(attribute='student_id', data_key='studentId')
    imageUrl = fields.String(attribute='image_url', data_key='imageUrl')
    createdBy = fields.String(attribute='created_by', data_key='createdBy')
    archivedAt = fields.DateTime(attribute='archived_at', data_key='archivedAt')
    createdAt = fields.DateTime(attribute='created_at', data_key='createdAt')
