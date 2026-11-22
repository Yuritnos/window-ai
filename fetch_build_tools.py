"""Fetch verified public PyPI wheels, then install them without index resolution."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen, urlretrieve
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename

packages = {
    "PyInstaller": "6.22.3", "altgraph": "0.17.4", "packaging": "25.0",
    "pyinstaller-hooks-contrib": None, "pefile": None,
    "pywin32-ctypes": "0.2.3", "setuptools": "80.9.0",
}
destination = Path(__file__).parent / "build-wheels"
destination.mkdir(exist_ok=True)
supported = set(sys_tags())
files = []
versions = {}
for name, version in packages.items():
    address = f"https://pypi.org/pypi/{name}/" + (f"{version}/" if version else "") + "json"
    with urlopen(address, timeout=30) as response:
        metadata = json.load(response)
    candidates = []
    for artifact in metadata["urls"]:
        if artifact["filename"].endswith(".whl"):
            _, _, _, tags = parse_wheel_filename(artifact["filename"])
            if supported.intersection(tags):
                candidates.append(artifact)
    if not candidates:
        raise RuntimeError(f"No compatible wheel for {name}")
    artifact = candidates[0]
    path = destination / artifact["filename"]
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["digests"]["sha256"]:
        urlretrieve(artifact["url"], path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["digests"]["sha256"]
    files.append(str(path))
    versions[name] = metadata["info"]["version"]
    print(f"Verified {name} {versions[name]}", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                "--no-index", "--no-deps", *files], check=True)
(destination / "versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
