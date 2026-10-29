"""Formulare der Testerstellung und des Prüflingsablaufs."""

from django import forms

from ..models import QuestionPool


class GenerateTestForm(forms.Form):
    """Validiert Prüfungstyp und gewünschte Fragenanzahl."""

    question_pool = forms.ModelChoiceField(
        label="Prüfungstyp / Fragenpool",
        queryset=QuestionPool.objects.none(),
        empty_label="Prüfungstyp auswählen",
    )
    time_limit_minutes = forms.IntegerField(
        label="Maximale Testdauer in Minuten",
        min_value=1,
        widget=forms.NumberInput(attrs={"min": 1}),
        help_text="Pflichtangabe innerhalb der Grenzen des gewählten Pools.",
    )

    def clean(self):
        """Prüft das Zeitlimit gegen die Grenzen des gewählten Fragenpools."""
        cleaned = super().clean()
        pool = cleaned.get("question_pool")
        minutes = cleaned.get("time_limit_minutes")
        if pool and minutes is not None:
            lowest = pool.minimum_time_limit_minutes
            highest = pool.maximum_time_limit_minutes
            if not lowest <= minutes <= highest:
                self.add_error(
                    "time_limit_minutes",
                    f"Das Zeitlimit muss für diesen Pool zwischen {lowest} und {highest} Minuten liegen.",
                )
        return cleaned

    def __init__(self, *args, **kwargs):
        """Bietet nur autorisierte Pools an und wählt den ersten davon vor."""
        question_pools = kwargs.pop("question_pools", None)
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
