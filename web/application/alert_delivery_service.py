from __future__ import annotations

import os
import smtplib
from collections.abc import Callable
from copy import deepcopy
from email.message import EmailMessage

import requests


def delivery_hooks(settings: dict) -> dict:
    return {
        "browser": "available",
        "email": _email_status(settings),
        "sms": _sms_status(settings),
        "webhook": "configured" if settings.get("webhook_enabled") and settings.get("webhook_url") else "optional",
    }


def deliver_alert(alert: dict, settings: dict, *, sent_at: str, post: Callable[..., object] = requests.post) -> dict:
    alert = deepcopy(alert)
    priority = float(alert.get("priority") or 0.0)
    if priority < float(settings.get("min_priority") or 0.0):
        return {"delivered": False, "skipped": True, "reason": f"Priority {priority:.0f} is below alert threshold.", "channels": []}
    deliveries = []
    if settings.get("browser_enabled"):
        deliveries.append({"channel": "browser", "status": "queued", "detail": "Browser notification queued for the active app."})
    if settings.get("email_enabled") and settings.get("email_address"):
        deliveries.append(_deliver_email(str(settings["email_address"]), alert))
    if settings.get("sms_enabled") and settings.get("sms_number"):
        deliveries.append(_deliver_sms(str(settings["sms_number"]), alert, post))
    if settings.get("webhook_enabled") and settings.get("webhook_url"):
        deliveries.append(_deliver_webhook(str(settings["webhook_url"]), alert, post))
    return {
        "delivered": any(row["status"] in {"queued", "sent"} for row in deliveries),
        "skipped": False,
        "channels": deliveries,
        "alert": alert,
        "sent_at": sent_at,
    }


def _email_status(settings: dict) -> str:
    if not settings.get("email_enabled") or not settings.get("email_address"):
        return "optional"
    return "configured" if os.getenv("EDGEIQ_SMTP_HOST") and os.getenv("EDGEIQ_SMTP_FROM") else "needs SMTP credentials"


def _sms_status(settings: dict) -> str:
    if not settings.get("sms_enabled") or not settings.get("sms_number"):
        return "optional"
    required = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")
    return "configured" if all(os.getenv(key) for key in required) else "needs Twilio credentials"


def _deliver_email(destination: str, alert: dict) -> dict:
    host = os.getenv("EDGEIQ_SMTP_HOST", "").strip()
    sender = os.getenv("EDGEIQ_SMTP_FROM", "").strip()
    if not host or not sender:
        return {"channel": "email", "status": "not_configured", "detail": "Set EDGEIQ_SMTP_HOST and EDGEIQ_SMTP_FROM to send email alerts."}
    message = EmailMessage()
    message["Subject"] = f"EdgeIQ: {alert.get('title') or 'Market alert'}"
    message["From"] = sender
    message["To"] = destination
    message.set_content(str(alert.get("message") or alert.get("summary") or "EdgeIQ alert"))
    try:
        port = int(os.getenv("EDGEIQ_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=8) as client:
            if os.getenv("EDGEIQ_SMTP_TLS", "true").strip().lower() not in {"0", "false", "no"}:
                client.starttls()
            username = os.getenv("EDGEIQ_SMTP_USERNAME", "").strip()
            if username:
                client.login(username, os.getenv("EDGEIQ_SMTP_PASSWORD", ""))
            client.send_message(message)
        return {"channel": "email", "status": "sent", "detail": f"Email sent to {destination}."}
    except (OSError, smtplib.SMTPException, ValueError):
        return {"channel": "email", "status": "error", "detail": "Email delivery failed. Check the SMTP settings and try again."}


def _deliver_sms(destination: str, alert: dict, post: Callable[..., object]) -> dict:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    sender = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    if not sid or not token or not sender:
        return {"channel": "sms", "status": "not_configured", "detail": "Set the Twilio account SID, auth token, and sender number to send SMS alerts."}
    try:
        response = post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data={"To": destination, "From": sender, "Body": str(alert.get("message") or alert.get("title") or "EdgeIQ alert")}, auth=(sid, token), timeout=8)
        ok = 200 <= int(getattr(response, "status_code", 500)) < 300
        return {"channel": "sms", "status": "sent" if ok else "error", "detail": "SMS sent." if ok else "SMS provider rejected the message. Check the number and credentials."}
    except requests.RequestException:
        return {"channel": "sms", "status": "error", "detail": "SMS delivery failed. Check the Twilio settings and try again."}


def _deliver_webhook(url: str, alert: dict, post: Callable[..., object]) -> dict:
    try:
        response = post(url, json={"source": "EdgeIQ", "alert": alert}, timeout=6)
        ok = 200 <= int(getattr(response, "status_code", 500)) < 300
        return {"channel": "webhook", "status": "sent" if ok else "error", "detail": "Webhook delivered." if ok else "Webhook returned an error. Check the URL and try again."}
    except requests.RequestException:
        return {"channel": "webhook", "status": "error", "detail": "Webhook delivery failed. Check the URL and try again."}
