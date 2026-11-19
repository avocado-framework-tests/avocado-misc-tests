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


STATE_FILE = "/tmp/spyre_rag_workload_state.json"
STOP_FILE = "/tmp/spyre_rag_stop_signal"
STATS_FILE = "/tmp/spyre_rag_inference_stats.json"


def _validate_answer(text, expected_keywords=None, min_chars=15):
    """
    Validate that the generated response is coherent and contains expected keywords.

    :param text: Generated text from VLLM.
    :param expected_keywords: List of expected keyword strings.
    :param min_chars: Minimum character length required for valid response.
    :return: Tuple of (is_valid: bool, matched_keywords: list, reason: str)
    """
    if not text or len(text.strip()) < min_chars:
        return False, [], "Generated response is empty or shorter than minimum threshold"

    clean_text = text.lower()
    matched = []
    if expected_keywords:
        for kw in expected_keywords:
            if kw.lower() in clean_text:
                matched.append(kw)

        if not matched:
            return False, [], f"None of the expected keywords ({expected_keywords}) found in answer"

    return True, matched, "Answer validation passed"


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
        total = data.get('total', 0)
        valid = data.get('valid_answers', 0)
        data['validation_rate_pct'] = (
            round((valid / total) * 100, 1) if total > 0 else 0.0
        )
        # Summarize prefix caching speedup if prefix groups recorded
        prefix_latencies = data.get('prefix_latencies', {})
        if prefix_latencies:
            cold_times = [times[0] for times in prefix_latencies.values() if times]
            warm_times = [t for times in prefix_latencies.values() for t in times[1:]]
            avg_cold = sum(cold_times) / len(cold_times) if cold_times else 0.0
            avg_warm = sum(warm_times) / len(warm_times) if warm_times else 0.0
            data['prefix_cache_avg_cold_s'] = round(avg_cold, 3)
            data['prefix_cache_avg_warm_s'] = round(avg_warm, 3)
            data['prefix_cache_speedup_pct'] = (
                round(((avg_cold - avg_warm) / avg_cold) * 100, 1)
                if avg_cold > 0 and avg_warm > 0 else 0.0
            )
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, stats_file)
    except Exception:
        pass


def _background_inference_worker(base_url, prompts, stats_file, stop_file,
                                 num_workers=2, max_duration=86400,
                                 req_timeout=120):
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

    stats = {
        'total': 0, 'success': 0, 'failed': 0,
        'valid_answers': 0, 'validation_failures': 0,
        'prefix_caching_requests': 0,
        'chunked_prefill_requests': 0,
        'prefix_latencies': {},
        'tokens': 0, 'times': [], 'errors': [],
        'sample_qa': [],
        'start_time': time.time(),
        'model': model,
    }
    stats_lock = threading.Lock()
    end_time = time.time() + max_duration

    def _worker(worker_id):
        idx = worker_id
        while time.time() < end_time:
            if os.path.exists(stop_file):
                break
            pd = prompts[idx % len(prompts)]
            full_prompt = (
                f"Context: {pd['context']}\n\n"
                f"Question: {pd['question']}\n\nAnswer:"
            )
            url = f"{base_url}/v1/completions"
            payload = {
                "model": model,
                "prompt": full_prompt,
                "max_tokens": 64,
                "temperature": 0.0,
                "ignore_eos": False,
            }
            t0 = time.time()
            try:
                r = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=req_timeout,
                )
                elapsed = time.time() - t0
                if r.status_code == 200:
                    text = r.json()['choices'][0]['text']
                    toks = len(text.split())
                    is_valid, matched, reason = _validate_answer(
                        text, pd.get('expected_keywords')
                    )
                    test_type = pd.get('test_type', '')
                    prefix_group = pd.get('prefix_group', '')
                    with stats_lock:
                        stats['total'] += 1
                        stats['success'] += 1
                        stats['tokens'] += toks
                        stats['times'].append(elapsed)
                        if is_valid:
                            stats['valid_answers'] += 1
                        else:
                            stats['validation_failures'] += 1

                        if test_type == 'prefix_caching' or prefix_group:
                            stats['prefix_caching_requests'] += 1
                            if prefix_group:
                                stats['prefix_latencies'].setdefault(prefix_group, []).append(elapsed)
                        if test_type == 'chunked_prefill' or len(pd['context'].split()) > 80:
                            stats['chunked_prefill_requests'] += 1

                        if len(stats['sample_qa']) < 5 and is_valid:
                            stats['sample_qa'].append({
                                'question': pd['question'],
                                'answer_preview': text.strip().replace('\n', ' ')[:160],
                                'matched_keywords': matched,
                                'test_type': test_type or 'rag',
                            })
                else:
                    with stats_lock:
                        stats['total'] += 1
                        stats['failed'] += 1
                        stats['errors'].append(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as ex:
                with stats_lock:
                    stats['total'] += 1
                    stats['failed'] += 1
                    stats['errors'].append(str(ex))

            if stats['total'] % 5 == 0:
                with stats_lock:
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


class SpyreRAGWorkloadTest(Test):
    """
    Test suite for running RAG (Retrieval-Augmented Generation) inferencing
    workloads against a deployed Spyre AIU container while collecting
    AIU performance and utilization metrics into the Avocado results directory
    and validating answer correctness.

    Supported test methods:
    * ``test_start_RAG_workload`` — start inference workers and AIU metrics in background.
    * ``test_stop_RAG_workload``  — stop inference and AIU metrics, report statistics.
    * ``test_run_workload``       — start, run for configured duration, and stop.
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

    def _get_prompts_path(self, prompts_filename="rag_prompts.json"):
        """
        Locate the RAG prompts file from the .data directory or specified path.

        :param prompts_filename: Name or path of the prompts file.
        :return: Absolute path to the prompts file.
        """
        prompts_path = None
        try:
            prompts_path = self.get_data(prompts_filename)
        except Exception:
            prompts_path = None

        if not prompts_path or not os.path.exists(prompts_path):
            fallback_dir = os.path.join(
                os.path.dirname(__file__), "spyre_RAG_workload.py.data"
            )
            candidate = os.path.join(fallback_dir, prompts_filename)
            if os.path.exists(candidate):
                prompts_path = candidate
            elif os.path.exists(prompts_filename):
                prompts_path = os.path.abspath(prompts_filename)

        if not prompts_path or not os.path.exists(prompts_path):
            self.cancel(f"Prompts file not found: {prompts_filename}")

        return os.path.abspath(prompts_path)

    def _load_prompts(self, prompts_filename="rag_prompts.json"):
        """
        Load RAG prompts list from the .data directory or specified path.

        :param prompts_filename: Name or path of the prompts file.
        :return: List of prompt dictionaries.
        """
        prompts_path = self._get_prompts_path(prompts_filename)
        self.log.info("Loading RAG prompts from: %s", prompts_path)
        try:
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
            if not isinstance(prompts, list) or not prompts:
                self.cancel(
                    f"Prompts file {prompts_path} does not contain a non-empty list"
                )
            return prompts
        except Exception as exc:
            self.cancel(f"Failed to parse prompts file {prompts_path}: {exc}")

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
    #  RAG workload — in-process API                                      #
    # ------------------------------------------------------------------ #

    def _rag_request(self, base_url, model, prompt_dict, max_tokens=128, req_timeout=120):
        """
        Send a single completion request to the VLLM /v1/completions endpoint
        and validate the generated response.
        """
        full_prompt = (
            f"Context: {prompt_dict['context']}\n\n"
            f"Question: {prompt_dict['question']}\n\nAnswer:"
        )
        url = f"{base_url}/v1/completions"
        payload = {
            "model": model,
            "prompt": full_prompt,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "ignore_eos": False,
        }
        t0 = time.time()
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=req_timeout,
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                text = resp.json()['choices'][0]['text']
                is_valid, matched, reason = _validate_answer(
                    text, prompt_dict.get('expected_keywords')
                )
                return {
                    "success": True,
                    "output": text,
                    "valid_answer": is_valid,
                    "matched_keywords": matched,
                    "validation_reason": reason,
                    "elapsed_time": elapsed,
                    "token_count": len(text.split()),
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

    def _rag_worker(self, base_url, model, prompts, end_ts, stats, stats_lock, req_timeout=120):
        """Background thread worker: sends RAG requests in a loop until end_ts."""
        idx = 0
        while time.time() < end_ts:
            pd = prompts[idx % len(prompts)]
            result = self._rag_request(base_url, model, pd,
                                       max_tokens=64, req_timeout=req_timeout)
            test_type = pd.get('test_type', '')
            prefix_group = pd.get('prefix_group', '')
            with stats_lock:
                stats['total'] += 1
                if result['success']:
                    stats['success'] += 1
                    stats['tokens'] += result['token_count']
                    stats['times'].append(result['elapsed_time'])
                    if result.get('valid_answer'):
                        stats['valid_answers'] += 1
                    else:
                        stats['validation_failures'] += 1

                    if test_type == 'prefix_caching' or prefix_group:
                        stats['prefix_caching_requests'] += 1
                        if prefix_group:
                            stats['prefix_latencies'].setdefault(prefix_group, []).append(result['elapsed_time'])
                    if test_type == 'chunked_prefill' or len(pd['context'].split()) > 80:
                        stats['chunked_prefill_requests'] += 1

                    if len(stats['sample_qa']) < 5 and result.get('valid_answer'):
                        stats['sample_qa'].append({
                            'question': pd['question'],
                            'answer_preview': result['output'].strip().replace('\n', ' ')[:160],
                            'matched_keywords': result.get('matched_keywords', []),
                            'test_type': test_type or 'rag',
                        })
                else:
                    stats['failed'] += 1
                    stats['errors'].append(result.get('error', ''))
            idx += 1
            time.sleep(0.1)

    def start_inference(self, base_url, prompts, num_workers=2, req_timeout=120):
        """Start RAG inference workers in background threads."""
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            model = resp.json()['data'][0]['id']
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach VLLM server at {base_url}: {exc}"
            ) from exc

        self.log.info("start_inference: model=%s  workers=%d  prompts=%d",
                      model, num_workers, len(prompts))

        stats = {
            'total': 0, 'success': 0, 'failed': 0,
            'valid_answers': 0, 'validation_failures': 0,
            'prefix_caching_requests': 0,
            'chunked_prefill_requests': 0,
            'prefix_latencies': {},
            'tokens': 0, 'times': [], 'errors': [],
            'sample_qa': [],
        }
        stats_lock = threading.Lock()
        end_ts_holder = [time.time() + 86400]

        executor = ThreadPoolExecutor(max_workers=num_workers)
        futures = [
            executor.submit(
                self._rag_worker, base_url, model, prompts,
                end_ts_holder[0], stats, stats_lock, req_timeout
            )
            for _ in range(num_workers)
        ]

        ctx = {
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
        return ctx

    def check_inference(self, ctx):
        """Log a live snapshot of inference metrics without stopping workers."""
        stats = ctx['stats']
        stats_lock = ctx['stats_lock']
        elapsed = time.time() - ctx['start_wall']
        with stats_lock:
            snapshot = dict(stats)

        throughput = snapshot['tokens'] / elapsed if elapsed > 0 else 0.0
        avg_time = (
            sum(snapshot['times']) / len(snapshot['times'])
            if snapshot['times'] else 0.0
        )
        total = snapshot['total']
        valid = snapshot['valid_answers']
        valid_rate = (valid / total * 100) if total > 0 else 0.0

        self.log.info(
            "check_inference [%.0fs elapsed] total=%d success=%d valid=%d (%.1f%%) "
            "failed=%d tokens=%d throughput=%.2f tok/s avg_req=%.3fs",
            elapsed, total, snapshot['success'], valid, valid_rate,
            snapshot['failed'], snapshot['tokens'], throughput, avg_time
        )

        if snapshot['failed'] > 0 and snapshot['errors']:
            self.log.warning("Recent errors: %s",
                             "; ".join(snapshot['errors'][-3:]))

        return {
            'total': snapshot['total'],
            'success': snapshot['success'],
            'valid_answers': snapshot['valid_answers'],
            'validation_failures': snapshot['validation_failures'],
            'prefix_caching_requests': snapshot.get('prefix_caching_requests', 0),
            'chunked_prefill_requests': snapshot.get('chunked_prefill_requests', 0),
            'prefix_latencies': snapshot.get('prefix_latencies', {}),
            'failed': snapshot['failed'],
            'tokens': snapshot['tokens'],
            'throughput_tok_s': round(throughput, 2),
            'avg_time_s': round(avg_time, 3),
            'sample_qa': snapshot.get('sample_qa', []),
        }

    def stop_inference(self, ctx, req_timeout=None):
        """Signal workers to stop and wait for them to finish."""
        ctx['end_ts_holder'][0] = 0.0

        wait = req_timeout or ctx.get('req_timeout', 120)
        for fut in as_completed(ctx['futures'], timeout=wait + 5):
            try:
                fut.result()
            except Exception as exc:
                self.log.warning("Worker raised: %s", exc)
        ctx['executor'].shutdown(wait=False)

        return self.check_inference(ctx)

    # ------------------------------------------------------------------ #
    #  Explicit start / stop lifecycle tests                             #
    # ------------------------------------------------------------------ #

    def test_start_RAG_workload(self):
        """
        Start RAG inferencing workload and AIU metrics collection in background.

        Collects AIU metrics into the default Avocado results directory (self.logdir)
        and saves background process state to ``/tmp/spyre_rag_workload_state.json``.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for RAG workload")

        use_case = self.params.get("USE_CASE", default="rag")
        container_name = self.params.get(
            "CONTAINER_NAME", default=f"spyre-{use_case}" if use_case else ""
        )
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        num_workers = int(self.params.get("WORKERS", default=2))
        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=60))
        prompts_file = self.params.get("PROMPTS_FILE", default="rag_prompts.json")
        stats_command = self.params.get("STATS_COMMAND", default="aiu-smi --csv")
        dtcompiler_export_dir = self.params.get("DTCOMPILER_EXPORT_DIR", default=None)

        self.log.info("=== test_start_RAG_workload: container=%s ===", container_name)

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
                120
            ),
            daemon=True
        )
        worker_proc.start()
        SpyreRAGWorkloadTest._active_worker_process = worker_proc

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
            "PASS: test_start_RAG_workload — Workload and metrics started successfully (PID: %d)",
            worker_proc.pid
        )

    def test_stop_RAG_workload(self):
        """
        Stop running RAG inferencing workload and AIU metrics collection.

        Reads process state from ``/tmp/spyre_rag_workload_state.json``,
        terminates workers, validates answer correctness, and preserves
        the metrics log in the Avocado results directory (self.logdir).
        """
        self.log.info("=== test_stop_RAG_workload ===")

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
            self.run_cmd_out(f"pkill -f 'aiu-smi' || true", sudo=True)

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

        prefix_reqs = stats.get('prefix_caching_requests', 0)
        chunk_reqs = stats.get('chunked_prefill_requests', 0)
        prefix_lats = stats.get('prefix_latencies', {})

        self.log.info(
            "RAG workload summary: total=%d success=%d valid_answers=%d "
            "validation_failures=%d tokens=%d throughput=%.2f tok/s avg_req=%.3fs",
            total, success, valid, validation_failures, tokens, throughput, avg_time
        )

        self.log.info("=== Feature Verification: Prefix Caching & Chunked Prefill ===")
        if prefix_lats:
            cold_times = [times[0] for times in prefix_lats.values() if times]
            warm_times = [t for times in prefix_lats.values() for t in times[1:]]
            avg_cold = sum(cold_times) / len(cold_times) if cold_times else 0.0
            avg_warm = sum(warm_times) / len(warm_times) if warm_times else 0.0
            speedup = ((avg_cold - avg_warm) / avg_cold * 100) if avg_cold > 0 and avg_warm > 0 else 0.0
            self.log.info(
                "  * Prefix Caching: %d requests across %d groups (Cold avg: %.3fs, Warm/Cached avg: %.3fs, Speedup: %.1f%%)",
                prefix_reqs, len(prefix_lats), avg_cold, avg_warm, speedup
            )
        else:
            self.log.info("  * Prefix Caching: %d requests tested", prefix_reqs)
        self.log.info("  * Chunked Prefill: %d long-context requests tested & validated", chunk_reqs)

        # Display sample validated Q&A
        sample_qa = stats.get('sample_qa', [])
        if sample_qa:
            self.log.info("=== Sample Validated Q&A Inferences ===")
            for idx, qa in enumerate(sample_qa, start=1):
                self.log.info(
                    "Sample #%d [%s]:\n  Q: %s\n  A: %s\n  Matched Keywords: %s",
                    idx, qa.get('test_type', 'rag'), qa['question'], qa['answer_preview'],
                    ", ".join(qa.get('matched_keywords', []))
                )

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
                f"RAG workload FAILED: 0 successful requests out of {total}. Errors: "
                + "; ".join(errors[:5])
            )

        if success > 0 and valid == 0:
            self.fail(
                f"RAG workload FAILED: None of the {success} generated responses passed answer validation."
            )

        validation_rate = (valid / total * 100) if total else 0
        self.log.info(
            "PASS: test_stop_RAG_workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, valid, total
        )

    # ------------------------------------------------------------------ #
    #  Integrated workload test runner                                   #
    # ------------------------------------------------------------------ #

    def run_RAG_workload(self, container_name, port, prompts,
                         duration_minutes=5, num_workers=2,
                         check_interval=30, stats_command="aiu-smi --csv",
                         dtcompiler_export_dir=None):
        """
        Run the complete RAG inferencing workload against a running Spyre container
        with answer validation.
        """
        if not HAS_REQUESTS:
            self.cancel("Python 'requests' package is required for RAG workload tests")

        base_url = f"http://127.0.0.1:{port}"
        self.log.info(
            "run_RAG_workload: container=%s  url=%s  duration=%d min  workers=%d  prompts=%d",
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
            ctx = self.start_inference(base_url, prompts=prompts, num_workers=num_workers)
        except RuntimeError as exc:
            if metrics_process is not None:
                try:
                    metrics_process.terminate()
                except Exception:
                    pass
            self.fail(str(exc))

        end_wall = time.time() + duration_minutes * 60
        self.log.info(
            "RAG workload running — will stop at %s",
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
        prefix_reqs = final.get('prefix_caching_requests', 0)
        chunk_reqs = final.get('chunked_prefill_requests', 0)
        prefix_lats = final.get('prefix_latencies', {})

        self.log.info(
            "RAG workload finished: total=%d success=%d valid_answers=%d "
            "tokens=%d throughput=%.2f tok/s avg_req=%.3fs",
            final['total'], final['success'], final.get('valid_answers', 0),
            final['tokens'], final['throughput_tok_s'], final['avg_time_s']
        )

        self.log.info("=== Feature Verification: Prefix Caching & Chunked Prefill ===")
        if prefix_lats:
            cold_times = [times[0] for times in prefix_lats.values() if times]
            warm_times = [t for times in prefix_lats.values() for t in times[1:]]
            avg_cold = sum(cold_times) / len(cold_times) if cold_times else 0.0
            avg_warm = sum(warm_times) / len(warm_times) if warm_times else 0.0
            speedup = ((avg_cold - avg_warm) / avg_cold * 100) if avg_cold > 0 and avg_warm > 0 else 0.0
            self.log.info(
                "  * Prefix Caching: %d requests across %d groups (Cold avg: %.3fs, Warm/Cached avg: %.3fs, Speedup: %.1f%%)",
                prefix_reqs, len(prefix_lats), avg_cold, avg_warm, speedup
            )
        else:
            self.log.info("  * Prefix Caching: %d requests tested", prefix_reqs)
        self.log.info("  * Chunked Prefill: %d long-context requests tested & validated", chunk_reqs)

        # Display sample validated Q&A
        sample_qa = final.get('sample_qa', [])
        if sample_qa:
            self.log.info("=== Sample Validated Q&A Inferences ===")
            for idx, qa in enumerate(sample_qa, start=1):
                self.log.info(
                    "Sample #%d [%s]:\n  Q: %s\n  A: %s\n  Matched Keywords: %s",
                    idx, qa.get('test_type', 'rag'), qa['question'], qa['answer_preview'],
                    ", ".join(qa.get('matched_keywords', []))
                )

        if final['success'] == 0:
            self.fail(
                f"RAG workload FAILED: 0 successful requests out of "
                f"{final['total']} total. Errors: "
                + "; ".join(ctx['stats']['errors'][:5])
            )

        if final.get('valid_answers', 0) == 0 and final['success'] > 0:
            self.fail(
                f"RAG workload FAILED: 0 responses passed answer validation out of {final['success']} successful requests."
            )

        validation_rate = (
            final.get('valid_answers', 0) / final['total'] * 100
            if final['total'] else 0
        )
        self.log.info(
            "PASS: RAG workload — validation rate %.1f%% (%d valid / %d total requests)",
            validation_rate, final.get('valid_answers', 0), final['total']
        )

    def test_run_workload(self):
        """
        Run an inferencing workload against the deployed Spyre container
        and collect AIU metrics into the Avocado results directory.

        Reads ``USE_CASE`` and ``CONTAINER_NAME`` from YAML.
        """
        use_case = self.params.get("USE_CASE", default="rag")
        container_name = self.params.get(
            "CONTAINER_NAME", default=f"spyre-{use_case}" if use_case else ""
        )
        if not container_name:
            self.cancel("CONTAINER_NAME parameter not specified in YAML")

        duration_minutes = int(self.params.get("WORKLOAD_MINS", default=5))
        num_workers = int(self.params.get("WORKERS", default=2))
        check_interval = int(self.params.get("CHECK_INTERVAL", default=30))
        prompts_file = self.params.get("PROMPTS_FILE", default="rag_prompts.json")
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

        if use_case == "rag":
            self.run_RAG_workload(
                container_name=container_name,
                port=port,
                prompts=prompts,
                duration_minutes=duration_minutes,
                num_workers=num_workers,
                check_interval=check_interval,
                stats_command=stats_command,
                dtcompiler_export_dir=dtcompiler_export_dir,
            )
        else:
            self.cancel(f"No workload implementation for use case '{use_case}'. Supported: rag")
