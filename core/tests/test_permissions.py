"""Tests zu Rechten und Rechteverwaltung."""

import csv
import io
from importlib import import_module
from datetime import timedelta
from types import SimpleNamespace
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase, override_settings
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
from ..permissions import (
    ADMINISTRATOR_GROUP,
    has_access,
    has_pool_access,
    pool_permission_codename,
)
from ..audit import prune_audit_logs


class PermissionTests(TestCase):
    """Prüft serverseitige Rechte unabhängig von ausgeblendeten UI-Aktionen."""

    def test_user_deletion_requires_its_permission_and_preserves_created_tests(self):
        manager = get_user_model().objects.create_user(username="staff-delete-manager")
        manager.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=("can_view_users", "can_delete_users"),
            )
        )
        employee = get_user_model().objects.create_user(username="employee-to-delete")
        question_pool = QuestionPool.objects.create(name="Mitarbeiter-Löschtest")
        test = TestSession.objects.create(
            created_by=employee,
            question_pool=question_pool,
            otp_hash=make_password("123456"),
        )
        self.client.force_login(manager)
        dashboard = self.client.get(reverse("users_dashboard"))
        self.assertContains(dashboard, reverse("user_delete", args=[employee.pk]))
        self.assertEqual(
            self.client.get(reverse("user_delete", args=[employee.pk])).status_code,
            405,
        )
        response = self.client.post(reverse("user_delete", args=[employee.pk]))
        self.assertRedirects(response, reverse("users_dashboard"))
        self.assertFalse(get_user_model().objects.filter(pk=employee.pk).exists())
        test.refresh_from_db()
        self.assertIsNone(test.created_by)
        deletion_log = AuditLog.objects.get(
            action="staff.deleted", object_id=str(employee.pk)
        )
        self.assertEqual(deletion_log.actor, manager)
        self.assertEqual(deletion_log.metadata["username"], employee.username)

    def test_user_deletion_is_denied_without_permission_and_protects_self_and_admins(
        self,
    ):
        manager = get_user_model().objects.create_user(username="staff-manager")
        employee = get_user_model().objects.create_user(username="protected-employee")
        self.client.force_login(manager)
        self.assertEqual(
            self.client.post(reverse("user_delete", args=[employee.pk])).status_code,
            403,
        )

        manager.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_delete_users",
            ),
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_view_users",
            ),
        )
        self.assertRedirects(
            self.client.post(reverse("user_delete", args=[manager.pk])),
            reverse("users_dashboard"),
        )
        self.assertTrue(get_user_model().objects.filter(pk=manager.pk).exists())

        administrator = get_user_model().objects.create_superuser(
            username="protected-admin"
        )
        self.assertEqual(
            self.client.post(
                reverse("user_delete", args=[administrator.pk])
            ).status_code,
            403,
        )
        self.assertTrue(get_user_model().objects.filter(pk=administrator.pk).exists())

    def test_question_pool_requires_custom_permission(self):
        """Fragenübersicht wird erst durch das konkrete Pool-View-Recht geöffnet."""
        user = get_user_model().objects.create_user(
            username="editor", password="test-pass-123"
        )
        question_pool = QuestionPool.objects.create(name="RBAC-Fragenpool")
        url = reverse("admin_dashboard")
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 403)
        permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("view", question_pool),
        )
        user.user_permissions.add(permission)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("question_create"))
        edit_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("create", question_pool),
        )
        user.user_permissions.add(edit_permission)
        self.assertContains(self.client.get(url), reverse("question_create"))

    def test_pool_question_and_test_views_are_isolated_by_dynamic_permissions(self):
        """Fragenbank, Generierung und Abgaben zeigen nur explizit erlaubte Pools."""
        user = get_user_model().objects.create_user(
            username="pool-scoped", password="test-pass-123"
        )
        view_pool = QuestionPool.objects.create(name="Sichtbarer Pool")
        generate_pool = QuestionPool.objects.create(name="Generierbarer Pool")
        hidden_pool = QuestionPool.objects.create(name="Privater Pool")
        Question.objects.create(
            question_pool=view_pool,
            text="Sichtbare Frage",
            question_type=Question.Type.SHORT,
            answer_key="X",
        )
        Question.objects.create(
            question_pool=hidden_pool,
            text="Versteckte Frage",
            question_type=Question.Type.SHORT,
            answer_key="Y",
        )
        visible_test = TestSession.objects.create(
            created_by=user,
            question_pool=view_pool,
            otp_hash=make_password("111222"),
            examinee_name="Visible Cadet",
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        hidden_test = TestSession.objects.create(
            created_by=user,
            question_pool=hidden_pool,
            otp_hash=make_password("333444"),
            examinee_name="Hidden Cadet",
            status=TestSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        user.user_permissions.add(
            *[
                Permission.objects.get(
                    content_type__app_label="core",
                    codename=pool_permission_codename(action, pool),
                )
                for action, pool in [
                    ("view", view_pool),
                    ("view_submissions", view_pool),
                    ("generate", generate_pool),
                ]
            ]
        )
        self.client.force_login(user)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "Sichtbarer Pool")
        self.assertNotContains(response, "Privater Pool")
        self.assertNotContains(response, "Versteckte Frage")
        self.assertNotContains(response, reverse("question_create"))
        self.assertEqual(
            self.client.get(
                f"{reverse('admin_dashboard')}?pool={hidden_pool.pk}"
            ).status_code,
            403,
        )
        generation = self.client.get(reverse("generate_test"))
        self.assertContains(generation, "Generierbarer Pool")
        self.assertNotContains(generation, "Privater Pool")
        self.assertEqual(
            self.client.post(
                reverse("generate_test"),
                {
                    "question_pool": str(hidden_pool.pk),
                    "question_count": "1",
                },
            ).status_code,
            403,
        )
        response = self.client.get(reverse("submissions"))
        self.assertContains(response, "Visible Cadet")
        self.assertNotContains(response, "Hidden Cadet")
        self.assertEqual(
            self.client.get(f"{reverse('submissions')}?pool={view_pool.pk}").context[
                "summaries"
            ][0]["test"],
            visible_test,
        )
        self.assertEqual(
            self.client.get(
                f"{reverse('submissions')}?pool={hidden_pool.pk}"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("submission_detail", args=[hidden_test.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("submission_detail", args=[visible_test.pk])
            ).status_code,
            200,
        )

    def test_question_bank_filters_question_text_type_and_pinned_state(self):
        """Such- und Selectfilter grenzen die Fragenliste des gewählten Pools ein."""
        administrator = get_user_model().objects.create_superuser(
            username="question-filter-admin",
            email="question-filter@example.com",
            password="strong-password",
        )
        question_pool = QuestionPool.objects.create(name="Filter-Fragen")
        Question.objects.create(
            question_pool=question_pool,
            text="Kontrollierter Funkruf",
            question_type=Question.Type.SHORT,
            is_pinned=True,
        )
        Question.objects.create(
            question_pool=question_pool,
            text="Andere Auswahl",
            question_type=Question.Type.SINGLE,
            options=[
                {"text": "Ja", "is_correct": True},
                {"text": "Nein", "is_correct": False},
            ],
        )
        self.client.force_login(administrator)
        response = self.client.get(
            reverse("admin_dashboard"),
            {
                "pool": question_pool.pk,
                "q": "Funk",
                "type": Question.Type.SHORT,
                "pinned": "yes",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kontrollierter Funkruf")
        self.assertNotContains(response, "Andere Auswahl")
        self.assertNotContains(response, 'href="/privacy/#datenschutz"')
        self.assertContains(response, "Impressum / DSGVO")
        self.assertEqual(len(response.context["questions"]), 1)

    def test_submission_filters_and_next_test_preserve_pending_workflow(self):
        """Auswertungsfilter zeigen offene Abgaben und übergeben Kriterien zur Detailnavigation."""
        user = get_user_model().objects.create_user(username="filter-reviewer")
        question_pool = QuestionPool.objects.create(name="Filter-Ergebnisse")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename=pool_permission_codename("view_submissions", question_pool),
            )
        )
        tests = []
        for index, name in enumerate(("Cadet Alpha", "Cadet Beta"), start=1):
            test = TestSession.objects.create(
                created_by=user,
                question_pool=question_pool,
                otp_hash=make_password(f"11111{index}"),
                examinee_name=name,
                status=TestSession.Status.COMPLETED,
                completed_at=timezone.now() - timedelta(minutes=index),
            )
            question = TestQuestion.objects.create(
                test=test,
                position=1,
                text=f"Freitext {index}",
                question_type=Question.Type.LONG,
                points=3,
            )
            Submission.objects.create(
                test=test,
                test_question=question,
                answer={"value": "Antwort"},
                needs_manual_grading=True,
            )
            tests.append(test)
        self.client.force_login(user)
        response = self.client.get(
            reverse("submissions"),
            {
                "pool": question_pool.pk,
                "q": "Cadet",
                "pending": "1",
            },
        )
        self.assertContains(response, "Cadet Alpha")
        self.assertContains(response, "Cadet Beta")
        self.assertEqual(response.context["summaries"][0]["test"], tests[0])
        detail = self.client.get(
            reverse("submission_detail", args=[tests[0].pk]),
            {"q": "Cadet", "pending": "1"},
        )
        self.assertNotContains(detail, "Nächster")

    def test_audit_log_filters_and_csv_export_are_permission_protected(self):
        """Audit-Filter werden in den Export übernommen und nur berechtigte Nutzer dürfen exportieren."""
        reader = get_user_model().objects.create_user(username="audit-export-reader")
        reader.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=("can_view_audit_logs", "can_export_audit_logs"),
            )
        )
        matching = AuditLog.objects.create(
            actor=reader,
            category=AuditLog.Category.STAFF,
            action="staff.profile.updated",
            description="Änderung am Profil",
        )
        AuditLog.objects.create(
            actor=reader,
            category=AuditLog.Category.STAFF,
            action="staff.profile.updated",
            description='  =HYPERLINK("https://example.com")',
        )
        AuditLog.objects.create(
            category=AuditLog.Category.TEST,
            action="test.generated",
            description="Test erstellt",
        )
        self.client.force_login(reader)
        response = self.client.get(
            reverse("audit_logs"),
            {
                "actor": reader.username,
                "action": "profil",
                "category": AuditLog.Category.STAFF,
            },
        )
        self.assertEqual(len(response.context["page"].object_list), 2)
        self.assertIn(matching, response.context["page"].object_list)
        export = self.client.get(
            reverse("audit_logs_export"),
            {
                "actor": reader.username,
                "action": "profil",
                "category": AuditLog.Category.STAFF,
            },
        )
        self.assertEqual(export.status_code, 200)
        export_content = export.content.decode("utf-8-sig")
        exported_rows = list(
            csv.reader(io.StringIO(export_content, newline=""), delimiter=";")
        )
        self.assertEqual(len(exported_rows[0]), 9)
        self.assertEqual(len(exported_rows[1]), 9)
        self.assertIn("Änderung am Profil", export_content)
        self.assertIn('\t  =HYPERLINK(""https://example.com"")', export_content)
        self.assertNotIn("Test erstellt", export_content)
        unauthorized = get_user_model().objects.create_user(
            username="audit-export-denied"
        )
        self.client.force_login(unauthorized)
        self.assertEqual(self.client.get(reverse("audit_logs_export")).status_code, 403)

    def test_custom_group_can_grant_a_dynamic_pool_permission(self):
        """Freie Gruppen verwalten Rechte und deren Mitglieder erhalten exakt diese Poolfreigabe."""
        administrator = get_user_model().objects.create_superuser(
            username="rights-admin", password="test-pass-123"
        )
        question_pool = QuestionPool.objects.create(name="Patrol Sergeant")
        permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("generate", question_pool),
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
        self.assertContains(group_form, "Sortierzahl")
        self.assertContains(group_form, f"Pool · {question_pool.name}")
        self.assertContains(group_form, "Seitentitel ändern")
        self.assertContains(
            group_form,
            f"Fragen in diesem Pool importieren: {question_pool.name}",
        )
        self.assertContains(
            group_form,
            f"Fragen aus diesem Pool exportieren: {question_pool.name}",
        )
        self.assertContains(
            group_form,
            f"Prüflingsnamen in diesem Pool ändern: {question_pool.name}",
        )
        self.assertContains(group_form, "Tests aus diesem Pool generieren")
        self.assertContains(
            group_form,
            "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.",
        )
        self.assertContains(
            group_form, "Erfordert Mitarbeiterverwaltung und erlaubt kein Vergeben."
        )
        self.assertNotContains(group_form, "Django-Admin")
        self.assertNotContains(group_form, "django.contrib.sessions")
        section_titles = list(group_form.context["permission_sections"])
        self.assertEqual(section_titles[0]["title"], "Mitarbeiter")
        pool_titles = [
            section["title"]
            for section in section_titles
            if section["title"].startswith("Pool · ")
        ]
        self.assertEqual(pool_titles, sorted(pool_titles, key=str.casefold))
        self.assertIn(f"Pool · {question_pool.name}", pool_titles)
        shown_permission_ids = [
            item["permission"].pk
            for section in section_titles
            for item in section["fields"]
        ]
        self.assertEqual(len(shown_permission_ids), len(set(shown_permission_ids)))
        self.assertEqual(
            set(shown_permission_ids),
            set(
                Permission.objects.filter(
                    content_type__app_label="core",
                    content_type__model="questionpool",
                )
                .exclude(
                    codename__in=[
                        "add_questionpool",
                        "change_questionpool",
                        "delete_questionpool",
                        "view_questionpool",
                    ]
                )
                .values_list("pk", flat=True)
            ),
        )
        self.assertNotContains(group_form, "can_view_pool_")
        csv_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("import", question_pool),
        )
        response = self.client.post(
            reverse("permission_group_create"),
            {
                "name": "Sergeant Prüfer",
                "sort_order": "3",
                f"permission_{permission.pk}": "on",
                f"permission_{csv_permission.pk}": "on",
            },
        )
        self.assertRedirects(response, reverse("permissions_dashboard"))
        role = Group.objects.get(name="Sergeant Prüfer")
        self.assertEqual(role.sort_config.sort_order, 3)
        self.assertTrue(role.permissions.filter(pk=permission.pk).exists())
        self.assertTrue(role.permissions.filter(pk=csv_permission.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.STAFF,
                action="permission_group.created",
                object_id=str(role.pk),
            ).exists()
        )
        response = self.client.post(
            reverse("permission_group_edit", args=[role.pk]),
            {
                "name": role.name,
                "sort_order": "2",
                f"permission_{permission.pk}": "on",
            },
        )
        self.assertRedirects(response, reverse("permissions_dashboard"))
        role.sort_config.refresh_from_db()
        self.assertEqual(role.sort_config.sort_order, 2)
        response = self.client.post(
            reverse("permission_group_create"),
            {
                "name": "Moderator",
                "sort_order": "1",
            },
        )
        self.assertRedirects(response, reverse("permissions_dashboard"))
        groups = self.client.get(reverse("permissions_dashboard")).context["groups"]
        self.assertEqual(
            [group.name for group in groups], ["Moderator", "Sergeant Prüfer"]
        )
        self.assertEqual(self.client.get("/django-admin/").status_code, 404)
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.STAFF,
                action="permission_group.updated",
                object_id=str(role.pk),
            ).exists()
        )
        employee = get_user_model().objects.create_user(
            username="sergeant-staff", password="test-pass-123"
        )
        employee.groups.add(role)
        self.assertTrue(has_pool_access(employee, question_pool, "generate"))
        self.assertFalse(has_pool_access(employee, question_pool, "view"))
        view_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("view", question_pool),
        )
        user_rights_form = self.client.get(
            reverse("permission_user_edit", args=[employee.pk])
        )
        self.assertContains(user_rights_form, f"Pool · {question_pool.name}")
        self.assertNotContains(user_rights_form, "Django-Admin")
        self.assertContains(
            user_rights_form,
            "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.",
        )
        response = self.client.post(
            reverse("permission_user_edit", args=[employee.pk]),
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_active": "on",
                "is_administrator": "",
                "groups": [str(role.pk)],
                "password": "",
                f"permission_{view_permission.pk}": "on",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee = get_user_model().objects.get(pk=employee.pk)
        self.assertTrue(has_pool_access(employee, question_pool, "view"))
        self.assertTrue(
            AuditLog.objects.filter(
                category=AuditLog.Category.STAFF,
                action="staff.permissions.updated",
                object_id=str(employee.pk),
            ).exists()
        )


class RightsAndAuditTests(TestCase):
    """Prüft Rechteverwaltung, Rechtegruppen und Systemlog-Rechte."""

    def test_standard_legacy_groups_are_not_recreated(self):
        """Es existiert keine fest verdrahtete Rolle außer Administrator."""
        self.assertFalse(Group.objects.filter(name=ADMINISTRATOR_GROUP).exists())
        self.assertFalse(
            Group.objects.filter(
                name__in=["Fragen-Editor", "Test-Manager", "Korrektor"]
            ).exists()
        )
        self.assertFalse(
            Permission.objects.filter(
                content_type__app_label="core",
                content_type__model="question",
                codename__in=[
                    "can_manage_questions",
                    "can_generate_tests",
                    "can_view_submissions",
                    "can_grade_submissions",
                    "can_manage_users",
                    "can_delete_tests",
                    "can_view_audit_logs",
                ],
            ).exists()
        )

    def test_legacy_aggregate_permission_does_not_grant_atomic_capabilities(self):
        """Ein altes Sammelrecht darf keine Einzelaktion mehr freischalten."""
        manager = get_user_model().objects.create_user(
            username="non-admin-manager", password="test-pass-123"
        )
        legacy_permission = Permission.objects.create(
            content_type=ContentType.objects.get(
                app_label="core", model="questionpool"
            ),
            codename="can_manage_users",
            name="Legacy-Sammelrecht",
        )
        manager.user_permissions.add(legacy_permission)
        self.assertFalse(has_access(manager, "view_users"))
        self.assertFalse(has_access(manager, "create_users"))
        self.client.force_login(manager)
        self.assertEqual(
            self.client.get(reverse("permissions_dashboard")).status_code, 403
        )

    def test_permission_migration_splits_existing_user_and_group_assignments(self):
        """Die Rechte-Migration überträgt vorhandene Zuweisungen auf Einzelrechte."""
        legacy_module = import_module(
            "core.migrations.0023_alter_questionpool_options"
        )
        content_type = ContentType.objects.get_for_model(QuestionPool)
        user = get_user_model().objects.create_user(username="legacy-rights-user")
        group = Group.objects.create(name="Legacy-Rechte")
        legacy_manage = Permission.objects.create(
            content_type=content_type,
            codename="can_manage_users",
            name="Mitarbeiter verwalten",
        )
        legacy_grant = Permission.objects.get(
            content_type=content_type,
            codename="can_grant_user_permissions",
        )
        legacy_revoke = Permission.objects.get(
            content_type=content_type,
            codename="can_revoke_user_permissions",
        )
        user.user_permissions.add(legacy_manage, legacy_grant, legacy_revoke)
        group.permissions.add(legacy_manage, legacy_grant, legacy_revoke)

        question_pool = QuestionPool.objects.create(name="Legacy-Poolrechte")
        legacy_delete = Permission.objects.create(
            content_type=content_type,
            codename=f"can_delete_questions_pool_{question_pool.pk}",
            name="Fragen löschen",
        )
        user.user_permissions.add(legacy_delete)
        group.permissions.add(legacy_delete)

        legacy_module.split_legacy_permissions(
            apps, SimpleNamespace(connection=connection)
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=content_type, codename="can_manage_users"
            ).exists()
        )
        for codename in (
            "can_view_users",
            "can_create_users",
            "can_update_users",
            "can_view_user_permissions",
            "can_assign_user_groups",
            "can_unassign_user_groups",
        ):
            migrated = Permission.objects.get(
                content_type=content_type, codename=codename
            )
            self.assertTrue(user.user_permissions.filter(pk=migrated.pk).exists())
            self.assertTrue(group.permissions.filter(pk=migrated.pk).exists())
        self.assertTrue(user.user_permissions.filter(pk=legacy_grant.pk).exists())
        self.assertTrue(user.user_permissions.filter(pk=legacy_revoke.pk).exists())
        for action in ("delete_single", "delete_bulk"):
            migrated = Permission.objects.get(
                content_type=content_type,
                codename=pool_permission_codename(action, question_pool),
            )
            self.assertTrue(user.user_permissions.filter(pk=migrated.pk).exists())
            self.assertTrue(group.permissions.filter(pk=migrated.pk).exists())

    def test_user_permission_grant_and_revoke_are_separately_authorized(self):
        """Nutzerrechte und Gruppen lassen sich nur mit Grant-/Revoke-Recht ändern."""
        manager = get_user_model().objects.create_user(
            username="delegated-rights-manager"
        )
        manager.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=[
                    "can_view_user_permissions",
                    "can_view_users",
                    "can_grant_user_permissions",
                    "can_assign_user_groups",
                ],
            )
        )
        employee = get_user_model().objects.create_user(
            username="delegated-rights-target"
        )
        role = Group.objects.create(name="Delegierte Prüfer")
        protected_role = Group.objects.create(name="Geschützte Audit-Verwalter")
        protected_role.permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_clear_audit_logs",
            )
        )
        employee.groups.add(protected_role)
        question_pool = QuestionPool.objects.create(name="RBAC-Test-Berechtigungspool")
        direct_permission = Permission.objects.get(
            content_type__app_label="core",
            codename=pool_permission_codename("view", question_pool),
        )
        protected_permission = Permission.objects.get(
            content_type__app_label="core",
            codename="can_grant_administrator",
        )
        forbidden_permission = Permission.objects.get(
            content_type__app_label="core",
            codename="can_revoke_administrator",
        )
        employee.user_permissions.add(protected_permission)
        self.client.force_login(manager)
        edit_url = reverse("permission_user_edit", args=[employee.pk])
        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_active": "on",
                "is_administrator": "",
                "groups": [str(role.pk)],
                "password": "",
                f"permission_{direct_permission.pk}": "on",
                f"permission_{forbidden_permission.pk}": "on",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(
            employee.user_permissions.filter(pk=direct_permission.pk).exists()
        )
        self.assertTrue(employee.groups.filter(pk=role.pk).exists())
        self.assertTrue(
            employee.user_permissions.filter(pk=protected_permission.pk).exists()
        )
        self.assertFalse(
            employee.user_permissions.filter(pk=forbidden_permission.pk).exists()
        )
        self.assertTrue(employee.groups.filter(pk=protected_role.pk).exists())

        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_active": "on",
                "is_administrator": "",
                "groups": [],
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(
            employee.user_permissions.filter(pk=direct_permission.pk).exists()
        )
        self.assertTrue(employee.groups.filter(pk=role.pk).exists())

        manager.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_grant_user_permissions",
            )
        )
        manager.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_revoke_user_permissions",
            ),
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_unassign_user_groups",
            ),
        )
        manager.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_assign_user_groups",
            )
        )
        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_active": "on",
                "is_administrator": "",
                "groups": [],
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertFalse(
            employee.user_permissions.filter(pk=direct_permission.pk).exists()
        )
        self.assertFalse(employee.groups.filter(pk=role.pk).exists())
        self.assertTrue(
            employee.user_permissions.filter(pk=protected_permission.pk).exists()
        )
        self.assertTrue(employee.groups.filter(pk=protected_role.pk).exists())

    def test_administrator_grant_and_revoke_are_separately_authorized(self):
        """Administratorstatus kann getrennt vergeben und wieder entzogen werden."""
        manager = get_user_model().objects.create_user(
            username="admin-delegation-manager"
        )
        manager.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=[
                    "can_view_users",
                    "can_update_user_first_name",
                    "can_grant_administrator",
                ],
            )
        )
        employee = get_user_model().objects.create_user(
            username="admin-delegation-target"
        )
        self.client.force_login(manager)
        edit_url = reverse("user_edit", args=[employee.pk])
        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_administrator": "on",
                "is_active": "on",
                "groups": [],
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertTrue(employee.is_superuser)

        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_administrator": "",
                "is_active": "on",
                "groups": [],
                "password": "",
            },
        )
        self.assertEqual(response.status_code, 403)
        employee.refresh_from_db()
        self.assertTrue(employee.is_superuser)

        manager.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_grant_administrator",
            )
        )
        manager.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_revoke_administrator",
            )
        )
        response = self.client.post(
            edit_url,
            {
                "username": employee.username,
                "first_name": "",
                "last_name": "",
                "is_administrator": "",
                "is_active": "on",
                "groups": [],
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        employee.refresh_from_db()
        self.assertFalse(employee.is_superuser)

    def test_audit_log_clear_requires_permission_and_preserves_clear_event(self):
        """Nur explizit Berechtigte leeren Logs; der Vorgang bleibt nachvollziehbar."""
        viewer = get_user_model().objects.create_user(username="audit-clear-user")
        viewer.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=["can_view_audit_logs", "can_clear_audit_logs"],
            )
        )
        marker = AuditLog.objects.create(
            category=AuditLog.Category.STAFF,
            action="test.marker",
            description="Zu entfernender Marker",
        )
        self.client.force_login(viewer)
        response = self.client.get(reverse("audit_logs"))
        self.assertContains(response, "Protokoll leeren")
        response = self.client.post(reverse("clear_audit_logs"))
        self.assertRedirects(response, reverse("audit_logs"))
        self.assertFalse(AuditLog.objects.filter(pk=marker.pk).exists())
        clear_event = AuditLog.objects.get(action="audit_logs.cleared")
        self.assertGreaterEqual(clear_event.metadata["deleted_entries"], 1)

        read_only_user = get_user_model().objects.create_user(
            username="audit-read-only"
        )
        read_only_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core",
                codename="can_view_audit_logs",
            )
        )
        self.client.force_login(read_only_user)
        self.assertNotContains(
            self.client.get(reverse("audit_logs")), "Protokoll leeren"
        )
        retained_event = AuditLog.objects.create(
            category=AuditLog.Category.STAFF,
            action="test.retained",
            description="Bleibt bestehen",
        )
        self.client.force_login(read_only_user)
        self.assertEqual(self.client.post(reverse("clear_audit_logs")).status_code, 403)
        self.assertTrue(AuditLog.objects.filter(pk=retained_event.pk).exists())

    @override_settings(AUDIT_LOG_RETENTION_DAYS=30, AUDIT_LOG_MAX_ENTRIES=2)
    def test_audit_log_retention_keeps_recent_entries_under_limit(self):
        """Retention entfernt alte Einträge und begrenzt das Log auf die neuesten."""
        now = timezone.now()
        entries = [
            AuditLog.objects.create(
                category=AuditLog.Category.REQUEST,
                action=f"test.retention.{index}",
                description="Test",
            )
            for index in range(4)
        ]
        AuditLog.objects.filter(pk=entries[0].pk).update(
            created_at=now - timedelta(days=31)
        )
        AuditLog.objects.filter(pk=entries[1].pk).update(
            created_at=now - timedelta(days=3)
        )
        AuditLog.objects.filter(pk=entries[2].pk).update(
            created_at=now - timedelta(days=2)
        )
        AuditLog.objects.filter(pk=entries[3].pk).update(
            created_at=now - timedelta(days=1)
        )
        deleted = prune_audit_logs(now=now)
        self.assertEqual(deleted, 2)
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertFalse(AuditLog.objects.filter(pk=entries[0].pk).exists())


class FieldLevelPermissionTests(TestCase):
    """Prüft, dass Konto-, Gruppen-, Pool- und Fragenfelder einzeln freigegeben werden."""

    def _grant(self, user, *codenames):
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core", codename__in=codenames
            )
        )

    def test_user_fields_are_updated_only_with_their_own_permission(self):
        manager = get_user_model().objects.create_user(username="field-manager")
        self._grant(manager, "can_view_users", "can_update_user_first_name")
        target = get_user_model().objects.create_user(
            username="field-target", first_name="Alt", last_name="Name"
        )
        self.client.force_login(manager)
        response = self.client.post(
            reverse("user_edit", args=[target.pk]),
            {
                "username": "hijacked",
                "first_name": "Neu",
                "last_name": "Geändert",
                "is_active": "",
                "password": "neues-passwort-123",
            },
        )
        self.assertRedirects(response, reverse("users_dashboard"))
        target.refresh_from_db()
        self.assertEqual(target.first_name, "Neu")
        self.assertEqual(target.username, "field-target")
        self.assertEqual(target.last_name, "Name")
        self.assertTrue(target.is_active)
        self.assertFalse(target.check_password("neues-passwort-123"))

    def test_user_edit_is_forbidden_without_any_update_permission(self):
        manager = get_user_model().objects.create_user(username="no-update-manager")
        self._grant(manager, "can_view_users")
        target = get_user_model().objects.create_user(username="no-update-target")
        self.client.force_login(manager)
        self.assertEqual(
            self.client.get(reverse("user_edit", args=[target.pk])).status_code, 403
        )

    def test_deactivation_needs_its_own_permission(self):
        manager = get_user_model().objects.create_user(username="deactivator")
        self._grant(manager, "can_view_users", "can_deactivate_users")
        target = get_user_model().objects.create_user(username="deactivate-target")
        self.client.force_login(manager)
        self.client.post(
            reverse("user_edit", args=[target.pk]),
            {"username": "deactivate-target", "is_active": ""},
        )
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_group_name_and_priority_are_separate_permissions(self):
        manager = get_user_model().objects.create_user(username="group-manager")
        self._grant(
            manager, "can_view_permission_groups", "can_update_permission_group_priority"
        )
        group = Group.objects.create(name="Alte Gruppe")
        self.client.force_login(manager)
        response = self.client.post(
            reverse("permission_group_edit", args=[group.pk]),
            {"name": "Neuer Name", "sort_order": 7},
        )
        self.assertRedirects(response, reverse("permissions_dashboard"))
        group.refresh_from_db()
        self.assertEqual(group.name, "Alte Gruppe")
        self.assertEqual(group.sort_config.sort_order, 7)

    def test_pool_fields_are_updated_only_with_their_own_permission(self):
        manager = get_user_model().objects.create_user(username="pool-manager")
        self._grant(manager, "can_view_question_pools", "can_update_pool_name")
        pool = QuestionPool.objects.create(name="Alt", pass_percentage=50)
        self.client.force_login(manager)
        response = self.client.post(
            reverse("pool_edit", args=[pool.pk]),
            {
                "name": "Neu",
                "description": "x",
                "test_question_count": pool.test_question_count,
                "pass_percentage": 99,
                "minimum_time_limit_minutes": pool.minimum_time_limit_minutes,
                "maximum_time_limit_minutes": pool.maximum_time_limit_minutes,
                "start_info_text": pool.start_info_text,
                "start_confirmations": pool.start_confirmations,
            },
        )
        self.assertRedirects(response, reverse("pools_dashboard"))
        pool.refresh_from_db()
        self.assertEqual(pool.name, "Neu")
        self.assertEqual(pool.pass_percentage, 50)

    def test_pool_actions_do_not_require_view_permission(self):
        employee = get_user_model().objects.create_user(username="export-only")
        pool = QuestionPool.objects.create(name="Export ohne Ansicht")
        employee.user_permissions.add(
            Permission.objects.get(
                codename=pool_permission_codename("export", pool)
            )
        )
        self.client.force_login(employee)
        self.assertEqual(
            self.client.get(reverse("question_export", args=[pool.pk])).status_code,
            200,
        )

    def test_pinning_and_answer_key_need_their_own_pool_permissions(self):
        employee = get_user_model().objects.create_user(username="question-editor")
        pool = QuestionPool.objects.create(name="Feldrechte")
        question = Question.objects.create(
            question_pool=pool,
            text="Frage?",
            question_type=Question.Type.SHORT,
            points=1,
            answer_key="alt",
        )
        employee.user_permissions.add(
            Permission.objects.get(codename=pool_permission_codename("update", pool))
        )
        self.client.force_login(employee)
        self.client.post(
            reverse("question_edit", args=[question.pk]),
            {
                "question_pool": pool.pk,
                "text": "Neu?",
                "question_type": Question.Type.SHORT,
                "points": 1,
                "answer_key": "geändert",
                "is_pinned": "on",
                "option_count": 2,
            },
        )
        question.refresh_from_db()
        self.assertEqual(question.text, "Neu?")
        self.assertEqual(question.answer_key, "alt")
        self.assertFalse(question.is_pinned)
