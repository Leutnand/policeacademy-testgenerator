# Police Academy Test Generator

Der Police Academy Test Generator ist ein lokales Django-Projekt für die Prüfungsverwaltung einer GTA-Roleplay-Police-Academy. Er bietet einen zentralen Fragenkatalog, zufällig zusammengestellte Prüfungen mit Einmalzugang, automatisierte Basisbewertung, manuelle Punktkorrektur und die Verwaltung von Academy-Mitarbeiterrechten. Prüflinge benötigen kein Konto. Die Oberfläche verwendet eine klassische Navy-Gold-Farbwelt.

## Funktionen und Architektur

- `testgenerator/`: Django-Einstellungen und ASGI-/WSGI-Einstiegspunkte.
- `core/models.py`: Fragen, Testläufe, persistierte Testfragen und Abgaben.
- `core/views/`: HTTP-Endpunkte, nach Bereichen aufgeteilt (`account`, `rights`, `questions`, `tests_flow`, `users`, `audit`, gemeinsame Helfer in `common`).
- `core/tests/`: Tests, nach Fachbereichen in mehrere Module aufgeteilt.
- Tool-Einstellungen: konfigurierbarer Seitentitel, Department-Name, Site-Icon, Logintext, Testgrenzen und Rechtstexte.
- `core/services.py`: Testauswahl sowie automatische Bewertung.
- `core/permissions.py`: Zuordnung der Fachrechte zu Djangos Berechtigungssystem.
- `templates/`: Mitarbeiter-Dashboard, Formulare und prüflingsseitige Seiten.
- `static/`: responsives CSS (aufgeteilt in `app-*.css` und `academy-*.css`, Ladereihenfolge siehe `templates/base.html`) und Theme-/Kopieraktionen.

Die Fragenbank unterstützt Single Choice, Multiple Choice, Kurzantwort und Freitext. Antwortmöglichkeiten werden im Formular als einzelne Zeilen angelegt; das interne JSON-Speicherformat wird nicht von Mitarbeitenden eingegeben. Bei Kurzantworten und Freitext blendet das Formular den Optionsbereich aus. Für Kurzantworten wird die erwartete Antwort zur automatischen Prüfung hinterlegt, für Freitext eine interne Musterlösung zur Korrektur.

## Prüfungstypen und Fragepools

Fragen werden einem benannten Fragenpool zugeordnet, zum Beispiel **Einstellungstest** oder **Sergeant-Test**. Die Poolverwaltung ist über **Pools verwalten** in der Fragenbank erreichbar. Dort lassen sich weitere Typen anlegen und umbenennen. Ein Pool mit Fragen oder Testläufen kann nicht gelöscht werden; zuerst muss sein Inhalt anderweitig verwaltet werden. Die Fragenbank unterstützt Suche im Fragetext, Fragetyp- und Verankerungsfilter sowie Seiten mit jeweils 50 Fragen.

Bei der Testgenerierung muss zuerst der Prüfungstyp gewählt werden. Alle verankerten Fragen und die zufällige Ergänzung kommen ausschließlich aus diesem Pool. Auch der erzeugte Test speichert den verwendeten Pool; er erscheint in der Ergebnisübersicht und Detailauswertung. Bestehende Fragen und Testläufe werden bei der Migration dem initialen Pool **Einstellungstest** zugewiesen.

Administratoren können unter **Einstellungen** globale Mindest- und Höchstzahlen für Fragen eines erzeugten Tests festlegen. Die Obergrenze kann die tatsächliche Größe des ausgewählten Pools nicht überschreiten.

Bei einer Auswahlfrage werden pro Zeile Antworttext und Korrekt-Markierung gepflegt. Single Choice verlangt genau eine richtige Antwort, Multiple Choice mindestens eine richtige Antwort. Im Datensatz sieht die interne Darstellung beispielsweise so aus:

Fragen lassen sich je Fragenpool als CSV exportieren oder ergänzend importieren. Die Excel-freundliche Datei verwendet UTF-8 mit BOM und in deutscher Excel-Umgebung übliche Semikolon-Trennzeichen. Sie enthält `text`, `question_type`, `points`, `answer_key`, `is_pinned` und `options_json`; Antwortoptionen werden als JSON in einer CSV-Zelle serialisiert. Der Import erkennt sowohl dieses Semikolonformat als auch ältere komma-getrennte Dateien. Er akzeptiert UTF-8-Dateien bis 5 MB und 5.000 Zeilen, prüft die gesamte Datei und speichert bei Fehlern keine Teilmenge. Identische Fragen im selben Fragenpool werden anhand von Fragetext, Typ, Punkten, Musterlösung, Verankerung und Antwortoptionen übersprungen; unterschiedliche Einstellungen bleiben importierbar. Bestehende Fragen werden weder verändert noch gelöscht. Für Export und Import sind sowohl das Ansichtsrecht als auch das separate Import-/Exportrecht des jeweiligen Pools erforderlich, da der Export interne Lösungsschlüssel enthält.

```json
[
  {"text": "Antwort A", "is_correct": true},
  {"text": "Antwort B", "is_correct": false}
]
```

Single Choice verlangt genau eine richtige Option. Bei Multiple Choice wird die komplette Auswahl exakt mit der Lösungsmenge verglichen. Kurzantworten werden durch Whitespace-Normalisierung und Groß-/Kleinschreibungsignorierung verglichen; alternative Schreibweisen können derzeit nicht konfiguriert werden. Freitextantworten bleiben zur manuellen Korrektur offen.

## Installation und Start

Voraussetzung ist Python 3.11 oder neuer. In PowerShell im Projektverzeichnis:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Danach die Anwendung unter <http://127.0.0.1:8000/> öffnen. Die mit `createsuperuser` angelegte Person kann sich in der Mitarbeiteroberfläche anmelden und erhält durch Django-Superuser-Regeln Zugriff. Die Anwendung verwaltet Fragen, Tests, Mitarbeitende und Rechtegruppen über ihre eigene Oberfläche; das technische Django-Admin ist deaktiviert.

Die Datenbankstruktur und Permission-Metadaten werden mit `python manage.py migrate` angelegt. Dynamische Rechte werden für jeden bestehenden und neu angelegten Pool synchronisiert. Ein Django-Superuser ist die einzige Administratorrolle; weitere Gruppen werden nach Bedarf erstellt.

## Tool-Einstellungen und Datenschutz

Mitarbeiter mit dem Recht `can_manage_tool_settings` öffnen über die Navigation **Einstellungen** die Tool-Einstellungen. Dort können sie Seitentitel, Department-Name, Favicon/Site-Icon (PNG oder ICO bis 1 MB), Mindest-/Höchstzahl der Testfragen und die sichtbaren Texte der Loginseite pflegen. Das Icon und die Rechtstexte werden in der Datenbank beziehungsweise im Media-Speicher gespeichert; Docker verwendet dafür das persistente Volume `media_data`.

Auf derselben Seite werden Datenschutzerklärung und Impressum hinterlegt. Der Footer verlinkt auf **Impressum / DSGVO**; dort ist auch die Datenschutzerklärung erreichbar. Sobald eine Datenschutzerklärung konfiguriert ist, muss jedes Mitarbeiterkonto ihre aktuelle Fassung bestätigen, bevor es andere Mitarbeiterfunktionen nutzen kann. Änderungen am Erklärungstext lösen eine erneute Bestätigung aus. Für die Bestätigung wird ein Hash des Textes gespeichert, nicht der Text im Mitarbeiterprofil. Die Anwendung liefert keine vorgefertigte Rechtsberatung; die zuständige Stelle muss die tatsächlichen, rechtlich geprüften Inhalte eintragen.

## Rechtekonzept

Die ausführliche Matrix der globalen Academy- und Poolrechte steht in [docs/berechtigungen.md](docs/berechtigungen.md).

Das RBAC verwendet Djangos `User`, `Group` und `Permission`. Berechtigungen werden serverseitig an jedem Endpunkt geprüft; dieselben Rechte steuern Navigation, Poolauswahl und Aktionsbuttons.

**Administrator**

`is_superuser=True` ist die einzige Administratorrolle und gewährt uneingeschränkten Zugriff. Die frühere Gruppe **Administrator** wird per Migration in diesen Status überführt und anschließend entfernt. Nur Administratoren verwalten Rechtegruppen. Mitarbeiter mit `can_manage_users` und dem passenden Grant-/Revoke-Recht dürfen gewöhnliche Gruppenmitgliedschaften und Rechte zuweisen; sicherheitskritische Rechte bleiben Administratoren vorbehalten. Die festen Gruppen „Fragen-Editor“, „Test-Manager“ und „Korrektor“ werden entfernt; neue Rollen werden ausschließlich über den Gruppenmanager erstellt.

**Globale Berechtigungen**

| Permission | Zugriff |
| --- | --- |
| `core.can_manage_users` | Mitarbeiterkonten verwalten und Mitarbeiter-Rechteformular öffnen |
| `core.can_delete_users` | Mitarbeiterkonten löschen; benötigt zusätzlich `can_manage_users`. Das eigene Konto und der letzte Administrator sind geschützt; Administratoren können andere Administratoren löschen. Tests bleiben erhalten und verlieren nur die Zuordnung zum gelöschten Ersteller. |
| `core.can_delete_tests` | Abgegebene Tests löschen, zusätzlich zum Pool-Auswertungsrecht |
| `core.can_view_audit_logs` | Systemprotokoll einsehen |
| `core.can_clear_audit_logs` | Alle Audit-Einträge löschen; erfordert zusätzlich `can_view_audit_logs`, der Löschvorgang bleibt selbst protokolliert |
| `core.can_grant_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte vergeben; zusätzlich ist `can_manage_users` erforderlich. Sicherheitskritische Rechte einschließlich `can_delete_users` bleiben Administratoren vorbehalten. |
| `core.can_revoke_user_permissions` | Gruppenmitgliedschaften und direkte Nutzerrechte entziehen; zusätzlich ist `can_manage_users` erforderlich. Sicherheitskritische Rechte einschließlich `can_delete_users` bleiben Administratoren vorbehalten. |
| `core.can_grant_administrator` | Einer anderen Person den Administratorstatus geben; zusätzlich ist `can_manage_users` erforderlich |
| `core.can_revoke_administrator` | Einer anderen Person den Administratorstatus entziehen; zusätzlich ist `can_manage_users` erforderlich |

Technische Django-Modellrechte und Admin-Protokollrechte werden nicht im Rechteeditor angeboten. Das technische Django-Admin ist deaktiviert; Anmeldung, Sessions und das interne Berechtigungsmodell bleiben notwendige Bestandteile der Anwendung.

**Dynamische Poolberechtigungen**

Bei jedem Fragenpool erzeugt das System fünf Permissions mit dem Poolschlüssel im Codename, beispielsweise `core.can_view_pool_12`, `core.can_edit_pool_12`, `core.can_import_export_pool_12`, `core.can_generate_test_from_pool_12` und `core.can_view_submissions_pool_12`. Sie werden nach Fragenpool gruppiert und beim Löschen des Pools mit entfernt.

| Suffix/Aktion | Wirkung |
| --- | --- |
| `can_view_pool_<id>` | Pool und seine Fragen in der Übersicht sehen |
| `can_edit_pool_<id>` | Fragen in diesem Pool hinzufügen, bearbeiten und löschen; zusätzlich ist View-Recht erforderlich |
| `can_import_export_pool_<id>` | Fragen dieses Pools als CSV importieren und exportieren; der Export enthält interne Lösungsschlüssel |
| `can_generate_test_from_pool_<id>` | Tests ausschließlich aus diesem Pool erzeugen |
| `can_view_submissions_pool_<id>` | Abgaben zu diesem Pool ansehen und bewerten |

Eine Testabgabe gehört zu genau einem Pool, der beim Erzeugen am Test gespeichert wird. Die Auswertungsübersicht und Detail-URLs filtern deshalb nach der jeweiligen Poolberechtigung; eine Berechtigung für Pool A zeigt keine Tests aus Pool B. Administratoren sehen alle Pools.

**Verwaltung**

Unter **Einstellungen** können Administratoren zwischen Mitarbeiterverwaltung und Rechtegruppen wechseln. Sie können eigene Gruppen anlegen, umbenennen, mit einer Sortierzahl versehen, mit globalen und dynamischen Poolrechten ausstatten und löschen. Die Liste folgt der Sortierzahl aufsteigend; gleiche Zahlen werden nach Gruppennamen sortiert. Berechtigungen werden im Gruppen- und Benutzerformular nach Wirkungsbereich gruppiert. Gruppen und individuelle Direktrechte lassen sich kombinieren. Delegierte Mitarbeiter benötigen `can_manage_users` plus jeweils das passende Grant- oder Revoke-Recht. Niemand kann den eigenen Administratorstatus entziehen. Bestehende Fragen und Tests wurden beim Pool-Backfill dem initialen Pool **Einstellungstest** zugeordnet.

## Systemprotokoll

Mitarbeitende mit `core.can_view_audit_logs` sehen `/admin-dashboard/logs/`; Administratoren erhalten das Recht automatisch. Das Protokoll erfasst alle nicht-statischen HTTP-Aufrufe mit Zeitpunkt, Benutzer (falls angemeldet), HTTP-Methode, Pfad/Route, Statuscode, Laufzeit, direkter Client-IP und Browserkennung. Zusätzlich werden Fachereignisse für erfolgreiche/fehlgeschlagene Anmeldungen, akzeptierte/abgelehnte OTP-Versuche, Fragenänderungen, Testgenerierung, Testabgabe, Punktkorrektur, Mitarbeiter-/Rechteänderungen und Testlöschungen gespeichert. Frageereignisse enthalten zur Nachvollziehbarkeit auch Antwortoptionen und Musterlösungen; die Logberechtigung sollte deshalb nur vertrauenswürdigen Personen zugewiesen werden. Logs lassen sich nach Kategorie, Konto, Aktion/Text und Datum filtern und unter Beibehaltung der Filter als CSV exportieren. Ein berechtigter Mitarbeiter mit `can_clear_audit_logs` und `can_view_audit_logs` kann alle Einträge manuell leeren; der Löschvorgang selbst bleibt als neuer Eintrag erhalten.

Passwörter, OTPs und rohe HTTP-Request-Bodies werden ausdrücklich **nicht** protokolliert. Fachereignisse speichern gezielt die für einen nachvollziehbaren Änderungsverlauf nötigen Werte, nicht beliebige POST-Daten. Bei Testlöschung wird der Audit-Eintrag in derselben Datenbanktransaktion geschrieben und bleibt auch nach dem Entfernen von Test und Antworten erhalten. Das Log enthält personenbezogene Metadaten wie Benutzername, IP und Browserkennung. Standardmäßig werden Einträge älter als 180 Tage entfernt und das Log auf höchstens 50.000 neueste Einträge begrenzt; die Bereinigung läuft höchstens einmal täglich bei einem Request. Beide Werte lassen sich über `AUDIT_LOG_RETENTION_DAYS` und `AUDIT_LOG_MAX_ENTRIES` konfigurieren. Regelmäßige Backups und eine externe, manipulationssichere Logsenke bleiben für strengere Nachweispflichten erforderlich.

## Testgenerierung und OTP

Beim Erzeugen eines Tests wird die gewünschte Gesamtzahl `N` gegen den verfügbaren Pool und die Zahl verankerter Fragen geprüft. Alle verankerten Fragen werden zuerst ausgewählt. Die verbleibenden `N - Anzahl(verankert)` Plätze werden ohne Zurücklegen mit `secrets.SystemRandom` aus den nicht verankerten Fragen gezogen. Die ausgewählten Fragen werden als Schnappschuss am Test gespeichert, damit spätere Änderungen am Fragenpool bereits erstellte Prüfungen nicht verändern.

Jeder Test erhält eine UUID und ein sechs Ziffern langes OTP aus dem kryptografischen Zufallszahlengenerator. Die Klartext-OTP wird ausschließlich bei erfolgreicher Erzeugung angezeigt und niemals in der Datenbank gespeichert: persistiert wird Djangos adaptiver Passwort-Hash. Der Prüfling öffnet den Direktlink, gibt das OTP ein, trägt danach seinen Namen ein und erhält anschließend nur Fragetext, Fragetyp und Antwortoptionen. Musterlösungen und Punkte werden nicht in den Prüflingskontext serialisiert. Der Name wird erst beim erfolgreichen Absenden mit dem Testlauf gespeichert.

Beim Absenden prüft der Server Antwortoptionen erneut. In einer Datenbanktransaktion wird der Teststatus per bedingtem Update von `ISSUED` nach `COMPLETED` gewechselt. Nur wenn genau ein Datensatz geändert wurde, werden Abgaben gespeichert. Das bedingte Update verhindert eine zweite Einlösung auch bei gleichzeitig eintreffenden Requests. SQLite ist für lokale Einzelinstanzen geeignet; für parallele Produktivlast sollte eine Datenbank mit stärkerer Konkurrenzkontrolle wie PostgreSQL eingesetzt werden. Das OTP hat im aktuellen lokalen MVP keine zeitbasierte Ablaufzeit oder verteilte Fehlversuchsdrosselung; Test-URLs sollten daher vertraulich geteilt und produktiv durch Rate-Limiting/Monitoring ergänzt werden.

Bei der Testerstellung kann optional ein Zeitlimit von 1 bis 1.440 Minuten gewählt werden. Die Zeitmessung beginnt, sobald der Prüfling die Fragenseite öffnet. Ein Countdown gibt den Test im Browser automatisch ab; zusätzlich setzt der Server ein abgelaufenes Zeitlimit durch und wertet nicht rechtzeitig eingegangene Antworten als unbeantwortet. Für die Übertragung der automatischen Abgabe räumt der Server höchstens drei Sekunden Netzwerkpuffer ein. Die Bearbeitungszeit (bei Zeitlimit höchstens bis zum Ablauf) erscheint in der Ergebnisübersicht und Detailauswertung.

Die Seite **Abgegebene Tests** zeigt bewusst zunächst eine Zeile pro Testlauf mit Test-ID, Prüfungstyp, Prüflingsname, Abgabezeit, Bearbeitungsdauer und Gesamtpunktzahl. Reiter filtern die Liste nach den freigegebenen Prüfungstypen. Suche nach Prüflingsname/Test-ID, Zeitraumauswahl und ein Filter auf offene Korrekturen verfeinern die Liste; Ergebnisse werden seitenweise angezeigt. Die Liste enthält nur Pools, für die das Konto `can_view_submissions_pool_<id>` besitzt. Ein Klick öffnet die Detailansicht mit allen Fragen und Antworten des erlaubten Pools. Inhaber dieses Poolrechts sehen die bisherigen Punkte direkt in den Eingabefeldern und können mehrere Bewertungen auf einmal über den Speichern-Button oben oder unten übernehmen. Bei gefilterter Korrektur bleiben Filter und Vor/Zurück-Navigation erhalten. Ungültige Punktwerte verhindern die gesamte Speicherung; leere Felder lassen eine noch nicht bewertete Antwort unverändert.

Antworten auf einer Testseite werden im `sessionStorage` des Browser-Tabs zwischengespeichert und nach einer Aktualisierung wiederhergestellt. Vor dem Verlassen einer Seite mit Eingaben erscheint eine Browserwarnung. Die Zwischenspeicherung wird bei erfolgreicher Abgabe gelöscht und ist nicht zwischen Geräten oder Tabs synchronisiert. Testlink, Einmalpasswort und Zeitlimit lassen sich gemeinsam als Einladung kopieren oder drucken.

## Lokale Entwicklung

```powershell
python manage.py check
python manage.py test
```

Die Oberfläche verwendet lokales CSS; Google Fonts werden optional extern geladen und fallen ohne Internet auf System-Schriften zurück. Die Standardwerte der Django-Konfiguration sind für lokale Entwicklung gedacht; für Deployment werden Produktionswerte über Umgebungsvariablen gesetzt.

## Docker-Deployment mit Portainer

Das Image verwendet Python 3.11, Gunicorn und WhiteNoise. SQLite liegt im persistenten Volume `sqlite_data`; die mit `collectstatic` erzeugten Dateien liegen im Volume `static_data`. Beim Start führt der Container zuerst Datenbankmigrationen und `collectstatic` aus und startet danach Gunicorn als unprivilegierter Benutzer.

1. Lege in Portainer unter **Stacks** einen neuen Stack aus diesem Git-Repository an und wähle `docker-compose.yml` als Compose-Datei.
1. Hinterlege unter den Stack-Umgebungsvariablen `DJANGO_SECRET_KEY` (einen langen zufälligen Wert), `DJANGO_ALLOWED_HOSTS` (deinen Hostnamen, ohne Schema) und `CSRF_TRUSTED_ORIGINS` (zum Beispiel `https://academy.example.org`). Setze außerdem `PORT` bei Bedarf auf den gewünschten Host-Port.
1. Lass `DJANGO_DEBUG=False`, `DJANGO_SECURE_SSL_REDIRECT=True` und `DJANGO_SECURE_COOKIES=True` für den Produktivbetrieb aktiv. Stelle die Anwendung über einen TLS-Reverse-Proxy bereit, der `X-Forwarded-Proto: https` setzt und überschreibt. Der Container-Port 8000 sollte nicht ungeschützt öffentlich erreichbar sein. Für einen lokalen HTTP-Test können Redirect und Secure-Cookies explizit abgeschaltet werden.
1. Deploye den Stack. Der Web-Container migriert die Datenbank und sammelt Statikdateien vor dem Start des Webservers.
1. Lege den ersten Mitarbeiter-Administrator über die Portainer-Containerkonsole oder per Docker-CLI an:

```sh
docker exec -it police-academy-web python manage.py createsuperuser
```

Das ist ein Django-Superuser und erhält automatisch Administratorzugriff auf die Academy.

Die Volumes bleiben bei Stack-Neuerstellungen erhalten. Sichere insbesondere `sqlite_data` regelmäßig und stoppe den Container vor dem Kopieren der SQLite-Datei. SQLite ist für eine einzelne Containerinstanz und geringe bis mittlere Schreiblast gedacht; für mehrere Web-Instanzen sollte PostgreSQL eingesetzt werden. Zugangsschlüssel gehören in Portainers Stack-Umgebungsvariablen, nicht in die Compose-Datei oder ins Repository.

# testgenerator
