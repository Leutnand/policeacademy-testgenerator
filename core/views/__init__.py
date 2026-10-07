"""HTTP-Endpunkte der Anwendung, nach Fachbereichen in Module aufgeteilt."""

from .account import (
    privacy_policy,
    site_icon,
    privacy_accept,
    tool_settings,
    dashboard,
    staff_login,
    staff_logout,
)
from .rights import (
    permissions_dashboard,
    permission_group_create,
    permission_group_edit,
    permission_group_delete,
    permission_user_edit,
)
from .questions import (
    admin_dashboard,
    question_export,
    question_import,
    pools_dashboard,
    pool_edit,
    pool_delete,
    question_create,
    question_edit,
    question_delete,
)
from .tests_flow import (
    generate_test_view,
    take_test,
    submissions,
    delete_test,
    submission_detail,
)
from .users import (
    users_dashboard,
    user_delete,
    user_create,
    user_edit,
)
from .audit import (
    audit_logs,
    audit_logs_export,
    clear_audit_logs,
)

__all__ = [
    "privacy_policy",
    "site_icon",
    "privacy_accept",
    "tool_settings",
    "dashboard",
    "staff_login",
    "staff_logout",
    "permissions_dashboard",
    "permission_group_create",
    "permission_group_edit",
    "permission_group_delete",
    "permission_user_edit",
    "admin_dashboard",
    "question_export",
    "question_import",
    "pools_dashboard",
    "pool_edit",
    "pool_delete",
    "question_create",
    "question_edit",
    "question_delete",
    "generate_test_view",
    "take_test",
    "submissions",
    "delete_test",
    "submission_detail",
    "users_dashboard",
    "user_delete",
    "user_create",
    "user_edit",
    "audit_logs",
    "audit_logs_export",
    "clear_audit_logs",
]
