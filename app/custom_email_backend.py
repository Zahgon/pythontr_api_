"""Mail backend that tolerates hosts presenting an untrusted certificate.

Ported verbatim from the baseline: the permissive SSL context (hostname
checking off, certificate verification off) is part of the deployed
behaviour and is reproduced rather than fixed.
"""

from __future__ import annotations

import smtplib
import ssl

from app.mail.backends.smtp import EmailBackend


class CustomEmailBackend(EmailBackend):
    """SMTP backend whose TLS handshake skips certificate validation."""

    def open(self):
        if self.connection:
            return False
        try:
            self.connection = smtplib.SMTP(self.host, self.port, timeout=10)
            self.connection.ehlo()
            if self.use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.connection.starttls(context=context)
                self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except Exception:
            if not self.fail_silently:
                raise
            return False
