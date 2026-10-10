from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_questionpool_start_confirmations"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionpool",
            name="start_info_text",
            field=models.TextField(
                blank=True,
                help_text="Optionaler längerer Text, der vor Testbeginn angezeigt wird. Der Prüfling bestätigt ihn mit einer Checkbox „Gelesen und verstanden“.",
                verbose_name="Infotext vor Testbeginn",
            ),
        ),
    ]
