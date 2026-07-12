"""1.4.2 Audio Control — pptx embedded audio that starts automatically.

Auto-starting audio in a deck IS the finding (a slide can't offer a pause/stop control);
click-started audio is a user choice and never flagged. Deterministic markers only:
<a:audioFile> + a zero-delay timing condition with no onClick gate.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as osx  # noqa: E402

_SLIDE_AUDIO = ('<?xml version="1.0"?><p:sld xmlns:p="p" xmlns:a="a" xmlns:r="r">'
                '<p:cSld><p:spTree><p:pic><a:audioFile r:link="rId2"/></p:pic></p:spTree></p:cSld>'
                '{timing}</p:sld>')
_T_AUTO = '<p:timing><p:cTn><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn></p:timing>'
_T_CLICK = '<p:timing><p:cTn><p:stCondLst><p:cond evt="onClick" delay="0"/></p:stCondLst></p:cTn></p:timing>'


def _deck(tmp_path, slide_xml):
    p = tmp_path / "d.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide1.xml", slide_xml)
    return p


def test_autoplay_audio_is_flagged_with_the_slide_number(tmp_path):
    f = osx.pptx_audio_autoplay_checks(_deck(tmp_path, _SLIDE_AUDIO.format(timing=_T_AUTO)))
    assert len(f) == 1
    assert f[0]["wcag"].startswith("1.4.2") and f[0]["severity"] == "SERIOUS"
    assert "slide 1" in f[0]["detail"]


def test_click_started_audio_is_not_flagged(tmp_path):
    assert osx.pptx_audio_autoplay_checks(_deck(tmp_path, _SLIDE_AUDIO.format(timing=_T_CLICK))) == []


def test_audio_without_a_timing_tree_is_not_flagged(tmp_path):
    # No timing tree = no start trigger = click-to-play in PowerPoint — not autoplay.
    assert osx.pptx_audio_autoplay_checks(_deck(tmp_path, _SLIDE_AUDIO.format(timing=""))) == []


def test_slide_without_audio_never_flags_even_with_autoplay_timing(tmp_path):
    xml = _SLIDE_AUDIO.format(timing=_T_AUTO).replace('<a:audioFile r:link="rId2"/>', "")
    assert osx.pptx_audio_autoplay_checks(_deck(tmp_path, xml)) == []


def test_garbage_never_raises(tmp_path):
    p = tmp_path / "junk.pptx"
    p.write_bytes(b"not a zip")
    assert osx.pptx_audio_autoplay_checks(p) == []
