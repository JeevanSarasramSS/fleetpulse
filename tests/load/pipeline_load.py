"""End-to-end pipeline load test with a zero-loss check, against the running docker compose stack.

usage: python tests/load/pipeline_load.py --rate 10000 --duration 300 --burst-every 60 --processors 8

1. stops the background simulator and restarts N processors (fresh dedup state);
2. runs a one-off simulator at --rate events/s, with 3x bursts for 10 s every --burst-every seconds;
3. samples consumer lag every 5 s, then waits for the lag to drain;
4. counts telemetry rows written since the start and compares them with the unique events the simulator sent.
Afterwards it restores the compose defaults (simulator running, default processor count).
"""
import argparse
import re
import statistics
import subprocess
import threading
import time

DC = ["docker", "compose"]


def sh(args, **kw) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True, **kw).stdout


def lag() -> int:
    out = sh(DC + ["exec", "-T", "redpanda", "rpk", "group", "describe", "processor"])
    m = re.search(r"TOTAL-LAG\s+(\d+)", out)
    return int(m.group(1)) if m else -1


def psql(q: str) -> str:
    return sh(DC + ["exec", "-T", "postgres", "psql", "-U", "fleet", "-d", "fleet", "-Atc", q]).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=10000)
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--burst-every", type=int, default=60)
    ap.add_argument("--processors", type=int, default=8)
    ap.add_argument("--default-processors", type=int, default=4)
    ap.add_argument("--simulators", type=int, default=1, help="parallel producers, each owning 1/k of the fleet")
    a = ap.parse_args()

    sh(DC + ["stop", "simulator"])
    sh(DC + ["up", "-d", "--no-deps", "--force-recreate", "--scale", f"processor={a.processors}", "processor"])
    deadline = time.time() + 120
    while lag() > 0 and time.time() < deadline:  # let the new group settle and drain leftovers
        time.sleep(3)
    t0 = psql("SELECT now()")
    samples, stop = [], threading.Event()

    def sampler():
        while not stop.is_set():
            samples.append((time.time(), lag()))
            stop.wait(5)

    threading.Thread(target=sampler, daemon=True).start()
    t_start = time.time()
    k = a.simulators
    runs = [subprocess.Popen(DC + ["run", "--rm", "--no-deps", "simulator", "python", "-m", "fleetpulse.simulator.run",
                                   "--rate", str(a.rate // k), "--duration", str(a.duration),
                                   "--burst-every", str(a.burst_every), "--shard", f"{i}/{k}"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) for i in range(k)]
    outs = [r.communicate()[0] for r in runs]
    t_sent = time.time()
    done = [re.search(r"done: (\d+) events \((\d+) unique\)", o) for o in outs]
    sent, unique = sum(int(m.group(1)) for m in done), sum(int(m.group(2)) for m in done)
    while lag() > 0 and time.time() - t_sent < 600:
        time.sleep(2)
    t_drained = time.time()
    stop.set()
    time.sleep(3)  # last batch commit
    written = int(psql(f"SELECT count(*) FROM telemetry WHERE ts >= '{t0}'"))

    lags = [x for _, x in samples if x >= 0]
    print(f"rate={a.rate}/s base over {k} producer(s), 3x bursts for 10 s every {a.burst_every} s, "
          f"duration={a.duration} s, processors={a.processors}")
    print(f"sent={sent} (incl. duplicate deliveries)  unique={unique}  written={written}  "
          f"missing={unique - written} ({(unique - written) / unique:.4%})")
    print(f"producer phase {t_sent - t_start:.0f} s -> {unique / (t_sent - t_start):.0f} unique events/s offered; "
          f"backlog drained {t_drained - t_sent:.0f} s after the producer stopped; "
          f"end-to-end {unique / (t_drained - t_start):.0f} events/s processed")
    if lags:
        print(f"consumer lag: max={max(lags)} median={statistics.median(lags):.0f} samples={len(lags)}")

    sh(DC + ["up", "-d", "--no-deps", "--scale", f"processor={a.default_processors}", "processor"])
    sh(DC + ["start", "simulator"])


if __name__ == "__main__":
    main()
