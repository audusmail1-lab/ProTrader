"""Provider-neutral, encrypted SMTP transport. Never log credentials or message bodies."""
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    security: str = 'starttls'

    @classmethod
    def from_environment(cls):
        names = ['HOST', 'USER', 'PASSWORD', 'FROM']
        if any(not os.environ.get('ACADEMY_SMTP_' + key, '').strip() for key in names):
            raise ValueError('Set SMTP host, user, password and sender in the host’s private environment settings.')
        security = os.environ.get('ACADEMY_SMTP_SECURITY', 'starttls')
        if security not in ('starttls', 'tls'):
            raise ValueError('SMTP security must be starttls or tls. Unencrypted delivery is not supported.')
        try:
            port = int(os.environ.get('ACADEMY_SMTP_PORT', '465' if security == 'tls' else '587'))
        except ValueError:
            raise ValueError('SMTP port must be a number.') from None
        if not 1 <= port <= 65535:
            raise ValueError('SMTP port must be between 1 and 65535.')
        host, user, password, sender = [os.environ['ACADEMY_SMTP_' + key] for key in names]
        if any(c in host + sender for c in '\r\n') or '@' not in parseaddr(sender)[1]:
            raise ValueError('Check the SMTP host and sender address.')
        return cls(host, port, user, password, sender, security)

    def connect(self):
        context = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=context) if self.security == 'tls' else smtplib.SMTP(self.host, self.port, timeout=15)
        try:
            smtp.ehlo()
            if self.security == 'starttls':
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(self.user, self.password)
            return smtp
        except Exception:
            smtp.close()
            raise

    def check(self):
        """Authenticate without sending an email or processing the outbox."""
        with self.connect() as smtp:
            code, _ = smtp.noop()
            if code != 250:
                raise smtplib.SMTPException('SMTP check failed')

    def send(self, row):
        msg = EmailMessage()
        msg['From'] = self.sender
        msg['To'] = row['recipient']
        msg['Subject'] = row['subject']
        domain = parseaddr(self.sender)[1].split('@')[-1]
        msg['Message-ID'] = f"<academy-{row['delivery_key']}@{domain}>"
        if self.host.lower() == 'smtp.resend.com':
            msg['Resend-Idempotency-Key'] = 'academy/' + row['delivery_key']
        msg.set_content(row['body'])
        with self.connect() as smtp:
            if smtp.send_message(msg):
                raise smtplib.SMTPRecipientsRefused({})


def safe_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'Email service sign-in failed. Check the private SMTP credentials.'
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return 'The email service rejected the sender. Check the verified sending domain.'
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return 'The email service rejected the recipient. Check the address and provider restrictions.'
    if isinstance(exc, ssl.SSLError):
        return 'The secure email connection failed. Check the host, port and TLS settings.'
    return 'Delivery could not be confirmed. Check provider logs before retrying; an email may already have been accepted.'
