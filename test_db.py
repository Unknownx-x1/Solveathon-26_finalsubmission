import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    uri = os.environ.get('DATABASE_URL')
    if not uri:
        print("❌ Error: DATABASE_URL not found in .env file.")
        return

    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)

    print(f"Connecting to: {uri.split('@')[-1] if '@' in uri else 'PostgreSQL'}...")
    
    try:
        engine = create_engine(uri)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            version = result.fetchone()
            print(f"✅ Success! Connected to PostgreSQL.")
            print(f"Database version: {version[0]}")
    except Exception as e:
        print(f"❌ Failed to connect.")
        print(f"Error: {e}")
        print("\nCommon fixes:")
        print("1. Check if the password is correct.")
        print("2. Ensure your IP is whitelisted in the hosted DB dashboard (Neon/Railway).")
        print("3. Verify the database name exists.")

if __name__ == "__main__":
    test_connection()
