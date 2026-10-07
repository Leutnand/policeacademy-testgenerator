"""Entfernt die alten festen Rollen und globalen Poolrechte einmalig."""

from django.db import migrations

LEGACY_GROUP_NAMES = ["Fragen-Editor", "Test-Manager", "Korrektor"]
LEGACY_POOL_PERMISSION_CODES = [
    "can_manage_questions",
    "can_generate_tests",
    "can_view_submissions",
    "can_grade_submissions",
    "can_manage_users",
    "can_delete_tests",
    "can_view_audit_logs",
]


def remove_legacy_roles_and_permissions(apps, schema_editor):
    """Bereinigt Datenbankrollen und Poolrechte vor dem neuen dynamischen Modell."""
    database = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group.objects.using(database).filter(name__in=LEGACY_GROUP_NAMES).delete()
    Group.objects.using(database).get_or_create(name="Administrator")
    question_type = (
        ContentType.objects.using(database)
        .filter(app_label="core", model="question")
        .first()
    )
    if question_type:
        Permission.objects.using(database).filter(
            content_type=question_type,
            codename__in=LEGACY_POOL_PERMISSION_CODES,
        ).delete()


def keep_clean_state_on_reverse(apps, schema_editor):
    """Lässt beim Rückwärtslauf die reservierte Administratorrolle unberührt."""
    return None


class Migration(migrations.Migration):
    """Wendet das Entfernen der starren Rollen als nachvollziehbare Migration an."""

    dependencies = [("core", "0007_alter_question_options_alter_questionpool_options")]
    operations = [
        migrations.RunPython(
            remove_legacy_roles_and_permissions, keep_clean_state_on_reverse
        )
    ]
