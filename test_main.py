import importlib.util
import io
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_TRACE = os.path.join(REPO, "example", "NAS_48_threads_group_imbalance_bug.trace.xz")
EXAMPLE_LSCPU = os.path.join(REPO, "example", "lscpu.txt")

# Four CPUs, CPU 3 has no events. CPU 0 runs 2 tasks from 11.0 to 12.0.
SMALL_TRACE = """\
cpus=4
 a-1 [000] 10.000000: sched_update_nr_running: cpu=0 change=1 nr_running=1
 a-1 [001] 10.100000: sched_update_nr_running: cpu=1 change=1 nr_running=1
 a-1 [002] 10.200000: sched_update_nr_running: cpu=2 change=1 nr_running=1
 a-1 [000] 11.000000: sched_update_nr_running: cpu=0 change=1 nr_running=2
 a-1 [000] 12.000000: sched_update_nr_running: cpu=0 change=-1 nr_running=1
 a-1 [000] 13.000000: sched_update_nr_running: cpu=1 change=-1 nr_running=0
"""


def load(script):
    spec = importlib.util.spec_from_file_location(script.replace("-", "_"), os.path.join(REPO, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args):
    env = dict(os.environ, MPLBACKEND="Agg")
    return subprocess.run([sys.executable] + list(args), env=env, cwd=REPO,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)


@pytest.fixture
def small_trace(tmp_path):
    path = tmp_path / "small.trace"
    path.write_text(SMALL_TRACE)
    return str(path)


def test_exec_on_example(tmp_path):
    image = tmp_path / "example.png"
    complete = run("plot-nr-running.py", "--lscpu-file", EXAMPLE_LSCPU,
                   "--image-file", str(image), EXAMPLE_TRACE)
    assert complete.returncode == 0, complete.stdout
    assert image.stat().st_size > 0


def test_bad_trace_fails(tmp_path):
    bad = tmp_path / "bad.trace"
    bad.write_text("garbage\n")
    complete = run("plot-nr-running.py", "--image-file", str(tmp_path / "bad.png"), str(bad))
    assert complete.returncode == 1


def test_imbalance_and_idle_cpu(small_trace, tmp_path):
    complete = run("plot-nr-running.py", "--image-file", str(tmp_path / "small.png"), small_trace)
    assert complete.returncode == 0, complete.stdout
    # The idle CPU 3 counts as 0 tasks, only the 2 tasks on CPU 0 are an imbalance
    assert "Imbalance from timestamp 11.0 lasting 1.0 seconds" in complete.stdout
    assert complete.stdout.count("Imbalance from") == 1


def test_states_follow_events(small_trace):
    plot = load("plot-nr-running.py")
    with open(small_trace) as trace:
        times, cpus, values, initial = plot.read_events(trace)
    time_axis, states, differences, sums, imbalances = plot.replay_events(
        times, cpus, values, initial, 1, 0, 2, 0.05)
    assert list(time_axis) == [10.0, 10.1, 10.2, 11.0, 12.0, 13.0]
    # states[i] is the state right after the event at time_axis[i]
    assert states[3].tolist() == [2, 1, 1, 0]
    assert list(differences) == [1, 1, 1, 2, 1, 1]
    assert imbalances == [[(11.0, 2), (12.0, 2)]]


def test_read_nodes_memory_only_node():
    plot = load("plot-nr-running.py")
    lscpu = io.StringIO("NUMA node(s): 3\n"
                        "NUMA node0 CPU(s):   0-1,4\n"
                        "NUMA node1 CPU(s):   2-3\n"
                        "NUMA node2 CPU(s):   \n")
    assert plot.read_nodes(lscpu) == {0: [0, 1, 4], 1: [2, 3]}


def test_cpu_layout_mismatched_lscpu():
    plot = load("plot-nr-running.py")
    order, nodes = plot.cpu_layout({0: [0, 1], 1: [2, 3, 4, 5]}, 5)
    assert order == [0, 1, 2, 3, 4]
    assert nodes == [(0, "Node 0"), (2, "Node 1")]
    order, nodes = plot.cpu_layout({1: [1]}, 3)
    assert order == [1, 0, 2]
    assert nodes == [(0, "Node 1"), (1, "Unknown")]


def test_check_on_small_trace(small_trace):
    complete = run("check-nr-running.py", small_trace)
    assert complete.returncode == 0, complete.stdout
    # CPU 3 never had an event and is reported idle for the whole trace
    assert "|  3  |      0.0    |     0.0   |    3.0   | 100.0  |       3.0      |" in complete.stdout


def test_compare(small_trace, tmp_path):
    image = tmp_path / "compare.png"
    complete = run("compare-nr-running.py", "--image-file", str(image), EXAMPLE_TRACE, small_trace)
    assert complete.returncode == 0, complete.stdout
    assert image.stat().st_size > 0


def test_plot_ps_late_thread(tmp_path):
    ps = tmp_path / "ps.txt"
    ps.write_text("2020-Jun-22_03h02m09s\nPID LWP PSR\n1 100 0\n1 101 1\n"
                  "2020-Jun-22_03h02m10s\nPID LWP PSR\n1 100 1\n1 101 1\n1 102 3\n")
    lscpu = tmp_path / "lscpu.txt"
    lscpu.write_text("NUMA node0 CPU(s): 0-3\n")
    complete = run("plot-ps.py", "--lscpu-file", str(lscpu), "--image-file", str(tmp_path / "ps.png"),
                   "--time-offset", "1592780000", str(ps))
    assert complete.returncode == 0, complete.stdout


def test_plot_mpstat_12_hour_clock(tmp_path):
    mpstat = tmp_path / "x.mpstat"
    mpstat.write_text(
        "#Date since epoch in seconds:1592788365.716\n"
        "Linux 6.12.0 (host) \t10/13/2025 \t_x86_64_\t(2 CPU)\n\n"
        "11:59:59 PM     CPU    %usr   %nice    %sys\n"
        "12:00:00 AM     all   50.00    0.00    0.00\n"
        "12:00:00 AM       0  100.00    0.00    0.00\n"
        "12:00:00 AM       1    0.00    0.00    0.00\n\n"
        "12:00:00 AM     CPU    %usr   %nice    %sys\n"
        "12:00:01 AM     all   25.00    0.00    0.00\n"
        "12:00:01 AM       0   40.00    0.00   10.00\n"
        "12:00:01 AM       1    0.00    0.00    0.00\n\n"
        "Average:        all   37.50    0.00    0.00\n")
    mp = load("plot-mpstat.py")
    with open(str(mpstat)) as f:
        values, time_axis = mp.process_report(f)
    assert values.tolist() == [[100.0, 0.0], [50.0, 0.0]]
    # Second block is past midnight
    assert time_axis.tolist() == [0.0, 1.0]
