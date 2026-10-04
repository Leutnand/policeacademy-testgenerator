from django.db import migrations, models
import django.db.models.deletion


def initialize_group_order(apps, schema_editor):
    """Ordnet vorhandene Rechtegruppen zunächst stabil alphabetisch."""
    Group = apps.get_model("auth", "Group")
    PermissionGroupSortOrder = apps.get_model("core", "PermissionGroupSortOrder")
    database = schema_editor.connection.alias
    groups = Group.objects.using(database).exclude(name="Administrator").order_by("name")
    PermissionGroupSortOrder.objects.using(database).bulk_create([
        PermissionGroupSortOrder(group_id=group.pk, sort_order=index)
        for index, group in enumerate(groups, start=1)
    ])


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0010_alter_questionpool_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="PermissionGroupSortOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sort_order", models.PositiveIntegerField(default=1, verbose_name="Sortierzahl")),
                ("group", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sort_config",
                    to="auth.group",
                    verbose_name="Rechtegruppe",
                )),
            ],
            options={"ordering": ["sort_order", "group__name"]},
        ),
        migrations.RunPython(initialize_group_order, migrations.RunPython.noop),
    ]
