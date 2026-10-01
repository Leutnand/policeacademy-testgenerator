"""Automatisierte Regressionstests für Auswahl, Geheimnisse, RBAC und OTP."""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from .models import AuditLog, Question, QuestionPool, Submission, TestQuestion, TestSession
from .permissions import ADMINISTRATOR_GROUP, has_pool_access, pool_permission_codename
from .audit import prune_audit_logs
from .services import TestGenerationError, generate_test


class TestGenerationTests(TestCase):
    """Prüft Fragenauswahl und Hashspeicherung bei der Testgenerierung."""
    def setUp(self):
        """Legt Benutzer und einen Pool aus verankerten/normalen Fragen an."""
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="manager", password="test-pass-123")
        self.question_pool, created = QuestionPool.objects.get_or_create(name="Einstellungstest")
        _ = created
        self.pinned = [Question.objects.create(question_pool=self.question_pool, text=f"Fix {index}", question_type=Question.Type.SHORT, answer_key="x", is_pinned=True) for index in range(2)]
        self.pool = [Question.objects.create(question_pool=self.question_pool, text=f"Pool {index}", question_type=Question.Type.SHORT, answer_key="x") for index in range(4)]

    def test_pinned_questions_are_always_selected_and_otp_is_hashed(self):
        """Alle verankerten Fragen bleiben enthalten und Klartext liegt nicht in DB."""
        test, otp = generate_test(3, self.user, self.question_pool)
        selected = list(test.items.all())
        self.assertEqual(len(selected), 3)
        self.assertEqual({item.source_question_id for item in selected} & {item.pk for item in self.pinned}, {item.pk for item in self.pinned})
        self.assertEqual(len({item.source_question_id for item in selected}), 3)
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())
        self.assertNotEqual(test.otp_hash, otp)
        self.assertTrue(check_password(otp, test.otp_hash))
        self.assertEqual(test.question_pool, self.question_pool)

    def test_invalid_question_count_is_rejected(self):
        """Unmögliche Testumfänge werden fachlich abgewiesen."""
        with self.assertRaises(TestGenerationError):
            generate_test(1, self.user, self.question_pool)
        with self.assertRaises(TestGenerationError):
            generate_test(99, self.user, self.question_pool)

    def test_generated_test_never_mixes_another_pool(self):
        """Sergeant-Test übernimmt nur Fragen aus seinem eigenen Pool."""
        sergeant_pool = QuestionPool.objects.create(name="Sergeant-Test")
        sergeant_questions = [
            Question.objects.create(question_pool=sergeant_pool, text=f"Sergeant Frage {index}",
                                    question_type=Question.Type.SHORT, answer_key="x", is_pinned=True)
            for index in range(2)
        ]
        test, otp = generate_test(2, self.user, sergeant_pool)
        _ = otp
        self.assertEqual(test.question_pool, sergeant_pool)
        self.assertEqual({item.source_question_id for item in test.items.all()}, {question.pk for question in sergeant_questions})
        self.assertFalse(test.items.filter(source_question__question_pool=self.question_pool).exists())

    def test_pool_permissions_are_created_updated_and_deleted_with_pool(self):
        """Jeder Pool erhält vier eigene Permissions, die beim Löschen entfernt werden."""
        question_pool = QuestionPool.objects.create(name="Dynamik-Prüfung")
        actions = ["view", "edit", "generate", "submissions"]
        permissions = [
            Permission.objects.get(content_type__app_label="core", codename=pool_permission_codename(action, question_pool))
            for action in actions
        ]
        self.assertEqual(len(permissions), 4)
        self.assertTrue(all(question_pool.name in permission.name for permission in permissions))
        question_pool.name = "Umbenannte Prüfung"
        question_pool.save()
        permissions = [Permission.objects.get(pk=permission.pk) for permission in permissions]
        self.assertTrue(all(question_pool.name in permission.name for permission in permissions))
        permission_ids = [permission.pk for permission in permissions]
        question_pool.delete()
        self.assertFalse(Permission.objects.filter(pk__in=permission_ids).exists())

    def test_superuser_has_access_to_every_pool(self):
        """Der einzelne Administratorstatus umgeht sämtliche Poolrechte."""
        administrator = get_user_model().objects.create_superuser(username="role-admin", password="test-pass-123")
        another_pool = QuestionPool.objects.create(name="Nicht Zugewiesen")
        self.assertTrue(has_pool_access(administrator, another_pool, "view"))
        self.assertTrue(has_pool_access(administrator, another_pool, "edit"))
        self.assertTrue(has_pool_access(administrator, another_pool, "generate"))
        self.assertTrue(has_pool_access(administrator, another_pool, "submissions"))


class ApplicantFlowTests(TestCase):
    """Prüft Prüflingsausgabe, Abgabe und Einmaligkeit des Zugangs."""
    def setUp(self):
        """Erzeugt einen Test mit Choice- und Freitextfrage."""
        self.user = get_user_model().objects.create_user(username="owner", password="test-pass-123")
        self.question_pool = QuestionPool.objects.create(name="Academy-Grundtest")
        # Der Test wird direkt erzeugt, damit die Testfragen den Lösungsschlüssel abdecken.
        from django.contrib.auth.hashers import make_password
        self.test = TestSession.objects.create(created_by=self.user, question_pool=self.question_pool, otp_hash=make_password("123456"))
        TestQuestion.objects.create(test=self.test, position=1, text="Welche Option?", question_type=Question.Type.SINGLE,
                                    options=[{"text": "Richtig", "is_correct": True}, {"text": "Falsch", "is_correct": False}], points=2, answer_key="intern")
        TestQuestion.objects.create(test=self.test, position=2, text="Begründe.", question_type=Question.Type.LONG,
                                    points=5, answer_key="Geheime Musterlösung")

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
        self.assertNotContains(response, "Geheime Musterlösung")
        self.assertNotContains(response, "is_correct")
        self.assertNotContains(response, "5.00")
        response = self.client.post(access_url, {"question_1": "0", "question_2": "Ausführliche Antwort"})
        self.assertContains(response, "Alles angekommen.")
        self.test.refresh_from_db()
        self.assertEqual(self.test.status, TestSession.Status.COMPLETED)
        self.assertEqual(self.test.examinee_name, "Alex Morgan")
        self.assertEqual(Submission.objects.count(), 2)
        self.assertEqual(Submission.objects.get(test_question__position=1).score, 2)
        self.assertTrue(Submission.objects.get(test_question__position=2).needs_manual_grading)
        self.assertEqual(self.client.get(access_url).status_code, 410)

    def test_wrong_otp_does_not_authorize_applicant(self):
        """Ein falsches Einmalpasswort gibt weder Fragen noch Zugang frei."""
        response = self.client.post(reverse("take_test", args=[self.test.pk]), {"otp": "000000"})
        self.assertContains(response, "ungültig")
        self.assertNotContains(response, "Welche Option?")
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.REQUEST,
            object_id="take_test",
            description__contains=str(self.test.pk),
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.SECURITY,
            action="test.otp.rejected",
            object_id=str(self.test.pk),
        ).exists())


class PermissionTests(TestCase):
    """Prüft serverseitige Rechte unabhängig von ausgeblendeten UI-Aktionen."""
    def test_question_pool_requires_custom_permission(self):
        """Fragenübersicht wird erst durch das konkrete Pool-View-Recht geöffnet."""
        user = get_user_model().objects.create_user(username="editor", password="test-pass-123")
        question_pool = QuestionPool.objects.create(name="RBAC-Fragenpool")
        url = reverse("admin_dashboard")
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 403)
        permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("view", question_pool),
        )
        user.user_permissions.add(permission)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("question_create"))
        edit_permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("edit", question_pool),
        )
        user.user_permissions.add(edit_permission)
        self.assertContains(self.client.get(url), reverse("question_create"))

    def test_pool_question_and_test_views_are_isolated_by_dynamic_permissions(self):
        """Fragenbank, Generierung und Abgaben zeigen nur explizit erlaubte Pools."""
        user = get_user_model().objects.create_user(username="pool-scoped", password="test-pass-123")
        view_pool = QuestionPool.objects.create(name="Sichtbarer Pool")
        generate_pool = QuestionPool.objects.create(name="Generierbarer Pool")
        hidden_pool = QuestionPool.objects.create(name="Privater Pool")
        Question.objects.create(question_pool=view_pool, text="Sichtbare Frage", question_type=Question.Type.SHORT, answer_key="X")
        Question.objects.create(question_pool=hidden_pool, text="Versteckte Frage", question_type=Question.Type.SHORT, answer_key="Y")
        visible_test = TestSession.objects.create(
            created_by=user, question_pool=view_pool, otp_hash=make_password("111222"),
            examinee_name="Visible Cadet", status=TestSession.Status.COMPLETED, completed_at=timezone.now(),
        )
        hidden_test = TestSession.objects.create(
            created_by=user, question_pool=hidden_pool, otp_hash=make_password("333444"),
            examinee_name="Hidden Cadet", status=TestSession.Status.COMPLETED, completed_at=timezone.now(),
        )
        user.user_permissions.add(*[
            Permission.objects.get(content_type__app_label="core", codename=pool_permission_codename(action, pool))
            for action, pool in [("view", view_pool), ("submissions", view_pool), ("generate", generate_pool)]
        ])
        self.client.force_login(user)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "Sichtbarer Pool")
        self.assertNotContains(response, "Privater Pool")
        self.assertNotContains(response, "Versteckte Frage")
        self.assertNotContains(response, reverse("question_create"))
        self.assertEqual(self.client.get(f"{reverse('admin_dashboard')}?pool={hidden_pool.pk}").status_code, 403)
        generation = self.client.get(reverse("generate_test"))
        self.assertContains(generation, "Generierbarer Pool")
        self.assertNotContains(generation, "Privater Pool")
        self.assertEqual(self.client.post(reverse("generate_test"), {
            "question_pool": str(hidden_pool.pk), "question_count": "1",
        }).status_code, 403)
        response = self.client.get(reverse("submissions"))
        self.assertContains(response, "Visible Cadet")
        self.assertNotContains(response, "Hidden Cadet")
        self.assertEqual(self.client.get(reverse("submission_detail", args=[hidden_test.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("submission_detail", args=[visible_test.pk])).status_code, 200)

    def test_custom_group_can_grant_a_dynamic_pool_permission(self):
        """Freie Gruppen verwalten Rechte und deren Mitglieder erhalten exakt diese Poolfreigabe."""
        administrator = get_user_model().objects.create_superuser(username="rights-admin", password="test-pass-123")
        question_pool = QuestionPool.objects.create(name="Patrol Sergeant")
        permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("generate", question_pool),
        )
        self.client.force_login(administrator)
        Group.objects.create(name=ADMINISTRATOR_GROUP)
        rights_home = self.client.get(reverse("permissions_dashboard"))
        self.assertEqual(rights_home.status_code, 200)
        self.assertContains(rights_home, "Rechtegruppen")
        self.assertContains(rights_home, "0 Rechtegruppen")
        self.assertContains(rights_home, "Rechtegruppen")
        self.assertNotContains(rights_home, "Reservierte Administratorrolle")
        group_form = self.client.get(reverse("permission_group_create"))
        self.assertContains(group_form, f"Pool · {question_pool.name}")
        self.assertContains(group_form, "Tests aus diesem Pool generieren")
        self.assertContains(group_form, "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.")
        self.assertContains(group_form, "Erfordert Mitarbeiterverwaltung und erlaubt kein Vergeben.")
        self.assertContains(group_form, "Betrifft gespeicherte Browser-Sitzungen, nicht die Anmeldung oder Academy-Rechte.")
        self.assertContains(group_form, "Benutzerkonto anlegen")
        self.assertContains(group_form, "Django-Framework · technische Metadaten")
        self.assertContains(group_form, "Django-Framework · Anmeldesitzungen")
        section_titles = list(group_form.context["permission_sections"])
        self.assertEqual(section_titles[0]["title"], "Globale Academy-Rechte")
        pool_titles = [section["title"] for section in section_titles if section["title"].startswith("Pool · ")]
        self.assertEqual(pool_titles, sorted(pool_titles, key=str.casefold))
        self.assertIn(f"Pool · {question_pool.name}", pool_titles)
        shown_permission_ids = [
            item["permission"].pk
            for section in section_titles
            for item in section["fields"]
        ]
        self.assertEqual(len(shown_permission_ids), len(set(shown_permission_ids)))
        self.assertEqual(set(shown_permission_ids), set(Permission.objects.values_list("pk", flat=True)))
        self.assertNotContains(group_form, "can_view_pool_")
        response = self.client.post(reverse("permission_group_create"), {
            "name": "Sergeant Prüfer", f"permission_{permission.pk}": "on",
        })
        self.assertRedirects(response, reverse("permissions_dashboard"))
        role = Group.objects.get(name="Sergeant Prüfer")
        self.assertTrue(role.permissions.filter(pk=permission.pk).exists())
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.STAFF,
            action="permission_group.created",
            object_id=str(role.pk),
        ).exists())
        response = self.client.post(reverse("permission_group_edit", args=[role.pk]), {
            "name": role.name, f"permission_{permission.pk}": "on",
        })
        self.assertRedirects(response, reverse("permissions_dashboard"))
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.STAFF,
            action="permission_group.updated",
            object_id=str(role.pk),
        ).exists())
        employee = get_user_model().objects.create_user(username="sergeant-staff", password="test-pass-123")
        employee.groups.add(role)
        self.assertTrue(has_pool_access(employee, question_pool, "generate"))
        self.assertFalse(has_pool_access(employee, question_pool, "view"))
        view_permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("view", question_pool),
        )
        user_rights_form = self.client.get(reverse("permission_user_edit", args=[employee.pk]))
        self.assertContains(user_rights_form, f"Pool · {question_pool.name}")
        self.assertContains(user_rights_form, "Zusätzlich braucht das Konto Adminzugang (is_staff)")
        self.assertContains(user_rights_form, "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.")
        response = self.client.post(reverse("permission_user_edit", args=[employee.pk]), {
            "username": employee.username, "first_name": "", "last_name": "", "is_active": "on",
            "is_administrator": "", "groups": [str(role.pk)], "password": "",
            f"permission_{view_permission.pk}": "on",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee = get_user_model().objects.get(pk=employee.pk)
        self.assertTrue(has_pool_access(employee, question_pool, "view"))
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.STAFF,
            action="staff.permissions.updated",
            object_id=str(employee.pk),
        ).exists())

    def test_standard_legacy_groups_are_not_recreated(self):
        """Es existiert keine fest verdrahtete Rolle außer Administrator."""
        self.assertFalse(Group.objects.filter(name=ADMINISTRATOR_GROUP).exists())
        self.assertFalse(Group.objects.filter(name__in=["Fragen-Editor", "Test-Manager", "Korrektor"]).exists())
        self.assertFalse(Permission.objects.filter(
            content_type__app_label="core", content_type__model="question",
            codename__in=[
                "can_manage_questions", "can_generate_tests", "can_view_submissions", "can_grade_submissions",
                "can_manage_users", "can_delete_tests", "can_view_audit_logs",
            ],
        ).exists())

    def test_rights_manager_is_admin_only(self):
        """Benutzer mit reiner Benutzerverwaltung dürfen keine Permissions delegieren."""
        manager = get_user_model().objects.create_user(username="non-admin-manager", password="test-pass-123")
        manager.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="can_manage_users"))
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("permissions_dashboard")).status_code, 403)

    def test_user_permission_grant_and_revoke_are_separately_authorized(self):
        """Nutzerrechte und Gruppen lassen sich nur mit Grant-/Revoke-Recht ändern."""
        manager = get_user_model().objects.create_user(username="delegated-rights-manager")
        manager.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["can_manage_users", "can_grant_user_permissions"],
        ))
        employee = get_user_model().objects.create_user(username="delegated-rights-target")
        role = Group.objects.create(name="Delegierte Prüfer")
        protected_role = Group.objects.create(name="Geschützte Audit-Verwalter")
        protected_role.permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="can_clear_audit_logs",
        ))
        employee.groups.add(protected_role)
        direct_permission = Permission.objects.get(content_type__app_label="core", codename="change_question")
        protected_permission = Permission.objects.get(
            content_type__app_label="core", codename="can_grant_administrator",
        )
        forbidden_permission = Permission.objects.get(
            content_type__app_label="core", codename="can_revoke_administrator",
        )
        employee.user_permissions.add(protected_permission)
        self.client.force_login(manager)
        edit_url = reverse("permission_user_edit", args=[employee.pk])
        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "", "is_active": "on",
            "is_administrator": "", "groups": [str(role.pk)], "password": "",
            f"permission_{direct_permission.pk}": "on",
            f"permission_{forbidden_permission.pk}": "on",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(employee.user_permissions.filter(pk=direct_permission.pk).exists())
        self.assertTrue(employee.groups.filter(pk=role.pk).exists())
        self.assertTrue(employee.user_permissions.filter(pk=protected_permission.pk).exists())
        self.assertFalse(employee.user_permissions.filter(pk=forbidden_permission.pk).exists())
        self.assertTrue(employee.groups.filter(pk=protected_role.pk).exists())

        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "", "is_active": "on",
            "is_administrator": "", "groups": [], "password": "",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(employee.user_permissions.filter(pk=direct_permission.pk).exists())
        self.assertTrue(employee.groups.filter(pk=role.pk).exists())

        manager.user_permissions.remove(Permission.objects.get(
            content_type__app_label="core", codename="can_grant_user_permissions",
        ))
        manager.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="can_revoke_user_permissions",
        ))
        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "", "is_active": "on",
            "is_administrator": "", "groups": [], "password": "",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertFalse(employee.user_permissions.filter(pk=direct_permission.pk).exists())
        self.assertFalse(employee.groups.filter(pk=role.pk).exists())
        self.assertTrue(employee.user_permissions.filter(pk=protected_permission.pk).exists())
        self.assertTrue(employee.groups.filter(pk=protected_role.pk).exists())

    def test_administrator_grant_and_revoke_are_separately_authorized(self):
        """Administratorstatus kann getrennt vergeben und wieder entzogen werden."""
        manager = get_user_model().objects.create_user(username="admin-delegation-manager")
        manager.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["can_manage_users", "can_grant_administrator"],
        ))
        employee = get_user_model().objects.create_user(username="admin-delegation-target")
        self.client.force_login(manager)
        edit_url = reverse("user_edit", args=[employee.pk])
        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "",
            "is_administrator": "on", "is_active": "on", "groups": [], "password": "",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(employee.is_superuser)

        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "",
            "is_administrator": "", "is_active": "on", "groups": [], "password": "",
        })
        self.assertEqual(response.status_code, 403)
        employee.refresh_from_db()
        self.assertTrue(employee.is_superuser)

        manager.user_permissions.remove(Permission.objects.get(
            content_type__app_label="core", codename="can_grant_administrator",
        ))
        manager.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="can_revoke_administrator",
        ))
        response = self.client.post(edit_url, {
            "username": employee.username, "first_name": "", "last_name": "",
            "is_administrator": "", "is_active": "on", "groups": [], "password": "",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertFalse(employee.is_superuser)

    def test_audit_log_clear_requires_permission_and_preserves_clear_event(self):
        """Nur explizit Berechtigte leeren Logs; der Vorgang bleibt nachvollziehbar."""
        viewer = get_user_model().objects.create_user(username="audit-clear-user")
        viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["can_view_audit_logs", "can_clear_audit_logs"],
        ))
        marker = AuditLog.objects.create(
            category=AuditLog.Category.STAFF, action="test.marker", description="Zu entfernender Marker",
        )
        self.client.force_login(viewer)
        response = self.client.get(reverse("audit_logs"))
        self.assertContains(response, "Protokoll leeren")
        response = self.client.post(reverse("clear_audit_logs"))
        self.assertRedirects(response, reverse("audit_logs"))
        self.assertFalse(AuditLog.objects.filter(pk=marker.pk).exists())
        clear_event = AuditLog.objects.get(action="audit_logs.cleared")
        self.assertGreaterEqual(clear_event.metadata["deleted_entries"], 1)

        read_only_user = get_user_model().objects.create_user(username="audit-read-only")
        read_only_user.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="can_view_audit_logs",
        ))
        self.client.force_login(read_only_user)
        self.assertNotContains(self.client.get(reverse("audit_logs")), "Protokoll leeren")
        retained_event = AuditLog.objects.create(
            category=AuditLog.Category.STAFF, action="test.retained", description="Bleibt bestehen",
        )
        self.client.force_login(read_only_user)
        self.assertEqual(self.client.post(reverse("clear_audit_logs")).status_code, 403)
        self.assertTrue(AuditLog.objects.filter(pk=retained_event.pk).exists())

    @override_settings(AUDIT_LOG_RETENTION_DAYS=30, AUDIT_LOG_MAX_ENTRIES=2)
    def test_audit_log_retention_keeps_recent_entries_under_limit(self):
        """Retention entfernt alte Einträge und begrenzt das Log auf die neuesten."""
        now = timezone.now()
        entries = [AuditLog.objects.create(
            category=AuditLog.Category.REQUEST, action=f"test.retention.{index}", description="Test",
        ) for index in range(4)]
        AuditLog.objects.filter(pk=entries[0].pk).update(created_at=now - timedelta(days=31))
        AuditLog.objects.filter(pk=entries[1].pk).update(created_at=now - timedelta(days=3))
        AuditLog.objects.filter(pk=entries[2].pk).update(created_at=now - timedelta(days=2))
        AuditLog.objects.filter(pk=entries[3].pk).update(created_at=now - timedelta(days=1))
        deleted = prune_audit_logs(now=now)
        self.assertEqual(deleted, 2)
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertFalse(AuditLog.objects.filter(pk=entries[0].pk).exists())

    def test_submission_summary_renders_for_authorized_user(self):
        """Zeigt Gesamtpunkte nur nach Prüfung der Auswertungsberechtigung."""
        user = get_user_model().objects.create_user(username="reviewer", password="test-pass-123")
        question_pool = QuestionPool.objects.create(name="Ergebnisprüfung")
        submissions_permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("submissions", question_pool),
        )
        user.user_permissions.add(submissions_permission)
        test = TestSession.objects.create(created_by=user, question_pool=question_pool, otp_hash=make_password("654321"), examinee_name="Cadet Morgan",
                                          status=TestSession.Status.COMPLETED, completed_at=timezone.now())
        question = TestQuestion.objects.create(test=test, position=1, text="Ergebnisfrage", question_type=Question.Type.SHORT,
                                               points=2, answer_key="ja")
        Submission.objects.create(test=test, test_question=question, answer={"value": "ja"}, score=2)
        self.client.force_login(user)
        response = self.client.get(reverse("submissions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadet Morgan")
        self.assertNotContains(response, "Ergebnisfrage")
        self.assertContains(response, "2 / 2")
        detail_url = reverse("submission_detail", args=[test.pk])
        response = self.client.get(detail_url)
        self.assertContains(response, "Ergebnisfrage")
        response = self.client.post(reverse("grade_submission", args=[test.submissions.get().pk]), {"score": "1.25"})
        self.assertRedirects(response, detail_url)
        test.submissions.get().refresh_from_db()
        self.assertEqual(test.submissions.get().score, 1.25)
        self.assertContains(self.client.get(detail_url), "1,25")
        self.assertContains(self.client.get(reverse("submissions")), "1,25 / 2")

    def test_choice_review_shows_options_selection_and_correctness(self):
        """Choice-Korrektur markiert gewählte, falsche und ausgelassene Antworten."""
        user = get_user_model().objects.create_user(username="choice-reviewer", password="test-pass-123")
        question_pool = QuestionPool.objects.create(name="Choice-Auswertung")
        permission = Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("submissions", question_pool),
        )
        user.user_permissions.add(permission)
        test = TestSession.objects.create(
            created_by=user, question_pool=question_pool, otp_hash=make_password("246810"),
            examinee_name="Cadet Choice", status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        question = TestQuestion.objects.create(
            test=test, position=1, text="Welche Funkcodes sind korrekt?",
            question_type=Question.Type.MULTIPLE,
            options=[
                {"text": "Code 1", "is_correct": True},
                {"text": "Code 2", "is_correct": True},
                {"text": "Code 3", "is_correct": False},
            ],
            points=2, answer_key="Interne Lösung",
        )
        Submission.objects.create(
            test=test, test_question=question, answer={"value": ["0", "2"]}, score=0,
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

    def test_question_form_accepts_rows_and_ignores_options_for_text_questions(self):
        """Auswahlantworten werden strukturiert gespeichert und Freitext bleibt optionsfrei."""
        manager = get_user_model().objects.create_superuser(username="question-admin", password="test-pass-123")
        self.client.force_login(manager)
        create_url = reverse("question_create")
        question_pool = QuestionPool.objects.create(name="Fragenformular-Test")
        form_page = self.client.get(create_url)
        self.assertContains(form_page, "Antwortmöglichkeiten")
        self.assertNotContains(form_page, "Antwortoptionen (JSON)")
        short_response = self.client.post(create_url, {
            "question_pool": str(question_pool.pk),
            "text": "Welcher Funkcode steht für verstanden?", "question_type": "short",
            "points": "2", "answer_key": "10-4", "is_pinned": "on", "option_count": "2",
            "option_text_0": "", "option_text_1": "", "answer_key": "10-4",
        })
        self.assertRedirects(short_response, f"{reverse('admin_dashboard')}?pool={question_pool.pk}")
        short_question = Question.objects.get(question_type=Question.Type.SHORT)
        self.assertEqual(short_question.options, [])
        multiple_response = self.client.post(create_url, {
            "question_pool": str(question_pool.pk),
            "text": "Welche Codes sind Notrufe?", "question_type": "multiple", "points": "3",
            "answer_key": "", "option_count": "3", "option_text_0": "Code 3", "option_correct_0": "on",
            "option_text_1": "Code 4", "option_correct_1": "", "option_text_2": "Code 10-13", "option_correct_2": "on",
        })
        self.assertRedirects(multiple_response, f"{reverse('admin_dashboard')}?pool={question_pool.pk}")
        multiple_question = Question.objects.get(question_type=Question.Type.MULTIPLE)
        self.assertEqual(multiple_question.options, [
            {"text": "Code 3", "is_correct": True},
            {"text": "Code 4", "is_correct": False},
            {"text": "Code 10-13", "is_correct": True},
        ])

    def test_test_generation_view_requires_pool_and_uses_only_selected_pool(self):
        """Die Testgenerierung verlangt einen Pool und übergibt ihn an den Dienst."""
        manager = get_user_model().objects.create_superuser(username="pool-test-admin", password="test-pass-123")
        self.client.force_login(manager)
        first_pool = QuestionPool.objects.create(name="Einstellungstest Web")
        second_pool = QuestionPool.objects.create(name="Sergeant-Test Web")
        Question.objects.create(question_pool=first_pool, text="Nur Einstellung", question_type=Question.Type.SHORT, answer_key="A")
        Question.objects.create(question_pool=second_pool, text="Nur Sergeant", question_type=Question.Type.SHORT, answer_key="B")
        response = self.client.get(reverse("generate_test"))
        self.assertContains(response, "Prüfungstyp / Fragenpool")
        self.assertContains(response, 'data-question-count="1"')
        self.assertContains(response, 'data-pinned-count="0"')
        response = self.client.post(reverse("generate_test"), {
            "question_pool": str(second_pool.pk), "question_count": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sergeant-Test Web: 1 Fragen · 0 davon verankert")
        test = TestSession.objects.get(question_pool=second_pool)
        self.assertEqual(list(test.items.values_list("text", flat=True)), ["Nur Sergeant"])
        self.assertContains(response, "SERGEANT-TEST WEB")

    def test_pool_management_creates_rename_and_protects_used_pool(self):
        """Pools können erstellt/umbenannt, mit Inhalt aber nicht gelöscht werden."""
        manager = get_user_model().objects.create_superuser(username="pool-manager", password="test-pass-123")
        self.client.force_login(manager)
        response = self.client.post(reverse("pools_dashboard"), {"name": "Sergeant-Auswahl", "description": "Aufstiegstest"})
        self.assertRedirects(response, reverse("pools_dashboard"))
        question_pool = QuestionPool.objects.get(name="Sergeant-Auswahl")
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.QUESTION,
            action="question_pool.created",
            object_id=str(question_pool.pk),
        ).exists())
        response = self.client.post(reverse("pool_edit", args=[question_pool.pk]), {"name": "Sergeant-Test", "description": "Aufstiegstest"})
        self.assertRedirects(response, reverse("pools_dashboard"))
        question_pool.refresh_from_db()
        self.assertEqual(question_pool.name, "Sergeant-Test")
        self.assertTrue(AuditLog.objects.filter(
            category=AuditLog.Category.QUESTION,
            action="question_pool.updated",
            object_id=str(question_pool.pk),
        ).exists())
        Question.objects.create(question_pool=question_pool, text="Sergeant only", question_type=Question.Type.SHORT, answer_key="10-4")
        response = self.client.post(reverse("pool_delete", args=[question_pool.pk]))
        self.assertRedirects(response, reverse("pools_dashboard"))
        self.assertTrue(QuestionPool.objects.filter(pk=question_pool.pk).exists())
        self.assertContains(self.client.get(reverse("pools_dashboard")), "Sergeant-Test")

    def test_staff_edit_saves_profile_and_roles(self):
        """Mitarbeiteränderungen speichern Profil, Gruppen und Aktivierungsstatus."""
        manager = get_user_model().objects.create_superuser(username="admin-editor", password="test-pass-123")
        staff = get_user_model().objects.create_user(username="academy-member", password="old-password")
        role = Group.objects.create(name="RBAC-Test-Fragenredaktion")
        direct_permission = Permission.objects.get(content_type__app_label="core", codename="change_question")
        staff.user_permissions.add(direct_permission)
        self.client.force_login(manager)
        response = self.client.post(reverse("user_edit", args=[staff.pk]), {
            "username": "academy-member", "first_name": "Riley", "last_name": "Officer",
            "is_active": "on", "groups": [str(role.pk)],
            "permission_" + str(direct_permission.pk): "on", "password": "",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        staff.refresh_from_db()
        self.assertEqual(staff.first_name, "Riley")
        self.assertEqual(list(staff.groups.values_list("name", flat=True)), ["RBAC-Test-Fragenredaktion"])
        self.assertTrue(staff.is_active)
        self.assertTrue(staff.user_permissions.filter(pk=direct_permission.pk).exists())

    def test_staff_create_saves_new_user_and_roles(self):
        """Neue Benutzer werden gespeichert, bevor ihre M2M-Rechte gelesen werden."""
        manager = get_user_model().objects.create_superuser(username="admin-create", password="test-pass-123")
        role = Group.objects.create(name="RBAC-Test-Prüfungsleitung")
        self.client.force_login(manager)
        response = self.client.post(reverse("user_create"), {
            "username": "new-cadet-staff", "first_name": "Taylor", "last_name": "Cadet",
            "is_active": "on", "groups": [str(role.pk)],
            "user_permissions": [], "password": "valid-test-password-123",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        created = get_user_model().objects.get(username="new-cadet-staff")
        self.assertTrue(created.check_password("valid-test-password-123"))
        self.assertEqual(list(created.groups.values_list("name", flat=True)), ["RBAC-Test-Prüfungsleitung"])
        creation_event = AuditLog.objects.get(category=AuditLog.Category.STAFF, action="staff.created", object_id=str(created.pk))
        self.assertEqual(creation_event.metadata["groups"], ["RBAC-Test-Prüfungsleitung"])
        self.assertNotIn("valid-test-password-123", str(creation_event.metadata))
        for description, metadata in AuditLog.objects.values_list("description", "metadata"):
            self.assertNotIn("valid-test-password-123", description)
            self.assertNotIn("valid-test-password-123", str(metadata))

    def test_user_list_includes_and_allows_editing_current_administrator(self):
        """Die Mitarbeiterliste zeigt den eigenen Superuser und seine Bearbeitung."""
        manager = get_user_model().objects.create_superuser(username="admin-list", password="test-pass-123")
        self.client.force_login(manager)
        response = self.client.get(reverse("users_dashboard"))
        self.assertContains(response, "admin-list")
        self.assertContains(response, "Administrator · Alle Rechte")
        self.assertEqual(response.content.decode().count("Administrator · Alle Rechte"), 1)
        self.assertContains(response, reverse("user_edit", args=[manager.pk]))
        self.assertEqual(self.client.get(reverse("user_edit", args=[manager.pk])).status_code, 200)
        response = self.client.post(reverse("user_edit", args=[manager.pk]), {
            "username": "admin-list", "is_active": "on", "groups": [], "user_permissions": [], "password": "",
        })
        self.assertEqual(response.status_code, 200)
        manager.refresh_from_db()
        self.assertTrue(manager.is_superuser)

    def test_staff_admin_switch_grants_all_application_permissions(self):
        """Der Administrator-Schalter aktiviert Superuser mit allen Fachrechten."""
        manager = get_user_model().objects.create_superuser(username="admin-role-manager", password="test-pass-123")
        self.client.force_login(manager)
        response = self.client.post(reverse("user_create"), {
            "username": "academy-admin", "first_name": "Academy", "last_name": "Admin",
            "is_administrator": "on", "is_active": "on", "groups": [],
            "user_permissions": [], "password": "strong-enough-password-123",
        })
        self.assertRedirects(response, reverse("users_dashboard"))
        created = get_user_model().objects.get(username="academy-admin")
        self.assertTrue(created.is_superuser)
        self.assertTrue(created.is_staff)
        self.assertTrue(created.has_perm("core.can_manage_users"))
        self.assertTrue(created.has_perm("core.can_delete_tests"))
        self.assertTrue(created.has_perm("core.can_view_audit_logs"))
        self.assertNotContains(self.client.get(reverse("user_edit", args=[created.pk])), "E-Mail-Adresse")

    def test_audit_log_permission_is_separate_and_http_access_is_recorded(self):
        """Nur die eigene Logberechtigung öffnet Systemlogs; Zugriffe werden erfasst."""
        user = get_user_model().objects.create_user(username="log-reader", password="test-pass-123")
        self.client.force_login(user)
        log_url = reverse("audit_logs")
        self.assertEqual(self.client.get(log_url).status_code, 403)
        permission = Permission.objects.get(content_type__app_label="core", codename="can_view_audit_logs")
        user.user_permissions.add(permission)
        response = self.client.get(log_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Systemprotokoll")
        self.assertTrue(AuditLog.objects.filter(category=AuditLog.Category.REQUEST, object_id="audit_logs").exists())

    def test_test_deletion_requires_permission_and_keeps_security_audit(self):
        """Testlöschung ist berechtigt, kaskadiert Antworten und hinterlässt Log."""
        creator = get_user_model().objects.create_user(username="test-owner", password="test-pass-123")
        test = TestSession.objects.create(
            created_by=creator, question_pool=QuestionPool.objects.create(name="Löschprüfung"),
            otp_hash=make_password("555111"), examinee_name="Cadet Delete",
            status=TestSession.Status.COMPLETED, completed_at=timezone.now(),
        )
        TestQuestion.objects.create(test=test, position=1, text="Delete test question", question_type=Question.Type.SHORT, points=1)
        Submission.objects.create(test=test, test_question=test.items.get(), answer={"value": "x"}, score=0)
        delete_url = reverse("delete_test", args=[test.pk])
        viewer = get_user_model().objects.create_user(username="viewer-only", password="test-pass-123")
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename=pool_permission_codename("submissions", test.question_pool),
        ))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        self.assertTrue(TestSession.objects.filter(pk=test.pk).exists())
        admin = get_user_model().objects.create_superuser(username="delete-admin", password="test-pass-123")
        self.client.force_login(admin)
        response = self.client.post(delete_url)
        self.assertRedirects(response, reverse("submissions"))
        self.assertFalse(TestSession.objects.filter(pk=test.pk).exists())
        self.assertFalse(Submission.objects.filter(test_id=test.pk).exists())
        event = AuditLog.objects.get(category=AuditLog.Category.SECURITY, action="test.deleted", object_id=str(test.pk))
        self.assertEqual(event.actor, admin)
