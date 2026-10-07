import contextlib
import importlib.util
import io
import lzma
import os
import random
import shutil
import subprocess
import sys
from array import array

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
    return run_command(sys.executable, *args)


def run_command(*args, stdin=None, cwd=REPO):
    env = dict(os.environ, MPLBACKEND="Agg")
    return subprocess.run(list(args), env=env, cwd=cwd, input=stdin,
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


def reference_replay(times, cpus, values, initial, sampling, time_sampling, threshold, duration):
    """Straightforward per-event version of plot-nr-running replay_events."""
    state = list(initial)
    time_axis, states, imbalances = [], [], []
    start = None
    counter = 0
    last = None
    for t, cpu, value in zip(times, cpus, values):
        state[cpu] = value
        diff = max(state) - min(state)
        if diff >= threshold and start is None:
            start = t
        if diff < threshold and start is not None:
            if t - start >= duration:
                imbalances.append([(start, threshold), (t, threshold)])
            start = None
        counter += 1
        if counter >= sampling:
            counter = 0
            if not time_sampling or last is None or t - last >= 1.0 / time_sampling:
                time_axis.append(t)
                states.append(list(state))
                last = t
    if start is not None and times[-1] - start >= duration:
        imbalances.append([(start, threshold), (times[-1], threshold)])
    return time_axis, states, imbalances


def test_replay_matches_reference():
    plot = load("plot-nr-running.py")
    # Smallest chunks, so that traces span several of them
    plot.REPLAY_CHUNK_CELLS = 1
    rng = random.Random(1)
    for trial in range(40):
        cpus_count = rng.randint(1, 9)
        events = rng.randint(1, 3000)
        times = sorted(rng.uniform(0, 5) for _ in range(events))
        cpus = [rng.randrange(cpus_count) for _ in range(events)]
        values = [rng.randint(0, 5) for _ in range(events)]
        initial = [rng.randint(0, 3) for _ in range(cpus_count)]
        args = (rng.choice([1, 1, 2, 7]), rng.choice([0, 0, 3, 50]), rng.randint(1, 4), rng.choice([0, 0.05, 0.3]))

        with contextlib.redirect_stdout(io.StringIO()):
            time_axis, states, differences, sums, imbalances = plot.replay_events(
                array('d', times), array('i', cpus), array('i', values), initial, *args)
        expected_time_axis, expected_states, expected_imbalances = reference_replay(
            times, cpus, values, initial, *args)

        assert time_axis.tolist() == expected_time_axis, trial
        assert states.tolist() == expected_states, trial
        assert differences.tolist() == [max(s) - min(s) for s in expected_states], trial
        assert sums.tolist() == [sum(s) for s in expected_states], trial
        assert imbalances == expected_imbalances, trial


def test_sampling_does_not_change_imbalances():
    plot = load("plot-nr-running.py")
    with lzma.open(EXAMPLE_TRACE, "rt") as trace, contextlib.redirect_stdout(io.StringIO()):
        events = plot.read_events(trace)
    results = {}
    for sampling, time_sampling in ((1, 0), (7, 0), (1, 10), (5, 100)):
        with contextlib.redirect_stdout(io.StringIO()):
            time_axis, _, _, _, imbalances = plot.replay_events(*events, sampling, time_sampling, 2, 0.05)
        results[sampling, time_sampling] = (len(time_axis), imbalances)

    full_count, full_imbalances = results[1, 0]
    assert full_imbalances
    for (sampling, time_sampling), (count, imbalances) in results.items():
        assert imbalances == full_imbalances, (sampling, time_sampling)
        if (sampling, time_sampling) != (1, 0):
            assert count < full_count


# Kernel recording the change unsigned: decrements show up as change=1.
# The last event is a real gap, nr_running of CPU 0 jumps from 0 to 2.
UNSIGNED_TRACE = """\
cpus=2
 a-1 [000] 1.000000: sched_update_nr_running: cpu=0 change=1 nr_running=0
 a-1 [000] 2.000000: sched_update_nr_running: cpu=0 change=1 nr_running=1
 a-1 [001] 3.000000: sched_update_nr_running: cpu=1 change=1 nr_running=1
 a-1 [001] 4.000000: sched_update_nr_running: cpu=1 change=1 nr_running=0
 a-1 [000] 5.000000: sched_update_nr_running: cpu=0 change=1 nr_running=0
 a-1 [000] 6.000000: sched_update_nr_running: cpu=0 change=1 nr_running=2
"""


def test_unsigned_change(tmp_path):
    trace = tmp_path / "unsigned.trace"
    trace.write_text(UNSIGNED_TRACE)

    plot = load("plot-nr-running.py")
    output = io.StringIO()
    with open(str(trace)) as f, contextlib.redirect_stdout(output):
        _, _, _, initial = plot.read_events(f)
    # The first event of CPU 0 is a decrement to 0
    assert initial == [1, 0]
    assert "NOTE: No negative 'change' values found" in output.getvalue()

    complete = run("check-nr-running.py", str(trace))
    assert complete.returncode == 0, complete.stdout
    assert "NOTE: No negative 'change' values found" in complete.stdout
    # Only the real gap is reported, not the unsigned decrements
    assert "Detected missed event number 1 " in complete.stdout
    assert "Detected missed event number 2 " not in complete.stdout


def test_signed_change_has_no_note(small_trace, tmp_path):
    complete = run("plot-nr-running.py", "--image-file", str(tmp_path / "small.png"), small_trace)
    assert "NOTE" not in complete.stdout
    complete = run("check-nr-running.py", small_trace)
    assert "NOTE" not in complete.stdout


@pytest.fixture
def traces_dir(tmp_path):
    shutil.copy(EXAMPLE_LSCPU, str(tmp_path / "lscpu.txt"))
    (tmp_path / "good one.trace").write_text(SMALL_TRACE)
    (tmp_path / "bad.trace").write_text("garbage\n")
    return tmp_path


WRAPPER_MODES = [
    pytest.param([], id="sequential"),
    pytest.param(["--parallel=2"], id="parallel", marks=pytest.mark.skipif(
        shutil.which("parallel") is None, reason="GNU parallel is not installed")),
]


@pytest.mark.parametrize("mode", WRAPPER_MODES)
def test_wrapper_exit_codes(traces_dir, mode):
    wrapper = os.path.join(REPO, "plot-nr-running.sh")
    good = str(traces_dir / "good one.trace")
    bad = str(traces_dir / "bad.trace")

    complete = run_command(wrapper, "--lscpu=lscpu.txt", *mode, good, cwd=str(traces_dir))
    assert complete.returncode == 0, complete.stdout
    assert (traces_dir / "good one.png").stat().st_size > 0
    assert "| CPU | Runtime (s) |" in (traces_dir / "good one.info").read_text()

    complete = run_command(wrapper, "--lscpu=lscpu.txt", *mode, good, bad, cwd=str(traces_dir))
    assert complete.returncode == 1, complete.stdout


@pytest.mark.parametrize("mode", WRAPPER_MODES)
def test_wrapper_dry_run(traces_dir, mode):
    before = sorted(os.listdir(str(traces_dir)))
    complete = run_command(os.path.join(REPO, "plot-nr-running.sh"), "--dry", "--lscpu=lscpu.txt", *mode,
                           str(traces_dir / "good one.trace"), cwd=str(traces_dir))
    assert complete.returncode == 0, complete.stdout
    assert sorted(os.listdir(str(traces_dir))) == before
    # Each command is printed once
    commands = [line.lstrip("'") for line in complete.stdout.splitlines()]
    for script in ("plot-nr-running.py", "check-nr-running.py"):
        assert sum(line.startswith(os.path.join(REPO, script)) for line in commands) == 1, complete.stdout


@pytest.mark.parametrize("mode", WRAPPER_MODES)
def test_batch_reports_failed_directory(tmp_path, mode):
    for directory, content in (("a_good", SMALL_TRACE), ("b_bad", "garbage\n"), ("c_good", SMALL_TRACE)):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "x.trace").write_text(content)
        shutil.copy(EXAMPLE_LSCPU, str(tmp_path / directory / "lscpu.txt"))

    complete = run_command(os.path.join(REPO, "plot-nr-running_batch.sh"), "--tracename=*.trace", *mode,
                           stdin="y\ny\n", cwd=str(tmp_path))
    assert complete.returncode == 1, complete.stdout
    failed = complete.stdout.split("Error when processing trace files from following directories:")[1]
    assert "b_bad" in failed and "a_good" not in failed and "c_good" not in failed
    # Directories after the failed one are processed too
    assert (tmp_path / "a_good" / "x.png").exists()
    assert (tmp_path / "c_good" / "x.png").exists()
