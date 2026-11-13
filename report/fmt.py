"""Formats d'affichage partagés par les rapports (dollars, durées)."""


def usd(v):
    if v is None:
        return "non disponible"
    if v >= 10:
        return f"{v:,.0f} $".replace(",", " ")
    # sous un centime, « 0.00 $ » cacherait l'ordre de grandeur : deux chiffres significatifs
    return f"{v:.2f} $" if v >= 0.01 or v == 0 else f"{v:.2g} $"


def ms(v):
    """0 ms = latence non rapportée par la source (journaux, import) : on ne l'affiche pas comme une mesure."""
    return "non mesuré" if not v else f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms"
