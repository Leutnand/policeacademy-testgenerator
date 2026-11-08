# Erweiterte Audit-Logging Implementierung

## Übersicht

Das Logging-System wurde vollständig überarbeitet, um eine **hundertprozentige Überwachung** aller Mitarbeiteraktionen zu ermöglichen. Jeder Schritt - ob Ansicht, Bearbeitung oder Änderung - wird jetzt detailliert geloggt.

## Neue Logging-Funktionen

### 1. **Erweiterte Audit-Module** (`core/audit.py`)

#### `record_access()` - Neue Funktion
- Protokolliert **Zugriffe auf geschützte Daten** (GET-Anfragen)
- Ideal für Lesevorgänge ohne Änderungen
- Wird von Views für Viewzugriffe verwendet
- **Beispiel**: "Fragenbank angezeigt", "Testabgabe angezeigt"

#### `record_change()` - Neue Funktion
- Speichert **Vorher-Nachher-Vergleiche** für Änderungen
- Capures Werte BEFORE und AFTER automatisch in metadata
- Ermöglicht vollständige Audit-Trail-Nachverfolgung
- **Beispiel**: "Recht 'X' hinzugefügt, 'Y' entfernt"

### 2. **Automatische Middleware-Logging**

Die existierende `AuditRequestMiddleware` (`core/middleware.py`) protokolliert bereits:
- ✅ Alle HTTP-Anfragen (Methode, Pfad, Status)
- ✅ Anfrage-Dauer in Millisekunden
- ✅ IP-Adresse und Browser-Kennung
- ✅ Benutzer und Route-Name
- ✅ Konfigurierbar via `AUDIT_LOG_REQUESTS` Setting

**Einstellung**: `AUDIT_LOG_REQUESTS = "all"` (alle Anfragen) oder `"changes"` (nur Änderungen)

## Geloggte Aktionen nach Bereich

### Tests & Abgaben (`core/views/tests_flow.py`)

| Action | Protokolliert | Details |
|--------|--------------|---------|
| `test.questions.viewed` | ✅ **NEU** | Zugriff auf Test-Fragen mit Pool-Name |
| `test.examinee_identified` | ✅ **NEU** | Prüfling-Name eingegeben |
| `test.started` | ✅ **NEU** | Test gestartet (alle Bestätigungen erledigt) |
| `tests.running_list.viewed` | ✅ **NEU** | Laufende Tests-Liste angezeigt |
| `submissions.list.viewed` | ✅ **NEU** | Abgabenliste angezeigt mit Filtern |
| `submission.viewed` | ✅ **NEU** | Einzelne Abgabe + Antworten angezeigt |
| `submission.graded` | ✅ **ERWEITERT** | Individuelle Bewertung pro Antwort mit Vorher-Nachher |
| `submission.graded_batch` | ✅ **NEU** | Aggregierte Bewertungs-Session mit allen Änderungen |
| `test.otp.accepted` | ✅ (existierend) | OTP-Validierung erfolgreich |
| `test.otp.rejected` | ✅ (existierend) | OTP-Versuch fehlgeschlagen |
| `test.otp.locked` | ✅ (existierend) | OTP-Versuche überschritten |
| `test.deleted` | ✅ (existierend) | Test gelöscht mit Prüfling-Name |

**Metadata-Struktur für Bewertungen:**
```json
{
  "pool": "Fragenpool-Name",
  "examinee_name": "Max Mustermann",
  "changes_count": 3,
  "changes": [
    {
      "question_position": 1,
      "old_score": "3",
      "new_score": "5",
      "old_needs_manual_grading": false,
      "max_points": 5
    }
  ]
}
```

### Fragenverwaltung (`core/views/questions.py`)

| Action | Protokolliert | Details |
|--------|--------------|---------|
| `questions.list.viewed` | ✅ **NEU** | Fragenbank mit Suchfilter, Pool-Filter |
| `questions.exported` | ✅ **NEU** | Fragen-Export mit Anzahl |
| `question.csv.imported` | ✅ **ERWEITERT** | Import mit Anzahl importiert, Duplikate, Fehler |
| `question.created` | ✅ (existierend) | Neue Frage angelegt |
| `question.updated` | ✅ (existierend) | Frage bearbeitet |
| `question.deleted` | ✅ (existierend) | Frage gelöscht |

**Metadata für CSV-Import:**
```json
{
  "pool_name": "Pool-Name",
  "imported_count": 45,
  "skipped_duplicates": 3,
  "valid_row_count": 48,
  "error_count": 0
}
```

### Rechte & Mitarbeiter (`core/views/rights.py`)

| Action | Protokolliert | Details |
|--------|--------------|---------|
| `permission_group.created` | ✅ (existierend) | Gruppe angelegt |
| `permission_group.updated` | ✅ **ERWEITERT** | Rechte mit Differenzen (hinzugefügt/entfernt) |
| `permission_group.deleted` | ✅ (existierend) | Gruppe gelöscht |
| `staff.permissions.updated` | ✅ **ERWEITERT** | Benutzer-Rechte mit Differenzen |

**Metadata für Gruppen-Bearbeitung:**
```json
{
  "added_permissions": ["can_delete_tests", "can_grade_submissions"],
  "removed_permissions": ["can_view_submissions"],
  "current_permissions": [...],
  "member_count": 5
}
```

**Metadata für Benutzer-Rechte:**
```json
{
  "username": "john_doe",
  "is_administrator": false,
  "added_groups": ["Moderator"],
  "removed_groups": ["Benutzer"],
  "added_direct_permissions": [],
  "removed_direct_permissions": ["can_delete_tests"],
  "current_groups": ["Moderator"],
  "current_direct_permissions": [...]
}
```

### Authentifizierung & Konto (`core/views/account.py`)

| Action | Protokolliert | Details |
|--------|--------------|---------|
| `auth.login` | ✅ (existierend) | Anmeldung erfolgreich |
| `auth.logout` | ✅ (existierend) | Abmeldung |
| `auth.failed_login` | ✅ (existierend) | Fehlgeschlagene Anmeldung |
| `account.password_changed` | ✅ (existierend) | Passwort geändert |
| `account.profile_updated` | ✅ (existierend) | Profildetails aktualisiert |

## AuditLog-Kategorien

| Kategorie | Zweck | Farbe im UI |
|-----------|--------|-----------|
| `REQUEST` | HTTP-Zugriffe und Lesevorgänge | Blau |
| `AUTH` | An-/Abmeldung, OTP-Validierung | Gelb |
| `QUESTION` | Fragenbank-Operationen | Grün |
| `TEST` | Test-Lauf und -Verwaltung | Lila |
| `SUBMISSION` | Abgaben und Bewertung | Orange |
| `STAFF` | Mitarbeiter- und Rechtsverwaltung | Rot |
| `SECURITY` | Sicherheitsereignisse | Rot (dunkel) |

## Datenspeicherung in Metadata

Das `metadata`-Feld ist ein JSON-Objekt, das strukturierte Informationen enthält:

### Standard-Felder
- `pool_name` / `pool_id` - Zugehöriger Fragenpool
- `examinee_name` - Name des Prüflings (bei Tests)
- `username` - Benutzername des Betroffenen
- `session_id` - Django-Session-ID für Nachverfolgung

### Änderungsspezifische Felder
- `changes.before` - Zustand VOR Änderung
- `changes.after` - Zustand NACH Änderung
- `added_*` - Hinzugefügte Elemente
- `removed_*` - Entfernte Elemente
- `old_score` / `new_score` - Score-Änderungen
- `*_count` - Aggregierte Zählungen

## Konfiguration

### Django Settings
```python
# settings.py
AUDIT_LOG_REQUESTS = "all"      # "all" = alle Requests, "changes" = nur Modifikationen
AUDIT_LOG_RETENTION_DAYS = 90   # Tage, bevor alte Einträge gelöscht werden
AUDIT_LOG_MAX_ENTRIES = 1000000 # Maximale Anzahl Einträge in Datenbank
```

### Middleware-Aktivierung
```python
MIDDLEWARE = [
    # ...
    'core.middleware.AuditRequestMiddleware',  # Muss aktiviert sein
    # ...
]
```

## Query-Beispiele für Audits

### Alle Änderungen durch einen Benutzer in den letzten 7 Tagen
```python
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import AuditLog
from datetime import timedelta

user = User.objects.get(username='john')
since = timezone.now() - timedelta(days=7)
logs = AuditLog.objects.filter(
    actor=user,
    created_at__gte=since
).exclude(category='request').order_by('-created_at')
```

### Alle Bewertungs-Aktivitäten (Grading)
```python
logs = AuditLog.objects.filter(
    action__startswith='submission.graded'
).select_related('actor').order_by('-created_at')
```

### Alle Rechtsverwaltungs-Änderungen
```python
logs = AuditLog.objects.filter(
    category='staff',
    action__contains='permission'
).order_by('-created_at')
```

### Alle Zugriffe auf eine bestimmte Abgabe
```python
test_id = 'uuid-here'
logs = AuditLog.objects.filter(
    object_type='test',
    object_id=str(test_id),
).order_by('-created_at')
```

## Sicherheitsmerkmale

1. **Unveränderlichkeit**: Alle Audit-Einträge sind `create_only` - können nie bearbeitet oder gelöscht werden
2. **Nativer Speicher**: Keine separaten Log-Dateien - alles in DB für ACID-Garantien
3. **Automatische Bereinigung**: Alte Einträge werden nach konfigurierbarer Zeit gelöscht
4. **Transaktionale Integrität**: Änderungen und Logs werden atomically mit `transaction.atomic()` gespeichert
5. **IP-Tracking**: IP-Adresse und Browser-Kennung werden automatisch erfasst
6. **Session-Tracking**: Django-Session-ID ermöglicht Nachverfolgung von Benutzer-Sessions

## Verwaltungsoberfläche

Die Audit-Logs können über die Web-UI eingesehen werden:

- **Zugriff**: `/audit-logs/` (mit `can_view_audit_logs`-Berechtigung)
- **Filter**: Nach Kategorie, Benutzer, Aktion, Datum
- **Export**: CSV-Export für externe Analyse (mit `can_export_audit_logs`)
- **Löschen**: Manuelle Löschung mit `can_clear_audit_logs` (wird selbst geloggt!)

## Performance-Hinweise

- Audit-Einträge werden asynchron geschrieben (Middleware)
- Indizes auf `created_at`, `category`, `action`, `actor` für schnelle Filterung
- Mit `settings.AUDIT_LOG_REQUESTS = "changes"` können unnötige GET-Logs reduziert werden
- Tägliche Bereinigung verhindert Tabellenvergrößerung

## Datenschutz

- **Keine Passworte**: Passwörter werden niemals im Log gespeichert
- **Keine POST-Daten**: Request-Body wird nicht erfasst
- **Keine Antworttexte**: Response-Body wird nicht erfasst
- **PII-Minimierung**: Prüfling-Namen werden geloggt, aber nur wenn direkt relevant

## Migration

Die Datenbankschema wurde bereits mit Migrationendatei `0003_alter_question_options_auditlog.py` erstellt. Keine zusätzliche Migration nötig.

Alle neuen Logging-Aufrufe sind rückwärtskompatibel und benötigen keine Schema-Änderungen.

---

**Letztes Update**: 2024-11-08  
**Status**: Produktionsbereit ✅
