#!/usr/bin/env python3
"""ROOT-only Linux x86_64 composition exporter. No SQL, installer or requests.

Execution requires the reviewed frozen plan and its out-of-band SHA. This file
is deliberately independent of Ledger/Support Python application dependencies.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import re
import selectors
import shutil
import signal
import socket
import stat
import sys
import tempfile
import time

MIB = 1024 * 1024
MAX_OUTPUT = 16 * MIB
MAX_SCRATCH = 128 * MIB
NODE = '/usr/bin/node'
SECCOMP = '/lib/x86_64-linux-gnu/libseccomp.so.2.5.4'
ROOT_EVIDENCE = Path('/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-support-composition-isolated-v12-20261031')
CLONE_NEWUSER, CLONE_NEWNS = 0x10000000, 0x00020000
CLONE_NEWNET, CLONE_NEWPID, CLONE_NEWIPC = 0x40000000, 0x20000000, 0x08000000
MS_BIND, MS_REMOUNT, MS_RDONLY, MS_NOSUID, MS_NODEV = 4096, 32, 1, 2, 4
MS_REC, MS_PRIVATE = 16384, 1 << 18
CONTROLS = ['guard-network', 'guard-dns', 'guard-process', 'guard-execve',
            'guard-read', 'guard-envfile', 'guard-loadenv', 'guard-write', 'guard-native',
            'guard-worker', 'guard-timer', 'permission-read', 'permission-write',
            'permission-process', 'permission-execve', 'permission-native', 'permission-worker',
            'fd-owned-read', 'guard-fd-unknown', 'guard-fd-closed', 'guard-fd-reused', 'guard-fd-write',
            'env-debug-absent-delete', 'guard-env-delete-existing', 'native-interface-feature-denial']
FINAL_RESERVE = 64 * 1024


class BoundaryError(RuntimeError):
    def __init__(self, code, evidence=None):
        super().__init__(code)
        self.code, self.evidence = code, evidence


def need(ok, code):
    if not ok:
        raise BoundaryError(code)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(MIB), b''):
            h.update(block)
    return h.hexdigest()


def relative(value):
    p = PurePosixPath(value)
    need(not p.is_absolute() and '..' not in p.parts and str(p) == value, 'manifest_path')
    return p


def json_read(path, expected=None):
    raw = Path(path).read_bytes()
    need(len(raw) <= MAX_OUTPUT, 'input_limit')
    if expected:
        need(hashlib.sha256(raw).hexdigest() == expected, 'manifest_identity')
    return json.loads(raw)


def compact(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


class CompositionEvidence:
    """Only this frozen task's exact filenames, cumulative across both phases."""
    def __init__(self):
        self.leaves = []
        self.largest = 256 * 1024

    def remaining(self):
        total = 0
        for p in ROOT_EVIDENCE.iterdir():
            if p.name in ['negative.json', 'export.json'] or re.fullmatch(r'(negative|export)-leaf-\d{2}-\d{2}\.json', p.name):
                info = p.lstat()
                need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'evidence_file_shape')
                total += info.st_size
        need(total <= MAX_OUTPUT, 'cumulative_output_limit')
        return MAX_OUTPUT - total

    def admit(self):
        # Stop before another child when its observed footprint cannot fit, with
        # extra space for child/failure metadata and the final compact aggregate.
        remaining = self.remaining()
        need(remaining >= self.largest + 2 * FINAL_RESERVE, 'next_child_output_budget')
        return remaining - 2 * FINAL_RESERVE

    def leaf(self, name, raw):
        need(re.fullmatch(r'(negative|export)-leaf-\d{2}-\d{2}\.json', name), 'leaf_name')
        need(len(raw) + FINAL_RESERVE <= self.remaining(), 'leaf_output_budget')
        target = ROOT_EVIDENCE / name
        with target.open('xb') as handle:
            os.chmod(target, 0o600)
            handle.write(raw)
        ref = {'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.leaves.append(ref)
        self.largest = max(self.largest, len(raw))
        return ref

    def final(self, target, value):
        raw = compact(value)
        need(len(raw) <= FINAL_RESERVE and len(raw) <= self.remaining(), 'final_output_budget')
        with target.open('xb') as handle:
            os.chmod(target, 0o600)
            handle.write(raw)


def source_verify(plan):
    root = Path(plan['sourceRoot'])
    for name, info in plan['fullNodes'].items():
        p = root.joinpath(relative(name))
        need(p.is_file() and not p.is_symlink(), 'source_file_shape')
        need(p.stat().st_size == info['bytes'] and digest(p) == info['sha256'], 'source_drift')
    for name, expected in plan['sourceExtra'].items():
        p = root.joinpath(relative(name))
        need(not p.is_symlink() and digest(p) == expected, 'source_extra_drift')
    for ref in plan['references']:
        need(digest(ref['path']) == ref['sha256'], 'reference_drift')


def deps_verify(plan):
    data = json_read(plan['depsManifest']['path'], plan['depsManifest']['sha256'])
    root = Path(plan['toolroot'])
    need(data['toolroot'] == str(root) and data['counts']['files'] == 38088, 'deps_target')
    expected = {name for name, _, _ in data['files']} | {name for name, _ in data['symlinks']}
    actual = set()
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in subdirs[:]:
            p = Path(directory, name)
            if p.is_symlink():
                actual.add(p.relative_to(root).as_posix())
                subdirs.remove(name)
        for name in files:
            p = Path(directory, name)
            actual.add(p.relative_to(root).as_posix())
    need(actual == expected, 'deps_tree_drift')
    for name, size, sha in data['files']:
        p = root.joinpath(relative(name))
        need(not p.is_symlink() and p.stat().st_size == size and digest(p) == sha, 'deps_file_drift')
    for name, target in data['symlinks']:
        p = root.joinpath(relative(name))
        need(p.is_symlink() and os.readlink(p) == target and p.resolve().is_relative_to(root), 'deps_link_drift')


def tool_verify(plan):
    need(os.uname().machine == 'x86_64' and sys.platform == 'linux', 'platform')
    need(digest(sys.executable) == plan['python']['sha256'], 'python_drift')
    for info in plan['python']['stdlibFiles']:
        need(digest(info['path']) == info['sha256'], 'python_stdlib_drift')
    need(digest(NODE) == plan['node']['sha256'], 'node_drift')
    for info in plan['systemFiles']:
        need(digest(info['source']) == info['sha256'], 'system_file_drift')
    if 'rootTracer' in plan:
        need(digest(plan['rootTracer']['path']) == plan['rootTracer']['sha256'], 'root_tracer_drift')
    here = Path(__file__).resolve().parent
    for name, info in plan['helpers'].items():
        p = here / ('tests/' + name if name == 'support-composition-negative.mjs' else name)
        need(digest(p) == info['sha256'], 'helper_drift')
    need(digest(__file__) == plan['launcherSHA256'], 'launcher_drift')


def clean_env(variant):
    return {
        'PATH': '/bin', 'HOME': '/home/synthetic', 'TMPDIR': '/tmp', 'TZ': 'UTC',
        'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'NODE_ENV': 'production',
        'UV_THREADPOOL_SIZE': '1', 'WS_NO_BUFFER_UTIL': '1', 'WS_NO_UTF_8_VALIDATE': '1',
        'JWT_SECRET': 'composition-only-access-0123456789abcdef0123456789abcdef',
        'JWT_REFRESH_SECRET': 'composition-only-refresh-fedcba9876543210fedcba9876543210',
        'SPACE_IDENTITY_MODE': variant['identity'],
        'CORE_API_URL': 'https://core.invalid', 'CORE_IDENTITY_KEY': 'composition-only-key',
        'ECOSYSTEM_SSO_JWKS_URL': 'https://core.invalid/api/sso/jwks',
        'ECOSYSTEM_SSO_ISSUER': 'composition-only-issuer', 'SSO_AUDIENCE': 'support',
        'SUPPORT_CONTEXT_ENABLED': str(variant['context']).lower(),
        'SUPPORT_CONTEXT_JWKS_URL': 'https://core.invalid/api/sso/jwks',
    }


def node_argv(mode, control=None):
    args = ['/bin/node', '--permission', '--no-addons', '--max-old-space-size=256',
            '--max-semi-space-size=16', '--v8-pool-size=2',
            '--allow-fs-read=/bin/node', '--allow-fs-read=/work/source',
            '--allow-fs-read=/work/node_modules', '--allow-fs-read=/tools',
            '--allow-fs-read=/tmp', '--allow-fs-write=/tmp',
            '--allow-fs-write=/evidence/result.json',
            '/tools/export-support-composition.mjs', mode]
    return args + ([control] if control else [])


def libc_api():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                           ctypes.c_ulong, ctypes.c_void_p]
    libc.mount.restype = ctypes.c_int
    libc.unshare.argtypes = [ctypes.c_int]
    libc.unshare.restype = ctypes.c_int
    return libc


def syscall_ok(value, code):
    need(value == 0, code + '_errno_' + str(ctypes.get_errno()))


def mount(libc, source, target, flags, kind=None, data=None):
    syscall_ok(libc.mount(os.fsencode(source) if source else None,
                         os.fsencode(target), kind.encode() if kind else None,
                         flags, data.encode() if data else None), 'mount')


def bind(libc, source, target, directory=False):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if directory:
        target.mkdir(exist_ok=True)
    else:
        target.touch()
    mount(libc, source, target, MS_BIND)
    mount(libc, None, target, MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV)


def drop_privileges(libc):
    # Linux capability v3: two u32 words; set effective/permitted/inheritable to zero.
    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
    class Cap(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32),
                    ('inheritable', ctypes.c_uint32)]
    syscall_ok(libc.prctl(38, 1, 0, 0, 0), 'no_new_privs')
    # Drop bounding set before permitted capabilities. Current kernel cap_last_cap <= 63.
    for cap in range(64):
        result = libc.prctl(24, cap, 0, 0, 0)
        need(result == 0 or ctypes.get_errno() == errno.EINVAL, 'cap_bounding')
    syscall_ok(libc.capset(ctypes.byref(Header(0x20080522, 0)), ctypes.byref((Cap * 2)())), 'capset')


def seccomp_filter(libc, seccomp, controls=False):
    class Comparison(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Comparison)]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    need(ctx, 'seccomp_init')
    try:
        # Unplanned rules kill the process; explicit feature-unavailable rules below
        # use ENOSYS. Native caught EPERM is not a path to a successful actual export.
        # Only no-app kernel selfchecks use observable EPERM, which they assert explicitly.
        default_action = (0x00050000 | errno.EPERM) if controls else 0x80000000
        def rule(name, action=None, comparisons=()):
            action = default_action if action is None else action
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            need(number >= 0, 'seccomp_syscall_' + name)
            values = (Comparison * len(comparisons))(*comparisons)
            need(seccomp.seccomp_rule_add_array(ctx, action, number, len(values), values) == 0,
                 'seccomp_rule_' + name)
        for name in ['socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
                     'sendto', 'sendmsg', 'sendmmsg', 'recvfrom', 'recvmsg', 'recvmmsg',
                     'fork', 'vfork', 'execveat', 'unshare', 'setns', 'mount', 'umount2',
                     'pivot_root', 'chroot', 'ptrace', 'process_vm_readv', 'process_vm_writev',
                     'open_by_handle_at', 'name_to_handle_at', 'bpf', 'userfaultfd',
                     'io_uring_enter', 'io_uring_register', 'setsid', 'setpgid', 'capset']:
            rule(name)
        # Disjoint exhaustive partition: no overlapping general KILL can override
        # the exact feature-denial EPERM. No combination creates any socket/FD.
        rule('socket', 0x00050000 | errno.EPERM, [Comparison(0, 4, 16, 0),
             Comparison(1, 4, 0x80003, 0), Comparison(2, 4, 0, 0)])
        rule('socket', comparisons=[Comparison(0, 1, 16, 0)])
        rule('socket', comparisons=[Comparison(0, 4, 16, 0), Comparison(1, 1, 0x80003, 0)])
        rule('socket', comparisons=[Comparison(0, 4, 16, 0), Comparison(1, 4, 0x80003, 0),
                                    Comparison(2, 1, 0, 0)])
        # SCMP_CMP_MASKED_EQ=7. Reject clone when CLONE_THREAD bit is absent.
        rule('clone', comparisons=[Comparison(0, 7, 0x00010000, 0)])
        rule('clone3', 0x00050000 | errno.ENOSYS)
        # ROOT V5 trace proved this libuv startup feature probe. Denied permanently:
        # ENOSYS grants no ring/FD/I/O. It is an intentional feature-unavailable
        # response, not a claim that every denied native attempt is logged/killed.
        rule('io_uring_setup', 0x00050000 | errno.ENOSYS)
        syscall_ok(libc.prctl(38, 1, 0, 0, 0), 'seccomp_nnp')
        need(seccomp.seccomp_load(ctx) == 0, 'seccomp_load')
    finally:
        seccomp.seccomp_release(ctx)


def kernel_controls(libc, sentinel):
    results = {}
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    response = libc.syscall(ctypes.c_long(41), ctypes.c_int(16), ctypes.c_int(0x80003), ctypes.c_int(0))
    need(response == -1 and ctypes.get_errno() == errno.EPERM, 'kernel_netlink_route_EPERM')
    results['socket_AF_NETLINK_RAW_CLOEXEC_ROUTE'] = errno.EPERM
    ctypes.set_errno(0)
    response = libc.syscall(ctypes.c_long(425), ctypes.c_uint(256), ctypes.c_void_p())
    need(response == -1 and ctypes.get_errno() == errno.ENOSYS, 'kernel_io_uring_setup_ENOSYS')
    results['io_uring_setup'] = errno.ENOSYS
    for number, name in [(426, 'io_uring_enter'), (427, 'io_uring_register')]:
        ctypes.set_errno(0)
        response = libc.syscall(ctypes.c_long(number), ctypes.c_long(-1),
                               ctypes.c_uint(0), ctypes.c_uint(0), ctypes.c_void_p(),
                               ctypes.c_uint(0), ctypes.c_uint(0))
        need(response == -1 and ctypes.get_errno() == errno.EPERM, 'kernel_' + name + '_EPERM')
        results[name] = errno.EPERM
    for name, action in [('socket', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
                         ('fork', os.fork), ('outside', lambda: Path(sentinel).read_bytes())]:
        try:
            action()
        except OSError as error:
            expected = errno.ENOENT if name == 'outside' else errno.EPERM
            need(error.errno == expected, 'kernel_control_errno')
            results[name] = error.errno
        else:
            raise RuntimeError('kernel_control_not_denied')
    # Mandatory shape: x86_64 int/long/pointer and SCMP comparison ABI.
    need(ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(ctypes.c_ulong) == 8, 'libc_abi')
    return results


def jail_process(plan, jail, stage, out, mode, control, sentinel):
    libc = libc_api()
    seccomp = ctypes.CDLL(SECCOMP, use_errno=True)  # loaded before chroot; frozen identity
    uid, gid = os.getuid(), os.getgid()
    syscall_ok(libc.unshare(CLONE_NEWUSER), 'unshare_user')
    Path('/proc/self/setgroups').write_text('deny')
    Path('/proc/self/uid_map').write_text(f'0 {uid} 1\n')
    Path('/proc/self/gid_map').write_text(f'0 {gid} 1\n')
    syscall_ok(libc.unshare(CLONE_NEWNS | CLONE_NEWNET | CLONE_NEWPID | CLONE_NEWIPC), 'unshare_rest')
    mount(libc, None, '/', MS_REC | MS_PRIVATE)
    # 96 MiB private filesystem + 16 MiB staging + 16 MiB evidence = 128 MiB.
    mount(libc, 'tmpfs', jail, MS_NOSUID | MS_NODEV, 'tmpfs', 'size=96m,nr_inodes=6000,mode=0755')
    bind(libc, stage / 'source', jail / 'work/source', True)
    bind(libc, plan['toolroot'], jail / 'work/node_modules', True)
    bind(libc, stage / 'tools', jail / 'tools', True)
    bind(libc, NODE, jail / 'bin/node')
    for info in plan['systemFiles']:
        bind(libc, info['source'], jail / info['target'].lstrip('/'))
    for p in ['tmp', 'home/synthetic', 'evidence', 'denied', 'dev']:
        (jail / p).mkdir(parents=True, exist_ok=True)
    # Only evidence is a writable bind; tmp is bounded private tmpfs. No hostproc.
    mount(libc, out, jail / 'evidence', MS_BIND)
    bind(libc, '/dev/null', jail / 'dev/null')
    (jail / 'denied/sentinel').write_text('synthetic permission control\n')
    (jail / 'tmp/.env').write_text('SYNTHETIC_SENTINEL=not-a-secret\n')
    (jail / 'tmp/probe.node').write_bytes(b'not an addon')
    (jail / 'tmp/fd-read-sentinel').write_bytes(b'support-composition-read-only-fd-v8\n')
    for p in ['uploads', 'dist', 'dist-context']:
        (jail / 'tmp' / p).mkdir()
    (jail / 'tmp/dist/index.html').write_text('<!doctype html><title>synthetic</title>')
    pid = os.fork()  # enters new PID namespace as PID 1; supervisor only
    if pid:
        _, status = os.waitpid(pid, 0)
        os._exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 89)
    os.chroot(jail)
    os.chdir('/work/source')
    drop_privileges(libc)
    # Fork Node before process-creation filter, then apply filter independently.
    nodepid = os.fork()
    if nodepid == 0:
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * MIB, 2 * 1024 * MIB))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        # Decrease with the shared durable-output budget; never raise outer hard limit.
        resource.setrlimit(resource.RLIMIT_FSIZE, (plan['payloadBudgetBytes'], plan['payloadBudgetBytes']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        seccomp_filter(libc, seccomp, controls=mode == 'kernel-controls')
        if mode == 'kernel-controls':
            value = {'status': 'KERNEL_CONTROLS', 'results': kernel_controls(libc, sentinel),
                     'outsideSentinelPath': sentinel}
            Path('/evidence/result.json').write_text(json.dumps(value) + '\n')
            os._exit(0)
        os.execve('/bin/node', node_argv(mode, control), clean_env(plan['variant']))
    _, status = os.waitpid(nodepid, 0)
    child_wait = {'waitStatus': status, 'exited': os.WIFEXITED(status),
                  'exitCode': os.WEXITSTATUS(status) if os.WIFEXITED(status) else None,
                  'signaled': os.WIFSIGNALED(status),
                  'signal': os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
                  'coreDump': os.WCOREDUMP(status) if os.WIFSIGNALED(status) else False}
    wait_bytes = compact(child_wait)
    need(len(wait_bytes) <= 1024, 'child_wait_bound')
    with Path('/evidence/child-wait.json').open('xb') as handle:
        handle.write(wait_bytes)
    # PID1 owns the namespace, reaps any residual descendant; no background jobs allowed.
    while True:
        try:
            child, _ = os.waitpid(-1, os.WNOHANG)
            if child == 0:
                os._exit(90)
        except ChildProcessError:
            break
    os._exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 91)


def bounded_files(root, max_bytes=MAX_OUTPUT, max_entries=191):
    entries = total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        entries += len(dirs) + len(files)
        for name in files:
            p = Path(directory, name)
            need(not p.is_symlink() and p.is_file(), 'scratch_file_shape')
            total += p.stat().st_size
    need(entries <= max_entries and total <= max_bytes, 'scratch_bound')


def disk_floor(directory, admission=False):
    info = os.statvfs(directory)
    free = info.f_bavail * info.f_frsize
    need(free >= 8 * 1024 * MIB + (192 * MIB if admission else 0), 'disk_floor_8GiB')
    return free


def run_one(plan, owned, mode, control, evidence, leaf_name):
    disk_floor(ROOT_EVIDENCE)
    stage, jail, out = [owned / name for name in ['stage', 'jail', 'out']]
    for p in [stage / 'source', stage / 'tools', jail, out]:
        p.mkdir(parents=True)
    source = Path(plan['sourceRoot'])
    for name in [*plan['staticNodes'], 'package.json']:
        target = stage / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    here = Path(__file__).resolve().parent
    for name in plan['helpers']:
        origin = here / ('tests/' + name if name == 'support-composition-negative.mjs' else name)
        shutil.copyfile(origin, stage / 'tools' / name)
    (stage / 'tools/plan.json').write_text(json.dumps(plan, sort_keys=True) + '\n')
    bounded_files(stage, MAX_OUTPUT, 2000)  # + private6000 + evidence191 + sentinel1 <=8192
    # Parent proves this real file exists outside chroot; no host/prod file is used.
    sentinel = owned / 'host-sentinel'
    sentinel_bytes = b'support-composition-owned-host-sentinel-v2\n'
    sentinel.write_bytes(sentinel_bytes)
    sentinel_sha = digest(sentinel)
    need(sentinel.read_bytes() == sentinel_bytes, 'sentinel_parent_before')
    readfd, writefd = os.pipe()
    started = time.monotonic()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            os.close(readfd)
            os.dup2(writefd, 1)
            os.dup2(writefd, 2)
            if writefd > 2:
                os.close(writefd)
            nullfd = os.open('/dev/null', os.O_RDONLY)
            os.dup2(nullfd, 0)
            if nullfd > 2:
                os.close(nullfd)
            os.closerange(3, 65536)
            os.environ.clear()  # source setup must not inherit proxy/Node/Python options
            jail_process(plan, jail, stage, out, mode, control,
                         str(sentinel) if mode == 'kernel-controls' else None)
        except BaseException as error:
            code = error.code if isinstance(error, BoundaryError) else type(error).__name__
            os.write(2, ('SUPPORT_ISOLATION_SETUP_INVALID:' + code + '\n').encode())
            os._exit(88)
    os.close(writefd)
    os.set_blocking(readfd, False)
    selector = selectors.DefaultSelector()
    selector.register(readfd, selectors.EVENT_READ)
    capture = bytearray()
    status = None
    execution_error = None
    try:
        while status is None:
            need(time.monotonic() - started <= 90, 'wall_timeout')
            disk_floor(ROOT_EVIDENCE)
            for key, _ in selector.select(0.1):
                block = os.read(key.fd, 65536)
                if block:
                    capture.extend(block)
                    need(len(capture) <= MAX_OUTPUT, 'stream_output_limit')
                else:
                    selector.unregister(key.fd)
            done, value = os.waitpid(pid, os.WNOHANG)
            if done:
                status = value
            bounded_files(out)
        # Drain bytes written immediately before child exit; retain the same output bound.
        while selector.get_map():
            need(time.monotonic() - started <= 90, 'pipe_drain_timeout')
            for key, _ in selector.select(0.1):
                block = os.read(key.fd, 65536)
                if block:
                    capture.extend(block)
                    need(len(capture) <= MAX_OUTPUT, 'stream_output_limit')
                else:
                    selector.unregister(key.fd)
    except Exception as error:
        execution_error = error
    finally:
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                try:
                    os.kill(pid, signal.SIGKILL)  # child may not have reached setsid yet
                except ProcessLookupError:
                    pass
            _, status = os.waitpid(pid, 0)
        selector.close()
        os.close(readfd)
    parent_after = sentinel.read_bytes() == sentinel_bytes and digest(sentinel) == sentinel_sha
    capture_info = {'waitStatus': status, 'streamBytes': len(capture),
                    'streamSHA256': hashlib.sha256(capture).hexdigest()}
    wait_file = out / 'child-wait.json'
    child_wait = None
    if wait_file.is_file():
        need(wait_file.stat().st_size <= 1024, 'child_wait_bound')
        child_wait = json_read(wait_file)
    capture_info['childWait'] = child_wait
    marker = b'SUPPORT_ISOLATION_SETUP_INVALID:'
    capture_info['setupCodes'] = [line[len(marker):].decode('ascii', 'replace')
                                 for line in capture.splitlines() if line.startswith(marker)]
    # Persist only closed diagnostic enums from the pinned producer, never its
    # arbitrary error text/stack/args. Unknown values map to fixed constants.
    diagnostic_marker = b'SUPPORT_COMPOSITION_INVALID '
    safe_errors = []
    for line in capture.splitlines():
        if not line.startswith(diagnostic_marker):
            continue
        need(len(safe_errors) < 8 and len(line) <= 16384, 'child_diagnostic_bound')
        try:
            detail = json.loads(line[len(diagnostic_marker):])
        except (ValueError, UnicodeError):
            detail = {}
        detail = detail if isinstance(detail, dict) else {}
        def enum_code(value):
            return value if isinstance(value, str) and value in plan['diagnosticEnums']['codes'] else 'UNKNOWN'
        kinds = detail.get('denied', [])
        kinds = kinds if isinstance(kinds, list) and len(kinds) <= 128 else []
        safe_errors.append({'code': enum_code(detail.get('code')),
            'writerCode': None if detail.get('writerCode') is None else enum_code(detail.get('writerCode')),
            'denied': [kind if isinstance(kind, str) and kind in plan['diagnosticEnums']['deniedKinds']
                       else 'UNKNOWN_DENIED_KIND' for kind in kinds]})
    capture_info['safeChildErrors'] = safe_errors
    output_file = out / 'result.json'
    if output_file.is_file():
        need(output_file.stat().st_size <= plan['payloadBudgetBytes'], 'child_file_size')
        raw_result = output_file.read_bytes()
    else:
        raw_result = compact({'status': 'NO_CHILD_OUTPUT', 'capture': capture_info})
    # Preserve complete raw JSON, or an incomplete/invalid raw receipt, before scratch cleanup.
    leaf = evidence.leaf(leaf_name, raw_result)
    capture_info['leaf'] = leaf
    need(parent_after, 'sentinel_parent_after')
    if execution_error:
        raise BoundaryError(execution_error.code if isinstance(execution_error, BoundaryError)
                            else type(execution_error).__name__, capture_info)
    if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
        raise BoundaryError('child_exit', capture_info)
    try:
        result = json.loads(raw_result)
    except (ValueError, UnicodeError):
        raise BoundaryError('invalid_child_json', capture_info) from None
    need(result['status'] in ['EXPORTED_REGISTRATION_ONLY', 'NEGATIVE_CONTROL', 'KERNEL_CONTROLS'], 'invalid_child_receipt')
    if mode == 'export':
        need(result['denied'] == [], 'caught_attempt')
        need(result['readFD']['active'] == 0, 'fd_binding_leak')
        need(result['environmentAudit']['unchanged'] is True
             and result['environmentAudit']['objectIdentityPreserved'] is True, 'env_snapshot_changed')
    elif mode == 'negative':
        if control in ['fd-owned-read', 'env-debug-absent-delete', 'native-interface-feature-denial']:
            need(result['result'].get('positive') is True and result['result']['denied'] is False, 'control_result')
        else:
            need(result['result']['denied'] is True, 'control_result')
        need(len(result['denied']) == (1 if control.startswith('guard-') else 0), 'control_extra_denial')
        need(result['readFD']['active'] == 0, 'fd_binding_leak')
        need(result['environmentAudit']['unchanged'] is True
             and result['environmentAudit']['objectIdentityPreserved'] is True, 'env_snapshot_changed')
    return {'leaf': leaf, 'childStatus': result['status'], 'exit': 0, 'reaped': True,
            'childWait': child_wait,
            'variant': plan['variant'], 'control': control,
            'layerCount': result.get('totalLayers'), 'deniedCount': len(result.get('denied', [])),
            'hostSentinelBeforeAfterSHA256': sentinel_sha,
            'streamBytes': len(capture), 'streamSHA256': hashlib.sha256(capture).hexdigest(),
            'seconds': round(time.monotonic() - started, 3), 'argv': node_argv(mode, control)
            if mode != 'kernel-controls' else None, 'environment': clean_env(plan['variant'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--mode', choices=['negative', 'export'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    global FAILURE_OUTPUT
    global FAILURE_EVIDENCE
    need(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, 'stdlib_isolated_required')
    plan = json_read(args.plan, args.plan_sha256)
    need(args.plan.absolute() == Path(plan['planPath']) and args.plan.resolve() == args.plan.absolute(), 'exact_plan_path')
    need(args.output.absolute() == ROOT_EVIDENCE / (args.mode + '.json')
         and str(ROOT_EVIDENCE) == plan['outputDirectory'], 'exact_output_path')
    need(ROOT_EVIDENCE.resolve() == ROOT_EVIDENCE and not ROOT_EVIDENCE.is_symlink(), 'output_symlink')
    info = ROOT_EVIDENCE.stat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
         and stat.S_IMODE(info.st_mode) == 0o700, 'output_owned0700')
    need(CONTROLS == plan['controls'], 'control_selection_drift')
    need([clean_env(v) for v in plan['variants']] == plan['environments'], 'environment_drift')
    need(node_argv('export') == plan['nodeExportArgv'], 'argv_drift')
    need(not args.output.exists() and not args.output.is_symlink()
         and args.output.parent.is_dir(), 'owned_output_required')
    FAILURE_OUTPUT = args.output
    evidence = CompositionEvidence()
    FAILURE_EVIDENCE = evidence
    expected_leaves = ([f'negative-leaf-{i:02d}-00.json' for i in range(len(CONTROLS) + 1)]
                       if args.mode == 'negative' else [f'export-leaf-00-{i:02d}.json' for i in range(8)])
    need(not any((ROOT_EVIDENCE / name).exists() or (ROOT_EVIDENCE / name).is_symlink()
                 for name in expected_leaves), 'phase_leaf_already_exists')
    need(Path(plan['sourceRoot']).is_absolute() and Path(plan['toolroot']).is_absolute(), 'absolute_roots')
    # No application import and no OS primitives before identities and disk admission.
    source_verify(plan)
    deps_verify(plan)
    tool_verify(plan)
    admission_bytes = disk_floor(ROOT_EVIDENCE, admission=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='support-composition-', dir=args.output.parent) as scratch:
        scratch = Path(scratch)
        selected = [('kernel-controls', None)] + [('negative', x) for x in CONTROLS]
        if args.mode == 'export':
            selected = [('export', None)]
        for index, (mode, control) in enumerate(selected):
            disk_floor(ROOT_EVIDENCE)
            variants = plan['variants'] if mode == 'export' else [plan['variants'][0]]
            for ordinal, variant in enumerate(variants):
                current = dict(plan, variant=variant, payloadBudgetBytes=evidence.admit())
                owned = scratch / f'{index}-{ordinal}'
                owned.mkdir()
                leaf_name = f'{args.mode}-leaf-{index:02d}-{ordinal:02d}.json'
                before_leaves = len(evidence.leaves)
                try:
                    results.append(run_one(current, owned, mode, control, evidence, leaf_name))
                except Exception as error:
                    if len(evidence.leaves) == before_leaves:
                        evidence.leaf(leaf_name, compact({'status': 'BLOCKED_BEFORE_RECEIPT',
                            'code': error.code if isinstance(error, BoundaryError) else type(error).__name__,
                            'variant': variant, 'control': control}))
                    raise
                shutil.rmtree(owned)  # only our unique owned tree; mounts died with namespace
                disk_floor(ROOT_EVIDENCE)
    source_verify(plan)
    deps_verify(plan)
    tool_verify(plan)
    result = {'schemaVersion': 1, 'status': 'ACCEPTANCE_CANDIDATE', 'mode': args.mode,
              'planSHA256': args.plan_sha256, 'sourceAfter': 'equal', 'depsAfter': 'equal',
              'systemAfter': 'equal', 'cleanup': 'owned namespaces exited; owned scratch removed',
              'diskAdmissionFreeBytes': admission_bytes, 'diskAfterFreeBytes': disk_floor(ROOT_EVIDENCE),
              'results': results, 'leaves': evidence.leaves,
              'outputRemainingBytesBeforeFinal': evidence.remaining()}
    evidence.final(args.output, result)


if __name__ == '__main__':
    FAILURE_OUTPUT = None
    FAILURE_EVIDENCE = None
    try:
        main()
    except Exception as error:
        # Deliberately no arbitrary exception text or child streams in public output.
        print('SUPPORT_COMPOSITION_BLOCKED:' + type(error).__name__, file=sys.stderr)
        if FAILURE_OUTPUT is not None and not FAILURE_OUTPUT.exists():
            failure = {'schemaVersion': 1, 'status': 'BLOCKED',
                       'code': error.code if isinstance(error, BoundaryError) else type(error).__name__,
                       'evidence': error.evidence if isinstance(error, BoundaryError) else None,
                       'leaves': FAILURE_EVIDENCE.leaves if FAILURE_EVIDENCE else []}
            if FAILURE_EVIDENCE:
                FAILURE_EVIDENCE.final(FAILURE_OUTPUT, failure)
        raise SystemExit(2)
