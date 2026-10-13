# Berechtigungskatalog

Diese Übersicht beschreibt die Berechtigungen der Police Academy und ihre Voraussetzungen. Rechte werden in Gruppen oder direkt an Mitarbeiter vergeben. Die wirksamen Rechte eines Kontos sind die Vereinigung aus beiden Quellen; dasselbe Recht doppelt zuzuweisen erhöht den Zugriff nicht.

## Atomare Rechte und Rechteeditor

Jede logische Mitarbeiteraktion wird als eigenes Einzelrecht geführt. Dazu
gehören Lesen, Anlegen, Ändern, einzelnes und mehrfaches Löschen, Import,
Export, Testgenerierung, Bewertung sowie das Vergeben und Entziehen von
Rechten. Poolbezogene Rechte enthalten weiterhin die Pool-ID.

Rechtegruppen und direkte Mitarbeiterrechte werden gleich dargestellt: als
übersichtliche, nach Wirkungsbereich und Pool gruppierte Einzel-Checkboxen,
damit jedes Recht direkt angeklickt und geprüft werden kann. Die serverseitige
Formularvalidierung bleibt maßgeblich.

Die früheren Sammelrechte werden durch die Datenmigration auf passende
Einzelrechte aufgeteilt und anschließend entfernt. Alte Sammelrechte sind
weder auswählbar noch als Berechtigungs-Fallback wirksam.
Bestehende Grant-/Revoke-Zuweisungen bleiben für direkte Mitarbeiterrechte
erhalten; sie werden zusätzlich auf die neuen, getrennten Rechte zum Zuordnen
und Entziehen von Rechtegruppen übertragen.

## Keine Dubletten

Die Datenbank identifiziert jedes Recht eindeutig anhand von Anwendung, Modell und Codename. Der Rechteeditor bietet nur die globalen Academy-Rechte und Poolrechte an, die die Anwendung tatsächlich prüft.

Direktrechte und Gruppenrechte werden additiv ausgewertet. Ist ein Recht sowohl direkt als auch über eine Gruppe vergeben, bleibt es effektiv nur einmal erlaubt. Der aktuelle Datenbankabgleich fand keine direkt-und-Gruppen-Überschneidungen.

## Administrator

`is_superuser=True` ist der einzige Administratorstatus. Er umgeht die Academy-Berechtigungsprüfungen und gibt Zugriff auf alle Pools. Der Status wird über den Schalter am Mitarbeiterkonto vergeben, nicht über eine Rechtegruppe. Der eigene Administratorstatus kann nicht entzogen werden.

## Globale Academy-Rechte

Diese Rechte steuern Funktionen der Mitarbeiteroberfläche und werden serverseitig geprüft.

| Codename | Wirkung und Voraussetzung |
| --- | --- |
| `core.can_view_users` | Mitarbeiterübersicht ansehen. |
| `core.can_create_users` | Mitarbeiterkonto anlegen. |
| `core.can_update_user_username` | Benutzernamen eines Mitarbeiters ändern. |
| `core.can_update_user_first_name` | Vornamen eines Mitarbeiters ändern. |
| `core.can_update_user_last_name` | Nachnamen eines Mitarbeiters ändern. |
| `core.can_activate_users` | Deaktiviertes Mitarbeiterkonto aktivieren. |
| `core.can_deactivate_users` | Mitarbeiterkonto deaktivieren (das eigene Konto bleibt geschützt). |
| `core.can_set_user_passwords` | Neues Passwort für einen Mitarbeiter setzen. |
| `core.can_delete_users` | Mitarbeiterkonten löschen. Eigene Konten und der letzte Administrator sind geschützt. Nur Administratoren dürfen andere Administratoren löschen. Zugehörige Tests bleiben erhalten; der Erstellerverweis wird entfernt. |
| `core.can_view_user_permissions` | Das Mitarbeiter-Rechteformular öffnen und vorhandene Rechte ansehen. |
| `core.can_assign_user_groups` | Einer Person Rechtegruppen zuweisen. |
| `core.can_unassign_user_groups` | Einer Person Rechtegruppen entziehen. |
| `core.can_view_permission_groups` | Rechtegruppenübersicht ansehen. |
| `core.can_create_permission_groups` | Rechtegruppe anlegen. |
| `core.can_rename_permission_groups` | Rechtegruppe umbenennen. |
| `core.can_update_permission_group_priority` | Sortierzahl (Priorität) einer Rechtegruppe ändern. |
| `core.can_delete_permission_groups` | Rechtegruppe löschen. |
| `core.can_view_tool_settings` | Tool-Einstellungen anzeigen. |
| `core.can_update_site_name` | Seitentitel ändern. |
| `core.can_update_department_name` | Department-Namen ändern. |
| `core.can_update_site_icon` | Site-Icon ändern. |
| `core.can_update_login_heading` | Überschrift der Anmeldeseite ändern. |
| `core.can_update_login_text` | Text der Anmeldeseite ändern. |
| `core.can_update_privacy_policy` | Datenschutzerklärung ändern. |
| `core.can_update_imprint` | Impressum ändern. |
| `core.can_delete_tests` | Abgegebene Tests löschen. Erfordert außerdem das Auswertungsrecht für den Fragenpool des Tests. |
| `core.can_view_audit_logs` | Das Systemprotokoll ansehen. |
| `core.can_export_audit_logs` | Gefiltertes Systemprotokoll als CSV exportieren. |
| `core.can_clear_audit_logs` | Das Systemprotokoll manuell leeren. Der Löschvorgang bleibt selbst als neuer Eintrag erhalten. |
| `core.can_grant_user_permissions` | Direkte Nutzerrechte vergeben. Erlaubt nicht, Rechte zu entziehen oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_revoke_user_permissions` | Direkte Nutzerrechte entziehen. Erlaubt nicht, Rechte zu vergeben oder delegierbare Sicherheitsrechte weiterzugeben. |
| `core.can_grant_group_permissions` | Einzelne Rechte an Rechtegruppen vergeben. |
| `core.can_revoke_group_permissions` | Einzelne Rechte aus Rechtegruppen entziehen. |
| `core.can_grant_administrator` | Einer anderen Person den Administratorstatus geben. Der Status kann nicht über eine Gruppe vergeben werden. |
| `core.can_revoke_administrator` | Einer anderen Person den Administratorstatus entziehen. Der eigene Status bleibt geschützt. |
| `core.can_view_question_pools` | Fragenpoolverwaltung ansehen. |
| `core.can_create_question_pools` | Fragenpool anlegen. |
| `core.can_update_pool_name` | Fragenpool umbenennen. |
| `core.can_update_pool_description` | Beschreibung eines Fragenpools ändern. |
| `core.can_update_pool_question_count` | Fragenanzahl pro Test ändern. |
| `core.can_update_pool_pass_percentage` | Bestehensgrenze ändern. |
| `core.can_update_pool_min_time_limit` | Minimales Zeitlimit ändern. |
| `core.can_update_pool_max_time_limit` | Maximales Zeitlimit ändern. |
| `core.can_update_pool_start_info_text` | Infotext vor dem Teststart ändern. |
| `core.can_update_pool_start_confirmations` | Startbestätigungen ändern. |
| `core.can_delete_question_pools` | Fragenpool löschen, sofern die Anwendung dies zulässt. |

Anzeigen, Anlegen, Ändern und Löschen sind getrennte Rechte. Beim Bearbeiten
eines Mitarbeiters, einer Rechtegruppe oder eines Pools wird jedes Feld nur mit
seinem eigenen Recht änderbar; Felder ohne Recht sind gesperrt und werden vom
Server ignoriert. Pool-Aktionen wie Export, Import, Ändern und Löschen prüfen im
Backend nur ihr eigenes Recht. Die Fragenbank (Schaltflächen) erreicht man
dennoch nur mit dem Ansichtsrecht des Pools. Gleiches gilt
für Gruppenmitgliedschaften, direkte Nutzerrechte, Gruppenrechte und
Administratorstatus: Vergeben und Entziehen sind jeweils unabhängig.

## Poolrechte

Für jeden Fragenpool erzeugt die Anwendung dreizehn eigene Rechte. Die Pool-ID im
Codename begrenzt das Recht auf genau diesen Pool.

| Muster | Wirkung |
| --- | --- |
| `core.can_view_pool_<id>` | Fragen des Pools in der Fragenbank ansehen. |
| `core.can_create_question_pool_<id>` | Neue Fragen ausschließlich in diesem Pool anlegen. |
| `core.can_update_question_pool_<id>` | Bestehende Fragen dieses Pools ändern. |
| `core.can_import_questions_pool_<id>` | Fragen in diesen Pool importieren. |
| `core.can_export_questions_pool_<id>` | Fragen aus diesem Pool exportieren. |
| `core.can_generate_test_from_pool_<id>` | Tests ausschließlich aus diesem Pool erstellen. |
| `core.can_view_submissions_pool_<id>` | Abgaben dieses Pools ansehen. |
| `core.can_grade_submissions_pool_<id>` | Punkte in Abgaben dieses Pools speichern. |
| `core.can_delete_single_question_pool_<id>` | Genau eine Frage dieses Pools löschen. |
| `core.can_bulk_delete_questions_pool_<id>` | Mehrere ausgewählte Fragen dieses Pools gemeinsam löschen. |
| `core.can_pin_questions_pool_<id>` | Fragen dieses Pools verankern oder die Verankerung lösen. |
| `core.can_edit_answer_key_pool_<id>` | Musterlösung von Fragen dieses Pools ändern. |
| `core.can_rename_examinee_pool_<id>` | Prüflingsnamen in der Auswertung ändern. Zusätzlich ist das Auswertungsrecht für diesen Pool erforderlich. |

Poolrechte tauchen im Editor als eigener Abschnitt pro Pool auf. Zwei gleichartige Aktionen für unterschiedliche Pools sind keine Dubletten, sondern getrennte Freigaben. Die technischen Django-Modellrechte sind für die eigene Mitarbeiteroberfläche nicht relevant und werden nicht zur Vergabe angeboten. Das technische Django-Admin ist deaktiviert; Django-Authentifizierung, Gruppen, Berechtigungen, Sessions und Content-Types bleiben als interne Grundlagen der Anwendung bestehen.

## Sortierung

Jede Rechtegruppe hat eine positive Sortierzahl. Die Gruppenübersicht sortiert aufsteigend nach dieser Zahl; bei gleicher Zahl entscheidet der Gruppenname alphabetisch. Bestehende Gruppen erhalten bei der Migration zunächst fortlaufende Sortierzahlen in alphabetischer Reihenfolge.

## Datenschutzerklärung und Tool-Einstellungen

Mitarbeiter benötigen `core.can_view_tool_settings`, um die Seite **Tool-Einstellungen** zu öffnen. Jede Änderung wird separat durch das passende Recht für Seitentitel, Department-Namen, Site-Icon, Loginüberschrift, Logintext, Datenschutzerklärung oder Impressum geschützt. Ist eine Erklärung hinterlegt, müssen angemeldete Mitarbeiter ihre aktuelle Textfassung bestätigen, bevor sie andere Mitarbeiterfunktionen verwenden. Eine Textänderung erfordert eine erneute Bestätigung; gespeichert wird ein Hash der bestätigten Fassung.

## Log-Aufbewahrung

Das Audit-Log entfernt automatisch Einträge älter als 180 Tage und hält höchstens die 50.000 neuesten Einträge. Die Bereinigung läuft maximal einmal täglich beim ersten normalen Request. Die Grenzen lassen sich mit `AUDIT_LOG_RETENTION_DAYS` und `AUDIT_LOG_MAX_ENTRIES` konfigurieren. Unabhängig davon kann ein ausdrücklich berechtigter Mitarbeiter das Log leeren; der Clear-Vorgang selbst bleibt protokolliert.
