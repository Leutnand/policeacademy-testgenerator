from django.db import migrations, models


def copy_global_limits_to_pools(apps, schema_editor):
    """Übernimmt die bisherigen globalen Grenzen für jeden vorhandenen Pool."""
    ToolSettings = apps.get_model("core", "ToolSettings")
    QuestionPool = apps.get_model("core", "QuestionPool")
    settings = ToolSettings.objects.first()
    if settings:
        QuestionPool.objects.update(
            minimum_test_questions=settings.minimum_test_questions,
            maximum_test_questions=settings.maximum_test_questions,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_testsession_otp_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionpool",
            name="minimum_test_questions",
            field=models.PositiveIntegerField(
                default=1, verbose_name="Minimale Fragenzahl je Test"
            ),
        ),
        migrations.AddField(
            model_name="questionpool",
            name="maximum_test_questions",
            field=models.PositiveIntegerField(
                default=100, verbose_name="Maximale Fragenzahl je Test"
            ),
        ),
        migrations.RunPython(copy_global_limits_to_pools, migrations.RunPython.noop),
        migrations.RemoveField(model_name="toolsettings", name="minimum_test_questions"),
        migrations.RemoveField(model_name="toolsettings", name="maximum_test_questions"),
    ]
