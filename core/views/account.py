"""Startseite, Datenschutz, Tool-Einstellungen und Mitarbeiter-Anmeldung."""

import hashlib
from mimetypes import guess_type
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from ..forms import PrivacyAcceptanceForm, ToolSettingsForm
from ..audit import record_event
from ..models import AuditLog, StaffProfile, ToolSettings
from ..permissions import has_access, has_any_pool_access
from .common import require_capability


def privacy_policy(request):
    """Zeigt Datenschutzerklärung und Impressum auch ohne Mitarbeiteranmeldung an."""
    return render(
        request, "core/privacy_policy.html", {"tool_settings": ToolSettings.current()}
    )


def site_icon(request):
    """Liefert das konfigurierte, auf Bildformate begrenzte Favicon aus dem Media-Storage."""
    _ = request
    configuration = ToolSettings.objects.filter(pk=1).first()
    if not configuration or not configuration.site_icon:
        raise Http404("Kein Site-Icon konfiguriert.")
    content_type = (
        guess_type(configuration.site_icon.name)[0] or "application/octet-stream"
    )
    return FileResponse(
        configuration.site_icon.open("rb"),
        content_type=content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def privacy_accept(request):
    """Speichert die ausdrückliche Bestätigung der aktuell hinterlegten Erklärung."""
    tool_settings = ToolSettings.current()
    policy = tool_settings.privacy_policy.strip()
    form = PrivacyAcceptanceForm(request.POST or None)
    if request.method == "POST" and policy and form.is_valid():
        policy_hash = hashlib.sha256(policy.encode("utf-8")).hexdigest()
        StaffProfile.objects.update_or_create(
            user=request.user,
            defaults={
                "accepted_privacy_hash": policy_hash,
                "privacy_accepted_at": timezone.now(),
            },
        )
        record_event(
            request,
            AuditLog.Category.STAFF,
            "privacy_policy.accepted",
            "Mitarbeiter hat die aktuelle Datenschutzerklärung bestätigt.",
            "user",
            request.user.pk,
            {"policy_hash": policy_hash},
        )
        messages.success(request, "Datenschutzerklärung bestätigt.")
        return redirect("dashboard")
    return render(
        request,
        "core/privacy_accept.html",
        {
            "tool_settings": tool_settings,
            "form": form,
            "policy_configured": bool(policy),
        },
    )


@require_capability("can_manage_tool_settings")
@require_http_methods(["GET", "POST"])
def tool_settings(request):
    """Bearbeitet zentrale Branding-, Prüfungs- und Rechtstext-Einstellungen."""
    configuration = ToolSettings.current()
    form = ToolSettingsForm(
        request.POST or None, request.FILES or None, instance=configuration
    )
    if form.is_valid():
        changed_fields = list(form.changed_data)
        form.save()
        record_event(
            request,
            AuditLog.Category.STAFF,
            "tool_settings.updated",
            "Zentrale Einstellungen des Testgenerators aktualisiert.",
            "tool_settings",
            configuration.pk,
            {"changed_fields": changed_fields},
        )
        messages.success(request, "Einstellungen wurden gespeichert.")
        return redirect("tool_settings")
    return render(request, "core/tool_settings.html", {"form": form})


def dashboard(request):
    """Leitet angemeldete Mitarbeiter zum passenden Arbeitsbereich."""
    if request.user.is_authenticated:
        for capability, route in (
            ("question_view", "admin_dashboard"),
            ("question_generate", "generate_test"),
            ("question_submissions", "submissions"),
            ("can_manage_users", "users_dashboard"),
        ):
            allowed = (
                has_any_pool_access(request.user, "view")
                if capability == "question_view"
                else (
                    has_any_pool_access(request.user, "generate")
                    if capability == "question_generate"
                    else (
                        has_any_pool_access(request.user, "submissions")
                        if capability == "question_submissions"
                        else has_access(request.user, capability)
                    )
                )
            )
            if allowed:
                return redirect(route)
        return render(request, "core/no_access.html", status=403)
    return redirect("login")


@require_http_methods(["GET", "POST"])
def staff_login(request):
    """Authentifiziert Mitarbeiter über Django-Benutzername und Passwort."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
        )
        if user is not None and user.is_active:
            login(request, user)
            record_event(
                request,
                AuditLog.Category.AUTH,
                "auth.login.success",
                "Mitarbeiter erfolgreich angemeldet.",
                "user",
                user.pk,
            )
            return redirect("dashboard")
        record_event(
            request,
            AuditLog.Category.AUTH,
            "auth.login.failed",
            "Fehlgeschlagener Anmeldeversuch.",
            metadata={"attempted_username": request.POST.get("username", "")[:150]},
        )
        messages.error(request, "Anmeldung fehlgeschlagen. Bitte Zugangsdaten prüfen.")
    return render(request, "registration/login.html")


@login_required
def staff_logout(request):
    """Beendet eine Mitarbeitersitzung und führt zurück zur Anmeldung."""
    record_event(
        request,
        AuditLog.Category.AUTH,
        "auth.logout",
        "Mitarbeiter abgemeldet.",
        "user",
        request.user.pk,
    )
    logout(request)
    return redirect("login")
