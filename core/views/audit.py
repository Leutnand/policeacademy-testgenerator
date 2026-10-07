"""Systemlog mit Filter, Export und Bereinigung."""

import csv
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from ..audit import record_event
from ..models import AuditLog
from .common import require_capability, _parse_filter_date


@require_capability("can_view_audit_logs")
def audit_logs(request):
    """Zeigt das zugriffsgeschützte Protokoll mit Filtern und Seiten."""
    selected_category = request.GET.get("category", "")
    for date_field, label in (("from", "Von"), ("to", "Bis")):
        raw_date = request.GET.get(date_field, "")
        if raw_date and _parse_filter_date(raw_date) is None:
            messages.error(request, f"Das Filterdatum „{label}“ ist ungültig.")
    entries = _filtered_audit_logs(request)
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "core/audit_logs.html",
        {
            "page": page,
            "categories": AuditLog.Category.choices,
            "selected_category": selected_category,
            "actor_query": request.GET.get("actor", "").strip()[:100],
            "action_query": request.GET.get("action", "").strip()[:100],
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
            "export_query": request.GET.urlencode(),
        },
    )


def _filtered_audit_logs(request):
    """Applies supported audit filters consistently to the log and CSV export."""
    entries = AuditLog.objects.select_related("actor")
    selected_category = request.GET.get("category", "")
    actor_query = request.GET.get("actor", "").strip()[:100]
    action_query = request.GET.get("action", "").strip()[:100]
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    parsed_from = _parse_filter_date(date_from)
    parsed_to = _parse_filter_date(date_to)
    if selected_category in AuditLog.Category.values:
        entries = entries.filter(category=selected_category)
    if actor_query:
        entries = entries.filter(actor__username__icontains=actor_query)
    if action_query:
        entries = entries.filter(
            Q(action__icontains=action_query) | Q(description__icontains=action_query)
        )
    if parsed_from:
        entries = entries.filter(created_at__date__gte=parsed_from)
    if parsed_to:
        entries = entries.filter(created_at__date__lte=parsed_to)
    return entries


@require_capability("can_view_audit_logs")
def audit_logs_export(request):
    """Exportiert ausschließlich die gefilterten Audit-Einträge als CSV."""
    if any(
        request.GET.get(field) and _parse_filter_date(request.GET[field]) is None
        for field in ("from", "to")
    ):
        return HttpResponseBadRequest("Ein übergebenes Filterdatum ist ungültig.")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="systemprotokoll.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        (
            "Zeitpunkt",
            "Benutzer",
            "Kategorie",
            "Aktion",
            "Beschreibung",
            "Objekttyp",
            "Objekt-ID",
            "IP-Adresse",
            "Browserkennung",
        )
    )
    for entry in (
        _filtered_audit_logs(request).order_by("-created_at", "-pk").iterator()
    ):
        values = (
            timezone.localtime(entry.created_at).isoformat(),
            entry.actor.username if entry.actor else "",
            entry.get_category_display(),
            entry.action,
            entry.description,
            entry.object_type,
            entry.object_id,
            entry.ip_address or "",
            entry.user_agent,
        )
        writer.writerow(
            tuple(
                (
                    f"\t{value}"
                    if isinstance(value, str)
                    and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                    else value
                )
                for value in values
            )
        )
    return response


@require_capability("can_view_audit_logs")
@require_capability("can_clear_audit_logs")
@require_POST
def clear_audit_logs(request):
    """Leert das Protokoll und hält die Löschung selbst im neuen Log fest."""
    deleted_count = AuditLog.objects.count()
    with transaction.atomic():
        AuditLog.objects.all().delete()
        record_event(
            request,
            AuditLog.Category.SECURITY,
            "audit_logs.cleared",
            "Systemprotokoll manuell geleert.",
            "audit_log",
            "",
            {"deleted_entries": deleted_count},
        )
    messages.success(
        request, f"Protokoll geleert; {deleted_count} Einträge wurden entfernt."
    )
    return redirect("audit_logs")
