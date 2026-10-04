"""HTTP-Endpunkte für RBAC-Verwaltung, Testausgabe und Korrektur."""
import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from mimetypes import guess_type
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from django.db.models import Count, Q, Sum, Value
from django.db.models import CharField
from django.db.models.functions import Cast, Coalesce
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from .forms import (
    ExamineeNameForm,
    GenerateTestForm,
    OtpForm,
    PermissionGroupForm,
    PrivacyAcceptanceForm,
    QuestionCsvImportForm,
    QuestionForm,
    QuestionPoolForm,
    StaffUserForm,
    ToolSettingsForm,
)
from .audit import record_event
from .models import AuditLog, Question, QuestionPool, StaffProfile, Submission, TestSession, ToolSettings
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


def _effective_academy_permissions(user):
    """Returns readable names of the Academy permissions inherited by a user."""
    codenames = {
        permission.split(".", 1)[1]
        for permission in user.get_all_permissions()
        if permission.startswith("core.")
    }
    return list(Permission.objects.filter(
        content_type__app_label="core", codename__in=codenames,
    ).order_by("name").values_list("name", flat=True))


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


def privacy_policy(request):
    """Zeigt Datenschutzerklärung und Impressum auch ohne Mitarbeiteranmeldung an."""
    return render(request, "core/privacy_policy.html", {"tool_settings": ToolSettings.current()})


def site_icon(request):
    """Liefert das konfigurierte, auf Bildformate begrenzte Favicon aus dem Media-Storage."""
    _ = request
    configuration = ToolSettings.objects.filter(pk=1).first()
    if not configuration or not configuration.site_icon:
        raise Http404("Kein Site-Icon konfiguriert.")
    content_type = guess_type(configuration.site_icon.name)[0] or "application/octet-stream"
    return FileResponse(
        configuration.site_icon.open("rb"),
        content_type=content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def privacy_accept(request):
    """Speichert die ausdrückliche Bestätigung der aktuell hinterlegten Erklärung."""
    tool_settings = ToolSettings.current()
    policy = tool_settings.privacy_policy.strip()
    form = PrivacyAcceptanceForm(request.POST or None)
    if request.method == "POST" and policy and form.is_valid():
        policy_hash = hashlib.sha256(policy.encode("utf-8")).hexdigest()
        StaffProfile.objects.update_or_create(
            user=request.user,
            defaults={
                "accepted_privacy_hash": policy_hash,
                "privacy_accepted_at": timezone.now(),
            },
        )
        record_event(
            request, AuditLog.Category.STAFF, "privacy_policy.accepted",
            "Mitarbeiter hat die aktuelle Datenschutzerklärung bestätigt.",
            "user", request.user.pk,
            {"policy_hash": policy_hash},
        )
        messages.success(request, "Datenschutzerklärung bestätigt.")
        return redirect("dashboard")
    return render(request, "core/privacy_accept.html", {
        "tool_settings": tool_settings,
        "form": form,
        "policy_configured": bool(policy),
    })


@require_capability("can_manage_tool_settings")
@require_http_methods(["GET", "POST"])
def tool_settings(request):
    """Bearbeitet zentrale Branding-, Prüfungs- und Rechtstext-Einstellungen."""
    configuration = ToolSettings.current()
    form = ToolSettingsForm(request.POST or None, request.FILES or None, instance=configuration)
    if form.is_valid():
        changed_fields = list(form.changed_data)
        form.save()
        record_event(
            request, AuditLog.Category.STAFF, "tool_settings.updated",
            "Zentrale Einstellungen des Testgenerators aktualisiert.",
            "tool_settings", configuration.pk,
            {"changed_fields": changed_fields},
        )
        messages.success(request, "Einstellungen wurden gespeichert.")
        return redirect("tool_settings")
    return render(request, "core/tool_settings.html", {"form": form})


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
    """Zeigt Academy-Rechtegruppen nach ihrer Sortierzahl."""
    groups = Group.objects.exclude(name=ADMINISTRATOR_GROUP).prefetch_related("permissions").annotate(
        permission_count=Count("permissions", distinct=True),
        member_count=Count("user", distinct=True),
        display_order=Coalesce("sort_config__sort_order", Value(0)),
    ).order_by("display_order", "name")
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
    effective_permission_names = _effective_academy_permissions(user)
    return render(request, "core/user_form.html", {
        "form": form, "title": f"Zugriffe: {user.username}",
        "effective_permission_names": effective_permission_names,
    })


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
    return render(request, "core/admin_dashboard.html", {
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
        "can_edit_selected_pool": has_pool_access(request.user, selected_pool, "edit"),
        "can_import_export_selected_pool": has_pool_access(request.user, selected_pool, "import_export"),
        "csv_import_form": QuestionCsvImportForm(),
    })


QUESTION_CSV_FIELDS = (
    "text", "question_type", "points", "answer_key", "is_pinned", "options_json",
)


@login_required
def question_export(request, pool_id):
    """Exportiert Fragen samt internen Antwortschlüsseln nur für Pool-Editoren."""
    question_pool = get_object_or_404(QuestionPool, pk=pool_id)
    if not has_pool_access(request.user, question_pool, "view") or not has_pool_access(
        request.user, question_pool, "import_export",
    ):
        return render(request, "core/403.html", {"capability": "can_import_export_pool"}, status=403)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="questions-pool-{question_pool.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(QUESTION_CSV_FIELDS)
    for question in Question.objects.filter(question_pool=question_pool).order_by("pk"):
        writer.writerow((
            question.text,
            question.question_type,
            question.points,
            question.answer_key,
            "true" if question.is_pinned else "false",
            json.dumps(question.options, ensure_ascii=False, separators=(",", ":")),
        ))
    return response


@login_required
@require_POST
def question_import(request, pool_id):
    """Importiert validierte Fragen ergänzend; vorhandene Fragen werden nie überschrieben."""
    question_pool = get_object_or_404(QuestionPool, pk=pool_id)
    if not has_pool_access(request.user, question_pool, "view") or not has_pool_access(
        request.user, question_pool, "import_export",
    ):
        return render(request, "core/403.html", {"capability": "can_import_export_pool"}, status=403)
    form = QuestionCsvImportForm(request.POST, request.FILES)
    errors = []
    imported_questions = []
    if form.is_valid():
        try:
            contents = form.cleaned_data["file"].read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(contents, newline=""))
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)) or set(headers) != set(QUESTION_CSV_FIELDS):
                errors.append("Die CSV-Kopfzeile muss genau diese Spalten enthalten: " + ", ".join(QUESTION_CSV_FIELDS))
            else:
                for row_number, row in enumerate(reader, start=2):
                    if row_number > 5001:
                        errors.append("Eine CSV-Datei darf höchstens 5.000 Fragen enthalten.")
                        break
                    if None in row:
                        errors.append(f"Zeile {row_number}: Die Zeile enthält mehr Spalten als die Kopfzeile.")
                        continue
                    if all(not (value or "").strip() for value in row.values()):
                        continue
                    try:
                        options = json.loads(row["options_json"])
                    except (json.JSONDecodeError, TypeError) as error:
                        errors.append(f"Zeile {row_number}: options_json ist kein gültiges JSON ({error}).")
                        continue
                    if not isinstance(options, list) or any(
                        not isinstance(option, dict)
                        or not isinstance(option.get("text"), str)
                        or not option["text"].strip()
                        or not isinstance(option.get("is_correct"), bool)
                        for option in options
                    ):
                        errors.append(f"Zeile {row_number}: options_json muss eine Liste aus Text- und Korrekt-Markierungen sein.")
                        continue
                    pinned_value = (row.get("is_pinned") or "").strip().casefold()
                    if pinned_value not in {"true", "false"}:
                        errors.append(f"Zeile {row_number}: is_pinned muss true oder false sein.")
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
                    question_form.fields["question_pool"].queryset = QuestionPool.objects.filter(pk=question_pool.pk)
                    if not question_form.is_valid():
                        details = "; ".join(
                            f"{field}: {', '.join(messages)}"
                            for field, messages in question_form.errors.items()
                        )
                        errors.append(f"Zeile {row_number}: {details}")
                        continue
                    if question_form.cleaned_data["question_type"] not in (
                        Question.Type.SINGLE, Question.Type.MULTIPLE,
                    ) and options:
                        errors.append(f"Zeile {row_number}: Nur Auswahlfragen dürfen Antwortoptionen enthalten.")
                        continue
                    imported_questions.append(question_form.save(commit=False))
        except UnicodeDecodeError:
            errors.append("Die CSV-Datei muss UTF-8-kodiert sein.")
        except csv.Error as error:
            errors.append(f"CSV-Lesefehler: {error}")
        if not errors and not imported_questions:
            errors.append("Die CSV-Datei enthält keine importierbaren Fragen.")
    if not form.is_valid():
        errors.extend(form.errors.get("file", []))
    if errors:
        messages.error(request, "Der Import wurde nicht gespeichert. Bitte korrigiere die gemeldeten Fehler.")
        pools = accessible_pools(request.user, "view")
        questions = Question.objects.filter(question_pool=question_pool)
        return render(request, "core/admin_dashboard.html", {
            "questions": questions,
            "pools": pools,
            "selected_pool": question_pool,
            "pinned_count": questions.filter(is_pinned=True).count(),
            "question_count": questions.count(),
            "question_types": Question.Type.choices,
            "question_search": "",
            "selected_question_type": "",
            "selected_pinned_filter": "",
            "can_edit_selected_pool": has_pool_access(request.user, question_pool, "edit"),
            "can_import_export_selected_pool": True,
            "csv_import_form": form,
            "csv_import_errors": errors,
        }, status=400)
    with transaction.atomic():
        Question.objects.bulk_create(imported_questions)
        record_event(
            request, AuditLog.Category.QUESTION, "question.csv.imported",
            "Fragen aus einer CSV-Datei in einen Fragenpool importiert.",
            "question_pool", question_pool.pk, {"count": len(imported_questions)},
        )
    messages.success(request, f"{len(imported_questions)} Fragen wurden ergänzt.")
    return redirect(f"{reverse('admin_dashboard')}?pool={question_pool.pk}")


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
    configuration = ToolSettings.current()
    form = GenerateTestForm(
        request.POST or None,
        question_pools=generatable_pools,
        minimum_questions=configuration.minimum_test_questions,
        maximum_questions=configuration.maximum_test_questions,
    )
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
            test.time_limit_minutes = form.cleaned_data["time_limit_minutes"]
            test.save(update_fields=["time_limit_minutes"])
            result = {"test": test, "otp": otp, "url": request.build_absolute_uri(f"/test/{test.pk}/")}
            record_event(
                request, AuditLog.Category.TEST, "test.generated", "Neuer Testlauf erstellt.",
                "test", test.pk, {
                    "question_count": test.items.count(),
                    "question_pool": test.question_pool.name,
                    "time_limit_minutes": test.time_limit_minutes,
                },
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
        "minimum_test_questions": configuration.minimum_test_questions,
        "maximum_test_questions": configuration.maximum_test_questions,
    })


def _public_questions(test):
    """Erstellt eine explizite Prüflingsprojektion ohne Punkte oder Lösungen."""
    return [{
        "id": item.pk, "position": item.position, "text": item.text,
        "question_type": item.question_type,
        "options": [{"index": index, "text": option["text"]} for index, option in enumerate(item.options)],
    } for item in test.items.all()]


def _finish_test(request, test, items, submitted_values, examinee_name, timed_out):
    """Speichert Antworten und verbraucht den Prüfungszugang atomar."""
    now = timezone.now()
    deadline = (
        test.started_at + timedelta(minutes=test.time_limit_minutes)
        if test.started_at and test.time_limit_minutes is not None else None
    )
    accept_timer_submission = (
        timed_out and request.method == "POST" and deadline is not None
        and now <= deadline + timedelta(seconds=3)
    )
    answers = []
    for item in items:
        if timed_out and not accept_timer_submission:
            value = [] if item.question_type == Question.Type.MULTIPLE else ""
        else:
            values = submitted_values.getlist(f"question_{item.pk}")
            value = values if item.question_type == Question.Type.MULTIPLE else (values[0] if values else "")
            if item.question_type in (Question.Type.SINGLE, Question.Type.MULTIPLE):
                allowed = {str(index) for index in range(len(item.options))}
                if any(choice not in allowed for choice in (value if isinstance(value, list) else [value]) if choice):
                    messages.error(request, "Ungültige Antwortoption. Bitte erneut versuchen.")
                    return False
        if timed_out and not accept_timer_submission:
            score, manual = Decimal("0"), False
        else:
            score, manual = grade_answer(item, {"value": value})
        answers.append(Submission(
            test=test, test_question=item, answer={"value": value},
            score=score, needs_manual_grading=manual,
        ))
    elapsed_seconds = max(0, int((now - test.started_at).total_seconds())) if test.started_at else None
    if test.time_limit_minutes is not None and elapsed_seconds is not None:
        elapsed_seconds = min(elapsed_seconds, test.time_limit_minutes * 60)
    with transaction.atomic():
        updated = TestSession.objects.filter(
            pk=test.pk, status=TestSession.Status.ISSUED,
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
    description = "Zeitlimit abgelaufen; Test automatisch abgegeben." if timed_out else "Prüfling hat den Test abgegeben."
    record_event(
        request, AuditLog.Category.SUBMISSION, action, description, "test", test.pk,
        {
            "examinee_name": examinee_name,
            "answer_count": len(answers),
            "elapsed_seconds": elapsed_seconds,
        },
    )
    request.session.pop(f"test_access_{test.pk}", None)
    request.session.pop(f"test_name_{test.pk}", None)
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
    if test.started_at is None:
        TestSession.objects.filter(
            pk=test.pk, status=TestSession.Status.ISSUED, started_at__isnull=True,
        ).update(started_at=timezone.now())
        test.refresh_from_db()
    deadline = (
        test.started_at + timedelta(minutes=test.time_limit_minutes)
        if test.started_at and test.time_limit_minutes is not None else None
    )
    timed_out = deadline is not None and timezone.now() >= deadline
    if request.method == "POST" or timed_out:
        if not _finish_test(
            request, test, items, request.POST, request.session[name_session_key], timed_out,
        ):
            if TestSession.objects.filter(pk=test.pk, status=TestSession.Status.COMPLETED).exists():
                return render(request, "core/test_unavailable.html", status=410)
            return render(request, "core/take_test.html", {
                "test": test, "questions": _public_questions(test),
                "remaining_seconds": max(1, math.ceil((deadline - timezone.now()).total_seconds()))
                if deadline else None,
                "remaining_milliseconds": max(0, int((deadline - timezone.now()).total_seconds() * 1000))
                if deadline else None,
            }, status=400)
        return render(request, "core/test_complete.html", {"test": test})
    return render(request, "core/take_test.html", {
        "test": test,
        "questions": _public_questions(test),
        "remaining_seconds": max(1, math.ceil((deadline - timezone.now()).total_seconds()))
        if deadline else None,
        "remaining_milliseconds": max(0, int((deadline - timezone.now()).total_seconds() * 1000))
        if deadline else None,
    })


@login_required
def submissions(request):
    """Zeigt freigegebene Testabgaben, optional gefiltert nach Prüfungstyp."""
    submission_pools = accessible_pools(request.user, "submissions").order_by("name")
    if not is_administrator(request.user) and not submission_pools.exists():
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    selected_pool_id = request.GET.get("pool", "")
    selected_pool = None
    if selected_pool_id:
        if not selected_pool_id.isdecimal():
            return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
        selected_pool = submission_pools.filter(pk=selected_pool_id).first()
        if selected_pool is None:
            return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    completed_tests = TestSession.objects.filter(
        status=TestSession.Status.COMPLETED,
        question_pool__in=submission_pools,
    ).select_related("question_pool").order_by("-completed_at")
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
            Q(examinee_name__icontains=search_query) | Q(pk_text__icontains=search_query)
        )
    if pending_only:
        completed_tests = completed_tests.filter(submissions__needs_manual_grading=True).distinct()
    if parsed_date_from:
        completed_tests = completed_tests.filter(completed_at__date__gte=parsed_date_from)
    if parsed_date_to:
        completed_tests = completed_tests.filter(completed_at__date__lte=parsed_date_to)
    test_page = Paginator(completed_tests, 50).get_page(request.GET.get("page"))
    summaries = []
    for test in test_page.object_list:
        # Getrennte Abfragen verhindern Summenvervielfachung durch mehrere Join-Beziehungen.
        possible = test.items.aggregate(total=Sum("points"))["total"] or Decimal("0")
        earned = test.submissions.filter(score__isnull=False).aggregate(total=Sum("score"))["total"] or Decimal("0")
        pending = test.submissions.filter(needs_manual_grading=True).count()
        summaries.append({"test": test, "possible": possible, "earned": earned, "pending": pending})
    return render(request, "core/submissions.html", {
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
    })


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
@require_http_methods(["GET", "POST"])
def submission_detail(request, test_id):
    """Zeigt eine Prüfung und speichert alle geänderten Punkte gemeinsam."""
    test = get_object_or_404(TestSession, pk=test_id, status=TestSession.Status.COMPLETED)
    if not has_pool_access(request.user, test.question_pool, "submissions"):
        return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
    answer_query = Submission.objects.filter(test=test).select_related("test_question", "graded_by").order_by("test_question__position")
    answers = list(answer_query)
    can_grade_submissions = has_pool_access(request.user, test.question_pool, "submissions")
    score_values = {}
    if request.method == "POST":
        if not can_grade_submissions:
            return render(request, "core/403.html", {"capability": "can_view_submissions_pool"}, status=403)
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
                if not score.is_finite() or score < 0 or score > answer.test_question.points:
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
                    answer.save(update_fields=["score", "needs_manual_grading", "graded_by", "graded_at"])
                    record_event(
                        request, AuditLog.Category.SUBMISSION, "submission.graded",
                        "Antwortpunkte in der gemeinsamen Prüfungskorrektur gespeichert.",
                        "submission", answer.pk,
                        {
                            "test_id": str(test.pk),
                            "question_position": answer.test_question.position,
                            "score": str(score),
                        },
                    )
            messages.success(request, "Punkte für den Test wurden gespeichert.")
            detail_url = reverse("submission_detail", args=[test.pk])
            filter_query = request.GET.urlencode()
            return redirect(f"{detail_url}?{filter_query}#score-save-top" if filter_query else f"{detail_url}#score-save-top")
        for answer in answers:
            answer.form_score_is_posted = answer.pk in score_values
            answer.form_score = score_values.get(answer.pk, answer.score)
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
    navigation_tests = TestSession.objects.filter(
        status=TestSession.Status.COMPLETED, question_pool=test.question_pool,
    ).order_by("-completed_at")
    navigation_search = request.GET.get("q", "").strip()[:120]
    navigation_pending = request.GET.get("pending") == "1"
    navigation_from = request.GET.get("from", "")
    navigation_to = request.GET.get("to", "")
    if navigation_search:
        navigation_tests = navigation_tests.annotate(pk_text=Cast("pk", CharField())).filter(
            Q(examinee_name__icontains=navigation_search)
            | Q(pk_text__icontains=navigation_search)
        )
    if navigation_pending:
        navigation_tests = navigation_tests.filter(submissions__needs_manual_grading=True).distinct()
    parsed_from = _parse_filter_date(navigation_from)
    parsed_to = _parse_filter_date(navigation_to)
    if navigation_from and parsed_from is None:
        messages.error(request, "Das Filterdatum „Von“ ist ungültig.")
    if navigation_to and parsed_to is None:
        messages.error(request, "Das Filterdatum „Bis“ ist ungültig.")
    if parsed_from:
        navigation_tests = navigation_tests.filter(completed_at__date__gte=parsed_from)
    if parsed_to:
        navigation_tests = navigation_tests.filter(completed_at__date__lte=parsed_to)
    navigation_ids = list(navigation_tests.values_list("pk", flat=True))
    current_index = navigation_ids.index(test.pk) if test.pk in navigation_ids else -1
    previous_test_id = navigation_ids[current_index - 1] if current_index > 0 else None
    next_test_id = (
        navigation_ids[current_index + 1]
        if 0 <= current_index < len(navigation_ids) - 1 else None
    )
    filter_query = request.GET.urlencode()
    return render(request, "core/submission_detail.html", {
        "test": test, "answers": answers, "possible": possible, "earned": earned, "pending": pending,
        "can_grade_submissions": can_grade_submissions,
        "score_values": score_values,
        "previous_test_id": previous_test_id,
        "next_test_id": next_test_id,
        "filter_query": filter_query,
        "navigation_pending": navigation_pending,
    })


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
    return render(request, "core/user_form.html", {
        "form": form,
        "title": "Mitarbeiter bearbeiten",
        "effective_permission_names": _effective_academy_permissions(user),
    })


@require_capability("can_view_audit_logs")
def audit_logs(request):
    """Zeigt das zugriffsgeschützte Protokoll mit Filtern und Seiten."""
    selected_category = request.GET.get("category", "")
    for date_field, label in (("from", "Von"), ("to", "Bis")):
        raw_date = request.GET.get(date_field, "")
        if raw_date and _parse_filter_date(raw_date) is None:
            messages.error(request, f"Das Filterdatum „{label}“ ist ungültig.")
    entries = _filtered_audit_logs(request)
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(request, "core/audit_logs.html", {
        "page": page,
        "categories": AuditLog.Category.choices,
        "selected_category": selected_category,
        "actor_query": request.GET.get("actor", "").strip()[:100],
        "action_query": request.GET.get("action", "").strip()[:100],
        "date_from": request.GET.get("from", ""),
        "date_to": request.GET.get("to", ""),
        "export_query": request.GET.urlencode(),
    })


def _filtered_audit_logs(request):
    """Applies supported audit filters consistently to the log and CSV export."""
    entries = AuditLog.objects.select_related("actor")
    selected_category = request.GET.get("category", "")
    actor_query = request.GET.get("actor", "").strip()[:100]
    action_query = request.GET.get("action", "").strip()[:100]
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    parsed_from = _parse_filter_date(date_from)
    parsed_to = _parse_filter_date(date_to)
    if selected_category in AuditLog.Category.values:
        entries = entries.filter(category=selected_category)
    if actor_query:
        entries = entries.filter(actor__username__icontains=actor_query)
    if action_query:
        entries = entries.filter(Q(action__icontains=action_query) | Q(description__icontains=action_query))
    if parsed_from:
        entries = entries.filter(created_at__date__gte=parsed_from)
    if parsed_to:
        entries = entries.filter(created_at__date__lte=parsed_to)
    return entries


@require_capability("can_view_audit_logs")
def audit_logs_export(request):
    """Exportiert ausschließlich die gefilterten Audit-Einträge als CSV."""
    if any(
        request.GET.get(field) and _parse_filter_date(request.GET[field]) is None
        for field in ("from", "to")
    ):
        return HttpResponseBadRequest("Ein übergebenes Filterdatum ist ungültig.")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="systemprotokoll.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(("Zeitpunkt", "Benutzer", "Kategorie", "Aktion", "Beschreibung", "Objekttyp", "Objekt-ID", "IP-Adresse", "Browserkennung"))
    for entry in _filtered_audit_logs(request).order_by("-created_at", "-pk").iterator():
        values = (
            timezone.localtime(entry.created_at).isoformat(),
            entry.actor.username if entry.actor else "",
            entry.get_category_display(),
            entry.action,
            entry.description,
            entry.object_type,
            entry.object_id,
            entry.ip_address or "",
            entry.user_agent,
        )
        writer.writerow(tuple(
            f"\t{value}"
            if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
            else value
            for value in values
        ))
    return response


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
