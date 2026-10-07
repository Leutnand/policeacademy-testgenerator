"""Verwaltung von Mitarbeiterkonten."""

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from ..forms import StaffUserForm
from ..audit import record_event
from ..models import AuditLog
from ..permissions import has_access, is_administrator
from .common import require_capability, _effective_academy_permissions


@require_capability("can_manage_users")
def users_dashboard(request):
    """Listet Mitarbeiterkonten und deren Aktivierungsstatus."""
    users = User.objects.prefetch_related("groups", "user_permissions").order_by(
        "username"
    )
    return render(
        request,
        "core/users.html",
        {
            "users": users,
            "can_delete_admin_users": is_administrator(request.user),
        },
    )


@require_capability("can_manage_users")
@require_capability("can_delete_users")
@require_POST
def user_delete(request, pk):
    """Löscht ein Mitarbeiterkonto, bewahrt Tests und protokolliert den Vorgang."""
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "Du kannst dein eigenes Konto nicht löschen.")
        return redirect("users_dashboard")
    if is_administrator(user) and not is_administrator(request.user):
        return render(
            request,
            "core/403.html",
            {"capability": "Administrator löschen"},
            status=403,
        )
    if is_administrator(user) and User.objects.filter(is_superuser=True).count() <= 1:
        messages.error(request, "Der letzte Administrator kann nicht gelöscht werden.")
        return redirect("users_dashboard")
    username = user.username
    user_id = user.pk
    with transaction.atomic():
        record_event(
            request,
            AuditLog.Category.SECURITY,
            "staff.deleted",
            f"Mitarbeiterkonto „{username}“ gelöscht.",
            "user",
            user_id,
            {"username": username},
        )
        user.delete()
    messages.success(
        request,
        f"Das Konto „{username}“ wurde gelöscht. Zugehörige Tests bleiben erhalten.",
    )
    return redirect("users_dashboard")


@require_capability("can_manage_users")
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def user_create(request):
    """Erstellt ein Mitarbeiterkonto mit mindestens initialem Passwort."""
    form = StaffUserForm(request.POST or None, current_user=request.user)
    if form.is_valid():
        if not form.cleaned_data.get("password"):
            form.add_error(
                "password", "Für neue Benutzer ist ein Passwort erforderlich."
            )
        else:
            user = form.save()
            record_event(
                request,
                AuditLog.Category.STAFF,
                "staff.created",
                "Mitarbeiterkonto angelegt.",
                "user",
                user.pk,
                {
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_administrator": user.is_superuser,
                    "groups": list(user.groups.values_list("name", flat=True)),
                    "direct_permissions": list(
                        user.user_permissions.values_list("codename", flat=True)
                    ),
                },
            )
            messages.success(request, "Mitarbeiterkonto wurde angelegt.")
            return redirect("users_dashboard")
    return render(
        request, "core/user_form.html", {"form": form, "title": "Mitarbeiter erstellen"}
    )


@require_capability("can_manage_users")
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def user_edit(request, pk):
    """Bearbeitet Kontodaten, Aktivierung, Gruppen und Einzelberechtigungen."""
    user = get_object_or_404(User, pk=pk)
    if (
        is_administrator(user)
        and not is_administrator(request.user)
        and not has_access(request.user, "can_revoke_administrator")
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "Administrator bearbeiten"},
            status=403,
        )
    form = StaffUserForm(request.POST or None, instance=user, current_user=request.user)
    if form.is_valid():
        user = form.save()
        record_event(
            request,
            AuditLog.Category.STAFF,
            "staff.updated",
            "Mitarbeiterkonto und Berechtigungen aktualisiert.",
            "user",
            user.pk,
            {
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_administrator": user.is_superuser,
                "is_active": user.is_active,
                "groups": list(user.groups.values_list("name", flat=True)),
                "direct_permissions": list(
                    user.user_permissions.values_list("codename", flat=True)
                ),
            },
        )
        messages.success(request, "Mitarbeiterkonto wurde aktualisiert.")
        return redirect("users_dashboard")
    return render(
        request,
        "core/user_form.html",
        {
            "form": form,
            "title": "Mitarbeiter bearbeiten",
            "effective_permission_names": _effective_academy_permissions(user),
        },
    )
