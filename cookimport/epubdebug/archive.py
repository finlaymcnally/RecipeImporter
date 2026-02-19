from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
import zipfile
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class ManifestItem:
    item_id: str
    href: str
    full_path: str
    media_type: str | None
    properties: str | None


@dataclass(frozen=True)
class SpineEntry:
    index: int
    idref: str | None
    href: str | None
    path: str | None
    media_type: str | None
    linear: bool | None


@dataclass
class EpubArchiveInfo:
    container_rootfile_path: str | None
    package_path: str | None
    metadata: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, ManifestItem] = field(default_factory=dict)
    spine: list[SpineEntry] = field(default_factory=list)
    nav_path: str | None = None
    warnings: list[str] = field(default_factory=list)


def parse_epub_archive(path: Path) -> EpubArchiveInfo:
    warnings: list[str] = []
    with zipfile.ZipFile(path) as zip_handle:
        package_path = _find_package_path(zip_handle, warnings)
        if not package_path:
            raise ValueError("Could not locate OPF package in EPUB archive.")

        try:
            opf_bytes = zip_handle.read(package_path)
        except KeyError as exc:
            raise ValueError(f"OPF package path not found in archive: {package_path}") from exc

        root = ET.fromstring(opf_bytes)
        metadata = _extract_metadata(root)
        manifest, nav_path = _extract_manifest(root, package_path)
        spine = _extract_spine(root, manifest, warnings)

        if not spine:
            warnings.append("Spine is empty.")
        if nav_path is None:
            warnings.append("Navigation document not found in manifest.")

        return EpubArchiveInfo(
            container_rootfile_path=_read_container_rootfile_path(zip_handle),
            package_path=package_path,
            metadata=metadata,
            manifest=manifest,
            spine=spine,
            nav_path=nav_path,
            warnings=warnings,
        )


def read_spine_bytes(path: Path, spine_path: str) -> bytes:
    with zipfile.ZipFile(path) as zip_handle:
        return read_zip_member(zip_handle, spine_path)


def read_zip_member(zip_handle: zipfile.ZipFile, member_path: str) -> bytes:
    return zip_handle.read(member_path)


def members_for_unpack(
    info: EpubArchiveInfo,
    *,
    only_spine: bool,
    available_members: list[str],
) -> list[str]:
    if not only_spine:
        return available_members

    wanted: set[str] = set()
    if info.container_rootfile_path:
        wanted.add("META-INF/container.xml")
    if info.package_path:
        wanted.add(info.package_path)
    if info.nav_path:
        wanted.add(info.nav_path)
    for entry in info.spine:
        if entry.path:
            wanted.add(entry.path)
    return [name for name in available_members if name in wanted]


def _read_container_rootfile_path(zip_handle: zipfile.ZipFile) -> str | None:
    try:
        container_bytes = zip_handle.read("META-INF/container.xml")
    except KeyError:
        return None
    try:
        root = ET.fromstring(container_bytes)
    except ET.ParseError:
        return None
    rootfile = root.find(".//{*}rootfile")
    if rootfile is None:
        return None
    return rootfile.attrib.get("full-path")


def _find_package_path(zip_handle: zipfile.ZipFile, warnings: list[str]) -> str | None:
    container_path = _read_container_rootfile_path(zip_handle)
    if container_path:
        return container_path

    for member in zip_handle.namelist():
        if member.lower().endswith(".opf"):
            warnings.append(
                "META-INF/container.xml missing or malformed; fell back to first .opf file."
            )
            return member
    return None


def _extract_metadata(root: ET.Element) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, xpath in (
        ("title", ".//{*}metadata/{*}title"),
        ("creator", ".//{*}metadata/{*}creator"),
        ("language", ".//{*}metadata/{*}language"),
        ("identifier", ".//{*}metadata/{*}identifier"),
        ("publisher", ".//{*}metadata/{*}publisher"),
    ):
        value = _node_text(root.find(xpath))
        if value:
            metadata[key] = value
    return metadata


def _extract_manifest(
    root: ET.Element,
    package_path: str,
) -> tuple[dict[str, ManifestItem], str | None]:
    manifest: dict[str, ManifestItem] = {}
    nav_path: str | None = None
    base_dir = PurePosixPath(package_path).parent
    for item in root.findall(".//{*}manifest/{*}item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if not item_id or not href:
            continue
        clean_href = href.split("#", 1)[0]
        full_path = (base_dir / clean_href).as_posix()
        media_type = item.attrib.get("media-type")
        properties = item.attrib.get("properties")
        manifest[item_id] = ManifestItem(
            item_id=item_id,
            href=clean_href,
            full_path=full_path,
            media_type=media_type,
            properties=properties,
        )
        if properties and "nav" in properties.split():
            nav_path = full_path
        if nav_path is None and media_type == "application/x-dtbncx+xml":
            nav_path = full_path
    return manifest, nav_path


def _extract_spine(
    root: ET.Element,
    manifest: dict[str, ManifestItem],
    warnings: list[str],
) -> list[SpineEntry]:
    entries: list[SpineEntry] = []
    for idx, itemref in enumerate(root.findall(".//{*}spine/{*}itemref")):
        idref = itemref.attrib.get("idref")
        linear_attr = itemref.attrib.get("linear")
        linear = None
        if linear_attr is not None:
            linear = linear_attr.strip().lower() != "no"
        manifest_item = manifest.get(idref or "")
        if manifest_item is None:
            warnings.append(f"Spine item missing from manifest: idref={idref!r}")
            entries.append(
                SpineEntry(
                    index=idx,
                    idref=idref,
                    href=None,
                    path=None,
                    media_type=None,
                    linear=linear,
                )
            )
            continue
        entries.append(
            SpineEntry(
                index=idx,
                idref=idref,
                href=manifest_item.href,
                path=manifest_item.full_path,
                media_type=manifest_item.media_type,
                linear=linear,
            )
        )
    return entries


def _node_text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def coerce_json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): coerce_json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [coerce_json_safe(item) for item in value]
    return str(value)
