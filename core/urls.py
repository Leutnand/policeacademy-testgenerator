"""URL-Muster der Mitarbeiteroberfläche und des prüflingsseitigen Testablaufs."""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.staff_login, name="login"),
    path("logout/", views.staff_logout, name="logout"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-dashboard/pools/", views.pools_dashboard, name="pools_dashboard"),
    path("admin-dashboard/pools/<int:pk>/edit/", views.pool_edit, name="pool_edit"),
    path("admin-dashboard/pools/<int:pk>/delete/", views.pool_delete, name="pool_delete"),
    path("admin-dashboard/questions/new/", views.question_create, name="question_create"),
    path("admin-dashboard/questions/<int:pk>/edit/", views.question_edit, name="question_edit"),
    path("admin-dashboard/questions/<int:pk>/delete/", views.question_delete, name="question_delete"),
    path("admin-dashboard/users/", views.users_dashboard, name="users_dashboard"),
    path("admin-dashboard/users/new/", views.user_create, name="user_create"),
    path("admin-dashboard/users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("admin-dashboard/permissions/", views.permissions_dashboard, name="permissions_dashboard"),
    path("admin-dashboard/permissions/groups/new/", views.permission_group_create, name="permission_group_create"),
    path("admin-dashboard/permissions/groups/<int:pk>/edit/", views.permission_group_edit, name="permission_group_edit"),
    path("admin-dashboard/permissions/groups/<int:pk>/delete/", views.permission_group_delete, name="permission_group_delete"),
    path("admin-dashboard/permissions/users/<int:pk>/", views.permission_user_edit, name="permission_user_edit"),
    path("generate-test/", views.generate_test_view, name="generate_test"),
    path("test/<uuid:test_id>/", views.take_test, name="take_test"),
    path("submissions/", views.submissions, name="submissions"),
    path("submissions/<uuid:test_id>/", views.submission_detail, name="submission_detail"),
    path("submissions/<uuid:test_id>/delete/", views.delete_test, name="delete_test"),
    path("submissions/<int:pk>/grade/", views.grade_submission, name="grade_submission"),
    path("admin-dashboard/logs/", views.audit_logs, name="audit_logs"),
    path("admin-dashboard/logs/clear/", views.clear_audit_logs, name="clear_audit_logs"),
]
