"""Erzeugt und bereinigt dynamische Berechtigungen je Fragenpool."""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver
from .models import QuestionPool
from .permissions import (
    POOL_PERMISSION_PREFIXES,
    pool_permission_codename,
    pool_permission_name,
)


@receiver(post_save, sender=QuestionPool)
def ensure_question_pool_permissions(sender, instance, using, **kwargs):
    """Erzeugt nach Poolanlage die vier konkreten Rechte; aktualisiert Namen nach Umbenennung."""
    content_type = ContentType.objects.db_manager(using).get_for_model(QuestionPool)
    for action in POOL_PERMISSION_PREFIXES:
        Permission.objects.using(using).update_or_create(
            content_type=content_type,
            codename=pool_permission_codename(action, instance),
            defaults={"name": pool_permission_name(action, instance)},
        )


@receiver(post_delete, sender=QuestionPool)
def remove_question_pool_permissions(sender, instance, using, **kwargs):
    """Entfernt nur die dynamischen Rechte dieses Pools nach erfolgreicher Löschung."""
    content_type = ContentType.objects.db_manager(using).get_for_model(QuestionPool)
    codenames = [
        pool_permission_codename(action, instance)
        for action in POOL_PERMISSION_PREFIXES
    ]
    Permission.objects.using(using).filter(
        content_type=content_type, codename__in=codenames
    ).delete()


@receiver(post_migrate)
def synchronize_dynamic_permissions(sender, using, **kwargs):
    """Stellt dynamische Poolrechte nach Migrationen wieder her."""
    if sender.name != "core":
        return
    content_type = ContentType.objects.db_manager(using).get_for_model(QuestionPool)
    Permission.objects.using(using).filter(
        content_type=content_type, codename__startswith="can_bulk_delete_questions_pool_"
    ).delete()
    for question_pool in QuestionPool.objects.using(using).all().iterator():
        ensure_question_pool_permissions(QuestionPool, question_pool, using=using)
