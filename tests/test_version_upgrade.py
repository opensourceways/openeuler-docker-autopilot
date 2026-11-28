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
        "# myapp\n\n"
        "```\n"
        "docker run myapp:2.1.0\n"
        "```\n"
        "\n"
        "| Tag | Currently | Architectures |\n"
        "|---|---|---|\n"
        "|[2.1.0-oe2203sp3](https://example.com/myapp/2.1.0/22.03-lts-sp3/Dockerfile)| myapp 2.1.0 on openEuler 22.03-LTS-SP3 | amd64, arm64 |\n",
        encoding="utf-8",
    )
    (app / "doc").mkdir()
    (app / "doc" / "image-info.yml").write_text(
        "tags: |\n"
        "  | Tag | Currently | Architectures |\n"
        "  |---|---|---|\n"
        "  |[2.1.0-oe2203sp3](https://example.com/myapp/2.1.0/22.03-lts-sp3/Dockerfile)| myapp 2.1.0 on openEuler 22.03-LTS-SP3 | amd64, arm64 |\n",
        encoding="utf-8",
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

    def test_prefers_the_same_version_line_below_the_target(self) -> None:
        """parquet 这类多版本线应用：1.18.2 不能复制版本更高的 2.12.0。"""
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Bigdata" / "parquet"
            for version in ("1.18.1", "2.12.0"):
                directory = app / version / "24.03-lts-sp4"
                directory.mkdir(parents=True)
                (directory / "Dockerfile").write_text(
                    "FROM openeuler/openeuler:24.03-lts-sp4\n", encoding="utf-8"
                )

            plan = version_upgrade.plan_upgrade(app, target_version="1.18.2")

            self.assertEqual(plan.old_version, "1.18.1")
            self.assertEqual(plan.os_version, "24.03-lts-sp4")

    def test_target_newer_than_all_versions_keeps_highest_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Bigdata" / "parquet"
            for version in ("1.18.1", "2.12.0"):
                directory = app / version / "24.03-lts-sp4"
                directory.mkdir(parents=True)
                (directory / "Dockerfile").write_text(
                    "FROM openeuler/openeuler:24.03-lts-sp4\n", encoding="utf-8"
                )

            plan = version_upgrade.plan_upgrade(app, target_version="3.0.0")

            self.assertEqual(plan.old_version, "2.12.0")


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
            self.assertEqual(
                dockerfile,
                version_upgrade.ensure_repo_cache_cleaned(
                    _new_dockerfile("2.2.0")
                ),
            )

            # README / image-info 的版本表追加新行，旧行与正文保持不变
            readme = (app / "README.md").read_text(encoding="utf-8")
            self.assertIn("myapp 2.2.0 on openEuler 22.03-LTS-SP3", readme)
            self.assertIn("myapp 2.1.0 on openEuler 22.03-LTS-SP3", readme)
            self.assertIn("docker run myapp:2.1.0", readme)
            info = (app / "doc" / "image-info.yml").read_text(encoding="utf-8")
            self.assertIn("myapp 2.2.0 on openEuler 22.03-LTS-SP3", info)
            self.assertIn("myapp 2.1.0 on openEuler 22.03-LTS-SP3", info)

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

    def test_appends_a_row_and_rewrites_underscore_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Others" / "openjdk"
            image = app / "28.25" / "24.03-lts-sp4"
            image.mkdir(parents=True)
            (image / "Dockerfile").write_text(
                "FROM openeuler/openeuler:24.03-lts-sp4\nARG V=28.25\n",
                encoding="utf-8",
            )
            (app / "README.md").write_text(
                "| Tag | Currently | Architectures |\n"
                "|---|---|---|\n"
                "|[28_25-oe2403sp4](https://example.com/openjdk/28.25/24.03-lts-sp4/Dockerfile)| OpenJDK 28.25 on openEuler 24.03-LTS-SP4 | amd64, arm64 |\n",
                encoding="utf-8",
            )
            (app / "doc").mkdir()
            (app / "doc" / "image-info.yml").write_text("tags: |\n", encoding="utf-8")
            (app / "meta.yml").write_text(
                "28.25-oe2403sp4:\n  path: 28.25/24.03-lts-sp4/Dockerfile\n",
                encoding="utf-8",
            )

            plan = version_upgrade.plan_upgrade(app, target_version="28.26")
            version_upgrade.apply_upgrade(
                app, plan, "28.26", _new_dockerfile("28.26")
            )

            readme = (app / "README.md").read_text(encoding="utf-8")
            self.assertIn("[28_26-oe2403sp4]", readme)
            self.assertIn("openjdk/28.26/24.03-lts-sp4/Dockerfile", readme)
            self.assertIn("OpenJDK 28.26 on openEuler", readme)
            self.assertIn("[28_25-oe2403sp4]", readme)
            self.assertIn("openjdk/28.25/24.03-lts-sp4/Dockerfile", readme)

    def test_tableless_readme_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(Path(tmp))
            (app / "README.md").write_text(
                "```\ndocker run myapp:2.1.0\n```\n", encoding="utf-8"
            )
            (app / "doc" / "image-info.yml").write_text(
                "version: 2.1.0\n", encoding="utf-8"
            )
            plan = version_upgrade.plan_upgrade(app)

            version_upgrade.apply_upgrade(
                app, plan, "2.2.0", _new_dockerfile("2.2.0")
            )

            self.assertEqual(
                (app / "README.md").read_text(encoding="utf-8"),
                "```\ndocker run myapp:2.1.0\n```\n",
            )

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
            self.assertIn("git clone --branch v2.2.0", written)
            self.assertIn(version_upgrade._CACHE_CLEAN_MARKER, written)
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

    def test_hash_version_uses_short_directory_and_tag(self) -> None:
        full = "b1acf3c01cc914729fe188dfc8ed761858028d4f"
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Others" / "webbench"
            image = app / "1.5" / "24.03-lts-sp4"
            image.mkdir(parents=True)
            (image / "Dockerfile").write_text(
                "FROM openeuler/openeuler:24.03-lts-sp4\nARG VERSION=1.5\n",
                encoding="utf-8",
            )
            (app / "meta.yml").write_text(
                "1.5-oe2403sp4:\n  path: 1.5/24.03-lts-sp4/Dockerfile\n",
                encoding="utf-8",
            )
            plan = version_upgrade.plan_upgrade(app, target_version="fb32cae")
            version_upgrade.apply_upgrade(
                app,
                plan,
                "fb32cae",
                f"FROM openeuler/openeuler:24.03-lts-sp4\nARG VERSION={full}\n",
                match_version=full,
            )

            self.assertTrue(
                (app / "fb32cae" / "24.03-lts-sp4" / "Dockerfile").is_file()
            )
            self.assertFalse((app / full).exists())
            meta = (app / "meta.yml").read_text(encoding="utf-8")
            self.assertIn("fb32cae-oe2403sp4:", meta)
            self.assertIn("path: fb32cae/24.03-lts-sp4/Dockerfile", meta)

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


class EnsureRepoCacheCleanedTest(unittest.TestCase):
    def test_injects_after_every_from(self) -> None:
        text = (
            "FROM openeuler/openeuler:24.03-lts-sp4 AS builder\n"
            "RUN dnf install -y gcc\n"
            "FROM openeuler/openeuler:24.03-lts-sp4\n"
            "RUN dnf install -y busybox\n"
        )
        out = version_upgrade.ensure_repo_cache_cleaned(text)
        self.assertEqual(out.count(version_upgrade._CACHE_CLEAN_MARKER), 2)
        self.assertIn(
            "FROM openeuler/openeuler:24.03-lts-sp4\n"
            + version_upgrade._CACHE_CLEAN_RUN,
            out,
        )
        self.assertIn("dnf clean all", out)
        self.assertIn("rm -rf /var/cache/dnf", out)
        self.assertIn("skip_if_unavailable=True", out)

    def test_is_idempotent(self) -> None:
        text = "FROM x\nRUN dnf install -y gcc\n"
        once = version_upgrade.ensure_repo_cache_cleaned(text)
        twice = version_upgrade.ensure_repo_cache_cleaned(once)
        self.assertEqual(once, twice)

    def test_skips_scratch_stage(self) -> None:
        text = "FROM scratch\nCOPY --from=build /x /x\n"
        self.assertEqual(
            version_upgrade.ensure_repo_cache_cleaned(text), text
        )


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

    def test_accepts_full_hash_when_naming_uses_short_hash(self) -> None:
        full = "fb32cae86117254cb27c4695e6aa77299724d62d"

        self.assertEqual(
            version_upgrade.check_dockerfile(
                f"FROM x\nARG VERSION={full}\n", "fb32cae"
            ),
            [],
        )
        # 短哈希与完整哈希不同源时仍然拒绝
        self.assertTrue(
            version_upgrade.check_dockerfile(
                "FROM x\nARG VERSION=b1acf3c01cc914729fe188dfc8ed761858028d4f\n",
                "fb32cae",
            )
        )
