"""Lecture des journaux d'invocation Bedrock : fichier, dossier ou archive .zip.

Formes reconnues (docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html) :

- livraison S3 : fichiers .json.gz (ou .json) qui contiennent des enregistrements `ModelInvocationLog`,
  un par ligne ou en tableau ;
- CloudWatch Logs : export en lignes `<horodatage> {json}`, sortie de `aws logs filter-log-events`
  (`{"events": [{"message": "{json}"}]}`), ou envoi par abonnement (`{"logEvents": [...]}`) ;
- corps de plus de 100 Ko : objets S3 séparés (`..._input.json.gz`, `..._output.json.gz`) que
  l'enregistrement référence par `inputBodyS3Path` / `outputBodyS3Path`. On les suit s'ils sont
  dans la même source (rapprochés par nom de fichier), sinon le contenu est marqué manquant.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import zipfile
from pathlib import Path

MAX_BYTES = 1_000_000_000  # garde-fou contre une archive ou un .gz piégé
SUFFIXES = (".json", ".jsonl", ".ndjson", ".log", ".txt", ".gz")
_BODY_NAME = re.compile(r"_(input|output)\.json(\.gz)?$")
_GZIP_MAGIC = b"\x1f\x8b"


class SourceError(Exception):
    """Source illisible ou invalide (message destiné à l'utilisateur)."""


def _bounded(data: bytes) -> bytes:
    if data[:2] == _GZIP_MAGIC:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                data = g.read(MAX_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise SourceError(f"fichier gzip corrompu : {type(exc).__name__}") from exc
    if len(data) > MAX_BYTES:
        raise SourceError("fichier décompressé trop volumineux (> 1 Go)")
    return data


def iter_blobs(source: str | Path):
    """(nom, octets décompressés) pour chaque fichier candidat de la source."""
    source = Path(source)
    if source.is_dir():
        for path in sorted(p for p in source.rglob("*") if p.is_file() and p.name.endswith(SUFFIXES)):
            yield str(path), _bounded(path.read_bytes())
    elif source.suffix == ".zip":
        try:
            with zipfile.ZipFile(source) as z:
                for info in sorted(z.infolist(), key=lambda i: i.filename):
                    if (info.is_dir() or "__MACOSX" in info.filename
                            or not info.filename.endswith(SUFFIXES)):
                        continue
                    if info.file_size > MAX_BYTES:
                        raise SourceError(f"{info.filename} : trop volumineux (> 1 Go)")
                    yield f"{source}!{info.filename}", _bounded(z.read(info))
        except zipfile.BadZipFile as exc:
            raise SourceError(f"archive zip illisible : {source}") from exc
    elif source.is_file():
        yield str(source), _bounded(source.read_bytes())
    else:
        raise SourceError(f"introuvable : {source}")


def body_key(name: str) -> str:
    """Nom de fichier d'un corps externe, sans .gz, pour rapprocher chemin S3 et fichier local."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".gz") else base


def is_body_name(name: str) -> bool:
    return bool(_BODY_NAME.search(body_key(name)))


def extract_records(obj, out: list[dict]) -> bool:
    """Ajoute à `out` chaque enregistrement d'invocation trouvé dans `obj` ; True si reconnu."""
    if isinstance(obj, list):
        return any([extract_records(o, out) for o in obj])
    if not isinstance(obj, dict):
        return False
    if obj.get("schemaType") == "ModelInvocationLog" or (
            "modelId" in obj and "operation" in obj and isinstance(obj.get("input"), dict)):
        out.append(obj)
        return True
    found = False
    if isinstance(obj.get("message"), str):  # événement CloudWatch : le JSON est dans `message`
        found = extract_records(_loads(obj["message"]), out)
    for key in ("events", "logEvents", "Records", "records"):
        if isinstance(obj.get(key), list):
            found = extract_records(obj[key], out) or found
    return found


def _loads(text: str):
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])  # saute un éventuel horodatage devant le JSON
    except ValueError:
        return None


def load(source: str | Path) -> tuple[list[dict], dict[str, bytes], dict]:
    """Source → (enregistrements, corps externes par nom, bilan de lecture).

    Bilan : fichiers, lignes_illisibles, fichiers_non_reconnus (noms), corps_externes.
    """
    records: list[dict] = []
    bodies: dict[str, bytes] = {}
    stats = {"fichiers": 0, "lignes_illisibles": 0, "fichiers_non_reconnus": [], "corps_externes": 0}
    for name, data in iter_blobs(source):
        stats["fichiers"] += 1
        if is_body_name(name):
            bodies[body_key(name)] = data
            stats["corps_externes"] += 1
            continue
        text = data.decode("utf-8", errors="replace")
        before = len(records)
        whole = None
        try:
            whole = json.loads(text)
        except ValueError:
            pass
        if whole is not None:
            extract_records(whole, records)
        else:
            for line in text.split("\n"):
                if not line.strip():
                    continue
                obj = _loads(line)
                if obj is None or not extract_records(obj, records):
                    stats["lignes_illisibles"] += 1
        if len(records) == before:
            stats["fichiers_non_reconnus"].append(name)
    return records, bodies, stats
