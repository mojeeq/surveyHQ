#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <sched.h>
#include <seccomp.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef O_PATH
#define O_PATH 010000000
#endif

#define SANDBOX_PROBE "surveyhq-r-sandbox-v1"

static void die(const char *message) {
    fprintf(stderr, "SurveyHQ R sandbox: %s: %s\n", message, strerror(errno));
    exit(126);
}

static int landlock_create(const struct landlock_ruleset_attr *attr, size_t size,
                           uint32_t flags) {
    return (int)syscall(SYS_landlock_create_ruleset, attr, size, flags);
}

static int landlock_add(int ruleset_fd, enum landlock_rule_type type,
                        const void *attr, uint32_t flags) {
    return (int)syscall(SYS_landlock_add_rule, ruleset_fd, type, attr, flags);
}

static int landlock_restrict(int ruleset_fd, uint32_t flags) {
    return (int)syscall(SYS_landlock_restrict_self, ruleset_fd, flags);
}

static void add_path_rule(int ruleset_fd, const char *path, uint64_t access,
                          bool optional) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    if (fd < 0) {
        if (optional && errno == ENOENT) {
            return;
        }
        die(path);
    }

    struct landlock_path_beneath_attr rule = {
        .allowed_access = access,
        .parent_fd = fd,
    };
    if (landlock_add(ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) < 0) {
        close(fd);
        die("could not add Landlock filesystem rule");
    }
    close(fd);
}

static void install_filesystem_sandbox(const char *workspace) {
    int abi = landlock_create(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) {
        die("Landlock is unavailable; refusing to run arbitrary R code");
    }

    uint64_t handled = LANDLOCK_ACCESS_FS_EXECUTE |
                       LANDLOCK_ACCESS_FS_WRITE_FILE |
                       LANDLOCK_ACCESS_FS_READ_FILE |
                       LANDLOCK_ACCESS_FS_READ_DIR |
                       LANDLOCK_ACCESS_FS_REMOVE_DIR |
                       LANDLOCK_ACCESS_FS_REMOVE_FILE |
                       LANDLOCK_ACCESS_FS_MAKE_DIR |
                       LANDLOCK_ACCESS_FS_MAKE_REG |
                       LANDLOCK_ACCESS_FS_MAKE_SYM |
                       LANDLOCK_ACCESS_FS_MAKE_FIFO |
                       LANDLOCK_ACCESS_FS_MAKE_SOCK;
#ifdef LANDLOCK_ACCESS_FS_REFER
    if (abi >= 2) {
        handled |= LANDLOCK_ACCESS_FS_REFER;
    }
#endif
#ifdef LANDLOCK_ACCESS_FS_TRUNCATE
    if (abi >= 3) {
        handled |= LANDLOCK_ACCESS_FS_TRUNCATE;
    }
#endif

    struct landlock_ruleset_attr ruleset = {.handled_access_fs = handled};
    int ruleset_fd = landlock_create(&ruleset, sizeof(ruleset), 0);
    if (ruleset_fd < 0) {
        die("could not create Landlock ruleset");
    }

    const uint64_t read_only = LANDLOCK_ACCESS_FS_EXECUTE |
                               LANDLOCK_ACCESS_FS_READ_FILE |
                               LANDLOCK_ACCESS_FS_READ_DIR;

    /* Runtime paths contain R, its shared libraries, locales and standard
       command-line tools. They are readable/executable but never writable. */
    add_path_rule(ruleset_fd, "/usr", read_only, false);
    add_path_rule(ruleset_fd, "/bin", read_only, true);
    add_path_rule(ruleset_fd, "/lib", read_only, true);
    add_path_rule(ruleset_fd, "/lib64", read_only, true);
    add_path_rule(ruleset_fd, "/etc", read_only, false);

    /* Device access is intentionally narrow. These are the ordinary stream and
       entropy devices R and libc expect; no device directory is exposed. */
    const uint64_t device_rw = LANDLOCK_ACCESS_FS_READ_FILE |
                               LANDLOCK_ACCESS_FS_WRITE_FILE;
    add_path_rule(ruleset_fd, "/dev/null", device_rw, false);
    add_path_rule(ruleset_fd, "/dev/zero", device_rw, false);
    add_path_rule(ruleset_fd, "/dev/random", device_rw, false);
    add_path_rule(ruleset_fd, "/dev/urandom", device_rw, false);

    /* This is the only host-backed location arbitrary project code may change
       or read. Sibling project workspaces and the rest of /data are absent
       from the allowlist and therefore denied by Landlock. */
    add_path_rule(ruleset_fd, workspace, handled, false);

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) {
        close(ruleset_fd);
        die("could not enable no_new_privs");
    }
    if (landlock_restrict(ruleset_fd, 0) < 0) {
        close(ruleset_fd);
        die("could not enforce Landlock rules");
    }
    close(ruleset_fd);
}

static void deny_syscall(scmp_filter_ctx ctx, const char *name, uint32_t action) {
    int nr = seccomp_syscall_resolve_name(name);
    if (nr == __NR_SCMP_ERROR) {
        return;
    }
    if (seccomp_rule_add(ctx, action, nr, 0) < 0) {
        errno = EINVAL;
        die(name);
    }
}

static void install_syscall_sandbox(void) {
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    if (ctx == NULL) {
        errno = ENOMEM;
        die("could not create seccomp filter");
    }

    const uint32_t denied = SCMP_ACT_ERRNO(EPERM);
    const char *blocked[] = {
        /* No network. The child receives only stdin/stdout/stderr pipes, so
           refusing socket creation also prevents subprocesses such as curl
           from acquiring a network endpoint. */
        "socket", "connect", "bind", "listen", "accept", "accept4",
        "sendto", "sendmsg", "recvfrom", "recvmsg", "shutdown",
        /* No process-memory inspection or kernel/admin escape primitives. */
        "ptrace", "process_vm_readv", "process_vm_writev", "kcmp",
        "mount", "umount2", "pivot_root", "chroot", "setns", "unshare",
        "open_by_handle_at", "name_to_handle_at", "bpf", "perf_event_open",
        "keyctl", "add_key", "request_key", "io_uring_setup", "userfaultfd",
        "init_module", "finit_module", "delete_module", "reboot", "swapon",
        "swapoff", "acct", "iopl", "ioperm",
    };
    for (size_t i = 0; i < sizeof(blocked) / sizeof(blocked[0]); i++) {
        deny_syscall(ctx, blocked[i], denied);
    }

    /* Modern glibc can use clone3 for process creation. Returning ENOSYS makes
       it fall back to ordinary clone/fork, where namespace-creating flags are
       filtered below. */
    deny_syscall(ctx, "clone3", SCMP_ACT_ERRNO(ENOSYS));

#ifdef __NR_clone
    const unsigned long namespace_flags[] = {
#ifdef CLONE_NEWNS
        CLONE_NEWNS,
#endif
#ifdef CLONE_NEWCGROUP
        CLONE_NEWCGROUP,
#endif
#ifdef CLONE_NEWUTS
        CLONE_NEWUTS,
#endif
#ifdef CLONE_NEWIPC
        CLONE_NEWIPC,
#endif
#ifdef CLONE_NEWUSER
        CLONE_NEWUSER,
#endif
#ifdef CLONE_NEWPID
        CLONE_NEWPID,
#endif
#ifdef CLONE_NEWNET
        CLONE_NEWNET,
#endif
    };
    for (size_t i = 0; i < sizeof(namespace_flags) / sizeof(namespace_flags[0]); i++) {
        if (seccomp_rule_add(ctx, denied, SCMP_SYS(clone), 1,
                             SCMP_A0(SCMP_CMP_MASKED_EQ, namespace_flags[i],
                                     namespace_flags[i])) < 0) {
            seccomp_release(ctx);
            errno = EINVAL;
            die("could not restrict clone namespace flags");
        }
    }
#endif

    if (seccomp_load(ctx) < 0) {
        seccomp_release(ctx);
        die("could not load seccomp filter");
    }
    seccomp_release(ctx);
}

static void prepare_environment(const char *workspace) {
    size_t length = strlen(workspace) + 32;
    char *tmp = malloc(length);
    char *libs = malloc(length);
    if (tmp == NULL || libs == NULL) {
        errno = ENOMEM;
        die("could not prepare sandbox environment");
    }

    snprintf(tmp, length, "%s/.sandbox-tmp", workspace);
    snprintf(libs, length, "%s/rlibs", workspace);
    if (mkdir(tmp, 0700) < 0 && errno != EEXIST) {
        die("could not create sandbox temp directory");
    }
    if (mkdir(libs, 0700) < 0 && errno != EEXIST) {
        die("could not create project R library directory");
    }

    setenv("HOME", workspace, 1);
    setenv("TMPDIR", tmp, 1);
    setenv("R_LIBS_USER", libs, 1);
    setenv("PATH", "/usr/local/bin:/usr/bin:/bin", 1);
    unsetenv("LD_PRELOAD");
    unsetenv("LD_LIBRARY_PATH");
    unsetenv("PYTHONPATH");
    unsetenv("BASH_ENV");
    unsetenv("ENV");
    free(tmp);
    free(libs);
}

int main(int argc, char **argv) {
    /* The application probes the configured executable before enabling R. A
       raw /usr/bin/Rscript cannot answer this, so a configuration mistake
       fails closed instead of silently restoring arbitrary server code exec. */
    if (argc == 2 && strcmp(argv[1], "--surveyhq-sandbox-probe") == 0) {
        puts(SANDBOX_PROBE);
        return 0;
    }

    char workspace[4096];
    if (getcwd(workspace, sizeof(workspace)) == NULL) {
        die("could not identify the project workspace");
    }

    umask(0077);
    prepare_environment(workspace);
    install_filesystem_sandbox(workspace);
    install_syscall_sandbox();

    /* Preserve the caller's Rscript arguments exactly. argv[0] only affects
       process display; the executable path is fixed and cannot be supplied by
       a user or project script. */
    execv("/usr/bin/Rscript", argv);
    die("could not start /usr/bin/Rscript");
    return 126;
}
