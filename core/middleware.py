"""Protokolliert jeden nicht-statischen HTTP-Aufruf ohne POST-Nutzdaten."""
import logging
from threading import Lock
from time import monotonic
from django.db import DatabaseError
from django.urls import resolve, Resolver404
from django.utils import timezone
from .audit import client_ip, prune_audit_logs
from .models import AuditLog

logger = logging.getLogger(__name__)


class AuditRequestMiddleware:
    """Erfasst Methode, Pfad, Ergebnis, Benutzer und Laufzeit jeder Anfrage."""
    def __init__(self, get_response):
        """Speichert die nächste Middleware in der Django-Kette."""
        self.get_response = get_response
        self._last_retention_cleanup = None
        self._retention_lock = Lock()

    def _run_daily_retention_cleanup(self):
        """Begrenzt das Log täglich, ohne bei jedem Request die Tabelle zu zählen."""
        today = timezone.localdate()
        if self._last_retention_cleanup == today:
            return
        with self._retention_lock:
            if self._last_retention_cleanup == today:
                return
            try:
                prune_audit_logs()
            except DatabaseError:
                logger.exception("Abgelaufene Audit-Log-Einträge konnten nicht entfernt werden.")
            self._last_retention_cleanup = today

    def __call__(self, request):
        """Misst eine Anfrage und protokolliert sie nach der Antwort."""
        started = monotonic()
        path = request.path_info
        if path.startswith(("/static/", "/media/")):
            return self.get_response(request)
        self._run_daily_retention_cleanup()
        response = self.get_response(request)
        try:
            match = resolve(path)
            route_name = match.view_name or ""
        except Resolver404:
            route_name = ""
        user = getattr(request, "user", None)
        actor = user if user and user.is_authenticated else None
        try:
            AuditLog.objects.create(
                actor=actor,
                category=AuditLog.Category.REQUEST,
                action=f"http.{request.method.lower()}",
                description=f"{request.method} {path} → HTTP {response.status_code}",
                object_type="route",
                object_id=route_name,
                ip_address=client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
                metadata={
                    "status_code": response.status_code,
                    "route": route_name,
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                },
            )
        except DatabaseError:
            # Fehlendes Schema während Erstinstallation darf den eigentlichen Request nicht stören.
            logger.exception("HTTP-Anfrage konnte nicht im Audit-Log gespeichert werden.")
        return response
