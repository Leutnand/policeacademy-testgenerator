"""Tests zur Testgenerierung."""

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from ..models import Question, QuestionPool, TestSession
from ..permissions import has_pool_access, pool_permission_codename
from ..services import TestGenerationError, generate_test


class TestGenerationTests(TestCase):
    """Prüft Fragenauswahl und Hashspeicherung bei der Testgenerierung."""

    def setUp(self):
        """Legt Benutzer und einen Pool aus verankerten/normalen Fragen an."""
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="manager", password="test-pass-123"
        )
        self.question_pool, created = QuestionPool.objects.get_or_create(
            name="Einstellungstest"
        )
        _ = created
        self.pinned = [
            Question.objects.create(
                question_pool=self.question_pool,
                text=f"Fix {index}",
                question_type=Question.Type.SHORT,
                answer_key="x",
                is_pinned=True,
            )
            for index in range(2)
        ]
        self.pool = [
            Question.objects.create(
                question_pool=self.question_pool,
                text=f"Pool {index}",
                question_type=Question.Type.SHORT,
                answer_key="x",
            )
            for index in range(4)
        ]

    def test_pinned_questions_are_always_selected_and_otp_is_hashed(self):
        """Alle verankerten Fragen bleiben enthalten und Klartext liegt nicht in DB."""
        test, otp = generate_test(3, self.user, self.question_pool)
        selected = list(test.items.all())
        self.assertEqual(len(selected), 3)
        self.assertEqual(
            {item.source_question_id for item in selected}
            & {item.pk for item in self.pinned},
            {item.pk for item in self.pinned},
        )
        self.assertEqual(len({item.source_question_id for item in selected}), 3)
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())
        self.assertNotEqual(test.otp_hash, otp)
        self.assertTrue(check_password(otp, test.otp_hash))
        self.assertEqual(test.question_pool, self.question_pool)

    def test_question_count_is_random_within_pool_range(self):
        """Ohne Angabe liegt die Fragenzahl innerhalb der Spanne des Pools."""
        self.question_pool.minimum_test_questions = 3
        self.question_pool.maximum_test_questions = 4
        self.question_pool.save()
        counts = {
            generate_test(None, self.user, self.question_pool)[0].items.count()
            for _ in range(30)
        }
        self.assertTrue(counts <= {3, 4})
        self.question_pool.minimum_test_questions = 4
        self.question_pool.maximum_test_questions = 4
        self.question_pool.save()
        test, _otp = generate_test(None, self.user, self.question_pool)
        self.assertEqual(test.items.count(), 4)

    def test_invalid_question_count_is_rejected(self):
        """Unmögliche Testumfänge werden fachlich abgewiesen."""
        with self.assertRaises(TestGenerationError):
            generate_test(1, self.user, self.question_pool)
        with self.assertRaises(TestGenerationError):
            generate_test(99, self.user, self.question_pool)

    def test_generated_test_stores_optional_time_limit(self):
        """Der Generator speichert das ausgewählte Zeitlimit am neuen Testlauf."""
        administrator = get_user_model().objects.create_superuser(
            username="timed-test-admin",
            email="timed@example.com",
            password="strong-password",
        )
        self.client.force_login(administrator)
        response = self.client.post(
            reverse("generate_test"),
            {"question_pool": self.question_pool.pk, "time_limit_minutes": 10},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zeitlimit: 10 Minuten")
        test = TestSession.objects.get(created_by=administrator)
        self.assertEqual(test.time_limit_minutes, 10)

    def test_generated_test_never_mixes_another_pool(self):
        """Sergeant-Test übernimmt nur Fragen aus seinem eigenen Pool."""
        sergeant_pool = QuestionPool.objects.create(name="Sergeant-Test")
        sergeant_questions = [
            Question.objects.create(
                question_pool=sergeant_pool,
                text=f"Sergeant Frage {index}",
                question_type=Question.Type.SHORT,
                answer_key="x",
                is_pinned=True,
            )
            for index in range(2)
        ]
        test, otp = generate_test(2, self.user, sergeant_pool)
        _ = otp
        self.assertEqual(test.question_pool, sergeant_pool)
        self.assertEqual(
            {item.source_question_id for item in test.items.all()},
            {question.pk for question in sergeant_questions},
        )
        self.assertFalse(
            test.items.filter(
                source_question__question_pool=self.question_pool
            ).exists()
        )

    def test_pool_permissions_are_created_updated_and_deleted_with_pool(self):
        """Jeder Pool erhält vier eigene Permissions, die beim Löschen entfernt werden."""
        question_pool = QuestionPool.objects.create(name="Dynamik-Prüfung")
        actions = [
            "view",
            "edit",
            "import_export",
            "generate",
            "submissions",
            "delete",
        ]
        permissions = [
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename(action, question_pool),
            )
            for action in actions
        ]
        self.assertEqual(len(permissions), 6)
        self.assertTrue(
            all(question_pool.name in permission.name for permission in permissions)
        )
        question_pool.name = "Umbenannte Prüfung"
        question_pool.save()
        permissions = [
            Permission.objects.get(pk=permission.pk) for permission in permissions
        ]
        self.assertTrue(
            all(question_pool.name in permission.name for permission in permissions)
        )
        permission_ids = [permission.pk for permission in permissions]
        question_pool.delete()
        self.assertFalse(Permission.objects.filter(pk__in=permission_ids).exists())

    def test_superuser_has_access_to_every_pool(self):
        """Der einzelne Administratorstatus umgeht sämtliche Poolrechte."""
        administrator = get_user_model().objects.create_superuser(
            username="role-admin", password="test-pass-123"
        )
        another_pool = QuestionPool.objects.create(name="Nicht Zugewiesen")
        self.assertTrue(has_pool_access(administrator, another_pool, "view"))
        self.assertTrue(has_pool_access(administrator, another_pool, "edit"))
        self.assertTrue(has_pool_access(administrator, another_pool, "generate"))
        self.assertTrue(has_pool_access(administrator, another_pool, "submissions"))
