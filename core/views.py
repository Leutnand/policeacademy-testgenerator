"""HTTP-Endpunkte für RBAC-Verwaltung, Testausgabe und Korrektur."""
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from .forms import ExamineeNameForm, GenerateTestForm, OtpForm, PermissionGroupForm, QuestionForm, QuestionPoolForm, StaffUserForm
from .audit import record_event
from .models import AuditLog, Question, QuestionPool, Submission, TestSession
from .permissions import (
    ADMINISTRATOR_GROUP,
    accessible_pools,
    has_access,
    has_any_pool_access,
    has_pool_access,
    is_administrator,
)
from .services import TestGenerationError, generate_test, grade_answer


def require_capability(capability):
    """Erzeugt einen Dekorator für Login- und Fachberechtigungsprüfung."""
    def decorator(view_func):
        """Prüft Rechte vor Ausführung des geschützten Endpunkts."""
        @login_required
        def wrapped(request, *args, **kwargs):
            """Lehnt nicht berechtigte Benutzer direkt mit HTTP 403 ab."""
            if not has_access(request.user, capability):
                return render(request, "core/403.html", {"capability": capability}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def require_administrator(view_func):
    """Schützt die zentrale Rechteverwaltung vor normalen Benutzerverwaltern."""
    @login_required
    def wrapped(request, *args, **kwargs):
        """Erlaubt Zugriff ausschließlich per Superuser oder Administratorrolle."""
        if not is_administrator(request.user):
            return render(request, "core/403.html", {"capability": "Administrator"}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapped


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
                has_any_pool_access(request.user, "view") if capability == "question_view"
                else has_any_pool_access(request.user, "generate") if capability == "question_generate"
                else has_any_pool_access(request.user, "submissions") if capability == "question_submissions"
                else has_access(request.user, capability)
            )
            if allowed:
                return redirect(route)
        return render(request, "core/no_access.html", status=403)
    return redirect("login")


@require_administrator
def permissions_dashboard(request):
    """Zeigt benutzerdefinierte Gruppen mit Rechten und Mitgliederzahlen."""
    groups = Group.objects.exclude(name=ADMINISTRATOR_GROUP).prefetch_related("permissions").annotate(
        permission_count=Count("permissions", distinct=True),
        member_count=Count("user", distinct=True),
    ).order_by("name")
    return render(request, "core/permissions.html", {
        "groups": groups,
    })


@require_administrator
@require_http_methods(["GET", "POST"])
def permission_group_create(request):
    """Legt eine frei benannte Gruppe mit beliebigen Django-Permissions an."""
    form = PermissionGroupForm(request.POST or None)
    if form.is_valid():
        group = form.save()
        record_event(request, AuditLog.Category.STAFF, "permission_group.created", "Benutzerdefinierte Rechtegruppe angelegt.", "group", group.pk, {"name": group.name, "permissions": list(group.permissions.values_list("codename", flat=True))})
        messages.success(request, "Rechtegruppe wurde angelegt.")
        return redirect("permissions_dashboard")
    return render(request, "core/permission_group_form.html", {
        "form": form, "title": "Rechtegruppe anlegen", "permission_sections": form.permission_sections,
    })


@require_administrator
@require_http_methods(["GET", "POST"])
def permission_group_edit(request, pk):
    """Bearbeitet eine eigene Gruppe; die reservierte Administratorrolle bleibt geschützt."""
    group = get_object_or_404(Group, pk=pk)
    if group.name == ADMINISTRATOR_GROUP:
        return render(request, "core/403.html", {"capability": "Administratorrolle bearbeiten"}, status=403)
    form = PermissionGroupForm(request.POST or None, instance=group)
    if form.is_valid():
        group = form.save()
        record_event(request, AuditLog.Category.STAFF, "permission_group.updated", "Rechtegruppe und zugehörige Rechte aktualisiert.", "group", group.pk, {"name": group.name, "permissions": list(group.permissions.values_list("codename", flat=True))})
        messages.success(request, "Rechtegruppe wurde aktualisiert.")
        return redirect("permissions_dashboard")
    return render(request, "core/permission_group_form.html", {
        "form": form, "title": "Rechtegruppe bearbeiten", "permission_sections": form.permission_sections,
    })


@require_administrator
@require_POST
def permission_group_delete(request, pk):
    """Löscht eine eigene Rechtegruppe, nicht aber die reservierte Administratorrolle."""
    group = get_object_or_404(Group, pk=pk)
    if group.name == ADMINISTRATOR_GROUP:
        return render(request, "core/403.html", {"capability": "Administratorrolle löschen"}, status=403)
    group_name = group.name
    group_id = group.pk
    group.delete()
    record_event(request, AuditLog.Category.STAFF, "permission_group.deleted", "Benutzerdefinierte Rechtegruppe gelöscht.", "group", group_id, {"name": group_name})
    messages.success(request, "Rechtegruppe wurde gelöscht.")
    return redirect("permissions_dashboard")


@require_capability("can_manage_users")
@require_http_methods(["GET", "POST"])
def permission_user_edit(request, pk):
    """Verwaltet Gruppen und individuelle Direktrechte eines Mitarbeiters."""
    user = get_object_or_404(User, pk=pk)
    form = StaffUserForm(request.POST or None, instance=user, current_user=request.user)
    if form.is_valid():
        user = form.save()
        record_event(request, AuditLog.Category.STAFF, "staff.permissions.updated", "Mitarbeitergruppen und Direktrechte aktualisiert.", "user", user.pk, {
            "username": user.username,
            "is_administrator": is_administrator(user),
            "groups": list(user.groups.values_list("name", flat=True)),
            "direct_permissions": list(user.user_permissions.values_list("codename", flat=True)),
        })
        messages.success(request, "Zugriffsrechte wurden gespeichert.")
        return redirect("users_dashboard")
    return render(request, "core/user_form.html", {"form": form, "title": f"Zugriffe: {user.username}"})


@require_http_methods(["GET", "POST"])
def staff_login(request):
    """Authentifiziert Mitarbeiter über Django-Benutzername und Passwort."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username", ""), password=request.POST.get("password", ""))
        if user is not None and user.is_active:
            login(request, user)
            record_event(request, AuditLog.Category.AUTH, "auth.login.success", "Mitarbeiter erfolgreich angemeldet.", "user", user.pk)
            return redirect("dashboard")
        record_event(
            request, AuditLog.Category.AUTH, "auth.login.failed", "Fehlgeschlagener Anmeldeversuch.",
            metadata={"attempted_username": request.POST.get("username", "")[:150]},
        )
        messages.error(request, "Anmeldung fehlgeschlagen. Bitte Zugangsdaten prüfen.")
    return render(request, "registration/login.html")


@login_required
def staff_logout(request):
    """Beendet eine Mitarbeitersitzung und führt zurück zur Anmeldung."""
    record_event(request, AuditLog.Category.AUTH, "auth.logout", "Mitarbeiter abgemeldet.", "user", request.user.pk)
    logout(request)
    return redirect("login")


@login_required
def admin_dashboard(request):
    """Zeigt nur Fragenpools, für die View-Recht ausdrücklich erteilt wurde."""
    pools = accessible_pools(request.user, "view")
    requested_pool = request.GET.get("pool")
    if requested_pool:
        selected_pool = pools.filter(pk=requested_pool).first()
        if selected_pool is None:
            return render(request, "core/403.html", {"capability": "can_view_pool"}, status=403)
    else:
        selected_pool = pools.first()
    if selected_pool is None:
        return render(request, "core/403.html", {"capability": "can_view_pool"}, status=403)
    questions = Question.objects.filter(question_pool=selected_pool) if selected_pool else Question.objects.none()
    return render(request, "core/admin_dashboard.html", {
        "questions": questions,
        "pools": pools,
        "selected_pool": selected_pool,
        "pinned_count": questions.filter(is_pinned=True).count(),
        "can_edit_selected_pool": has_pool_access(request.user, selected_pool, "edit"),
    })


@require_administrator
@require_http_methods(["GET", "POST"])
def pools_dashboard(request):
    """Listet Prüfungstypen und legt neue, voneinander getrennte Fragenpools an."""
    form = QuestionPoolForm(request.POST or None)
    if form.is_valid():
        question_pool = form.save()
        record_event(
            request, AuditLog.Category.QUESTION, "question_pool.created", "Neuer Fragenpool angelegt.",
            "question_pool", question_pool.pk, {"name": question_pool.name},
        )
        messages.success(request, "Fragenpool wurde angelegt.")
        return redirect("pools_dashboard")
    pools = QuestionPool.objects.annotate(
        question_count=Count("questions", distinct=True),
        test_count=Count("test_sessions", distinct=True),
    )
    return render(request, "core/pools.html", {"form": form, "pools": pools})


@require_administrator
@require_http_methods(["GET", "POST"])
def pool_edit(request, pk):
    """Benennt einen vorhandenen Prüfungspool um, ohne Fragen zu verschieben."""
    question_pool = get_object_or_404(QuestionPool, pk=pk)
    form = QuestionPoolForm(request.POST or None, instance=question_pool)
    if form.is_valid():
        question_pool = form.save()
        record_event(
            request, AuditLog.Category.QUESTION, "question_pool.updated", "Fragenpool bearbeitet.",
            "question_pool", question_pool.pk, {"name": question_pool.name},
        )
        messages.success(request, "Fragenpool wurde aktualisiert.")
        return redirect("pools_dashboard")
    return render(request, "core/pool_form.html", {"form": form, "title": "Fragenpool bearbeiten"})


@require_administrator
@require_POST
def pool_delete(request, pk):
    """Löscht ausschließlich leere Pools und bewahrt Pools verwendeter Tests."""
    question_pool = get_object_or_404(QuestionPool, pk=pk)
    if QuestionPool.objects.count() <= 1:
        messages.error(request, "Der letzte Fragenpool kann nicht gelöscht werden.")
        return redirect("pools_dashboard")
    if question_pool.questions.exists() or question_pool.test_sessions.exists():
        messages.error(request, "Dieser Fragenpool enthält Fragen oder Testläufe und kann nicht gelöscht werden.")
        return redirect("pools_dashboard")
    record_event(
        request, AuditLog.Category.QUESTION, "question_pool.deleted", "Leerer Fragenpool gelöscht.",
        "question_pool", question_pool.pk, {"name": question_pool.name},
    )
    question_pool.delete()
    messages.success(request, "Leerer Fragenpool wurde gelöscht.")
    return redirect("pools_dashboard")


@login_required
@require_http_methods(["GET", "POST"])
def question_create(request):
    """Legt eine Frage im ausgewählten Prüfungspool an."""
    visible_pool_ids = accessible_pools(request.user, "view").values_list("pk", flat=True)
    editable_pools = accessible_pools(request.user, "edit").filter(pk__in=visible_pool_ids)
    if not editable_pools.exists():
        return render(request, "core/403.html", {"capability": "can_edit_pool"}, status=403)
    requested_pool_id = request.GET.get("pool") or request.POST.get("question_pool")
    if requested_pool_id and not editable_pools.filter(pk=requested_pool_id).exists():
        return render(request, "core/403.html", {"capability": "can_edit_pool"}, status=403)
    selected_pool_id = request.GET.get("pool") or editable_pools.values_list("pk", flat=True).first()
    initial = {"question_pool": selected_pool_id} if selected_pool_id else None
    form = QuestionForm(request.POST or None, initial=initial)
    form.fields["question_pool"].queryset = editable_pools
    if form.is_valid():
        question = form.save()
        record_event(
            request, AuditLog.Category.QUESTION, "question.created", "Prüfungsfrage angelegt.",
            "question", question.pk,
            {"text": question.text, "question_type": question.question_type, "options": question.options,
               "answer_key": question.answer_key, "points": str(question.points), "is_pinned": question.is_pinned,
               "question_pool": question.question_pool.name},
        )
        messages.success(request, "Frage wurde angelegt.")
        return redirect(f"{reverse('admin_dashboard')}?pool={question.question_pool_id}")
    return render(request, "core/question_form.html", {"form": form, "title": "Frage erstellen", "option_rows": form.option_rows})


@login_required
@require_http_methods(["GET", "POST"])
def question_edit(request, pk):
    """Bearbeitet eine Frage nach serverseitiger Rechteprüfung."""
    question = get_object_or_404(Question, pk=pk)
    if not has_pool_access(request.user, question.question_pool, "view") or not has_pool_access(request.user, question.question_pool, "edit"):
        return render(request, "core/403.html", {"capability": "can_edit_pool"}, status=403)
    visible_pool_ids = accessible_pools(request.user, "view").values_list("pk", flat=True)
    editable_pools = accessible_pools(request.user, "edit").filter(pk__in=visible_pool_ids)
    if request.method == "POST":
        target_pool_id = request.POST.get("question_pool")
        if target_pool_id and not editable_pools.filter(pk=target_pool_id).exists():
            return render(request, "core/403.html", {"capability": "can_edit_pool"}, status=403)
    form = QuestionForm(request.POST or None, instance=question)
    form.fields["question_pool"].queryset = editable_pools
    if form.is_valid():
        question = form.save()
        record_event(
            request, AuditLog.Category.QUESTION, "question.updated", "Prüfungsfrage bearbeitet.",
            "question", question.pk,
            {"text": question.text, "question_type": question.question_type, "options": question.options,
               "answer_key": question.answer_key, "points": str(question.points), "is_pinned": question.is_pinned,
               "question_pool": question.question_pool.name},
        )
        messages.success(request, "Frage wurde gespeichert.")
        return redirect(f"{reverse('admin_dashboard')}?pool={question.question_pool_id}")
    return render(request, "core/question_form.html", {"form": form, "title": "Frage bearbeiten", "option_rows": form.option_rows})


@login_required
@require_POST
def question_delete(request, pk):
    """Löscht eine Frage ausschließlich über eine CSRF-geschützte POST-Aktion."""
    question = get_object_or_404(Question, pk=pk)
    if not has_pool_access(request.user, question.question_pool, "view") or not has_pool_access(request.user, question.question_pool, "edit"):
        return render(request, "core/403.html", {"capability": "can_edit_pool"}, status=403)
    question_pool_id = question.question_pool_id
    record_event(
        request, AuditLog.Category.QUESTION, "question.deleted", "Prüfungsfrage gelöscht.",
        "question", question.pk,
        {"text": question.text, "question_type": question.question_type,
         "options": question.options, "answer_key": question.answer_key},
    )
    question.delete()
    messages.success(request, "Frage wurde gelöscht.")
    return redirect(f"{reverse('admin_dashboard')}?pool={question_pool_id}")


@login_required
@require_http_methods(["GET", "POST"])
def generate_test_view(request):
    """Generiert Test, OTP und Direktlink ausschließlich aus einem Fragenpool."""
    generatable_pools = accessible_pools(request.user, "generate")
    if not generatable_pools.exists():
        return render(request, "core/403.html", {"capability": "can_generate_test_from_pool"}, status=403)
    requested_pool_id = request.POST.get("question_pool") if request.method == "POST" else None
    if requested_pool_id and not generatable_pools.filter(pk=requested_pool_id).exists():
        return render(request, "core/403.html", {"capability": "can_generate_test_from_pool"}, status=403)
    form = GenerateTestForm(request.POST or None, question_pools=generatable_pools)
    result = None
    form_is_valid = form.is_valid()
    if form_is_valid:
        try:
            test, otp = generate_test(
                form.cleaned_data["question_count"], request.user, form.cleaned_data["question_pool"],
            )
        except TestGenerationError as error:
            form.add_error("question_count", str(error))
        else:
            result = {"test": test, "otp": otp, "url": request.build_absolute_uri(f"/test/{test.pk}/")}
            record_event(
                request, AuditLog.Category.TEST, "test.generated", "Neuer Testlauf erstellt.",
                "test", test.pk, {"question_count": test.items.count(), "question_pool": test.question_pool.name},
            )
    selected_pool = form.cleaned_data.get("question_pool") if form.is_bound else form.fields["question_pool"].initial
    if not hasattr(selected_pool, "pk"):
        selected_pool = QuestionPool.objects.filter(pk=selected_pool).first() if selected_pool else None
    pool_choices = generatable_pools.annotate(
        question_count=Count("questions", distinct=True),
        pinned_count=Count("questions", filter=Q(questions__is_pinned=True), distinct=True),
    )
    selected_counts = next((pool for pool in pool_choices if selected_pool and pool.pk == selected_pool.pk), None)
    return render(request, "core/generate_test.html", {
        "form": form, "result": result, "selected_pool": selected_pool,
        "pool_choices": pool_choices,
        "available_count": selected_counts.question_count if selected_counts else 0,
        "pinned_count": selected_counts.pinned_count if selected_counts else 0,
    })


def _public_questions(test):
    """Erstellt eine explizite Prüflingsprojektion ohne Punkte oder Lösungen."""
    return [{
        "id": item.pk, "position": item.position, "text": item.text,
        "question_type": item.question_type,
        "options": [{"index": index, "text": option["text"]} for index, option in enumerate(item.options)],
    } for item in test.items.all()]


@require_http_methods(["GET", "POST"])
def take_test(request, test_id):
    """Prüft OTP-Zugang, rendert Fragen sicher und verbraucht ihn atomar."""
    test = get_object_or_404(TestSession, pk=test_id)
    session_key = f"test_access_{test.pk}"
    name_session_key = f"test_name_{test.pk}"
    if test.status != TestSession.Status.ISSUED:
        return render(request, "core/test_unavailable.html", status=410)
    if request.session.get(session_key) != str(test.pk):
        otp_form = OtpForm(request.POST or None)
        if request.method == "POST" and otp_form.is_valid():
            if check_password(otp_form.cleaned_data["otp"], test.otp_hash):
                request.session[session_key] = str(test.pk)
                record_event(
                    request, AuditLog.Category.AUTH, "test.otp.accepted", "Einmalpasswort für Testzugang bestätigt.",
                    "test", test.pk,
                )
                return redirect("take_test", test_id=test.pk)
            record_event(
                request, AuditLog.Category.SECURITY, "test.otp.rejected", "Ungültiger Versuch mit einem Test-Einmalpasswort.",
                "test", test.pk,
            )
            otp_form.add_error("otp", "Das Einmalpasswort ist ungültig.")
        return render(request, "core/otp.html", {"form": otp_form, "test": test})
    if not request.session.get(name_session_key):
        name_form = ExamineeNameForm(request.POST or None)
        if request.method == "POST" and name_form.is_valid():
            request.session[name_session_key] = name_form.cleaned_data["examinee_name"]
            return redirect("take_test", test_id=test.pk)
        return render(request, "core/examinee_name.html", {"form": name_form, "test": test})
    items = list(test.items.all())
    if request.method == "POST":
        answers = []
        for item in items:
            values = request.POST.getlist(f"question_{item.pk}")
            value = values if item.question_type == Question.Type.MULTIPLE else (values[0] if values else "")
            if item.question_type in (Question.Type.SINGLE, Question.Type.MULTIPLE):
                allowed = {str(index) for index in range(len(item.options))}
                if any(choice not in allowed for choice in (value if isinstance(value, list) else [value]) if choice):
                    messages.error(request, "Ungültige Antwortoption. Bitte erneut versuchen.")
                    return render(request, "core/take_test.html", {"test": test, "questions": _public_questions(test)}, status=400)
            score, manual = grade_answer(item, {"value": value})
            answers.append(Submission(test=test, test_question=item, answer={"value": value}, score=score, needs_manual_grading=manual))
        with transaction.atomic():
            # Bedingtes Update als Compare-and-swap schützt vor parallelen OTP-Einlösungen.
            updated = TestSession.objects.filter(pk=test.pk, status=TestSession.Status.ISSUED).update(
                status=TestSession.Status.COMPLETED,
                completed_at=timezone.now(),
                examinee_name=request.session[name_session_key],
            )
            if updated != 1:
                return render(request, "core/test_unavailable.html", status=410)
            Submission.objects.bulk_create(answers)
        record_event(
            request, AuditLog.Category.SUBMISSION, "submission.completed", "Prüfling hat den Test abgegeben.",
            "test", test.pk, {"examinee_name": request.session[name_session_key], "answer_count": len(answers)},
        )
        request.session.pop(session_key, None)
        request.session.pop(name_session_key, None)
        return render(request, "core/test_complete.html")
    return render(request, "core/take_test.html", {"test": test, "questions": _public_questions(test)})


@login_required
def submissions(request):
    """Zeigt nur Tests, deren Fragenpool für den Mitarbeiter freigegeben ist."""
    allowed_pool_ids = accessible_pools(request.user, "submissions").values_list("pk", flat=True)
    if not is_administrator(request.user) and not accessible_pools(request.user, "submissions").exists():
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    completed_tests = TestSession.objects.filter(
        status=TestSession.Status.COMPLETED,
        question_pool_id__in=allowed_pool_ids,
    ).select_related("question_pool").order_by("-completed_at")
    summaries = []
    for test in completed_tests:
        # Getrennte Abfragen verhindern Summenvervielfachung durch mehrere Join-Beziehungen.
        possible = test.items.aggregate(total=Sum("points"))["total"] or Decimal("0")
        earned = test.submissions.filter(score__isnull=False).aggregate(total=Sum("score"))["total"] or Decimal("0")
        pending = test.submissions.filter(needs_manual_grading=True).count()
        summaries.append({"test": test, "possible": possible, "earned": earned, "pending": pending})
    return render(request, "core/submissions.html", {"summaries": summaries})


@require_capability("can_delete_tests")
@require_POST
def delete_test(request, test_id):
    """Löscht einen abgeschlossenen Test mitsamt Antworten und protokolliert den Vorgang."""
    test = get_object_or_404(TestSession, pk=test_id, status=TestSession.Status.COMPLETED)
    if not has_pool_access(request.user, test.question_pool, "submissions"):
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    with transaction.atomic():
        record_event(
            request, AuditLog.Category.SECURITY, "test.deleted", "Abgegebener Test und zugehörige Antworten gelöscht.",
            "test", test.pk, {"examinee_name": test.examinee_name},
        )
        test.delete()
    messages.success(request, "Testlauf und zugehörige Antworten wurden gelöscht. Der Vorgang ist protokolliert.")
    return redirect("submissions")


@login_required
def submission_detail(request, test_id):
    """Zeigt nach Klick auf einen Test alle Fragen und Antworten dieses Prüflings."""
    test = get_object_or_404(TestSession, pk=test_id, status=TestSession.Status.COMPLETED)
    if not has_pool_access(request.user, test.question_pool, "submissions"):
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    answer_query = Submission.objects.filter(test=test).select_related("test_question", "graded_by").order_by("test_question__position")
    answers = list(answer_query)
    for answer in answers:
        # Verbindet gespeicherte Optionsindizes mit den internen Lösungsschlüsseln für die Korrektursicht.
        if answer.test_question.question_type in (Question.Type.SINGLE, Question.Type.MULTIPLE):
            selected_values = answer.answer.get("value", [])
            if not isinstance(selected_values, list):
                selected_values = [selected_values]
            selected_indices = {str(value) for value in selected_values if value != ""}
            answer.choice_review = [
                {
                    "text": option.get("text", ""),
                    "selected": str(index) in selected_indices,
                    "correct": bool(option.get("is_correct")),
                }
                for index, option in enumerate(answer.test_question.options)
            ]
    possible = test.items.aggregate(total=Sum("points"))["total"] or Decimal("0")
    earned = answer_query.filter(score__isnull=False).aggregate(total=Sum("score"))["total"] or Decimal("0")
    pending = answer_query.filter(needs_manual_grading=True).count()
    return render(request, "core/submission_detail.html", {
        "test": test, "answers": answers, "possible": possible, "earned": earned, "pending": pending,
        "can_grade_submissions": has_pool_access(request.user, test.question_pool, "submissions"),
    })


@login_required
@require_POST
def grade_submission(request, pk):
    """Vergibt oder korrigiert Punkte; die Detailansicht berechnet Summen neu."""
    submission = get_object_or_404(Submission.objects.select_related("test"), pk=pk, test__status=TestSession.Status.COMPLETED)
    if not has_pool_access(request.user, submission.test.question_pool, "submissions"):
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    try:
        score = Decimal(request.POST.get("score", ""))
        if not score.is_finite() or score < 0 or score > submission.test_question.points:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        messages.error(request, "Bitte eine gültige Punktzahl innerhalb des Fragenmaximums angeben.")
        return redirect("submissions")
    submission.score = score
    submission.needs_manual_grading = False
    submission.graded_by = request.user
    submission.graded_at = timezone.now()
    submission.save(update_fields=["score", "needs_manual_grading", "graded_by", "graded_at"])
    record_event(
        request, AuditLog.Category.SUBMISSION, "submission.graded", "Antwortpunkte manuell gespeichert.",
        "submission", submission.pk,
        {"test_id": str(submission.test_id), "question_position": submission.test_question.position, "score": str(score)},
    )
    messages.success(request, "Freitextantwort wurde bewertet.")
    return redirect("submission_detail", test_id=submission.test_id)


@require_capability("can_manage_users")
def users_dashboard(request):
    """Listet Mitarbeiterkonten und deren Aktivierungsstatus."""
    users = User.objects.prefetch_related("groups", "user_permissions").order_by("username")
    return render(request, "core/users.html", {"users": users})


@require_capability("can_manage_users")
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def user_create(request):
    """Erstellt ein Mitarbeiterkonto mit mindestens initialem Passwort."""
    form = StaffUserForm(request.POST or None, current_user=request.user)
    if form.is_valid():
        if not form.cleaned_data.get("password"):
            form.add_error("password", "Für neue Benutzer ist ein Passwort erforderlich.")
        else:
            user = form.save()
            record_event(
                request, AuditLog.Category.STAFF, "staff.created", "Mitarbeiterkonto angelegt.",
                "user", user.pk, {
                    "username": user.username, "first_name": user.first_name, "last_name": user.last_name,
                    "is_administrator": user.is_superuser,
                    "groups": list(user.groups.values_list("name", flat=True)),
                    "direct_permissions": list(user.user_permissions.values_list("codename", flat=True)),
                },
            )
            messages.success(request, "Mitarbeiterkonto wurde angelegt.")
            return redirect("users_dashboard")
    return render(request, "core/user_form.html", {"form": form, "title": "Mitarbeiter erstellen"})


@require_capability("can_manage_users")
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def user_edit(request, pk):
    """Bearbeitet Kontodaten, Aktivierung, Gruppen und Einzelberechtigungen."""
    user = get_object_or_404(User, pk=pk)
    if is_administrator(user) and not is_administrator(request.user) and not has_access(request.user, "can_revoke_administrator"):
        return render(request, "core/403.html", {"capability": "Administrator bearbeiten"}, status=403)
    form = StaffUserForm(request.POST or None, instance=user, current_user=request.user)
    if form.is_valid():
        user = form.save()
        record_event(
            request, AuditLog.Category.STAFF, "staff.updated", "Mitarbeiterkonto und Berechtigungen aktualisiert.",
            "user", user.pk, {
                "username": user.username, "first_name": user.first_name, "last_name": user.last_name,
                "is_administrator": user.is_superuser,
                "is_active": user.is_active,
                "groups": list(user.groups.values_list("name", flat=True)),
                "direct_permissions": list(user.user_permissions.values_list("codename", flat=True)),
            },
        )
        messages.success(request, "Mitarbeiterkonto wurde aktualisiert.")
        return redirect("users_dashboard")
    return render(request, "core/user_form.html", {"form": form, "title": "Mitarbeiter bearbeiten"})


@require_capability("can_view_audit_logs")
def audit_logs(request):
    """Zeigt das zugriffsgeschützte Protokoll mit Kategorieauswahl und Seiten."""
    selected_category = request.GET.get("category", "")
    entries = AuditLog.objects.select_related("actor")
    if selected_category in AuditLog.Category.values:
        entries = entries.filter(category=selected_category)
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(request, "core/audit_logs.html", {
        "page": page,
        "categories": AuditLog.Category.choices,
        "selected_category": selected_category,
    })


@require_capability("can_view_audit_logs")
@require_capability("can_clear_audit_logs")
@require_POST
def clear_audit_logs(request):
    """Leert das Protokoll und hält die Löschung selbst im neuen Log fest."""
    deleted_count = AuditLog.objects.count()
    with transaction.atomic():
        AuditLog.objects.all().delete()
        record_event(
            request, AuditLog.Category.SECURITY, "audit_logs.cleared",
            "Systemprotokoll manuell geleert.", "audit_log", "",
            {"deleted_entries": deleted_count},
        )
    messages.success(request, f"Protokoll geleert; {deleted_count} Einträge wurden entfernt.")
    return redirect("audit_logs")
