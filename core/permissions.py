"""Zentrale Autorisierungsregeln für Administratoren, globale Rechte und Poolrechte."""
from .models import QuestionPool

ADMINISTRATOR_GROUP = "Administrator"
POOL_PERMISSION_PREFIXES = {
    "view": "can_view_pool_",
    "edit": "can_edit_pool_",
    "import_export": "can_import_export_pool_",
    "generate": "can_generate_test_from_pool_",
    "submissions": "can_view_submissions_pool_",
}
GLOBAL_PERMISSION_CODES = {
    "can_manage_users": "core.can_manage_users",
    "can_manage_tool_settings": "core.can_manage_tool_settings",
    "can_delete_tests": "core.can_delete_tests",
    "can_view_audit_logs": "core.can_view_audit_logs",
    "can_clear_audit_logs": "core.can_clear_audit_logs",
    "can_grant_user_permissions": "core.can_grant_user_permissions",
    "can_revoke_user_permissions": "core.can_revoke_user_permissions",
    "can_grant_administrator": "core.can_grant_administrator",
    "can_revoke_administrator": "core.can_revoke_administrator",
}
DELEGATION_CONTROL_CODES = frozenset({
    "can_clear_audit_logs",
    "can_grant_user_permissions",
    "can_revoke_user_permissions",
    "can_grant_administrator",
    "can_revoke_administrator",
})


def is_administrator(user):
    """Erkennt Administratoren ausschließlich über Djangos Superuser-Status."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser


def pool_permission_codename(action, question_pool):
    """Erzeugt den stabilen Django-Codename für eine Aktion an einem konkreten Pool."""
    prefix = POOL_PERMISSION_PREFIXES.get(action)
    if prefix is None:
        raise ValueError(f"Unbekannte Poolaktion: {action}")
    return f"{prefix}{question_pool.pk}"


def pool_permission_name(action, question_pool):
    """Liefert die verständliche Rechtebezeichnung für Gruppen- und Benutzerformulare."""
    labels = {
        "view": "Fragenpool einsehen",
        "edit": "Fragen im Pool bearbeiten, hinzufügen und löschen",
        "import_export": "Fragen im Pool importieren und exportieren",
        "generate": "Tests aus diesem Pool generieren",
        "submissions": "Abgaben dieses Pools einsehen und bewerten",
    }
    return f"{labels[action]}: {question_pool.name}"


def has_access(user, capability):
    """Prüft ein globales Recht; Administratoren umgehen alle globalen Schranken."""
    if is_administrator(user):
        return True
    permission = GLOBAL_PERMISSION_CODES.get(capability)
    return bool(permission and user.has_perm(permission))


def has_pool_access(user, question_pool, action):
    """Prüft ein Recht für genau einen Pool, niemals poolübergreifend."""
    if is_administrator(user):
        return True
    if not user or not user.is_authenticated or question_pool is None:
        return False
    codename = pool_permission_codename(action, question_pool)
    return user.has_perm(f"core.{codename}")


def accessible_pools(user, action):
    """Liefert ausschließlich Pools zurück, auf die der Benutzer für die Aktion Zugriff hat."""
    pools = QuestionPool.objects.all()
    if is_administrator(user):
        return pools
    if not user or not user.is_authenticated:
        return pools.none()
    allowed_ids = [pool.pk for pool in pools if has_pool_access(user, pool, action)]
    return pools.filter(pk__in=allowed_ids)


def has_any_pool_access(user, action):
    """Prüft, ob ein Mitarbeiter für mindestens einen Fragenpool eine Aktion darf."""
    if is_administrator(user):
        return True
    return accessible_pools(user, action).exists()


def navigation_permissions(request):
    """Stellt ausschließlich tatsächlich erlaubte Navigationsbereiche bereit."""
    user = request.user
    can_manage_users = has_access(user, "can_manage_users")
    return {
        "can_manage_users": can_manage_users,
        "can_manage_permissions": is_administrator(user),
        "can_manage_pools": is_administrator(user),
        "can_clear_audit_logs": has_access(user, "can_clear_audit_logs"),
        "can_view_audit_logs": has_access(user, "can_view_audit_logs"),
        "can_delete_tests": has_access(user, "can_delete_tests"),
        "has_viewable_question_pools": has_any_pool_access(user, "view"),
        "has_editable_question_pools": has_any_pool_access(user, "edit"),
        "has_csv_question_pools": has_any_pool_access(user, "import_export"),
        "can_manage_tool_settings": has_access(user, "can_manage_tool_settings"),
        "has_generatable_question_pools": has_any_pool_access(user, "generate"),
        "has_viewable_submission_pools": has_any_pool_access(user, "submissions"),
    }
