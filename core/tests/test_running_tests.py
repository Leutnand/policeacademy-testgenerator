"""Tests der Übersicht laufender Tests."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import QuestionPool, TestSession
from ..permissions import pool_permission_codename


class RunningTestsViewTests(TestCase):
    """Prüft Sichtbarkeit, Phasen und Restzeit laufender Tests."""

    def setUp(self):
        """Legt zwei Pools und einen Prüfer mit Recht für genau einen Pool an."""
        self.pool = QuestionPool.objects.create(name="Pool A")
        self.other_pool = QuestionPool.objects.create(name="Pool B")
        self.supervisor = get_user_model().objects.create_user(username="supervisor")
        self.supervisor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("generate", self.pool),
            )
        )
        self.url = reverse("running_tests")

    def make_test(self, pool=None, **fields):
        """Erzeugt einen ausgestellten Test."""
        return TestSession.objects.create(
            question_pool=pool or self.pool,
            otp_hash=make_password("123456"),
            **fields,
        )

    def test_requires_generate_permission(self):
        """Ohne Testerstellungsrecht gibt es keinen Zugriff."""
        self.client.force_login(get_user_model().objects.create_user(username="nobody"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_shows_name_phase_and_remaining_time_only_for_permitted_pools(self):
        """Namen, Phase und Restzeit erscheinen, fremde Pools und Unfertiges nicht."""
        now = timezone.now()
        self.make_test(
            examinee_name="Alex Läuft",
            time_limit_minutes=30,
            otp_verified_at=now - timedelta(minutes=11),
            started_at=now - timedelta(minutes=10),
        )
        self.make_test(
            examinee_name="Bea Bereit", otp_verified_at=now - timedelta(minutes=2)
        )
        self.make_test(otp_verified_at=now - timedelta(minutes=1))
        self.make_test(examinee_name="Nie Gestartet")
        self.make_test(
            pool=self.other_pool,
            examinee_name="Fremder Pool",
            started_at=now,
            otp_verified_at=now,
        )
        self.make_test(
            examinee_name="Fertig",
            status=TestSession.Status.COMPLETED,
            started_at=now,
            otp_verified_at=now,
        )
        self.make_test(
            examinee_name="Verlassen",
            otp_verified_at=now - timedelta(hours=30),
            started_at=now - timedelta(hours=30),
        )
        self.client.force_login(self.supervisor)
        response = self.client.get(self.url)
        self.assertContains(response, "Alex Läuft")
        self.assertContains(response, "Bea Bereit")
        self.assertContains(response, "Name noch nicht eingetragen")
        self.assertContains(response, "Läuft")
        self.assertContains(response, "Startbereit")
        self.assertContains(response, "Zugang bestätigt")
        for hidden in ("Nie Gestartet", "Fremder Pool", "Fertig", "Verlassen"):
            self.assertNotContains(response, hidden)
        running = next(
            row for row in response.context["rows"] if row["phase"] == "running"
        )
        self.assertAlmostEqual(running["remaining_seconds"], 20 * 60, delta=5)
        self.assertEqual(response.context["running_count"], 1)

    def test_expired_test_is_marked(self):
        """Abgelaufene, noch nicht abgegebene Tests werden gekennzeichnet."""
        now = timezone.now()
        self.make_test(
            examinee_name="Zu Spät",
            time_limit_minutes=5,
            started_at=now - timedelta(minutes=9),
            otp_verified_at=now - timedelta(minutes=10),
        )
        self.client.force_login(self.supervisor)
        response = self.client.get(self.url)
        self.assertContains(response, "Zeit abgelaufen")
        self.assertTrue(response.context["rows"][0]["expired"])

    def test_examinee_name_is_visible_right_after_entry(self):
        """Der Name wird beim Eintragen gespeichert, nicht erst bei der Abgabe."""
        test = self.make_test()
        access_url = reverse("take_test", args=[test.pk])
        self.client.post(access_url, {"otp": "123456"})
        self.client.post(access_url, {"examinee_name": "Sofort Sichtbar"})
        test.refresh_from_db()
        self.assertEqual(test.examinee_name, "Sofort Sichtbar")
        self.assertEqual(test.status, TestSession.Status.ISSUED)
        supervisor_client = self.client_class()
        supervisor_client.force_login(self.supervisor)
        self.assertContains(supervisor_client.get(self.url), "Sofort Sichtbar")

    def test_navigation_links_to_running_tests(self):
        """Die Testlauf-Seite bietet den Tab zur Übersicht an."""
        self.client.force_login(self.supervisor)
        self.assertContains(self.client.get(reverse("generate_test")), self.url)
