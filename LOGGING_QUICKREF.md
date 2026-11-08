# ⚡ Logging System - Quick Reference

## 🚀 Schnellstart

### Zugriff auf Audit-Logs
```
URL: /audit-logs/
Berechtigung: can_view_audit_logs
Filter: Kategorie, Benutzer, Aktion, Datum
Export: CSV möglich mit can_export_audit_logs
```

### Beispiel: Wer hat Test #12345 bewertet?
```python
# Django Shell
from core.models import AuditLog
logs = AuditLog.objects.filter(
    object_id='12345',
    action__contains='graded'
).order_by('created_at')

for log in logs:
    print(f"{log.actor} - {log.created_at}: {log.description}")
```

---

## 📍 Alle Logging-Punkte

### Test & Abgaben (7)
| Action | Wann | Details |
|--------|------|---------|
| `test.otp.accepted` | OTP korrekt | Test-ID |
| `test.otp.rejected` | OTP falsch | Test-ID |
| `test.otp.locked` | Zu viele Versuche | Test-ID |
| `test.questions.viewed` | Fragen angezeigt | Pool-Name, Session-ID |
| `test.examinee_identified` | Name eingegeben | Pool-Name |
| `test.started` | Test gestartet | Zeit-Limit |
| `tests.running_list.viewed` | Laufende Tests angezeigt | Sichtbare Pools |
| `submissions.list.viewed` | Abgabe-Liste angezeigt | Filter, Pool |
| `submission.viewed` | Abgabe angezeigt | Pool, Prüfling-Name |
| `submission.graded` | Antwort bewertet | Alt-Score, Neu-Score, Frage |
| `submission.graded_batch` | Session abgeschlossen | Anz. Änderungen, Zusammenfassung |
| `test.deleted` | Test gelöscht | Prüfling-Name |

### Fragen (3)
| Action | Wann | Details |
|--------|------|---------|
| `questions.list.viewed` | Fragenbank geöffnet | Pool, Filter |
| `question.created` | Frage angelegt | Text, Typ, Punkte |
| `question.updated` | Frage bearbeitet | Geänderte Felder |
| `question.deleted` | Frage gelöscht | Frage-ID |
| `questions.exported` | Export gestartet | Anzahl, Pool |
| `question.csv.imported` | Import abgeschlossen | Importiert, Duplikate, Fehler |

### Rechte (2)
| Action | Wann | Details |
|--------|------|---------|
| `permission_group.created` | Gruppe angelegt | Gruppe-Name, Rechte |
| `permission_group.updated` | Gruppe bearbeitet | Hinzugefügt, Entfernt, Mitglieder |
| `permission_group.deleted` | Gruppe gelöscht | Gruppe-Name |
| `staff.permissions.updated` | Benutzer-Rechte geändert | Gruppen hinzugefügt/entfernt |

### Auth (5)
| Action | Wann | Details |
|--------|------|---------|
| `auth.login` | Anmeldung erfolgreich | IP-Adresse |
| `auth.failed_login` | Anmeldung fehlgeschlagen | Versuchter Name, IP |
| `auth.logout` | Abmeldung | Session-Dauer |
| `account.password_changed` | Passwort geändert | - |
| `account.profile_updated` | Profil bearbeitet | Geänderte Felder |

### HTTP (Auto via Middleware)
| Action | Wann | Details |
|--------|------|---------|
| `http.get` / `http.post` | Jede HTTP-Anfrage | Status, Route, Dauer |

**Hinweis**: HTTP-Logs können mit `AUDIT_LOG_REQUESTS = "changes"` auf nur Modifikationen begrenzt werden.

---

## 🔍 Häufige Abfragen

### 1. Was hat ein Mitarbeiter heute getan?
```python
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import AuditLog

user = User.objects.get(username='john')
today = timezone.now().date()

logs = AuditLog.objects.filter(
    actor=user,
    created_at__date=today
).order_by('-created_at')

for log in logs:
    print(f"{log.created_at:%H:%M:%S} - {log.action}: {log.description}")
```

### 2. Wer hat welchen Test bewertet?
```python
from core.models import AuditLog

test_id = 'uuid-here'
grading_logs = AuditLog.objects.filter(
    object_id=test_id,
    action__startswith='submission.graded'
).select_related('actor')

for log in grading_logs:
    print(f"{log.actor.username} bewertet: {log.metadata}")
```

### 3. Zeige Score-Änderungen für einen Test
```python
from core.models import AuditLog

logs = AuditLog.objects.filter(
    object_id='test-id',
    action='submission.graded'
).order_by('created_at')

for log in logs:
    metadata = log.metadata
    old_score = metadata.get('old_score')
    new_score = metadata.get('new_score')
    question = metadata.get('question_position')
    print(f"Frage {question}: {old_score} → {new_score}")
```

### 4. Verdächtige Aktivitäten (Recht-Eskalationen)
```python
from core.models import AuditLog

suspicious = AuditLog.objects.filter(
    action='staff.permissions.updated',
    category='staff'
)

for log in suspicious:
    added = log.metadata.get('added_groups', [])
    if 'admin' in added or 'administrator' in added:
        print(f"⚠️ {log.actor} wurde Admin: {log.created_at}")
```

### 5. Alle Änderungen an einer Gruppe
```python
from core.models import AuditLog

group_id = 5
logs = AuditLog.objects.filter(
    object_type='group',
    object_id=str(group_id),
    category='staff'
).order_by('-created_at')

for log in logs:
    print(f"{log.created_at} - {log.action}")
    print(f"  Hinzugefügt: {log.metadata.get('added_permissions', [])}")
    print(f"  Entfernt: {log.metadata.get('removed_permissions', [])}")
```

---

## 🎯 Typische Audit-Szenarien

### Szenario 1: Test-Bewertung prüfen
```
Problem: "Wie wurde Test #12345 bewertet?"

Lösung:
1. Gehe zu /audit-logs/
2. Filtere nach Objekt-ID: 12345
3. Suche nach "submission.graded"
4. Sehe alle Score-Änderungen mit Vorher-Nachher

Ergebnis:
├─ John: Frage 1: 3 → 5 (14:32:15)
├─ John: Frage 2: 2 → 4 (14:32:20)
└─ John: Frage 3: 1 → 3 (14:32:25)
  
Alle Änderungen durch EINEN Bewerter = OK
```

### Szenario 2: Rechteveränderung nachvollziehen
```
Problem: "Wann und wie wurde Moderator zur Admin?"

Lösung:
1. Gehe zu /audit-logs/
2. Filtere nach Benutzer: "john"
3. Filtere nach Aktion: "permissions.updated"

Ergebnis:
└─ 2024-11-08 14:35:40 | staff.permissions.updated
   ├─ Vorher: [Moderator]
   ├─ Nachher: [Admin]
   └─ "Versuch zur Selbst-Eskalation BLOCKIERT ❌"
```

### Szenario 3: Alle Zugriffe auf sensible Daten
```
Problem: "Wer hatte Zugriff auf die Abgaben von Test X?"

Lösung via CLI:
```python
from core.models import AuditLog

test_id = 'test-uuid'
viewers = AuditLog.objects.filter(
    object_id=test_id,
    action__in=['submission.viewed', 'test.questions.viewed']
).values('actor__username', 'created_at').distinct('actor')

for entry in viewers:
    print(f"{entry['actor__username']} at {entry['created_at']}")
```

---

## 🔐 Sicherheits-Checklisten

### Täglich
- [ ] Keine unerwarteten Login-Fehler mehrfach hintereinander
- [ ] Keine verdächtigen Recht-Änderungen (Admin-Vergabe)

### Wöchentlich
- [ ] Welche Mitarbeiter haben wie viele Tests bewertet
- [ ] Waren alle Bewertungsänderungen begründet
- [ ] Keine unerlaubten Fragenbank-Zugriffe

### Monatlich
- [ ] Vollständige Audit-Trail für kritische Mitarbeiter
- [ ] Änderungen an Rechtegruppen überprüfen
- [ ] Verdächtige CSV-Importe identifizieren

---

## 🛠️ Admin-Befehle

### Audit-Log anzeigen
```bash
python manage.py shell
```
```python
from core.models import AuditLog
from django.utils import timezone
from datetime import timedelta

# Letzte 100 Einträge
AuditLog.objects.all().order_by('-created_at')[:100]

# Heute
today = timezone.now().date()
AuditLog.objects.filter(created_at__date=today)

# Letzte 7 Tage nur Änderungen
since = timezone.now() - timedelta(days=7)
AuditLog.objects.exclude(
    category='request'
).filter(
    created_at__gte=since
)
```

### Audit-Log exportieren
```bash
# Web-UI unter /audit-logs/export/
# Oder via Python:
```python
from core.models import AuditLog
import csv

logs = AuditLog.objects.all().order_by('-created_at')
with open('audit_export.csv', 'w') as f:
    writer = csv.writer(f, delimiter=';')
    writer.writerow(['Zeitpunkt', 'Benutzer', 'Aktion', 'Objekt', 'Details'])
    for log in logs:
        writer.writerow([
            log.created_at.isoformat(),
            log.actor.username if log.actor else 'System',
            log.action,
            f"{log.object_type}#{log.object_id}",
            log.description,
        ])
```

### Statistiken anzeigen
```python
from core.models import AuditLog
from django.db.models import Count

# Logs pro Kategorie
AuditLog.objects.values('category').annotate(count=Count('id')).order_by('-count')

# Top-Benutzer
AuditLog.objects.filter(
    actor__isnull=False
).values('actor__username').annotate(
    count=Count('id')
).order_by('-count')[:10]

# Top-Aktionen
AuditLog.objects.values('action').annotate(
    count=Count('id')
).order_by('-count')[:10]
```

---

## 📊 Performance-Tipps

### Schnellere Abfragen
```python
# ❌ Langsam - N+1 Problem
for log in AuditLog.objects.all():
    print(log.actor.username)

# ✅ Schnell - prefetch
for log in AuditLog.objects.select_related('actor'):
    print(log.actor.username)

# ✅ Noch schneller - mit Filter
logs = AuditLog.objects.filter(
    created_at__date='2024-11-08'
).select_related('actor').order_by('-created_at')
```

### Indizierte Felder nutzen
- `created_at` - Immer filtern nach Datum!
- `actor` - Für Benutzer-Filter
- `category` - Für Kategorie-Filter
- `action` - Für Aktion-Filter
- `object_id` - Für Objekt-Filter

### Limits setzen
```python
# ❌ Kann zu viel RAM brauchen
all_logs = list(AuditLog.objects.all())

# ✅ Besser - mit Iterator
for log in AuditLog.objects.all().iterator(chunk_size=1000):
    # Verarbeite log

# ✅ Auch gut - begrenzen
recent_logs = AuditLog.objects.all()[:1000]
```

---

## 📞 Support / FAQs

**F: Warum sehe ich einen Zugriff, den ich nicht durchgeführt habe?**
A: HTTP-Middleware protokolliert auch Fehler und Redirects. Prüfe den HTTP-Status-Code.

**F: Kann ich Logs löschen?**
A: Ja, mit `can_clear_audit_logs`. Dies wird selbst geloggt. Nur Administratoren sollten dies dürfen.

**F: Wie lange werden Logs aufbewahrt?**
A: Konfigurierbar via `AUDIT_LOG_RETENTION_DAYS` (Standard: 90 Tage).

**F: Sind Logs verschlüsselt?**
A: Nein, aber SQL-Datenbank-Verschlüsselung können Sie konfigurieren.

**F: Können Logs verfälscht werden?**
A: Nein - sie sind Write-Once (INSERT only), nie UPDATE/DELETE.

**F: Kann ich Logs suchen?**
A: Ja - /audit-logs/ bietet Suche nach Benutzer, Aktion, Datum.

---

## 📚 Weitere Ressourcen

- **Vollständige Dokumentation**: `LOGGING_ENHANCEMENTS.md`
- **Visuelle Übersicht**: `LOGGING_VISUAL_GUIDE.md`
- **Implementierungs-Details**: Siehe Code-Kommentare in `core/audit.py`

---

**Letzte Aktualisierung**: 2024-11-08  
**System Status**: ✅ Operativ
