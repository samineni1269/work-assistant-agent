"""
gmail_smtp.py — Send emails via Gmail SMTP
===========================================
Uses a Gmail App Password (not your main password).

Setup (one-time):
  1. Go to https://myaccount.google.com/apppasswords
  2. Select app: Mail, device: Other → name it "Work Assistant"
  3. Copy the 16-char password shown
  4. Add to .env:
       GMAIL_USER=samineni98@gmail.com
       GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   (spaces OK — they are ignored)

Why App Password and not OAuth?
  App passwords work with 2FA-enabled accounts and are simpler than OAuth
  for a local tool. They only allow sending mail — they cannot read or delete.
"""

import os
import smtplib
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from typing import Optional


def _get_credentials() -> tuple[str, str]:
    """Return (gmail_user, app_password) from .env, raising clearly if missing."""
    user = os.getenv("GMAIL_USER", "").strip()
    pwd  = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()

    missing = []
    if not user:
        missing.append("GMAIL_USER")
    if not pwd:
        missing.append("GMAIL_APP_PASSWORD")

    if missing:
        raise ValueError(
            f"❌ Missing Gmail credentials: {', '.join(missing)}\n"
            "  To set up:\n"
            "  1. Visit https://myaccount.google.com/apppasswords\n"
            "  2. Create an app password for 'Work Assistant'\n"
            "  3. Add GMAIL_USER and GMAIL_APP_PASSWORD to your .env file"
        )
    return user, pwd


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    html_body: Optional[str] = None,
) -> dict:
    """
    Send an email via Gmail SMTP.

    Args:
        to:        Recipient email (single address)
        subject:   Email subject line
        body:      Plain-text body
        cc:        CC address (optional)
        html_body: HTML version of body (optional — enhances plain text)

    Returns:
        {"status": "sent", "to": to, "subject": subject, "from": sender}
    """
    sender, app_password = _get_credentials()

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = sender
    msg["To"]       = to
    msg["Date"]     = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    if cc:
        msg["Cc"] = cc

    # Plain text part
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # HTML part (auto-generated from plain text if not provided)
    if not html_body:
        escaped = html.escape(body)
        paragraphs = "".join(
            f"<p style='margin:0 0 10px;line-height:1.6'>{p}</p>"
            for p in escaped.split("\n\n")
            if p.strip()
        )
        html_body = f"""
<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#1a1a1a;max-width:600px;margin:0 auto;padding:20px">
{paragraphs}
<hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb">
<p style="font-size:11px;color:#9ca3af">Sent via Work Assistant Agent</p>
</body></html>"""

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    recipients = [to] + ([cc] if cc else [])
    raw = msg.as_string()

    # Try port 587 (STARTTLS) first, fall back to port 465 (SSL)
    last_error = None
    for _attempt, (port, use_ssl) in enumerate([(587, False), (465, True)], 1):
        try:
            if use_ssl:
                import ssl as _ssl
                ctx = _ssl.create_default_context()
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30, context=ctx) as smtp:
                    smtp.login(sender, app_password)
                    smtp.sendmail(sender, recipients, raw)
            else:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(sender, app_password)
                    smtp.sendmail(sender, recipients, raw)
            # Success
            return {"status": "sent", "to": to, "subject": subject, "from": sender, "port": port}
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"Gmail SMTP failed on both port 587 and 465.\n"
        f"Last error: {last_error}\n"
        f"Check:\n"
        f"  1. GMAIL_APP_PASSWORD is correct (visit myaccount.google.com/apppasswords)\n"
        f"  2. 2-Step Verification is ON for {sender}\n"
        f"  3. 'Less secure app access' is NOT needed — App Passwords bypass that\n"
        f"  4. No network/firewall blocking outbound port 587 or 465"
    )


def send_html_email(
    to: str,
    subject: str,
    html_body: str,
    plain_fallback: str = "",
) -> dict:
    """
    Send an HTML email via Gmail. Useful for formatted briefings and reports.

    Args:
        to:            Recipient address
        subject:       Subject line
        html_body:     Full HTML string
        plain_fallback: Optional plain-text fallback

    Returns:
        {"status": "sent", "to": to, "subject": subject}
    """
    if not plain_fallback:
        import re
        plain_fallback = re.sub(r"<[^>]+>", " ", html_body)
        plain_fallback = re.sub(r"\s+", " ", plain_fallback).strip()

    return send_email(to, subject, plain_fallback, html_body=html_body)
