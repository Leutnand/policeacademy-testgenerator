# Berechtigungskatalog

Diese Übersicht beschreibt die Berechtigungen der Police Academy und ihre Voraussetzungen. Rechte werden in Gruppen oder direkt an Mitarbeiter vergeben. Die wirksamen Rechte eines Kontos sind die Vereinigung aus beiden Quellen; dasselbe Recht doppelt zuzuweisen erhöht den Zugriff nicht.

## Keine Dubletten

Die Datenbank identifiziert jedes Recht eindeutig anhand von Anwendung, Modell und Codename. Der Rechteeditor bietet nur die globalen Academy-Rechte und Poolrechte an, die die Anwendung tatsächlich prüft.

Direktrechte und Gruppenrechte werden additiv ausgewertet. Ist ein Recht sowohl direkt als auch über eine Gruppe vergeben, bleibt es effektiv nur einmal erlaubt. Der aktuelle Datenbankabgleich fand keine direkt-und-Gruppen-Überschneidungen.

## Administrator

`is_superuser=True` ist der einzige Administratorstatus. Er umgeht die Academy-Berechtigungsprüfungen und gibt Zugriff auf alle Pools. Der Status wird über den Schalter am Mitarbeiterkonto vergeben, nicht über eine Rechtegruppe. Der eigene Administratorstatus kann nicht entzogen werden.

## Globale Academy-Rechte

Diese Rechte steuern Funktionen der Mitarbeiteroberfläche und werden serverseitig geprüft.

| Codename | Wirkung und Voraussetzung |
| --- | --- |
| `core.can_manage_users` | Mitarbeiterliste sowie Mitarbeiter-Stammdaten und Mitarbeiter-Rechteformular öffnen. Für Änderungen an Gruppen und Einzelrechten ist zusätzlich das passende Grant- oder Revoke-Recht nötig. |
| `core.can_delete_users` | Mitarbeiterkonten löschen; zusätzlich ist `can_manage_users` erforderlich. Eigene Konten und der letzte Administrator sind geschützt. Nur Administratoren dürfen andere Administratoren löschen. Zugehörige Tests bleiben erhalten; der Erstellerverweis wird entfernt. |
| `core.can_manage_tool_settings` | Branding, Logintexte, Site-Icon, Testgrenzen, Datenschutzerklärung und Impressum unter Tool-Einstellungen bearbeiten. |
| `core.can_delete_tests` | Abgegebene Tests löschen. Erfordert außerdem das Auswertungsrecht für den Fragenpool des Tests. |
| `core.can_view_audit_logs` | Das Systemprotokoll ansehen. |
| `core.can_clear_audit_logs` | Das Systemprotokoll manuell leeren. Erfordert zusätzlich `can_view_audit_logs`; der Löschvorgang bleibt selbst als neuer Eintrag erhalten. |
| `core.can_grant_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte vergeben. Erfordert `can_manage_users`. Erlaubt nicht, Rechte zu entziehen oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_revoke_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte entziehen. Erfordert `can_manage_users`. Erlaubt nicht, Rechte zu vergeben oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_grant_administrator` | Einer anderen Person den Administratorstatus geben. Erfordert `can_manage_users`; Admin-Status kann nicht über eine Gruppe vergeben werden. |
| `core.can_revoke_administrator` | Einer anderen Person den Administratorstatus entziehen. Erfordert `can_manage_users`; der eigene Status bleibt geschützt. |

Die Nutzerrechte Grant und Revoke sind absichtlich getrennt. Gleiches gilt für Administratorstatus vergeben und entziehen. Das Löschrecht für Mitarbeiterkonten kann nur ein Administrator delegieren. Nur Administratoren können außerdem die Rechte für Logleerung, Rechte-Delegation und Kontolöschung weitergeben.

## Poolrechte

Für jeden Fragenpool erzeugt die Anwendung fünf eigene Rechte. Die Pool-ID im Codename begrenzt das Recht auf genau diesen Pool.

| Muster | Wirkung |
| --- | --- |
| `core.can_view_pool_<id>` | Fragen des Pools in der Fragenbank ansehen. |
| `core.can_edit_pool_<id>` | Fragen dieses Pools anlegen, bearbeiten und löschen. Zusätzlich ist das View-Recht erforderlich. |
| `core.can_import_export_pool_<id>` | CSV-Fragen dieses Pools importieren und exportieren. Zusätzlich ist `core.can_view_pool_<id>` erforderlich. Der Excel-freundliche Export enthält interne Lösungsschlüssel. |
| `core.can_generate_test_from_pool_<id>` | Tests ausschließlich aus diesem Pool erstellen. |
| `core.can_view_submissions_pool_<id>` | Abgaben dieses Pools ansehen und bewerten. |

Poolrechte tauchen im Editor als eigener Abschnitt pro Pool auf. Zwei gleichartige Aktionen für unterschiedliche Pools sind keine Dubletten, sondern getrennte Freigaben. Die technischen Django-Modellrechte sind für die eigene Mitarbeiteroberfläche nicht relevant und werden nicht zur Vergabe angeboten. Das technische Django-Admin ist deaktiviert; Django-Authentifizierung, Gruppen, Berechtigungen, Sessions und Content-Types bleiben als interne Grundlagen der Anwendung bestehen.

## Sortierung

Jede Rechtegruppe hat eine positive Sortierzahl. Die Gruppenübersicht sortiert aufsteigend nach dieser Zahl; bei gleicher Zahl entscheidet der Gruppenname alphabetisch. Bestehende Gruppen erhalten bei der Migration zunächst fortlaufende Sortierzahlen in alphabetischer Reihenfolge.

## Datenschutzerklärung und Tool-Einstellungen

Mitarbeiter mit `core.can_manage_tool_settings` können die Datenschutzerklärung und das Impressum sowie Namen, Logintexte, Site-Icon und globale Fragenzahlgrenzen unter **Tool-Einstellungen** verwalten. Ist eine Erklärung hinterlegt, müssen angemeldete Mitarbeiter ihre aktuelle Textfassung bestätigen, bevor sie andere Mitarbeiterfunktionen verwenden. Eine Textänderung erfordert eine erneute Bestätigung; gespeichert wird ein Hash der bestätigten Fassung.

## Log-Aufbewahrung

Das Audit-Log entfernt automatisch Einträge älter als 180 Tage und hält höchstens die 50.000 neuesten Einträge. Die Bereinigung läuft maximal einmal täglich beim ersten normalen Request. Die Grenzen lassen sich mit `AUDIT_LOG_RETENTION_DAYS` und `AUDIT_LOG_MAX_ENTRIES` konfigurieren. Unabhängig davon kann ein ausdrücklich berechtigter Mitarbeiter das Log leeren; der Clear-Vorgang selbst bleibt protokolliert.
