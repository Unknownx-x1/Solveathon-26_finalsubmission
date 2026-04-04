**Railway Demo Deploy**

This setup is intended for a short demo on Railway with PostgreSQL and OCR enabled.

**What This Repo Now Supports**

- PostgreSQL via `DATABASE_URL`
- Persistent uploads via a Railway Volume when mounted
- OCR/PDF dependencies via `nixpacks.toml`
- Gunicorn start command tuned for a small demo workload

**Recommended Demo Architecture**

1. One Railway project
2. One app service from this GitHub repo
3. One PostgreSQL service
4. One Volume attached to the app service

**Step 1: Push the Repo**

Push this repo to GitHub first.

**Step 2: Create the Railway Project**

1. Sign in to Railway
2. Create a new project
3. Choose `Deploy from GitHub Repo`
4. Select this repository

Railway will build the app with Railpack/Nixpacks and use:
- [nixpacks.toml](/C:/dev/laundry%20repo%203/nixpacks.toml)
- [railway.json](/C:/dev/laundry%20repo%203/railway.json)

**Step 3: Add PostgreSQL**

1. In the project, click `New`
2. Add `PostgreSQL`
3. Wait for it to finish provisioning

Railway will expose a `DATABASE_URL` variable for that service. Copy it into the app service if it is not automatically shared in your setup.

**Step 4: Add a Volume**

1. Open the app service
2. Add a Volume
3. Mount it at:

```text
/app/uploads
```

The app will automatically use `RAILWAY_VOLUME_MOUNT_PATH` if present, so uploads and lost-and-found images will persist better during the demo.

**Step 5: Environment Variables**

Set these on the app service:

```text
SECRET_KEY=any-long-random-string
```

You usually do not need to set `UPLOADS_ROOT` manually on Railway if the volume is mounted, because Railway provides `RAILWAY_VOLUME_MOUNT_PATH`.

If needed, you can still set:

```text
UPLOADS_ROOT=/app/uploads
```

**Step 6: Migrate Your Existing Local Data**

After Railway Postgres is ready, copy the app-visible `DATABASE_URL` and run locally:

```powershell
$env:DATABASE_URL="your-railway-postgres-url"
python migrate_to_pg.py
```

Then trigger a redeploy or restart the app service.

**Step 7: Verify Demo Flows**

Check:
- student login
- booking creation
- token generation
- laundry history
- announcements and complaints
- lost and found image upload

**Free/Trial Caveats**

- Railway docs say volumes on Free and Trial plans default to `0.5GB`. Source: https://docs.railway.com/reference/volumes
- Railway docs say a mounted volume is exposed at the configured mount path and also provides `RAILWAY_VOLUME_MOUNT_PATH`. Source: https://docs.railway.com/guides/volumes
- Railway docs say build/start commands can be overridden for a service. Source: https://docs.railway.com/builds/build-and-start-commands
- Railway docs say new users can use the free trial without a credit card. Source: https://docs.railway.com/reference/pricing/faqs

**If PostgreSQL Is Not Auto-Wired**

If the app service does not automatically see the DB connection string:

1. Open the PostgreSQL service
2. Copy the connection URL
3. Open the app service variables
4. Add:

```text
DATABASE_URL=<copied-postgres-url>
```

**If OCR Build Fails**

This repo already includes OCR system dependencies in [nixpacks.toml](/C:/dev/laundry%20repo%203/nixpacks.toml), but if Railway changes package naming you may need to adjust those package names in build logs.
