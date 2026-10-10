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
)


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
