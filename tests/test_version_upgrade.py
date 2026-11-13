"""确定性应用版本升级单测。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import version_upgrade  # noqa: E402


def _build_app(root: Path) -> Path:
    app = root / "Database" / "myapp"
    for version, os_version in (
        ("2.0.0", "24.03-lts-sp4"),
        ("2.1.0", "22.03-lts-sp3"),
    ):
        image = app / version / os_version
        image.mkdir(parents=True)
        (image / "Dockerfile").write_text(
            f"FROM openeuler/openeuler:24.03-lts-sp4\n"
            f"ARG VERSION={version}\n"
            f"RUN curl -o /tmp/x.tar.gz https://example.com/myapp-{version}.tar.gz\n",
            encoding="utf-8",
        )
    (app / "README.md").write_text(
        "```\ndocker run myapp:2.1.0\n```\n", encoding="utf-8"
    )
    (app / "doc").mkdir()
    (app / "doc" / "image-info.yml").write_text(
        "version: 2.1.0\n", encoding="utf-8"
    )
    (app / "meta.yml").write_text(
        "2.1.0-oe2203sp3:\n  path: 2.1.0/22.03-lts-sp3/Dockerfile\n", encoding="utf-8"
    )
    return app


class PlanUpgradeTest(unittest.TestCase):
    def test_picks_highest_version_then_os(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            self.assertEqual(plan.old_version, "2.1.0")
            self.assertEqual(plan.os_version, "22.03-lts-sp3")

    def test_no_dockerfile_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "Database" / "empty"
            empty.mkdir(parents=True)
            with pytest.raises(version_upgrade.UpgradeError):
                version_upgrade.plan_upgrade(empty)


class ApplyUpgradeTest(unittest.TestCase):
    def test_copies_tree_rewrites_versions_and_appends_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            changed = version_upgrade.apply_upgrade(app, plan, "2.2.0")

            target = app / "2.2.0" / "22.03-lts-sp3"
            self.assertTrue((target / "Dockerfile").is_file())
            dockerfile = (target / "Dockerfile").read_text(encoding="utf-8")
            self.assertIn("ARG VERSION=2.2.0", dockerfile)
            self.assertIn("myapp-2.2.0.tar.gz", dockerfile)
            # 基础镜像的 os 版本不能被误替换
            self.assertIn("openeuler:24.03-lts-sp4", dockerfile)

            # README / image-info 在应用根目录，原地更新
            self.assertIn("myapp:2.2.0", (app / "README.md").read_text(encoding="utf-8"))
            self.assertIn("2.2.0", (app / "doc" / "image-info.yml").read_text(encoding="utf-8"))

            meta = (app / "meta.yml").read_text(encoding="utf-8")
            self.assertIn("2.2.0-oe2203sp3:", meta)
            self.assertIn("path: 2.2.0/22.03-lts-sp3/Dockerfile", meta)
            # 旧条目保留
            self.assertIn("2.1.0-oe2203sp3:", meta)

            relative = {path.relative_to(app).as_posix() for path in changed}
            self.assertIn("2.2.0/22.03-lts-sp3/Dockerfile", relative)
            self.assertIn("README.md", relative)
            self.assertIn("doc/image-info.yml", relative)
            self.assertIn("meta.yml", relative)

    def test_same_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            with pytest.raises(version_upgrade.UpgradeError):
                version_upgrade.apply_upgrade(app, plan, "2.1.0")

    def test_existing_target_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            (app / "2.2.0" / "22.03-lts-sp3").mkdir(parents=True)
            with pytest.raises(version_upgrade.UpgradeError):
                version_upgrade.apply_upgrade(app, plan, "2.2.0")

    def test_dockerfile_without_old_version_fails_closed_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            (plan.src_dir / "Dockerfile").write_text(
                "FROM openeuler/openeuler:24.03-lts-sp4\n", encoding="utf-8"
            )
            with pytest.raises(version_upgrade.UpgradeError, match="旧版本串"):
                version_upgrade.apply_upgrade(app, plan, "2.2.0")
            self.assertFalse((app / "2.2.0" / "22.03-lts-sp3").exists())

    def test_missing_meta_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            (app / "meta.yml").unlink()
            with pytest.raises(version_upgrade.UpgradeError, match="meta.yml"):
                version_upgrade.apply_upgrade(app, plan, "2.2.0")
            self.assertFalse((app / "2.2.0" / "22.03-lts-sp3").exists())
