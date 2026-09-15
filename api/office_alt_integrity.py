"""Exact Office alt-write readback and package preservation, not semantic certification.

Run before provenance stamping or other approved transforms. Only description attributes
at unambiguous approved targets may change; media, layout and all other parts must survive.
This does not establish that the description is accurate or visually render the document.
"""
from io import BytesIO
import zipfile
import re
from html import unescape
from apply_alt import parse_locator, tag_for_part, resolve_target, _alt_elements


def verify_alt_write(before, after, expected):
    """Fail closed for corrupt packages, ambiguous targets, or unrelated modifications."""
    if not expected:
        return False
    try:
        packages = []
        for data in (before, after):
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or archive.testzip() is not None:
                    return False
                packages.append({name: archive.read(name) for name in names})
        old, new = packages
        if old.keys() != new.keys():
            return False
        targets = {}
        for locator, value in expected.items():
            parsed = parse_locator(locator)
            if not parsed or not isinstance(value, str) or not value.strip():
                return False
            part, fragment = parsed
            if part not in old or not tag_for_part(part):
                return False
            targets.setdefault(part, []).append((fragment, value.strip()))
        for part in old:
            if part not in targets:
                if old[part] != new[part]:
                    return False
                continue
            normalized = []
            selected = []
            for candidate, content in enumerate((old[part], new[part])):
                xml = content.decode('utf-8')
                matches = _alt_elements(xml, tag_for_part(part))
                indices = []
                for fragment, value in targets[part]:
                    names = [re.search(r'\bname="([^\"]*)"', match.group(2)) for match in matches]
                    name_count = sum(bool(name and unescape(name[1]).strip() == fragment) for name in names)
                    if name_count > 1:
                        return False
                    if not name_count and len(re.findall(r'\br:embed="' + re.escape(fragment) + '"', xml)) > 1:
                        return False
                    offset = resolve_target(xml, tag_for_part(part), fragment)
                    index = next((i for i, match in enumerate(matches) if match.start() == offset), None)
                    if index is None or index in indices:
                        return False
                    indices.append(index)
                    description = re.search(r'\bdescr="([^\"]*)"', matches[index].group(2))
                    if candidate and (not description or unescape(description[1]) != value):
                        return False
                selected.append(indices)
                # Exact remaining bytes must match, including whitespace, order, media,
                # and drawing geometry. This is intentionally stricter than XML equivalence.
                for index in sorted(indices, reverse=True):
                    match = matches[index]
                    tag = re.sub(r'\s*\bdescr="[^\"]*"', '', match.group())
                    xml = xml[:match.start()] + tag + xml[match.end():]
                normalized.append(xml)
            if selected[0] != selected[1] or normalized[0] != normalized[1]:
                return False
        return True
    except (ValueError, KeyError, OSError, zipfile.BadZipFile):
        return False
