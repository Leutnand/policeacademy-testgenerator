"""Tests zu Auswertung, Verwaltungsansichten und Einstellungen."""

from decimal import Decimal
from tempfile import TemporaryDirectory
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from ..models import (
    AuditLog,
    Question,
    QuestionPool,
    StaffProfile,
    Submission,
    TestQuestion,
    TestSession,
    ToolSettings,
)
from ..permissions import pool_permission_codename


class SubmissionAndPoolViewTests(TestCase):
    """Prüft Auswertung, Fragenformular und Prüfungstyp-Verwaltung."""

    def test_delete_is_its_own_pool_permission(self):
        """Löschen (einzeln und mehrfach) braucht view und das eigene Löschrecht, nicht edit."""
        user = get_user_model().objects.create_user(username="bulk", password="x")
        question_pool = QuestionPool.objects.create(name="Bulk-Pool")
        questions = [
            Question.objects.create(
                question_pool=question_pool,
                text=f"Frage {i}",
                question_type=Question.Type.SHORT,
                points=1,
                answer_key="a",
            )
            for i in range(4)
        ]
        bulk_url = reverse("question_bulk_delete", args=[question_pool.pk])
        single_url = reverse("question_delete", args=[questions[3].pk])
        data = {"question_ids": [q.pk for q in questions[:2]]}

        def grant(*actions):
            user.user_permissions.add(
                *[
                    Permission.objects.get(
                        content_type__app_label="core",
                        codename=pool_permission_codename(action, question_pool),
                    )
                    for action in actions
                ]
            )
            self.client.force_login(get_user_model().objects.get(pk=user.pk))

        grant("view", "edit")
        self.assertEqual(self.client.post(bulk_url, data).status_code, 403)
        self.assertEqual(self.client.post(single_url).status_code, 403)
        self.assertEqual(Question.objects.count(), 4)
        grant("delete")
        self.assertEqual(self.client.post(bulk_url, data).status_code, 302)
        self.assertEqual(self.client.post(single_url).status_code, 302)
        self.assertEqual(Question.objects.count(), 1)

    def test_submission_summary_renders_for_authorized_user(self):
        """Zeigt Gesamtpunkte nur nach Prüfung der Auswertungsberechtigung."""
        user = get_user_model().objects.create_user(
            username="reviewer", password="test-pass-123"
        )
        question_pool = QuestionPool.objects.create(name="Ergebnisprüfung")
        submissions_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("submissions", question_pool),
        )
        user.user_permissions.add(submissions_permission)
        test = TestSession.objects.create(
            created_by=user,
            question_pool=question_pool,
            otp_hash=make_password("654321"),
            examinee_name="Cadet Morgan",
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        question = TestQuestion.objects.create(
            test=test,
            position=1,
            text="Ergebnisfrage",
            question_type=Question.Type.SHORT,
            points=2,
            answer_key="Erwartete Musterlösung",
        )
        Submission.objects.create(
            test=test, test_question=question, answer={"value": "ja"}, score=2
        )
        self.client.force_login(user)
        response = self.client.get(reverse("submissions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadet Morgan")
        self.assertNotContains(response, "Ergebnisfrage")
        self.assertContains(response, "2 / 2")
        detail_url = reverse("submission_detail", args=[test.pk])
        response = self.client.get(detail_url)
        self.assertContains(response, "Ergebnisfrage")
        self.assertContains(response, "Musterlösung")
        self.assertContains(response, "Erwartete Musterlösung")
        self.assertContains(response, f'name="score_{test.submissions.get().pk}"')
        self.assertContains(response, 'value="2.00"')
        response = self.client.post(
            detail_url, {f"score_{test.submissions.get().pk}": "1.25"}
        )
        self.assertRedirects(response, f"{detail_url}#score-save-top")
        test.submissions.get().refresh_from_db()
        self.assertEqual(test.submissions.get().score, 1.25)
        self.assertContains(self.client.get(detail_url), "1,25")
        self.assertContains(self.client.get(reverse("submissions")), "1,25 / 2")
        self.assertContains(
            self.client.get(detail_url), f'name="score_{test.submissions.get().pk}"'
        )
        self.assertContains(self.client.get(detail_url), 'value="1.25"')

    def test_bulk_score_save_is_atomic_and_ignores_blank_ungraded_answers(self):
        """Speichert mehrere Punktänderungen gemeinsam, ohne Teilupdates bei ungültigen Werten."""
        user = get_user_model().objects.create_user(username="bulk-reviewer")
        question_pool = QuestionPool.objects.create(name="Gemeinsame Korrektur")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("submissions", question_pool),
            )
        )
        test = TestSession.objects.create(
            created_by=user,
            question_pool=question_pool,
            otp_hash=make_password("131415"),
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        submissions = []
        for position in range(1, 4):
            question = TestQuestion.objects.create(
                test=test,
                position=position,
                text=f"Frage {position}",
                question_type=Question.Type.LONG,
                points=5,
            )
            submissions.append(
                Submission.objects.create(
                    test=test,
                    test_question=question,
                    answer={"value": "Antwort"},
                    score=Decimal("1.00") if position == 1 else None,
                    needs_manual_grading=position > 1,
                )
            )
        self.client.force_login(user)
        detail_url = reverse("submission_detail", args=[test.pk])
        invalid = self.client.post(
            detail_url,
            {
                f"score_{submissions[0].pk}": "3",
                f"score_{submissions[1].pk}": "8",
                f"score_{submissions[2].pk}": "",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        submissions[0].refresh_from_db()
        self.assertEqual(submissions[0].score, Decimal("1.00"))
        self.assertContains(invalid, "Es wurde nichts gespeichert")
        saved = self.client.post(
            detail_url,
            {
                f"score_{submissions[0].pk}": "3",
                f"score_{submissions[1].pk}": "4",
                f"score_{submissions[2].pk}": "",
            },
        )
        self.assertRedirects(saved, f"{detail_url}#score-save-top")
        submissions[0].refresh_from_db()
        submissions[1].refresh_from_db()
        submissions[2].refresh_from_db()
        self.assertEqual(submissions[0].score, Decimal("3"))
        self.assertEqual(submissions[1].score, Decimal("4"))
        self.assertFalse(submissions[1].needs_manual_grading)
        self.assertIsNone(submissions[2].score)
        self.assertTrue(submissions[2].needs_manual_grading)

    def test_choice_review_shows_options_selection_and_correctness(self):
        """Choice-Korrektur markiert gewählte, falsche und ausgelassene Antworten."""
        user = get_user_model().objects.create_user(
            username="choice-reviewer", password="test-pass-123"
        )
        question_pool = QuestionPool.objects.create(name="Choice-Auswertung")
        permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("submissions", question_pool),
        )
        user.user_permissions.add(permission)
        test = TestSession.objects.create(
            created_by=user,
            question_pool=question_pool,
            otp_hash=make_password("246810"),
            examinee_name="Cadet Choice",
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        question = TestQuestion.objects.create(
            test=test,
            position=1,
            text="Welche Funkcodes sind korrekt?",
            question_type=Question.Type.MULTIPLE,
            options=[
                {"text": "Code 1", "is_correct": True},
                {"text": "Code 2", "is_correct": True},
                {"text": "Code 3", "is_correct": False},
            ],
            points=2,
            answer_key="Interne Lösung",
        )
        Submission.objects.create(
            test=test,
            test_question=question,
            answer={"value": ["0", "2"]},
            score=0,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("submission_detail", args=[test.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Code 1")
        self.assertContains(response, "Code 2")
        self.assertContains(response, "Code 3")
        self.assertContains(response, "Angekreuzt · Richtig")
        self.assertContains(response, "Nicht angekreuzt · Richtige Antwort")
        self.assertContains(response, "Angekreuzt · Falsch")
        self.assertContains(response, 'data-selection="selected"')
        self.assertContains(response, 'data-selection="not-selected"')
        self.assertContains(response, ">✓</span>")
        self.assertContains(response, ">×</span>")

    def test_question_form_accepts_rows_and_ignores_options_for_text_questions(self):
        """Auswahlantworten werden strukturiert gespeichert und Freitext bleibt optionsfrei."""
        manager = get_user_model().objects.create_superuser(
            username="question-admin", password="test-pass-123"
        )
        self.client.force_login(manager)
        create_url = reverse("question_create")
        question_pool = QuestionPool.objects.create(name="Fragenformular-Test")
        form_page = self.client.get(create_url)
        self.assertContains(form_page, "Antwortmöglichkeiten")
        self.assertNotContains(form_page, "Antwortoptionen (JSON)")
        short_response = self.client.post(
            create_url,
            {
                "question_pool": str(question_pool.pk),
                "text": "Welcher Funkcode steht für verstanden?",
                "question_type": "short",
                "points": "2",
                "answer_key": "10-4",
                "is_pinned": "on",
                "option_count": "2",
                "option_text_0": "",
                "option_text_1": "",
                "answer_key": "10-4",
            },
        )
        self.assertRedirects(
            short_response, f"{reverse('admin_dashboard')}?pool={question_pool.pk}"
        )
        short_question = Question.objects.get(question_type=Question.Type.SHORT)
        self.assertEqual(short_question.options, [])
        multiple_response = self.client.post(
            create_url,
            {
                "question_pool": str(question_pool.pk),
                "text": "Welche Codes sind Notrufe?",
                "question_type": "multiple",
                "points": "3",
                "answer_key": "",
                "option_count": "3",
                "option_text_0": "Code 3",
                "option_correct_0": "on",
                "option_text_1": "Code 4",
                "option_correct_1": "",
                "option_text_2": "Code 10-13",
                "option_correct_2": "on",
            },
        )
        self.assertRedirects(
            multiple_response, f"{reverse('admin_dashboard')}?pool={question_pool.pk}"
        )
        multiple_question = Question.objects.get(question_type=Question.Type.MULTIPLE)
        self.assertEqual(
            multiple_question.options,
            [
                {"text": "Code 3", "is_correct": True},
                {"text": "Code 4", "is_correct": False},
                {"text": "Code 10-13", "is_correct": True},
            ],
        )

    def test_test_generation_view_requires_pool_and_uses_only_selected_pool(self):
        """Die Testgenerierung verlangt einen Pool und übergibt ihn an den Dienst."""
        manager = get_user_model().objects.create_superuser(
            username="pool-test-admin", password="test-pass-123"
        )
        self.client.force_login(manager)
        first_pool = QuestionPool.objects.create(
            name="Einstellungstest Web", test_question_count=1
        )
        second_pool = QuestionPool.objects.create(
            name="Sergeant-Test Web", test_question_count=1
        )
        Question.objects.create(
            question_pool=first_pool,
            text="Nur Einstellung",
            question_type=Question.Type.SHORT,
            answer_key="A",
        )
        Question.objects.create(
            question_pool=second_pool,
            text="Nur Sergeant",
            question_type=Question.Type.SHORT,
            answer_key="B",
        )
        response = self.client.get(reverse("generate_test"))
        self.assertContains(response, "Prüfungstyp / Fragenpool")
        self.assertContains(response, 'data-question-count="1"')
        self.assertContains(response, 'data-pinned-count="0"')
        response = self.client.post(
            reverse("generate_test"),
            {
                "question_pool": str(second_pool.pk),
                "question_count": "1",
                "time_limit_minutes": "30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Einladung kopieren")
        self.assertContains(response, "Sergeant-Test Web: 1 Fragen · 0 davon verankert")
        test = TestSession.objects.get(question_pool=second_pool)
        self.assertEqual(
            list(test.items.values_list("text", flat=True)), ["Nur Sergeant"]
        )
        self.assertContains(response, "SERGEANT-TEST WEB")

    def test_pool_management_creates_rename_and_protects_used_pool(self):
        """Pools können erstellt/umbenannt, mit Inhalt aber nicht gelöscht werden."""
        manager = get_user_model().objects.create_superuser(
            username="pool-manager", password="test-pass-123"
        )
        self.client.force_login(manager)
        response = self.client.post(
            reverse("pools_dashboard"),
            {
                "name": "Sergeant-Auswahl",
                "description": "Aufstiegstest",
                "test_question_count": "10",
                "pass_percentage": "50",
                "minimum_time_limit_minutes": "5",
                "maximum_time_limit_minutes": "120",
            },
        )
        self.assertRedirects(response, reverse("pools_dashboard"))
        question_pool = QuestionPool.objects.get(name="Sergeant-Auswahl")
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.QUESTION,
                action="question_pool.created",
                object_id=str(question_pool.pk),
            ).exists()
        )
        response = self.client.post(
            reverse("pool_edit", args=[question_pool.pk]),
            {
                "name": "Sergeant-Test",
                "description": "Aufstiegstest",
                "test_question_count": "10",
                "pass_percentage": "50",
                "minimum_time_limit_minutes": "5",
                "maximum_time_limit_minutes": "120",
            },
        )
        self.assertRedirects(response, reverse("pools_dashboard"))
        question_pool.refresh_from_db()
        self.assertEqual(question_pool.name, "Sergeant-Test")
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.QUESTION,
                action="question_pool.updated",
                object_id=str(question_pool.pk),
            ).exists()
        )
        Question.objects.create(
            question_pool=question_pool,
            text="Sergeant only",
            question_type=Question.Type.SHORT,
            answer_key="10-4",
        )
        response = self.client.post(reverse("pool_delete", args=[question_pool.pk]))
        self.assertRedirects(response, reverse("pools_dashboard"))
        self.assertTrue(QuestionPool.objects.filter(pk=question_pool.pk).exists())
        self.assertContains(
            self.client.get(reverse("pools_dashboard")), "Sergeant-Test"
        )


class StaffAndSettingsTests(TestCase):
    """Prüft Mitarbeiteransichten, Datenschutz und Tool-Einstellungen."""

    def test_staff_edit_saves_profile_and_roles(self):
        """Mitarbeiteränderungen speichern Profil, Gruppen und Aktivierungsstatus."""
        manager = get_user_model().objects.create_superuser(
            username="admin-editor", password="test-pass-123"
        )
        staff = get_user_model().objects.create_user(
            username="academy-member", password="old-password"
        )
        role = Group.objects.create(name="RBAC-Test-Fragenredaktion")
        question_pool = QuestionPool.objects.create(name="RBAC-Profilbearbeitung")
        direct_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("view", question_pool),
        )
        staff.user_permissions.add(direct_permission)
        self.client.force_login(manager)
        response = self.client.post(
            reverse("user_edit", args=[staff.pk]),
            {
                "username": "academy-member",
                "first_name": "Riley",
                "last_name": "Officer",
                "is_active": "on",
                "groups": [str(role.pk)],
                "permission_" + str(direct_permission.pk): "on",
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        staff.refresh_from_db()
        self.assertEqual(staff.first_name, "Riley")
        self.assertEqual(
            list(staff.groups.values_list("name", flat=True)),
            ["RBAC-Test-Fragenredaktion"],
        )
        self.assertTrue(staff.is_active)
        self.assertTrue(staff.user_permissions.filter(pk=direct_permission.pk).exists())
        response = self.client.get(reverse("user_edit", args=[staff.pk]))
        self.assertContains(response, "Effektiv geltende Academy-Rechte")
        self.assertContains(response, direct_permission.name)

    def test_staff_create_saves_new_user_and_roles(self):
        """Neue Benutzer werden gespeichert, bevor ihre M2M-Rechte gelesen werden."""
        manager = get_user_model().objects.create_superuser(
            username="admin-create", password="test-pass-123"
        )
        role = Group.objects.create(name="RBAC-Test-Prüfungsleitung")
        self.client.force_login(manager)
        response = self.client.post(
            reverse("user_create"),
            {
                "username": "new-cadet-staff",
                "first_name": "Taylor",
                "last_name": "Cadet",
                "is_active": "on",
                "groups": [str(role.pk)],
                "user_permissions": [],
                "password": "valid-test-password-123",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        created = get_user_model().objects.get(username="new-cadet-staff")
        self.assertTrue(created.check_password("valid-test-password-123"))
        self.assertEqual(
            list(created.groups.values_list("name", flat=True)),
            ["RBAC-Test-Prüfungsleitung"],
        )
        creation_event = AuditLog.objects.get(
            category=AuditLog.Category.STAFF,
            action="staff.created",
            object_id=str(created.pk),
        )
        self.assertEqual(
            creation_event.metadata["groups"], ["RBAC-Test-Prüfungsleitung"]
        )
        self.assertNotIn("valid-test-password-123", str(creation_event.metadata))
        for description, metadata in AuditLog.objects.values_list(
            "description", "metadata"
        ):
            self.assertNotIn("valid-test-password-123", description)
            self.assertNotIn("valid-test-password-123", str(metadata))

    def test_user_list_includes_and_allows_editing_current_administrator(self):
        """Die Mitarbeiterliste zeigt den eigenen Superuser und seine Bearbeitung."""
        manager = get_user_model().objects.create_superuser(
            username="admin-list", password="test-pass-123"
        )
        self.client.force_login(manager)
        response = self.client.get(reverse("users_dashboard"))
        self.assertContains(response, "admin-list")
        self.assertContains(response, "Administrator · Alle Rechte")
        self.assertEqual(
            response.content.decode().count("Administrator · Alle Rechte"), 1
        )
        self.assertContains(response, reverse("user_edit", args=[manager.pk]))
        self.assertEqual(
            self.client.get(reverse("user_edit", args=[manager.pk])).status_code, 200
        )
        response = self.client.post(
            reverse("user_edit", args=[manager.pk]),
            {
                "username": "admin-list",
                "is_active": "on",
                "groups": [],
                "user_permissions": [],
                "password": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        manager.refresh_from_db()
        self.assertTrue(manager.is_superuser)

    def test_staff_admin_switch_grants_all_application_permissions(self):
        """Der Administrator-Schalter aktiviert Superuser mit allen Fachrechten."""
        manager = get_user_model().objects.create_superuser(
            username="admin-role-manager", password="test-pass-123"
        )
        self.client.force_login(manager)
        response = self.client.post(
            reverse("user_create"),
            {
                "username": "academy-admin",
                "first_name": "Academy",
                "last_name": "Admin",
                "is_administrator": "on",
                "is_active": "on",
                "groups": [],
                "user_permissions": [],
                "password": "strong-enough-password-123",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        created = get_user_model().objects.get(username="academy-admin")
        self.assertTrue(created.is_superuser)
        self.assertTrue(created.is_staff)
        self.assertTrue(created.has_perm("core.can_manage_users"))
        self.assertTrue(created.has_perm("core.can_delete_tests"))
        self.assertTrue(created.has_perm("core.can_view_audit_logs"))
        self.assertNotContains(
            self.client.get(reverse("user_edit", args=[created.pk])), "E-Mail-Adresse"
        )

    def test_audit_log_permission_is_separate_and_http_access_is_recorded(self):
        """Nur die eigene Logberechtigung öffnet Systemlogs; Zugriffe werden erfasst."""
        user = get_user_model().objects.create_user(
            username="log-reader", password="test-pass-123"
        )
        self.client.force_login(user)
        log_url = reverse("audit_logs")
        self.assertEqual(self.client.get(log_url).status_code, 403)
        permission = Permission.objects.get(
            content_type__app_label="core", codename="can_view_audit_logs"
        )
        user.user_permissions.add(permission)
        response = self.client.get(log_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Systemprotokoll")
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.REQUEST, object_id="audit_logs"
            ).exists()
        )

    def test_first_staff_access_requires_current_privacy_policy_confirmation(self):
        """Mitarbeiter bleiben bis zur Bestätigung der aktuellen Fassung gesperrt."""
        administrator = get_user_model().objects.create_superuser(
            username="privacy-admin"
        )
        configuration = ToolSettings.current()
        configuration.privacy_policy = "Datenschutzerklärung Fassung eins."
        configuration.save()
        self.client.force_login(administrator)

        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("privacy_accept"))
        self.assertContains(
            self.client.get(reverse("privacy_accept")),
            "Datenschutzerklärung Fassung eins.",
        )
        response = self.client.post(reverse("privacy_accept"), {"accepted": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))
        self.assertEqual(self.client.get(reverse("tool_settings")).status_code, 200)
        self.assertTrue(
            StaffProfile.objects.get(user=administrator).accepted_privacy_hash
        )

        configuration.privacy_policy = "Datenschutzerklärung Fassung zwei."
        configuration.save()
        self.assertRedirects(
            self.client.get(reverse("dashboard")), reverse("privacy_accept")
        )
        self.assertEqual(self.client.get(reverse("privacy_policy")).status_code, 200)

    def test_tool_settings_are_admin_only_and_control_login_and_question_limits(self):
        """Admins konfigurieren Oberfläche und Testgrenzen; andere Mitarbeiter sind ausgeschlossen."""
        administrator = get_user_model().objects.create_superuser(
            username="configuration-admin"
        )
        self.client.force_login(administrator)
        response = self.client.post(
            reverse("tool_settings"),
            {
                "site_name": "Academy Prüfungen",
                "department_name": "San Andreas Training",
                "login_page_heading": "Sicher trainieren",
                "login_page_text": "Bitte mit Teamkonto anmelden.",
                "privacy_policy": "",
                "imprint": "San Andreas Police Department",
            },
        )
        self.assertRedirects(response, reverse("tool_settings"))
        configuration = ToolSettings.objects.get(pk=1)
        self.assertEqual(configuration.site_name, "Academy Prüfungen")
        self.client.logout()
        self.assertContains(self.client.get(reverse("login")), "Sicher trainieren")
        self.assertContains(
            self.client.get(reverse("privacy_policy")), "San Andreas Police Department"
        )

        question_pool = QuestionPool.objects.create(
            name="Fragenlimit", test_question_count=2
        )
        Question.objects.create(
            question_pool=question_pool,
            text="Eine Frage",
            question_type=Question.Type.SHORT,
        )
        administrator.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("generate", question_pool),
            )
        )
        self.client.force_login(administrator)
        settings_page = self.client.get(reverse("tool_settings"))
        self.assertContains(settings_page, "VORSCHAU ANMELDESEITE")
        self.assertContains(settings_page, "data-original-privacy")
        response = self.client.post(
            reverse("generate_test"),
            {"question_pool": str(question_pool.pk), "time_limit_minutes": "10"},
        )
        self.assertContains(response, "feste Fragenzahl")
        self.assertFalse(TestSession.objects.filter(question_pool=question_pool).exists())
        response = self.client.post(
            reverse("pool_edit", args=[question_pool.pk]),
            {
                "name": "Fragenlimit",
                "description": "",
                "test_question_count": "1",
                "pass_percentage": "50",
                "minimum_time_limit_minutes": "50",
                "maximum_time_limit_minutes": "20",
            },
        )
        self.assertEqual(response.status_code, 200)
        question_pool.refresh_from_db()
        self.assertEqual(question_pool.test_question_count, 2)
        response = self.client.post(
            reverse("tool_settings"),
            {
                "site_name": "Ungültig",
                "department_name": "Department",
                "login_page_heading": "Überschrift",
                "login_page_text": "Text",
                "privacy_policy": "",
                "imprint": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        employee = get_user_model().objects.create_user(username="settings-employee")
        self.client.force_login(employee)
        self.assertEqual(self.client.get(reverse("tool_settings")).status_code, 403)
        settings_permission = Permission.objects.get(
            content_type__app_label="core",
            codename="can_manage_tool_settings",
        )
        employee.user_permissions.add(settings_permission)
        self.assertEqual(self.client.get(reverse("tool_settings")).status_code, 200)
        response = self.client.post(
            reverse("tool_settings"),
            {
                "site_name": "Delegierte Einstellungen",
                "department_name": "Department",
                "login_page_heading": "Heading",
                "login_page_text": "Login",
                "privacy_policy": "",
                "imprint": "",
            },
        )
        self.assertRedirects(response, reverse("tool_settings"))
        self.assertEqual(
            ToolSettings.objects.get(pk=1).site_name, "Delegierte Einstellungen"
        )

    def test_csv_access_is_independently_grantable_per_question_pool(self):
        """CSV-Zugriff pro Pool kann getrennt von Fragebearbeitung delegiert werden."""
        user = get_user_model().objects.create_user(username="csv-delegated")
        question_pool = QuestionPool.objects.create(name="Separates CSV-Recht")
        question = Question.objects.create(
            question_pool=question_pool,
            text="Kurzfrage",
            question_type=Question.Type.SHORT,
            answer_key="Antwort",
        )
        user.user_permissions.add(
            *[
                Permission.objects.get(
                    content_type__app_label="core",
                    codename=pool_permission_codename(action, question_pool),
                )
                for action in ("view", "import_export")
            ]
        )
        self.client.force_login(user)
        dashboard = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "CSV exportieren")
        self.assertContains(dashboard, "CSV importieren")
        self.assertNotContains(dashboard, reverse("question_create"))
        self.assertEqual(
            self.client.get(
                reverse("question_export", args=[question_pool.pk]),
            ).status_code,
            200,
        )
        csv_body = (
            "text,question_type,points,answer_key,is_pinned,options_json\n"
            "Neue Frage,short,1,Erwartet,false,[]\n"
        )
        uploaded = SimpleUploadedFile(
            "questions.csv",
            csv_body.encode("utf-8"),
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("question_import", args=[question_pool.pk]),
            {"file": uploaded},
        )
        self.assertRedirects(
            response, f"{reverse('admin_dashboard')}?pool={question_pool.pk}"
        )
        self.assertEqual(
            Question.objects.filter(question_pool=question_pool).count(), 2
        )
        user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("import_export", question_pool),
            )
        )
        self.assertEqual(
            self.client.get(
                reverse("question_export", args=[question_pool.pk]),
            ).status_code,
            403,
        )

    def test_site_icon_upload_is_validated_and_served_from_media_storage(self):
        """Ein gültiges kleines PNG wird gespeichert und als Bild statt Upload-URL ausgeliefert."""
        administrator = get_user_model().objects.create_superuser(username="icon-admin")
        self.client.force_login(administrator)
        image_bytes = b"\x89PNG\r\n\x1a\nacademy-icon"
        with TemporaryDirectory(dir=settings.BASE_DIR) as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("tool_settings"),
                    {
                        "site_name": "Icon-Test",
                        "department_name": "Department",
                        "login_page_heading": "Heading",
                        "login_page_text": "Login",
                        "privacy_policy": "",
                        "imprint": "",
                        "site_icon": SimpleUploadedFile(
                            "academy.png",
                            image_bytes,
                            content_type="image/png",
                        ),
                    },
                )
                self.assertRedirects(response, reverse("tool_settings"))
                icon_response = self.client.get(reverse("site_icon"))
                self.assertEqual(icon_response.status_code, 200)
                self.assertEqual(icon_response["Content-Type"], "image/png")
                self.assertEqual(icon_response["X-Content-Type-Options"], "nosniff")
                self.assertEqual(b"".join(icon_response.streaming_content), image_bytes)

    def test_test_deletion_requires_permission_and_keeps_security_audit(self):
        """Testlöschung ist berechtigt, kaskadiert Antworten und hinterlässt Log."""
        creator = get_user_model().objects.create_user(
            username="test-owner", password="test-pass-123"
        )
        test = TestSession.objects.create(
            created_by=creator,
            question_pool=QuestionPool.objects.create(name="Löschprüfung"),
            otp_hash=make_password("555111"),
            examinee_name="Cadet Delete",
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        TestQuestion.objects.create(
            test=test,
            position=1,
            text="Delete test question",
            question_type=Question.Type.SHORT,
            points=1,
        )
        Submission.objects.create(
            test=test, test_question=test.items.get(), answer={"value": "x"}, score=0
        )
        delete_url = reverse("delete_test", args=[test.pk])
        viewer = get_user_model().objects.create_user(
            username="viewer-only", password="test-pass-123"
        )
        viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("submissions", test.question_pool),
            )
        )
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        self.assertTrue(TestSession.objects.filter(pk=test.pk).exists())
        admin = get_user_model().objects.create_superuser(
            username="delete-admin", password="test-pass-123"
        )
        self.client.force_login(admin)
        response = self.client.post(delete_url)
        self.assertRedirects(response, reverse("submissions"))
        self.assertFalse(TestSession.objects.filter(pk=test.pk).exists())
        self.assertFalse(Submission.objects.filter(test_id=test.pk).exists())
        event = AuditLog.objects.get(
            category=AuditLog.Category.SECURITY,
            action="test.deleted",
            object_id=str(test.pk),
        )
        self.assertEqual(event.actor, admin)
