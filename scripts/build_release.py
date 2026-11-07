"""Build a reproducible manual-install archive without caches or credentials."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "mammotion_openapi"


def main() -> None:
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    target = ROOT / "dist" / f"mammotion_openapi-{version}.zip"
    target.parent.mkdir(exist_ok=True)
    sources = [
        file
        for file in COMPONENT.rglob("*")
        if file.is_file() and file.suffix in (".py", ".json", ".yaml")
    ]
    sources.append(ROOT / "README.md")
    sources.append(ROOT / "scripts/package-homeassistant.sh")
    sources.extend(file for file in (ROOT / "docs").iterdir() if file.suffix in (".md", ".json"))
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            info = ZipInfo(source.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert "custom_components/mammotion_openapi/manifest.json" in archive.namelist()
    print(target)
    print("SHA256:", hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
