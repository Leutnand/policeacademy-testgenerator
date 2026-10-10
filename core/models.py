"""Datenmodelle für Fragen, Tests und deren Abgaben."""

import uuid
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)


class QuestionPool(models.Model):
    """Benannter Fragenbestand für einen eigenständigen Prüfungstyp."""

    name = models.CharField("Name des Fragenpools", max_length=120, unique=True)
    description = models.TextField("Beschreibung", blank=True)
    test_question_count = models.PositiveIntegerField(
        "Fragenzahl je Test",
        default=20,
        validators=[MinValueValidator(1)],
    )
    pass_percentage = models.PositiveSmallIntegerField(
        "Bestehgrenze in Prozent",
        default=50,
        validators=[MaxValueValidator(100)],
    )
    minimum_time_limit_minutes = models.PositiveIntegerField(
        "Minimales Zeitlimit in Minuten",
        default=5,
        validators=[MinValueValidator(1)],
    )
    maximum_time_limit_minutes = models.PositiveIntegerField(
        "Maximales Zeitlimit in Minuten",
        default=180,
        validators=[MinValueValidator(1)],
    )
    start_info_text = models.TextField(
        "Infotext vor Testbeginn",
        blank=True,
        help_text=(
            "Optionaler längerer Text, der vor Testbeginn angezeigt wird. Der Prüfling "
            "bestätigt ihn mit einer Checkbox „Gelesen und verstanden“."
        ),
    )
    start_confirmations = models.TextField(
        "Bestätigungen vor Testbeginn",
        blank=True,
        help_text=(
            "Eine Aussage pro Zeile. Der Prüfling muss jede Aussage vor Testbeginn "
            "bestätigen. Leer lassen, wenn keine Bestätigung nötig ist."
        ),
    )
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)

    @property
    def start_confirmation_list(self):
        """Liefert die nicht leeren Bestätigungsaussagen."""
        return [
            line.strip() for line in self.start_confirmations.splitlines() if line.strip()
        ]

    class Meta:
        """Sortiert Pools stabil und definiert die verbliebenen globalen Rechte."""

        ordering = ["name"]
        permissions = [
            ("can_manage_users", "Mitarbeiter, Gruppen und Rechte verwalten"),
            ("can_delete_users", "Mitarbeiterkonten löschen"),
            ("can_manage_tool_settings", "Seiteneinstellungen verwalten"),
            ("can_delete_tests", "Abgegebene Tests löschen"),
            ("can_view_audit_logs", "Systemprotokoll einsehen"),
            ("can_clear_audit_logs", "Systemprotokoll leeren"),
            ("can_grant_user_permissions", "Nutzerrechte vergeben"),
            ("can_revoke_user_permissions", "Nutzerrechte entziehen"),
            ("can_grant_administrator", "Administratorstatus vergeben"),
            ("can_revoke_administrator", "Administratorstatus entziehen"),
        ]

    def __str__(self):
        """Zeigt den Poolnamen in Auswahlfeldern und Verwaltungslisten."""
        return self.name


class PermissionGroupSortOrder(models.Model):
    """Speichert die manuell festgelegte Reihenfolge einer Rechtegruppe."""

    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="sort_config",
        verbose_name="Rechtegruppe",
    )
    sort_order = models.PositiveIntegerField("Sortierzahl", default=1)

    class Meta:
        """Zeigt gleiche Sortierzahlen stabil nach Gruppennamen an."""

        ordering = ["sort_order", "group__name"]

    def __str__(self):
        """Liefert Sortierzahl und Gruppennamen für Verwaltungsansichten."""
        return f"{self.sort_order} · {self.group.name}"


class ToolSettings(models.Model):
    """Konfiguration der sichtbaren Marke, Rechtstexte und Testgrenzen."""

    site_name = models.CharField(
        "Seitentitel", max_length=120, default="Police Academy Test Generator"
    )
    department_name = models.CharField(
        "Department-Name", max_length=120, default="San Andreas Police Department"
    )
    site_icon = models.FileField(
        "Favicon / Site-Icon",
        upload_to="site-icons/",
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["ico", "png"])],
    )
    login_page_heading = models.TextField(
        "Überschrift der Anmeldeseite",
        default="Train with\npurpose.\nServe with honor.",
    )
    login_page_text = models.TextField(
        "Text der Anmeldeseite",
        default="Prüfungsverwaltung für die Police Academy. Fragen, Testläufe und Bewertungen an einem Ort.",
    )
    privacy_policy = models.TextField("Datenschutzerklärung", blank=True)
    imprint = models.TextField("Impressum", blank=True)

    class Meta:
        """Stellt den Datensatz als zentrale Toolkonfiguration dar."""

        verbose_name = "Tool-Einstellungen"
        verbose_name_plural = "Tool-Einstellungen"

    @classmethod
    def current(cls):
        """Liefert den einzelnen Konfigurationsdatensatz und legt ihn bei Bedarf an."""
        return cls.objects.get_or_create(pk=1)[0]


class StaffProfile(models.Model):
    """Speichert die Datenschutzbestätigung je Mitarbeiterkonto."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    accepted_privacy_hash = models.CharField(max_length=64, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)


class Question(models.Model):
    """Frage im Fragenpool; Lösungen sind ausschließlich intern verfügbar."""

    class Type(models.TextChoices):
        """Verfügbare Typen bestimmen Darstellung und automatische Bewertung."""

        SINGLE = "single", "Single Choice"
        MULTIPLE = "multiple", "Multiple Choice"
        SHORT = "short", "Kurzantwort"
        LONG = "long", "Lange Antwort / Freitext"

    text = models.TextField("Fragetext")
    question_pool = models.ForeignKey(
        QuestionPool,
        on_delete=models.PROTECT,
        related_name="questions",
        verbose_name="Fragenpool",
    )
    question_type = models.CharField("Fragetyp", max_length=12, choices=Type.choices)
    options = models.JSONField("Antwortoptionen", default=list, blank=True)
    points = models.DecimalField("Punkte", max_digits=7, decimal_places=2, default=1)
    answer_key = models.TextField("Musterlösung", blank=True)
    is_pinned = models.BooleanField("Verankert", default=False)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)
    updated_at = models.DateTimeField("Aktualisiert am", auto_now=True)

    class Meta:
        """Sortiert Fragen; poolbezogene Rechte werden dynamisch am Pool erzeugt."""

        ordering = ["-is_pinned", "-updated_at"]

    def __str__(self):
        """Liefert eine kompakte Bezeichnung für Listen und Admin."""
        return f"{self.get_question_type_display()}: {self.text[:70]}"


class TestSession(models.Model):
    """Erzeugter Test mit UUID und sicher gehashtem Einmalpasswort."""

    class Status(models.TextChoices):
        """Kennzeichnet einen noch nutzbaren oder bereits verbrauchten Zugang."""

        ISSUED = "issued", "Ausgestellt"
        COMPLETED = "completed", "Abgeschlossen"

    id = models.UUIDField(
        "Test-UUID", primary_key=True, default=uuid.uuid4, editable=False
    )
    question_pool = models.ForeignKey(
        QuestionPool,
        on_delete=models.PROTECT,
        related_name="test_sessions",
        verbose_name="Prüfungstyp / Fragenpool",
    )
    otp_hash = models.CharField("OTP-Hash", max_length=256)
    examinee_name = models.CharField("Name des Prüflings", max_length=120, blank=True)
    status = models.CharField(
        "Status", max_length=12, choices=Status.choices, default=Status.ISSUED
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_tests",
    )
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)
    time_limit_minutes = models.PositiveIntegerField(
        "Zeitlimit in Minuten", null=True, blank=True
    )
    pass_percentage = models.PositiveSmallIntegerField(
        "Bestehgrenze in Prozent (bei Erstellung)", null=True, blank=True
    )
    otp_verified_at = models.DateTimeField(
        "Einmalpasswort bestätigt am", null=True, blank=True
    )
    started_at = models.DateTimeField("Gestartet am", null=True, blank=True)
    completed_at = models.DateTimeField("Abgeschlossen am", null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(
        "Bearbeitungszeit in Sekunden", null=True, blank=True
    )

    @property
    def time_taken_display(self):
        """Formatiert die gespeicherte Bearbeitungszeit für Ergebnisansichten."""
        if self.elapsed_seconds is None:
            return "Nicht erfasst"
        hours, remainder = divmod(self.elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def __str__(self):
        """Zeigt UUID und Status, ohne das Geheimnis offenzulegen."""
        return f"Test {self.pk} ({self.get_status_display()})"


class TestQuestion(models.Model):
    """Fragenschnappschuss hält einen erzeugten Test unverändert."""

    test = models.ForeignKey(
        TestSession, on_delete=models.CASCADE, related_name="items"
    )
    source_question = models.ForeignKey(
        Question, on_delete=models.SET_NULL, null=True, blank=True
    )
    position = models.PositiveIntegerField("Position")
    text = models.TextField("Fragetext")
    question_type = models.CharField(
        "Fragetyp", max_length=12, choices=Question.Type.choices
    )
    options = models.JSONField(
        "Optionen und interne Lösungsschlüssel", default=list, blank=True
    )
    points = models.DecimalField("Punkte", max_digits=7, decimal_places=2)
    answer_key = models.TextField("Musterlösung", blank=True)

    class Meta:
        """Sichert Testreihenfolge und eine eindeutige Positionsnummer."""

        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["test", "position"], name="unique_test_question_position"
            )
        ]

    def __str__(self):
        """Liefert eine verständliche Bezeichnung für den Admin."""
        return f"{self.test_id} · Frage {self.position}"


class Submission(models.Model):
    """Antwort auf eine Testfrage einschließlich Bewertungsmetadaten."""

    test = models.ForeignKey(
        TestSession, on_delete=models.CASCADE, related_name="submissions"
    )
    test_question = models.ForeignKey(
        TestQuestion, on_delete=models.CASCADE, related_name="submissions"
    )
    answer = models.JSONField("Antwort", default=dict, blank=True)
    score = models.DecimalField(
        "Erreichte Punkte", max_digits=7, decimal_places=2, null=True, blank=True
    )
    needs_manual_grading = models.BooleanField(
        "Manuelle Korrektur erforderlich", default=False
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graded_submissions",
    )
    graded_at = models.DateTimeField("Bewertet am", null=True, blank=True)

    class Meta:
        """Verhindert doppelte Antworten zur selben Testfrage."""

        constraints = [
            models.UniqueConstraint(
                fields=["test", "test_question"],
                name="unique_submission_per_test_question",
            )
        ]

    def __str__(self):
        """Liefert eine knappe Korrekturansicht-Bezeichnung."""
        return f"Abgabe {self.test_id} · Frage {self.test_question.position}"

    @property
    def answer_text(self):
        """Formatiert einen gespeicherten Einzelwert oder eine Auswahl für die Anzeige."""
        value = self.answer.get("value", "")
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)


class AuditLog(models.Model):
    """Unveränderlicher Prüfpfad für HTTP-Zugriffe und fachliche Änderungen."""

    class Category(models.TextChoices):
        """Gruppiert Einträge für die geschützte Logansicht."""

        REQUEST = "request", "Zugriff"
        AUTH = "auth", "Anmeldung"
        QUESTION = "question", "Fragenbank"
        TEST = "test", "Testlauf"
        SUBMISSION = "submission", "Abgabe/Korrektur"
        STAFF = "staff", "Mitarbeiter/Rechte"
        SECURITY = "security", "Sicherheit"

    created_at = models.DateTimeField("Zeitpunkt", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    category = models.CharField(
        "Bereich", max_length=16, choices=Category.choices, db_index=True
    )
    action = models.CharField("Aktion", max_length=80, db_index=True)
    description = models.TextField("Beschreibung")
    object_type = models.CharField("Objekttyp", max_length=80, blank=True)
    object_id = models.CharField("Objekt-ID", max_length=100, blank=True)
    ip_address = models.GenericIPAddressField("IP-Adresse", null=True, blank=True)
    user_agent = models.CharField("Browserkennung", max_length=512, blank=True)
    metadata = models.JSONField("Zusatzinformationen", default=dict, blank=True)

    class Meta:
        """Ordnet Protokolle chronologisch neueste zuerst."""

        ordering = ["-created_at", "-pk"]

    def __str__(self):
        """Liefert eine kompakte Beschreibung für Admin und Loglisten."""
        username = self.actor.get_username() if self.actor_id else "Anonym"
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} · {username} · {self.action}"
