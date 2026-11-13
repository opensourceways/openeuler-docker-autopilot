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


def _new_dockerfile(version: str) -> str:
    return (
        "FROM openeuler/openeuler:24.03-lts-sp4\n"
        f"ARG VERSION={version}\n"
        f"RUN curl -o /tmp/x.tar.gz https://example.com/myapp-{version}.tar.gz\n"
    )


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
    def test_copies_tree_writes_generated_dockerfile_and_appends_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            changed = version_upgrade.apply_upgrade(
                app, plan, "2.2.0", _new_dockerfile("2.2.0")
            )

            target = app / "2.2.0" / "22.03-lts-sp3"
            self.assertTrue((target / "Dockerfile").is_file())
            dockerfile = (target / "Dockerfile").read_text(encoding="utf-8")
            self.assertEqual(dockerfile, _new_dockerfile("2.2.0"))

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

    def test_generated_dockerfile_is_not_mechanically_replaced(self) -> None:
        """AI 产出的构建方式必须原样落盘，不能被旧文件的版本替换覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            custom = (
                "FROM openeuler/openeuler:24.03-lts-sp4\n"
                "ARG VERSION=2.2.0\n"
                "RUN git clone --branch v2.2.0 https://example.com/other-source.git\n"
            )
            version_upgrade.apply_upgrade(app, plan, "2.2.0", custom)

            written = (app / "2.2.0" / "22.03-lts-sp3" / "Dockerfile").read_text(
                encoding="utf-8"
            )
            self.assertEqual(written, custom)
            self.assertNotIn("myapp-2.2.0.tar.gz", written)

    def test_same_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            with pytest.raises(version_upgrade.UpgradeError):
                version_upgrade.apply_upgrade(app, plan, "2.1.0", _new_dockerfile("2.1.0"))

    def test_existing_target_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            (app / "2.2.0" / "22.03-lts-sp3").mkdir(parents=True)
            with pytest.raises(version_upgrade.UpgradeError):
                version_upgrade.apply_upgrade(app, plan, "2.2.0", _new_dockerfile("2.2.0"))

    def test_generated_dockerfile_without_new_version_fails_closed_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            with pytest.raises(version_upgrade.UpgradeError, match="目标版本"):
                version_upgrade.apply_upgrade(
                    app, plan, "2.2.0", _new_dockerfile("9.9.9")
                )
            self.assertFalse((app / "2.2.0" / "22.03-lts-sp3").exists())

    def test_empty_generated_dockerfile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            with pytest.raises(version_upgrade.UpgradeError, match="为空"):
                version_upgrade.apply_upgrade(app, plan, "2.2.0", "   \n")

    def test_missing_meta_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            (app / "meta.yml").unlink()
            with pytest.raises(version_upgrade.UpgradeError, match="meta.yml"):
                version_upgrade.apply_upgrade(app, plan, "2.2.0", _new_dockerfile("2.2.0"))
            self.assertFalse((app / "2.2.0" / "22.03-lts-sp3").exists())


class CheckDockerfileTest(unittest.TestCase):
    def test_accepts_v_prefixed_and_bare_versions(self) -> None:
        self.assertEqual(version_upgrade.check_dockerfile(_new_dockerfile("2.2.0"), "2.2.0"), [])
        self.assertEqual(
            version_upgrade.check_dockerfile(
                "FROM x\nARG VERSION=v2.2.0\n", "2.2.0"
            ),
            [],
        )

    def test_rejects_missing_from_and_wrong_version(self) -> None:
        self.assertIn("FROM", version_upgrade.check_dockerfile("ARG VERSION=2.2.0\n", "2.2.0")[0])
        findings = version_upgrade.check_dockerfile("FROM x\nARG VERSION=2.1.0\n", "2.2.0")
        self.assertTrue(any("2.2.0" in item for item in findings))
