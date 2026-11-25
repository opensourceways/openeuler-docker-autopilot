#!/usr/bin/env python3
"""
Stage: 场景二单应用升级（upgrade_apply）

在目标仓完整克隆上，对一个应用执行：

1. 切出升级分支 ``auto/version-update/<app>/<ver>-<oe_tag>``；
2. AI 结合看板证据包与上游源码生成新版本 Dockerfile（**不做版本串机械替换**），
   并在真实容器里逐条重放、失败当场修，返回「实际跑通」的版本
   （与 CI 失败修复链路的 dockerfile-builder 同一套做法）；
3. 若该应用缺功能测试脚本，复用场景四的 ``generate_test_script`` 生成
   ``tests/test.sh``（**只写工作树，不提交、不建 PR**）；生成失败不阻断升级；
4. 确定性复制目录 + 写入 AI 生成的 Dockerfile + README/doc 版本更新 +
   meta.yml 追加（:mod:`scripts.lib.version_upgrade`）；
5. commit，推送到 fork，并把上游证据写入 ``$RUNNER_TEMP/task-spec.json``
   供双架构验证复用。

输入: --item '<json>'（upgrade_scan 的产物）
环境: GITCODE_TOKEN, GITCODE_FORK_REPO(可选), SOURCE_REPO_DIR, TARGET_REPO,
      TARGET_BRANCH, GIT_COMMIT_NAME/EMAIL, AI_API_KEY, OPENCODE_BIN
输出: GITHUB_OUTPUT 写 branch/test_status；状态文件 task-spec.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import (  # noqa: E402
    ai_provider,
    app_notes,
    build_runner,
    supporting_files,
    upstream_evidence,
    version_upgrade,
)
from scripts.lib.agent_policy import build_policy  # noqa: E402
from scripts.lib.agent_runtime import run_agent  # noqa: E402
from scripts.lib.stage_common import (  # noqa: E402
    agent_prompt_file,
    log_stage,
    normalize_repo,
)
from scripts.lib.task_spec import TaskSpec, _os_tag  # noqa: E402

DEFAULT_SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, "source-repo")
DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_TARGET_BRANCH = "master"

DOCKERFILE_AGENT_ROLE = "upgrade_creator"
DOCKERFILE_REQUIRED_KEYS = ("success", "dockerfile", "summary")
# 首次生成 + 最多 1 轮按校验问题重写。
MAX_DOCKERFILE_ROUNDS = 2
# 生成与容器重放放在同一个 Agent 调用里：研究上游 + 起容器逐条跑通 + 当场修。
# 默认预算 90 分钟（见 app_notes），单个应用可在 config/app-notes/<app>.md 调整。

# docker 包装脚本目录：给本 run 的容器自动打 run 唯一标签，便于并发安全清理
DOCKER_SHIM_DIR = os.path.join(PROJECT_ROOT, "scripts", "lib", "docker_shim")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _redact(text: str) -> str:
    return re.sub(r"oauth2:[^@]+@", "oauth2:***@", text)


def _git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = _redact((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(
            f"git {_redact(' '.join(args))} failed ({completed.returncode}): {detail[:2000]}"
        )
    return completed


def _emit_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


# KunpengTest 4.7 禁止 set -e / set -o errexit，其余选项（-u、-o pipefail）允许。
_SET_OPTIONS_LINE_RE = re.compile(r"^(\s*)set\s+(-[A-Za-z]+)(.*)$")
_SET_ERREXIT_LINE_RE = re.compile(r"^(\s*)set\s+-o\s+errexit\s*$")


def _strip_errexit(text: str) -> str:
    """删除 set -e / set -o errexit，保留其它选项和行尾符。

    只做这一处确定性改写：现有测试脚本是人工维护的共享资产，不整体重写，
    避免丢失断言语义；改写后仍要重新跑完整静态契约。
    """
    changed = False
    result: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if _SET_ERREXIT_LINE_RE.match(body):
            changed = True
            continue
        match = _SET_OPTIONS_LINE_RE.match(body)
        if match:
            indent, options, rest = match.groups()
            if "e" in options[1:]:
                changed = True
                remaining = options[1:].replace("e", "")
                if not remaining:
                    continue
                body = f"{indent}set -{remaining}{rest}"
        result.append(body + ending)
    return "".join(result) if changed else text


def _ensure_test_script(
    *,
    repo_dir: Path,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
) -> str:
    """确保测试脚本存在且通过静态契约；返回 added / existing / existing-fixed。

    升级不允许在没有测试脚本的情况下继续：缺脚本就生成，生成失败直接失败，
    不推分支、不浪费双架构构建。现有脚本若只是用了 KunpengTest 4.7 禁止的
    ``set -e``，先做确定性最小改写（只去掉 e）再复检；其它违规仍然失败，
    避免自动重写覆盖人工维护的测试语义。
    """
    from scripts.harness.testgen_generate import generate_test_script
    from scripts.lib.kunpeng_test_contract import check_test_script

    app_dir = repo_dir / domain / app
    existing = _existing_test_script(app_dir)
    if existing is not None:
        findings = check_test_script(existing)
        if findings and {f["code"] for f in findings} == {"kunpeng.set_e"}:
            with existing.open("r", encoding="utf-8", newline="") as handle:
                original = handle.read()
            patched = _strip_errexit(original)
            if patched != original:
                with existing.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(patched)
                findings = check_test_script(existing)
                if not findings:
                    log_stage(
                        "upgrade-apply",
                        f"{app}: 去掉 "
                        f"{existing.relative_to(repo_dir).as_posix()} 中 "
                        "KunpengTest 4.7 禁止的 set -e，复用其余断言",
                    )
                    return "existing-fixed"
                # 复检仍失败时还原，避免把半成品写进升级分支。
                with existing.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(original)
        if findings:
            detail = "; ".join(
                f"{finding['code']}: {finding['message']}" for finding in findings
            )
            raise version_upgrade.UpgradeError(
                f"{app}: 现有测试脚本 "
                f"{existing.relative_to(repo_dir).as_posix()} 未通过静态契约：{detail}"
            )
        return "existing"

    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise version_upgrade.UpgradeError(
            f"{app}: 缺 tests/test.sh，且没有 AI 凭证/opencode 可生成；"
            "升级要求测试脚本必须存在并通过契约"
        )

    findings = generate_test_script(
        repo_dir=repo_dir,
        app=app,
        domain=domain,
        dockerfile_rel=f"{domain}/{app}/{plan.old_version}/{plan.os_version}/Dockerfile",
        source_url=str(item.get("source_url") or ""),
        latest_version=str(item["version"]),
        api_key=api_key,
        executable=Path(executable),
        extra_context=upstream_evidence.render_prompt(
            upstream_evidence.for_non_dockerfile(item.get("evidence"))
        ),
    )
    if findings:
        detail = "; ".join(f"{f['code']}: {f['message']}" for f in findings)
        raise version_upgrade.UpgradeError(f"{app}: 测试脚本生成未通过：{detail}")
    return "added"


def _existing_test_script(app_dir: Path) -> Path | None:
    """按 CI 的三个搜索位置找现有 test.sh。"""
    for candidate in (app_dir / "tests" / "test.sh", app_dir / "test.sh"):
        if candidate.is_file():
            return candidate
    matches = sorted(app_dir.glob("*/*/test.sh"))
    return matches[0] if matches else None


def build_dockerfile_prompt(
    *,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
    old_dockerfile: str,
    findings: list[str] | None = None,
    session: dict | None = None,
    notes: app_notes.AppNotes | None = None,
    supporting: list[supporting_files.SupportingFile] | None = None,
    arch: str = "x86_64",
) -> str:
    """组装升级 Dockerfile 生成提示：角色规则 + 任务契约 + 旧文件 + 证据包。"""
    prompt = Path(agent_prompt_file("upgrade-creator")).read_text(encoding="utf-8")
    evidence = item.get("evidence") or {}
    contract = {
        "app": app,
        "domain": domain,
        "old_version": plan.old_version,
        "new_version": str(item["version"]),
        "os_version": plan.os_version,
        "dockerfile_path": (
            f"{domain}/{app}/{plan.old_version}/{plan.os_version}/Dockerfile"
        ),
        "source_url": str(item.get("source_url") or ""),
        "tag": evidence.get("tag"),
        "tag_url": evidence.get("tag_url"),
        "commit_sha": evidence.get("commit_sha"),
        "install_candidates": evidence.get("install_candidates") or [],
        "output_fields": (
            ["dockerfile", "supporting_files"] if supporting else ["dockerfile"]
        ),
        "supporting_files": [item.path for item in supporting or []],
    }
    if item.get("build_notes"):
        contract["build_notes"] = str(item["build_notes"])
    prompt += (
        "\n\n## Immutable task contract\n\n"
        + json.dumps(contract, indent=2, ensure_ascii=False)
        + "\n\n"
        + build_policy()
        + upstream_evidence.render_install_section(evidence)
        + "\n\n## Current Dockerfile (previous version)\n\n```dockerfile\n"
        + old_dockerfile.rstrip()
        + "\n```\n"
    )
    prompt += supporting_files.render_prompt(supporting or [])
    prompt += "\n\n" + upstream_evidence.render_prompt(evidence).strip() + "\n"
    prompt += app_notes.render_prompt(notes)
    if session:
        prompt += container_verification_section(
            staging=Path(session["staging"]),
            container=str(session["container"]),
            output_dockerfile=Path(session["output_dockerfile"]),
            build_log=Path(session["build_log"]),
            arch=arch,
        )
    if findings:
        prompt += (
            "\n## Validation report to resolve\n\n"
            "上一轮生成的 Dockerfile 未通过确定性校验，逐条修正后重新生成完整文件：\n"
            + json.dumps(findings, indent=2, ensure_ascii=False)
            + "\n"
        )
    prompt += (
        "\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、dockerfile(str，完整 Dockerfile 文本)、"
        'install_mode(str，"source" 或 "binary"，必须与最终 Dockerfile 的实际做法一致)、'
        "summary(str)、app_note(str 或 null，本次新增的可复用构建经验)、"
        "error(null 或 str)"
        + (
            "、supporting_files(list，逐个辅助文件的审计结论)"
            if supporting
            else ""
        )
        + "。不得修改工作区文件；只返回 JSON。\n"
    )
    return prompt


def _reset_workspace(repo_dir: Path) -> None:
    """清掉 Agent 可能写下的改动；Dockerfile 只通过 JSON/落盘文件返回。"""
    _git(repo_dir, "checkout", "--", ".", check=False)
    _git(repo_dir, "clean", "-fd", check=False)


def container_name(app: str) -> str:
    """本应用本轮构建容器的确定性名字（清理用）。"""
    name = re.sub(r"[^a-z0-9_.-]", "-", app.lower())
    run_id = _env("GITHUB_RUN_ID")
    if run_id:
        name += f"-{run_id}"
        attempt = _env("GITHUB_RUN_ATTEMPT")
        if attempt:
            name += f"-{attempt}"
    return f"oe-upgrade-{name}"


def session_dir(
    repo_dir: Path, app: str, version: str, os_version: str, kind: str
) -> Path:
    """Agent 的构建暂存目录。

    放在 ``<repo>/.oe-scratch`` 下：``run_agent`` 会把该目录写进 .git/info/exclude，
    因此 Agent 在里面写候选 Dockerfile、``git clean -fd`` 都不会污染提交。
    """
    root = (
        repo_dir / ".oe-scratch" / f"upgrade-{kind}"
        / f"{app}-{version}-{os_version}"
    )
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_agent_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def container_verification_section(
    *,
    staging: Path,
    container: str,
    output_dockerfile: Path,
    build_log: Path,
    arch: str = "x86_64",
    mode: str = "generate",
) -> str:
    """生成/修复共用的「起容器逐条重放、失败当场修」规则。

    取自 CI 失败修复链路的做法（dockerfile-builder）：把 Dockerfile 指令在活的
    容器里按顺序执行，成功的安装不会重跑，失败的那条就地修，最后反推出真实跑通
    的 Dockerfile。生成阶段先做这一步，验证阶段就只剩确定性构建，成功率显著更高。
    """
    if mode == "repair":
        lead = (
            "修复不能只改文本：必须把修复后的 Dockerfile 在容器里重放到通过，"
            "再返回最终版本。若失败证据来自运行期（`tests/test.sh`、启动就绪），"
            "还要实际启动镜像执行测试来复现与验证。"
        )
        arch_note = (
            f"当前 runner 架构是 `{arch}`；若失败证据来自另一架构，修复必须架构中立"
            "或加架构守卫（如 `if [ \"$(uname -m)\" = \"x86_64\" ]`），不能破坏另一架构。\n"
        )
    elif mode == "replay":
        lead = (
            "这份候选 Dockerfile 已在 x86_64 的容器里逐条重放通过；本次是在 "
            "aarch64 上对同一份文件再做一次完整重放。只修复与架构相关的问题"
            "（包名、产物名、下载地址的架构差异、编译守卫、依赖可用性），"
            "不要改版本、下载源或 x86_64 下已验证通过的步骤。"
        )
        arch_note = (
            f"当前 runner 架构是 `{arch}`；必须在真实容器里逐条执行，不能只做文本修改。"
            "重放通过后，后续仍会做双架构原生构建与功能测试。\n"
        )
    else:
        lead = (
            "生成候选 Dockerfile 只是第一步，必须在真实容器里把它逐条跑通、"
            "失败当场修，再返回最终版本。"
        )
        arch_note = (
            f"当前 runner 架构是 `{arch}`（另一架构由后续 arm64 容器重放与原生验证把关）；"
            "Dockerfile 必须保持双架构同源，不要硬编码架构。\n"
        )
    return (
        "\n## Container build verification (mandatory)\n\n"
        + lead
        + "\n\n"
        + arch_note
        + f"""
- 构建上下文（staging，已含该版本目录副本与全部 COPY 源文件）：`{staging}`
- 先把候选/修复后的 Dockerfile 写到 `{staging}/Dockerfile`，再按它重放
- 容器名：`{container}`（同名容器已存在时先 `docker rm -f {container}`）
- 最终 Dockerfile 落盘：`{output_dockerfile}`（纯文本，无代码围栏）
- 构建日志落盘：`{build_log}`（markdown）

步骤：

1. `docker pull <FROM 镜像>`，然后
   `docker run -d --name {container} <FROM 镜像> sleep infinity`。
2. 按顺序逐条重放：
   - `ENV K=V` → `docker exec {container} sh -c 'export K=V'`（记入环境变量清单）
   - `WORKDIR d` → `docker exec {container} mkdir -p d`
   - `RUN cmd` → `docker exec -w <workdir> {container} sh -c 'cmd'`
   - `COPY src dst` → `docker cp {staging}/src {container}:dst`
   - 多阶段构建：每个 `FROM` 起一个容器（`{container}-stageN`）；`COPY --from=<stage>`
     用 `docker cp` 从对应容器复制；`COPY --from=<外部镜像>` 可跳过并记录。
3. 某条命令失败：读错误 → 定位根因 → 在容器里执行修复命令（装依赖、换 URL、
   调参数）→ 重跑原命令直到成功。把「原命令 + 修复命令 + 原因」记入构建日志。
4. **每修好一处就立即覆盖写一次 `{output_dockerfile}`**，再继续往下重放；
   不要攒到最后——任何时刻中断都要留下可用产物。
5. 尽力而为：`docker build -f {staging}/Dockerfile {staging}` 自检。预算不足时
   不要死磕，落盘最佳版本并在 `summary` 里写明「未完成从零自检」。
6. 收尾时 `docker rm -f` 清理你起的容器。
7. 最终 JSON 的 `dockerfile` 必须与 `{output_dockerfile}` 内容一致。

环境说明：openEuler 的 `[update-source]` 仓库元数据 404 是已知环境问题，harness
会在每个 `FROM` 后注入清缓存并写 `skip_if_unavailable=True` 的 RUN；
不要为了 404 修改仓库配置或下载源。
"""
    )


def _app_note(payload: dict) -> str:
    note = payload.get("app_note")
    return note.strip() if isinstance(note, str) and note.strip() else ""


def _generate_dockerfile(
    *,
    repo_dir: Path,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
    arch: str = "x86_64",
) -> tuple[str, dict[str, str], str, str]:
    """让 AI 生成新版本 Dockerfile，并在容器里逐条跑通、失败当场修。

    与 CI 失败修复链路同构：生成与修复在同一次 Agent 调用里完成，
    产物以「容器里实际跑通的那份」为准；验证阶段只做确定性构建。
    同时审计 Dockerfile 引用的辅助脚本，返回
    ``(Dockerfile, 需要写回的辅助文件, app_note, install_mode)``。
    """
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise version_upgrade.UpgradeError(
            f"{app}: 缺少 AI 凭证/opencode，无法生成 Dockerfile"
            "（场景二禁止机械替换版本串）"
        )

    new_version = str(item["version"])
    old_dockerfile = (plan.src_dir / "Dockerfile").read_text(encoding="utf-8")
    supporting = supporting_files.collect(plan.src_dir, old_dockerfile)
    if supporting:
        log_stage(
            "upgrade-apply",
            f"{app}: 需要审计 {len(supporting)} 个辅助文件 "
            f"{[item.path for item in supporting]}",
        )
    base_img = build_runner.base_image(old_dockerfile) or "(unknown)"
    notes = app_notes.load(app)
    agent_timeout = app_notes.generate_timeout_seconds(notes)
    if notes is not None and notes.body:
        log_stage(
            "upgrade-apply",
            f"{app}: 已加载注意点文档 config/app-notes/{notes.app}.md "
            f"({len(notes.body)} chars)",
        )
    if notes is not None and notes.generate_timeout_minutes:
        log_stage(
            "upgrade-apply",
            f"{app}: 注意点文档覆盖生成预算 {notes.generate_timeout_minutes} 分钟",
        )
    container = container_name(app)
    label = build_runner.activate_docker_shim(DOCKER_SHIM_DIR)
    findings: list[str] = []
    try:
        for round_no in range(MAX_DOCKERFILE_ROUNDS):
            root = session_dir(
                repo_dir, app, new_version, plan.os_version, "build"
            )
            staging = root / "context"
            shutil.copytree(plan.src_dir, staging)
            output_dockerfile = root / "final-Dockerfile"
            build_log = root / "build-log.md"

            prompt = build_dockerfile_prompt(
                app=app,
                domain=domain,
                plan=plan,
                item=item,
                old_dockerfile=old_dockerfile,
                findings=findings or None,
                session={
                    "staging": staging,
                    "container": container,
                    "output_dockerfile": output_dockerfile,
                    "build_log": build_log,
                },
                notes=notes,
                supporting=supporting,
                arch=arch,
            )
            log_stage(
                "upgrade-apply",
                f"{app}: dockerfile agent round {round_no + 1} "
                f"(generate + container replay, base={base_img})",
            )

            agent_error: Exception | None = None
            result = None
            try:
                result = run_agent(
                    executable=Path(executable),
                    role=DOCKERFILE_AGENT_ROLE,
                    prompt=prompt,
                    workspace=repo_dir,
                    api_key=api_key,
                    required_keys=DOCKERFILE_REQUIRED_KEYS,
                    timeout=agent_timeout,
                )
            except Exception as error:  # noqa: BLE001 - 见下：产物优先于退出码
                # 超时/契约失败不等于一无所获：Agent 被要求每修好一处就落盘，
                # 只要文件在，就继续用它，确定性验证阶段会兜底。
                agent_error = error
                log_stage(
                    "upgrade-apply",
                    f"{app}: agent 异常 {type(error).__name__}: {error}",
                )
            finally:
                # 必须在 _reset_workspace 之前读：暂存目录虽被 git exclude，
                # 但产物读取不应依赖这一点。
                written = read_agent_file(output_dockerfile)
                _reset_workspace(repo_dir)

            payload = result.payload if result is not None else {}
            candidate = written
            if not candidate:
                candidate = payload.get("dockerfile")
                if not isinstance(candidate, str):
                    candidate = ""
            if not candidate.strip():
                if agent_error is not None:
                    findings = [
                        f"Agent 异常且未落盘 Dockerfile："
                        f"{type(agent_error).__name__}: {agent_error}"
                    ]
                else:
                    findings = ["Agent 未返回非空的 dockerfile 字符串"]
                log_stage("upgrade-apply", f"{app}: findings={findings}")
                continue

            if agent_error is not None:
                log_stage(
                    "upgrade-apply",
                    f"{app}: agent 未正常结束，但容器内已落盘 Dockerfile，继续采用",
                )
            findings = version_upgrade.check_dockerfile(candidate, new_version)
            findings += supporting_files.deterministic_findings(
                supporting,
                old_version=plan.old_version,
                new_version=new_version,
            )
            review_findings, updates = supporting_files.validate(
                supporting, payload
            )
            findings += review_findings
            if not findings:
                return candidate, updates, _app_note(payload), (
                    upstream_evidence.resolved_install_mode(
                        {
                            "install_mode": payload.get("install_mode"),
                            "evidence": item.get("evidence"),
                        }
                    )
                )
            log_stage("upgrade-apply", f"{app}: findings={findings}")
    finally:
        build_runner.docker_rm(container)
        build_runner.docker_rm_by_label(label)
        build_runner.docker_rm_images_by_label(label)

    raise version_upgrade.UpgradeError(
        f"{app}: AI 生成的 Dockerfile 未通过校验：{'；'.join(findings)}"
    )


def run(
    item: dict,
    *,
    task_spec_out: Path,
    app_note_out: Path | None = None,
) -> int:
    app = str(item["app"])
    domain = str(item["domain"])
    new_version = str(item["version"])

    repo_dir = Path(_env("SOURCE_REPO_DIR", DEFAULT_SOURCE_REPO_DIR))
    if not repo_dir.is_dir():
        raise SystemExit(f"source repo not found: {repo_dir}")
    app_dir = repo_dir / domain / app
    if not app_dir.is_dir():
        raise SystemExit(f"{app}: 目标仓里没有 {domain}/{app}")

    plan = version_upgrade.plan_upgrade(app_dir, target_version=new_version)
    branch = f"auto/version-update/{app}/{new_version}-{_os_tag(plan.os_version)}"
    base_branch = _env("TARGET_BRANCH", DEFAULT_TARGET_BRANCH)

    checkout = _git(repo_dir, "checkout", "-B", branch, f"origin/{base_branch}", check=False)
    if checkout.returncode != 0:
        _git(repo_dir, "checkout", "-B", branch, base_branch, check=False)

    log_stage(
        "upgrade-apply",
        f"{app}: {plan.old_version} -> {new_version} (os={plan.os_version})",
    )
    dockerfile_text, supporting_updates, app_note, install_mode = (
        _generate_dockerfile(
            repo_dir=repo_dir,
            app=app,
            domain=domain,
            plan=plan,
            item=item,
            arch=_env("OE_RUNNER_ARCH", "x86_64"),
        )
    )
    if app_notes.save_note_text(app_note_out, app_note) is not None:
        log_stage("upgrade-apply", f"{app}: app note 已暂存 -> {app_note_out}")
    test_status = _ensure_test_script(
        repo_dir=repo_dir, app=app, domain=domain, plan=plan, item=item
    )
    changed = version_upgrade.apply_upgrade(
        app_dir,
        plan,
        new_version,
        dockerfile_text,
        supporting_files=supporting_updates,
    )

    _git(repo_dir, "add", "-A", str(app_dir.relative_to(repo_dir)))
    commit_name = _env("GIT_COMMIT_NAME", "github-actions[bot]")
    commit_email = _env("GIT_COMMIT_EMAIL", "github-actions[bot]@users.noreply.github.com")
    _git(
        repo_dir,
        "-c", f"user.name={commit_name}",
        "-c", f"user.email={commit_email}",
        "commit", "-m", f"feat: upgrade {app} to {new_version}",
    )

    token = _env("GITCODE_TOKEN")
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to push the upgrade branch")
    target_repo = _env("TARGET_REPO", DEFAULT_TARGET_REPO)
    push_repo = normalize_repo(_env("GITCODE_FORK_REPO")) or target_repo
    push_url = f"https://oauth2:{token}@gitcode.com/{push_repo}.git"
    _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
    log_stage("upgrade-apply", f"{app}: pushed {branch} -> {push_repo}")

    task = TaskSpec(
        app=app,
        version=new_version,
        os_version=plan.os_version,
        domain=domain,
        source_url=str(item.get("source_url") or ""),
        scenario="version-update",
    )
    task_spec_out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(task.to_json())
    payload["evidence"] = item.get("evidence") or {}
    payload["install_mode"] = install_mode
    task_spec_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _emit_output(
        branch=branch,
        test_status=test_status,
        push_repo=push_repo,
        item_json=json.dumps(
            {**item, "install_mode": install_mode},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    log_stage(
        "upgrade-apply",
        f"{app}: done changed={[str(p.relative_to(repo_dir)) for p in changed]} "
        f"tests={test_status}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, help="upgrade_scan 产出的单条 item JSON")
    parser.add_argument(
        "--task-spec-out",
        default=os.path.join(os.environ.get("RUNNER_TEMP", PROJECT_ROOT), "task-spec.json"),
    )
    parser.add_argument(
        "--app-note-out",
        type=Path,
        help="Agent 总结的 app note 暂存路径（留空则不暂存）",
    )
    args = parser.parse_args()
    return run(
        json.loads(args.item),
        task_spec_out=Path(args.task_spec_out),
        app_note_out=args.app_note_out,
    )


if __name__ == "__main__":
    sys.exit(main())
