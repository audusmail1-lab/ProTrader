"""Run on the host with secrets configured; checks TLS/auth without sending mail."""
from mailer import SMTPConfig, safe_error

if __name__ == '__main__':
    try:
        settings = SMTPConfig.from_environment()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    try:
        settings.check()
    except Exception as exc:
        raise SystemExit(safe_error(exc)) from None
    print('Secure SMTP connection and sign-in passed. No email was sent. Verify the sender domain and send one test from Teaching before opening applications.')
