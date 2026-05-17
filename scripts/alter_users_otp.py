import os
import sys
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import engine

def main():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_otp VARCHAR(6)"))
            conn.commit()
            print("Added reset_otp column")
        except Exception as e:
            conn.rollback()
            print(f"Skipping reset_otp (might already exist): {e}")

        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_otp_expires TIMESTAMP WITH TIME ZONE"))
            conn.commit()
            print("Added reset_otp_expires column")
        except Exception as e:
            conn.rollback()
            print(f"Skipping reset_otp_expires (might already exist): {e}")
            
        print("Database migration complete.")

if __name__ == "__main__":
    main()
