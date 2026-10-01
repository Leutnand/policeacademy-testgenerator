"""Konfiguration der Testgenerator-App."""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Registriert die App und ihre Signale für die Rolleninitialisierung."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        """Lädt Signale nach Aufbau der Django-App-Registry."""
        from importlib import import_module

        import_module(f"{self.name}.signals")
