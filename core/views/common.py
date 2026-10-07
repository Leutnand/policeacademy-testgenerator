"""Gemeinsame Hilfsfunktionen und Rechteprüfungen für alle Views."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.shortcuts import render
from django.utils.dateparse import parse_date
from ..permissions import has_access, is_administrator


def require_capability(capability):
    """Erzeugt einen Dekorator für Login- und Fachberechtigungsprüfung."""

    def decorator(view_func):
        """Prüft Rechte vor Ausführung des geschützten Endpunkts."""

        @login_required
        def wrapped(request, *args, **kwargs):
            """Lehnt nicht berechtigte Benutzer direkt mit HTTP 403 ab."""
            if not has_access(request.user, capability):
                return render(
                    request, "core/403.html", {"capability": capability}, status=403
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def require_administrator(view_func):
    """Schützt die zentrale Rechteverwaltung vor normalen Benutzerverwaltern."""

    @login_required
    def wrapped(request, *args, **kwargs):
        """Erlaubt Zugriff ausschließlich per Superuser oder Administratorrolle."""
        if not is_administrator(request.user):
            return render(
                request, "core/403.html", {"capability": "Administrator"}, status=403
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def _effective_academy_permissions(user):
    """Returns readable names of the Academy permissions inherited by a user."""
    codenames = {
        permission.split(".", 1)[1]
        for permission in user.get_all_permissions()
        if permission.startswith("core.")
    }
    return list(
        Permission.objects.filter(
            content_type__app_label="core",
            codename__in=codenames,
        )
        .order_by("name")
        .values_list("name", flat=True)
    )


def _query_without_page(query_params):
    """Returns the current filter query without its pagination cursor."""
    query_params = query_params.copy()
    query_params.pop("page", None)
    return query_params.urlencode()


def _parse_filter_date(value):
    """Parses a browser date filter without raising on malformed query strings."""
    if not value:
        return None
    try:
        return parse_date(value)
    except ValueError:
        return None
