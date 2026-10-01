# Berechtigungskatalog

Diese Übersicht beschreibt die Berechtigungen der Police Academy, ihre Voraussetzungen und die technischen Django-Rechte. Rechte werden in Gruppen oder direkt an Mitarbeiter vergeben. Die wirksamen Rechte eines Kontos sind die Vereinigung aus beiden Quellen; dasselbe Recht doppelt zuzuweisen erhöht den Zugriff nicht.

## Keine Dubletten

Ein Django-Recht ist durch Anwendung, Modell und Codename eindeutig, zum Beispiel `core.can_view_pool_3`. Die Datenbank erzwingt diese Eindeutigkeit. Die Rechteansicht listet jede gespeicherte Permission genau einmal.

Ähnlich benannte Rechte können absichtlich verschiedene Geltungsbereiche haben. Ein dynamisches Poolrecht gilt in der Academy-Anwendung nur für den betreffenden Pool. Ein Django-Modellrecht kann stattdessen eine Modellaktion im technischen Django-Admin erlauben. Die Abschnitte im Rechteeditor benennen diese Ebenen getrennt.

Direktrechte und Gruppenrechte werden additiv ausgewertet. Ist ein Recht sowohl direkt als auch über eine Gruppe vergeben, bleibt es effektiv nur einmal erlaubt. Der aktuelle Datenbankabgleich fand keine direkt-und-Gruppen-Überschneidungen.

## Administrator

`is_superuser=True` ist der einzige Administratorstatus. Er umgeht die Academy-Berechtigungsprüfungen und gibt Zugriff auf alle Pools. Der Status wird über den Schalter am Mitarbeiterkonto vergeben, nicht über eine Rechtegruppe. Der eigene Administratorstatus kann nicht entzogen werden.

## Globale Academy-Rechte

Diese Rechte steuern Funktionen der Mitarbeiteroberfläche und werden serverseitig geprüft.

| Codename | Wirkung und Voraussetzung |
| --- | --- |
| `core.can_manage_users` | Mitarbeiterliste sowie Mitarbeiter-Stammdaten und Mitarbeiter-Rechteformular öffnen. Für Änderungen an Gruppen und Einzelrechten ist zusätzlich das passende Grant- oder Revoke-Recht nötig. |
| `core.can_delete_tests` | Abgegebene Tests löschen. Erfordert außerdem das Auswertungsrecht für den Fragenpool des Tests. |
| `core.can_view_audit_logs` | Das Systemprotokoll ansehen. |
| `core.can_clear_audit_logs` | Das Systemprotokoll manuell leeren. Erfordert zusätzlich `can_view_audit_logs`; der Löschvorgang bleibt selbst als neuer Eintrag erhalten. |
| `core.can_grant_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte vergeben. Erfordert `can_manage_users`. Erlaubt nicht, Rechte zu entziehen oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_revoke_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte entziehen. Erfordert `can_manage_users`. Erlaubt nicht, Rechte zu vergeben oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_grant_administrator` | Einer anderen Person den Administratorstatus geben. Erfordert `can_manage_users`; Admin-Status kann nicht über eine Gruppe vergeben werden. |
| `core.can_revoke_administrator` | Einer anderen Person den Administratorstatus entziehen. Erfordert `can_manage_users`; der eigene Status bleibt geschützt. |

Die beiden Nutzerrechte Grant und Revoke sind absichtlich getrennt. Gleiches gilt für Administratorstatus vergeben und entziehen. Nur Administratoren können die Rechte für Logleerung und Rechte-Delegation weitergeben.

## Poolrechte

Für jeden Fragenpool erzeugt die Anwendung vier eigene Rechte. Die Pool-ID im Codename begrenzt das Recht auf genau diesen Pool.

| Muster | Wirkung |
| --- | --- |
| `core.can_view_pool_<id>` | Fragen des Pools in der Fragenbank ansehen. |
| `core.can_edit_pool_<id>` | Fragen dieses Pools anlegen, bearbeiten und löschen. Zusätzlich ist das View-Recht erforderlich. |
| `core.can_generate_test_from_pool_<id>` | Tests ausschließlich aus diesem Pool erstellen. |
| `core.can_view_submissions_pool_<id>` | Abgaben dieses Pools ansehen und bewerten. |

Poolrechte tauchen im Editor als eigener Abschnitt pro Pool auf. Zwei gleichartige Aktionen für unterschiedliche Pools sind keine Dubletten, sondern getrennte Freigaben.

## Django-Modellrechte

Django legt für Modelle standardmäßig die Rechte `add_<model>`, `change_<model>`, `delete_<model>` und `view_<model>` an. Sie beziehen sich auf das technische Datenmodell, nicht automatisch auf die Academy-Oberfläche. Sie sind vor allem für Django-Admin-Ansichten relevant, sofern das Modell dort registriert ist und der Account überhaupt Django-Admin-Zugang hat.

Beispiele sind `core.change_question` für eine Frage oder `auth.add_user` für ein Benutzerkonto. Diese Modellrechte ersetzen keine Poolrechte. `core.can_edit_pool_<id>` steuert die Academy-Fragenoberfläche; ein Django-Modellrecht steuert dagegen die entsprechende technische Admin-Aktion.

Das Audit-Log ist im Django-Admin schreibgeschützt: die `AuditLogAdmin`-Ansicht verweigert Hinzufügen, Ändern und Löschen unabhängig von den Standard-Modellrechten. Fragen, Tests und Abgaben sind für Superuser im Django-Admin registriert. Nicht registrierte Modelle erhalten zwar Django-Standardrechte in der Datenbank, haben dadurch aber keine eigene Admin-Ansicht in dieser Anwendung.

## Sitzungsrechte

Die Rechte `sessions.add_session`, `sessions.change_session`, `sessions.delete_session` und `sessions.view_session` betreffen Zeilen des Modells `django.contrib.sessions.Session`, also gespeicherte Browser-Sitzungen. Sie bedeuten nicht „anmelden dürfen“, legen keine Login-Dauer fest und vergeben keine Academy-Rechte.

Die Anwendung stellt keine Sitzungsverwaltung bereit und registriert das Session-Modell nicht im Django-Admin. Diese Rechte haben deshalb im normalen Academy-Ablauf keine Wirkung. Sitzungsdatensätze können Login-Zustand enthalten; die Rechte sollten nur bei einem konkreten technischen Verwaltungsbedarf vergeben werden.

## Weitere technische Rechte

Django zeigt außerdem Standardrechte für Gruppen und Benutzer (`auth`), Admin-Protokolleinträge (`admin`) und Content-Types (`contenttypes`) an. Sie sind vom Academy-RBAC getrennt und wirken nur in Django-Komponenten, die diese Modellrechte tatsächlich prüfen. Sie ersetzen insbesondere nicht `can_manage_users`, Poolrechte oder die gesonderten Grant-/Revoke-Rechte.

## Log-Aufbewahrung

Das Audit-Log entfernt automatisch Einträge älter als 180 Tage und hält höchstens die 50.000 neuesten Einträge. Die Bereinigung läuft maximal einmal täglich beim ersten normalen Request. Die Grenzen lassen sich mit `AUDIT_LOG_RETENTION_DAYS` und `AUDIT_LOG_MAX_ENTRIES` konfigurieren. Unabhängig davon kann ein ausdrücklich berechtigter Mitarbeiter das Log leeren; der Clear-Vorgang selbst bleibt protokolliert.
