from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_build_uses_fixed_pyinstaller_spec() -> None:
    script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "VideoDownloadKing.spec").read_text(encoding="utf-8")

    assert "VideoDownloadKing.spec" in script
    assert "--collect-all gmssl" not in script
    assert "collect_all" not in spec
    assert "'gmssl.func'" in spec
    assert "'gmssl.sm3'" in spec


def test_release_build_prunes_only_nonessential_qt_platform_plugins() -> None:
    script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")

    assert "Optimize-QtPackage" in script
    assert "translations" in script
    assert "opengl32sw.dll" in script
    assert "Qt6Quick.dll" in script
    assert "Qt6Qml.dll" in script
    assert "Qt6Pdf.dll" in script
    assert '$_ .Name -ne "qwindows.dll"' not in script
    assert '$_.Name -ne "qwindows.dll"' in script
