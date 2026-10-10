"""Testgenerierung, Prüflingsablauf, Abgaben und Korrektur."""

import math
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Count, Q, Sum, CharField
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from ..forms import ExamineeNameForm, GenerateTestForm, OtpForm
from ..audit import record_event
from ..models import (
    AuditLog,
    Question,
    QuestionPool,
    Submission,
    TestSession,
)
from ..permissions import accessible_pools, has_pool_access, is_administrator
from ..services import (
    TestGenerationError,
    evaluate_result,
    generate_test,
    grade_answer,
)
from .common import require_capability, _query_without_page, _parse_filter_date


@login_required
@require_http_methods(["GET", "POST"])
def generate_test_view(request):
    """Generiert Test, OTP und Direktlink ausschließlich aus einem Fragenpool."""
    generatable_pools = accessible_pools(request.user, "generate")
    if not generatable_pools.exists():
        return render(
            request,
            "core/403.html",
            {"capability": "can_generate_test_from_pool"},
            status=403,
        )
    requested_pool_id = (
        request.POST.get("question_pool") if request.method == "POST" else None
    )
    if (
        requested_pool_id
        and not generatable_pools.filter(pk=requested_pool_id).exists()
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "can_generate_test_from_pool"},
            status=403,
        )
    form = GenerateTestForm(
        request.POST or None,
        question_pools=generatable_pools,
    )
    result = None
    form_is_valid = form.is_valid()
    if form_is_valid:
        try:
            test, otp = generate_test(
                None,
                request.user,
                form.cleaned_data["question_pool"],
            )
        except TestGenerationError as error:
            form.add_error("question_pool", str(error))
        else:
            test.time_limit_minutes = form.cleaned_data["time_limit_minutes"]
            test.save(update_fields=["time_limit_minutes"])
            result = {
                "test": test,
                "otp": otp,
                "url": request.build_absolute_uri(f"/test/{test.pk}/"),
            }
            record_event(
                request,
                AuditLog.Category.TEST,
                "test.generated",
                "Neuer Testlauf erstellt.",
                "test",
                test.pk,
                {
                    "question_count": test.items.count(),
                    "question_pool": test.question_pool.name,
                    "time_limit_minutes": test.time_limit_minutes,
                },
            )
    selected_pool = (
        form.cleaned_data.get("question_pool")
        if form.is_bound
        else form.fields["question_pool"].initial
    )
    if not hasattr(selected_pool, "pk"):
        selected_pool = (
            QuestionPool.objects.filter(pk=selected_pool).first()
            if selected_pool
            else None
        )
    pool_choices = generatable_pools.annotate(
        question_count=Count("questions", distinct=True),
        pinned_count=Count(
            "questions", filter=Q(questions__is_pinned=True), distinct=True
        ),
    )
    selected_counts = next(
        (
            pool
            for pool in pool_choices
            if selected_pool and pool.pk == selected_pool.pk
        ),
        None,
    )
    return render(
        request,
        "core/generate_test.html",
        {
            "form": form,
            "result": result,
            "selected_pool": selected_pool,
            "pool_choices": pool_choices,
            "available_count": selected_counts.question_count if selected_counts else 0,
            "pinned_count": selected_counts.pinned_count if selected_counts else 0,
        },
    )


def _public_questions(test):
    """Erstellt eine explizite Prüflingsprojektion ohne Punkte oder Lösungen."""
    return [
        {
            "id": item.pk,
            "position": item.position,
            "text": item.text,
            "question_type": item.question_type,
            "options": [
                {"index": index, "text": option["text"]}
                for index, option in enumerate(item.options)
            ],
        }
        for item in test.items.all()
    ]


def _finish_test(request, test, items, submitted_values, examinee_name, timed_out):
    """Speichert Antworten und verbraucht den Prüfungszugang atomar."""
    now = timezone.now()
    deadline = (
        test.started_at + timedelta(minutes=test.time_limit_minutes)
        if test.started_at and test.time_limit_minutes is not None
        else None
    )
    accept_timer_submission = (
        timed_out
        and request.method == "POST"
        and deadline is not None
        and now <= deadline + timedelta(seconds=3)
    )
    answers = []
    for item in items:
        if timed_out and not accept_timer_submission:
            value = [] if item.question_type == Question.Type.MULTIPLE else ""
        else:
            values = submitted_values.getlist(f"question_{item.pk}")
            value = (
                values
                if item.question_type == Question.Type.MULTIPLE
                else (values[0] if values else "")
            )
            if item.question_type in (Question.Type.SINGLE, Question.Type.MULTIPLE):
                allowed = {str(index) for index in range(len(item.options))}
                if any(
                    choice not in allowed
                    for choice in (value if isinstance(value, list) else [value])
                    if choice
                ):
                    messages.error(
                        request, "Ungültige Antwortoption. Bitte erneut versuchen."
                    )
                    return False
        if timed_out and not accept_timer_submission:
            score, manual = Decimal("0"), False
        else:
            score, manual = grade_answer(item, {"value": value})
        answers.append(
            Submission(
                test=test,
                test_question=item,
                answer={"value": value},
                score=score,
                needs_manual_grading=manual,
            )
        )
    timing_start = test.otp_verified_at or test.started_at
    elapsed_seconds = (
        max(0, int((now - timing_start).total_seconds())) if timing_start else None
    )
    with transaction.atomic():
        updated = TestSession.objects.filter(
            pk=test.pk,
            status=TestSession.Status.ISSUED,
        ).update(
            status=TestSession.Status.COMPLETED,
            completed_at=now,
            examinee_name=examinee_name,
            elapsed_seconds=elapsed_seconds,
        )
        if updated != 1:
            return False
        Submission.objects.bulk_create(answers)
    action = "submission.timed_out" if timed_out else "submission.completed"
    description = (
        "Zeitlimit abgelaufen; Test automatisch abgegeben."
        if timed_out
        else "Prüfling hat den Test abgegeben."
    )
    record_event(
        request,
        AuditLog.Category.SUBMISSION,
        action,
        description,
        "test",
        test.pk,
        {
            "examinee_name": examinee_name,
            "answer_count": len(answers),
            "elapsed_seconds": elapsed_seconds,
        },
    )
    request.session.pop(f"test_access_{test.pk}", None)
    request.session.pop(f"test_name_{test.pk}", None)
    request.session.pop(f"test_confirmed_{test.pk}", None)
    return True


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
                TestSession.objects.filter(
                    pk=test.pk,
                    status=TestSession.Status.ISSUED,
                    otp_verified_at__isnull=True,
                ).update(otp_verified_at=timezone.now())
                record_event(
                    request,
                    AuditLog.Category.AUTH,
                    "test.otp.accepted",
                    "Einmalpasswort für Testzugang bestätigt.",
                    "test",
                    test.pk,
                )
                return redirect("take_test", test_id=test.pk)
            record_event(
                request,
                AuditLog.Category.SECURITY,
                "test.otp.rejected",
                "Ungültiger Versuch mit einem Test-Einmalpasswort.",
                "test",
                test.pk,
            )
            otp_form.add_error("otp", "Das Einmalpasswort ist ungültig.")
        return render(request, "core/otp.html", {"form": otp_form, "test": test})
    if not request.session.get(name_session_key):
        name_form = ExamineeNameForm(request.POST or None)
        if request.method == "POST" and name_form.is_valid():
            request.session[name_session_key] = name_form.cleaned_data["examinee_name"]
            return redirect("take_test", test_id=test.pk)
        return render(
            request, "core/examinee_name.html", {"form": name_form, "test": test}
        )
    info_text = test.question_pool.start_info_text.strip()
    confirmations = test.question_pool.start_confirmation_list
    if info_text:
        confirmations = [
            "Ich habe den obigen Text gelesen und verstanden."
        ] + confirmations
    confirm_session_key = f"test_confirmed_{test.pk}"
    if confirmations and not request.session.get(confirm_session_key):
        if request.method == "POST":
            posted = set(request.POST.getlist("confirm"))
            if posted == {str(index) for index in range(len(confirmations))}:
                request.session[confirm_session_key] = True
                return redirect("take_test", test_id=test.pk)
            missing = True
        else:
            missing = False
        return render(
            request,
            "core/test_confirmations.html",
            {
                "test": test,
                "info_text": info_text,
                "confirmations": list(enumerate(confirmations)),
                "missing": missing,
            },
        )
    items = list(test.items.all())
    if test.started_at is None:
        TestSession.objects.filter(
            pk=test.pk,
            status=TestSession.Status.ISSUED,
            started_at__isnull=True,
        ).update(started_at=timezone.now())
        test.refresh_from_db()
    deadline = (
        test.started_at + timedelta(minutes=test.time_limit_minutes)
        if test.started_at and test.time_limit_minutes is not None
        else None
    )
    timed_out = deadline is not None and timezone.now() >= deadline
    if request.method == "POST" or timed_out:
        if not _finish_test(
            request,
            test,
            items,
            request.POST,
            request.session[name_session_key],
            timed_out,
        ):
            if TestSession.objects.filter(
                pk=test.pk, status=TestSession.Status.COMPLETED
            ).exists():
                return render(request, "core/test_unavailable.html", status=410)
            return render(
                request,
                "core/take_test.html",
                {
                    "test": test,
                    "questions": _public_questions(test),
            "examinee_name": request.session.get(name_session_key, ""),
                    "remaining_seconds": (
                        max(1, math.ceil((deadline - timezone.now()).total_seconds()))
                        if deadline
                        else None
                    ),
                    "remaining_milliseconds": (
                        max(0, int((deadline - timezone.now()).total_seconds() * 1000))
                        if deadline
                        else None
                    ),
                },
                status=400,
            )
        return render(request, "core/test_complete.html", {"test": test})
    return render(
        request,
        "core/take_test.html",
        {
            "test": test,
            "questions": _public_questions(test),
            "examinee_name": request.session.get(name_session_key, ""),
            "remaining_seconds": (
                max(1, math.ceil((deadline - timezone.now()).total_seconds()))
                if deadline
                else None
            ),
            "remaining_milliseconds": (
                max(0, int((deadline - timezone.now()).total_seconds() * 1000))
                if deadline
                else None
            ),
        },
    )


@login_required
def submissions(request):
    """Zeigt freigegebene Testabgaben, optional gefiltert nach Prüfungstyp."""
    submission_pools = accessible_pools(request.user, "submissions").order_by("name")
    if not is_administrator(request.user) and not submission_pools.exists():
        return render(
            request,
            "core/403.html",
            {"capability": "can_view_submissions_pool"},
            status=403,
        )
    selected_pool_id = request.GET.get("pool", "")
    selected_pool = None
    if selected_pool_id:
        if not selected_pool_id.isdecimal():
            return render(
                request,
                "core/403.html",
                {"capability": "can_view_submissions_pool"},
                status=403,
            )
        selected_pool = submission_pools.filter(pk=selected_pool_id).first()
        if selected_pool is None:
            return render(
                request,
                "core/403.html",
                {"capability": "can_view_submissions_pool"},
                status=403,
            )
    completed_tests = (
        TestSession.objects.filter(
            status=TestSession.Status.COMPLETED,
            question_pool__in=submission_pools,
        )
        .select_related("question_pool")
        .order_by("-completed_at")
    )
    if selected_pool is not None:
        completed_tests = completed_tests.filter(question_pool=selected_pool)
    search_query = request.GET.get("q", "").strip()[:120]
    pending_only = request.GET.get("pending") == "1"
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    parsed_date_from = _parse_filter_date(date_from)
    parsed_date_to = _parse_filter_date(date_to)
    if date_from and parsed_date_from is None:
        messages.error(request, "Das Filterdatum „Von“ ist ungültig.")
    if date_to and parsed_date_to is None:
        messages.error(request, "Das Filterdatum „Bis“ ist ungültig.")
    if search_query:
        completed_tests = completed_tests.annotate(pk_text=Cast("pk", CharField()))
        completed_tests = completed_tests.filter(
            Q(examinee_name__icontains=search_query)
            | Q(pk_text__icontains=search_query)
        )
    if pending_only:
        completed_tests = completed_tests.filter(
            submissions__needs_manual_grading=True
        ).distinct()
    if parsed_date_from:
        completed_tests = completed_tests.filter(
            completed_at__date__gte=parsed_date_from
        )
    if parsed_date_to:
        completed_tests = completed_tests.filter(completed_at__date__lte=parsed_date_to)
    test_page = Paginator(completed_tests, 50).get_page(request.GET.get("page"))
    summaries = []
    for test in test_page.object_list:
        # Getrennte Abfragen verhindern Summenvervielfachung durch mehrere Join-Beziehungen.
        possible = test.items.aggregate(total=Sum("points"))["total"] or Decimal("0")
        earned = test.submissions.filter(score__isnull=False).aggregate(
            total=Sum("score")
        )["total"] or Decimal("0")
        pending = test.submissions.filter(needs_manual_grading=True).count()
        summaries.append(
            {
                "test": test,
                "possible": possible,
                "earned": earned,
                "pending": pending,
                **evaluate_result(test, earned, possible),
            }
        )
    return render(
        request,
        "core/submissions.html",
        {
            "summaries": summaries,
            "test_page": test_page,
            "result_count": test_page.paginator.count,
            "submission_pools": submission_pools,
            "selected_pool": selected_pool,
            "search_query": search_query,
            "pending_only": pending_only,
            "date_from": date_from,
            "date_to": date_to,
            "filter_query": request.GET.urlencode(),
            "pagination_query": _query_without_page(request.GET),
        },
    )


@require_capability("can_delete_tests")
@require_POST
def delete_test(request, test_id):
    """Löscht einen abgeschlossenen Test mitsamt Antworten und protokolliert den Vorgang."""
    test = get_object_or_404(
        TestSession, pk=test_id, status=TestSession.Status.COMPLETED
    )
    if not has_pool_access(request.user, test.question_pool, "submissions"):
        return render(
            request,
            "core/403.html",
            {"capability": "can_view_submissions_pool"},
            status=403,
        )
    with transaction.atomic():
        record_event(
            request,
            AuditLog.Category.SECURITY,
            "test.deleted",
            "Abgegebener Test und zugehörige Antworten gelöscht.",
            "test",
            test.pk,
            {"examinee_name": test.examinee_name},
        )
        test.delete()
    messages.success(
        request,
        "Testlauf und zugehörige Antworten wurden gelöscht. Der Vorgang ist protokolliert.",
    )
    return redirect("submissions")


@login_required
@require_http_methods(["GET", "POST"])
def submission_detail(request, test_id):
    """Zeigt eine Prüfung und speichert alle geänderten Punkte gemeinsam."""
    test = get_object_or_404(
        TestSession, pk=test_id, status=TestSession.Status.COMPLETED
    )
    if not has_pool_access(request.user, test.question_pool, "submissions"):
        return render(
            request,
            "core/403.html",
            {"capability": "can_view_submissions_pool"},
            status=403,
        )
    answer_query = (
        Submission.objects.filter(test=test)
        .select_related("test_question", "graded_by")
        .order_by("test_question__position")
    )
    answers = list(answer_query)
    can_grade_submissions = has_pool_access(
        request.user, test.question_pool, "submissions"
    )
    score_values = {}
    if request.method == "POST":
        if not can_grade_submissions:
            return render(
                request,
                "core/403.html",
                {"capability": "can_view_submissions_pool"},
                status=403,
            )
        updates = []
        score_values = {
            answer.pk: request.POST[f"score_{answer.pk}"]
            for answer in answers
            if f"score_{answer.pk}" in request.POST
        }
        for answer in answers:
            field_name = f"score_{answer.pk}"
            if field_name not in request.POST:
                continue
            raw_score = request.POST[field_name].strip()
            if not raw_score:
                continue
            try:
                score = Decimal(raw_score)
                if (
                    not score.is_finite()
                    or score < 0
                    or score > answer.test_question.points
                ):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                messages.error(
                    request,
                    f"Bitte für Frage {answer.test_question.position} eine gültige Punktzahl "
                    f"zwischen 0 und {answer.test_question.points} angeben. Es wurde nichts gespeichert.",
                )
                break
            if score != answer.score or answer.needs_manual_grading:
                updates.append((answer, score))
        else:
            with transaction.atomic():
                for answer, score in updates:
                    answer.score = score
                    answer.needs_manual_grading = False
                    answer.graded_by = request.user
                    answer.graded_at = timezone.now()
                    answer.save(
                        update_fields=[
                            "score",
                            "needs_manual_grading",
                            "graded_by",
                            "graded_at",
                        ]
                    )
                    record_event(
                        request,
                        AuditLog.Category.SUBMISSION,
                        "submission.graded",
                        "Antwortpunkte in der gemeinsamen Prüfungskorrektur gespeichert.",
                        "submission",
                        answer.pk,
                        {
                            "test_id": str(test.pk),
                            "question_position": answer.test_question.position,
                            "score": str(score),
                        },
                    )
            messages.success(request, "Punkte für den Test wurden gespeichert.")
            detail_url = reverse("submission_detail", args=[test.pk])
            filter_query = request.GET.urlencode()
            return redirect(
                f"{detail_url}?{filter_query}#score-save-top"
                if filter_query
                else f"{detail_url}#score-save-top"
            )
        for answer in answers:
            answer.form_score_is_posted = answer.pk in score_values
            answer.form_score = score_values.get(answer.pk, answer.score)
    for answer in answers:
        # Verbindet gespeicherte Optionsindizes mit den internen Lösungsschlüsseln für die Korrektursicht.
        if answer.test_question.question_type in (
            Question.Type.SINGLE,
            Question.Type.MULTIPLE,
        ):
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
    earned = answer_query.filter(score__isnull=False).aggregate(total=Sum("score"))[
        "total"
    ] or Decimal("0")
    pending = answer_query.filter(needs_manual_grading=True).count()
    navigation_pending = request.GET.get("pending") == "1"
    filter_query = request.GET.urlencode()
    return render(
        request,
        "core/submission_detail.html",
        {
            "test": test,
            "answers": answers,
            "possible": possible,
            "earned": earned,
            "pending": pending,
            "result": evaluate_result(test, earned, possible),
            "can_grade_submissions": can_grade_submissions,
            "score_values": score_values,
            "filter_query": filter_query,
            "navigation_pending": navigation_pending,
        },
    )
