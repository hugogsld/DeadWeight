"""--apply : le diff est appliqué sur une nouvelle branche, jamais sur la courante, jamais sur un dépôt sale."""
import subprocess

import pytest

from optimize.patch import ApplyError, apply_diffs

DIFF = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-un
+deux
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("un\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_applique_sur_nouvelle_branche_sans_commit(repo):
    branch, changed = apply_diffs(repo, [DIFF])
    assert branch == "deadweight/appliquer" and git(repo, "rev-parse", "--abbrev-ref", "HEAD") == branch
    assert changed == ["a.txt"] and (repo / "a.txt").read_text() == "deux\n"
    assert git(repo, "rev-list", "--count", "main") == "1" and git(repo, "rev-list", "--count", branch) == "1"


def test_refuse_depot_sale_et_ne_touche_a_rien(repo):
    (repo / "a.txt").write_text("local\n")
    with pytest.raises(ApplyError, match="non commités"):
        apply_diffs(repo, [DIFF])
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and (repo / "a.txt").read_text() == "local\n"


def test_refuse_branche_existante(repo):
    git(repo, "branch", "deadweight/appliquer")
    with pytest.raises(ApplyError, match="existe déjà"):
        apply_diffs(repo, [DIFF])
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_diff_invalide_restaure_le_depot(repo):
    bad = DIFF.replace("-un", "-absent")
    with pytest.raises(ApplyError, match="ne s'applique pas"):
        apply_diffs(repo, [bad])
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and git(repo, "status", "--porcelain") == ""
    assert git(repo, "branch", "--list", "deadweight/appliquer") == ""


def test_rien_a_appliquer_et_pas_un_depot(repo, tmp_path_factory):
    with pytest.raises(ApplyError, match="aucun diff"):
        apply_diffs(repo, [""])
    with pytest.raises(ApplyError, match="dépôt git"):
        apply_diffs(tmp_path_factory.mktemp("vide"), [DIFF])
