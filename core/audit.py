"""Gemeinsame Erfassung fachlicher Ereignisse im unveränderlichen Audit-Log."""
from datetime import timedelta
from django.conf import settings
from django.db.models import Subquery
from django.utils import timezone
from .models import AuditLog


def client_ip(request):
    """Liefert ausschließlich die direkte Client-IP aus der Serververbindung."""
    return request.META.get("REMOTE_ADDR") or None


def record_event(request, category, action, description, object_type="", object_id="", metadata=None):
    """Speichert ein fachliches Ereignis ohne Formularinhalte oder Geheimnisse."""
    user = getattr(request, "user", None)
    actor = user if user and user.is_authenticated else None
    return AuditLog.objects.create(
        actor=actor,
        category=category,
        action=action,
        description=description,
        object_type=object_type,
        object_id=str(object_id) if object_id else "",
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        metadata=metadata or {},
    )


def prune_audit_logs(now=None):
    """Entfernt abgelaufene Einträge und bewahrt höchstens die neuesten Protokolle."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)
    expired_count, _details = AuditLog.objects.filter(created_at__lt=cutoff).delete()
    newest_ids = AuditLog.objects.order_by("-created_at", "-pk").values("pk")[:settings.AUDIT_LOG_MAX_ENTRIES]
    excess_count, _details = AuditLog.objects.exclude(pk__in=Subquery(newest_ids)).delete()
    return expired_count + excess_count
