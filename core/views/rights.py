"""Verwaltung von Rechtegruppen und Einzelrechten."""

from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.db.models import Count, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from ..audit import record_event
from ..forms import PermissionGroupForm, StaffUserForm
from ..models import AuditLog
from ..permissions import (
    ADMINISTRATOR_GROUP,
    GROUP_UPDATE_CAPABILITIES,
    has_access,
    has_any_access,
    is_administrator,
)
from .common import (
    _effective_academy_permissions,
    require_capability,
)


@require_capability("view_groups")
def permissions_dashboard(request):
    """Zeigt Academy-Rechtegruppen nach ihrer Sortierzahl."""
    groups = (
        Group.objects.exclude(name=ADMINISTRATOR_GROUP)
        .prefetch_related("permissions")
        .annotate(
            permission_count=Count("permissions", distinct=True),
            member_count=Count("user", distinct=True),
            display_order=Coalesce("sort_config__sort_order", Value(0)),
        )
        .order_by("display_order", "name")
    )
    return render(
        request,
        "core/permissions.html",
        {
            "groups": groups,
            "can_create_groups": has_access(request.user, "create_groups"),
            "can_update_groups": has_any_access(
                request.user, GROUP_UPDATE_CAPABILITIES
            ),
            "can_delete_groups": has_access(request.user, "delete_groups"),
        },
    )


@require_capability("create_groups")
@require_http_methods(["GET", "POST"])
def permission_group_create(request):
    """Legt eine frei benannte Gruppe mit beliebigen Django-Permissions an."""
    form = PermissionGroupForm(request.POST or None, current_user=request.user)
    if form.is_valid():
        group = form.save()
        record_event(
            request,
            AuditLog.Category.STAFF,
            "permission_group.created",
            "Benutzerdefinierte Rechtegruppe angelegt.",
            "group",
            group.pk,
            {
                "name": group.name,
                "permissions": list(
                    group.permissions.values_list("codename", flat=True)
                ),
            },
        )
        messages.success(request, "Rechtegruppe wurde angelegt.")
        return redirect("permissions_dashboard")
    return render(
        request,
        "core/permission_group_form.html",
        {
            "form": form,
            "title": "Rechtegruppe anlegen",
            "permission_sections": form.permission_sections,
        },
    )


@require_capability(*GROUP_UPDATE_CAPABILITIES)
@require_http_methods(["GET", "POST"])
def permission_group_edit(request, pk):
    """Bearbeitet eine eigene Gruppe; die reservierte Administratorrolle bleibt geschützt."""
    group = get_object_or_404(Group, pk=pk)
    if group.name == ADMINISTRATOR_GROUP:
        return render(
            request,
            "core/403.html",
            {"capability": "Administratorrolle bearbeiten"},
            status=403,
        )
    form = PermissionGroupForm(
        request.POST or None, instance=group, current_user=request.user
    )
    if form.is_valid():
        group = form.save()
        record_event(
            request,
            AuditLog.Category.STAFF,
            "permission_group.updated",
            "Rechtegruppe und zugehörige Rechte aktualisiert.",
            "group",
            group.pk,
            {
                "name": group.name,
                "permissions": list(
                    group.permissions.values_list("codename", flat=True)
                ),
            },
        )
        messages.success(request, "Rechtegruppe wurde aktualisiert.")
        return redirect("permissions_dashboard")
    return render(
        request,
        "core/permission_group_form.html",
        {
            "form": form,
            "title": "Rechtegruppe bearbeiten",
            "permission_sections": form.permission_sections,
        },
    )


@require_capability("delete_groups")
@require_POST
def permission_group_delete(request, pk):
    """Löscht eine eigene Rechtegruppe, nicht aber die reservierte Administratorrolle."""
    group = get_object_or_404(Group, pk=pk)
    if group.name == ADMINISTRATOR_GROUP:
        return render(
            request,
            "core/403.html",
            {"capability": "Administratorrolle löschen"},
            status=403,
        )
    group_name = group.name
    group_id = group.pk
    group.delete()
    record_event(
        request,
        AuditLog.Category.STAFF,
        "permission_group.deleted",
        "Benutzerdefinierte Rechtegruppe gelöscht.",
        "group",
        group_id,
        {"name": group_name},
    )
    messages.success(request, "Rechtegruppe wurde gelöscht.")
    return redirect("permissions_dashboard")


@require_capability("view_user_permissions")
@require_http_methods(["GET", "POST"])
def permission_user_edit(request, pk):
    """Verwaltet Gruppen und individuelle Direktrechte eines Mitarbeiters."""
    if request.method == "POST" and not any(
        has_access(request.user, capability)
        for capability in (
            "can_assign_user_groups",
            "can_unassign_user_groups",
            "can_grant_user_permissions",
            "can_revoke_user_permissions",
            "can_grant_administrator",
            "can_revoke_administrator",
        )
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "Rechte zuweisen oder entziehen"},
            status=403,
        )
    user = get_object_or_404(User, pk=pk)
    form = StaffUserForm(
        request.POST or None,
        instance=user,
        current_user=request.user,
        rights_only=True,
    )
    if form.is_valid():
        user = form.save()
        record_event(
            request,
            AuditLog.Category.STAFF,
            "staff.permissions.updated",
            "Mitarbeitergruppen und Direktrechte aktualisiert.",
            "user",
            user.pk,
            {
                "username": user.username,
                "is_administrator": is_administrator(user),
                "groups": list(user.groups.values_list("name", flat=True)),
                "direct_permissions": list(
                    user.user_permissions.values_list("codename", flat=True)
                ),
            },
        )
        messages.success(request, "Zugriffsrechte wurden gespeichert.")
        return redirect("users_dashboard")
    effective_permission_names = _effective_academy_permissions(user)
    return render(
        request,
        "core/user_form.html",
        {
            "form": form,
            "title": f"Zugriffe: {user.username}",
            "effective_permission_names": effective_permission_names,
        },
    )
