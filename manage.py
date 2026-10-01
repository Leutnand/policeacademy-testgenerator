#!/usr/bin/env python
"""Django-Verwaltungsbefehl für das lokale Projekt."""
import os
import sys


def main():
    """Startet Django mit den projektspezifischen Einstellungen."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testgenerator.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
