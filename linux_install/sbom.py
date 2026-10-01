#!/usr/bin/env python3
"""Create and validate Lemma's deterministic CycloneDX dependency inventory.

The release builder intentionally uses only Python's standard library here.  SBOM
generation therefore works in the same offline environment as the rest of the
bundle build and does not add a package-manager or network dependency.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

SBOM_FORMAT = "CycloneDX"
SBOM_SPEC_VERSION = "1.5"
LOCKED_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)(?:\s*;.*)?(?:\s*\\)?$"
)


def _normalise_python_name(name: str) -> str:
    """Return the canonical distribution spelling used by Python package URLs."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _purl(kind: str, name: str, version: str) -> str:
    if kind == "npm":
        encoded_name = quote(name, safe="/")
    else:
        encoded_name = quote(_normalise_python_name(name), safe="")
    return f"pkg:{kind}/{encoded_name}@{quote(version, safe='')}"


def _integrity_hash(integrity: object) -> list[dict[str, str]]:
    """Translate one npm Subresource Integrity value to CycloneDX hash syntax."""
    if not isinstance(integrity, str) or "-" not in integrity:
        return []
    algorithm, encoded = integrity.split("-", 1)
    algorithm_label = {"sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}.get(
        algorithm.lower()
    )
    if algorithm_label is None:
        return []
    try:
        digest = base64.b64decode(encoded, validate=True).hex()
    except (ValueError, base64.binascii.Error):
        return []
    return [{"alg": algorithm_label, "content": digest}]


def _npm_components(lock_path: Path) -> list[dict[str, Any]]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read npm lockfile {lock_path}: {error}") from error
    if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict):
        raise ValueError("npm lockfile must contain a packages object")

    components: dict[str, dict[str, Any]] = {}
    for location, metadata in lock["packages"].items():
        if not location or "node_modules/" not in location or not isinstance(metadata, dict):
            continue
        version = metadata.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(f"npm lock entry {location!r} has no exact version")
        inferred_name = location.rsplit("node_modules/", 1)[-1]
        name = metadata.get("name", inferred_name)
        if not isinstance(name, str) or not name:
            raise ValueError(f"npm lock entry {location!r} has no package name")
        reference = _purl("npm", name, version)
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": reference,
            "name": name,
            "version": version,
            "purl": reference,
            "properties": [
                {"name": "lemma:ecosystem", "value": "javascript"},
                {
                    "name": "lemma:npm-scope",
                    "value": "development" if metadata.get("dev") is True else "production",
                },
            ],
        }
        hashes = _integrity_hash(metadata.get("integrity"))
        if hashes:
            component["hashes"] = hashes
        license_name = metadata.get("license")
        if isinstance(license_name, str) and license_name.strip():
            component["licenses"] = [{"license": {"name": license_name.strip()}}]
        # Several node_modules locations can resolve to the same immutable package.
        # One purl is enough in an inventory and makes output stable across hoisting.
        components.setdefault(reference, component)
    return list(components.values())


def _python_components(requirements_path: Path) -> list[dict[str, Any]]:
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read exported Python requirements {requirements_path}: {error}") from error

    components: dict[str, dict[str, Any]] = {}
    for line in lines:
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or candidate.startswith("--hash="):
            continue
        match = LOCKED_REQUIREMENT.fullmatch(candidate)
        if match is None:
            # uv adds indented provenance comments and hash continuations. Anything
            # else that resembles a requirement must fail closed instead of silently
            # disappearing from the inventory.
            if candidate.startswith(("--", "#")):
                continue
            raise ValueError(f"unsupported or unlocked Python requirement line: {candidate}")
        name, version = match.groups()
        reference = _purl("pypi", name, version)
        components[reference] = {
            "type": "library",
            "bom-ref": reference,
            "name": _normalise_python_name(name),
            "version": version,
            "purl": reference,
            "properties": [{"name": "lemma:ecosystem", "value": "python"}],
        }
    return list(components.values())


def create_sbom(
    package_lock: Path,
    requirements: Path,
    application_version: str,
) -> dict[str, Any]:
    """Build a timestamp-free CycloneDX document from exact lock-derived inputs."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9]+)*", application_version):
        raise ValueError(f"invalid application version: {application_version}")
    root_reference = _purl("generic", "lemma", application_version)
    components = _npm_components(package_lock) + _python_components(requirements)
    components.sort(key=lambda component: component["bom-ref"])
    if not components:
        raise ValueError("dependency inventory is empty")
    return {
        "bomFormat": SBOM_FORMAT,
        "specVersion": SBOM_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_reference,
                "name": "lemma",
                "version": application_version,
                "purl": root_reference,
            },
            "properties": [
                {"name": "lemma:javascript-lock", "value": "frontend/package-lock.json"},
                {"name": "lemma:python-lock", "value": "backend/uv.lock"},
            ],
        },
        "components": components,
        "dependencies": [
            {
                "ref": root_reference,
                "dependsOn": [component["bom-ref"] for component in components],
            }
        ],
    }


def validate_sbom(document: object, application_version: str | None = None) -> None:
    """Validate the invariants relied on by release consumers."""
    if not isinstance(document, dict):
        raise ValueError("SBOM root must be an object")
    if document.get("bomFormat") != SBOM_FORMAT:
        raise ValueError("SBOM is not a CycloneDX document")
    if document.get("specVersion") != SBOM_SPEC_VERSION or document.get("version") != 1:
        raise ValueError(f"SBOM must use CycloneDX {SBOM_SPEC_VERSION} document version 1")
    metadata = document.get("metadata")
    root = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(root, dict) or root.get("name") != "lemma":
        raise ValueError("SBOM metadata must identify the Lemma application")
    if application_version is not None and root.get("version") != application_version:
        raise ValueError("SBOM application version does not match VERSION")
    components = document.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("SBOM dependency component list is empty")
    references: list[str] = []
    ecosystems: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("SBOM component must be an object")
        reference = component.get("bom-ref")
        if (
            component.get("type") != "library"
            or not isinstance(reference, str)
            or reference != component.get("purl")
            or not isinstance(component.get("name"), str)
            or not isinstance(component.get("version"), str)
        ):
            raise ValueError("SBOM contains an incomplete dependency component")
        references.append(reference)
        for prop in component.get("properties", []):
            if isinstance(prop, dict) and prop.get("name") == "lemma:ecosystem":
                ecosystems.add(str(prop.get("value")))
    if references != sorted(references) or len(references) != len(set(references)):
        raise ValueError("SBOM dependency components must be sorted and unique")
    if ecosystems != {"javascript", "python"}:
        raise ValueError("SBOM must inventory both JavaScript and Python dependencies")
    dependencies = document.get("dependencies")
    expected = [{"ref": root.get("bom-ref"), "dependsOn": references}]
    if dependencies != expected:
        raise ValueError("SBOM root dependency list is incomplete or out of order")


def _load_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read SBOM {path}: {error}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create a deterministic CycloneDX SBOM")
    create.add_argument("--package-lock", type=Path, required=True)
    create.add_argument("--requirements", type=Path, required=True)
    create.add_argument("--application-version", required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate", help="validate a Lemma CycloneDX SBOM")
    validate.add_argument("sbom", type=Path)
    validate.add_argument("--application-version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            document = create_sbom(args.package_lock, args.requirements, args.application_version)
            validate_sbom(document, args.application_version)
            args.output.write_text(
                json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            validate_sbom(_load_document(args.sbom), args.application_version)
    except ValueError as error:
        print(f"sbom.py: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
