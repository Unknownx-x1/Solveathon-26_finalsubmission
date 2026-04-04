**Render Deploy**

1. Push this repo to GitHub.
2. Create a new Render Blueprint and point it to the repo.
3. Render will provision:
   - a Python web service
   - a PostgreSQL database
   - a persistent disk for uploaded OCR and lost-and-found images
4. After the database is created, run the migration once:

```powershell
$env:DATABASE_URL="your-render-postgres-connection-string"
python migrate_to_pg.py
```

5. Open the deployed site and verify:
   - student/staff login
   - booking creation
   - token generation
   - lost and found image upload
   - laundry history and notifications

**Important Notes**

- `UPLOADS_ROOT` is set to `/var/data/uploads` in production so uploaded images survive restarts.
- The app now serves uploaded files from `/uploads/...`.
- Existing local `/static/uploads/...` image URLs are still resolved for cleanup compatibility.
- `migrate_to_pg.py` now migrates all core data, including:
  - students
  - batches
  - schedules
  - settings
  - invites
  - notifications
  - complaints
  - daily laundry details
  - laundry records
  - lost and found items

**Recommended First Deploy Flow**

1. Deploy the blueprint.
2. Copy the Render PostgreSQL connection string.
3. Run `python migrate_to_pg.py` locally against that database.
4. Restart the Render service once after migration.
