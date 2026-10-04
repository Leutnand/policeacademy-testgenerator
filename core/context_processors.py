"""Stellt die öffentliche Toolkonfiguration in allen Templates bereit."""
from .models import ToolSettings


def tool_configuration(request):
    """Liefert gespeicherte Markenwerte oder Modellstandardwerte."""
    _ = request
    return {"tool_settings": ToolSettings.objects.filter(pk=1).first() or ToolSettings(pk=1)}
