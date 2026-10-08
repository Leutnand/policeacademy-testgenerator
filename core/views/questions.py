"""Fragenbank, CSV-Import/-Export sowie Verwaltung von Fragen und Prüfungstypen."""

import csv
import io
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from ..forms import QuestionCsvImportForm, QuestionForm, QuestionPoolForm
from ..audit import record_event
from ..models import AuditLog, Question, QuestionPool
from ..permissions import accessible_pools, has_pool_access
from .common import require_administrator


@login_required
def admin_dashboard(request):
    """Zeigt nur Fragenpools, für die View-Recht ausdrücklich erteilt wurde."""
    pools = accessible_pools(request.user, "view")
    requested_pool = request.GET.get("pool")
    if requested_pool:
        selected_pool = pools.filter(pk=requested_pool).first()
        if selected_pool is None:
            return render(
                request, "core/403.html", {"capability": "can_view_pool"}, status=403
            )
    else:
        selected_pool = pools.first()
    if selected_pool is None:
        return render(
            request, "core/403.html", {"capability": "can_view_pool"}, status=403
        )
    questions = (
        Question.objects.filter(question_pool=selected_pool)
        if selected_pool
        else Question.objects.none()
    )
    search_query = request.GET.get("q", "").strip()[:120]
    question_type = request.GET.get("type", "")
    pinned_filter = request.GET.get("pinned", "")
    if search_query:
        questions = questions.filter(text__icontains=search_query)
    if question_type in Question.Type.values:
        questions = questions.filter(question_type=question_type)
    if pinned_filter in {"yes", "no"}:
        questions = questions.filter(is_pinned=(pinned_filter == "yes"))
    questions = questions.order_by("-is_pinned", "-updated_at")
    question_count = questions.count()
    pinned_count = questions.filter(is_pinned=True).count()
    question_page = Paginator(questions, 50).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "core/admin_dashboard.html",
        {
            "questions": question_page.object_list,
            "question_page": question_page,
            "question_count": question_count,
            "question_pagination_query": query_params.urlencode(),
            "pools": pools,
            "selected_pool": selected_pool,
            "pinned_count": pinned_count,
            "question_search": search_query,
            "selected_question_type": question_type,
            "selected_pinned_filter": pinned_filter,
            "question_types": Question.Type.choices,
            "can_edit_selected_pool": has_pool_access(
                request.user, selected_pool, "edit"
            ),
            "can_delete_selected_pool": has_pool_access(
                request.user, selected_pool, "delete"
            ),
            "can_import_export_selected_pool": has_pool_access(
                request.user, selected_pool, "import_export"
            ),
            "csv_import_form": QuestionCsvImportForm(),
        },
    )


QUESTION_CSV_FIELDS = (
    "text",
    "question_type",
    "points",
    "answer_key",
    "is_pinned",
    "options_json",
)
QUESTION_CSV_DELIMITER = ";"


def _question_import_key(question):
    """Identifiziert gleiche Fragen samt Bewertungseinstellungen für den append-only Import."""
    options = tuple(
        (option.get("text", "").strip(), option.get("is_correct", False))
        for option in question.options
    )
    return (
        question.text.strip(),
        question.question_type,
        question.points,
        question.answer_key.strip(),
        question.is_pinned,
        options,
    )


@login_required
def question_export(request, pool_id):
    """Exportiert Fragen samt internen Antwortschlüsseln nur für Pool-Editoren."""
    question_pool = get_object_or_404(QuestionPool, pk=pool_id)
    if not has_pool_access(request.user, question_pool, "view") or not has_pool_access(
        request.user,
        question_pool,
        "import_export",
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "can_import_export_pool"},
            status=403,
        )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="questions-pool-{question_pool.pk}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(
        response, delimiter=QUESTION_CSV_DELIMITER, lineterminator="\r\n"
    )
    writer.writerow(QUESTION_CSV_FIELDS)
    for question in Question.objects.filter(question_pool=question_pool).order_by("pk"):
        writer.writerow(
            (
                question.text,
                question.question_type,
                question.points,
                question.answer_key,
                "true" if question.is_pinned else "false",
                json.dumps(question.options, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return response


@login_required
@require_POST
def question_import(request, pool_id):
    """Importiert validierte Fragen ergänzend; vorhandene Fragen werden nie überschrieben."""
    question_pool = get_object_or_404(QuestionPool, pk=pool_id)
    if not has_pool_access(request.user, question_pool, "view") or not has_pool_access(
        request.user,
        question_pool,
        "import_export",
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "can_import_export_pool"},
            status=403,
        )
    form = QuestionCsvImportForm(request.POST, request.FILES)
    errors = []
    imported_questions = []
    skipped_duplicates = 0
    valid_question_count = 0
    if form.is_valid():
        try:
            contents = form.cleaned_data["file"].read().decode("utf-8-sig")
            header_line = contents.splitlines()[0] if contents else ""
            delimiter = ","
            for candidate in (QUESTION_CSV_DELIMITER, ","):
                header = next(csv.reader([header_line], delimiter=candidate), [])
                if len(header) == len(QUESTION_CSV_FIELDS) and set(header) == set(
                    QUESTION_CSV_FIELDS
                ):
                    delimiter = candidate
                    break
            reader = csv.DictReader(
                io.StringIO(contents, newline=""), delimiter=delimiter
            )
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)) or set(headers) != set(
                QUESTION_CSV_FIELDS
            ):
                errors.append(
                    "Die CSV-Kopfzeile muss genau diese Spalten enthalten: "
                    + ", ".join(QUESTION_CSV_FIELDS)
                )
            else:
                existing_question_keys = {
                    _question_import_key(question)
                    for question in Question.objects.filter(
                        question_pool=question_pool
                    ).only(
                        "text",
                        "question_type",
                        "points",
                        "answer_key",
                        "is_pinned",
                        "options",
                    )
                }
                for row_number, row in enumerate(reader, start=2):
                    if row_number > 5001:
                        errors.append(
                            "Eine CSV-Datei darf höchstens 5.000 Fragen enthalten."
                        )
                        break
                    if None in row:
                        errors.append(
                            f"Zeile {row_number}: Die Zeile enthält mehr Spalten als die Kopfzeile."
                        )
                        continue
                    if all(not (value or "").strip() for value in row.values()):
                        continue
                    try:
                        options = json.loads(row["options_json"])
                    except (json.JSONDecodeError, TypeError) as error:
                        errors.append(
                            f"Zeile {row_number}: options_json ist kein gültiges JSON ({error})."
                        )
                        continue
                    if not isinstance(options, list) or any(
                        not isinstance(option, dict)
                        or not isinstance(option.get("text"), str)
                        or not option["text"].strip()
                        or not isinstance(option.get("is_correct"), bool)
                        for option in options
                    ):
                        errors.append(
                            f"Zeile {row_number}: options_json muss eine Liste aus Text- und Korrekt-Markierungen sein."
                        )
                        continue
                    pinned_value = (row.get("is_pinned") or "").strip().casefold()
                    if pinned_value not in {"true", "false"}:
                        errors.append(
                            f"Zeile {row_number}: is_pinned muss true oder false sein."
                        )
                        continue
                    data = {
                        "question_pool": str(question_pool.pk),
                        "text": row.get("text", ""),
                        "question_type": row.get("question_type", ""),
                        "points": row.get("points", ""),
                        "answer_key": row.get("answer_key", ""),
                        "is_pinned": "on" if pinned_value == "true" else "",
                        "option_count": str(max(len(options), 2)),
                    }
                    for index in range(max(len(options), 2)):
                        option = options[index] if index < len(options) else {}
                        data[f"option_text_{index}"] = option.get("text", "")
                        if option.get("is_correct"):
                            data[f"option_correct_{index}"] = "on"
                    question_form = QuestionForm(data)
                    question_form.fields["question_pool"].queryset = (
                        QuestionPool.objects.filter(pk=question_pool.pk)
                    )
                    if not question_form.is_valid():
                        details = "; ".join(
                            f"{field}: {', '.join(messages)}"
                            for field, messages in question_form.errors.items()
                        )
                        errors.append(f"Zeile {row_number}: {details}")
                        continue
                    if (
                        question_form.cleaned_data["question_type"]
                        not in (
                            Question.Type.SINGLE,
                            Question.Type.MULTIPLE,
                        )
                        and options
                    ):
                        errors.append(
                            f"Zeile {row_number}: Nur Auswahlfragen dürfen Antwortoptionen enthalten."
                        )
                        continue
                    question = question_form.save(commit=False)
                    valid_question_count += 1
                    question_key = _question_import_key(question)
                    if question_key in existing_question_keys:
                        skipped_duplicates += 1
                        continue
                    existing_question_keys.add(question_key)
                    imported_questions.append(question)
        except UnicodeDecodeError:
            errors.append("Die CSV-Datei muss UTF-8-kodiert sein.")
        except csv.Error as error:
            errors.append(f"CSV-Lesefehler: {error}")
        if not errors and not valid_question_count:
            errors.append("Die CSV-Datei enthält keine importierbaren Fragen.")
    if not form.is_valid():
        errors.extend(form.errors.get("file", []))
    if errors:
        messages.error(
            request,
            "Der Import wurde nicht gespeichert. Bitte korrigiere die gemeldeten Fehler.",
        )
        pools = accessible_pools(request.user, "view")
        questions = Question.objects.filter(question_pool=question_pool)
        return render(
            request,
            "core/admin_dashboard.html",
            {
                "questions": questions,
                "pools": pools,
                "selected_pool": question_pool,
                "pinned_count": questions.filter(is_pinned=True).count(),
                "question_count": questions.count(),
                "question_types": Question.Type.choices,
                "question_search": "",
                "selected_question_type": "",
                "selected_pinned_filter": "",
                "can_edit_selected_pool": has_pool_access(
                    request.user, question_pool, "edit"
                ),
                "can_delete_selected_pool": has_pool_access(
                    request.user, question_pool, "delete"
                ),
                "can_import_export_selected_pool": True,
                "csv_import_form": form,
                "csv_import_errors": errors,
            },
            status=400,
        )
    with transaction.atomic():
        if imported_questions:
            Question.objects.bulk_create(imported_questions)
        record_event(
            request,
            AuditLog.Category.QUESTION,
            "question.csv.imported",
            "CSV-Fragenimport abgeschlossen.",
            "question_pool",
            question_pool.pk,
            {
                "count": len(imported_questions),
                "skipped_duplicates": skipped_duplicates,
            },
        )
    if imported_questions:
        summary = f"{len(imported_questions)} Fragen wurden ergänzt."
    else:
        summary = "Es wurden keine neuen Fragen ergänzt."
    if skipped_duplicates:
        duplicate_label = (
            "identisches Duplikat"
            if skipped_duplicates == 1
            else "identische Duplikate"
        )
        verb = "wurde" if skipped_duplicates == 1 else "wurden"
        summary += f" {skipped_duplicates} {duplicate_label} {verb} übersprungen."
    messages.success(request, summary)
    return redirect(f"{reverse('admin_dashboard')}?pool={question_pool.pk}")


@require_administrator
@require_http_methods(["GET", "POST"])
def pools_dashboard(request):
    """Listet Prüfungstypen und legt neue, voneinander getrennte Fragenpools an."""
    form = QuestionPoolForm(request.POST or None)
    if form.is_valid():
        question_pool = form.save()
        record_event(
            request,
            AuditLog.Category.QUESTION,
            "question_pool.created",
            "Neuer Fragenpool angelegt.",
            "question_pool",
            question_pool.pk,
            {"name": question_pool.name},
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
            request,
            AuditLog.Category.QUESTION,
            "question_pool.updated",
            "Fragenpool bearbeitet.",
            "question_pool",
            question_pool.pk,
            {"name": question_pool.name},
        )
        messages.success(request, "Fragenpool wurde aktualisiert.")
        return redirect("pools_dashboard")
    return render(
        request, "core/pool_form.html", {"form": form, "title": "Fragenpool bearbeiten"}
    )


@require_administrator
@require_POST
def pool_delete(request, pk):
    """Löscht ausschließlich leere Pools und bewahrt Pools verwendeter Tests."""
    question_pool = get_object_or_404(QuestionPool, pk=pk)
    if QuestionPool.objects.count() <= 1:
        messages.error(request, "Der letzte Fragenpool kann nicht gelöscht werden.")
        return redirect("pools_dashboard")
    if question_pool.questions.exists() or question_pool.test_sessions.exists():
        messages.error(
            request,
            "Dieser Fragenpool enthält Fragen oder Testläufe und kann nicht gelöscht werden.",
        )
        return redirect("pools_dashboard")
    record_event(
        request,
        AuditLog.Category.QUESTION,
        "question_pool.deleted",
        "Leerer Fragenpool gelöscht.",
        "question_pool",
        question_pool.pk,
        {"name": question_pool.name},
    )
    question_pool.delete()
    messages.success(request, "Leerer Fragenpool wurde gelöscht.")
    return redirect("pools_dashboard")


@login_required
@require_http_methods(["GET", "POST"])
def question_create(request):
    """Legt eine Frage im ausgewählten Prüfungspool an."""
    visible_pool_ids = accessible_pools(request.user, "view").values_list(
        "pk", flat=True
    )
    editable_pools = accessible_pools(request.user, "edit").filter(
        pk__in=visible_pool_ids
    )
    if not editable_pools.exists():
        return render(
            request, "core/403.html", {"capability": "can_edit_pool"}, status=403
        )
    requested_pool_id = request.GET.get("pool") or request.POST.get("question_pool")
    if requested_pool_id and not editable_pools.filter(pk=requested_pool_id).exists():
        return render(
            request, "core/403.html", {"capability": "can_edit_pool"}, status=403
        )
    selected_pool_id = (
        request.GET.get("pool") or editable_pools.values_list("pk", flat=True).first()
    )
    initial = {"question_pool": selected_pool_id} if selected_pool_id else None
    form = QuestionForm(request.POST or None, initial=initial)
    form.fields["question_pool"].queryset = editable_pools
    if form.is_valid():
        question = form.save()
        record_event(
            request,
            AuditLog.Category.QUESTION,
            "question.created",
            "Prüfungsfrage angelegt.",
            "question",
            question.pk,
            {
                "text": question.text,
                "question_type": question.question_type,
                "options": question.options,
                "answer_key": question.answer_key,
                "points": str(question.points),
                "is_pinned": question.is_pinned,
                "question_pool": question.question_pool.name,
            },
        )
        messages.success(request, "Frage wurde angelegt.")
        return redirect(
            f"{reverse('admin_dashboard')}?pool={question.question_pool_id}"
        )
    return render(
        request,
        "core/question_form.html",
        {"form": form, "title": "Frage erstellen", "option_rows": form.option_rows},
    )


@login_required
@require_http_methods(["GET", "POST"])
def question_edit(request, pk):
    """Bearbeitet eine Frage nach serverseitiger Rechteprüfung."""
    question = get_object_or_404(Question, pk=pk)
    if not has_pool_access(
        request.user, question.question_pool, "view"
    ) or not has_pool_access(request.user, question.question_pool, "edit"):
        return render(
            request, "core/403.html", {"capability": "can_edit_pool"}, status=403
        )
    visible_pool_ids = accessible_pools(request.user, "view").values_list(
        "pk", flat=True
    )
    editable_pools = accessible_pools(request.user, "edit").filter(
        pk__in=visible_pool_ids
    )
    if request.method == "POST":
        target_pool_id = request.POST.get("question_pool")
        if target_pool_id and not editable_pools.filter(pk=target_pool_id).exists():
            return render(
                request, "core/403.html", {"capability": "can_edit_pool"}, status=403
            )
    form = QuestionForm(request.POST or None, instance=question)
    form.fields["question_pool"].queryset = editable_pools
    if form.is_valid():
        question = form.save()
        record_event(
            request,
            AuditLog.Category.QUESTION,
            "question.updated",
            "Prüfungsfrage bearbeitet.",
            "question",
            question.pk,
            {
                "text": question.text,
                "question_type": question.question_type,
                "options": question.options,
                "answer_key": question.answer_key,
                "points": str(question.points),
                "is_pinned": question.is_pinned,
                "question_pool": question.question_pool.name,
            },
        )
        messages.success(request, "Frage wurde gespeichert.")
        return redirect(
            f"{reverse('admin_dashboard')}?pool={question.question_pool_id}"
        )
    return render(
        request,
        "core/question_form.html",
        {"form": form, "title": "Frage bearbeiten", "option_rows": form.option_rows},
    )


@login_required
@require_POST
def question_delete(request, pk):
    """Löscht eine Frage ausschließlich über eine CSRF-geschützte POST-Aktion."""
    question = get_object_or_404(Question, pk=pk)
    if not has_pool_access(
        request.user, question.question_pool, "view"
    ) or not has_pool_access(request.user, question.question_pool, "delete"):
        return render(
            request,
            "core/403.html",
            {"capability": "can_delete_questions_pool"},
            status=403,
        )
    question_pool_id = question.question_pool_id
    record_event(
        request,
        AuditLog.Category.QUESTION,
        "question.deleted",
        "Prüfungsfrage gelöscht.",
        "question",
        question.pk,
        {
            "text": question.text,
            "question_type": question.question_type,
            "options": question.options,
            "answer_key": question.answer_key,
        },
    )
    question.delete()
    messages.success(request, "Frage wurde gelöscht.")
    return redirect(f"{reverse('admin_dashboard')}?pool={question_pool_id}")


@login_required
@require_POST
def question_bulk_delete(request, pool_pk):
    """Löscht mehrere ausgewählte Fragen eines Pools per POST."""
    question_pool = get_object_or_404(QuestionPool, pk=pool_pk)
    if not has_pool_access(request.user, question_pool, "view") or not has_pool_access(
        request.user, question_pool, "delete"
    ):
        return render(
            request,
            "core/403.html",
            {"capability": "can_delete_questions_pool"},
            status=403,
        )
    ids = [i for i in request.POST.getlist("question_ids") if i.isdigit()]
    questions = list(Question.objects.filter(question_pool=question_pool, pk__in=ids))
    redirect_url = f"{reverse('admin_dashboard')}?pool={question_pool.pk}"
    if not questions:
        messages.error(request, "Es wurden keine Fragen ausgewählt.")
        return redirect(redirect_url)
    with transaction.atomic():
        for question in questions:
            record_event(
                request,
                AuditLog.Category.QUESTION,
                "question.deleted",
                "Prüfungsfrage gelöscht.",
                "question",
                question.pk,
                {
                    "text": question.text,
                    "question_type": question.question_type,
                    "options": question.options,
                    "answer_key": question.answer_key,
                },
            )
            question.delete()
    messages.success(request, f"{len(questions)} Fragen wurden gelöscht.")
    return redirect(redirect_url)
