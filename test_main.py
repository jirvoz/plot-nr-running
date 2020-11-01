import subprocess


def test_exec_on_example():
    complete = subprocess.run(
        [
            "./plot-nr-running.py",
            "--lscpu-file",
            "example/lscpu.txt",
            "--image-file",
            "NAS_48_threads_group_imbalance_bug.png",
            "example/NAS_48_threads_group_imbalance_bug.trace.xz",
        ]
    )
    assert complete.returncode == 0
