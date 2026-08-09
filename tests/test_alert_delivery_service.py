from web.application.alert_delivery_service import deliver_alert, delivery_hooks


class _Response:
    status_code = 201


def test_enabled_channels_do_not_claim_configuration_without_credentials(monkeypatch):
    for key in ("EDGEIQ_SMTP_HOST", "EDGEIQ_SMTP_FROM", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.delenv(key, raising=False)
    hooks = delivery_hooks({"email_enabled": True, "email_address": "a@example.com", "sms_enabled": True, "sms_number": "+15555555555"})
    assert hooks["email"] == "needs SMTP credentials"
    assert hooks["sms"] == "needs Twilio credentials"


def test_sms_delivery_uses_configured_twilio_account(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    result = deliver_alert(
        {"priority": 80, "title": "Line moved", "message": "A line changed."},
        {"sms_enabled": True, "sms_number": "+15551111111", "min_priority": 65},
        sent_at="2026-08-09T12:00:00Z",
        post=post,
    )
    assert result["delivered"] is True
    assert result["channels"][0]["status"] == "sent"
    assert calls[0][1]["auth"] == ("AC123", "secret")
