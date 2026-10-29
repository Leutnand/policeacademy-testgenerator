"""Formulare für Mitarbeiter, Rechtegruppen und Berechtigungsauswahl."""

from django import forms
from django.contrib.auth.models import Group, Permission, User
from django.db.models import Max, Q, Value
from django.db.models.functions import Coalesce

from ..models import PermissionGroupSortOrder, QuestionPool
from ..permissions import (
    ADMINISTRATOR_GROUP,
    DELEGATION_CONTROL_CODES,
    GLOBAL_PERMISSION_CODES,
    POOL_PERMISSION_PREFIXES,
    USER_UPDATE_FIELD_CAPABILITIES,
    has_access,
    is_administrator,
)

# Themenbereiche der globalen Rechte in fester Anzeigereihenfolge
GLOBAL_PERMISSION_SECTIONS = (
    (
        "Mitarbeiter",
        (
            "can_view_users",
            "can_create_users",
            "can_update_user_username",
            "can_update_user_first_name",
            "can_update_user_last_name",
            "can_set_user_passwords",
            "can_activate_users",
            "can_deactivate_users",
            "can_delete_users",
        ),
    ),
    (
        "Rechtegruppen",
        (
            "can_view_permission_groups",
            "can_create_permission_groups",
            "can_rename_permission_groups",
            "can_update_permission_group_priority",
            "can_delete_permission_groups",
        ),
    ),
    (
        "Rechtevergabe",
        (
            "can_view_user_permissions",
            "can_assign_user_groups",
            "can_unassign_user_groups",
            "can_grant_user_permissions",
            "can_revoke_user_permissions",
            "can_grant_group_permissions",
            "can_revoke_group_permissions",
            "can_grant_administrator",
            "can_revoke_administrator",
        ),
    ),
    (
        "Fragenpool-Verwaltung",
        (
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
        ),
    ),
    (
        "Tool-Einstellungen",
        (
            "can_view_tool_settings",
            "can_update_site_name",
            "can_update_department_name",
            "can_update_site_icon",
            "can_update_login_heading",
            "can_update_login_text",
            "can_update_privacy_policy",
            "can_update_imprint",
        ),
    ),
    ("Tests", ("can_delete_tests",)),
    (
        "Systemprotokoll",
        ("can_view_audit_logs", "can_export_audit_logs", "can_clear_audit_logs"),
    ),
)
GLOBAL_SECTION_LOOKUP = {
    codename: (section_index, position)
    for section_index, (_, codenames) in enumerate(GLOBAL_PERMISSION_SECTIONS)
    for position, codename in enumerate(codenames)
}


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
    # Poolrechte: Reihenfolge und Unterthema (Fragen bzw. Tests & Auswertung)
    pool_action_order = {
        action: index
        for index, action in enumerate(
            (
                "view",
                "create",
                "update",
                "import",
                "export",
                "pin",
                "edit_answer_key",
                "delete_single",
                "delete_bulk",
                "generate",
                "view_submissions",
                "grade",
                "rename_examinee",
            )
        )
    }
    pool_test_actions = {"generate", "view_submissions", "grade", "rename_examinee"}
    global_help = {
        "can_view_users": "Zeigt die Mitarbeiterübersicht.",
        "can_view_user_permissions": "Zeigt die Rechte und Gruppen eines Mitarbeiters an.",
        "can_create_users": "Erlaubt das Anlegen von Mitarbeiterkonten.",
        "can_update_user_username": "Ändert den Benutzernamen (Anmeldenamen) eines Mitarbeiters.",
        "can_update_user_first_name": "Ändert den Vornamen eines Mitarbeiters.",
        "can_update_user_last_name": "Ändert den Nachnamen eines Mitarbeiters.",
        "can_activate_users": "Aktiviert ein deaktiviertes Mitarbeiterkonto wieder.",
        "can_deactivate_users": "Deaktiviert ein Mitarbeiterkonto (das eigene Konto bleibt geschützt).",
        "can_set_user_passwords": "Setzt ein neues Passwort für einen Mitarbeiter.",
        "can_delete_users": "Löscht Mitarbeiterkonten. Das eigene Konto und andere Administratoren sind geschützt.",
        "can_view_permission_groups": "Zeigt die Verwaltung der Rechtegruppen.",
        "can_create_permission_groups": "Erlaubt das Anlegen von Rechtegruppen.",
        "can_rename_permission_groups": "Benennt eine Rechtegruppe um.",
        "can_update_permission_group_priority": "Ändert die Sortierzahl (Priorität) einer Rechtegruppe.",
        "can_delete_permission_groups": "Erlaubt das Löschen von Rechtegruppen.",
        "can_view_tool_settings": "Zeigt die Tool-Einstellungen.",
        "can_update_site_name": "Ändert den Seitentitel.",
        "can_update_department_name": "Ändert den Department-Namen.",
        "can_update_site_icon": "Ändert das Site-Icon.",
        "can_update_login_heading": "Ändert die Überschrift der Anmeldeseite.",
        "can_update_login_text": "Ändert den Text der Anmeldeseite.",
        "can_update_privacy_policy": "Ändert die Datenschutzerklärung.",
        "can_update_imprint": "Ändert das Impressum.",
        "can_delete_tests": "Löscht abgeschlossene Tests. Zusätzlich ist Auswertungszugriff auf den zugehörigen Pool erforderlich.",
        "can_view_audit_logs": "Zeigt Zugriffe und Änderungen im Systemprotokoll an.",
        "can_export_audit_logs": "Exportiert die gefilterten Audit-Einträge als CSV.",
        "can_clear_audit_logs": "Leert alle bisherigen Logeinträge. Der Löschvorgang wird selbst protokolliert; zusätzlich ist Leserecht nötig.",
        "can_grant_user_permissions": "Vergibt Gruppenmitgliedschaften und direkte Rechte.",
        "can_revoke_user_permissions": "Entzieht Gruppenmitgliedschaften und direkte Rechte.",
        "can_assign_user_groups": "Weist Mitarbeitenden Rechtegruppen zu.",
        "can_unassign_user_groups": "Entzieht Mitarbeitenden Rechtegruppen.",
        "can_grant_group_permissions": "Fügt einer Rechtegruppe einzelne Berechtigungen hinzu.",
        "can_revoke_group_permissions": "Entzieht einer Rechtegruppe einzelne Berechtigungen.",
        "can_grant_administrator": "Vergibt einer anderen Person vollständigen Administratorzugriff.",
        "can_revoke_administrator": "Entzieht einer anderen Person den Administratorzugriff. Der eigene Status bleibt geschützt.",
        "can_view_question_pools": "Zeigt die Fragenpoolverwaltung.",
        "can_create_question_pools": "Legt einen neuen Fragenpool an.",
        "can_update_pool_name": "Benennt einen Fragenpool um.",
        "can_update_pool_description": "Ändert die Beschreibung eines Fragenpools.",
        "can_update_pool_question_count": "Ändert, wie viele Fragen ein Test aus dem Pool enthält.",
        "can_update_pool_pass_percentage": "Ändert die Bestehensgrenze in Prozent.",
        "can_update_pool_min_time_limit": "Ändert das minimale Zeitlimit eines Tests.",
        "can_update_pool_max_time_limit": "Ändert das maximale Zeitlimit eines Tests.",
        "can_update_pool_start_info_text": "Ändert den Infotext vor dem Teststart.",
        "can_update_pool_start_confirmations": "Ändert die Bestätigungsaussagen vor dem Teststart.",
        "can_delete_question_pools": "Löscht einen leeren Fragenpool.",
    }
    pool_help = {
        "view": "Erlaubt, Fragen dieses Pools in der Academy-Fragenbank anzusehen.",
        "create": "Erlaubt, neue Fragen ausschließlich in diesem Pool anzulegen.",
        "update": "Erlaubt, bestehende Fragen dieses Pools zu ändern.",
        "import": "Erlaubt, Fragen in diesen Pool zu importieren.",
        "export": "Erlaubt, Fragen aus diesem Pool zu exportieren.",
        "generate": "Erlaubt Tests ausschließlich aus diesem Fragenpool zu erstellen.",
        "view_submissions": "Erlaubt Abgaben dieses Pools anzusehen.",
        "grade": "Erlaubt, Abgaben dieses Pools zu bewerten.",
        "delete_single": "Erlaubt genau eine Frage in diesem Pool zu löschen.",
        "delete_bulk": "Erlaubt mehrere ausgewählte Fragen dieses Pools gemeinsam zu löschen.",
        "rename_examinee": "Erlaubt, den Namen eines Prüflings in der Auswertung dieses Pools zu ändern.",
        "pin": "Erlaubt, Fragen dieses Pools zu verankern oder die Verankerung zu lösen.",
        "edit_answer_key": "Erlaubt, die Musterlösung (Antwortschlüssel) von Fragen dieses Pools zu ändern.",
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
            section_kind = "pool"
            pool_action = next(
                action
                for action, prefix in POOL_PERMISSION_PREFIXES.items()
                if permission.codename.startswith(prefix)
            )
            field_order = pool_action_order[pool_action]
            subgroup = (
                "Tests & Auswertung" if pool_action in pool_test_actions else "Fragen"
            )
        else:
            # Globale Rechte werden nach Themenbereich gruppiert und dort sortiert
            section_index, field_order = GLOBAL_SECTION_LOOKUP.get(
                permission.codename,
                (len(GLOBAL_PERMISSION_SECTIONS), global_codes[permission.codename]),
            )
            section_key = (0, f"{section_index:02d}")
            section_kind = "global"
            subgroup = ""
            section_title = (
                GLOBAL_PERMISSION_SECTIONS[section_index][0]
                if section_index < len(GLOBAL_PERMISSION_SECTIONS)
                else "Weitere Rechte"
            )
        if pool_id and pool_id in pools:
            pool_action = next(
                action_name
                for action_name, prefix in POOL_PERMISSION_PREFIXES.items()
                if permission.codename.startswith(prefix)
            )
            permission_help = pool_help[pool_action]
        else:
            permission_help = global_help.get(
                permission.codename,
                "Erlaubt die zugehörige atomare Systemaktion.",
            )
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
                "kind": section_kind,
                "anchor": f"perm-section-{len(sections)}",
                "fields": [],
            },
        )["fields"].append(
            {
                "subgroup": subgroup,
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
    # Ankernamen nach der endgültigen Sortierung vergeben, damit die Sprungleiste stimmt
    for index, section in enumerate(form.permission_sections):
        section["anchor"] = f"perm-section-{index}"
        section["total"] = len(section["fields"])
    form.global_permission_sections = [
        s for s in form.permission_sections if s["kind"] == "global"
    ]
    form.pool_permission_sections = [
        s for s in form.permission_sections if s["kind"] == "pool"
    ]
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
        queryset=Group.objects.exclude(name=ADMINISTRATOR_GROUP)
        .annotate(display_order=Coalesce("sort_config__sort_order", Value(0)))
        .order_by("display_order", "name"),
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
        self.rights_only = kwargs.pop("rights_only", False)
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
            self.can_grant_user_permissions
            or self.can_revoke_user_permissions
            or is_administrator(self.current_user)
        )
        self.can_assign_user_groups = is_administrator(self.current_user) or has_access(
            self.current_user, "can_assign_user_groups"
        )
        self.can_unassign_user_groups = is_administrator(
            self.current_user
        ) or has_access(self.current_user, "can_unassign_user_groups")
        self.can_manage_groups = (
            self.can_assign_user_groups or self.can_unassign_user_groups
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
        self.can_save_rights = (
            self.can_manage_roles
            or self.can_manage_groups
            or self.can_manage_administrator
        )
        super().__init__(*args, **kwargs)
        self.fields["is_administrator"].initial = is_administrator(self.instance)
        self.fields["is_administrator"].disabled = not self.can_manage_administrator
        self.fields["username"].label = "Benutzername"
        self.fields["first_name"].label = "Vorname"
        self.fields["last_name"].label = "Nachname"
        self.fields["is_active"].label = "Konto aktiv"
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
            self.protected_group_ids = set(
                Group.objects.filter(permissions__in=protected_permissions).values_list(
                    "pk", flat=True
                )
            )
        if self.can_manage_groups:
            self.fields["groups"].queryset = self.fields["groups"].queryset.exclude(
                pk__in=self.protected_group_ids
            )
        else:
            self.fields["groups"].queryset = (
                self.instance.groups.all() if self.instance.pk else Group.objects.none()
            )
            self.fields["groups"].disabled = True
        if self.can_manage_roles:
            selected_ids = (
                set(self.instance.user_permissions.values_list("pk", flat=True))
                if self.instance.pk
                else set()
            )
            add_permission_checkboxes(self, selected_ids)
            for permission_id, field_name in self.permission_ids.items():
                selected = permission_id in selected_ids
                field = self.fields[field_name]
                field.disabled = (
                    (selected and not self.can_revoke_user_permissions)
                    or (not selected and not self.can_grant_user_permissions)
                    or permission_id in self.protected_permission_ids
                )
        else:
            self.permission_sections = []
            self.permission_ids = {}
        if self.instance.pk and not self.rights_only:
            # Bestehende Konten: jedes Feld nur mit seinem eigenen Einzelrecht änderbar
            for field_name, capability in USER_UPDATE_FIELD_CAPABILITIES.items():
                if not has_access(self.current_user, capability):
                    self.fields[field_name].disabled = True
            may_toggle_active = has_access(
                self.current_user,
                (
                    "can_deactivate_users"
                    if self.instance.is_active
                    else "can_activate_users"
                ),
            )
            if not may_toggle_active:
                self.fields["is_active"].disabled = True
        if self.rights_only:
            for field_name in (
                "username",
                "first_name",
                "last_name",
                "is_active",
                "password",
            ):
                self.fields[field_name].disabled = True
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
            if self.can_manage_groups:
                current_groups = set(user.groups.all())
                selected_groups = set(self.cleaned_data.get("groups", []))
                locked_groups = {
                    group
                    for group in current_groups
                    if group.pk in self.protected_group_ids
                }
                if not self.can_assign_user_groups:
                    selected_groups.intersection_update(current_groups)
                if not self.can_unassign_user_groups:
                    selected_groups.update(current_groups)
                selected_groups.update(locked_groups)
                user.groups.set(selected_groups)

            if self.can_manage_roles:
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
        self.current_user = kwargs.pop("current_user", None)
        self.can_grant_group_permissions = is_administrator(
            self.current_user
        ) or has_access(self.current_user, "can_grant_group_permissions")
        self.can_revoke_group_permissions = is_administrator(
            self.current_user
        ) or has_access(self.current_user, "can_revoke_group_permissions")
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
        if self.instance.pk:
            # Bestehende Gruppe: Name und Priorität haben je ein eigenes Recht
            if not has_access(self.current_user, "can_rename_permission_groups"):
                self.fields["name"].disabled = True
            if not has_access(
                self.current_user, "can_update_permission_group_priority"
            ):
                self.fields["sort_order"].disabled = True
        selected_ids = (
            set(self.instance.permissions.values_list("pk", flat=True))
            if self.instance.pk
            else set()
        )
        add_permission_checkboxes(self, selected_ids)
        for permission_id, field_name in self.permission_ids.items():
            selected = permission_id in selected_ids
            if (selected and not self.can_revoke_group_permissions) or (
                not selected and not self.can_grant_group_permissions
            ):
                self.fields[field_name].disabled = True
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
