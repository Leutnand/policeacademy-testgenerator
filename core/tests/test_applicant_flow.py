"""Tests zum Prüflingsablauf."""

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from ..models import (
    AuditLog,
    Question,
    QuestionPool,
    Submission,
    TestQuestion,
    TestSession,
)


class ApplicantFlowTests(TestCase):
    """Prüft Prüflingsausgabe, Abgabe und Einmaligkeit des Zugangs."""

    def setUp(self):
        """Erzeugt einen Test mit Choice- und Freitextfrage."""
        self.user = get_user_model().objects.create_user(
            username="owner", password="test-pass-123"
        )
        self.question_pool = QuestionPool.objects.create(name="Academy-Grundtest")
        # Der Test wird direkt erzeugt, damit die Testfragen den Lösungsschlüssel abdecken.
        from django.contrib.auth.hashers import make_password

        self.test = TestSession.objects.create(
            created_by=self.user,
            question_pool=self.question_pool,
            otp_hash=make_password("123456"),
        )
        TestQuestion.objects.create(
            test=self.test,
            position=1,
            text="Welche Option?",
            question_type=Question.Type.SINGLE,
            options=[
                {"text": "Richtig", "is_correct": True},
                {"text": "Falsch", "is_correct": False},
            ],
            points=2,
            answer_key="intern",
        )
        TestQuestion.objects.create(
            test=self.test,
            position=2,
            text="Begründe.",
            question_type=Question.Type.LONG,
            points=5,
            answer_key="Geheime Musterlösung",
        )

    def test_exam_hides_solutions_and_consumes_otp_atomically(self):
        """HTML zeigt keine Lösungen/Punkte und erneute Einlösung wird gesperrt."""
        access_url = reverse("take_test", args=[self.test.pk])
        response = self.client.post(access_url, {"otp": "123456"})
        self.assertRedirects(response, access_url)
        response = self.client.get(access_url)
        self.assertContains(response, "Wer schreibt den Test?")
        self.assertNotContains(response, "Welche Option?")
        response = self.client.post(access_url, {"examinee_name": "Alex Morgan"})
        self.assertRedirects(response, access_url)
        response = self.client.get(access_url)
        self.assertContains(response, "Welche Option?")
        self.assertContains(response, "academy-test-draft")
        self.assertContains(response, "beforeunload")
        self.assertNotContains(response, "Geheime Musterlösung")
        self.assertNotContains(response, "is_correct")
        self.assertNotContains(response, "5.00")
        response = self.client.post(
            access_url, {"question_1": "0", "question_2": "Ausführliche Antwort"}
        )
        self.assertContains(response, "Alles angekommen.")
        self.assertContains(response, "sessionStorage.removeItem")
        self.test.refresh_from_db()
        self.assertEqual(self.test.status, TestSession.Status.COMPLETED)
        self.assertEqual(self.test.examinee_name, "Alex Morgan")
        self.assertEqual(Submission.objects.count(), 2)
        self.assertEqual(Submission.objects.get(test_question__position=1).score, 2)
        self.assertTrue(
            Submission.objects.get(test_question__position=2).needs_manual_grading
        )
        self.assertEqual(self.client.get(access_url).status_code, 410)

    def test_wrong_otp_does_not_authorize_applicant(self):
        """Ein falsches Einmalpasswort gibt weder Fragen noch Zugang frei."""
        response = self.client.post(
            reverse("take_test", args=[self.test.pk]), {"otp": "000000"}
        )
        self.assertContains(response, "ungültig")
        self.assertNotContains(response, "Welche Option?")
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.REQUEST,
                object_id="take_test",
                description__contains=str(self.test.pk),
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.SECURITY,
                action="test.otp.rejected",
                object_id=str(self.test.pk),
            ).exists()
        )

    def test_timed_test_starts_on_exam_page_and_auto_submits_when_expired(self):
        """Zeitlimit startet mit der Fragenseite und wird serverseitig erzwungen."""
        self.test.time_limit_minutes = 1
        self.test.save(update_fields=["time_limit_minutes"])
        access_url = reverse("take_test", args=[self.test.pk])
        self.client.post(access_url, {"otp": "123456"})
        self.client.post(access_url, {"examinee_name": "Timed Applicant"})
        response = self.client.get(access_url)
        self.assertEqual(response.context["remaining_seconds"], 60)
        self.assertContains(response, "Verbleibende Zeit")
        self.test.refresh_from_db()
        self.assertIsNotNone(self.test.started_at)
        self.test.started_at = self.test.otp_verified_at = timezone.now() - timedelta(
            seconds=61
        )
        self.test.save(update_fields=["started_at", "otp_verified_at"])

        response = self.client.get(access_url)
        self.assertContains(response, "Alles angekommen.")
        self.test.refresh_from_db()
        self.assertEqual(self.test.status, TestSession.Status.COMPLETED)
        self.assertEqual(self.test.elapsed_seconds, 61)
        self.assertEqual(self.test.time_taken_display, "1:01")
        self.assertTrue(
            AuditLog.objects.filter(
                action="submission.timed_out",
                object_id=str(self.test.pk),
            ).exists()
        )
        self.assertEqual(Submission.objects.filter(test=self.test).count(), 2)
        self.assertEqual(
            Submission.objects.get(test_question__position=1).answer, {"value": ""}
        )
        administrator = get_user_model().objects.create_superuser(
            username="timed-review-admin",
            email="timed-review@example.com",
            password="strong-password",
        )
        self.client.force_login(administrator)
        self.assertContains(self.client.get(reverse("submissions")), "1:01")
        self.assertContains(
            self.client.get(reverse("submission_detail", args=[self.test.pk])),
            "BEARBEITUNGSZEIT",
        )

    def test_timer_submission_keeps_answers_during_network_grace(self):
        """Die automatische Abgabe behält Antworten bei kurzer Request-Laufzeit nach Fristende."""
        self.test.time_limit_minutes = 1
        self.test.save(update_fields=["time_limit_minutes"])
        access_url = reverse("take_test", args=[self.test.pk])
        self.client.post(access_url, {"otp": "123456"})
        self.client.post(access_url, {"examinee_name": "Grace Applicant"})
        self.client.get(access_url)
        self.test.refresh_from_db()
        self.test.started_at = self.test.otp_verified_at = timezone.now() - timedelta(
            seconds=61, milliseconds=500
        )
        self.test.save(update_fields=["started_at", "otp_verified_at"])

        response = self.client.post(
            access_url, {"question_1": "0", "question_2": "Antwort"}
        )
        self.assertContains(response, "Alles angekommen.")
        self.test.refresh_from_db()
        self.assertEqual(self.test.status, TestSession.Status.COMPLETED)
        self.assertEqual(self.test.elapsed_seconds, 61)
        self.assertEqual(Submission.objects.get(test_question__position=1).score, 2)
        self.assertEqual(
            Submission.objects.get(test_question__position=2).answer,
            {"value": "Antwort"},
        )
