#!/usr/bin/env python3
"""landlock.py WRITABLE BINARY [ARGS...]: run BINARY under a Landlock ruleset.

The mutation sandbox for Linux machines where bubblewrap cannot run, because
the container forbids mounts (a JupyterHub pod under AppArmor, for one).
Landlock needs no mounts and no privileges: a process restricts itself and
every child it starts. This one may

- write, create and delete only under WRITABLE (build-oracle/), plus write
  to the character devices /dev/null and /dev/tty;
- execute only BINARY and its ELF interpreter, so no shell or delegate
  program can start.

Reading stays open: magick needs its libraries, fonts and configuration.
The network is cut off by the caller, which starts this in a fresh network
namespace (`unshare --user --map-current-user --net`): Landlock ABI 1, the
version on 5.15 kernels, has no network rules.

ABI 1 cannot stop truncate(2) by path name on a file outside WRITABLE;
opening one for writing, O_TRUNC included, is denied. If the kernel has no
Landlock this exits with status 125 rather than run the binary unconfined.
"""
import ctypes
import os
import sys

SYS_CREATE_RULESET, SYS_ADD_RULE, SYS_RESTRICT_SELF = 444, 445, 446
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

EXECUTE, WRITE_FILE = 1 << 0, 1 << 1
# REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR, MAKE_REG, MAKE_SOCK,
# MAKE_FIFO, MAKE_BLOCK, MAKE_SYM: bits 4 to 12 of ABI 1.
CHANGE_TREE = sum(1 << b for b in range(4, 13))
HANDLED = EXECUTE | WRITE_FILE | CHANGE_TREE
INTERPRETER = "/lib64/ld-linux-x86-64.so.2"

libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long


class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathBeneath(ctypes.Structure):
    _pack_ = 1  # the kernel's struct is packed: 8 + 4 bytes
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def fail(what):
    sys.stderr.write("landlock.py: %s: %s\n" % (what, os.strerror(ctypes.get_errno())))
    sys.exit(125)


def allow(ruleset, path, access):
    fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    rule = PathBeneath(access, fd)
    if libc.syscall(SYS_ADD_RULE, ruleset, RULE_PATH_BENEATH, ctypes.byref(rule), 0) != 0:
        fail("add rule for " + path)
    os.close(fd)


def restrict(writable, binary):
    attr = RulesetAttr(HANDLED)
    ruleset = libc.syscall(SYS_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset < 0:
        fail("create ruleset (is Landlock enabled?)")
    allow(ruleset, writable, WRITE_FILE | CHANGE_TREE)
    for dev in ("/dev/null", "/dev/tty"):
        if os.path.exists(dev):
            allow(ruleset, dev, WRITE_FILE)
    for exe in (binary, INTERPRETER):
        allow(ruleset, os.path.realpath(exe), EXECUTE)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        fail("no_new_privs")
    if libc.syscall(SYS_RESTRICT_SELF, ruleset, 0) != 0:
        fail("restrict self")
    os.close(ruleset)


def main():
    writable, binary = os.path.realpath(sys.argv[1]), sys.argv[2]
    restrict(writable, binary)
    os.execv(binary, sys.argv[2:])


if __name__ == "__main__":
    main()
