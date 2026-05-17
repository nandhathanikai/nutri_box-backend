import logging
import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

logger = logging.getLogger(__name__)

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@nutribox.app")
FROM_NAME = os.getenv("FROM_NAME", "NutriBox")


def is_email_configured() -> bool:
    """Return True if email delivery is wired up. Callers should branch on this
    so 'email broken' doesn't silently masquerade as 'email sent'."""
    return bool(BREVO_API_KEY)


def _get_brevo_client():
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    return sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )


def _send(to_email: str, subject: str, html_content: str, *, kind: str) -> bool:
    if not BREVO_API_KEY:
        # Loud log so ops notices in production. Callers should treat False as
        # a hard failure — never as "we sent it but never mind."
        logger.error(
            "Email NOT sent (kind=%s, to=%s): BREVO_API_KEY is not configured.",
            kind, to_email,
        )
        return False

    payload = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email}],
        sender={"name": FROM_NAME, "email": FROM_EMAIL},
        subject=subject,
        html_content=html_content,
    )
    try:
        api = _get_brevo_client()
        response = api.send_transac_email(payload)
        logger.info("Email sent (kind=%s, to=%s, message_id=%s)", kind, to_email, response.message_id)
        return True
    except ApiException as e:
        logger.error("Brevo API error (kind=%s, to=%s, status=%s, body=%s)", kind, to_email, e.status, e.body)
        return False
    except Exception:
        logger.exception("Unexpected error sending email (kind=%s, to=%s)", kind, to_email)
        return False


def send_reset_password_email(to_email: str, otp: str) -> bool:
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; padding: 24px; color: #222;">
      <h2 style="color: #2e7d32; margin-bottom: 8px;">NutriBox - Password Reset</h2>
      <p>Hello,</p>
      <p>You requested to reset your password. Use the following 6-digit OTP to set a new password:</p>
      <div style="font-size: 28px; font-weight: bold; letter-spacing: 6px; background: #f1f8e9; padding: 14px 20px; text-align: center; border-radius: 8px; margin: 16px 0;">
        {otp}
      </div>
      <p>This OTP will expire in <b>5 minutes</b>.</p>
      <p>If you did not request a password reset, please ignore this email.</p>
      <br/>
      <p>Thanks,<br/>The NutriBox Team</p>
    </div>
    """
    return _send(to_email, "NutriBox - Password Reset OTP", html_content, kind="password_reset")


def send_verification_email(to_email: str, full_name: str, verification_link: str) -> bool:
    """Send the post-signup email-verification link.

    The link should resolve to the frontend, which calls
    GET /api/auth/verify-email?token=... on the user's behalf.
    """
    safe_name = (full_name or "there").split(" ")[0]
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; padding: 24px; color: #222;">
      <h2 style="color: #2e7d32; margin-bottom: 8px;">Welcome to NutriBox, {safe_name}!</h2>
      <p>Tap the button below to confirm this is your email address.</p>
      <p style="text-align: center; margin: 24px 0;">
        <a href="{verification_link}"
           style="display: inline-block; background: #2e7d32; color: #fff; text-decoration: none;
                  padding: 12px 24px; border-radius: 8px; font-weight: 600;">
          Verify my email
        </a>
      </p>
      <p style="font-size: 13px; color: #666;">If the button doesn't work, paste this link into your browser:<br/>
        <span style="word-break: break-all;">{verification_link}</span>
      </p>
      <p>Didn't sign up? You can safely ignore this email.</p>
      <br/>
      <p>Thanks,<br/>The NutriBox Team</p>
    </div>
    """
    return _send(to_email, "NutriBox - Verify your email", html_content, kind="verify_email")


def send_credit_expiry_warning(
    to_email: str,
    full_name: str,
    credits_count: int,
    days_remaining: int,
) -> bool:
    """Notify a customer that their meal credits are about to expire.

    Sent by the daily scheduler when credits enter the warning window
    (CREDIT_EXPIRY_WARN_DAYS before expiry).
    """
    safe_name = (full_name or "there").split(" ")[0]
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; padding: 24px; color: #222;">
      <h2 style="color: #2e7d32; margin-bottom: 8px;">Hi {safe_name}, your meal credits are expiring soon!</h2>
      <p>You have <b>{credits_count} unused meal credit{"s" if credits_count != 1 else ""}</b> that
         will expire in approximately <b>{days_remaining} day{"s" if days_remaining != 1 else ""}</b>.</p>
      <div style="background: #f1f8e9; padding: 16px 20px; border-radius: 8px; margin: 16px 0;">
        <p style="margin: 0; font-size: 15px;">
          <b>What are meal credits?</b><br/>
          When you skip a delivery during your subscription, you earn bonus meal
          days that are added after your plan ends. If they are not used in time,
          they expire automatically.
        </p>
      </div>
      <p>No action is needed if you don't wish to use them — they'll simply expire
         and no charges apply.</p>
      <br/>
      <p>Thanks,<br/>The NutriBox Team</p>
    </div>
    """
    return _send(
        to_email,
        f"NutriBox - {credits_count} meal credit{'s' if credits_count != 1 else ''} expiring soon",
        html_content,
        kind="credit_expiry_warning",
    )
