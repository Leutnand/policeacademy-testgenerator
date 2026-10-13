"""Zentrale Autorisierungsregeln für Administratoren, globale Rechte und Poolrechte."""

from .models import QuestionPool

ADMINISTRATOR_GROUP = "Administrator"
POOL_PERMISSION_PREFIXES = {
    "view": "can_view_pool_",
    "create": "can_create_question_pool_",
    "update": "can_update_question_pool_",
    "import": "can_import_questions_pool_",
    "export": "can_export_questions_pool_",
    "generate": "can_generate_test_from_pool_",
    "view_submissions": "can_view_submissions_pool_",
    "grade": "can_grade_submissions_pool_",
    "delete_single": "can_delete_single_question_pool_",
    "delete_bulk": "can_bulk_delete_questions_pool_",
    "rename_examinee": "can_rename_examinee_pool_",
    "pin": "can_pin_questions_pool_",
    "edit_answer_key": "can_edit_answer_key_pool_",
}
LEGACY_POOL_PERMISSION_PREFIXES = {}
GLOBAL_PERMISSION_CODES = {
    "view_users": "core.can_view_users",
    "create_users": "core.can_create_users",
    # Mitarbeiterkonto: jedes Feld und jede Statusänderung hat ein eigenes Recht
    "can_update_user_username": "core.can_update_user_username",
    "can_update_user_first_name": "core.can_update_user_first_name",
    "can_update_user_last_name": "core.can_update_user_last_name",
    "can_activate_users": "core.can_activate_users",
    "can_deactivate_users": "core.can_deactivate_users",
    "can_set_user_passwords": "core.can_set_user_passwords",
    "can_delete_users": "core.can_delete_users",
    "view_user_permissions": "core.can_view_user_permissions",
    "can_assign_user_groups": "core.can_assign_user_groups",
    "can_unassign_user_groups": "core.can_unassign_user_groups",
    "view_groups": "core.can_view_permission_groups",
    "create_groups": "core.can_create_permission_groups",
    "can_rename_permission_groups": "core.can_rename_permission_groups",
    "can_update_permission_group_priority": "core.can_update_permission_group_priority",
    "delete_groups": "core.can_delete_permission_groups",
    "view_tool_settings": "core.can_view_tool_settings",
    "update_site_name": "core.can_update_site_name",
    "update_department_name": "core.can_update_department_name",
    "update_site_icon": "core.can_update_site_icon",
    "update_login_heading": "core.can_update_login_heading",
    "update_login_text": "core.can_update_login_text",
    "update_privacy_policy": "core.can_update_privacy_policy",
    "update_imprint": "core.can_update_imprint",
    "can_delete_tests": "core.can_delete_tests",
    "can_view_audit_logs": "core.can_view_audit_logs",
    "can_export_audit_logs": "core.can_export_audit_logs",
    "can_clear_audit_logs": "core.can_clear_audit_logs",
    "can_grant_user_permissions": "core.can_grant_user_permissions",
    "can_revoke_user_permissions": "core.can_revoke_user_permissions",
    "can_grant_group_permissions": "core.can_grant_group_permissions",
    "can_revoke_group_permissions": "core.can_revoke_group_permissions",
    "can_grant_administrator": "core.can_grant_administrator",
    "can_revoke_administrator": "core.can_revoke_administrator",
    "can_view_question_pools": "core.can_view_question_pools",
    "can_create_question_pools": "core.can_create_question_pools",
    "can_update_pool_name": "core.can_update_pool_name",
    "can_update_pool_description": "core.can_update_pool_description",
    "can_update_pool_question_count": "core.can_update_pool_question_count",
    "can_update_pool_pass_percentage": "core.can_update_pool_pass_percentage",
    "can_update_pool_min_time_limit": "core.can_update_pool_min_time_limit",
    "can_update_pool_max_time_limit": "core.can_update_pool_max_time_limit",
    "can_update_pool_start_info_text": "core.can_update_pool_start_info_text",
    "can_update_pool_start_confirmations": "core.can_update_pool_start_confirmations",
    "can_delete_question_pools": "core.can_delete_question_pools",
}
DELEGATION_CONTROL_CODES = frozenset(
    {
        "can_clear_audit_logs",
        "can_delete_users",
        "can_view_user_permissions",
        "can_view_permission_groups",
        "can_create_permission_groups",
        "can_rename_permission_groups",
        "can_update_permission_group_priority",
        "can_delete_permission_groups",
        "can_view_question_pools",
        "can_create_question_pools",
        "can_update_pool_name",
        "can_update_pool_description",
        "can_update_pool_question_count",
        "can_update_pool_pass_percentage",
        "can_update_pool_min_time_limit",
        "can_update_pool_max_time_limit",
        "can_update_pool_start_info_text",
        "can_update_pool_start_confirmations",
        "can_delete_question_pools",
        "can_grant_user_permissions",
        "can_revoke_user_permissions",
        "can_grant_group_permissions",
        "can_revoke_group_permissions",
        "can_assign_user_groups",
        "can_unassign_user_groups",
        "can_grant_administrator",
        "can_revoke_administrator",
    }
)

# Zuordnung Formularfeld -> Einzelrecht (jedes Feld ist separat freigebbar)
USER_UPDATE_FIELD_CAPABILITIES = {
    "username": "can_update_user_username",
    "first_name": "can_update_user_first_name",
    "last_name": "can_update_user_last_name",
    "password": "can_set_user_passwords",
}
USER_UPDATE_CAPABILITIES = (
    *USER_UPDATE_FIELD_CAPABILITIES.values(),
    "can_activate_users",
    "can_deactivate_users",
)
GROUP_UPDATE_CAPABILITIES = (
    "can_rename_permission_groups",
    "can_update_permission_group_priority",
    "can_grant_group_permissions",
    "can_revoke_group_permissions",
)
POOL_UPDATE_FIELD_CAPABILITIES = {
    "name": "can_update_pool_name",
    "description": "can_update_pool_description",
    "test_question_count": "can_update_pool_question_count",
    "pass_percentage": "can_update_pool_pass_percentage",
    "minimum_time_limit_minutes": "can_update_pool_min_time_limit",
    "maximum_time_limit_minutes": "can_update_pool_max_time_limit",
    "start_info_text": "can_update_pool_start_info_text",
    "start_confirmations": "can_update_pool_start_confirmations",
}
POOL_UPDATE_CAPABILITIES = tuple(POOL_UPDATE_FIELD_CAPABILITIES.values())


def is_administrator(user):
    """Erkennt Administratoren ausschließlich über Djangos Superuser-Status."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser


def pool_permission_codename(action, question_pool):
    """Erzeugt den stabilen Django-Codename für eine Aktion an einem konkreten Pool."""
    prefix = {**POOL_PERMISSION_PREFIXES, **LEGACY_POOL_PERMISSION_PREFIXES}.get(action)
    if prefix is None:
        raise ValueError(f"Unbekannte Poolaktion: {action}")
    return f"{prefix}{question_pool.pk}"


def pool_permission_name(action, question_pool):
    """Liefert die verständliche Rechtebezeichnung für Gruppen- und Benutzerformulare."""
    labels = {
        "view": "Fragenpool einsehen",
        "create": "Fragen in diesem Pool anlegen",
        "update": "Fragen in diesem Pool ändern",
        "import": "Fragen in diesem Pool importieren",
        "export": "Fragen aus diesem Pool exportieren",
        "generate": "Tests aus diesem Pool generieren",
        "view_submissions": "Abgaben dieses Pools einsehen",
        "grade": "Abgaben dieses Pools bewerten",
        "delete_single": "Einzelne Frage in diesem Pool löschen",
        "delete_bulk": "Mehrere Fragen dieses Pools gleichzeitig löschen",
        "rename_examinee": "Prüflingsnamen in diesem Pool ändern",
        "pin": "Fragen in diesem Pool verankern",
        "edit_answer_key": "Musterlösung in diesem Pool ändern",
    }
    return f"{labels[action]}: {question_pool.name}"


def has_access(user, capability):
    """Prüft ausschließlich das angeforderte Einzelrecht oder den Superuser-Bypass."""
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


def has_any_access(user, capabilities):
    """Prüft, ob mindestens eines der genannten Einzelrechte vorhanden ist."""
    return any(has_access(user, capability) for capability in capabilities)


def navigation_permissions(request):
    """Stellt ausschließlich tatsächlich erlaubte Navigationsbereiche bereit."""
    user = request.user
    can_view_users = has_access(user, "view_users")
    return {
        "can_view_users": can_view_users,
        "can_delete_users": has_access(user, "can_delete_users"),
        "can_view_permission_groups": has_access(user, "view_groups"),
        "can_view_question_pools": has_access(user, "can_view_question_pools"),
        "can_clear_audit_logs": has_access(user, "can_clear_audit_logs"),
        "can_view_audit_logs": has_access(user, "can_view_audit_logs"),
        "can_export_audit_logs": has_access(user, "can_export_audit_logs"),
        "can_delete_tests": has_access(user, "can_delete_tests"),
        "has_viewable_question_pools": has_any_pool_access(user, "view"),
        "has_editable_question_pools": has_any_pool_access(user, "update"),
        "has_csv_question_pools": has_any_pool_access(user, "import")
        or has_any_pool_access(user, "export"),
        "has_generatable_question_pools": has_any_pool_access(user, "generate"),
        "has_viewable_submission_pools": has_any_pool_access(user, "view_submissions"),
        "can_view_user_permissions": has_access(user, "view_user_permissions"),
        "can_create_users": has_access(user, "create_users"),
        "can_update_users": has_any_access(user, USER_UPDATE_CAPABILITIES),
        "can_create_groups": has_access(user, "create_groups"),
        "can_update_groups": has_any_access(user, GROUP_UPDATE_CAPABILITIES),
        "can_delete_groups": has_access(user, "delete_groups"),
        "can_create_question_pools": has_access(user, "can_create_question_pools"),
        "can_update_question_pools": has_any_access(user, POOL_UPDATE_CAPABILITIES),
        "can_delete_question_pools": has_access(user, "can_delete_question_pools"),
        "can_view_tool_settings": has_access(user, "view_tool_settings"),
    }
