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


STATE_FILE = "/tmp/spyre_entity_extract_workload_state.json"
STOP_FILE = "/tmp/spyre_entity_extract_stop_signal"
STATS_FILE = "/tmp/spyre_entity_extract_inference_stats.json"

DEFAULT_PROMPTS_FILE = "entity_extraction_prompts.json"
DEFAULT_MIN_MATCH_PCT = 50.0


def _build_prompt(text):
    """Build the entity extraction prompt for the given input text."""
    return (
        "Extract all named entities from the following text. "
        "List each entity type and the entities found.\n\n"
        f"Text: {text}\n\n"
        "Entities (format as \"Type: entity1, entity2, ...\"):\n"
    )


def _validate_entities(text, expected_entities=None, min_match_pct=DEFAULT_MIN_MATCH_PCT,
                       min_chars=3):
    """
    Validate that the generated response contains the expected entities.

    :param text: Generated text from VLLM.
    :param expected_entities: List of expected entity strings.
    :param min_match_pct: Minimum percentage of expected entities that must be found.
    :param min_chars: Minimum character length required for valid response.
    :return: Tuple of (is_valid: bool, matched_entities: list, match_pct: float, reason: str)
    """
    if not text or len(text.strip()) < min_chars:
        return False, [], 0.0, "Generated response is empty or shorter than minimum threshold"

    if not expected_entities:
        return True, [], 100.0, "No expected entities defined; response is non-empty"

    clean_text = text.lower()
    matched = [ent for ent in expected_entities if ent.lower() in clean_text]
    match_pct = len(matched) * 100.0 / len(expected_entities)

    if match_pct < min_match_pct:
        return False, matched, match_pct, (
            f"Only {len(matched)}/{len(expected_entities)} expected entities found "
            f"({match_pct:.1f}% < {min_match_pct:.1f}%)"
        )
    return True, matched, match_pct, "Entity validation passed"


def _entity_request(base_url, model, prompt_dict, max_tokens=200, req_timeout=60,
                    min_match_pct=DEFAULT_MIN_MATCH_PCT):
    """
    Send a single entity extraction request to the VLLM /v1/completions endpoint
    and validate the extracted entities.

    :return: Result dictionary describing success, output and validation state.
    """
    payload = {
        "model": model,
        "prompt": _build_prompt(prompt_dict['text']),
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "top_p": 0.9,
        "stop": ["\n\n", "Text:"],
    }
    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url}/v1/completions",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=req_timeout,
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            body = resp.json()
            text = body['choices'][0]['text'].strip()
            is_valid, matched, match_pct, reason = _validate_entities(
                text, prompt_dict.get('expected_entities'), min_match_pct
            )
            tokens = body.get('usage', {}).get('completion_tokens') or len(text.split())
            return {
                "success": True,
                "output": text,
                "valid_answer": is_valid,
                "matched_entities": matched,
                "match_pct": match_pct,
                "validation_reason": reason,
                "elapsed_time": elapsed,
                "token_count": tokens,
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
        'match_pcts': [],
        'tokens': 0, 'times': [], 'errors': [],
        'sample_extractions': [],
    }


def _record_result(stats, prompt_dict, result):
    """Update stats with one request result. Caller must hold the stats lock."""
    stats['total'] += 1
    if not result['success']:
        stats['failed'] += 1
        stats['errors'].append(result.get('error', ''))
        return

    stats['success'] += 1
    stats['tokens'] += result['token_count']
    stats['times'].append(result['elapsed_time'])
    stats['match_pcts'].append(result['match_pct'])
    if result['valid_answer']:
        stats['valid_answers'] += 1
        if len(stats['sample_extractions']) < 5:
            stats['sample_extractions'].append({
                'name': prompt_dict.get('name', ''),
                'text': prompt_dict['text'],
                'entities_preview': result['output'].replace('\n', ' ')[:200],
                'matched_entities': result['matched_entities'],
                'expected_entities': prompt_dict.get('expected_entities', []),
            })
    else:
        stats['validation_failures'] += 1


def _save_stats_to_file(stats_file, stats):
    """Save live inference stats dict to JSON file safely."""
    try:
        temp_file = f"{stats_file}.tmp"
        data = dict(stats)
        elapsed = time.time() - data.get('start_time', time.time())
        data['elapsed_seconds'] = round(elapsed, 2)
        data['throughput_tok_s'] = (
            round(data['tokens'] / elapsed, 2) if elapsed > 0 else 0.0
        )
        data['avg_time_s'] = (
            round(sum(data['times']) / len(data['times']), 3)
            if data.get('times') else 0.0
        )
        data['requests_per_sec'] = (
            round(data['total'] / elapsed, 2) if elapsed > 0 else 0.0
        )
        pcts = data.pop('match_pcts', [])
        data['avg_entity_match_pct'] = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
        total = data.get('total', 0)
        valid = data.get('valid_answers', 0)
        data['validation_rate_pct'] = (
            round((valid / total) * 100, 1) if total > 0 else 0.0
        )
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, stats_file)
    except Exception:
        pass


def _background_inference_worker(base_url, prompts, stats_file, stop_file,
                                 num_workers=2, max_duration=86400,
                                 req_timeout=60,
                                 min_match_pct=DEFAULT_MIN_MATCH_PCT):
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
    stats_lock = threading.Lock()
    end_time = time.time() + max_duration

    def _worker(worker_id):
        idx = worker_id
        while time.time() < end_time:
            if os.path.exists(stop_file):
                break
            pd = prompts[idx % len(prompts)]
            result = _entity_request(base_url, model, pd, req_timeout=req_timeout,
                                     min_match_pct=min_match_pct)
            with stats_lock:
                _record_result(stats, pd, result)
                if stats['total'] % 5 == 0:
                    _save_stats_to_file(stats_file, stats)
            idx += num_workers
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


class SpyreEntityExtractWorkloadTest(Test):
    """
    Test suite for running Entity Extraction inferencing workloads against a
    deployed Spyre AIU container while collecting AIU performance and
    utilization metrics into the Avocado results directory and validating
    the extracted entities against a sample entity dataset.

    Supported test methods:
    * ``test_start_entity_extract_workload`` — start inference workers and AIU metrics in background.
    * ``test_stop_entity_extract_workload``  — stop inference and AIU metrics, report statistics.
    * ``test_run_workload``                  — start, run for configured duration, and stop.
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

    def _get_prompts_path(self, prompts_filename=DEFAULT_PROMPTS_FILE):
        """
        Locate the entity dataset file from the .data directory or specified path.

        :param prompts_filename: Name or path of the dataset file.
        :return: Absolute path to the dataset file.
        """
        prompts_path = None
        try:
            prompts_path = self.get_data(prompts_filename)
        except Exception:
            prompts_path = None

        if not prompts_path or not os.path.exists(prompts_path):
            fallback_dir = os.path.join(
                os.path.dirname(__file__), "spyre_Entity_Extract_workload.py.data"
            )
            candidate = os.path.join(fallback_dir, prompts_filename)
            if os.path.exists(candidate):
                prompts_path = candidate
            elif os.path.exists(prompts_filename):
                prompts_path = os.path.abspath(prompts_filename)

        if not prompts_path or not os.path.exists(prompts_path):
            self.cancel(f"Entity dataset file not found: {prompts_filename}")

        return os.path.abspath(prompts_path)

    def _load_prompts(self, prompts_filename=DEFAULT_PROMPTS_FILE):
        """
        Load the sample entity dataset from the .data directory or specified path.

        :param prompts_filename: Name or path of the dataset file.
        :return: List of dictionaries with ``text`` and ``expected_entities``.
        """
        prompts_path = self._get_prompts_path(prompts_filename)
        self.log.info("Loading entity dataset from: %s", prompts_path)
        try:
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
        except Exception as exc:
            self.cancel(f"Failed to parse entity dataset {prompts_path}: {exc}")
        if not isinstance(prompts, list) or not prompts:
            self.cancel(
                f"Entity dataset {prompts_path} does not contain a non-empty list"
            )
        return prompts

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
    #  Entity extraction workload — in-process API                        #
    # ------------------------------------------------------------------ #

    def _entity_worker(self, base_url, model, prompts, end_ts_holder, stats, stats_lock,
                       req_timeout=60, min_match_pct=DEFAULT_MIN_MATCH_PCT):
        """Background thread worker: sends extraction requests in a loop until end time."""
        idx = 0
        while time.time() < end_ts_holder[0]:
            pd = prompts[idx % len(prompts)]
            result = _entity_request(base_url, model, pd, req_timeout=req_timeout,
                                     min_match_pct=min_match_pct)
            with stats_lock:
                _record_result(stats, pd, result)
            idx += 1
            time.sleep(0.1)

    def start_inference(self, base_url, prompts, num_workers=2, req_timeout=60,
                        min_match_pct=DEFAULT_MIN_MATCH_PCT):
        """Start entity extraction inference workers in background threads."""
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            model = resp.json()['data'][0]['id']
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach VLLM server at {base_url}: {exc}"
            ) from exc

        self.log.info("start_inference: model=%s  workers=%d  samples=%d",
                      model, num_workers, len(prompts))

        stats = _new_stats()
        stats_lock = threading.Lock()
        end_ts_holder = [time.time() + 86400]

        executor = ThreadPoolExecutor(max_workers=num_workers)
        futures = [
            executor.submit(
                self._entity_worker, base_url, model, prompts,
                end_ts_holder, stats, stats_lock, req_timeout, min_match_pct
            )
            for _ in range(num_workers)
        ]

        return {
            'base_url': base_url,
            'model': model,
            'prompts': prompts,
            'stats': stats,
            'stats_lock': stats_lock,
            'end_ts_holder': end_ts_holder,
            'executor': executor,
            'futures': futures,
            'start_wall': time.time(),
            'req_timeout': req_timeout,
        }

    def check_inference(self, ctx):
        """Log a live snapshot of inference metrics without stopping workers."""
        stats = ctx['stats']
        stats_lock = ctx['stats_lock']
        elapsed = time.time() - ctx['start_wall']
        with stats_lock:
            snapshot = dict(stats)
            pcts = list(snapshot['match_pcts'])
            times = list(snapshot['times'])

        throughput = snapshot['tokens'] / elapsed if elapsed > 0 else 0.0
        avg_time = sum(times) / len(times) if times else 0.0
        avg_match = sum(pcts) / len(pcts) if pcts else 0.0
        total = snapshot['total']
        valid = snapshot['valid_answers']
        valid_rate = (valid / total * 100) if total > 0 else 0.0

        self.log.info(
            "check_inference [%.0fs elapsed] total=%d success=%d valid=%d (%.1f%%) "
            "failed=%d tokens=%d throughput=%.2f tok/s avg_req=%.3fs avg_entity_match=%.1f%%",
            elapsed, total, snapshot['success'], valid, valid_rate,
            snapshot['failed'], snapshot['tokens'], throughput, avg_time, avg_match
        )

        if snapshot['failed'] > 0 and snapshot['errors']:
            self.log.warning("Recent errors: %s",
                             "; ".join(snapshot['errors'][-3:]))

        return {
            'total': snapshot['total'],
            'success': snapshot['success'],
            'valid_answers': snapshot['valid_answers'],
            'validation_failures': snapshot['validation_failures'],
            'failed': snapshot['failed'],
            'tokens': snapshot['tokens'],
            'throughput_tok_s': round(throughput, 2),
            'avg_time_s': round(avg_time, 3),
            'avg_entity_match_pct': round(avg_match, 1),
            'sample_extractions': list(snapshot.get('sample_extractions', [])),
        }

    def stop_inference(self, ctx, req_timeout=None):
        """Signal workers to stop and wait for them to finish."""
        ctx['end_ts_holder'][0] = 0.0

        wait = req_timeout or ctx.get('req_timeout', 60)
        for fut in as_completed(ctx['futures'], timeout=wait + 5):
            try:
                fut.result()
            except Exception as exc:
                self.log.warning("Worker raised: %s", exc)
        ctx['executor'].shutdown(wait=False)

        return self.check_inference(ctx)

    def _log_sample_extractions(self, samples):
        """Log sample validated extractions."""
        if not samples:
            return
        self.log.info("=== Sample Validated Entity Extractions ===")
        for idx, sample in enumerate(samples, start=1):
            self.log.info(
                "Sample #%d [%s]:\n  Text: %s\n  Entities: %s\n  Matched: %s (of %s)",
                idx, sample.get('name', ''), sample['text'],
                sample['entities_preview'],
                ", ".join(sample.get('matched_entities', [])),
                ", ".join(sample.get('expected_entities', []))
            )

    # ------------------------------------------------------------------ #
    #  Explicit start / stop lifecycle tests                             #
    # ------------------------------------------------------------------ #

    def test_start_entity_extract_workload(self):
        """
        Start Entity Extraction inferencing workload and AIU metrics collection in background.

        Collects AIU metrics into the default Avocado results directory (self.logdir)
        and saves background process state to
        ``/tmp/spyre_entity_extract_workload_state.json``.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Entity Extraction workload")

        use_case = self.params.get("USE_CASE", default="entity_extract")
        container_name = self.params.get(
            "CONTAINER_NAME", default="spyre-entity-extract"
        )
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        num_workers = int(self.params.get("WORKERS", default=2))
        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=60))
        prompts_file = self.params.get("PROMPTS_FILE", default=DEFAULT_PROMPTS_FILE)
        min_match_pct = float(self.params.get("MIN_ENTITY_MATCH_PCT", default=DEFAULT_MIN_MATCH_PCT))
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info("=== test_start_entity_extract_workload: container=%s ===", container_name)

        if not self.check_container_running(container_name):
            self.fail(f"Container {container_name} is not running")

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        base_url = f"http://127.0.0.1:{port}"
        prompts = self._load_prompts(prompts_file)

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

        # 2. Start background inference worker process
        self.log.info("Starting background inference worker process (%d workers)", num_workers)
        worker_proc = multiprocessing.Process(
            target=_background_inference_worker,
            args=(
                base_url,
                prompts,
                STATS_FILE,
                STOP_FILE,
                num_workers,
                duration_minutes * 60,
                60,
                min_match_pct
            ),
            daemon=True
        )
        worker_proc.start()
        SpyreEntityExtractWorkloadTest._active_worker_process = worker_proc

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
                f"Background inference process exited immediately with code {worker_proc.exitcode}"
            )

        self.log.info(
            "PASS: test_start_entity_extract_workload — Workload and metrics started successfully (PID: %d)",
            worker_proc.pid
        )

    def test_stop_entity_extract_workload(self):
        """
        Stop running Entity Extraction inferencing workload and AIU metrics collection.

        Reads process state from ``/tmp/spyre_entity_extract_workload_state.json``,
        terminates workers, validates extraction correctness, and preserves
        the metrics log in the Avocado results directory (self.logdir).
        """
        self.log.info("=== test_stop_entity_extract_workload ===")

        if not os.path.exists(STATE_FILE):
            self.cancel(f"No active workload found (state file {STATE_FILE} missing)")

        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as ex:
            self.fail(f"Failed to read workload state file {STATE_FILE}: {ex}")

        # 1. Signal background inference process to stop
        stop_file = state.get("stop_file", STOP_FILE)
        try:
            with open(stop_file, 'w') as f:
                f.write("stop\n")
        except Exception as ex:
            self.log.warning("Could not write stop file: %s", ex)

        inference_pid = state.get("inference_pid")
        if inference_pid:
            self.log.info("Waiting for inference process (PID: %d) to terminate", inference_pid)
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

        # 3. Read and report inference stats
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
        validation_failures = stats.get('validation_failures', 0)
        tokens = stats.get('tokens', 0)
        throughput = stats.get('throughput_tok_s', 0.0)
        avg_time = stats.get('avg_time_s', 0.0)
        avg_match = stats.get('avg_entity_match_pct', 0.0)

        self.log.info(
            "Entity Extraction workload summary: total=%d success=%d valid_answers=%d "
            "validation_failures=%d tokens=%d throughput=%.2f tok/s avg_req=%.3fs "
            "avg_entity_match=%.1f%%",
            total, success, valid, validation_failures, tokens, throughput, avg_time, avg_match
        )

        self._log_sample_extractions(stats.get('sample_extractions', []))

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
                f"Entity Extraction workload FAILED: 0 successful requests out of {total}. Errors: "
                + "; ".join(errors[:5])
            )

        if success > 0 and valid == 0:
            self.fail(
                f"Entity Extraction workload FAILED: None of the {success} responses passed entity validation."
            )

        validation_rate = (valid / total * 100) if total else 0
        self.log.info(
            "PASS: test_stop_entity_extract_workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, valid, total
        )

    # ------------------------------------------------------------------ #
    #  Integrated workload test runner                                   #
    # ------------------------------------------------------------------ #

    def run_entity_extract_workload(self, container_name, port, prompts,
                                    duration_minutes=5, num_workers=2,
                                    check_interval=30, stats_command="aiu-smi --csv",
                                    dtcompiler_export_dir=None,
                                    min_match_pct=DEFAULT_MIN_MATCH_PCT):
        """
        Run the complete Entity Extraction inferencing workload against a running
        Spyre container with entity validation.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for Entity Extraction workload tests")

        base_url = f"http://127.0.0.1:{port}"
        self.log.info(
            "run_entity_extract_workload: container=%s  url=%s  duration=%d min  workers=%d  samples=%d",
            container_name, base_url, duration_minutes, num_workers, len(prompts)
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

        # 2. Start inference
        try:
            ctx = self.start_inference(base_url, prompts=prompts, num_workers=num_workers,
                                       min_match_pct=min_match_pct)
        except RuntimeError as exc:
            if metrics_process is not None:
                try:
                    metrics_process.terminate()
                except Exception:
                    pass
            self.fail(str(exc))

        end_wall = time.time() + duration_minutes * 60
        self.log.info(
            "Entity Extraction workload running — will stop at %s",
            datetime.fromtimestamp(end_wall).strftime('%H:%M:%S')
        )

        # 3. Check loop
        while time.time() < end_wall:
            sleep_secs = min(check_interval, max(0, end_wall - time.time()))
            if sleep_secs <= 0:
                break
            time.sleep(sleep_secs)
            self.check_inference(ctx)

        # 4. Stop inference
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
        self.log.info(
            "Entity Extraction workload finished: total=%d success=%d valid_answers=%d "
            "tokens=%d throughput=%.2f tok/s avg_req=%.3fs avg_entity_match=%.1f%%",
            final['total'], final['success'], final.get('valid_answers', 0),
            final['tokens'], final['throughput_tok_s'], final['avg_time_s'],
            final['avg_entity_match_pct']
        )

        self._log_sample_extractions(final.get('sample_extractions', []))

        if final['success'] == 0:
            self.fail(
                f"Entity Extraction workload FAILED: 0 successful requests out of "
                f"{final['total']} total. Errors: "
                + "; ".join(ctx['stats']['errors'][:5])
            )

        if final.get('valid_answers', 0) == 0:
            self.fail(
                f"Entity Extraction workload FAILED: 0 responses passed entity validation "
                f"out of {final['success']} successful requests."
            )

        validation_rate = (
            final.get('valid_answers', 0) / final['total'] * 100
            if final['total'] else 0
        )
        self.log.info(
            "PASS: Entity Extraction workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, final.get('valid_answers', 0), final['total']
        )

    def test_run_workload(self):
        """
        Run an Entity Extraction inferencing workload against the deployed Spyre
        container and collect AIU metrics into the Avocado results directory.

        Reads ``USE_CASE`` and ``CONTAINER_NAME`` from YAML.
        """
        use_case = self.params.get("USE_CASE", default="entity_extract")
        container_name = self.params.get(
            "CONTAINER_NAME", default="spyre-entity-extract"
        )
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=5))
        num_workers = int(self.params.get("WORKERS", default=2))
        check_interval = int(self.params.get("CHECK_INTERVAL", default=30))
        prompts_file = self.params.get("PROMPTS_FILE", default=DEFAULT_PROMPTS_FILE)
        min_match_pct = float(self.params.get("MIN_ENTITY_MATCH_PCT", default=DEFAULT_MIN_MATCH_PCT))
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info(
            "=== test_run_workload: use_case=%s  container=%s  duration=%d min ===",
            use_case, container_name, duration_minutes
        )

        prompts = self._load_prompts(prompts_file)

        if not self.check_container_running(container_name):
            self.fail(
                f"Container {container_name} is not running — "
                "start it first with test_create_container"
            )

        port = self._get_container_port(container_name)
        if not port:
            self.fail(f"Could not determine host port for container {container_name}")

        self.log.info("Container %s is running on port %s", container_name, port)

        if use_case == "entity_extract":
            self.run_entity_extract_workload(
                container_name=container_name,
                port=port,
                prompts=prompts,
                duration_minutes=duration_minutes,
                num_workers=num_workers,
                check_interval=check_interval,
                stats_command=stats_command,
                dtcompiler_export_dir=dtcompiler_export_dir,
                min_match_pct=min_match_pct,
            )
        else:
            self.cancel(
                f"No workload implementation for use case '{use_case}'. "
                "Supported: entity_extract"
            )
