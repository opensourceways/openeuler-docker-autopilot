"""build_runner 纯逻辑单元测试。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.build_runner import (
    parse_dockerfile,
    base_image,
    find_dockerfile_target,
    render_diff,
    container_name,
    docker_rm_by_label,
    docker_rm_images_by_label,
    build_command,
    ensure_build_cache,
)
import scripts.lib.build_runner as build_runner


def test_parse_dockerfile_basic():
    dockerfile = """\
FROM openeuler/openeuler:22.03
RUN yum install -y gcc \\
    && yum clean all
COPY . /src
WORKDIR /src
"""
    insts = parse_dockerfile(dockerfile)
    assert [i.keyword for i in insts] == ['FROM', 'RUN', 'COPY', 'WORKDIR']
    run = insts[1]
    assert 'gcc' in run.args and 'yum clean all' in run.args
    # 续行应被折叠为一条逻辑指令
    assert run.raw.count('\n') == 1


def test_parse_dockerfile_skips_comments_and_blanks():
    dockerfile = """\
# comment
FROM scratch

# another comment
RUN echo hi
"""
    insts = parse_dockerfile(dockerfile)
    assert [i.keyword for i in insts] == ['FROM', 'RUN']


def test_base_image():
    assert base_image('FROM openeuler/openeuler:22.03\n') == 'openeuler/openeuler:22.03'
    assert base_image('FROM --platform=$BUILDPLATFORM alpine:3.18\n') == 'alpine:3.18'
    assert base_image('RUN echo hi\n') is None


def test_base_image_scratch():
    assert base_image('FROM scratch\n') == 'scratch'


def test_find_dockerfile_target_unique():
    pr_files = ['AI/mlflow/3.12.0/Dockerfile', 'README.md']
    assert find_dockerfile_target(pr_files) == 'AI/mlflow/3.12.0/Dockerfile'


def test_find_dockerfile_target_dockerfile_suffix():
    assert find_dockerfile_target(['a/b/c.dev.Dockerfile']) == 'a/b/c.dev.Dockerfile'


def test_find_dockerfile_target_ambiguous():
    # 多个 Dockerfile → 返回 None（需人工判断）
    assert find_dockerfile_target(['a/Dockerfile', 'b/Dockerfile']) is None


def test_find_dockerfile_target_none():
    assert find_dockerfile_target(['README.md', 'src/main.c']) is None


def test_render_diff():
    diff = render_diff('FROM alpine\nRUN echo a\n', 'FROM alpine\nRUN echo b\n', 'Dockerfile')
    assert '-RUN echo a' in diff
    assert '+RUN echo b' in diff
    assert 'a/Dockerfile' in diff


def test_container_name():
    assert container_name(2546, 'arm64') == 'ci-fix-2546-arm64'
    assert container_name(2546, 'amd64') == 'ci-fix-2546-amd64'


def _completed(stdout=''):
    m = MagicMock()
    m.stdout = stdout
    return m


def test_docker_rm_by_label_removes_matching_containers():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed('abc\ndef\n')

    with patch('scripts.lib.build_runner.subprocess.run', side_effect=fake_run):
        docker_rm_by_label('oe.ci-fix=1-1')
    assert calls[0] == ['docker', 'ps', '-aq', '--filter', 'label=oe.ci-fix=1-1']
    assert calls[1] == ['docker', 'rm', '-f', 'abc', 'def']


def test_docker_rm_images_by_label_removes_deduped_matches():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed('img2\nimg1\nimg1\n')

    with patch('scripts.lib.build_runner.subprocess.run', side_effect=fake_run):
        docker_rm_images_by_label('oe.ci-fix=1-1')
    assert calls[0] == ['docker', 'images', '-aq', '--filter', 'label=oe.ci-fix=1-1']
    assert calls[1] == ['docker', 'image', 'rm', '-f', 'img1', 'img2']


def test_docker_rm_images_by_label_noop_without_label():
    with patch('scripts.lib.build_runner.subprocess.run') as run:
        docker_rm_images_by_label('')
    run.assert_not_called()


def test_docker_rm_images_by_label_noop_when_none_match():
    with patch('scripts.lib.build_runner.subprocess.run',
               return_value=_completed('')) as run:
        docker_rm_images_by_label('oe.ci-fix=1-1')
    # 只有一次列镜像调用，没有实际删除
    assert run.call_count == 1


# ── 持久 BuildKit 层缓存（可选，仅自托管 runner）─────────────────────────────

def test_build_command_without_cache_is_plain_docker_build():
    """没配缓存目录时命令与改造前逐字一致。"""
    assert build_command('AI/mlflow/3.12.0/Dockerfile') == [
        'docker', 'build', '-f', 'AI/mlflow/3.12.0/Dockerfile', '.']


def test_build_command_with_cache_uses_buildx_local_cache():
    cmd = build_command('Dockerfile', '/work/ci-fix-buildkit-cache', 'oe-ci-fix')
    assert cmd[:3] == ['docker', 'buildx', 'build']
    assert '--load' in cmd
    assert 'type=local,src=/work/ci-fix-buildkit-cache' in cmd
    assert ('type=local,dest=/work/ci-fix-buildkit-cache,mode=max,ignore-error=true' in cmd)
    assert cmd[cmd.index('--builder') + 1] == 'oe-ci-fix'
    assert cmd[-3:] == ['-f', 'Dockerfile', '.']


def test_build_command_without_builder_flag_when_name_empty():
    cmd = build_command('Dockerfile', '/cache')
    assert '--builder' not in cmd


def test_ensure_build_cache_disabled_without_dir(monkeypatch):
    monkeypatch.setattr(build_runner, 'BUILD_CACHE_DIR', '')
    monkeypatch.setattr(build_runner, '_CACHE_READY', None)
    assert ensure_build_cache() is False


def test_ensure_build_cache_falls_back_when_buildx_unusable(monkeypatch, tmp_path):
    """buildx/builder 不可用 → 返回 False，调用方退回普通 docker build。"""
    monkeypatch.setattr(build_runner, 'BUILD_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(build_runner, '_CACHE_READY', None)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        m = MagicMock()
        m.returncode = 1
        m.stderr = 'docker: unknown command: buildx'
        return m

    monkeypatch.setattr(build_runner.subprocess, 'run', fake_run)
    assert ensure_build_cache() is False
    assert calls[0] == ['docker', 'buildx', 'inspect', 'oe-ci-fix']
    assert calls[1][:3] == ['docker', 'buildx', 'create']
    # 探测结果被记住，不会每次 docker_build 都重新 bootstrap（inspect+create 各一次）
    assert ensure_build_cache() is False
    assert len(calls) == 2


def test_docker_build_uses_cache_command_when_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(build_runner, 'BUILD_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(build_runner, '_CACHE_READY', True)
    seen = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        return _completed('')

    monkeypatch.setattr(build_runner.subprocess, 'run', fake_run)
    build_runner.docker_build('Dockerfile', str(tmp_path))
    assert 'buildx' in seen['cmd']
    assert any(a.startswith('type=local,src=') for a in seen['cmd'])


def test_docker_build_stays_plain_when_cache_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(build_runner, 'BUILD_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(build_runner, '_CACHE_READY', False)
    seen = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        return _completed('')

    monkeypatch.setattr(build_runner.subprocess, 'run', fake_run)
    build_runner.docker_build('Dockerfile', str(tmp_path))
    assert seen['cmd'] == ['docker', 'build', '-f', 'Dockerfile', '.']
