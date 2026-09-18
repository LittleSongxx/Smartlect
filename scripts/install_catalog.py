"""Install the authorized product catalog and local image files."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "backend/data/02_catalog_seed.sql"
GALLERY_FIX = ROOT / "backend/data/03_catalog_value_gallery.sql"
ASSET_SOURCE = ROOT / "run/catalog-source/file"
UPLOADS = ROOT / "run/uploads/file"
VERSION_MARKER = ROOT / "run/uploads/.catalog-version"
# -valuegallery1: per-value color gallery backfill layered via 03_catalog_value_gallery.sql
CATALOG_VERSION = "catalog-mirror-a7d6063f05a397a6-valuegallery1"
PRODUCT_COUNT = 47


def parse_env():
    path = ROOT / "run/runtime.env"
    if not path.exists():
        raise RuntimeError("Run ./scripts/dev.sh bootstrap first")
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#"))


def compose(*args, capture=False, input_text=None):
    command = ["docker", "compose", "--project-name", "smartlect", "--env-file",
               str(ROOT / "run/runtime.env"), "-f", str(ROOT / "deploy/compose.yaml"), *args]
    return subprocess.run(command, cwd=ROOT, check=True, text=True,
                          capture_output=capture, input=input_text).stdout


def mysql(sql, database="", capture=True):
    target = f" {database}" if database else ""
    return compose("exec", "-T", "mysql", "sh", "-ec",
                   f'MYSQL_PWD="$SMARTLECT_FLYWAY_PASSWORD" mysql -usmartlect_flyway{target} -e "$1"',
                   "catalog-install", sql, capture=capture)


def copy_assets():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    if not ASSET_SOURCE.is_dir():
        if any(UPLOADS.rglob("*.jpg")) or any(UPLOADS.rglob("*.png")):
            print("Catalog images already present in run/uploads/file.")
            return
        print("Catalog image source is missing; product covers will be empty until images are installed.")
        return
    copied = 0
    for source in ASSET_SOURCE.rglob("*"):
        if not source.is_file():
            continue
        destination = UPLOADS / source.relative_to(ASSET_SOURCE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.stat().st_size != source.stat().st_size:
            shutil.copy2(source, destination)
            copied += 1
    VERSION_MARKER.write_text(CATALOG_VERSION + "\n")
    print(f"Catalog images ready under run/uploads/file/ ({copied} file(s) copied).")


def installed_version():
    try:
        rows = mysql(
            "SELECT catalog_version, product_count FROM catalog_install_meta "
            "WHERE catalog_key='default';",
            "smartlect_product",
        )
    except subprocess.CalledProcessError:
        return None
    for line in rows.splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2 and parts[0] != "catalog_version":
            return parts[0], int(parts[1])
    return None


def apply_sql():
    if not SQL.is_file():
        raise RuntimeError("backend/data/02_catalog_seed.sql is missing")
    current = installed_version()
    if current == (CATALOG_VERSION, PRODUCT_COUNT):
        print(f"Catalog {CATALOG_VERSION} already installed ({PRODUCT_COUNT} products).")
        return
    # The seed mirrors the authorized catalog and re-inserts property rows, so the
    # gallery backfill must ride along after it inside the same install pass.
    statements = SQL.read_text()
    if GALLERY_FIX.is_file():
        statements += "\n" + GALLERY_FIX.read_text()
    statements += (
        f"\nUPDATE catalog_install_meta SET catalog_version = '{CATALOG_VERSION}' "
        "WHERE catalog_key = 'default';"
    )
    compose("exec", "-T", "mysql", "sh", "-ec",
            'MYSQL_PWD="$SMARTLECT_FLYWAY_PASSWORD" mysql -usmartlect_flyway smartlect_product',
            input_text=statements, capture=True)
    print(f"Installed catalog {CATALOG_VERSION} into smartlect_product / smartlect_stock.")


def apply_catalog(_env=None):
    copy_assets()
    apply_sql()


if __name__ == "__main__":
    try:
        apply_catalog(parse_env())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Smartlect catalog install failed: {error}", file=sys.stderr)
        sys.exit(1)
