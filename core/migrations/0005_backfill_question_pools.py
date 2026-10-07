"""Ordnet vorhandene Fragen und Tests dem initialen Einstellungstest zu."""

from django.db import migrations


def assign_default_pool(apps, schema_editor):
    """Erhält alle Bestandsdaten durch Zuordnung zum ersten Standardpool."""
    database = schema_editor.connection.alias
    QuestionPool = apps.get_model("core", "QuestionPool")
    Question = apps.get_model("core", "Question")
    TestSession = apps.get_model("core", "TestSession")
    pool, created = QuestionPool.objects.using(database).get_or_create(
        name="Einstellungstest",
        defaults={"description": "Bestehende Fragen und Tests vor der Poolaufteilung."},
    )
    _ = created
    Question.objects.using(database).filter(question_pool__isnull=True).update(
        question_pool=pool
    )
    TestSession.objects.using(database).filter(question_pool__isnull=True).update(
        question_pool=pool
    )


def reverse_default_pool_assignment(apps, schema_editor):
    """Setzt nur Poolverweise zurück; die Fragensätze selbst bleiben erhalten."""
    database = schema_editor.connection.alias
    Question = apps.get_model("core", "Question")
    TestSession = apps.get_model("core", "TestSession")
    Question.objects.using(database).update(question_pool=None)
    TestSession.objects.using(database).update(question_pool=None)


class Migration(migrations.Migration):
    """Backfill-Migration vor dem Erzwingen der Poolzuordnung."""

    dependencies = [("core", "0004_questionpool_question_question_pool_and_more")]
    operations = [
        migrations.RunPython(assign_default_pool, reverse_default_pool_assignment)
    ]
