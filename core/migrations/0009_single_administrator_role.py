"""Führt Mitglieder der alten Administratorgruppe in den Superuserstatus über."""
from django.db import migrations


def migrate_administrator_group(apps, schema_editor):
    """Erhält den bisherigen Vollzugriff und entfernt die doppelte Gruppenrolle."""
    database = schema_editor.connection.alias
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")
    User.objects.using(database).filter(groups__name="Administrator").update(
        is_superuser=True,
        is_staff=True,
    )
    Group.objects.using(database).filter(name="Administrator").delete()


class Migration(migrations.Migration):
    """Vereinheitlicht Administratorzugriff auf Djangos Superuser-Status."""

    dependencies = [
        ("core", "0008_remove_legacy_rbac"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(migrate_administrator_group, migrations.RunPython.noop)]