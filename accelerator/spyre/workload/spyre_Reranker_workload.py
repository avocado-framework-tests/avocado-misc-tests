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

import csv
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


STATE_FILE = "/tmp/spyre_reranker_workload_state.json"
STOP_FILE = "/tmp/spyre_reranker_stop_signal"
STATS_FILE = "/tmp/spyre_reranker_inference_stats.json"

DEFAULT_DATASET_FILE = "demo_scoring_dataset.csv"
DEFAULT_BATCH_SIZE = 20
DEFAULT_REQ_TIMEOUT = 600
DEFAULT_MIN_RANK_PCT = 80.0
DEFAULT_MODEL = "/models/bge-reranker-v2-m3"
SCORE_ENDPOINT = "/score"

# Tolerance used to report how close scores are to the dataset's expected scores
SCORE_RTOL = 0.02
SCORE_ATOL = 0.03


def _load_dataset_rows(path):
    """
    Load query/document pairs from a CSV file with columns
    ``document``, ``query`` and ``score``.

    :param path: Path to the CSV dataset.
    :return: List of dicts with ``query``, ``document`` and ``expected_score``.
    :raises ValueError: If the file has missing columns or no rows.
    """
    rows = []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        missing = {'document', 'query', 'score'} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            rows.append({
                'query': row['query'],
                'document': row['document'],
                'expected_score': float(row['score']),
            })
    if not rows:
        raise ValueError("dataset contains no rows")
    return rows


def _build_batches(rows, batch_size):
    """
    Group dataset rows into request batches without splitting a query's
    documents across batches, so the ranking can be verified for each query.

    Whole query groups are appended to a batch until it holds at least
    ``batch_size`` pairs.

    :return: List of batches, each a list of row dicts.
    """
    groups = {}
    for row in rows:
        groups.setdefault(row['query'], []).append(row)

    batches, current = [], []
    for group in groups.values():
        current.extend(group)
        if len(current) >= batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches


def _validate_scores(scores, expected_count):
    """
    Validate the scores returned for a batch of pairs.

    :param scores: List of scores returned by VLLM.
    :param expected_count: Number of pairs sent in the request.
    :return: Tuple of (is_valid: bool, reason: str)
    """
    if not isinstance(scores, list) or len(scores) != expected_count:
        got = len(scores) if isinstance(scores, list) else 'n/a'
        return False, f"Expected {expected_count} scores, got {got}"
    for idx, score in enumerate(scores):
        if (isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score)):
            return False, f"Score #{idx} is not a finite number: {score!r}"
    return True, "Score validation passed"


def _compare_with_expected(batch, scores):
    """
    Compare actual scores of a batch with the dataset's expected scores.

    For every query in the batch that has at least two documents, the document
    with the highest expected score must also get the highest actual score.

    :return: Dict with ranking and tolerance counters for the batch.
    """
    abs_diffs = [abs(s - row['expected_score']) for row, s in zip(batch, scores)]
    tol_matches = sum(
        1 for row, s in zip(batch, scores)
        if abs(s - row['expected_score']) <= SCORE_ATOL + SCORE_RTOL * abs(row['expected_score'])
    )

    by_query = {}
    for idx, row in enumerate(batch):
        by_query.setdefault(row['query'], []).append(idx)

    ranking_checks = ranking_correct = 0
    for indices in by_query.values():
        if len(indices) < 2:
            continue
        ranking_checks += 1
        best_expected = max(indices, key=lambda i: batch[i]['expected_score'])
        best_actual = max(indices, key=lambda i: scores[i])
        if best_expected == best_actual:
            ranking_correct += 1

    return {
        'ranking_checks': ranking_checks,
        'ranking_correct': ranking_correct,
        'tol_matches': tol_matches,
        'abs_diff_sum': sum(abs_diffs),
        'abs_diff_max': max(abs_diffs) if abs_diffs else 0.0,
    }


def _score_request(base_url, model, batch, req_timeout=DEFAULT_REQ_TIMEOUT):
    """
    Send one batch of query/document pairs to the VLLM score endpoint and
    validate the returned scores.

    :return: Result dictionary describing success, validation and timing.
    """
    payload = {
        "model": model,
        "text_1": [row['query'] for row in batch],
        "text_2": [row['document'] for row in batch],
    }
    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url}{SCORE_ENDPOINT}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=req_timeout,
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            data = sorted(resp.json()['data'], key=lambda d: d.get('index', 0))
            scores = [d['score'] for d in data]
            is_valid, reason = _validate_scores(scores, len(batch))
            result = {
                "success": True,
                "valid_answer": is_valid,
                "validation_reason": reason,
                "num_pairs": len(batch),
                "elapsed_time": elapsed,
            }
            if is_valid:
                result["scores"] = scores
                result.update(_compare_with_expected(batch, scores))
            return result
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
        'pairs': 0, 'scored_pairs': 0,
        'score_min': None, 'score_max': None, 'score_sum': 0.0,
        'ranking_checks': 0, 'ranking_correct': 0,
        'tol_matches': 0, 'abs_diff_sum': 0.0, 'abs_diff_max': 0.0,
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
    stats['pairs'] += result['num_pairs']
    stats['times'].append(result['elapsed_time'])
    if not result['valid_answer']:
        stats['validation_failures'] += 1
        if len(stats['validation_errors']) < 10:
            stats['validation_errors'].append(result['validation_reason'])
        return

    stats['valid_answers'] += 1
    scores = result['scores']
    stats['scored_pairs'] += len(scores)
    stats['score_sum'] += sum(scores)
    lo, hi = min(scores), max(scores)
    stats['score_min'] = lo if stats['score_min'] is None else min(stats['score_min'], lo)
    stats['score_max'] = hi if stats['score_max'] is None else max(stats['score_max'], hi)
    for key in ('ranking_checks', 'ranking_correct', 'tol_matches', 'abs_diff_sum'):
        stats[key] += result[key]
    stats['abs_diff_max'] = max(stats['abs_diff_max'], result['abs_diff_max'])


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
    scored = stats['scored_pairs']
    checks = stats['ranking_checks']
    return {
        'elapsed_seconds': round(elapsed, 2),
        'pairs_per_sec': round(stats['pairs'] / elapsed, 2) if elapsed > 0 else 0.0,
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
        'avg_score': round(stats['score_sum'] / scored, 4) if scored else 0.0,
        'avg_abs_diff': round(stats['abs_diff_sum'] / scored, 4) if scored else 0.0,
        'within_tolerance_pct': (
            round(stats['tol_matches'] * 100.0 / scored, 1) if scored else 0.0
        ),
        'ranking_accuracy_pct': (
            round(stats['ranking_correct'] * 100.0 / checks, 1) if checks else 0.0
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


def _discover_model(base_url, timeout=15):
    """Return the served model id, falling back to the default BGE reranker path."""
    try:
        resp = requests.get(f"{base_url}/v1/models", timeout=timeout)
        resp.raise_for_status()
        return resp.json()['data'][0]['id']
    except Exception:
        return DEFAULT_MODEL


def _background_inference_worker(base_url, batches, stats_file, stop_file,
                                 num_workers=8, max_duration=86400,
                                 req_timeout=DEFAULT_REQ_TIMEOUT):
    """
    Background worker loop executed by multiprocessing daemon.
    Runs until stop_file exists or max_duration is reached.
    """
    model = _discover_model(base_url)

    stats = _new_stats()
    stats['start_time'] = time.time()
    stats['model'] = model
    stats_lock = threading.Lock()
    end_time = time.time() + max_duration

    def _worker(worker_id):
        batch_no = worker_id
        while time.time() < end_time:
            if os.path.exists(stop_file):
                break
            batch = batches[batch_no % len(batches)]
            result = _score_request(base_url, model, batch, req_timeout)
            with stats_lock:
                _record_result(stats, result)
                if stats['total'] % 5 == 0:
                    _save_stats_to_file(stats_file, stats)
            batch_no += num_workers
            time.sleep(0.05)

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


class SpyreRerankerWorkloadTest(Test):
    """
    Test suite for running Reranker (query/document scoring) workloads against
    a deployed Spyre AIU container while collecting AIU performance and
    utilization metrics into the Avocado results directory and validating the
    returned relevance scores against a sample scoring dataset.

    Supported test methods:
    * ``test_start_reranker_workload`` — start scoring workers and AIU metrics in background.
    * ``test_stop_reranker_workload``  — stop workers and AIU metrics, report statistics.
    * ``test_run_workload``            — start, run for configured duration, and stop.
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

    def _get_dataset_path(self, dataset_filename=DEFAULT_DATASET_FILE):
        """
        Locate the scoring dataset from the .data directory or specified path.

        :param dataset_filename: Name or path of the dataset file.
        :return: Absolute path to the dataset file.
        """
        dataset_path = None
        try:
            dataset_path = self.get_data(dataset_filename)
        except Exception:
            dataset_path = None

        if not dataset_path or not os.path.exists(dataset_path):
            fallback_dir = os.path.join(
                os.path.dirname(__file__), "spyre_Reranker_workload.py.data"
            )
            candidate = os.path.join(fallback_dir, dataset_filename)
            if os.path.exists(candidate):
                dataset_path = candidate
            elif os.path.exists(dataset_filename):
                dataset_path = os.path.abspath(dataset_filename)

        if not dataset_path or not os.path.exists(dataset_path):
            self.cancel(f"Scoring dataset file not found: {dataset_filename}")

        return os.path.abspath(dataset_path)

    def _load_batches(self, dataset_filename, batch_size):
        """
        Load the scoring dataset and group it into request batches.

        :param dataset_filename: Name or path of the dataset file.
        :param batch_size: Minimum number of pairs per request.
        :return: List of batches (lists of row dicts).
        """
        dataset_path = self._get_dataset_path(dataset_filename)
        self.log.info("Loading scoring dataset from: %s", dataset_path)
        try:
            rows = _load_dataset_rows(dataset_path)
        except Exception as exc:
            self.cancel(f"Failed to parse scoring dataset {dataset_path}: {exc}")
        batches = _build_batches(rows, batch_size)
        self.log.info("Loaded %d pairs, %d request batches (batch_size=%d)",
                      len(rows), len(batches), batch_size)
        return batches

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
    #  Reranker workload — in-process API                                 #
    # ------------------------------------------------------------------ #

    def _reranker_worker(self, base_url, model, batches, worker_id, num_workers,
                         end_ts_holder, stats, stats_lock, req_timeout):
        """Background thread worker: sends scoring batches in a loop until end time."""
        batch_no = worker_id
        while time.time() < end_ts_holder[0]:
            batch = batches[batch_no % len(batches)]
            result = _score_request(base_url, model, batch, req_timeout)
            with stats_lock:
                _record_result(stats, result)
            batch_no += num_workers
            time.sleep(0.05)

    def start_inference(self, base_url, batches, num_workers=8,
                        req_timeout=DEFAULT_REQ_TIMEOUT):
        """Start reranker scoring workers in background threads."""
        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach VLLM server at {base_url}: {exc}"
            ) from exc

        model = _discover_model(base_url, timeout=10)
        self.log.info("start_inference: model=%s  workers=%d  batches=%d",
                      model, num_workers, len(batches))

        stats = _new_stats()
        stats_lock = threading.Lock()
        end_ts_holder = [time.time() + 86400]

        executor = ThreadPoolExecutor(max_workers=num_workers)
        futures = [
            executor.submit(
                self._reranker_worker, base_url, model, batches, i, num_workers,
                end_ts_holder, stats, stats_lock, req_timeout
            )
            for i in range(num_workers)
        ]

        return {
            'base_url': base_url,
            'model': model,
            'batches': batches,
            'stats': stats,
            'stats_lock': stats_lock,
            'end_ts_holder': end_ts_holder,
            'executor': executor,
            'futures': futures,
            'start_wall': time.time(),
            'req_timeout': req_timeout,
        }

    def check_inference(self, ctx):
        """Log a live snapshot of reranker metrics without stopping workers."""
        elapsed = time.time() - ctx['start_wall']
        with ctx['stats_lock']:
            snapshot = dict(ctx['stats'])
            snapshot['times'] = list(snapshot['times'])
            snapshot['errors'] = list(snapshot['errors'])
            snapshot['validation_errors'] = list(snapshot['validation_errors'])

        summary = _summarize(snapshot, elapsed)

        self.log.info(
            "check_inference [%.0fs elapsed] requests=%d success=%d valid=%d (%.1f%%) "
            "failed=%d pairs=%d throughput=%.2f pairs/s avg_req=%.3fs ranking_acc=%.1f%%",
            elapsed, snapshot['total'], snapshot['success'], snapshot['valid_answers'],
            summary['validation_rate_pct'], snapshot['failed'], snapshot['pairs'],
            summary['pairs_per_sec'], summary['avg_time_s'], summary['ranking_accuracy_pct']
        )

        if snapshot['failed'] > 0 and snapshot['errors']:
            self.log.warning("Recent errors: %s", "; ".join(snapshot['errors'][-3:]))
        if snapshot['validation_errors']:
            self.log.warning("Validation errors: %s",
                             "; ".join(snapshot['validation_errors'][-3:]))

        result = {key: snapshot[key] for key in (
            'total', 'success', 'failed', 'valid_answers', 'validation_failures',
            'pairs', 'scored_pairs', 'score_min', 'score_max',
            'ranking_checks', 'ranking_correct', 'abs_diff_max')}
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
        """Log the performance and accuracy summary for a stats dictionary."""
        self.log.info(
            "Reranker workload summary: requests=%d success=%d valid=%d "
            "validation_failures=%d failed=%d pairs=%d",
            data.get('total', 0), data.get('success', 0), data.get('valid_answers', 0),
            data.get('validation_failures', 0), data.get('failed', 0), data.get('pairs', 0)
        )
        self.log.info(
            "Performance: %.2f pairs/s, %.2f req/s | request time avg=%.3fs "
            "min=%.3fs max=%.3fs p50=%.3fs p95=%.3fs p99=%.3fs",
            data.get('pairs_per_sec', 0.0), data.get('requests_per_sec', 0.0),
            data.get('avg_time_s', 0.0), data.get('min_time_s', 0.0),
            data.get('max_time_s', 0.0), data.get('p50_time_s', 0.0),
            data.get('p95_time_s', 0.0), data.get('p99_time_s', 0.0)
        )
        self.log.info(
            "Accuracy vs expected: score range=[%s, %s] avg_score=%.4f avg_abs_diff=%.4f "
            "max_abs_diff=%.4f within_tolerance=%.1f%% ranking_accuracy=%.1f%% (%d/%d queries)",
            data.get('score_min'), data.get('score_max'), data.get('avg_score', 0.0),
            data.get('avg_abs_diff', 0.0), data.get('abs_diff_max', 0.0),
            data.get('within_tolerance_pct', 0.0), data.get('ranking_accuracy_pct', 0.0),
            data.get('ranking_correct', 0), data.get('ranking_checks', 0)
        )

    def _check_ranking(self, data, min_rank_pct):
        """Fail the test if the ranking accuracy is below the configured minimum."""
        checks = data.get('ranking_checks', 0)
        if checks and data.get('ranking_accuracy_pct', 0.0) < min_rank_pct:
            self.fail(
                f"Reranker workload FAILED: ranking accuracy "
                f"{data.get('ranking_accuracy_pct', 0.0):.1f}% "
                f"({data.get('ranking_correct', 0)}/{checks}) is below the minimum "
                f"{min_rank_pct:.1f}%"
            )

    # ------------------------------------------------------------------ #
    #  Explicit start / stop lifecycle tests                             #
    # ------------------------------------------------------------------ #

    def test_start_reranker_workload(self):
        """
        Start Reranker workload and AIU metrics collection in background.

        Collects AIU metrics into the default Avocado results directory (self.logdir)
        and saves background process state to
        ``/tmp/spyre_reranker_workload_state.json``.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Reranker workload")

        use_case = self.params.get("USE_CASE", default="reranker")
        container_name = self.params.get("CONTAINER_NAME", default="spyre-reranker")
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        num_workers = int(self.params.get("WORKERS", default=8))
        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=60))
        batch_size = int(self.params.get("BATCH_SIZE", default=DEFAULT_BATCH_SIZE))
        req_timeout = int(self.params.get("REQUEST_TIMEOUT", default=DEFAULT_REQ_TIMEOUT))
        dataset_file = self.params.get("DATASET_FILE", default=DEFAULT_DATASET_FILE)
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info("=== test_start_reranker_workload: container=%s ===", container_name)

        if not self.check_container_running(container_name):
            self.fail(f"Container {container_name} is not running")

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        base_url = f"http://127.0.0.1:{port}"
        batches = self._load_batches(dataset_file, batch_size)

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

        # 2. Start background scoring worker process
        self.log.info("Starting background reranker worker process (%d workers)", num_workers)
        worker_proc = multiprocessing.Process(
            target=_background_inference_worker,
            args=(
                base_url,
                batches,
                STATS_FILE,
                STOP_FILE,
                num_workers,
                duration_minutes * 60,
                req_timeout
            ),
            daemon=True
        )
        worker_proc.start()
        SpyreRerankerWorkloadTest._active_worker_process = worker_proc

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
                f"Background reranker process exited immediately with code {worker_proc.exitcode}"
            )

        self.log.info(
            "PASS: test_start_reranker_workload — Workload and metrics started successfully (PID: %d)",
            worker_proc.pid
        )

    def test_stop_reranker_workload(self):
        """
        Stop running Reranker workload and AIU metrics collection.

        Reads process state from ``/tmp/spyre_reranker_workload_state.json``,
        terminates workers, validates scoring correctness, and preserves
        the metrics log in the Avocado results directory (self.logdir).
        """
        self.log.info("=== test_stop_reranker_workload ===")

        if not os.path.exists(STATE_FILE):
            self.cancel(f"No active workload found (state file {STATE_FILE} missing)")

        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as ex:
            self.fail(f"Failed to read workload state file {STATE_FILE}: {ex}")

        min_rank_pct = float(self.params.get("MIN_RANK_ACCURACY_PCT", default=DEFAULT_MIN_RANK_PCT))

        # 1. Signal background process to stop
        stop_file = state.get("stop_file", STOP_FILE)
        try:
            with open(stop_file, 'w') as f:
                f.write("stop\n")
        except Exception as ex:
            self.log.warning("Could not write stop file: %s", ex)

        inference_pid = state.get("inference_pid")
        if inference_pid:
            self.log.info("Waiting for reranker process (PID: %d) to terminate", inference_pid)
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
                f"Reranker workload FAILED: 0 successful requests out of {total}. Errors: "
                + "; ".join(errors[:5])
            )

        if success > 0 and valid == 0:
            self.fail(
                f"Reranker workload FAILED: None of the {success} responses passed score validation."
            )

        self._check_ranking(stats, min_rank_pct)

        validation_rate = (valid / total * 100) if total else 0
        self.log.info(
            "PASS: test_stop_reranker_workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, valid, total
        )

    # ------------------------------------------------------------------ #
    #  Integrated workload test runner                                   #
    # ------------------------------------------------------------------ #

    def run_reranker_workload(self, container_name, port, batches,
                              duration_minutes=5, num_workers=8,
                              check_interval=30, stats_command="aiu-smi --csv",
                              dtcompiler_export_dir=None,
                              req_timeout=DEFAULT_REQ_TIMEOUT,
                              min_rank_pct=DEFAULT_MIN_RANK_PCT):
        """
        Run the complete Reranker workload against a running Spyre container
        with score validation.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Reranker workload tests")

        base_url = f"http://127.0.0.1:{port}"
        self.log.info(
            "run_reranker_workload: container=%s  url=%s  duration=%d min  workers=%d  batches=%d",
            container_name, base_url, duration_minutes, num_workers, len(batches)
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

        # 2. Start scoring workers
        try:
            ctx = self.start_inference(base_url, batches=batches, num_workers=num_workers,
                                       req_timeout=req_timeout)
        except RuntimeError as exc:
            if metrics_process is not None:
                try:
                    metrics_process.terminate()
                except Exception:
                    pass
            self.fail(str(exc))

        end_wall = time.time() + duration_minutes * 60
        self.log.info(
            "Reranker workload running — will stop at %s",
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
                f"Reranker workload FAILED: 0 successful requests out of "
                f"{final['total']} total. Errors: "
                + "; ".join(ctx['stats']['errors'][:5])
            )

        if final['valid_answers'] == 0:
            self.fail(
                f"Reranker workload FAILED: 0 responses passed score validation "
                f"out of {final['success']} successful requests. Reasons: "
                + "; ".join(ctx['stats']['validation_errors'][:5])
            )

        self._check_ranking(final, min_rank_pct)

        validation_rate = (
            final['valid_answers'] / final['total'] * 100 if final['total'] else 0
        )
        self.log.info(
            "PASS: Reranker workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, final['valid_answers'], final['total']
        )

    def test_run_workload(self):
        """
        Run a Reranker workload against the deployed Spyre container and
        collect AIU metrics into the Avocado results directory.

        Reads ``USE_CASE`` and ``CONTAINER_NAME`` from YAML.
        """
        use_case = self.params.get("USE_CASE", default="reranker")
        container_name = self.params.get("CONTAINER_NAME", default="spyre-reranker")
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=5))
        num_workers = int(self.params.get("WORKERS", default=8))
        check_interval = int(self.params.get("CHECK_INTERVAL", default=30))
        batch_size = int(self.params.get("BATCH_SIZE", default=DEFAULT_BATCH_SIZE))
        req_timeout = int(self.params.get("REQUEST_TIMEOUT", default=DEFAULT_REQ_TIMEOUT))
        dataset_file = self.params.get("DATASET_FILE", default=DEFAULT_DATASET_FILE)
        min_rank_pct = float(self.params.get("MIN_RANK_ACCURACY_PCT", default=DEFAULT_MIN_RANK_PCT))
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info(
            "=== test_run_workload: use_case=%s  container=%s  duration=%d min ===",
            use_case, container_name, duration_minutes
        )

        batches = self._load_batches(dataset_file, batch_size)

        if not self.check_container_running(container_name):
            self.fail(
                f"Container {container_name} is not running — "
                "start it first with test_create_container"
            )

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        self.log.info("Container %s is running on port %s", container_name, port)

        if use_case == "reranker":
            self.run_reranker_workload(
                container_name=container_name,
                port=port,
                batches=batches,
                duration_minutes=duration_minutes,
                num_workers=num_workers,
                check_interval=check_interval,
                stats_command=stats_command,
                dtcompiler_export_dir=dtcompiler_export_dir,
                req_timeout=req_timeout,
                min_rank_pct=min_rank_pct,
            )
        else:
            self.cancel(
                f"No workload implementation for use case '{use_case}'. "
                "Supported: reranker"
            )
