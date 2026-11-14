#!/usr/bin/env python3
"""
build 阶段工具库：Dockerfile 解析 / 定位 / diff，容器与构建封装

纯逻辑（可单测）：
  - parse_dockerfile:   解析 Dockerfile 为指令序列（支持续行、跳过注释）
  - base_image:         提取 FROM 基础镜像
  - find_dockerfile_target: 从 PR 文件列表中定位唯一 Dockerfile
  - render_diff:        生成 unified diff（展示 / 校验用）
  - container_name:     计算确定性容器名（清理用）

Docker CLI 封装（依赖宿主机 docker，供 stage 脚本调用）：
  - docker_rm / docker_build
  - build_command / ensure_build_cache: 可选的 BuildKit 持久层缓存（自托管 runner）
"""

import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

DOCKER_BUILD_TIMEOUT = int(os.environ.get('BUILD_DOCKER_TIMEOUT', '7200'))

# 持久化 BuildKit 层缓存：自托管 runner 上的稳定目录（跨 run 复用）。未设置时
# docker_build 的命令与行为完全不变，托管 runner（一次性环境）不受影响。
BUILD_CACHE_DIR = os.environ.get('CI_FIX_BUILD_CACHE_DIR', '').strip()
BUILDKIT_BUILDER = os.environ.get('CI_FIX_BUILDKIT_BUILDER', 'oe-ci-fix').strip()

# ensure_build_cache() 的结果只探一次：避免每次 docker_build 都去 bootstrap builder
_CACHE_READY: Optional[bool] = None


@dataclass
class Instruction:
    keyword: str  # FROM / RUN / ENV / ARG / WORKDIR / COPY / ADD / ...
    args: str     # 参数（不含关键字）
    raw: str      # 原始逻辑行（含续行）


def parse_dockerfile(content: str) -> List[Instruction]:
    """把 Dockerfile 文本解析为逻辑指令序列。

    支持反斜杠续行；跳过空行与整行注释。不处理 `# escape=` / heredoc 等高级语法，
    对本工作流（定位 FROM、枚举 RUN）足够。
    """
    instructions: List[Instruction] = []
    buf: List[str] = []

    def flush() -> None:
        joined = '\n'.join(buf)
        stripped = joined.lstrip()
        if stripped and not stripped.startswith('#'):
            parts = stripped.split(None, 1)
            instructions.append(Instruction(
                keyword=parts[0].upper(),
                args=parts[1].lstrip() if len(parts) > 1 else '',
                raw=joined,
            ))

    for line in content.splitlines():
        if not buf and (not line.strip() or line.lstrip().startswith('#')):
            continue
        buf.append(line)
        if line.rstrip().endswith('\\'):
            continue
        flush()
        buf = []
    if buf:
        flush()
    return instructions


def base_image(content: str) -> Optional[str]:
    """提取 FROM 的基础镜像（镜像名:tag），跳过 --platform 等 flag。"""
    for inst in parse_dockerfile(content):
        if inst.keyword == 'FROM':
            for token in inst.args.split():
                if not token.startswith('-'):
                    return token
            return inst.args.strip() or None
    return None


def find_dockerfile_target(pr_files: List[str]) -> Optional[str]:
    """从 PR 文件列表中定位待修复的 Dockerfile；唯一命中才返回，否则 None。"""
    candidates = [
        f for f in pr_files
        if f.split('/')[-1].lower() == 'dockerfile'
        or f.split('/')[-1].lower().endswith('.dockerfile')
    ]
    return candidates[0] if len(candidates) == 1 else None


def render_diff(original: str, final: str, path: str = 'Dockerfile') -> str:
    """生成 unified diff，用于展示与校验。"""
    import difflib
    return ''.join(difflib.unified_diff(
        original.splitlines(keepends=True),
        final.splitlines(keepends=True),
        fromfile=f'a/{path}',
        tofile=f'b/{path}',
    ))


def container_name(pr_number: int, arch: str) -> str:
    return f'ci-fix-{pr_number}-{arch}'


def docker_rm(name: str) -> None:
    """尽力清理容器，忽略失败（容器可能已被 agent 自行移除）。"""
    try:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                       text=True, timeout=120)
    except Exception:
        pass


def docker_rm_by_label(label: str) -> None:
    """删除本 run 打上该标签的所有容器，忽略失败。

    label 形如 `oe.ci-fix=<run_id>-<run_attempt>`（见 docker_shim）。
    按标签而非名字清理：只命中本 run 创建的容器，不会误伤并发运行的其他
    job（它们带的是各自的 run 标签）。
    """
    if not label:
        return
    try:
        listed = subprocess.run(
            ['docker', 'ps', '-aq', '--filter', f'label={label}'],
            capture_output=True, text=True, timeout=60,
        )
        ids = listed.stdout.split()
        if ids:
            subprocess.run(['docker', 'rm', '-f', *ids],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        pass


def docker_rm_images_by_label(label: str) -> None:
    """删除本 run 打上该标签的镜像，忽略失败。

    镜像由 docker_shim 在 `docker build` 时注入 run 标签；这里只命中本 run 构建的
    镜像，不会误删基础镜像或并发运行的其他 job 的镜像。
    """
    if not label:
        return
    try:
        listed = subprocess.run(
            ['docker', 'images', '-aq', '--filter', f'label={label}'],
            capture_output=True, text=True, timeout=60,
        )
        ids = sorted(set(listed.stdout.split()))
        if ids:
            subprocess.run(['docker', 'image', 'rm', '-f', *ids],
                           capture_output=True, text=True, timeout=300)
    except Exception:
        pass


def _log(msg: str) -> None:
    print(f"[build-cache] {msg}", flush=True)


def build_command(dockerfile_path: str, cache_dir: str = '',
                  builder: str = '') -> List[str]:
    """构造 docker build 命令（纯函数，便于单测）。

    没有 cache_dir 时与原来完全一致：`docker build -f <path> .`。

    配了 cache_dir 就换成 buildx，把层缓存落盘到该目录并复用：
      --load        镜像仍要回到本地 docker（清理按 label、verify 也只看宿主机）
      mode=max      连中间层一起缓存。重型镜像（bolt 这种从源码编 34 个 conan
                    依赖的）主要耗时都在中间层，只缓存最终层等于没缓存。
      ignore-error  缓存读写失败不该把一个能构建通过的结果判成失败。
    """
    if not cache_dir:
        return ['docker', 'build', '-f', dockerfile_path, '.']
    cmd = [
        'docker', 'buildx', 'build', '--load',
        '--cache-from', f'type=local,src={cache_dir}',
        '--cache-to', f'type=local,dest={cache_dir},mode=max,ignore-error=true',
    ]
    if builder:
        cmd += ['--builder', builder]
    return cmd + ['-f', dockerfile_path, '.']


def ensure_build_cache() -> bool:
    """准备（幂等）持久化 BuildKit 缓存，返回是否可用。

    docker 默认的 `docker` driver 不支持 local 缓存导出，所以要有一个
    docker-container builder。任何一步失败（拉不到 moby/buildkit 镜像、buildx 缺失、
    目录不可写……）都返回 False，调用方退回普通 `docker build`——缓存是加速手段，
    不能让它在 runner 环境不满足时把构建本身弄失败。
    """
    global _CACHE_READY
    if _CACHE_READY is not None:
        return _CACHE_READY
    _CACHE_READY = False
    if not BUILD_CACHE_DIR:
        return False
    try:
        os.makedirs(BUILD_CACHE_DIR, exist_ok=True)
    except OSError as e:
        _log(f"缓存目录不可用，退回普通 docker build: {e}")
        return False
    try:
        if subprocess.run(['docker', 'buildx', 'inspect', BUILDKIT_BUILDER],
                          capture_output=True, text=True, timeout=120).returncode == 0:
            _CACHE_READY = True
            return True
        created = subprocess.run(
            ['docker', 'buildx', 'create', '--name', BUILDKIT_BUILDER,
             '--driver', 'docker-container'],
            capture_output=True, text=True, timeout=180)
        if created.returncode != 0 and 'already exists' not in (created.stderr or ''):
            _log(f"创建 builder 失败，退回普通 docker build: {created.stderr.strip()[:200]}")
            return False
        boot = subprocess.run(['docker', 'buildx', 'inspect', '--bootstrap', BUILDKIT_BUILDER],
                              capture_output=True, text=True, timeout=600)
        if boot.returncode != 0:
            _log(f"builder 启动失败，退回普通 docker build: {boot.stderr.strip()[:200]}")
            return False
        _log(f"BuildKit 持久缓存就绪: builder={BUILDKIT_BUILDER} dir={BUILD_CACHE_DIR}")
        _CACHE_READY = True
    except Exception as e:
        _log(f"缓存不可用，退回普通 docker build: {e}")
        return False
    return True


def docker_build(dockerfile_path: str, context: str,
                 timeout: int = DOCKER_BUILD_TIMEOUT) -> subprocess.CompletedProcess:
    """对指定 Dockerfile 执行 docker build（context 为仓库根目录，-f 指向 Dockerfile 相对路径）。

    返回 CompletedProcess，不在此处抛超时异常；调用方自行判断 returncode。
    配置了 CI_FIX_BUILD_CACHE_DIR 且缓存就绪时走 buildx + 持久层缓存；否则与原来一致。
    这里不做「buildx 失败就退回普通构建」的兜底：builder 在构建前已经验过可用，此时
    非零返回就是真的构建失败，退回重跑只会把一次 74 分钟的重型构建再烧一遍。
    """
    cache_dir = BUILD_CACHE_DIR if ensure_build_cache() else ''
    return subprocess.run(
        build_command(dockerfile_path, cache_dir, BUILDKIT_BUILDER if cache_dir else ''),
        cwd=context, capture_output=True, text=True, timeout=timeout,
    )
