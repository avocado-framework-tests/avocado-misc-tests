#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Authors: Abdul Haleem (abdhalee@linux.ibm.com)

import json
import math
import multiprocessing
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from avocado import Test
from avocado.utils import cpu, process
from avocado.utils.podman import Podman, PodmanException

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


STATE_FILE = "/tmp/spyre_embedding_workload_state.json"
STOP_FILE = "/tmp/spyre_embedding_stop_signal"
STATS_FILE = "/tmp/spyre_embedding_inference_stats.json"

DEFAULT_TEXTS_FILE = "embedding_texts.json"
DEFAULT_BATCH_SIZE = 50
DEFAULT_REQ_TIMEOUT = 600


def _validate_embeddings(embeddings, expected_count):
    """
    Validate the embeddings returned for a batch of texts.

    Checks that the number of vectors matches the number of inputs, that all
    vectors share the same non-zero dimension, that every value is a finite
    number and that no vector is all zeros.

    :param embeddings: List of embedding vectors returned by VLLM.
    :param expected_count: Number of input texts sent in the request.
    :return: Tuple of (is_valid: bool, dimension: int, reason: str)
    """
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        got = len(embeddings) if isinstance(embeddings, list) else 'n/a'
        return False, 0, f"Expected {expected_count} embeddings, got {got}"

    dimension = len(embeddings[0]) if embeddings and embeddings[0] else 0
    if dimension == 0:
        return False, 0, "Embedding vector is empty"

    for idx, vec in enumerate(embeddings):
        if len(vec) != dimension:
            return False, dimension, (
                f"Embedding #{idx} has dimension {len(vec)}, expected {dimension}"
            )
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vec):
            return False, dimension, f"Embedding #{idx} contains NaN/Inf/non-numeric values"
        if not any(vec):
            return False, dimension, f"Embedding #{idx} is an all-zero vector"

    return True, dimension, "Embedding validation passed"


def _make_batch(texts, batch_no, batch_size):
    """Build a batch of ``batch_size`` texts by cycling through the dataset."""
    start = batch_no * batch_size
    return [texts[(start + i) % len(texts)] for i in range(batch_size)]


def _embedding_request(base_url, model, batch, req_timeout=DEFAULT_REQ_TIMEOUT):
    """
    Send one batch of texts to the VLLM /v1/embeddings endpoint and validate
    the returned embeddings.

    :return: Result dictionary describing success, validation and timing.
    """
    payload = {"model": model, "input": batch}
    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url}/v1/embeddings",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=req_timeout,
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            data = sorted(resp.json()['data'], key=lambda d: d.get('index', 0))
            embeddings = [d['embedding'] for d in data]
            is_valid, dimension, reason = _validate_embeddings(embeddings, len(batch))
            return {
                "success": True,
                "valid_answer": is_valid,
                "validation_reason": reason,
                "num_embeddings": len(embeddings),
                "dimension": dimension,
                "elapsed_time": elapsed,
            }
        return {
            "success": False,
            "valid_answer": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            "elapsed_time": elapsed,
        }
    except requests.exceptions.Timeout:
        return {
            "success": False, "valid_answer": False,
            "error": "Request timeout", "elapsed_time": req_timeout
        }
    except Exception as exc:
        return {
            "success": False, "valid_answer": False,
            "error": str(exc), "elapsed_time": 0
        }


def _new_stats():
    """Return an empty inference stats dictionary."""
    return {
        'total': 0, 'success': 0, 'failed': 0,
        'valid_answers': 0, 'validation_failures': 0,
        'embeddings': 0, 'dimension': 0,
        'times': [], 'errors': [], 'validation_errors': [],
    }


def _record_result(stats, result):
    """Update stats with one request result. Caller must hold the stats lock."""
    stats['total'] += 1
    if not result['success']:
        stats['failed'] += 1
        stats['errors'].append(result.get('error', ''))
        return

    stats['success'] += 1
    stats['embeddings'] += result['num_embeddings']
    stats['times'].append(result['elapsed_time'])
    if result['valid_answer']:
        stats['valid_answers'] += 1
        stats['dimension'] = result['dimension']
    else:
        stats['validation_failures'] += 1
        if len(stats['validation_errors']) < 10:
            stats['validation_errors'].append(result['validation_reason'])


def _percentile(sorted_values, pct):
    """Return the given percentile of an already sorted list."""
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100.0))
    return sorted_values[idx]


def _summarize(stats, elapsed):
    """Compute derived metrics from a stats snapshot."""
    times = sorted(stats['times'])
    total = stats['total']
    return {
        'elapsed_seconds': round(elapsed, 2),
        'embeddings_per_sec': round(stats['embeddings'] / elapsed, 2) if elapsed > 0 else 0.0,
        'requests_per_sec': round(total / elapsed, 2) if elapsed > 0 else 0.0,
        'avg_time_s': round(sum(times) / len(times), 3) if times else 0.0,
        'min_time_s': round(times[0], 3) if times else 0.0,
        'max_time_s': round(times[-1], 3) if times else 0.0,
        'p50_time_s': round(_percentile(times, 50), 3),
        'p95_time_s': round(_percentile(times, 95), 3),
        'p99_time_s': round(_percentile(times, 99), 3),
        'validation_rate_pct': (
            round(stats['valid_answers'] * 100.0 / total, 1) if total > 0 else 0.0
        ),
    }


def _save_stats_to_file(stats_file, stats):
    """Save live inference stats dict to JSON file safely."""
    try:
        temp_file = f"{stats_file}.tmp"
        data = dict(stats)
        elapsed = time.time() - data.get('start_time', time.time())
        data.update(_summarize(stats, elapsed))
        data.pop('times', None)
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, stats_file)
    except Exception:
        pass


def _background_inference_worker(base_url, texts, stats_file, stop_file,
                                 num_workers=8, max_duration=86400,
                                 req_timeout=DEFAULT_REQ_TIMEOUT,
                                 batch_size=DEFAULT_BATCH_SIZE):
    """
    Background worker loop executed by multiprocessing daemon.
    Runs until stop_file exists or max_duration is reached.
    """
    try:
        resp = requests.get(f"{base_url}/v1/models", timeout=15)
        resp.raise_for_status()
        model = resp.json()['data'][0]['id']
    except Exception:
        model = "vllm-model"

    stats = _new_stats()
    stats['start_time'] = time.time()
    stats['model'] = model
    stats['batch_size'] = batch_size
    stats_lock = threading.Lock()
    end_time = time.time() + max_duration

    def _worker(worker_id):
        batch_no = worker_id
        while time.time() < end_time:
            if os.path.exists(stop_file):
                break
            batch = _make_batch(texts, batch_no, batch_size)
            result = _embedding_request(base_url, model, batch, req_timeout)
            with stats_lock:
                _record_result(stats, result)
                if stats['total'] % 5 == 0:
                    _save_stats_to_file(stats_file, stats)
            batch_no += num_workers
            time.sleep(0.1)

    threads = [
        threading.Thread(target=_worker, args=(i,), daemon=True)
        for i in range(num_workers)
    ]
    for t in threads:
        t.start()

    while any(t.is_alive() for t in threads):
        if os.path.exists(stop_file) or time.time() >= end_time:
            break
        time.sleep(1)
        with stats_lock:
            _save_stats_to_file(stats_file, stats)

    for t in threads:
        t.join(timeout=5)

    with stats_lock:
        _save_stats_to_file(stats_file, stats)


class SpyreEmbeddingWorkloadTest(Test):
    """
    Test suite for running Embedding generation workloads against a deployed
    Spyre AIU container while collecting AIU performance and utilization
    metrics into the Avocado results directory and validating the returned
    embedding vectors.

    Supported test methods:
    * ``test_start_embedding_workload`` — start embedding workers and AIU metrics in background.
    * ``test_stop_embedding_workload``  — stop workers and AIU metrics, report statistics.
    * ``test_run_workload``             — start, run for configured duration, and stop.
    """

    test_user = None
    podman = None
    _active_worker_process = None

    def run_cmd(self, cmd, sudo=True):
        """Execute a command and return True if successful, False otherwise."""
        if process.system(cmd, sudo=sudo, shell=True):
            return False
        return True

    @staticmethod
    def run_cmd_out(cmd, sudo=True):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, ignore_status=True,
            sudo=sudo).decode("utf-8").strip()

    def setUp(self):
        """Set up test environment."""
        if 'powerpc' not in cpu.get_arch() and "ppc" not in os.uname()[4]:
            self.cancel("Supported only on IBM Power platform")

        self.test_user = self.params.get("USER", default="")
        if not self.test_user:
            self.test_user = self.run_cmd_out('whoami')

        self.port_mapping = self.params.get(
            "PORT_MAPPING", default="127.0.0.1:8000:8000")

        try:
            self.podman = Podman()
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman utility: {ex}")

    def _get_texts_path(self, texts_filename=DEFAULT_TEXTS_FILE):
        """
        Locate the sample texts file from the .data directory or specified path.

        :param texts_filename: Name or path of the texts file.
        :return: Absolute path to the texts file.
        """
        texts_path = None
        try:
            texts_path = self.get_data(texts_filename)
        except Exception:
            texts_path = None

        if not texts_path or not os.path.exists(texts_path):
            fallback_dir = os.path.join(
                os.path.dirname(__file__), "spyre_Embedding_workload.py.data"
            )
            candidate = os.path.join(fallback_dir, texts_filename)
            if os.path.exists(candidate):
                texts_path = candidate
            elif os.path.exists(texts_filename):
                texts_path = os.path.abspath(texts_filename)

        if not texts_path or not os.path.exists(texts_path):
            self.cancel(f"Embedding texts file not found: {texts_filename}")

        return os.path.abspath(texts_path)

    def _load_texts(self, texts_filename=DEFAULT_TEXTS_FILE):
        """
        Load the sample texts from the .data directory or specified path.

        :param texts_filename: Name or path of the texts file.
        :return: List of text strings.
        """
        texts_path = self._get_texts_path(texts_filename)
        self.log.info("Loading embedding texts from: %s", texts_path)
        try:
            with open(texts_path, 'r', encoding='utf-8') as f:
                texts = json.load(f)
        except Exception as exc:
            self.cancel(f"Failed to parse embedding texts {texts_path}: {exc}")
        if (not isinstance(texts, list) or not texts
                or not all(isinstance(t, str) and t for t in texts)):
            self.cancel(
                f"Embedding texts {texts_path} must be a non-empty list of non-empty strings"
            )
        return texts

    def _resolve_metrics_file(self, container_name):
        """
        Determine the dedicated log file path for saving AIU metrics
        in the default Avocado results directory (self.logdir).

        :param container_name: Name of the container being tested.
        :return: Resolved path for the metrics log file.
        """
        results_dir = None
        for dir_attr in ('logdir', 'outputdir', 'workdir'):
            if hasattr(self, dir_attr):
                val = getattr(self, dir_attr)
                if val and os.path.exists(val):
                    results_dir = val
                    break

        if not results_dir:
            results_dir = "/tmp"

        default_file = os.path.join(results_dir, f"aiu_metrics_{container_name}.log")
        metrics_file = self.params.get("METRICS_FILE", default=default_file)
        if not metrics_file:
            metrics_file = default_file

        parent_dir = os.path.dirname(os.path.abspath(metrics_file))
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as ex:
                self.log.warning("Could not create metrics directory %s: %s", parent_dir, ex)
        return metrics_file

    def check_container_running(self, container_name):
        """
        Check if a container is running.

        :param container_name: Name of the container
        :return: True if container is running, False otherwise
        """
        if self.test_user and self.test_user != "root":
            cmd = (
                f"su - {self.test_user} -c "
                f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman ps --filter name={container_name} --format {{{{.Names}}}}'"
            )
        else:
            cmd = f"podman ps --filter name={container_name} --format '{{{{.Names}}}}'"
        output = self.run_cmd_out(cmd, sudo=True)
        return container_name in output

    def _get_container_port(self, container_name):
        """
        Retrieve the host-side port mapped for a running container.

        Parses ``podman port <container>`` output, e.g.::

            8000/tcp -> 127.0.0.1:8000

        :param container_name: Name of the running Podman container.
        :return: Port string (e.g. ``"8000"``) or ``None`` if not found.
        """
        if self.test_user and self.test_user != "root":
            cmd = (
                f"su - {self.test_user} -c "
                f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman port {container_name}'"
            )
        else:
            cmd = f"podman port {container_name}"
        output = self.run_cmd_out(cmd, sudo=True)
        for line in output.splitlines():
            if '->' in line:
                host_part = line.split('->')[-1].strip()
                port = host_part.rsplit(':', 1)[-1]
                if port.isdigit():
                    return port
        if hasattr(self, 'port_mapping') and self.port_mapping:
            parts = self.port_mapping.split(':')
            if parts:
                candidate = parts[-1]
                if candidate.isdigit():
                    return candidate
        return None

    # ------------------------------------------------------------------ #
    #  Embedding workload — in-process API                                #
    # ------------------------------------------------------------------ #

    def _embedding_worker(self, base_url, model, texts, worker_id, num_workers,
                          end_ts_holder, stats, stats_lock, batch_size, req_timeout):
        """Background thread worker: sends embedding batches in a loop until end time."""
        batch_no = worker_id
        while time.time() < end_ts_holder[0]:
            batch = _make_batch(texts, batch_no, batch_size)
            result = _embedding_request(base_url, model, batch, req_timeout)
            with stats_lock:
                _record_result(stats, result)
            batch_no += num_workers
            time.sleep(0.1)

    def start_inference(self, base_url, texts, num_workers=8,
                        batch_size=DEFAULT_BATCH_SIZE, req_timeout=DEFAULT_REQ_TIMEOUT):
        """Start embedding workers in background threads."""
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            model = resp.json()['data'][0]['id']
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach VLLM server at {base_url}: {exc}"
            ) from exc

        self.log.info("start_inference: model=%s  workers=%d  batch_size=%d  texts=%d",
                      model, num_workers, batch_size, len(texts))

        stats = _new_stats()
        stats_lock = threading.Lock()
        end_ts_holder = [time.time() + 86400]

        executor = ThreadPoolExecutor(max_workers=num_workers)
        futures = [
            executor.submit(
                self._embedding_worker, base_url, model, texts, i, num_workers,
                end_ts_holder, stats, stats_lock, batch_size, req_timeout
            )
            for i in range(num_workers)
        ]

        return {
            'base_url': base_url,
            'model': model,
            'texts': texts,
            'stats': stats,
            'stats_lock': stats_lock,
            'end_ts_holder': end_ts_holder,
            'executor': executor,
            'futures': futures,
            'start_wall': time.time(),
            'req_timeout': req_timeout,
        }

    def check_inference(self, ctx):
        """Log a live snapshot of embedding metrics without stopping workers."""
        elapsed = time.time() - ctx['start_wall']
        with ctx['stats_lock']:
            snapshot = dict(ctx['stats'])
            snapshot['times'] = list(snapshot['times'])
            snapshot['errors'] = list(snapshot['errors'])
            snapshot['validation_errors'] = list(snapshot['validation_errors'])

        summary = _summarize(snapshot, elapsed)

        self.log.info(
            "check_inference [%.0fs elapsed] requests=%d success=%d valid=%d (%.1f%%) "
            "failed=%d embeddings=%d dim=%d throughput=%.2f emb/s avg_req=%.3fs",
            elapsed, snapshot['total'], snapshot['success'], snapshot['valid_answers'],
            summary['validation_rate_pct'], snapshot['failed'], snapshot['embeddings'],
            snapshot['dimension'], summary['embeddings_per_sec'], summary['avg_time_s']
        )

        if snapshot['failed'] > 0 and snapshot['errors']:
            self.log.warning("Recent errors: %s", "; ".join(snapshot['errors'][-3:]))
        if snapshot['validation_errors']:
            self.log.warning("Validation errors: %s",
                             "; ".join(snapshot['validation_errors'][-3:]))

        result = {key: snapshot[key] for key in (
            'total', 'success', 'failed', 'valid_answers',
            'validation_failures', 'embeddings', 'dimension')}
        result.update(summary)
        return result

    def stop_inference(self, ctx, req_timeout=None):
        """Signal workers to stop and wait for them to finish."""
        ctx['end_ts_holder'][0] = 0.0

        wait = req_timeout or ctx.get('req_timeout', DEFAULT_REQ_TIMEOUT)
        for fut in as_completed(ctx['futures'], timeout=wait + 5):
            try:
                fut.result()
            except Exception as exc:
                self.log.warning("Worker raised: %s", exc)
        ctx['executor'].shutdown(wait=False)

        return self.check_inference(ctx)

    def _log_performance(self, data):
        """Log the performance summary for a stats dictionary."""
        self.log.info(
            "Embedding workload summary: requests=%d success=%d valid=%d "
            "validation_failures=%d failed=%d embeddings=%d dimension=%d",
            data.get('total', 0), data.get('success', 0), data.get('valid_answers', 0),
            data.get('validation_failures', 0), data.get('failed', 0),
            data.get('embeddings', 0), data.get('dimension', 0)
        )
        self.log.info(
            "Performance: %.2f embeddings/s, %.2f req/s | request time avg=%.3fs "
            "min=%.3fs max=%.3fs p50=%.3fs p95=%.3fs p99=%.3fs",
            data.get('embeddings_per_sec', 0.0), data.get('requests_per_sec', 0.0),
            data.get('avg_time_s', 0.0), data.get('min_time_s', 0.0),
            data.get('max_time_s', 0.0), data.get('p50_time_s', 0.0),
            data.get('p95_time_s', 0.0), data.get('p99_time_s', 0.0)
        )

    # ------------------------------------------------------------------ #
    #  Explicit start / stop lifecycle tests                             #
    # ------------------------------------------------------------------ #

    def test_start_embedding_workload(self):
        """
        Start Embedding workload and AIU metrics collection in background.

        Collects AIU metrics into the default Avocado results directory (self.logdir)
        and saves background process state to
        ``/tmp/spyre_embedding_workload_state.json``.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Embedding workload")

        use_case = self.params.get("USE_CASE", default="embedding")
        container_name = self.params.get("CONTAINER_NAME", default="spyre-embedding")
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        num_workers = int(self.params.get("WORKERS", default=8))
        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=60))
        batch_size = int(self.params.get("BATCH_SIZE", default=DEFAULT_BATCH_SIZE))
        req_timeout = int(self.params.get("REQUEST_TIMEOUT", default=DEFAULT_REQ_TIMEOUT))
        texts_file = self.params.get("PROMPTS_FILE", default=DEFAULT_TEXTS_FILE)
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info("=== test_start_embedding_workload: container=%s ===", container_name)

        if not self.check_container_running(container_name):
            self.fail(f"Container {container_name} is not running")

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        base_url = f"http://127.0.0.1:{port}"
        texts = self._load_texts(texts_file)

        # Cleanup any lingering stop signal or previous state
        if os.path.exists(STOP_FILE):
            try:
                os.remove(STOP_FILE)
            except OSError:
                pass

        user = self.test_user if (self.test_user and self.test_user != "root") else None
        metrics_file = self._resolve_metrics_file(container_name)

        if user:
            try:
                self.run_cmd(f"touch {metrics_file} {STATS_FILE}")
                self.run_cmd(f"chown {user}:{user} {metrics_file} {STATS_FILE}")
            except Exception as ex:
                self.log.warning("Could not pre-create metrics/stats file: %s", ex)

        # 1. Start AIU metrics collection in Avocado results directory
        self.log.info("Starting AIU metrics collection (metrics log: %s)", metrics_file)
        metrics_process = None
        try:
            metrics_process = self.podman.collect_container_aiu_metrics(
                container_id=container_name,
                output_file=metrics_file,
                dtcompiler_export_dir=dtcompiler_export_dir,
                stats_command=stats_command,
                timeout=(duration_minutes * 60) + 120,
                user=user
            )
            self.log.info(
                "AIU metrics collection started in results log file: %s (PID: %s)",
                metrics_file, getattr(metrics_process, 'pid', 'unknown')
            )
        except Exception as ex:
            self.log.warning("Failed to start AIU metrics collection: %s", ex)

        # 2. Start background embedding worker process
        self.log.info("Starting background embedding worker process (%d workers)", num_workers)
        worker_proc = multiprocessing.Process(
            target=_background_inference_worker,
            args=(
                base_url,
                texts,
                STATS_FILE,
                STOP_FILE,
                num_workers,
                duration_minutes * 60,
                req_timeout,
                batch_size
            ),
            daemon=True
        )
        worker_proc.start()
        SpyreEmbeddingWorkloadTest._active_worker_process = worker_proc

        state = {
            "container_name": container_name,
            "use_case": use_case,
            "port": port,
            "base_url": base_url,
            "metrics_file": metrics_file,
            "metrics_pid": metrics_process.pid if metrics_process else None,
            "inference_pid": worker_proc.pid,
            "stats_file": STATS_FILE,
            "stop_file": STOP_FILE,
            "start_time": time.time(),
        }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)

        # Allow workers to initialize and verify process is alive
        time.sleep(3)
        if not worker_proc.is_alive():
            self.fail(
                f"Background embedding process exited immediately with code {worker_proc.exitcode}"
            )

        self.log.info(
            "PASS: test_start_embedding_workload — Workload and metrics started successfully (PID: %d)",
            worker_proc.pid
        )

    def test_stop_embedding_workload(self):
        """
        Stop running Embedding workload and AIU metrics collection.

        Reads process state from ``/tmp/spyre_embedding_workload_state.json``,
        terminates workers, validates embedding correctness, and preserves
        the metrics log in the Avocado results directory (self.logdir).
        """
        self.log.info("=== test_stop_embedding_workload ===")

        if not os.path.exists(STATE_FILE):
            self.cancel(f"No active workload found (state file {STATE_FILE} missing)")

        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as ex:
            self.fail(f"Failed to read workload state file {STATE_FILE}: {ex}")

        # 1. Signal background process to stop
        stop_file = state.get("stop_file", STOP_FILE)
        try:
            with open(stop_file, 'w') as f:
                f.write("stop\n")
        except Exception as ex:
            self.log.warning("Could not write stop file: %s", ex)

        inference_pid = state.get("inference_pid")
        if inference_pid:
            self.log.info("Waiting for embedding process (PID: %d) to terminate", inference_pid)
            try:
                os.kill(inference_pid, 15)  # SIGTERM
            except OSError:
                pass

        # 2. Stop AIU metrics collection process
        metrics_pid = state.get("metrics_pid")
        if metrics_pid:
            self.log.info("Stopping metrics process (PID: %s)", metrics_pid)
            try:
                os.kill(metrics_pid, 15)
            except OSError:
                pass

        # Also terminate any podman exec aiu-smi commands if lingering
        container_name = state.get("container_name", "")
        if container_name:
            self.run_cmd_out("pkill -f 'aiu-smi' || true", sudo=True)

        time.sleep(2)

        # 3. Read and report stats
        stats_file = state.get("stats_file", STATS_FILE)
        stats = {}
        if os.path.exists(stats_file):
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
            except Exception as ex:
                self.log.warning("Could not read stats file: %s", ex)

        total = stats.get('total', 0)
        success = stats.get('success', 0)
        valid = stats.get('valid_answers', 0)

        self._log_performance(stats)
        if stats.get('validation_errors'):
            self.log.warning("Validation errors: %s",
                             "; ".join(stats['validation_errors'][:5]))

        # 4. Read and report dedicated AIU metrics log file in results directory
        metrics_file = state.get("metrics_file", "")
        if metrics_file and os.path.exists(metrics_file):
            if hasattr(self, 'logdir') and self.logdir and os.path.exists(self.logdir):
                target_metrics = os.path.join(self.logdir, os.path.basename(metrics_file))
                if os.path.abspath(target_metrics) != os.path.abspath(metrics_file):
                    try:
                        shutil.copyfile(metrics_file, target_metrics)
                        self.log.info(
                            "Metrics log copied to current results directory: %s",
                            target_metrics
                        )
                    except Exception as copy_ex:
                        self.log.warning("Could not copy metrics log to logdir: %s", copy_ex)

            file_size = os.path.getsize(metrics_file)
            self.log.info(
                "AIU metrics log file: %s (size: %d bytes)", metrics_file, file_size
            )
            try:
                with open(metrics_file, 'r') as f:
                    preview = f.readlines()[:10]
                    if preview:
                        self.log.info(
                            "AIU metrics log preview (first 10 lines):\n%s",
                            ''.join(preview)
                        )
            except Exception as ex:
                self.log.warning("Could not read metrics log file: %s", ex)
        else:
            self.log.warning("Metrics log file not found: %s", metrics_file)

        # Clean up state and stop files
        for fpath in (STATE_FILE, stop_file):
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass

        # 5. Evaluate result
        if total > 0 and success == 0:
            errors = stats.get('errors', [])
            self.fail(
                f"Embedding workload FAILED: 0 successful requests out of {total}. Errors: "
                + "; ".join(errors[:5])
            )

        if success > 0 and valid == 0:
            self.fail(
                f"Embedding workload FAILED: None of the {success} responses passed embedding validation."
            )

        validation_rate = (valid / total * 100) if total else 0
        self.log.info(
            "PASS: test_stop_embedding_workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, valid, total
        )

    # ------------------------------------------------------------------ #
    #  Integrated workload test runner                                   #
    # ------------------------------------------------------------------ #

    def run_embedding_workload(self, container_name, port, texts,
                               duration_minutes=5, num_workers=8,
                               check_interval=30, stats_command="aiu-smi --csv",
                               dtcompiler_export_dir=None,
                               batch_size=DEFAULT_BATCH_SIZE,
                               req_timeout=DEFAULT_REQ_TIMEOUT):
        """
        Run the complete Embedding workload against a running Spyre container
        with embedding validation.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Embedding workload tests")

        base_url = f"http://127.0.0.1:{port}"
        self.log.info(
            "run_embedding_workload: container=%s  url=%s  duration=%d min  workers=%d  batch_size=%d  texts=%d",
            container_name, base_url, duration_minutes, num_workers, batch_size, len(texts)
        )

        user = self.test_user if (self.test_user and self.test_user != "root") else None
        metrics_file = self._resolve_metrics_file(container_name)

        if user:
            try:
                self.run_cmd(f"touch {metrics_file}")
                self.run_cmd(f"chown {user}:{user} {metrics_file}")
            except Exception as ex:
                self.log.warning("Could not pre-create metrics log file: %s", ex)

        # 1. Start AIU metrics collection into results log file
        metrics_process = None
        metrics_timeout = (duration_minutes * 60) + 60
        self.log.info(
            "Starting AIU metrics collection in results dir (log: %s, command: %s)",
            metrics_file, stats_command
        )
        try:
            metrics_process = self.podman.collect_container_aiu_metrics(
                container_id=container_name,
                output_file=metrics_file,
                dtcompiler_export_dir=dtcompiler_export_dir,
                stats_command=stats_command,
                timeout=metrics_timeout,
                user=user
            )
            self.log.info(
                "AIU metrics collection started in results log file: %s", metrics_file
            )
        except Exception as ex:
            self.log.warning("Failed to start AIU metrics collection: %s", ex)

        # 2. Start embedding workers
        try:
            ctx = self.start_inference(base_url, texts=texts, num_workers=num_workers,
                                       batch_size=batch_size, req_timeout=req_timeout)
        except RuntimeError as exc:
            if metrics_process is not None:
                try:
                    metrics_process.terminate()
                except Exception:
                    pass
            self.fail(str(exc))

        end_wall = time.time() + duration_minutes * 60
        self.log.info(
            "Embedding workload running — will stop at %s",
            datetime.fromtimestamp(end_wall).strftime('%H:%M:%S')
        )

        # 3. Check loop
        while time.time() < end_wall:
            sleep_secs = min(check_interval, max(0, end_wall - time.time()))
            if sleep_secs <= 0:
                break
            time.sleep(sleep_secs)
            self.check_inference(ctx)

        # 4. Stop workers
        final = self.stop_inference(ctx)

        # 5. Stop AIU metrics collection
        self.log.info("Stopping AIU metrics collection")
        if metrics_process is not None:
            try:
                metrics_process.terminate()
                self.log.info("AIU metrics collection process terminated")
            except Exception as ex:
                self.log.warning("Error stopping AIU metrics process: %s", ex)

        if os.path.exists(metrics_file):
            file_size = os.path.getsize(metrics_file)
            self.log.info(
                "AIU metrics log file saved in results dir: %s (size: %d bytes)",
                metrics_file, file_size
            )
            try:
                with open(metrics_file, 'r') as f:
                    preview_lines = f.readlines()[:10]
                    if preview_lines:
                        self.log.info(
                            "AIU metrics log file preview (first 10 lines):\n%s",
                            ''.join(preview_lines)
                        )
            except Exception as ex:
                self.log.warning("Could not read metrics log file: %s", ex)
        else:
            self.log.warning("Metrics log file was not created: %s", metrics_file)

        # Result evaluation
        self._log_performance(final)

        if final['success'] == 0:
            self.fail(
                f"Embedding workload FAILED: 0 successful requests out of "
                f"{final['total']} total. Errors: "
                + "; ".join(ctx['stats']['errors'][:5])
            )

        if final['valid_answers'] == 0:
            self.fail(
                f"Embedding workload FAILED: 0 responses passed embedding validation "
                f"out of {final['success']} successful requests. Reasons: "
                + "; ".join(ctx['stats']['validation_errors'][:5])
            )

        validation_rate = (
            final['valid_answers'] / final['total'] * 100 if final['total'] else 0
        )
        self.log.info(
            "PASS: Embedding workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, final['valid_answers'], final['total']
        )

    def test_run_workload(self):
        """
        Run an Embedding workload against the deployed Spyre container and
        collect AIU metrics into the Avocado results directory.

        Reads ``USE_CASE`` and ``CONTAINER_NAME`` from YAML.
        """
        use_case = self.params.get("USE_CASE", default="embedding")
        container_name = self.params.get("CONTAINER_NAME", default="spyre-embedding")
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=5))
        num_workers = int(self.params.get("WORKERS", default=8))
        check_interval = int(self.params.get("CHECK_INTERVAL", default=30))
        batch_size = int(self.params.get("BATCH_SIZE", default=DEFAULT_BATCH_SIZE))
        req_timeout = int(self.params.get("REQUEST_TIMEOUT", default=DEFAULT_REQ_TIMEOUT))
        texts_file = self.params.get("PROMPTS_FILE", default=DEFAULT_TEXTS_FILE)
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info(
            "=== test_run_workload: use_case=%s  container=%s  duration=%d min ===",
            use_case, container_name, duration_minutes
        )

        texts = self._load_texts(texts_file)

        if not self.check_container_running(container_name):
            self.fail(
                f"Container {container_name} is not running — "
                "start it first with test_create_container"
            )

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        self.log.info("Container %s is running on port %s", container_name, port)

        if use_case == "embedding":
            self.run_embedding_workload(
                container_name=container_name,
                port=port,
                texts=texts,
                duration_minutes=duration_minutes,
                num_workers=num_workers,
                check_interval=check_interval,
                stats_command=stats_command,
                dtcompiler_export_dir=dtcompiler_export_dir,
                batch_size=batch_size,
                req_timeout=req_timeout,
            )
        else:
            self.cancel(
                f"No workload implementation for use case '{use_case}'. "
                "Supported: embedding"
            )
