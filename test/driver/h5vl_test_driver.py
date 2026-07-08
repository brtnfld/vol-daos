#!/usr/bin/env python3
"""Test driver that starts a server (and optionally a client-helper and a
one-shot client-init) process, waits for each to signal readiness via a
line printed to its stdout/stderr, then runs a client process against them
and reports its result.

Pure Python 3 standard library, no external dependencies.
"""

import os
import re
import select
import shlex
import subprocess
import sys
import time

ERROR_SUBSTRINGS = [
    "ERROR",
    "FAILED",
    "Assertion failed",
    "Segmentation fault",
    "core dumped",
]

# Substrings that would otherwise match ERROR_SUBSTRINGS but are not actual
# failures (e.g. success messages that happen to contain the word "errors",
# or third-party tool banners printed under valgrind).
NON_ERROR_SUBSTRINGS = [
    "finished with no errors",
    "Memcheck, a memory error detector",
]

PROCESS_FLAGS = {
    "--server": ("server", "server_args"),
    "--client": ("client", "client_args"),
    "--client-helper": ("client_helper", "client_helper_args"),
    "--client-init": ("client_init", "client_init_args"),
}

VALUE_FLAGS = {
    "--server-start-msg": "server_start_msg",
    "--server-exit-command": "server_exit_command",
    "--client-helper-start-msg": "client_helper_start_msg",
    "--client-helper-exit-command": "client_helper_exit_command",
    "--client-init-token-regex": "client_init_token_regex",
    "--client-init-token-var": "client_init_token_var",
    "--init-command": "init_command",
    "--mpiexec": "mpiexec",
    "--mpiexec-numproc-flag": "mpiexec_numproc_flag",
    "--mpiexec-max-numprocs": "mpiexec_max_numprocs",
    "--mpiexec-server-max-numprocs": "mpiexec_server_max_numprocs",
    "--mpiexec-preflags": "mpiexec_preflags",
    "--mpiexec-postflags": "mpiexec_postflags",
    "--mpiexec-server-preflags": "mpiexec_server_preflags",
    "--mpiexec-server-postflags": "mpiexec_server_postflags",
    "--timeout": "timeout",
}

RECOGNIZED_FLAGS = (
    set(PROCESS_FLAGS) | set(VALUE_FLAGS) | {"--client-env", "--allow-server-errors", "--serial"}
)


def contains_error(line):
    if any(s in line for s in NON_ERROR_SUBSTRINGS):
        return False
    return any(s in line for s in ERROR_SUBSTRINGS)


def parse_args(argv):
    """Manual parser: --server/--client/--client-helper/--client-init each
    consume the next token as an executable, then all following tokens up
    to the next recognized flag become that process's own trailing args."""
    args = {
        "server": None,
        "server_args": [],
        "client": None,
        "client_args": [],
        "client_helper": None,
        "client_helper_args": [],
        "client_init": None,
        "client_init_args": [],
        "server_start_msg": None,
        "server_exit_command": None,
        "client_helper_start_msg": None,
        "client_helper_exit_command": None,
        "client_init_token_regex": None,
        "client_init_token_var": None,
        "init_command": None,
        "mpiexec": None,
        "mpiexec_numproc_flag": "-n",
        "mpiexec_max_numprocs": "1",
        "mpiexec_server_max_numprocs": "1",
        "mpiexec_preflags": "",
        "mpiexec_postflags": "",
        "mpiexec_server_preflags": "",
        "mpiexec_server_postflags": "",
        "client_env": [],
        "allow_server_errors": False,
        "serial": False,
        "timeout": 120.0,
    }

    i = 0
    n = len(argv)

    def take_value(flag):
        nonlocal i
        i += 1
        if i >= n:
            sys.exit(f"{flag} requires a value")
        return argv[i]

    while i < n:
        tok = argv[i]
        if tok in PROCESS_FLAGS:
            exe_key, args_key = PROCESS_FLAGS[tok]
            args[exe_key] = take_value(tok)
            trailing = []
            i += 1
            while i < n and argv[i] not in RECOGNIZED_FLAGS:
                trailing.append(argv[i])
                i += 1
            args[args_key] = trailing
            continue
        if tok in VALUE_FLAGS:
            value = take_value(tok)
            args[VALUE_FLAGS[tok]] = float(value) if tok == "--timeout" else value
        elif tok == "--client-env":
            args["client_env"].append(take_value(tok))
        elif tok == "--allow-server-errors":
            args["allow_server_errors"] = True
        elif tok == "--serial":
            args["serial"] = True
        else:
            sys.exit(f"unrecognized argument: {tok}")
        i += 1

    if not args["client"]:
        sys.exit("--client is required")

    return args


def build_env(extra_vars):
    env = os.environ.copy()
    for entry in extra_vars:
        key, _, value = entry.partition("=")
        env[key] = value
    return env


def build_mpiexec_argv(args, exe, exe_args, numprocs, preflags, postflags):
    if not args["mpiexec"]:
        return [exe] + exe_args
    argv = [args["mpiexec"], args["mpiexec_numproc_flag"], numprocs]
    argv += shlex.split(preflags)
    argv += [exe]
    argv += shlex.split(postflags)
    argv += exe_args
    return argv


def start_process(argv, env):
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env)


def _pump_ready_stream(stream, buffers, on_line):
    chunk = os.read(stream.fileno(), 4096)
    if not chunk:
        return False
    buffers[stream] += chunk.decode(errors="replace")
    while "\n" in buffers[stream]:
        line, buffers[stream] = buffers[stream].split("\n", 1)
        on_line(line)
    return True


def wait_for_line(proc, pattern, timeout, error_lines, print_output, collect=None):
    """Reads proc's stdout/stderr concurrently until a line matching
    `pattern` appears, the process exits, or `timeout` elapses. Kills the
    process on timeout. Returns True if the pattern was seen."""
    start_time = time.monotonic()
    streams = [s for s in (proc.stdout, proc.stderr) if s is not None]
    buffers = {s: "" for s in streams}
    found = False

    def on_line(line):
        nonlocal found
        if print_output:
            print(line)
        if collect is not None:
            collect.append(line)
        if contains_error(line):
            error_lines.append(line)
        if not found and pattern is not None and re.search(pattern, line):
            found = True

    while streams and not found:
        remaining = timeout - (time.monotonic() - start_time)
        if remaining <= 0:
            proc.kill()
            break

        ready, _, _ = select.select(streams, [], [], min(0.5, remaining))
        if not ready and proc.poll() is not None:
            break

        for stream in ready:
            if not _pump_ready_stream(stream, buffers, on_line):
                streams.remove(stream)

    return found


def drain_to_completion(proc, timeout, error_lines):
    """Reads proc's stdout/stderr until it exits or `timeout` elapses,
    printing every line. Returns the process's exit code (killing and
    returning -1 on timeout)."""
    wait_for_line(proc, pattern=None, timeout=timeout, error_lines=error_lines, print_output=True)
    if proc.poll() is None:
        proc.kill()
        proc.wait()
        print("driver: client timed out", file=sys.stderr)
        return -1
    return proc.wait()


def stop_process(proc, exit_command, env):
    if exit_command:
        subprocess.run(shlex.split(exit_command), env=env, check=False)
    else:
        proc.terminate()
    try:
        return proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


def run(args):
    env = build_env(args["client_env"])
    error_lines = []
    server_proc = None
    client_helper_proc = None
    server_result = 0

    try:
        if args["server"]:
            server_argv = build_mpiexec_argv(
                args, args["server"], args["server_args"], args["mpiexec_server_max_numprocs"],
                args["mpiexec_server_preflags"], args["mpiexec_server_postflags"],
            )
            server_proc = start_process(server_argv, env)
            if not wait_for_line(server_proc, args["server_start_msg"], args["timeout"],
                                  error_lines, print_output=True):
                print("driver: server did not start in time", file=sys.stderr)
                return 1

        if args["client_helper"]:
            client_helper_proc = start_process(
                [args["client_helper"]] + args["client_helper_args"], env)
            if not wait_for_line(client_helper_proc, args["client_helper_start_msg"], args["timeout"],
                                  error_lines, print_output=True):
                print("driver: client-helper did not start in time", file=sys.stderr)
                return 1

        if args["init_command"]:
            subprocess.run(shlex.split(args["init_command"]), env=env, check=False)

        client_env = env
        if args["client_init"]:
            init_proc = start_process([args["client_init"]] + args["client_init_args"], env)
            init_output = []
            wait_for_line(init_proc, pattern=None, timeout=args["timeout"],
                          error_lines=error_lines, print_output=False, collect=init_output)
            init_result = init_proc.wait()
            if init_result != 0:
                print("driver: client-init failed", file=sys.stderr)
                return init_result

            match = re.search(args["client_init_token_regex"], "\n".join(init_output))
            if not match:
                print("driver: client-init token not found in output", file=sys.stderr)
                return 1
            client_env = dict(env)
            client_env[args["client_init_token_var"]] = match.group(1)

        client_argv = (
            [args["client"]] + args["client_args"]
            if args["serial"]
            else build_mpiexec_argv(args, args["client"], args["client_args"],
                                     args["mpiexec_max_numprocs"],
                                     args["mpiexec_preflags"], args["mpiexec_postflags"])
        )
        client_proc = start_process(client_argv, client_env)
        client_result = drain_to_completion(client_proc, args["timeout"], error_lines)

    finally:
        if client_helper_proc is not None:
            stop_process(client_helper_proc, args["client_helper_exit_command"], env)
        if server_proc is not None:
            server_result = stop_process(server_proc, args["server_exit_command"], env)

    if server_result != 0 and not args["allow_server_errors"]:
        return server_result
    if error_lines:
        print("driver: error string(s) found in output:", file=sys.stderr)
        for line in error_lines:
            print(f"  {line}", file=sys.stderr)
        return 1
    return client_result


def main():
    args = parse_args(sys.argv[1:])
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
