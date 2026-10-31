#!/usr/bin/env python3
"""SOURCE ONLY / NOTRUN: trusted external kernel-v1 supervisor.

This file is not a candidate helper and never imports one.  Future execution
requires a separately reviewed configuration, controller/broker/policy/image
pins, a privileged native broker and ROOT's controls.  Merely having this source
does not establish kernel availability, CPython compatibility or safety.
All admission measurements originate in the native bootstrap/broker; candidate
JSON and stdout are workload output, never kernel attestations.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import posixpath
import re
import selectors
import signal
import stat
import struct
import sys
import time


PARENT = "59c23b6561a1417ec11f14a7cbab1701dedef9df"
HELPER = "clearledger/server/tests/partner_dx_metadata_approved.py"
SCHEMA = "clearledger/docs/api/PARTNER_DX_KERNEL_ADMISSION_V1.schema.json"
NATIVE = "/home/mag/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu"
VENV = "/srv/projects/api-modernization-upgrade-test-env-20261030/.venv"
POLICY = "/inputs/policy/execute-policy.json"
ADMISSION = "/inputs/admission/admission.json"
MIB = 1024 ** 2
FLOOR = 8 * 1024 ** 3
JSON_LIMIT = 65536
PROC_LIMIT = 131072
OUTPUT_LIMIT = 8 * MIB
POOL_LIMIT = 64 * MIB
FILE_LIMIT = 16 * MIB
HELPER_SHA = "3129cf75a14575ecf200391fb70db98f7fc1eabb518e6b99c7f35942381d6dfa"
SCHEMA_SHA = "3653efd446bc3f743f29eb85650cf78d4ed871d5cfc25827780a21adf8ac09ed"
TREE_ENTRIES = 20000
TREE_BYTES = 512 * MIB
ROLES = ("rootfs", "source", "native_runtime", "venv", "policy", "admission",
         "cache", "work_pool", "cwd", "upload", "evidence", "scratch")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
PATH_RE = re.compile(r"/[A-Za-z0-9._/-]*\Z")
BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}\Z")
OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class Rejected(Exception):
    """An incomplete observation can never become an accepted final."""


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    def types(item, depth=0):
        require(depth <= 32, "JSON nesting bound")
        if type(item) is dict:
            require(all(type(k) is str and k.isascii() for k in item), "ASCII JSON keys")
            for child in item.values():
                types(child, depth + 1)
        elif type(item) is list:
            require(len(item) <= TREE_ENTRIES, "JSON array bound")
            for child in item:
                types(child, depth + 1)
        elif type(item) is str:
            require(item.isascii(), "ASCII JSON string")
        elif type(item) is int:
            # Native notification cookies are u64. Receipt-specific N fields
            # are independently restricted to signed63 by shape().
            require(0 <= item <= 2 ** 64 - 1, "unsigned JSON integer bound")
        else:
            require(item is None or type(item) is bool, "closed JSON type")
    types(value)
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def unique(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def no_float(_):
    raise Rejected("floating point JSON is forbidden")


def parse(raw, limit=JSON_LIMIT, *, exact=True):
    require(type(raw) is bytes and 0 < len(raw) <= limit, "JSON byte bound")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                           parse_float=no_float, parse_constant=no_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise Rejected("invalid bounded JSON") from error
    if exact:
        require(raw == canonical(value), "noncanonical JSON bytes")
    return value


def keys(value, expected, name):
    require(type(value) is dict and set(value) == set(expected), "closed fields: " + name)
    return value


def number(value, name, maximum=2 ** 63 - 1):
    require(type(value) is int and 0 <= value <= maximum, "integer: " + name)
    return value


def pin(value, name):
    require(type(value) is str and HEX64.fullmatch(value), "SHA256: " + name)
    return value


def path(value):
    require(type(value) is str and PATH_RE.fullmatch(value)
            and posixpath.normpath(value) == value and not value.startswith("//")
            and all(part not in {".", ".."} for part in value.split("/")), "literal absolute path")
    return value


def open_directory(value):
    """Walk every component with O_NOFOLLOW; return an owned descriptor."""
    value = path(value)
    fd = os.open("/", OPEN_DIR)
    try:
        for component in value.split("/")[1:]:
            if component:
                next_fd = os.open(component, OPEN_DIR, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def stable(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_at(parent, name, maximum=FILE_LIMIT):
    require(type(name) is str and name not in {"", ".", ".."} and "/" not in name,
            "single file component")
    fd = os.open(name, OPEN_FILE, dir_fd=parent)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and 0 <= before.st_size <= maximum, "single-link bounded regular file")
        chunks, total = [], 0
        while True:
            block = os.read(fd, min(65536, maximum + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            require(total <= maximum, "read byte bound")
        require(total == before.st_size and stable(before) == stable(os.fstat(fd)), "stable file read")
        return b"".join(chunks), before
    finally:
        os.close(fd)


def read_file(value, maximum=FILE_LIMIT):
    value = path(value)
    parent = open_directory(posixpath.dirname(value))
    try:
        return read_at(parent, posixpath.basename(value), maximum)
    finally:
        os.close(parent)


def inventory_tree(root, *, symlinks=False, exclude=(), maximum=TREE_BYTES):
    """A complete bounded inventory, including empty directories and link text.

    Files are never loaded as modules. Special nodes, directory substitutions,
    hardlinks and symlink traversal are rejected.  The digest covers metadata and
    every byte, not just the application's known subset.
    """
    rows, file_rows, total, entries = [], [], 0, 0
    first = open_directory(root)
    root_info = os.fstat(first)
    stack = [(first, "", 0)]
    try:
        while stack:
            directory, relative, depth = stack.pop()
            try:
                require(depth <= 48, "tree depth bound")
                directory_before = os.fstat(directory)
                names = []
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        entries += 1
                        require(entries <= TREE_ENTRIES, "tree entry bound")
                        names.append(entry.name)
                for name in sorted(names):
                    require(name.isascii() and name not in {"", ".", ".."}
                            and not any(ord(c) < 32 for c in name), "tree component syntax")
                    rel = relative + "/" + name if relative else name
                    if rel in exclude:
                        continue
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    metadata = [rel, format(stat.S_IMODE(info.st_mode), "04o"), info.st_uid, info.st_gid]
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(name, OPEN_DIR, dir_fd=directory)
                        require(stable(info) == stable(os.fstat(child)), "stable directory identity")
                        rows.append(["d", *metadata])
                        stack.append((child, rel, depth + 1))
                    elif stat.S_ISREG(info.st_mode):
                        raw, actual = read_at(directory, name, maximum=min(maximum, 64 * MIB))
                        require(stable(info) == stable(actual), "stable inventory file identity")
                        total += len(raw)
                        require(total <= maximum, "tree total byte bound")
                        value = digest(raw)
                        rows.append(["f", *metadata, len(raw), value])
                        file_rows.append([rel, len(raw), value])
                    elif stat.S_ISLNK(info.st_mode) and symlinks:
                        target = os.readlink(name, dir_fd=directory)
                        require(target.isascii() and 0 < len(target) <= 4096
                                and "\0" not in target and stable(info) == stable(os.stat(
                                    name, dir_fd=directory, follow_symlinks=False)), "stable pinned symlink")
                        rows.append(["l", *metadata, target])
                    else:
                        raise Rejected("special node/symlink in inventory: " + rel)
                require(stable(directory_before) == stable(os.fstat(directory)), "directory changed during inventory")
            finally:
                os.close(directory)
        rows.sort()
        file_rows.sort()
        manifest = {"format": "elsy.partner-dx.tree.v1", "root_mode": format(stat.S_IMODE(root_info.st_mode), "04o"),
                    "root_uid": root_info.st_uid, "root_gid": root_info.st_gid, "rows": rows,
                    "files": len(file_rows), "bytes": total}
        return manifest, file_rows
    finally:
        for pending, _, _ in stack:
            os.close(pending)


def tree_sha(root, **kwargs):
    manifest, files = inventory_tree(root, **kwargs)
    return digest(canonical(manifest)), manifest, files


def helper_literals(raw):
    """Read literal manifests through stdlib AST; never import/call the helper."""
    wanted = {"FROZEN", "SUPPORT", "PINNED_DISTRIBUTIONS", "FROZEN_SITE", "VENV_CFG_SHA",
              "KERNEL_SHAPES", "KERNEL_PATTERNS"}
    found = {}
    try:
        module = ast.parse(raw, filename=HELPER)
        for node in module.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in wanted:
                    require(name not in found, "duplicate helper manifest")
                    found[name] = ast.literal_eval(node.value)
    except (SyntaxError, ValueError, TypeError, RecursionError) as error:
        raise Rejected("helper literal manifest parse") from error
    require(set(found) == wanted, "all frozen literal manifests present")
    return found


def verify_frozen(source, native, venv, helper_raw):
    literals = helper_literals(helper_raw)
    bindings = {}
    for name, expected in literals["FROZEN"].items():
        _, rows = inventory_tree(source + "/clearledger/server/" + name,
                                 exclude=("partner_dx_metadata_approved.py",) if name == "tests" else ())
        rows = [[name + "/" + rel, size, sha] for rel, size, sha in rows]
        actual = {"count": len(rows), "bytes": sum(row[1] for row in rows),
                  "sha256": digest(json.dumps(rows, separators=(",", ":")).encode("ascii"))}
        require(actual == expected, "immutable helper frozen tree: " + name)
        bindings[{"app": "app_sha256", "tests": "tests_sha256",
                  "schema_migrations": "migrations_sha256"}[name]] = actual["sha256"]
    for relative, expected in literals["SUPPORT"].items():
        require(type(relative) is str and not relative.startswith("/") and ".." not in relative.split("/"),
                "support relative path")
        require(digest(read_file(source + "/" + relative)[0]) == expected, "immutable support bytes")
    _, rows = inventory_tree(venv + "/lib/python3.13/site-packages")
    site = {"count": len(rows), "bytes": sum(row[1] for row in rows),
            "sha256": digest(json.dumps(rows, separators=(",", ":")).encode("ascii"))}
    require(site == literals["FROZEN_SITE"], "immutable full installed site")
    require(digest(read_file(venv + "/pyvenv.cfg")[0]) == literals["VENV_CFG_SHA"], "immutable venv config")
    # The complete native runtime is separately inventoried and pinned; frozen
    # SITE alone does not cover the ELF interpreter, loader or stdlib.
    require(path(native) and path(venv), "runtime paths")
    bindings.update(native_site_sha256=site["sha256"],
                    support_sha256=digest(canonical(literals["SUPPORT"])),
                    versions_sha256=digest(canonical(literals["PINNED_DISTRIBUTIONS"])))
    return bindings


def shape(value, kind, literals):
    """Interpret immutable literal *data*; execute no helper/validator code."""
    if type(kind) is str and kind in literals["KERNEL_SHAPES"]:
        fields = literals["KERNEL_SHAPES"][kind]
        keys(value, fields, kind)
        for key, item in fields.items():
            shape(value[key], item, literals)
    elif kind == "N":
        number(value, "N")
    elif kind == "Bool":
        require(type(value) is bool, "boolean")
    elif type(kind) is str and kind in literals["KERNEL_PATTERNS"]:
        require(type(value) is str and value.isascii()
                and re.fullmatch(literals["KERNEL_PATTERNS"][kind], value), "pattern: " + kind)
        if kind == "P":
            path(value)
    elif type(kind) is tuple and kind[0] == "const":
        require(type(value) is type(kind[1]) and value == kind[1], "exact typed constant")
    elif type(kind) is tuple and kind[0] == "enum":
        require(type(value) is str and value in kind[1], "exact enum")
    elif type(kind) is tuple and kind[0] == "ascii":
        require(type(value) is str and value.isascii() and kind[1] <= len(value) <= kind[2], "ASCII length")
    elif type(kind) is tuple and kind[0] == "list":
        require(type(value) is list and kind[2] <= len(value) <= kind[3], "list cardinality")
        for item in value:
            shape(item, kind[1], literals)
    else:
        raise Rejected("unknown immutable type grammar")


# This order is part of launcher_protocol.h, not dict iteration order.
CONFIG_FIELDS = (
    "rootfs", "source", "native_runtime", "venv", "cache_host", "cache_guest",
    "policy_host", "pool", "home", "uid", "gid", "source_git_dir",
    "source_git_common_dir", "storage_path", "storage_id", "python_sha256",
    "policy_sha256", "rootfs_digest", "runner_sha256", "source_head",
    "source_branch", "controller_sha256", "admission_host", "cgroup_parent",
    "host_evidence_dir",
)
CONFIG_PATHS = set(CONFIG_FIELDS) - {
    "uid", "gid", "storage_id", "python_sha256", "policy_sha256", "rootfs_digest",
    "runner_sha256", "source_head", "source_branch", "controller_sha256",
}
PIN_FIELDS = {"launcher_sha256", "controller_sha256", "source_tree_sha256",
              "native_tree_sha256", "venv_tree_sha256", "rootfs_tree_sha256",
              "cache_sha256", "policy_sha256", "runner_sha256", "python_sha256",
              "schema_sha256"}


def private_directory(value, uid, *, empty=False):
    fd = open_directory(value)
    try:
        info = os.fstat(fd)
        require(info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700, "private owned0700 directory")
        if empty:
            with os.scandir(fd) as entries:
                require(next(entries, None) is None, "initially empty directory")
        return info
    finally:
        os.close(fd)


def sealed_input(value, uid, mode, expected):
    private_directory(posixpath.dirname(path(value)), uid)
    parent = open_directory(posixpath.dirname(value))
    try:
        with os.scandir(parent) as entries:
            first = next(entries, None)
            require(first is not None and first.name == posixpath.basename(value)
                    and next(entries, None) is None, "singleton sealed input parent; no unpinned siblings")
    finally:
        os.close(parent)
    raw, info = read_file(value)
    require(info.st_uid == uid and stat.S_IMODE(info.st_mode) == mode
            and digest(raw) == expected, "sealed input identity/mode/hash")
    return raw


def git_provenance(config):
    """Read Git reference bytes only; candidate never receives Git directories."""
    git_dir, common = config["source_git_dir"], config["source_git_common_dir"]
    raw, _ = read_file(git_dir + "/HEAD", 4096)
    expected_ref = "refs/heads/" + config["source_branch"]
    require(raw == ("ref: " + expected_ref + "\n").encode("ascii"), "actual source branch HEAD")
    try:
        actual, _ = read_file(common + "/" + expected_ref, 128)
        require(actual == (config["source_head"] + "\n").encode("ascii"), "actual loose source HEAD")
    except FileNotFoundError:
        packed, _ = read_file(common + "/packed-refs", FILE_LIMIT)
        matches = [line for line in packed.decode("ascii").splitlines()
                   if line and not line.startswith(("#", "^")) and line.split(" ")[-1] == expected_ref]
        require(matches == [config["source_head"] + " " + expected_ref], "actual packed source HEAD")
    # Source completeness is established by the independent complete snapshot
    # pin plus frozen manifests, not a claim that reading HEAD proves clean Git.


def load_config(filename, expected):
    raw, _ = read_file(filename, JSON_LIMIT)
    require(digest(raw) == pin(expected, "config"), "independent config byte pin")
    config = parse(raw)
    keys(config, {"format", "native", "pins", "launcher", "nonce_dir", "final_dir"}, "controller config")
    require(config["format"] == "elsy.partner-dx.controller-config.v1", "config version")
    native = keys(config["native"], CONFIG_FIELDS, "native config")
    pins = keys(config["pins"], PIN_FIELDS, "independent pins")
    for name, value in pins.items():
        pin(value, name)
    for name in CONFIG_FIELDS:
        value = native[name]
        require(type(value) is str and value.isascii() and 0 < len(value) <= 4095
                and "\0" not in value, "native config ASCII strings")
        if name in CONFIG_PATHS:
            path(value)
        elif name.endswith("_sha256"):
            pin(value, name)
    for name in ("uid", "gid"):
        require(re.fullmatch(r"[1-9][0-9]*", native[name]) and int(native[name]) <= 2 ** 32 - 2,
                "nonzero native identity")
    require(len(native["storage_id"]) <= 128 and all(32 <= ord(c) < 127 for c in native["storage_id"]), "storage ID")
    require(native["source_head"] == PARENT and HEX40.fullmatch(native["source_head"])
            and BRANCH_RE.fullmatch(native["source_branch"]), "exact PR91 provenance")
    require(native["native_runtime"] == NATIVE and native["venv"] == VENV, "fixed helper runtime paths")
    require(native["rootfs_digest"] == "sha256:" + pins["rootfs_tree_sha256"], "independently pinned image digest")
    for key in ("runner_sha256", "policy_sha256", "controller_sha256", "python_sha256"):
        require(native[key] == pins[key], "native/independent pin binding")
    require(pins["runner_sha256"] == HELPER_SHA and pins["schema_sha256"] == SCHEMA_SHA, "immutable PR91 helper/schema")
    for name in ("launcher", "nonce_dir", "final_dir"):
        path(config[name])
    # Inputs, pool, output and bookkeeping are independently named. No output
    # may be hidden under an input or become another candidate writable mount.
    separate = [native[k] for k in ("rootfs", "source", "native_runtime", "venv", "pool",
                                    "host_evidence_dir")] + [config["nonce_dir"], config["final_dir"]]
    for index, left in enumerate(separate):
        for right in separate[index + 1:]:
            require(left != right and not left.startswith(right.rstrip("/") + "/")
                    and not right.startswith(left.rstrip("/") + "/"), "nonnested input/output roots")
    require(os.geteuid() == 0, "privileged trusted controller required outside candidate")
    private_directory(native["host_evidence_dir"], 0, empty=True)
    private_directory(config["nonce_dir"], 0)
    private_directory(config["final_dir"], 0, empty=True)
    return config


def check_storage(config):
    native = config["native"]
    fd = open_directory(native["storage_path"])
    try:
        info, capacity = os.fstat(fd), os.fstatvfs(fd)
        require(os.major(info.st_dev) != 0, "physical block-backed storage only; virtual/overlay unsupported")
        require(capacity.f_bavail * capacity.f_frsize >= FLOOR, "physical free8GiB before")
        for value in (native["rootfs"], native["source"], native["native_runtime"], native["venv"],
                      posixpath.dirname(native["cache_host"]), posixpath.dirname(native["policy_host"]),
                      posixpath.dirname(native["admission_host"]), native["host_evidence_dir"],
                      config["nonce_dir"], config["final_dir"]):
            other = open_directory(value)
            try:
                require(os.fstat(other).st_dev == info.st_dev, "all physical input/evidence stores covered")
            finally:
                os.close(other)
        return {"device": info.st_dev, "free_bytes": capacity.f_bavail * capacity.f_frsize}
    finally:
        os.close(fd)


def immutable_inputs(config):
    native, pins = config["native"], config["pins"]
    source = native["source"]
    helper_raw = read_file(source + "/" + HELPER)[0]
    require(digest(helper_raw) == pins["runner_sha256"], "actual PR91 helper bytes")
    require(digest(read_file(source + "/" + SCHEMA)[0]) == pins["schema_sha256"], "actual PR91 schema bytes")
    own_raw, _ = read_file(path(os.path.abspath(__file__)), FILE_LIMIT)
    require(digest(own_raw) == pins["controller_sha256"], "independent complete controller source pin")
    launcher_raw, launcher_info = read_file(config["launcher"], 64 * MIB)
    require(launcher_raw[:4] == b"\x7fELF" and digest(launcher_raw) == pins["launcher_sha256"]
            and launcher_info.st_uid == 0 and not launcher_info.st_mode & 0o022
            and launcher_info.st_mode & 0o111 and not launcher_info.st_mode & 0o6000, "trusted pinned launcher ELF")
    # The venv's deliberate interpreter alias is the explicit historical
    # exception. Resolve a bounded pinned chain, including relative link text;
    # do not assume that bin/python points directly at the native ELF.
    verify_interpreter_alias()
    python_raw, _ = read_file(NATIVE + "/bin/python3.13", 64 * MIB)
    require(python_raw[:4] == b"\x7fELF" and digest(python_raw) == pins["python_sha256"], "actual interpreter ELF pin")
    uid = int(native["uid"])
    policy_raw = sealed_input(native["policy_host"], uid, 0o400, pins["policy_sha256"])
    # A policy is independently pinned data. Parsing it does not prove that its
    # BPF program has actually been installed: that is a native proof obligation.
    parse(policy_raw, FILE_LIMIT)
    cache_raw = sealed_input(native["cache_host"], uid, 0o600, pins["cache_sha256"])
    cache = parse(cache_raw, FILE_LIMIT, exact=False)
    require(type(cache) is dict and cache.get("runner_sha256") == pins["runner_sha256"]
            and type(cache.get("source")) is dict
            and cache["source"].get("head") == native["source_head"]
            and cache["source"].get("branch") == native["source_branch"]
            and cache.get("runtime_execution") == 0, "prepared cache provenance")
    for directory, files in (inventory_tree(source),):
        require(not any(rel == ".git" or rel.startswith(".git/") or any(
            part in {".ssh", ".vault", ".claude", ".env"} or part.startswith(".env.")
            for part in rel.split("/")) for rel, _, _ in files), "no Git/config/secrets in source copy")
        # Directory rows also detect an empty .git or secret directory.
        require(not any(any(part in {".git", ".ssh", ".vault", ".claude", ".env"}
                            or part.startswith(".env.") for part in row[1].split("/"))
                        for row in directory["rows"]), "no hidden source directories")
    signatures, manifests = {}, {}
    for key, root, links in (("source", source, False), ("native", native["native_runtime"], True),
                             ("venv", native["venv"], True), ("rootfs", native["rootfs"], True)):
        signature, manifest, _ = tree_sha(root, symlinks=links)
        require(signature == pins[key + "_tree_sha256"], "complete independently pinned tree: " + key)
        signatures[key] = signature
        manifests[key] = manifest
    verify_guest_links(native, manifests)
    bindings = verify_frozen(source, native["native_runtime"], native["venv"], helper_raw)
    bindings.update(runner_sha256=pins["runner_sha256"], source_head=native["source_head"],
                    source_branch=native["source_branch"], prepared_cache_sha256=pins["cache_sha256"],
                    policy_sha256=pins["policy_sha256"], controller_sha256=pins["controller_sha256"],
                    image_digest=native["rootfs_digest"])
    git_provenance(native)
    return signatures, bindings, helper_literals(helper_raw)


def verify_interpreter_alias():
    current = VENV + "/bin/python"
    expected = NATIVE + "/bin/python3.13"
    seen = set()
    for _ in range(8):
        require(current not in seen and (current == expected or current.startswith(VENV + "/bin/")),
                "interpreter chain stays in pinned venv bin until exact native ELF")
        seen.add(current)
        parent = open_directory(posixpath.dirname(path(current)))
        try:
            name = posixpath.basename(current)
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISREG(before.st_mode):
                require(current == expected and before.st_nlink == 1, "exact final native interpreter inode")
                return
            require(stat.S_ISLNK(before.st_mode) and current != expected, "bounded interpreter alias link")
            target = os.readlink(name, dir_fd=parent)
            require(target.isascii() and "\0" not in target and 0 < len(target) <= 4095
                    and stable(before) == stable(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                    "stable interpreter link text")
            current = posixpath.normpath(target if target.startswith("/") else
                                         posixpath.join(posixpath.dirname(current), target))
        finally:
            os.close(parent)
    raise Rejected("interpreter alias depth/cycle")


def verify_guest_links(native, manifests):
    """Resolve pinned link text against the final guest input map, never host /.

    This explicit image/runtime exception does not weaken no-symlink guards on
    source, site, admission, cache or any candidate work directory.
    """
    mappings = [("/", native["rootfs"]), (native["native_runtime"], native["native_runtime"]),
                (native["venv"], native["venv"]), (native["source"], native["source"])]
    blocked = ("/proc", "/dev", "/inputs", native["pool"], native["cache_guest"])
    for name in ("rootfs", "native", "venv"):
        guest_base = {"rootfs": "/", "native": native["native_runtime"], "venv": native["venv"]}[name]
        for row in manifests[name]["rows"]:
            if row[0] != "l":
                continue
            pending = posixpath.join(guest_base, row[1])
            for _ in range(33):
                require(not any(pending == b or pending.startswith(b.rstrip("/") + "/") for b in blocked),
                        "runtime symlink target outside immutable image/runtime")
                components = pending.split("/")[1:]
                restart = False
                for index in range(len(components)):
                    guest = "/" + "/".join(components[:index + 1])
                    options = [(left, right) for left, right in mappings
                               if guest == left or guest.startswith(left.rstrip("/") + "/")]
                    left, right = max(options, key=lambda pair: len(pair[0]))
                    host = right.rstrip("/") + guest[len(left):] if left != "/" else right.rstrip("/") + guest
                    parent = open_directory(posixpath.dirname(host))
                    try:
                        info = os.stat(posixpath.basename(host), dir_fd=parent, follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            target = os.readlink(posixpath.basename(host), dir_fd=parent)
                            require(target.isascii() and "\0" not in target and 0 < len(target) <= 4096, "guest link text")
                            resolved = target if target.startswith("/") else posixpath.join(posixpath.dirname(guest), target)
                            pending = posixpath.normpath(posixpath.join(resolved, *components[index + 1:]))
                            path(pending)
                            restart = True
                            break
                        require(stat.S_ISDIR(info.st_mode) if index < len(components) - 1 else (
                            stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)), "guest link resolves to regular image inode")
                    finally:
                        os.close(parent)
                if not restart:
                    break
            else:
                raise Rejected("guest runtime symlink cycle/depth")


HEADER = struct.Struct("<4sHHII")
FRAME_LIMIT = 2 * MIB
META_LIMIT = 4 * MIB
CONFIG, READY, SEAL, EXEC, STDOUT, STDERR, EXIT, ERROR, CANCEL = range(1, 10)
FINALIZE, FINAL = 10, 11
RESERVATION_BYTES = OUTPUT_LIMIT + META_LIMIT + 2 * JSON_LIMIT


def lp(value):
    require(type(value) is str and value.isascii() and "\0" not in value
            and 0 < len(value) <= 4095, "wire string bound")
    raw = value.encode("ascii")
    return struct.pack("<I", len(raw)) + raw


def config_bytes(native):
    return struct.pack("<I", len(CONFIG_FIELDS)) + b"".join(lp(native[name]) for name in CONFIG_FIELDS)


def environment(config, a, raw):
    n = config["native"]
    env = {"ROOT_APPROVED_PARTNER_DX": "1", "RUN_PARTNER_DX_METADATA": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "HOME": n["home"], "DX_RUNNER_SHA256": n["runner_sha256"],
           "DX_SOURCE_HEAD": n["source_head"], "DX_SOURCE_BRANCH": n["source_branch"],
           "DX_PREPARED_CACHE": n["cache_guest"], "DX_PREPARED_CACHE_SHA256": config["pins"]["cache_sha256"],
           "DX_EXECUTION_MODE": "kernel-controlled-v1", "DX_ADMISSION_RECEIPT": ADMISSION,
           "DX_ADMISSION_RECEIPT_SHA256": digest(raw), "DX_WORKLOAD_NONCE": a["nonce"],
           "DX_KERNEL_POLICY_SHA256": n["policy_sha256"], "DX_EXPECTED_UID": n["uid"],
           "DX_EXPECTED_GID": n["gid"]}
    for key, suffix in (("DX_EMPTY_CWD", "cwd"), ("DX_UPLOAD_DIR", "upload"),
                        ("DX_EVIDENCE_DIR", "evidence"), ("DX_SCRATCH_DIR", "scratch")):
        env[key] = n["pool"] + "/" + suffix
    require(len(env) == 24, "closed kernel environment size")
    return env


def seal_bytes(raw, env):
    require(0 < len(raw) <= JSON_LIMIT, "admission frame bound")
    return (struct.pack("<I", len(raw)) + raw + struct.pack("<I", len(env))
            + b"".join(lp(key) + lp(env[key]) for key in sorted(env)))


class Broker:
    """Bounded transport; only native events authorize state transitions."""
    def __init__(self, config):
        self.pid = None
        self.status = None
        self.tx = self.rx = 0
        self.buffer = bytearray()
        self.metadata = self.output_bytes = 0
        self.output_hash = hashlib.sha256()
        self.transcript_hash = hashlib.sha256()
        self.err = bytearray()
        self.eof = False
        self.selector = selectors.DefaultSelector()
        self.write_fd = self.read_fd = self.error_fd = None
        fds = []
        try:
            for _ in range(3):
                fds.extend(os.pipe2(os.O_CLOEXEC))
            child_in, parent_write, parent_read, child_out, parent_error, child_error = fds
            binary_parent = open_directory(posixpath.dirname(config["launcher"]))
            try:
                executable = os.open(posixpath.basename(config["launcher"]), OPEN_FILE, dir_fd=binary_parent)
            finally:
                os.close(binary_parent)
            try:
                info = os.fstat(executable)
                require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                        and info.st_size <= 64 * MIB and not info.st_mode & 0o6022, "pinned spawn executable identity")
                hasher = hashlib.sha256()
                while True:
                    block = os.read(executable, 65536)
                    if not block:
                        break
                    hasher.update(block)
                require(hasher.hexdigest() == config["pins"]["launcher_sha256"]
                        and stable(info) == stable(os.fstat(executable)), "pinned spawn executable bytes")
                actions = [(os.POSIX_SPAWN_DUP2, child_in, 0), (os.POSIX_SPAWN_DUP2, child_out, 1),
                           (os.POSIX_SPAWN_DUP2, child_error, 2)]
                actions.extend((os.POSIX_SPAWN_CLOSE, fd) for fd in fds if fd > 2)
                self.pid = os.posix_spawn("/proc/self/fd/" + str(executable),
                                         [config["launcher"], "--broker-v1"], {}, file_actions=actions,
                                         setsid=True, setsigmask=(),
                                         setsigdef=(signal.SIGPIPE, signal.SIGTERM, signal.SIGINT))
            finally:
                os.close(executable)
            self.write_fd, self.read_fd, self.error_fd = parent_write, parent_read, parent_error
            for fd in (child_in, child_out, child_error):
                os.close(fd)
                fds.remove(fd)
            for fd in (self.write_fd, self.read_fd, self.error_fd):
                os.set_blocking(fd, False)
            self.selector.register(self.read_fd, selectors.EVENT_READ, "protocol")
            self.selector.register(self.error_fd, selectors.EVENT_READ, "error")
        except BaseException:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self.kill()
            raise

    def send(self, opcode, payload):
        require(opcode in {CONFIG, SEAL, CANCEL, FINALIZE} and len(payload) <= FRAME_LIMIT, "outbound frame")
        self.tx += 1
        require(self.tx < 2 ** 32, "outbound sequence overflow")
        raw = HEADER.pack(b"DXK1", 1, opcode, len(payload), self.tx) + payload
        deadline = time.monotonic_ns() + 5_000_000_000
        offset = 0
        while offset < len(raw):
            require(time.monotonic_ns() < deadline, "bounded command write deadline")
            try:
                offset += os.write(self.write_fd, raw[offset:])
            except BlockingIOError:
                # Always drain while writing; a full native metadata queue must
                # not deadlock against a full command pipe.
                self.drain(0.01)
        self.transcript_hash.update(b"A" + raw)

    def drain(self, timeout):
        for event, _ in self.selector.select(timeout):
            fd, kind = event.fd, event.data
            block = os.read(fd, 65536)
            if not block:
                self.selector.unregister(fd)
                if kind == "protocol":
                    self.eof = True
                continue
            if kind == "error":
                self.err.extend(block)
                require(len(self.err) <= JSON_LIMIT, "trusted stderr cap")
                # A successful broker uses framed ERROR. Unframed diagnostics
                # remain bounded and cannot be mistaken for trusted evidence.
                require(False, "unexpected native stderr")
            else:
                self.buffer.extend(block)
                require(len(self.buffer) <= FRAME_LIMIT + HEADER.size + 65536, "bounded pending frame buffer")

    def next(self, deadline_ms):
        while True:
            if len(self.buffer) >= HEADER.size:
                magic, version, opcode, length, sequence = HEADER.unpack_from(self.buffer)
                require(magic == b"DXK1" and version == 1 and opcode in {READY, EXEC, STDOUT, STDERR, EXIT, ERROR, FINAL}
                        and length <= FRAME_LIMIT and sequence == self.rx + 1, "closed native frame header/sequence")
                if len(self.buffer) >= HEADER.size + length:
                    raw = bytes(self.buffer[:HEADER.size + length])
                    payload = raw[HEADER.size:]
                    del self.buffer[:len(raw)]
                    self.rx = sequence
                    self.transcript_hash.update(b"B" + raw)
                    if opcode in {STDOUT, STDERR}:
                        require(0 < length <= 16384, "native output chunk")
                        self.output_bytes += length
                        require(self.output_bytes <= OUTPUT_LIMIT, "combined stdout/stderr cap")
                        self.output_hash.update(payload)
                    else:
                        self.metadata += length
                        require(self.metadata <= META_LIMIT, "native cumulative metadata cap")
                    return opcode, payload
            require(not self.eof, "native protocol EOF before complete terminal evidence")
            require(time.monotonic_ns() // 1_000_000 <= deadline_ms, "external transport deadline")
            self.drain(0.1)

    def finish(self):
        deadline = time.monotonic_ns() // 1_000_000 + 5000
        while not self.eof:
            require(time.monotonic_ns() // 1_000_000 <= deadline, "broker did not close after EXIT")
            self.drain(0.05)
        require(not self.buffer and not self.err, "bytes after terminal frame")
        while self.status is None:
            pid, status_value = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = status_value
                break
            require(time.monotonic_ns() // 1_000_000 <= deadline, "broker wait deadline")
            self.selector.select(0.01)
        require(os.WIFEXITED(self.status) and os.WEXITSTATUS(self.status) == 0, "native broker exit0")

    def kill(self):
        if self.pid is not None and self.status is None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic_ns() + 5_000_000_000
            while time.monotonic_ns() < deadline:
                try:
                    pid, status_value = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid:
                    self.status = status_value
                    break
                time.sleep(0.01)

    def close(self):
        self.selector.close()
        for fd in (self.write_fd, self.read_fd, self.error_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def mountinfo(raw):
    require(type(raw) is str and raw.isascii() and 0 < len(raw) <= PROC_LIMIT, "raw mountinfo bound")
    mounts = {}
    def unescape(value):
        require(re.search(r"\\(?!040|011|012|134)", value) is None, "mountinfo octal escapes")
        return re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), value)
    for line in raw.splitlines():
        cells = line.split(" ")
        require(cells.count("-") == 1 and all(cells), "mountinfo delimiter")
        separator = cells.index("-")
        require(separator >= 6 and len(cells) == separator + 4, "complete mountinfo row")
        numbers = [cells[0], cells[1], *cells[2].split(":")]
        require(len(numbers) == 4 and all(re.fullmatch(r"0|[1-9][0-9]*", v) for v in numbers), "mountinfo numeric fields")
        mount_id, _, major, minor = map(int, numbers)
        require(mount_id > 0 and mount_id not in mounts, "unique mount ID")
        flags = cells[5].split(",")
        require(("ro" in flags) != ("rw" in flags) and len(set(flags)) == len(flags), "mount ro/rw")
        root, point = (path(unescape(v)) for v in cells[3:5])
        mounts[mount_id] = {"mount_id": mount_id, "major": major, "minor": minor,
                            "root": root, "mount_point": point, "fs_type": cells[separator + 1],
                            "read_only": "ro" in flags, "superoptions": cells[separator + 3].split(",")}
    require(mounts, "nonempty actual mountinfo")
    return mounts


def ready_admission(ready, config, bindings, literals, nonce):
    keys(ready, {"candidate", "namespaces", "mounts", "quota", "host_floor", "controller", "runtime"}, "READY")
    runtime = keys(ready["runtime"], {"mountinfo_base64", "status_base64", "python_sha256", "policy_sha256", "rootfs_digest",
                    "reservation_bytes", "reservation_entries", "rlimits", "cgroup",
                    "pool_capacity_bytes", "pool_files"}, "READY runtime")
    n = config["native"]
    for key in ("python_sha256", "policy_sha256", "rootfs_digest"):
        require(runtime[key] == n[key], "native measured/independent runtime pin: " + key)
    require(runtime["reservation_bytes"] == RESERVATION_BYTES and runtime["reservation_entries"] == 4,
            "physical output/metadata/final reservations")
    require(0 < number(runtime["pool_capacity_bytes"], "pool capacity") <= POOL_LIMIT
            and 0 < number(runtime["pool_files"], "pool inodes") <= 133, "actual total tmpfs capacity")
    expected_limits = {"CPU": [150, 150], "AS": [2 * 1024 ** 3] * 2,
                       "FSIZE": [FILE_LIMIT] * 2, "CORE": [0, 0], "NOFILE": [96, 96]}
    require(type(runtime["rlimits"]) is dict and runtime["rlimits"] == expected_limits, "actual hard/soft rlimits")
    for values in runtime["rlimits"].values():
        require(type(values) is list and len(values) == 2, "limit pair")
        for item in values:
            number(item, "actual limit")
    require(type(runtime["cgroup"]) is dict and runtime["cgroup"] == {
        "memory_max_bytes": 2 * 1024 ** 3, "memory_swap_max_bytes": 0, "pids_max": 1}, "actual cgroup limits")
    for item in runtime["cgroup"].values():
        number(item, "actual cgroup limit")
    decoded = {}
    for name in ("mountinfo", "status"):
        value = runtime[name + "_base64"]
        require(type(value) is str and value.isascii() and len(value) <= 4 * ((PROC_LIMIT + 2) // 3), "bounded base64 proc")
        try:
            raw = base64.b64decode(value, validate=True)
            require(0 < len(raw) <= PROC_LIMIT and base64.b64encode(raw).decode("ascii") == value, "canonical bounded proc base64")
            decoded[name] = raw.decode("ascii")
        except (ValueError, UnicodeError) as error:
            raise Rejected("invalid native proc base64") from error
    raw_status = decoded["status"]
    require(type(raw_status) is str and raw_status.isascii() and 0 < len(raw_status) <= PROC_LIMIT, "raw proc status")
    status_fields = {}
    for line in raw_status.splitlines():
        key, separator, value = line.partition(":")
        require(separator and key not in status_fields, "complete unique status fields")
        status_fields[key] = value.strip()
    require(status_fields.get("Uid", "").split() == [n["uid"]] * 4
            and status_fields.get("Gid", "").split() == [n["gid"]] * 4
            and status_fields.get("Groups") == "" and status_fields.get("Threads") == "1"
            and status_fields.get("NoNewPrivs") == "1" and status_fields.get("Seccomp") == "2", "actual candidate identity/thread/filter")
    for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        require(status_fields.get(key) == "0000000000000000", "actual empty capability set")
    now = time.monotonic_ns() // 1_000_000
    admission = {"format": "elsy.partner-dx.kernel-admission.v1", "phase": "ADMISSION",
                 "clock": "CLOCK_MONOTONIC_MS", "nonce": nonce, "issued_ms": now, "expires_ms": now + 30000,
                 "bindings": bindings, **{key: ready[key] for key in (
                     "candidate", "namespaces", "mounts", "quota", "host_floor", "controller")}}
    shape(admission, "A", literals)
    require(admission["candidate"]["uid"] == int(n["uid"])
            and admission["candidate"]["gid"] == int(n["gid"])
            and admission["candidate"]["home"] == n["home"], "A candidate matches config")
    namespaces = admission["namespaces"]
    for name in ("mnt", "net", "pid", "ipc", "user", "time"):
        require((namespaces[name] == namespaces["controller_" + name]) == (name in {"user", "time"}),
                "actual shared/separate namespace: " + name)
    mounts = mountinfo(decoded["mountinfo"])
    require(digest(decoded["mountinfo"].encode("ascii")) == namespaces["mountinfo_sha256"], "whole final mountinfo hash")
    role_paths = {"rootfs": "/", "source": n["source"], "native_runtime": NATIVE, "venv": VENV,
                  "cache": n["cache_guest"], "policy": POLICY, "admission": ADMISSION, "work_pool": n["pool"]}
    role_paths.update({role: n["pool"] + "/" + role for role in ("cwd", "upload", "evidence", "scratch")})
    roles = {row["role"]: row for row in admission["mounts"]}
    require(len(roles) == 12 and set(roles) == set(ROLES), "exact twelve roles")
    for role, row in roles.items():
        require(row["path"] == role_paths[role], "exact role path")
        covering = [item for item in mounts.values() if row["path"] == item["mount_point"]
                    or row["path"].startswith(item["mount_point"].rstrip("/") + "/")]
        require(covering, "role mount coverage")
        longest = max(len(item["mount_point"]) for item in covering)
        selected = [item for item in covering if len(item["mount_point"]) == longest]
        require(len(selected) == 1 and all(row[key] == selected[0][key] for key in (
            "mount_id", "major", "minor", "root", "mount_point", "fs_type", "read_only")), "actual most-specific role mount")
        require(row["read_only"] is (role not in {"work_pool", "evidence", "scratch"}), "exact role RO/RW")
        if role in {"cwd", "upload", "evidence", "scratch", "policy", "admission", "cache"}:
            expected_mode = "0700" if role in {"cwd", "upload", "evidence", "scratch"} else (
                "0600" if role == "cache" else "0400")
            require(row["owner_uid"] == int(n["uid"]) and row["mode"] == expected_mode, "actual private role ownership/mode")
    pool = roles["work_pool"]
    require(pool["fs_type"] == "tmpfs" and pool["owner_uid"] == 0 and pool["mode"] == "0755"
            and admission["quota"]["pool_mount_id"] == pool["mount_id"], "actual root-owned single tmpfs")
    for role in ("cwd", "upload", "evidence", "scratch"):
        item = roles[role]
        require(item["fs_type"] == "tmpfs" and (item["major"], item["minor"]) == (pool["major"], pool["minor"]), "shared tmpfs device")
        if item["mount_id"] != pool["mount_id"]:
            require(item["root"] == posixpath.join(pool["root"], role)
                    and item["mount_point"] == item["path"], "exact sibling bind roots")
    options = {}
    for option in mounts[pool["mount_id"]]["superoptions"]:
        name, separator, value = option.partition("=")
        require(name not in options, "unique tmpfs superoptions")
        options[name] = value if separator else None
    for name, maximum in (("size", POOL_LIMIT), ("nr_inodes", 133)):
        value = options.get(name)
        require(type(value) is str and re.fullmatch(r"[1-9][0-9]*[kKmMgG]?", value), "explicit actual tmpfs bound")
        suffix = value[-1].lower()
        amount = int(value[:-1]) * {"k": 1024, "m": MIB, "g": 1024 ** 3}[suffix] if suffix in "kmg" else int(value)
        require(0 < amount <= maximum, "finite actual tmpfs quota")
    allowed = {row["mount_point"] for row in roles.values()} | {"/proc", "/dev"}
    for item in mounts.values():
        require(item["mount_point"] in allowed, "unknown auxiliary mount")
        if item["mount_id"] != pool["mount_id"]:
            require(item["read_only"], "unexpected auxiliary writable mount")
    before = admission["host_floor"]["before"]
    require(len(before) == 1 and before[0]["storage_id"] == n["storage_id"]
            and before[0]["free_bytes"] >= FLOOR and 0 <= now - before[0]["measured_ms"] <= 1000,
            "actual physical BEFORE ID/floor/freshness")
    require(admission["controller"]["euid"] == os.geteuid(), "actual privileged controller euid")
    require(len(canonical(admission)) <= JSON_LIMIT, "canonical admission byte bound")
    return admission


def claim_nonce(directory):
    nonce = os.getrandom(32).hex()
    require(len(nonce) == 64, "fresh kernel entropy")
    fd = open_directory(directory)
    try:
        # A failed launch consumes its nonce too. No timestamp-based reuse and
        # no deletion of the external journal after either success or failure.
        claim = os.open(nonce, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o600, dir_fd=fd)
        try:
            raw = canonical({"format": "elsy.partner-dx.nonce.v1", "nonce": nonce,
                             "clock": "CLOCK_MONOTONIC_MS", "claimed_ms": time.monotonic_ns() // 1_000_000})
            write_all(claim, raw)
            os.fsync(claim)
        finally:
            os.close(claim)
        os.fsync(fd)
    finally:
        os.close(fd)
    return nonce


def write_all(fd, raw):
    offset = 0
    while offset < len(raw):
        wrote = os.write(fd, raw[offset:])
        require(wrote > 0, "short file write")
        offset += wrote


def exclusive_json(directory, name, raw):
    require(name in {"artifact-manifest.json", "final.json"} and len(raw) <= JSON_LIMIT, "final bookkeeping bounds")
    fd = open_directory(directory)
    try:
        target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o400, dir_fd=fd)
        try:
            write_all(target, raw)
            os.fsync(target)
            require(os.fstat(target).st_nlink == 1, "single-link external final")
        finally:
            os.close(target)
        os.fsync(fd)
    finally:
        os.close(fd)


def admission_placeholder(config):
    n = config["native"]
    private_directory(posixpath.dirname(n["admission_host"]), int(n["uid"]), empty=True)
    fd = open_directory(posixpath.dirname(n["admission_host"]))
    try:
        target = os.open(posixpath.basename(n["admission_host"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=fd)
        try:
            os.fchown(target, int(n["uid"]), int(n["gid"]))
            os.fchmod(target, 0o400)
            os.fsync(target)
        finally:
            os.close(target)
        os.fsync(fd)
    finally:
        os.close(fd)


def exec_evidence(value):
    keys(value, {"consumed", "continue_count", "exec_observed", "notification_id", "pid"}, "EXEC")
    require(value["consumed"] is True and value["exec_observed"] is True
            and number(value["continue_count"], "CONTINUE count") == 1
            and number(value["notification_id"], "notification ID", 2 ** 64 - 1) > 0
            and number(value["pid"], "native observed TID", 2 ** 32 - 1) > 1,
            "exactly one successful trusted-bootstrap exec")
    return value


def exit_evidence(value, config, broker):
    keys(value, {"exit_code", "termination_signal", "output_bytes", "host_floor", "artifacts_copied",
                 "reservation_bytes", "reservation_entries", "exec_observed", "continue_count", "rejected"}, "EXIT")
    code = number(value["exit_code"], "exit code", 255)
    sig = number(value["termination_signal"], "termination signal", 64)
    require((sig == 0 and 0 <= code <= 255) or (sig > 0 and code == 128 + sig), "actual exit/signal relation")
    require(value["artifacts_copied"] is True and value["exec_observed"] is True
            and number(value["continue_count"], "terminal CONTINUE count") == 1
            and value["rejected"] is False, "complete native terminal evidence")
    require(value["reservation_bytes"] == RESERVATION_BYTES and value["reservation_entries"] == 4,
            "native accounting reservation binding")
    require(number(value["output_bytes"], "native combined output bytes", OUTPUT_LIMIT) == broker.output_bytes,
            "observed and archived output accounting")
    floor = keys(value["host_floor"], {"storage_id", "before_free", "minimum_observed_during_free",
                 "after_free", "samples", "max_gap_ms", "status"}, "native final floor")
    require(floor["storage_id"] == config["native"]["storage_id"] and floor["status"] == "PASS", "physical final storage ID/status")
    for key in ("before_free", "minimum_observed_during_free", "after_free"):
        require(number(floor[key], key) >= FLOOR, "physical before/during/after floor")
    require(number(floor["samples"], "during samples", 512) >= 1
            and number(floor["max_gap_ms"], "sample gap", 1500) <= 1500, "physical monitor liveness")
    require(code == 0 and sig == 0, "workload actual normal exit0")
    return floor


def artifact_bundle(config, a, broker, execution, terminal):
    n = config["native"]
    root = n["host_evidence_dir"]
    private_directory(root, 0)
    bundle, files = inventory_tree(root, maximum=POOL_LIMIT)
    require({row[1].split("/")[0] for row in bundle["rows"]}
            == {"evidence", "scratch"}, "closed native archive roots")
    evidence_names = {"receipt.json", "phases.json", "imports.json", "junit.xml", "pytest-output.txt",
                      "canonical.json", "browser.json", "registry.json", "schema-checks.json", "prepare-cache.json"}
    for row in bundle["rows"]:
        kind, relative, mode, uid, _ = row[:5]
        require(kind in {"d", "f"} and not int(mode, 8) & 0o077, "private regular archive entries")
        if relative in {"scratch/controller-output.bin", "scratch/controller-native.json"}:
            require(kind == "f" and uid == 0 and mode == "0600", "trusted generated artifact metadata")
        elif relative.startswith(("evidence/", "scratch/")) or relative in {"evidence", "scratch"}:
            require(uid == int(n["uid"]), "candidate artifact ownership preserved")
            if relative.startswith("evidence/"):
                require(kind == "f" and relative.split("/", 1)[1] in evidence_names, "closed candidate evidence names")
        else:
            raise Rejected("unknown archive root")
        if kind == "f":
            require(row[5] <= FILE_LIMIT, "per-artifact16MiB")
    # Include variable scratch directories as well as files in the logical entry
    # ceiling; this is stricter than relying on regular-file count alone.
    entries = len(bundle["rows"]) - 2
    journal_raw, journal_info = read_file(config["nonce_dir"] + "/" + a["nonce"], JSON_LIMIT)
    require(journal_info.st_uid == 0 and stat.S_IMODE(journal_info.st_mode) == 0o600,
            "durable exclusive nonce journal identity")
    journal = parse(journal_raw)
    keys(journal, {"format", "nonce", "clock", "claimed_ms"}, "nonce journal")
    require(journal["format"] == "elsy.partner-dx.nonce.v1" and journal["nonce"] == a["nonce"]
            and journal["clock"] == "CLOCK_MONOTONIC_MS"
            and number(journal["claimed_ms"], "nonce issue time") <= a["issued_ms"], "durable nonce session binding")
    # The replay journal is visible outside control state, not a hidden output.
    # Charge its actual bytes/entry too, conservatively inside metadata reserve.
    require(entries + 3 <= 128 and bundle["bytes"] + len(journal_raw) + 2 * JSON_LIMIT <= POOL_LIMIT,
            "whole output plus reserved manifest/final budget")
    output_raw, _ = read_file(root + "/scratch/controller-output.bin", OUTPUT_LIMIT)
    require(len(output_raw) == broker.output_bytes and digest(output_raw) == broker.output_hash.hexdigest(),
            "saved combined raw output equals observed stream")
    trace_raw, _ = read_file(root + "/scratch/controller-native.json", META_LIMIT)
    trace = parse(trace_raw, META_LIMIT)
    keys(trace, {"format", "clock", "storage_id", "samples", "firstnotify", "failures",
                 "output_bytes", "output_sha256"}, "native monitor trace")
    first = keys(trace["firstnotify"], {"consumed", "continue_count", "exec_observed", "id", "pid"}, "trace exec")
    mapped_exec = {**{key: first[key] for key in ("consumed", "continue_count", "exec_observed", "pid")},
                   "notification_id": first["id"]}
    require(trace["format"] == "elsy.partner-dx.native-trace.v1" and trace["clock"] == "CLOCK_MONOTONIC_MS"
            and trace["storage_id"] == n["storage_id"] and trace["failures"] == []
            and mapped_exec == execution and trace["output_bytes"] == broker.output_bytes
            and trace["output_sha256"] == broker.output_hash.hexdigest(), "actual trace/exec/session evidence")
    samples = trace["samples"]
    require(type(samples) is list and 3 <= len(samples) <= 512, "bounded complete monitor trace")
    previous, gaps, during, phases = None, [], [], []
    for sample in samples:
        keys(sample, {"measured_ms", "free_bytes", "phase"}, "trace sample")
        measured = number(sample["measured_ms"], "sample timestamp")
        free = number(sample["free_bytes"], "sample free bytes")
        require(free >= FLOOR and sample["phase"] in {"BEFORE", "DURING", "AFTER"}, "physical trace sample")
        if previous is not None:
            require(measured >= previous, "monotonic trace timestamps")
            gaps.append(measured - previous)
        previous = measured
        phases.append(sample["phase"])
        if sample["phase"] == "DURING":
            during.append(free)
    ranks = [{"BEFORE": 0, "DURING": 1, "AFTER": 2}[phase] for phase in phases]
    require(phases[0] == "BEFORE" and phases[-1] == "AFTER" and during
            and ranks == sorted(ranks), "complete monotonic trace phases")
    require(max(gaps) <= 1500, "all observed physical sample gaps")
    before = a["host_floor"]["before"][0]
    require(any(sample["phase"] == "BEFORE" and sample["measured_ms"] == before["measured_ms"]
                and sample["free_bytes"] == before["free_bytes"] for sample in samples), "trace matches admission BEFORE")
    floor = terminal["host_floor"]
    require(floor["before_free"] == before["free_bytes"]
            and floor["after_free"] == samples[-1]["free_bytes"]
            and floor["minimum_observed_during_free"] == min(during)
            and floor["samples"] == len(during) and floor["max_gap_ms"] == max(gaps), "trace recomputes final aggregates")
    receipt_raw, _ = read_file(root + "/evidence/receipt.json", FILE_LIMIT)
    # This ordinary helper artifact contains elapsed_seconds as a float. Its
    # encoding is deliberately not confused with the integer-only A/F protocol.
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=no_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise Rejected("invalid bounded workload receipt") from error
    require(type(receipt) is dict and receipt.get("ok") is True
            and receipt.get("mode") == "kernel-controlled-v1"
            and receipt.get("safety_acceptance") == "EXTERNAL_FINAL_PENDING"
            and receipt.get("nonce") == a["nonce"] and receipt.get("clock") == "CLOCK_MONOTONIC_MS"
            and receipt.get("admission_sha256") == digest(canonical(a))
            and receipt.get("runner_sha256") == n["runner_sha256"]
            and receipt.get("errors") == [] and type(receipt.get("postcheck")) is dict
            and receipt["postcheck"].get("ok") is True, "successful workload receipt binding; never kernel self-attestation")
    manifest = {"format": "elsy.partner-dx.artifacts.v1", "nonce": a["nonce"],
                "admission_sha256": digest(canonical(a)), "policy_sha256": n["policy_sha256"],
                "launcher_sha256": config["pins"]["launcher_sha256"],
                "controller_sha256": config["pins"]["controller_sha256"],
                "transport_sha256": broker.transcript_hash.hexdigest(),
                "output_sha256": broker.output_hash.hexdigest(), "execution": execution,
                "rows": bundle["rows"], "count": entries, "bytes": bundle["bytes"],
                "nonce_journal_sha256": digest(journal_raw), "nonce_journal_bytes": len(journal_raw),
                "external_bookkeeping_count": 3, "external_bookkeeping_reserve_bytes": 2 * JSON_LIMIT + len(journal_raw)}
    raw = canonical(manifest)
    require(len(raw) <= JSON_LIMIT, "external artifact manifest64KiB")
    return raw, {**bundle, "bytes": bundle["bytes"] + len(journal_raw)}


def final_receipt(config, admission, admission_raw, before, after, terminal, manifest_raw, literals):
    floor = terminal["host_floor"]
    storage_result = {key: floor[key] for key in ("storage_id", "before_free", "minimum_observed_during_free",
                                                 "after_free", "samples", "max_gap_ms")}
    value = {"format": "elsy.partner-dx.kernel-final.v1", "phase": "FINAL", "clock": "CLOCK_MONOTONIC_MS",
             "nonce": admission["nonce"], "admission_sha256": digest(admission_raw),
             "policy_sha256": config["pins"]["policy_sha256"], "runner_sha256": config["pins"]["runner_sha256"],
             "source_head": config["native"]["source_head"], "exit_code": terminal["exit_code"],
             "termination_signal": terminal["termination_signal"],
             "host_floor": {"storage_results": [storage_result], "status": "PASS"},
             "output_bytes": terminal["output_bytes"], "artifacts_manifest_sha256": digest(manifest_raw),
             "source_before_sha256": before["source"], "source_after_sha256": after["source"],
             "runtime_before_sha256": digest(canonical({k: before[k] for k in ("native", "venv", "rootfs")})),
             "runtime_after_sha256": digest(canonical({k: after[k] for k in ("native", "venv", "rootfs")})),
             "decision": "SAFETY_ACCEPTED"}
    require(before == after, "complete source/runtime/rootfs prepost immutability")
    shape(value, "F", literals)
    raw = canonical(value)
    require(len(raw) <= JSON_LIMIT, "external final64KiB")
    return raw


def run(config):
    check_storage(config)
    before, bindings, literals = immutable_inputs(config)
    nonce = claim_nonce(config["nonce_dir"])
    admission_placeholder(config)
    broker = None
    published = False
    try:
        broker = Broker(config)
        broker.send(CONFIG, config_bytes(config["native"]))
        startup = time.monotonic_ns() // 1_000_000 + 30000
        opcode, payload = broker.next(startup)
        require(opcode == READY, "native READY must be first")
        admission = ready_admission(parse(payload, FRAME_LIMIT), config, bindings, literals, nonce)
        admission_raw = canonical(admission)
        broker.send(SEAL, seal_bytes(admission_raw, environment(config, admission, admission_raw)))
        execution, terminal = None, None
        deadline = time.monotonic_ns() // 1_000_000 + 210000
        while terminal is None:
            opcode, payload = broker.next(deadline)
            if opcode == EXEC:
                require(execution is None, "single initial exec event")
                execution = exec_evidence(parse(payload, FRAME_LIMIT))
            elif opcode in {STDOUT, STDERR}:
                require(execution is not None, "no candidate output before successful exec")
            elif opcode == EXIT:
                require(execution is not None, "terminal event requires actual exec")
                terminal = parse(payload, FRAME_LIMIT)
                exit_evidence(terminal, config, broker)
            elif opcode == ERROR:
                raise Rejected("native broker rejected workload")
            else:
                raise Rejected("native opcode in wrong state")
        # Check actual admission bytes after native fsync/close, not a promise
        # that a requested SEAL was installed.
        actual_a = sealed_input(config["native"]["admission_host"], int(config["native"]["uid"]), 0o400,
                                digest(admission_raw))
        require(actual_a == admission_raw, "actual sealed admission bytes")
        after, after_bindings, _ = immutable_inputs(config)
        require(after_bindings == bindings and before == after, "all independent input bytes unchanged")
        broker.send(FINALIZE, struct.pack("<I", 0))
        opcode, payload = broker.next(time.monotonic_ns() // 1_000_000 + 10000)
        require(opcode == FINAL, "authoritative FINAL after posthash")
        finalized = parse(payload, FRAME_LIMIT)
        exit_evidence(finalized, config, broker)
        require(all(finalized[key] == terminal[key] for key in (
            "exit_code", "termination_signal", "output_bytes", "exec_observed", "continue_count")),
            "finalization preserves actual workload outcome")
        terminal = finalized
        broker.finish()
        manifest_raw, bundle = artifact_bundle(config, admission, broker, execution, terminal)
        final_raw = final_receipt(config, admission, admission_raw, before, after, terminal, manifest_raw, literals)
        require(bundle["bytes"] + len(manifest_raw) + len(final_raw) <= POOL_LIMIT, "actual aggregate persisted bytes")
        check_storage(config)
        exclusive_json(config["final_dir"], "artifact-manifest.json", manifest_raw)
        exclusive_json(config["final_dir"], "final.json", final_raw)
        check_storage(config)
        published = True
        return {"decision": "SAFETY_ACCEPTED", "nonce": nonce, "final_sha256": digest(final_raw),
                "final_path": config["final_dir"] + "/final.json"}
    finally:
        if broker is not None:
            broker.kill()
            broker.close()
        if not published:
            # Only this invocation's exclusively-created final can exist in the
            # initially-empty private final directory. A failed post-save floor
            # observation must not leave an accepted-looking F behind.
            directory = open_directory(config["final_dir"])
            try:
                try:
                    os.unlink("final.json", dir_fd=directory)
                    os.fsync(directory)
                except FileNotFoundError:
                    pass
            finally:
                os.close(directory)


def main():
    require(sys.argv[1:2] == ["--execute-root-approved-kernel-controller-v1"] and len(sys.argv) == 4,
            "exact opt-in, config path and independent config SHA; no default/help execution")
    require(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
            and not sys.flags.optimize, "isolated stdlib-only supervisor flags -I -S -B")
    os.umask(0o077)
    config = load_config(path(sys.argv[2]), sys.argv[3])
    result = run(config)
    # Consumers require this successful controller exit as well as the external
    # pinned F; a file left by an interrupted controller is never sufficient.
    sys.stdout.buffer.write(canonical(result))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except BaseException as error:
        # No fabricated schema-complete F on missing observations. This bounded
        # diagnostic is explicitly a rejection, not an admission/final receipt.
        failure = {"decision": "REJECTED", "error_type": type(error).__name__}
        sys.stderr.buffer.write(canonical(failure))
        status = 1
    raise SystemExit(status)
