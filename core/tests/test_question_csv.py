"""Tests zu CSV-Import und -Export."""

import csv
import io
import json
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from ..models import Question, QuestionPool
from ..permissions import pool_permission_codename


class QuestionCsvTests(TestCase):
    """Prüft CSV-Export, ergänzenden Import und Poolberechtigungen."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="csv-admin",
            email="csv@example.com",
            password="strong-password",
        )
        self.question_pool = QuestionPool.objects.create(name="CSV-Importtest")
        self.question = Question.objects.create(
            question_pool=self.question_pool,
            text="Welche Antwort stimmt?",
            question_type=Question.Type.SINGLE,
            points=Decimal("2.50"),
            answer_key="Interne Notiz",
            is_pinned=True,
            options=[
                {"text": "Richtig", "is_correct": True},
                {"text": "Falsch", "is_correct": False},
            ],
        )
        self.client.force_login(self.user)

    def test_exported_question_is_skipped_as_duplicate_on_reimport(self):
        """Der Export ist verlustfrei und erneuter Import erstellt keine identische Frage."""
        response = self.client.get(
            reverse("question_export", args=[self.question_pool.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        exported_rows = list(
            csv.reader(
                io.StringIO(response.content.decode("utf-8-sig"), newline=""),
                delimiter=";",
            )
        )
        self.assertEqual(len(exported_rows[0]), 6)
        self.assertEqual(exported_rows[0][0], "text")
        self.assertEqual(len(exported_rows[1]), 6)
        imported_file = SimpleUploadedFile(
            "questions.csv",
            response.content,
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("question_import", args=[self.question_pool.pk]),
            {"file": imported_file},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 identisches Duplikat wurde übersprungen.")
        self.assertEqual(
            Question.objects.filter(question_pool=self.question_pool).count(), 1
        )

    def test_import_accepts_legacy_comma_delimited_csv(self):
        """Ältere CSV-Dateien bleiben importierbar und Duplikate innerhalb der Datei werden ausgelassen."""
        contents = (
            "text,question_type,points,answer_key,is_pinned,options_json\r\n"
            'Legacy-Frage,short,1,,false,"[]"\r\n'
            'Legacy-Frage,short,1,,false,"[]"\r\n'
        )
        upload = SimpleUploadedFile(
            "legacy.csv",
            contents.encode("utf-8"),
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("question_import", args=[self.question_pool.pk]),
            {"file": upload},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 identisches Duplikat wurde übersprungen.")
        self.assertEqual(
            Question.objects.filter(
                question_pool=self.question_pool,
                text="Legacy-Frage",
            ).count(),
            1,
        )

    def test_same_text_with_different_settings_is_not_treated_as_duplicate(self):
        """Gleichlautende Fragen mit abweichender Punktzahl bleiben getrennte Fragen."""
        contents = io.StringIO(newline="")
        writer = csv.writer(contents, delimiter=";")
        writer.writerow(
            (
                "text",
                "question_type",
                "points",
                "answer_key",
                "is_pinned",
                "options_json",
            )
        )
        writer.writerow(
            (
                self.question.text,
                "single",
                "3.00",
                self.question.answer_key,
                "true",
                json.dumps(self.question.options, separators=(",", ":")),
            )
        )
        upload = SimpleUploadedFile(
            "different-settings.csv",
            contents.getvalue().encode("utf-8"),
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("question_import", args=[self.question_pool.pk]),
            {"file": upload},
        )
        self.assertRedirects(
            response, f"{reverse('admin_dashboard')}?pool={self.question_pool.pk}"
        )
        self.assertEqual(
            Question.objects.filter(
                question_pool=self.question_pool,
                text=self.question.text,
            ).count(),
            2,
        )

    def test_invalid_csv_is_atomic_and_export_requires_edit_permission(self):
        """Fehlerhafte CSV-Zeilen erzeugen keine Teilimporte; Leserecht allein reicht nicht."""
        text = (
            "text,question_type,points,answer_key,is_pinned,options_json\n"
            "Gültige Frage,short,1,,false,[]\n"
            'Ungültige Frage,single,1,,false,"not-json"\n'
        )
        upload = SimpleUploadedFile(
            "questions.csv", text.encode("utf-8"), content_type="text/csv"
        )
        response = self.client.post(
            reverse("question_import", args=[self.question_pool.pk]),
            {"file": upload},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Question.objects.filter(question_pool=self.question_pool).count(), 1
        )

        viewer = get_user_model().objects.create_user(
            username="csv-viewer", password="strong-password"
        )
        viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("view", self.question_pool),
            )
        )
        self.client.force_login(viewer)
        self.assertEqual(
            self.client.get(
                reverse("question_export", args=[self.question_pool.pk])
            ).status_code,
            403,
        )
