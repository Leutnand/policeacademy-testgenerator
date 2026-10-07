from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_toolsettings_staffprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="testsession",
            name="time_limit_minutes",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="Zeitlimit in Minuten"
            ),
        ),
        migrations.AddField(
            model_name="testsession",
            name="started_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Gestartet am"
            ),
        ),
        migrations.AddField(
            model_name="testsession",
            name="elapsed_seconds",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="Bearbeitungszeit in Sekunden"
            ),
        ),
    ]
