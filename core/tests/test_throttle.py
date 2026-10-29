"""Tests zur Begrenzung von OTP- und Anmelde-Fehlversuchen."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import AuditLog, QuestionPool, TestSession


@override_settings(OTP_MAX_FAILED_ATTEMPTS=3)
class OtpThrottleTests(TestCase):
    """Prüft, dass das Einmalpasswort nicht durchprobiert werden kann."""

    def setUp(self):
        """Erzeugt einen ausgestellten Test mit bekanntem Einmalpasswort."""
        pool = QuestionPool.objects.create(name="Throttle-Pool")
        self.test = TestSession.objects.create(
            question_pool=pool, otp_hash=make_password("123456")
        )
        self.url = reverse("take_test", args=[self.test.pk])

    def test_test_is_locked_after_too_many_wrong_attempts(self):
        """Nach dem Limit wird auch das korrekte Passwort nicht mehr akzeptiert."""
        for _ in range(3):
            response = self.client.post(self.url, {"otp": "000000"})
            self.assertContains(response, "ungültig")
        response = self.client.post(self.url, {"otp": "123456"})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "gesperrt", status_code=429)
        self.assertTrue(
            AuditLog.objects.filter(
                action="test.otp.locked", object_id=str(self.test.pk)
            ).exists()
        )
        self.assertEqual(self.client.get(self.url).status_code, 429)
        self.test.refresh_from_db()
        self.assertIsNone(self.test.otp_verified_at)

    def test_correct_otp_resets_counter(self):
        """Ein gültiges Passwort setzt die Fehlversuche zurück."""
        self.client.post(self.url, {"otp": "000000"})
        self.client.post(self.url, {"otp": "123456"})
        self.test.refresh_from_db()
        self.assertEqual(self.test.otp_failed_attempts, 0)
        self.assertIsNotNone(self.test.otp_verified_at)


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_FAILURE_WINDOW_MINUTES=15)
class LoginThrottleTests(TestCase):
    """Prüft die Sperre der Mitarbeiter-Anmeldung nach Fehlversuchen."""

    def setUp(self):
        """Legt einen Mitarbeiter mit bekanntem Passwort an."""
        self.password = "Correct-Horse-9"
        get_user_model().objects.create_user(username="officer", password=self.password)

    def attempt(self, username, password):
        """Sendet einen Anmeldeversuch."""
        return self.client.post(
            reverse("login"), {"username": username, "password": password}
        )

    def test_login_is_blocked_after_repeated_failures_even_with_correct_password(self):
        """Fehlversuche sperren den Benutzernamen unabhängig von der Schreibweise."""
        for name in ("officer", "OFFICER", "Officer"):
            self.assertEqual(self.attempt(name, "falsch").status_code, 200)
        response = self.attempt("officer", self.password)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(action="auth.login.blocked").exists())

    def test_failures_outside_window_do_not_block(self):
        """Alte Fehlversuche außerhalb des Zeitfensters zählen nicht mehr."""
        for _ in range(3):
            self.attempt("officer", "falsch")
        AuditLog.objects.filter(action="auth.login.failed").update(
            created_at=timezone.now() - timedelta(minutes=16)
        )
        response = self.attempt("officer", self.password)
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_other_users_are_not_affected(self):
        """Die Sperre gilt nur für den betroffenen Benutzernamen."""
        get_user_model().objects.create_user(username="other", password=self.password)
        for _ in range(3):
            self.attempt("officer", "falsch")
        self.assertEqual(self.attempt("other", self.password).status_code, 302)


class AuditRequestModeTests(TestCase):
    """Prüft die konfigurierbare Protokollierung von Lesezugriffen."""

    @override_settings(AUDIT_LOG_REQUESTS="changes")
    def test_changes_mode_skips_successful_reads_but_logs_errors(self):
        """Erfolgreiche GET-Anfragen entfallen, Fehler und Schreibzugriffe bleiben."""
        self.client.get(reverse("login"))
        self.assertFalse(AuditLog.objects.filter(action="http.get").exists())
        self.client.get("/gibt-es-nicht/")
        self.assertTrue(AuditLog.objects.filter(action="http.get").exists())
        self.client.post(reverse("login"), {"username": "x", "password": "y"})
        self.assertTrue(AuditLog.objects.filter(action="http.post").exists())

    def test_default_mode_logs_reads(self):
        """Standardmäßig wird weiterhin jeder Zugriff protokolliert."""
        self.client.get(reverse("login"))
        self.assertTrue(AuditLog.objects.filter(action="http.get").exists())
