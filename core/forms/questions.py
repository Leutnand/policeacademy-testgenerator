"""Formulare für Fragen, CSV-Import und Fragenpools."""

from django import forms

from ..models import Question, QuestionPool
from ..permissions import (
    POOL_UPDATE_FIELD_CAPABILITIES,
    has_access,
    has_pool_access,
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
        # Ohne Benutzer (z. B. interne Aufrufe) erfolgt keine Feldsperre
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user is not None and self.instance.pk:
            # Bestehende Frage: Verankern und Musterlösung haben je ein eigenes Poolrecht
            pool = self.instance.question_pool
            if not has_pool_access(self.user, pool, "pin"):
                self.fields["is_pinned"].disabled = True
            if not has_pool_access(self.user, pool, "edit_answer_key"):
                self.fields["answer_key"].disabled = True
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
        target_pool = cleaned.get("question_pool")
        if self.user is not None and target_pool is not None:
            # Änderungen an Verankerung oder Musterlösung erfordern das jeweilige Poolrecht
            if cleaned.get("is_pinned", False) != self.instance.is_pinned and not (
                has_pool_access(self.user, target_pool, "pin")
            ):
                self.add_error("is_pinned", "Dir fehlt das Recht, Fragen zu verankern.")
            if (cleaned.get("answer_key") or "") != (
                self.instance.answer_key or ""
            ) and not has_pool_access(self.user, target_pool, "edit_answer_key"):
                self.add_error(
                    "answer_key", "Dir fehlt das Recht, die Musterlösung zu ändern."
                )
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


class QuestionPoolForm(forms.ModelForm):
    """Erstellt und bearbeitet benannte Prüfungstypen/Fragenpools."""

    class Meta:
        """Beschränkt Poolpflege auf Namen, Beschreibung und Testparameter."""

        model = QuestionPool
        fields = (
            "name",
            "description",
            "test_question_count",
            "pass_percentage",
            "minimum_time_limit_minutes",
            "maximum_time_limit_minutes",
            "start_info_text",
            "start_confirmations",
        )

    def __init__(self, *args, **kwargs):
        current_user = kwargs.pop("current_user", None)
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Bestehender Pool: jedes Feld nur mit dem passenden Einzelrecht änderbar
            for field_name, capability in POOL_UPDATE_FIELD_CAPABILITIES.items():
                if not has_access(current_user, capability):
                    self.fields[field_name].disabled = True
        self.fields["start_info_text"].widget.attrs["rows"] = 6
        self.fields["start_confirmations"].widget.attrs["rows"] = 4
        self.fields["test_question_count"].widget.attrs["min"] = 1
        self.fields["test_question_count"].help_text = (
            "Jeder Test aus diesem Pool enthält genau diese Anzahl an Fragen."
        )
        self.fields["pass_percentage"].widget.attrs.update({"min": 0, "max": 100})
        self.fields["pass_percentage"].help_text = (
            "Mindestprozentwert (0 bis 100), ab dem ein Test als bestanden gilt."
        )
        for field_name in ("minimum_time_limit_minutes", "maximum_time_limit_minutes"):
            self.fields[field_name].widget.attrs.update({"min": 1, "max": 1440})
        self.fields["minimum_time_limit_minutes"].help_text = (
            "Grenzen für das Zeitlimit, das beim Erstellen eines Tests eingegeben wird."
        )

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("minimum_time_limit_minutes")
        maximum = cleaned.get("maximum_time_limit_minutes")
        if maximum is not None and maximum > 1440:
            self.add_error(
                "maximum_time_limit_minutes",
                "Das maximale Zeitlimit darf höchstens 1.440 Minuten betragen.",
            )
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error(
                "maximum_time_limit_minutes",
                "Das maximale Zeitlimit muss mindestens dem minimalen Zeitlimit entsprechen.",
            )
        return cleaned
