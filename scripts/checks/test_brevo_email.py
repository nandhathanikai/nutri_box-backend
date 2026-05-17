"""Quick check: send a sample password-reset OTP email via Brevo.

Run from the backend directory:
    venv\\Scripts\\python.exe scripts\\checks\\test_brevo_email.py
"""
import os
import sys
import random
import string
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from app.utils.email import send_reset_password_email, BREVO_API_KEY, FROM_EMAIL, FROM_NAME

TO = "nandhathanikai@gmail.com"

print("--- Brevo configuration ---")
print(f"BREVO_API_KEY present : {bool(BREVO_API_KEY)} (len={len(BREVO_API_KEY) if BREVO_API_KEY else 0})")
if BREVO_API_KEY:
    print(f"BREVO_API_KEY prefix  : {BREVO_API_KEY[:8]}...")
print(f"FROM_EMAIL            : {FROM_EMAIL}")
print(f"FROM_NAME             : {FROM_NAME}")
print(f"Sending sample OTP to : {TO}")
print("---------------------------")

otp = "".join(random.choices(string.digits, k=6))
print(f"Generated test OTP    : {otp}")

ok = send_reset_password_email(to_email=TO, otp=otp)

print("---------------------------")
print("Result:", "SUCCESS" if ok else "FAILED")
sys.exit(0 if ok else 1)
