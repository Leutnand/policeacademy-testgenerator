"""Formulare für Tool-Einstellungen und die Datenschutzbestätigung."""

from django import forms
from django.core.files.uploadedfile import UploadedFile

from ..models import ToolSettings
from ..permissions import has_access, is_administrator


class ToolSettingsForm(forms.ModelForm):
    """Validiert globale Darstellungseinstellungen und die Test-Fragenlimits."""

    class Meta:
        model = ToolSettings
        fields = (
            "site_name",
            "department_name",
            "site_icon",
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
        current_user = kwargs.pop("current_user", None)
        super().__init__(*args, **kwargs)
        field_capabilities = {
            "site_name": "update_site_name",
            "department_name": "update_department_name",
            "site_icon": "update_site_icon",
            "login_page_heading": "update_login_heading",
            "login_page_text": "update_login_text",
            "privacy_policy": "update_privacy_policy",
            "imprint": "update_imprint",
        }
        self.writable_fields = {
            field_name
            for field_name, capability in field_capabilities.items()
            if is_administrator(current_user) or has_access(current_user, capability)
        }
        for field_name in field_capabilities:
            self.fields[field_name].disabled = field_name not in self.writable_fields
        self.fields["privacy_policy"].widget.attrs["data-original-privacy"] = (
            self.instance.privacy_policy if self.instance.pk else ""
        )
        self.fields["site_name"].widget.attrs["data-settings-site-name"] = ""
        self.fields["department_name"].widget.attrs["data-settings-department"] = ""
        self.fields["login_page_heading"].widget.attrs["data-settings-heading"] = ""
        self.fields["login_page_text"].widget.attrs["data-settings-login-text"] = ""

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


class PrivacyAcceptanceForm(forms.Form):
    """Erfordert die ausdrückliche Bestätigung der aktuellen Datenschutzerklärung."""

    accepted = forms.BooleanField(
        label="Ich habe die Datenschutzerklärung gelesen und bestätige sie.",
        required=True,
    )
