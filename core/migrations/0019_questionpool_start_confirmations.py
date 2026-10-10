from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_pool_fixed_count_pass_and_time_range"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionpool",
            name="start_confirmations",
            field=models.TextField(
                blank=True,
                help_text="Eine Aussage pro Zeile. Der Prüfling muss jede Aussage vor Testbeginn bestätigen. Leer lassen, wenn keine Bestätigung nötig ist.",
                verbose_name="Bestätigungen vor Testbeginn",
            ),
        ),
    ]
