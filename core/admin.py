"""Django-Admin-Registrierungen für technische Administration."""
from django.contrib import admin
from .models import AuditLog, Question, Submission, TestQuestion, TestSession


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """Bietet Filter und Suche für den vollständigen Fragenpool."""
    list_display = ("text", "question_type", "points", "is_pinned", "updated_at")
    list_filter = ("question_type", "is_pinned")
    search_fields = ("text", "answer_key")


class TestQuestionInline(admin.TabularInline):
    """Zeigt gespeicherte Fragen-Schnappschüsse im jeweiligen Test."""
    model = TestQuestion
    extra = 0
    readonly_fields = ("position", "text", "question_type", "points")


@admin.register(TestSession)
class TestSessionAdmin(admin.ModelAdmin):
    """Zeigt Testlauf-Metadaten, aber niemals ein OTP im Klartext."""
    list_display = ("id", "status", "created_by", "created_at", "completed_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("otp_hash",)
    inlines = (TestQuestionInline,)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    """Ermöglicht Superusern die technische Prüfung der Abgaben."""
    list_display = ("test", "test_question", "score", "needs_manual_grading", "graded_by")
    list_filter = ("needs_manual_grading",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Stellt Audit-Einträge im Django-Admin ausschließlich lesbar dar."""
    list_display = ("created_at", "actor", "category", "action", "description", "ip_address")
    list_filter = ("category", "action", "created_at")
    search_fields = ("description", "object_id", "actor__username", "ip_address")
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)

    def has_add_permission(self, request):
        """Verhindert manuelles Erzeugen gefälschter Protokolleinträge."""
        _ = request
        return False

    def has_change_permission(self, request, obj=None):
        """Verhindert nachträgliche Manipulation von Audit-Einträgen."""
        _ = request, obj
        return False

    def has_delete_permission(self, request, obj=None):
        """Verhindert das Löschen von Protokollspuren über das Admin-UI."""
        _ = request, obj
        return False
