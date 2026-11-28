"""Heat-index screening shown to the operator and on both camera feeds."""
import math


HEAT_ALERTS = {
    'below_warning': {
        'label': 'Below heat warning',
        'severity': 'info',
        'guidance': 'Confirm site conditions with the rescue lead before continuing the search.',
    },
    'caution': {
        'label': 'Caution',
        'severity': 'warning',
        'guidance': 'Review heat precautions with the rescue lead before continuing.',
    },
    'extreme_caution': {
        'label': 'Extreme caution',
        'severity': 'warning',
        'guidance': 'Notify the rescue lead and review heat precautions before advancing.',
    },
    'danger': {
        'label': 'Danger',
        'severity': 'alert',
        'guidance': 'Pause the search, notify the rescue lead, and follow site heat procedures.',
    },
    'extreme_danger': {
        'label': 'Extreme danger',
        'severity': 'alert',
        'guidance': 'Treat as an urgent heat warning. Notify the rescue lead and follow site emergency procedures.',
    },
    'unavailable': {
        'label': 'Reading unavailable',
        'severity': 'info',
        'guidance': 'Wait for a fresh heat reading and follow site safety procedures.',
    },
}


def classify_heat_band(heat_index_c, risk_level):
    if not isinstance(heat_index_c, (int, float)) or isinstance(heat_index_c, bool) or not math.isfinite(heat_index_c):
        return 'unavailable'
    # NWS Heat Index chart bands. At a shared boundary use the higher band.
    if heat_index_c >= (125 - 32) * 5 / 9:
        return 'extreme_danger'
    # Preserve BIM-Bot's existing severe air-temperature warning even in dry air.
    if heat_index_c >= (103 - 32) * 5 / 9 or risk_level == 'Severe Risk':
        return 'danger'
    if heat_index_c >= (90 - 32) * 5 / 9:
        return 'extreme_caution'
    if heat_index_c >= (80 - 32) * 5 / 9:
        return 'caution'
    return 'below_warning'
