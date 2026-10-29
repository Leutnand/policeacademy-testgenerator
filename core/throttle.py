"""Begrenzung von Fehlversuchen bei OTP-Eingabe und Mitarbeiter-Anmeldung."""

from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from .models import AuditLog, TestSession

LOGIN_FAILED_ACTION = "auth.login.failed"


def login_username_key(username: str) -> str:
    """Normalisiert Benutzernamen, damit Groß-/Kleinschreibung die Sperre nicht umgeht."""
    return username.strip().lower()[:150]


def login_is_blocked(username: str) -> bool:
    """Sperrt die Anmeldung je Benutzername nach zu vielen Fehlversuchen im Zeitfenster.

    Die Sperre hängt am Benutzernamen, weil hinter einem Reverse-Proxy alle
    Clients dieselbe Remote-Adresse haben und eine IP-Sperre alle aussperren würde.
    """
    key = login_username_key(username)
    if not key:
        return False
    since = timezone.now() - timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    failures = AuditLog.objects.filter(
        action=LOGIN_FAILED_ACTION,
        created_at__gte=since,
        metadata__username_key=key,
    ).count()
    return failures >= settings.LOGIN_MAX_FAILURES


def otp_is_locked(test: TestSession) -> bool:
    """Zeigt, ob der Testzugang durch Fehlversuche dauerhaft gesperrt ist."""
    return test.otp_failed_attempts >= settings.OTP_MAX_FAILED_ATTEMPTS


def reserve_otp_attempt(test: TestSession) -> bool:
    """Reserviert atomar einen Versuch vor der Prüfung, damit parallele Anfragen nichts umgehen."""
    reserved = TestSession.objects.filter(
        pk=test.pk,
        status=TestSession.Status.ISSUED,
        otp_failed_attempts__lt=settings.OTP_MAX_FAILED_ATTEMPTS,
    ).update(otp_failed_attempts=F("otp_failed_attempts") + 1)
    return reserved == 1


def reset_otp_attempts(test: TestSession) -> None:
    """Setzt den Zähler nach korrekter Eingabe zurück."""
    TestSession.objects.filter(pk=test.pk).update(otp_failed_attempts=0)
