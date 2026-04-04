import os
import uuid
from datetime import datetime

from models import LostFoundItem, db


def ensure_directory(path):
    os.makedirs(path, exist_ok=True)


def save_lost_found_image(file_storage, storage_dir):
    ensure_directory(storage_dir)
    _, ext = os.path.splitext((file_storage.filename or "").lower())
    ext = ext or ".png"
    filename = f"lost_found_{uuid.uuid4().hex}{ext}"
    absolute_path = os.path.join(storage_dir, filename)
    file_storage.save(absolute_path)
    return filename, absolute_path


def delete_image_if_exists(absolute_path):
    if absolute_path and os.path.exists(absolute_path):
        os.remove(absolute_path)


def mark_lost_item_found(token_number, new_image_url=None, description=None, archive=False):
    lost_item = LostFoundItem.query.filter_by(
        token_number=token_number,
        status='lost'
    ).order_by(LostFoundItem.created_at.desc()).first()

    if not lost_item:
        return None

    old_image_url = lost_item.image_url
    lost_item.status = 'found'
    if new_image_url:
        lost_item.image_url = new_image_url
    if description:
        lost_item.description = description
    if archive:
        lost_item.archived_at = datetime.utcnow()

    return {
        "item": lost_item,
        "old_image_url": old_image_url,
    }
