"""HTTP-Endpunkte der Anwendung, nach Fachbereichen in Module aufgeteilt."""

from .account import (
    dashboard,
    privacy_accept,
    privacy_policy,
    site_icon,
    staff_login,
    staff_logout,
    tool_settings,
)
from .audit import (
    audit_logs,
    audit_logs_export,
    clear_audit_logs,
)
from .questions import (
    admin_dashboard,
    pool_delete,
    pool_edit,
    pools_dashboard,
    question_bulk_delete,
    question_create,
    question_delete,
    question_edit,
    question_export,
    question_import,
)
from .rights import (
    permission_group_create,
    permission_group_delete,
    permission_group_edit,
    permission_user_edit,
    permissions_dashboard,
)
from .tests_flow import (
    delete_test,
    generate_test_view,
    rename_examinee,
    running_tests,
    submission_detail,
    submissions,
    take_test,
)
from .users import (
    user_create,
    user_delete,
    user_edit,
    users_dashboard,
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
    "question_bulk_delete",
    "question_delete",
    "generate_test_view",
    "take_test",
    "running_tests",
    "submissions",
    "delete_test",
    "submission_detail",
    "rename_examinee",
    "users_dashboard",
    "user_delete",
    "user_create",
    "user_edit",
    "audit_logs",
    "audit_logs_export",
    "clear_audit_logs",
]
