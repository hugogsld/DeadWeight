"""Audit 100 % local : l'agent auditeur tourne sur un modèle Ollama de la machine.

En mode local, deux garde-fous empêchent toute donnée de sortir :
1. l'adresse du modèle doit être locale (localhost, 127.0.0.1, ::1), sinon refus avant tout appel ;
2. un crochet d'audit Python (sys.addaudithook) refuse, pour tout le processus, toute résolution
   DNS ou connexion vers un hôte non local. Un crochet d'audit ne se retire pas : même un module
   tiers ne peut pas le contourner depuis Python.
"""
import ipaddress
import socket
import sys
from urllib.parse import urlsplit

LOCAL_BASE_URL = "http://localhost:11434/v1"  # API compatible OpenAI d'Ollama
LOCAL_MODEL = "qwen2.5:3b"  # le plus petit modèle testé qui gère les appels d'outils
LOCAL_TIMEOUT = 600  # secondes par appel : un modèle local sur un portable est lent
LOCAL_API_KEY = "ollama"  # Ollama ignore la clé ; aucune clé du client n'est lue
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}

_installed = False


class NonLocalHostError(PermissionError):
    """Tentative de joindre un hôte hors de la machine en mode local."""


def is_local_host(host):
    """Vrai pour un nom ou une adresse de boucle locale (127.0.0.0/8, ::1, localhost)."""
    if host is None:
        return False
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host in LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def require_local(base_url):
    """Refuse une adresse de modèle qui n'est pas sur la machine. Rend l'adresse inchangée."""
    host = urlsplit(base_url).hostname
    if not is_local_host(host):
        raise NonLocalHostError(f"mode local : l'adresse du modèle doit être locale, pas {host!r}")
    return base_url


def _address_host(address):
    """Hôte d'une adresse de socket ; None pour un socket Unix (fichier local, toujours permis)."""
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _hook(event, args):
    if event == "socket.getaddrinfo":
        host = args[0]
        if host is None:  # adresse d'écoute locale
            return
    elif event in ("socket.connect", "socket.sendto"):
        sock, address = args[0], args[1]
        if getattr(sock, "family", None) == socket.AF_UNIX:
            return
        host = _address_host(address)
        if host is None:
            return
    else:
        return
    if not is_local_host(host):
        raise NonLocalHostError(f"mode local : connexion vers {host!r} refusée, aucune donnée ne sort")


def install_network_guard():
    """Refuse, pour le reste du processus, toute résolution ou connexion vers un hôte non local."""
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
