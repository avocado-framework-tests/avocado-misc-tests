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

"""
Spyre Stack Test Suite

This test suite validates various Spyre AI accelerator use cases including:
- RAG (Retrieval-Augmented Generation)
- Entity Extraction
- RAG Embedding
- Reranker/Scoring

All configurations are driven by YAML parameter files.
"""

import os
import time
from avocado import Test
from avocado.utils import dmesg, process
from avocado.utils.podman import (
    Podman,
    PodmanException,
    install_huggingface_cli,
    download_model_from_hf
)
from avocado.utils.software_manager.manager import SoftwareManager


class SpyreStackTest(Test):
    """
    Generic test suite for Spyre AI accelerator stack validation.

    All test parameters are loaded from YAML configuration files,
    making it easy to test different models, batch sizes, and configurations.
    """

    is_fail = 0
    container_ids = []
    podman = None
    dmesg_log_file = None
    initial_dmesg = None

    DMESG_ERROR_PATTERNS = [
        'WARNING:', 'BUG:', 'Oops:', 'Call Trace:',
        'kernel panic', 'segfault', 'Hardware Error',
        'vfio.*error', 'aiu.*error'
    ]

    def run_cmd(self, cmd):
        """Execute a command and track failures."""
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.log.info("%s command failed", cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, ignore_status=True,
            sudo=True).decode("utf-8").strip()

    @staticmethod
    def spyre_exists():
        """Check if VFIO Spyre devices exist."""
        if os.path.exists('/dev/vfio'):
            files = os.listdir('/dev/vfio')
            for file in files:
                if file.isdigit():
                    return True
        return False

    def wait_for_vllm_startup(self, container_id, timeout=300, check_interval=10):
        """
        Wait for VLLM to start by checking container logs for startup message.

        :param container_id: Container ID to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :return: True if startup successful, False otherwise
        """
        elapsed = 0

        while elapsed < timeout:
            try:
                _, logs, _ = self.podman.logs(container_id, tail=200)
                log_content = logs.decode()

                if "Application startup complete." in log_content:
                    self.log.info("VLLM started successfully for container %s", container_id)
                    return True

                if "VFIO" in log_content and "fail" in log_content.lower():
                    self.log.error("VFIO device access failure detected in logs")
                    return False

                self.log.info("Waiting for VLLM startup... (%d/%d seconds)", elapsed, timeout)
                time.sleep(check_interval)
                elapsed += check_interval

            except PodmanException as ex:
                self.log.warning("Failed to get container logs: %s", ex)
                time.sleep(check_interval)
                elapsed += check_interval

        self.log.error("Timeout waiting for VLLM startup")
        return False

    def setUp(self):
        """Set up test environment and initialize Podman."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")

        self.log.info("Checking SELinux status")
        try:
            selinux_status = self.run_cmd_out("getenforce")
            self.log.info("SELinux status: %s", selinux_status)

            if selinux_status.strip().lower() == "enforcing":
                self.log.info("SELinux is Enforcing, disabling it for container operations")
                result = process.run("setenforce 0", shell=True, sudo=True, ignore_status=True)
                if result.exit_status == 0:
                    self.log.info("SELinux set to Permissive mode")
                else:
                    self.log.warning("Failed to set SELinux to Permissive mode")
        except Exception as ex:
            self.log.warning("Could not check/modify SELinux status: %s", ex)

        smm = SoftwareManager()
        for package in ['podman']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(f"Fail to install {package} required for this test.")

        if not self.spyre_exists():
            self.cancel("No VFIO Spyre devices found. Please check Spyre configuration.")

        try:
            self.podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        self.api_key = self.params.get("API_KEY", default="")
        container_registry = self.params.get("CONTAINER_REGISTRY", default="")

        if self.api_key and container_registry:
            try:
                self.podman.login(registry=container_registry, api_key=self.api_key)
                self.log.info("Successfully logged in to registry: %s", container_registry)
            except PodmanException as ex:
                self.log.warning("Failed to login to registry: %s", ex)

        download_model = self.params.get("DOWNLOAD_MODEL", default="false")
        if download_model.lower() in ("true", "1", "yes"):
            self.log.info("=" * 80)
            self.log.info("Model Download Enabled")
            self.log.info("=" * 80)

            if not install_huggingface_cli():
                self.cancel("Failed to install Hugging Face CLI")

            hf_model_id = self.params.get("HF_MODEL_ID", default="")
            host_models_dir = self.params.get("HOST_MODELS_DIR", default="/opt/ibm/spyre/models")
            model_name = self.params.get("MODEL_NAME", default="")

            if not hf_model_id:
                self.log.warning("HF_MODEL_ID not specified, skipping model download")
            elif not model_name:
                self.log.warning("MODEL_NAME not specified, skipping model download")
            else:
                self.log.info("Downloading model: %s", hf_model_id)
                if not download_model_from_hf(hf_model_id, host_models_dir, model_name):
                    self.log.warning("Model download failed, but continuing with test")
                else:
                    self.log.info("Model ready at: %s/%s", host_models_dir, model_name)

        self.log.info("Capturing initial dmesg state for kernel issue tracking")
        try:
            self.dmesg_log_file = dmesg.collect_dmesg()
            self.initial_dmesg = open(self.dmesg_log_file, 'r').read()
            self.log.info("Initial dmesg captured: %s", self.dmesg_log_file)
        except Exception as ex:
            self.log.warning("Failed to capture initial dmesg: %s", ex)
            self.dmesg_log_file = None
            self.initial_dmesg = None

    def _run_container_test(self, test_name=None):
        """
        Internal method to run a Spyre container with parameters from YAML.

        All configuration is loaded from the YAML file, including:
        - Container image and tag
        - AIU PCIe IDs
        - Model paths
        - Batch sizes and context lengths
        - Memory and resource limits
        - VLLM-specific parameters

        :param test_name: Optional test name override
        """
        if test_name is None:
            test_name = self.params.get("TEST_NAME", default="Spyre Container Test")

        self.log.info("=" * 80)
        self.log.info("Starting test: %s", test_name)
        self.log.info("=" * 80)

        container_url = self.params.get("CONTAINER_URL", default="")
        container_tag = self.params.get("CONTAINER_TAG", default="")
        if not container_url or not container_tag:
            self.cancel("CONTAINER_URL and CONTAINER_TAG must be specified in YAML")

        image = f"{container_url}:{container_tag}"

        aiu_pcie_ids = self.params.get("AIU_PCIE_IDS", default="")
        if not aiu_pcie_ids:
            self.cancel("AIU_PCIE_IDS must be specified in YAML")

        host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        if not host_models_dir or not vllm_model_path:
            self.cancel("HOST_MODELS_DIR and VLLM_MODEL_PATH must be specified in YAML")

        aiu_world_size = self.params.get("AIU_WORLD_SIZE", default=1)
        max_model_len = self.params.get("MAX_MODEL_LEN", default=2048)
        max_batch_size = self.params.get("MAX_BATCH_SIZE", default=1)

        memory = self.params.get("MEMORY", default="200G")
        shm_size = self.params.get("SHM_SIZE", default="")  # Optional, empty string if not needed
        device = self.params.get("DEVICE", default="/dev/vfio")
        privileged = self.params.get("PRIVILEGED", default="true")
        pids_limit = self.params.get("PIDS_LIMIT", default="0")
        userns = self.params.get("USERNS", default="keep-id")
        group_add = self.params.get("GROUP_ADD", default="keep-groups")
        port_mapping = self.params.get("PORT_MAPPING", default="127.0.0.1::8000")

        vllm_spyre_use_cb = self.params.get("VLLM_SPYRE_USE_CB", default="1")
        vllm_dt_chunk_len = self.params.get("VLLM_DT_CHUNK_LEN", default=None)
        vllm_spyre_use_chunked_prefill = self.params.get("VLLM_SPYRE_USE_CHUNKED_PREFILL", default=None)

        enable_prefix_caching_str = self.params.get("ENABLE_PREFIX_CACHING", default="true")
        enable_prefix_caching = enable_prefix_caching_str.lower() in ("true", "1", "yes")

        additional_vllm_args_str = self.params.get("ADDITIONAL_VLLM_ARGS", default="")
        additional_vllm_args = None
        if additional_vllm_args_str:
            additional_vllm_args = [arg.strip() for arg in additional_vllm_args_str.split(",") if arg.strip()]

        startup_timeout = self.params.get("STARTUP_TIMEOUT", default=600)

        self.log.info("Configuration:")
        self.log.info("  Image: %s", image)
        self.log.info("  AIU IDs: %s", aiu_pcie_ids)
        self.log.info("  Model Path: %s", vllm_model_path)
        self.log.info("  World Size: %s", aiu_world_size)
        self.log.info("  Max Model Length: %s", max_model_len)
        self.log.info("  Max Batch Size: %s", max_batch_size)
        self.log.info("  Memory: %s", memory)
        if shm_size:
            self.log.info("  Shared Memory: %s", shm_size)
        self.log.info("  Enable Prefix Caching: %s", enable_prefix_caching)
        if vllm_dt_chunk_len is not None:
            self.log.info("  DT Chunk Length: %s", vllm_dt_chunk_len)
        if vllm_spyre_use_chunked_prefill is not None:
            self.log.info("  Use Chunked Prefill: %s", vllm_spyre_use_chunked_prefill)

        container_name = f"spyre-{test_name.lower().replace(' ', '-').replace('_', '-')}"

        try:
            run_params = {
                'image': image,
                'aiu_ids': aiu_pcie_ids,
                'host_models_dir': host_models_dir,
                'vllm_model_path': vllm_model_path,
                'aiu_world_size': aiu_world_size,
                'max_model_len': max_model_len,
                'max_batch_size': max_batch_size,
                'memory': memory,
                'device': device,
                'privileged': privileged,
                'pids_limit': pids_limit,
                'userns': userns,
                'group_add': group_add,
                'port_mapping': port_mapping,
                'vllm_spyre_use_cb': vllm_spyre_use_cb,
                'vllm_dt_chunk_len': vllm_dt_chunk_len,
                'vllm_spyre_use_chunked_prefill': vllm_spyre_use_chunked_prefill,
                'enable_prefix_caching': enable_prefix_caching,
                'additional_vllm_args': additional_vllm_args,
                'container_name': container_name
            }

            if shm_size:
                run_params['shm_size'] = shm_size

            returncode, stdout, stderr = self.podman.run_vllm_container(**run_params)

            container_id = stdout.decode().strip()
            self.log.info("Container created successfully: %s", container_id)
            self.container_ids.append(container_id)

            self.log.info("Waiting for VLLM to start (timeout: %d seconds)...", startup_timeout)
            startup_success = self.wait_for_vllm_startup(container_id, timeout=startup_timeout)

            try:
                _, logs, _ = self.podman.logs(container_id, tail=200)
                log_content = logs.decode()
                self.log.info("Container logs:\n%s", log_content)
            except Exception as ex:
                self.log.warning("Failed to retrieve logs: %s", ex)

            if not startup_success:
                self.fail(f"Container failed to start successfully for test: {test_name}")

            self.log.info("=" * 80)
            self.log.info("✓ Test PASSED: %s", test_name)
            self.log.info("=" * 80)

        except PodmanException as ex:
            self.fail(f"Failed to run container for {test_name}: {ex}")

    def test_rag_granite_8b(self):
        """
        Test RAG use case with Granite 3.3-8B Instruct model.

        Configuration loaded from rag_granite_8b.yaml:
        - Model: granite-3.3-8b-instruct
        - Batch size: 32
        - Max context: 32768 tokens
        - Cards per container: 4
        """
        self._run_container_test("RAG_Granite_8B")

    def test_entity_extraction_granite_8b(self):
        """
        Test Entity Extraction use case with Granite 3.3-8B Instruct model.

        Configuration loaded from entity_extraction_granite_8b.yaml:
        - Model: granite-3.3-8b-instruct
        - Batch size: 16
        - Max context: 3072 tokens
        - Cards per container: 1
        - Uses chunked prefill
        """
        self._run_container_test("Entity_Extraction_Granite_8B")

    def test_rag_embedding_granite_125m(self):
        """
        Test RAG Embedding use case with Granite Embedding 125M model.

        Configuration loaded from rag_embedding_granite_125m.yaml or specific embedding YAML:
        - Model: granite-embedding-125m-english
        - Various batch sizes and prompt lengths
        - Cards per container: 1
        """
        self._run_container_test("RAG_Embedding")

    def test_reranker_bge_m3(self):
        """
        Test Reranker/Scoring use case with BGE Reranker v2-m3 model.

        Configuration loaded from reranker_bge_m3.yaml:
        - Model: bge-reranker-v2-m3
        - Batch size: 4
        - Max context: 8192 tokens
        - Cards per container: 1
        """
        self._run_container_test("Reranker_BGE_M3")

    def test_spyre_container(self):
        """
        Generic test method that runs a Spyre container with parameters from YAML.

        This is a flexible test that can be used with any YAML configuration.
        Use the specific test methods above for standard use cases, or use this
        method with custom YAML files for other configurations.
        """
        self._run_container_test()

    def tearDown(self):
        """Clean up: stop and remove all containers."""
        if self.container_ids:
            self.log.info("=" * 80)
            self.log.info("Cleaning up %d containers", len(self.container_ids))
            self.log.info("=" * 80)

            for container_id in self.container_ids:
                try:
                    self.log.info("Final logs for container %s:", container_id)
                    try:
                        _, logs, _ = self.podman.logs(container_id, tail=100)
                        self.log.info(logs.decode())
                    except Exception as log_ex:
                        self.log.warning("Failed to retrieve logs: %s", log_ex)

                    self.log.info("Stopping container: %s", container_id)
                    self.podman.stop(container_id)
                    self.log.info("Removing container: %s", container_id)
                    self.podman.remove(container_id, force=True)
                    self.log.info("Container %s cleaned up successfully", container_id)

                except PodmanException as ex:
                    self.log.warning("Failed to cleanup container %s: %s", container_id, ex)
                except Exception as ex:
                    self.log.warning("Unexpected error cleaning up container %s: %s", container_id, ex)

            self.log.info("Cleanup completed")

        self.log.info("=" * 80)
        self.log.info("Checking dmesg for kernel warnings and errors")
        self.log.info("=" * 80)

        try:
            final_dmesg_file = dmesg.collect_dmesg()
            final_dmesg = open(final_dmesg_file, 'r').read()

            if self.initial_dmesg:
                new_messages = self._get_new_dmesg_messages(self.initial_dmesg, final_dmesg)

                if new_messages:
                    self.log.info("New dmesg messages detected (%d lines)", len(new_messages.split('\n')))

                    errors_found = dmesg.collect_errors_dmesg(self.DMESG_ERROR_PATTERNS)

                    if errors_found:
                        self.log.warning("Kernel issues detected:")
                        for error in errors_found[:10]:  # Show first 10 errors
                            self.log.warning("  %s", error)

                        if len(errors_found) > 10:
                            self.log.warning("  ... and %d more issues", len(errors_found) - 10)

                        dmesg_output = os.path.join(self.logdir, 'dmesg_errors.log')
                        with open(dmesg_output, 'w') as f:
                            f.write('\n'.join(errors_found))
                        self.log.warning("Full dmesg errors saved to: %s", dmesg_output)
                    else:
                        self.log.info("✓ No critical kernel issues detected")
                else:
                    self.log.info("✓ No new dmesg messages")
            else:
                self.log.warning("Initial dmesg not captured, checking current state only")

                errors_found = dmesg.collect_errors_dmesg(self.DMESG_ERROR_PATTERNS)

                if errors_found:
                    self.log.warning("Kernel issues found in dmesg (%d)", len(errors_found))
                    for error in errors_found[:5]:
                        self.log.warning("  %s", error)
                else:
                    self.log.info("✓ No critical kernel issues detected")

        except Exception as ex:
            self.log.warning("Failed to check dmesg for issues: %s", ex)

        self.log.info("=" * 80)

    def _get_new_dmesg_messages(self, before, after):
        """
        Extract new dmesg messages by comparing before and after states.

        :param before: dmesg content before test
        :param after: dmesg content after test
        :return: New messages as string
        """
        before_lines = before.split('\n')
        after_lines = after.split('\n')

        if len(after_lines) > len(before_lines):
            new_lines = after_lines[len(before_lines):]
            return '\n'.join(new_lines)

        return ""
