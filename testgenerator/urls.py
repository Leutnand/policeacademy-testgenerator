"""Zentrale URL-Routen des Projekts."""

from django.urls import include, path

urlpatterns = [path("", include("core.urls"))]
