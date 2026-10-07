"""Formulare mit serverseitiger Validierung für Fragen, Benutzer und Prüfungen."""

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.auth.models import Group, Permission, User
from django.db.models import Max, Q
from .models import PermissionGroupSortOrder, Question, QuestionPool, ToolSettings
from .permissions import (
    ADMINISTRATOR_GROUP,
    DELEGATION_CONTROL_CODES,
    GLOBAL_PERMISSION_CODES,
    POOL_PERMISSION_PREFIXES,
    has_access,
    is_administrator,
)


class QuestionForm(forms.ModelForm):
    """Pflegt Fragen mit strukturierten, verständlichen Auswahloptionen."""

    option_count = forms.IntegerField(
        min_value=0, max_value=20, initial=2, widget=forms.HiddenInput
    )

    class Meta:
        """Ordnet nur die für alle Fragetypen gemeinsamen Felder zu."""

        model = Question
        fields = (
            "question_pool",
            "text",
            "question_type",
            "points",
            "answer_key",
            "is_pinned",
        )

    def __init__(self, *args, **kwargs):
        """Erzeugt einzelne Text- und Korrekt-Felder passend zum Fragenbestand."""
        super().__init__(*args, **kwargs)
        self.fields["question_pool"].queryset = QuestionPool.objects.order_by("name")
        self.fields["question_pool"].label = "Fragenpool / Prüfungstyp"
        self.fields["question_pool"].empty_label = "Pool auswählen"
        try:
            posted_count = (
                int(self.data.get(self.add_prefix("option_count"), 0))
                if self.is_bound
                else 0
            )
        except (TypeError, ValueError):
            posted_count = 0
        self.option_count = min(
            max(posted_count, len(self.instance.options or []), 2), 20
        )
        self.fields["option_count"].initial = self.option_count
        current_type = (
            self.data.get(self.add_prefix("question_type"))
            if self.is_bound
            else self.instance.question_type
        )
        self.fields["question_type"].label = "Fragetyp"
        self.fields["text"].label = "Frage"
        self.fields["points"].label = "Punkte"
        self.fields["is_pinned"].label = "Verankerte Frage"
        self.fields["answer_key"].label = "Musterlösung / erwartete Antwort"
        self.fields["answer_key"].help_text = (
            "Wird bei Kurzantworten zum automatischen Vergleich verwendet."
            if current_type == Question.Type.SHORT
            else "Interne Notiz für die Korrektur; wird Prüflingen niemals angezeigt."
        )
        existing_options = self.instance.options or []
        self.option_rows = []
        for index in range(self.option_count):
            option = existing_options[index] if index < len(existing_options) else {}
            text_name = f"option_text_{index}"
            correct_name = f"option_correct_{index}"
            self.fields[text_name] = forms.CharField(
                label=f"Antwort {index + 1}",
                required=False,
                initial=option.get("text", ""),
                widget=forms.TextInput(
                    attrs={
                        "placeholder": f"Antwortmöglichkeit {index + 1}",
                        "data-option-text": "",
                    }
                ),
            )
            self.fields[correct_name] = forms.BooleanField(
                label="Korrekt",
                required=False,
                initial=option.get("is_correct", False),
                widget=forms.CheckboxInput(attrs={"data-option-correct": ""}),
            )
            self.option_rows.append(
                {"text": self[text_name], "correct": self[correct_name]}
            )

    def clean(self):
        """Prüft Auswahlfelder und erstellt daraus das interne Optionsformat."""
        cleaned = super().clean()
        kind = cleaned.get("question_type")
        options = []
        if kind in (Question.Type.SINGLE, Question.Type.MULTIPLE):
            for index in range(self.option_count):
                text = cleaned.get(f"option_text_{index}", "").strip()
                correct = cleaned.get(f"option_correct_{index}", False)
                if text:
                    options.append({"text": text, "is_correct": correct})
                elif correct:
                    self.add_error(
                        f"option_text_{index}",
                        "Bitte den Antworttext ergänzen oder die Markierung entfernen.",
                    )
            if len(options) < 2:
                self.add_error(
                    "option_count",
                    "Auswahlfragen benötigen mindestens zwei Antwortmöglichkeiten.",
                )
            if (
                kind == Question.Type.SINGLE
                and sum(option["is_correct"] for option in options) != 1
            ):
                self.add_error(
                    "option_count",
                    "Bei Single Choice muss genau eine Antwort als korrekt markiert sein.",
                )
            if kind == Question.Type.MULTIPLE and not any(
                option["is_correct"] for option in options
            ):
                self.add_error(
                    "option_count", "Markiere mindestens eine korrekte Antwort."
                )
        cleaned["options"] = options
        return cleaned

    def save(self, commit=True):
        """Überträgt validierte JSON-Optionen vor dem Speichern ins Modell."""
        question = super().save(commit=False)
        question.options = self.cleaned_data.get("options", [])
        if commit:
            question.save()
        return question


def add_permission_checkboxes(form, selected_ids=()):
    """Bietet ausschließlich tatsächlich verwendete Academy-Rechte zur Auswahl an."""
    academy_permissions = Q(
        content_type__app_label="core",
        content_type__model="questionpool",
        codename__in=[
            code.rsplit(".", 1)[-1] for code in GLOBAL_PERMISSION_CODES.values()
        ],
    )
    for prefix in POOL_PERMISSION_PREFIXES.values():
        academy_permissions |= Q(
            content_type__app_label="core",
            content_type__model="questionpool",
            codename__startswith=prefix,
        )
    permissions = list(
        Permission.objects.filter(academy_permissions)
        .select_related(
            "content_type",
        )
        .order_by("name")
    )
    pools = {str(pool.pk): pool for pool in QuestionPool.objects.all()}
    global_codes = {
        code.rsplit(".", 1)[-1]: index
        for index, code in enumerate(GLOBAL_PERMISSION_CODES.values())
    }
    pool_action_order = {
        action: index for index, action in enumerate(POOL_PERMISSION_PREFIXES)
    }
    global_help = {
        "can_manage_users": "Öffnet die Mitarbeiterverwaltung. Rechteänderungen brauchen zusätzlich das passende Recht zum Vergeben oder Entziehen.",
        "can_delete_users": "Löscht Mitarbeiterkonten. Das eigene Konto und andere Administratoren sind geschützt.",
        "can_manage_tool_settings": "Erlaubt Branding, Logintexte, Testgrenzen und Datenschutztexte in den Tool-Einstellungen zu ändern.",
        "can_delete_tests": "Löscht abgeschlossene Tests. Zusätzlich ist Auswertungszugriff auf den zugehörigen Pool erforderlich.",
        "can_view_audit_logs": "Zeigt Zugriffe und Änderungen im Systemprotokoll an.",
        "can_clear_audit_logs": "Leert alle bisherigen Logeinträge. Der Löschvorgang wird selbst protokolliert; zusätzlich ist Leserecht nötig.",
        "can_grant_user_permissions": "Vergibt Gruppenmitgliedschaften und direkte Rechte. Erfordert Mitarbeiterverwaltung und erlaubt kein Entziehen.",
        "can_revoke_user_permissions": "Entzieht Gruppenmitgliedschaften und direkte Rechte. Erfordert Mitarbeiterverwaltung und erlaubt kein Vergeben.",
        "can_grant_administrator": "Vergibt einer anderen Person vollständigen Administratorzugriff. Erfordert Mitarbeiterverwaltung.",
        "can_revoke_administrator": "Entzieht einer anderen Person den Administratorzugriff. Der eigene Status bleibt geschützt.",
    }
    pool_help = {
        "view": "Erlaubt, Fragen dieses Pools in der Academy-Fragenbank anzusehen.",
        "edit": "Erlaubt Fragen dieses Pools anzulegen, zu bearbeiten und zu löschen. Zusätzlich ist das Ansichtsrecht nötig.",
        "import_export": "Erlaubt den CSV-Import und -Export dieses Pools. Der Export enthält interne Lösungsschlüssel.",
        "generate": "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.",
        "submissions": "Erlaubt Abgaben dieses Pools anzusehen und zu bewerten.",
    }
    sections = {}
    for permission in permissions:
        pool_id = None
        for prefix in POOL_PERMISSION_PREFIXES.values():
            if permission.codename.startswith(prefix):
                pool_id = permission.codename[len(prefix) :]
                break
        if pool_id and pool_id not in pools:
            continue
        if pool_id and pool_id in pools:
            section_key = (1, pools[pool_id].name.casefold())
            section_title = f"Pool · {pools[pool_id].name}"
            field_order = next(
                pool_action_order[action]
                for action, prefix in POOL_PERMISSION_PREFIXES.items()
                if permission.codename.startswith(prefix)
            )
        else:
            section_key = (0, "")
            section_title = "Globale Academy-Rechte"
            field_order = global_codes[permission.codename]
        if pool_id and pool_id in pools:
            pool_action = next(
                action_name
                for action_name, prefix in POOL_PERMISSION_PREFIXES.items()
                if permission.codename.startswith(prefix)
            )
            permission_help = pool_help[pool_action]
        elif permission.codename in global_help:
            permission_help = global_help[permission.codename]
        else:
            permission_help = global_help[permission.codename]
        field_name = f"permission_{permission.pk}"
        form.fields[field_name] = forms.BooleanField(
            label=permission.name,
            required=False,
            initial=permission.pk in selected_ids,
        )
        sections.setdefault(
            section_key,
            {
                "title": section_title,
                "order": section_key,
                "fields": [],
            },
        )["fields"].append(
            {
                "name": field_name,
                "permission": permission,
                "permission_label": permission.name,
                "permission_help": permission_help,
                "sort_order": field_order,
                "bound_field": form[field_name],
            }
        )
    form.permission_sections = sorted(
        sections.values(), key=lambda section: section["order"]
    )
    for section in form.permission_sections:
        section["fields"].sort(
            key=lambda item: (item["sort_order"], item["permission_label"].casefold())
        )
    form.permission_ids = {
        int(name.removeprefix("permission_")): name
        for name in form.fields
        if name.startswith("permission_")
    }


def selected_permission_ids(form):
    """Liest IDs aller angehakten dynamischen Permissionfelder aus dem Formular."""
    return [
        permission_id
        for permission_id, field_name in form.permission_ids.items()
        if form.cleaned_data.get(field_name)
    ]


class StaffUserForm(forms.ModelForm):
    """Verwaltet Mitarbeiter, Administratorstatus, Gruppen und beliebige Direktrechte."""

    password = forms.CharField(
        label="Neues Passwort",
        required=False,
        widget=forms.PasswordInput,
        help_text="Bei Bearbeitung leer lassen, damit es unverändert bleibt.",
    )
    is_administrator = forms.BooleanField(
        label="Administrator (alle Rechte)",
        required=False,
        help_text="Administratoren erhalten automatisch sämtliche Rechte der Academy-Anwendung.",
    )
    groups = forms.ModelMultipleChoiceField(
        label="Rechtegruppen",
        queryset=Group.objects.exclude(name=ADMINISTRATOR_GROUP),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        """Beschränkt die Verwaltung auf Mitarbeiterstammdaten und Gruppen."""

        model = User
        fields = ("username", "first_name", "last_name", "is_active", "groups")

    def __init__(self, *args, **kwargs):
        """Initialisiert Adminstatus und verhindert versehentliches Aussperren."""
        self.current_user = kwargs.pop("current_user", None)
        self.can_grant_user_permissions = is_administrator(
            self.current_user
        ) or has_access(
            self.current_user,
            "can_grant_user_permissions",
        )
        self.can_revoke_user_permissions = is_administrator(
            self.current_user
        ) or has_access(
            self.current_user,
            "can_revoke_user_permissions",
        )
        self.can_manage_roles = (
            self.can_grant_user_permissions or self.can_revoke_user_permissions
        )
        self.can_grant_administrator = is_administrator(
            self.current_user
        ) or has_access(
            self.current_user,
            "can_grant_administrator",
        )
        self.can_revoke_administrator = is_administrator(
            self.current_user
        ) or has_access(
            self.current_user,
            "can_revoke_administrator",
        )
        self.can_manage_administrator = (
            self.can_grant_administrator or self.can_revoke_administrator
        )
        super().__init__(*args, **kwargs)
        self.fields["is_administrator"].initial = is_administrator(self.instance)
        self.fields["is_administrator"].disabled = not self.can_manage_administrator
        self.fields["username"].label = "Benutzername"
        self.fields["first_name"].label = "Vorname"
        self.fields["last_name"].label = "Nachname"
        self.fields["is_active"].label = "Konto aktiv"
        if self.can_manage_roles:
            selected_ids = (
                set(self.instance.user_permissions.values_list("pk", flat=True))
                if self.instance.pk
                else set()
            )
            add_permission_checkboxes(self, selected_ids)
            self.protected_permission_ids = set()
            self.protected_group_ids = set()
            if not is_administrator(self.current_user):
                protected_permissions = Permission.objects.filter(
                    content_type__app_label="core",
                    codename__in=DELEGATION_CONTROL_CODES,
                )
                self.protected_permission_ids = set(
                    protected_permissions.values_list("pk", flat=True)
                )
                for permission_id in self.protected_permission_ids:
                    field = self.fields.get(f"permission_{permission_id}")
                    if field:
                        field.disabled = True
                self.protected_group_ids = set(
                    Group.objects.filter(
                        permissions__in=protected_permissions,
                    ).values_list("pk", flat=True)
                )
                self.fields["groups"].queryset = self.fields["groups"].queryset.exclude(
                    pk__in=self.protected_group_ids,
                )
        else:
            self.fields["groups"].queryset = (
                self.instance.groups.all() if self.instance.pk else Group.objects.none()
            )
            self.fields["groups"].disabled = True
            self.protected_permission_ids = set()
            self.protected_group_ids = set()
            self.permission_sections = []
            self.permission_ids = {}
        self.order_fields(
            [
                "username",
                "first_name",
                "last_name",
                "is_administrator",
                "is_active",
                "groups",
                *self.permission_ids.values(),
                "password",
            ]
        )

    def clean(self):
        """Verhindert, dass ein Administrator sein eigenes Konto deaktiviert."""
        cleaned = super().clean()
        existing_administrator = is_administrator(self.instance)
        requested_administrator = bool(
            cleaned.get("is_administrator", existing_administrator)
        )
        if (
            requested_administrator
            and not existing_administrator
            and not self.can_grant_administrator
        ):
            self.add_error(
                "is_administrator",
                "Dir fehlt das Recht, den Administratorstatus zu vergeben.",
            )
        if existing_administrator and not requested_administrator:
            if self.current_user and self.instance.pk == self.current_user.pk:
                self.add_error(
                    "is_administrator",
                    "Du kannst deinen eigenen Administratorstatus nicht entziehen.",
                )
            elif not self.can_revoke_administrator:
                self.add_error(
                    "is_administrator",
                    "Dir fehlt das Recht, den Administratorstatus zu entziehen.",
                )
        if existing_administrator and not self.can_revoke_administrator:
            cleaned["is_administrator"] = True
        if self.current_user and self.instance.pk == self.current_user.pk:
            if not cleaned.get("is_active"):
                self.add_error(
                    "is_active", "Du kannst dein eigenes Konto nicht deaktivieren."
                )
        return cleaned

    def save(self, commit=True):
        """Setzt ein neues Passwort nur, wenn ein nichtleerer Wert vorliegt."""
        user = super().save(commit=False)
        if self.can_manage_administrator:
            administrator = self.cleaned_data.get(
                "is_administrator", is_administrator(user)
            )
            user.is_superuser = administrator
            user.is_staff = administrator
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            if self.can_manage_roles:
                current_groups = set(user.groups.all())
                selected_groups = set(self.cleaned_data.get("groups", []))
                locked_groups = {
                    group
                    for group in current_groups
                    if group.pk in self.protected_group_ids
                }
                if not self.can_grant_user_permissions:
                    selected_groups.intersection_update(current_groups)
                if not self.can_revoke_user_permissions:
                    selected_groups.update(current_groups)
                selected_groups.update(locked_groups)
                user.groups.set(selected_groups)

                current_permission_ids = set(
                    user.user_permissions.values_list("pk", flat=True)
                )
                selected_ids = set(selected_permission_ids(self))
                locked_permission_ids = (
                    current_permission_ids & self.protected_permission_ids
                )
                selected_ids.difference_update(self.protected_permission_ids)
                if not self.can_grant_user_permissions:
                    selected_ids.intersection_update(current_permission_ids)
                if not self.can_revoke_user_permissions:
                    selected_ids.update(current_permission_ids)
                selected_ids.update(locked_permission_ids)
                user.user_permissions.set(
                    Permission.objects.filter(pk__in=selected_ids)
                )
        return user


class PermissionGroupForm(forms.ModelForm):
    """Erstellt Rechtegruppen mit Academy-Rechten und manueller Sortierzahl."""

    sort_order = forms.IntegerField(
        label="Sortierzahl",
        min_value=1,
        widget=forms.NumberInput(attrs={"min": 1, "step": 1}),
    )

    class Meta:
        """Speichert den frei wählbaren Gruppennamen."""

        model = Group
        fields = ("name",)

    def __init__(self, *args, **kwargs):
        """Markiert bestehende Rechte und lädt eine passende Sortierzahl."""
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            current_order = (
                PermissionGroupSortOrder.objects.filter(
                    group_id=self.instance.pk,
                )
                .values_list("sort_order", flat=True)
                .first()
            )
        else:
            current_order = None
        if current_order is None:
            current_order = (
                PermissionGroupSortOrder.objects.aggregate(
                    maximum=Max("sort_order"),
                )["maximum"]
                or 0
            ) + 1
        self.fields["sort_order"].initial = current_order
        selected_ids = (
            set(self.instance.permissions.values_list("pk", flat=True))
            if self.instance.pk
            else set()
        )
        add_permission_checkboxes(self, selected_ids)
        self.order_fields(["name", "sort_order", *self.permission_ids.values()])

    def clean_name(self):
        """Reserviert den Namen Administrator für die uneingeschränkte Sonderrolle."""
        name = self.cleaned_data["name"].strip()
        if name.casefold() == ADMINISTRATOR_GROUP.casefold():
            raise forms.ValidationError(
                "Die Rolle Administrator ist reserviert und kann nicht bearbeitet werden."
            )
        return name

    def save(self, commit=True):
        """Speichert die Gruppe und ersetzt ihre Rechteliste durch die Auswahl."""
        group = super().save(commit=commit)
        if commit:
            group.permissions.set(
                Permission.objects.filter(pk__in=selected_permission_ids(self))
            )
            PermissionGroupSortOrder.objects.update_or_create(
                group=group,
                defaults={"sort_order": self.cleaned_data["sort_order"]},
            )
        return group


class ToolSettingsForm(forms.ModelForm):
    """Validiert globale Darstellungseinstellungen und die Test-Fragenlimits."""

    class Meta:
        model = ToolSettings
        fields = (
            "site_name",
            "department_name",
            "site_icon",
            "minimum_test_questions",
            "maximum_test_questions",
            "login_page_heading",
            "login_page_text",
            "privacy_policy",
            "imprint",
        )
        widgets = {
            "login_page_heading": forms.Textarea(attrs={"rows": 3}),
            "login_page_text": forms.Textarea(attrs={"rows": 4}),
            "privacy_policy": forms.Textarea(attrs={"rows": 12}),
            "imprint": forms.Textarea(attrs={"rows": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["privacy_policy"].widget.attrs["data-original-privacy"] = (
            self.instance.privacy_policy if self.instance.pk else ""
        )
        self.fields["site_name"].widget.attrs["data-settings-site-name"] = ""
        self.fields["department_name"].widget.attrs["data-settings-department"] = ""
        self.fields["login_page_heading"].widget.attrs["data-settings-heading"] = ""
        self.fields["login_page_text"].widget.attrs["data-settings-login-text"] = ""
        for field_name in ("minimum_test_questions", "maximum_test_questions"):
            self.fields[field_name].min_value = 1
            self.fields[field_name].validators.append(
                MinValueValidator(
                    1, message="Die Fragenzahl muss mindestens 1 betragen."
                ),
            )
            self.fields[field_name].widget.attrs["min"] = 1

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("minimum_test_questions")
        maximum = cleaned.get("maximum_test_questions")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error(
                "maximum_test_questions",
                "Die maximale Fragenzahl muss mindestens der minimalen Fragenzahl entsprechen.",
            )
        return cleaned

    def clean_site_icon(self):
        icon = self.cleaned_data.get("site_icon")
        if isinstance(icon, UploadedFile):
            if icon.size > 1024 * 1024:
                raise forms.ValidationError(
                    "Das Site-Icon darf höchstens 1 MB groß sein."
                )
            signature = icon.read(8)
            icon.seek(0)
            valid_signature = (
                icon.name.lower().endswith(".png") and signature == b"\x89PNG\r\n\x1a\n"
            ) or (
                icon.name.lower().endswith(".ico")
                and signature[:4] == b"\x00\x00\x01\x00"
            )
            if not valid_signature:
                raise forms.ValidationError(
                    "Die Datei ist kein gültiges PNG- oder ICO-Site-Icon."
                )
        return icon


class GenerateTestForm(forms.Form):
    """Validiert Prüfungstyp und gewünschte Fragenanzahl."""

    question_pool = forms.ModelChoiceField(
        label="Prüfungstyp / Fragenpool",
        queryset=QuestionPool.objects.none(),
        empty_label="Prüfungstyp auswählen",
    )
    question_count = forms.IntegerField(
        label="Fragen im Test", min_value=1, widget=forms.NumberInput(attrs={"min": 1})
    )
    time_limit_minutes = forms.IntegerField(
        label="Maximale Testdauer in Minuten",
        min_value=1,
        max_value=1440,
        required=False,
        widget=forms.NumberInput(
            attrs={"min": 1, "max": 1440, "placeholder": "Kein Zeitlimit"}
        ),
        help_text="Optional. Ohne Angabe läuft der Test ohne Zeitlimit.",
    )

    def __init__(self, *args, **kwargs):
        """Bietet nur autorisierte Pools an und wählt den ersten davon vor."""
        question_pools = kwargs.pop("question_pools", None)
        minimum = kwargs.pop("minimum_questions", 1)
        maximum = kwargs.pop("maximum_questions", 100)
        super().__init__(*args, **kwargs)
        self.fields["question_pool"].queryset = (
            question_pools
            if question_pools is not None
            else QuestionPool.objects.none()
        )
        if not self.is_bound:
            self.fields["question_pool"].initial = self.fields[
                "question_pool"
            ].queryset.first()
        question_count = self.fields["question_count"]
        question_count.min_value = minimum
        question_count.max_value = maximum
        question_count.validators.extend(
            [
                MinValueValidator(
                    minimum,
                    message=f"Die Fragenzahl muss mindestens {minimum} betragen.",
                ),
                MaxValueValidator(
                    maximum,
                    message=f"Die Fragenzahl darf höchstens {maximum} betragen.",
                ),
            ]
        )
        question_count.widget.attrs.update({"min": minimum, "max": maximum})


class QuestionCsvImportForm(forms.Form):
    """Nimmt einen CSV-Export der Fragenbank zur ergänzenden Übernahme entgegen."""

    file = forms.FileField(
        label="CSV-Datei",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if not uploaded_file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Bitte eine CSV-Datei auswählen.")
        if uploaded_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Die CSV-Datei darf höchstens 5 MB groß sein.")
        return uploaded_file


class PrivacyAcceptanceForm(forms.Form):
    """Erfordert die ausdrückliche Bestätigung der aktuellen Datenschutzerklärung."""

    accepted = forms.BooleanField(
        label="Ich habe die Datenschutzerklärung gelesen und bestätige sie.",
        required=True,
    )


class QuestionPoolForm(forms.ModelForm):
    """Erstellt und bearbeitet benannte Prüfungstypen/Fragenpools."""

    class Meta:
        """Beschränkt Poolpflege auf Namen und optionale Beschreibung."""

        model = QuestionPool
        fields = ("name", "description")


class OtpForm(forms.Form):
    """Erfasst das sechsstellige Prüfungsgeheimnis ohne Benutzerkonto."""

    otp = forms.CharField(
        label="6-stelliges Einmalpasswort",
        min_length=6,
        max_length=6,
        widget=forms.PasswordInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
            }
        ),
    )

    def clean_otp(self):
        """Erlaubt ausschließlich sechs ASCII-Ziffern als OTP."""
        value = self.cleaned_data["otp"]
        if not value.isascii() or not value.isdigit():
            raise forms.ValidationError(
                "Das Einmalpasswort muss aus sechs Ziffern bestehen."
            )
        return value


class ExamineeNameForm(forms.Form):
    """Fragt nach erfolgreicher OTP-Prüfung den Namen des Prüflings ab."""

    examinee_name = forms.CharField(
        label="Name des Prüflings",
        max_length=120,
        widget=forms.TextInput(attrs={"autocomplete": "name", "autofocus": True}),
    )

    def clean_examinee_name(self):
        """Entfernt überflüssige Leerzeichen und fordert einen echten Namen."""
        value = self.cleaned_data["examinee_name"].strip()
        if not value:
            raise forms.ValidationError("Bitte gib den Namen des Prüflings ein.")
        return value
