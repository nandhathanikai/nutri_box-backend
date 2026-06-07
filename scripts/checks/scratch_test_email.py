import sys
import os
sys.path.append(os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

from app.utils.email import send_verification_email

print("BREVO_API_KEY from env:", os.getenv("BREVO_API_KEY"))
print("Sending verification email to nandhathanikai@gmail.com...")
success = send_verification_email(
    to_email="nandhathanikai@gmail.com",
    full_name="Nandha",
    verification_link="http://localhost:4200/verify-email?token=testtoken"
)

if success:
    print("SUCCESS: Email sent successfully according to Brevo!")
else:
    print("FAILED: Check the printed log above for any Brevo API errors.")
