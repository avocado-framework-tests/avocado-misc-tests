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
Spyre Stack Quadlet Test Suite

This test suite validates Spyre AI accelerator use cases using Podman Quadlet
(systemd container management) including:
- Entity Extraction
- Reranker
- Embedding
- RAG (Retrieval-Augmented Generation)

Key Features:
1. Generates quadlet .container files for each use case
2. Uses systemd to manage container lifecycle
3. Monitors journalctl logs for VLLM startup
4. Supports parallel startup of EE, Rerank, and Embedding
5. Sequential shutdown and RAG startup with all PCIe IDs
6. Runs as senuser with systemd --user mode
"""

import os
import time
import threading
from avocado import Test
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class SpyreQuadletTest(Test):
    """
    Test suite for Spyre AI accelerator stack validation using Podman Quadlet.
    
    All test parameters are loaded from YAML configuration files.
    Tests run as senuser using systemd --user services.
    """

    is_fail = 0
    test_username = "senuser"
    quadlet_dir = None
    active_services = []
    
    # Use case configurations
    USECASES = {
        "entity_extraction": {
            "container_name": "spyre-entity-extract",
            "service_name": "spyre-entity-extract",
            "slice": "spyre-ee.slice",
            "description": "Spyre Entity Extraction"
        },
        "embedding": {
            "container_name": "spyre-embedding",
            "service_name": "spyre-embedding",
            "slice": "spyre-embedding.slice",
            "description": "Spyre Embedding"
        },
        "reranker": {
            "container_name": "spyre-reranker",
            "service_name": "spyre-reranker",
            "slice": "spyre-reranker.slice",
            "description": "Spyre Reranker"
        },
        "rag": {
            "container_name": "spyre-rag",
            "service_name": "spyre-rag",
            "slice": "spyre-rag.slice",
            "description": "Spyre RAG"
        }
    }

    def run_cmd(self, cmd, user=None):
        """Execute a command and track failures."""
        if user and user != "root":
            escaped_cmd = cmd.replace("'", "'\"'\"'")
            cmd = f"su - {user} -c '{escaped_cmd}'"
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.log.info("%s command failed", cmd)
        return

    @staticmethod
    def run_cmd_out(cmd, user=None):
        """Execute a command and return output."""
        if user and user != "root":
            escaped_cmd = cmd.replace("'", "'\"'\"'")
            cmd = f"su - {user} -c '{escaped_cmd}'"
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

    def setUp(self):
        """
        Initial setup for Spyre quadlet tests.
        
        This includes:
        - Platform validation
        - SELinux configuration
        - Package installation
        - Spyre device validation
        - Models directory setup with proper permissions
        - Enable linger for senuser
        - Configure persistent journald logging
        - Quadlet directory setup
        - Model verification
        """
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")

        # Configure SELinux
        self.log.info("Checking SELinux status")
        try:
            selinux_status = self.run_cmd_out("getenforce")
            self.log.info("SELinux status: %s", selinux_status)

            if selinux_status.strip().lower() == "enforcing":
                self.log.info("SELinux is Enforcing, disabling it for container operations")
                result = process.run("setenforce 0", shell=True, sudo=True, ignore_status=True)
                if result.exit_status == 0:
                    self.log.info("✓ SELinux set to Permissive mode")
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

        # Get models directory from YAML
        host_models_dir = self.params.get("HOST_MODELS_DIR", default="/opt/ibm/spyre/models")
        
        # Setup models directory with proper permissions
        self.log.info("Setting up models directory: %s", host_models_dir)
        models_cmd = f"install -d -m 0775 -o root -g sentient {host_models_dir}"
        result = process.run(models_cmd, shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.log.warning("Failed to create models directory with sentient group, trying without group")
            # Fallback: create directory without specific group
            fallback_cmd = f"mkdir -p {host_models_dir} && chmod 0775 {host_models_dir}"
            process.run(fallback_cmd, shell=True, sudo=True, ignore_status=False)
        
        # Enable linger for senuser (allows user services to run without login)
        self.log.info("Enabling linger for %s", self.test_username)
        linger_cmd = f"loginctl enable-linger {self.test_username}"
        process.run(linger_cmd, shell=True, sudo=True, ignore_status=True)
        
        # Configure persistent journald logging
        self.log.info("Configuring persistent journald logging")
        journal_dir_cmd = "install -d -m 2755 -o root -g systemd-journal /var/log/journal"
        process.run(journal_dir_cmd, shell=True, sudo=True, ignore_status=True)
        
        # Update journald configuration for persistent storage
        journald_config_cmd = "sed -ri 's/^#?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf"
        process.run(journald_config_cmd, shell=True, sudo=True, ignore_status=True)
        
        # Restart journald to apply changes
        self.log.info("Restarting systemd-journald")
        restart_journald_cmd = "systemctl restart systemd-journald"
        process.run(restart_journald_cmd, shell=True, sudo=True, ignore_status=True)
        
        # Create systemd user service directory
        self.log.info("Setting up systemd user service directory")
        systemd_user_dir_cmd = "install -d -m 0755 -o root -g root /etc/systemd/system/user@.service.d"
        process.run(systemd_user_dir_cmd, shell=True, sudo=True, ignore_status=True)

        # Setup quadlet directory for senuser
        self.quadlet_dir = f"/home/{self.test_username}/.config/containers/systemd"
        self.log.info("Setting up quadlet directory: %s", self.quadlet_dir)
        
        # Create directory as senuser
        mkdir_cmd = f"mkdir -p {self.quadlet_dir}"
        self.run_cmd(mkdir_cmd, user=self.test_username)
        
        self.log.info("Quadlet directory ready: %s", self.quadlet_dir)
        
        # Verify models are downloaded
        self.log.info("Verifying models in %s", host_models_dir)
        required_models = []
        
        # Check which models are required based on test parameters
        ee_model = self.params.get("EE_MODEL_PATH", default="")
        if ee_model:
            model_name = os.path.basename(ee_model)
            required_models.append(model_name)
        
        emb_model = self.params.get("EMB_MODEL_PATH", default="")
        if emb_model:
            model_name = os.path.basename(emb_model)
            if model_name not in required_models:
                required_models.append(model_name)
        
        rr_model = self.params.get("RR_MODEL_PATH", default="")
        if rr_model:
            model_name = os.path.basename(rr_model)
            if model_name not in required_models:
                required_models.append(model_name)
        
        rag_model = self.params.get("RAG_MODEL_PATH", default="")
        if rag_model:
            model_name = os.path.basename(rag_model)
            if model_name not in required_models:
                required_models.append(model_name)
        
        # Check if models exist
        missing_models = []
        for model_name in required_models:
            model_path = os.path.join(host_models_dir, model_name)
            if not os.path.exists(model_path):
                missing_models.append(model_name)
                self.log.warning("Model not found: %s", model_path)
            else:
                self.log.info("✓ Model found: %s", model_name)
        
        if missing_models:
            self.log.warning("Missing models: %s", ", ".join(missing_models))
            self.log.warning("Tests may fail if models are not available")
            self.log.warning("Please download models before running tests")
        else:
            self.log.info("✓ All required models are available")

    def generate_quadlet_file(self, usecase, image, aiu_pcie_ids, memory, 
                             model_path, tensor_parallel, max_model_len,
                             max_num_seqs, max_num_batched_tokens, 
                             host_models_dir="/opt/ibm/spyre/models",
                             shm_size=None):
        """
        Generate a quadlet .container file for a specific use case.
        
        :param usecase: Use case name (entity_extraction, embedding, reranker, rag)
        :param image: Container image URL with tag
        :param aiu_pcie_ids: PCIe IDs for AIU devices (space-separated)
        :param memory: Memory limit (e.g., "200G")
        :param model_path: Path to model inside container
        :param tensor_parallel: Tensor parallel size
        :param max_model_len: Maximum model length
        :param max_num_seqs: Maximum number of sequences
        :param max_num_batched_tokens: Maximum batched tokens
        :param host_models_dir: Host directory for models
        :param shm_size: Shared memory size (optional, e.g., "2G")
        :return: Path to generated quadlet file
        """
        config = self.USECASES.get(usecase)
        if not config:
            self.fail(f"Unknown use case: {usecase}")
        
        quadlet_filename = f"{config['service_name']}.container"
        quadlet_path = os.path.join(self.quadlet_dir, quadlet_filename)
        
        self.log.info("Generating quadlet file: %s", quadlet_path)
        
        # Build quadlet content
        content = f"""[Unit]
Description={config['description']}
After=network-online.target

[Container]
ContainerName={config['container_name']}
PublishPort=127.0.0.1::8000
Image={image}

Environment=AIU_PCIE_IDS="{aiu_pcie_ids}"

PodmanArgs=--device=/dev/vfio
PodmanArgs=--userns=keep-id
PodmanArgs=--group-add=keep-groups
PodmanArgs=--pids-limit=0
PodmanArgs=--memory={memory}
PodmanArgs=--privileged=true
"""

        # Add shm-size if specified (for RAG)
        if shm_size:
            content += f"PodmanArgs=--shm-size={shm_size}\n"
        
        content += f"""
Volume={host_models_dir}:/models

Exec=--model {model_path} -tp {tensor_parallel} --max-model-len {max_model_len} --max-num-seqs {max_num_seqs} --max-num-batched-tokens {max_num_batched_tokens}

[Service]
Slice={config['slice']}
Restart=always

[Install]
WantedBy=default.target
"""
        
        # Write quadlet file as senuser
        temp_file = f"/tmp/{quadlet_filename}"
        with open(temp_file, 'w') as f:
            f.write(content)
        
        # Move to quadlet directory with proper ownership
        mv_cmd = f"mv {temp_file} {quadlet_path}"
        self.run_cmd(mv_cmd, user=self.test_username)
        
        # Set proper permissions
        chmod_cmd = f"chmod 644 {quadlet_path}"
        self.run_cmd(chmod_cmd, user=self.test_username)
        
        self.log.info("✓ Quadlet file generated: %s", quadlet_path)
        return quadlet_path

    def systemd_daemon_reload(self):
        """Reload systemd user daemon to pick up new quadlet files."""
        self.log.info("Reloading systemd user daemon...")
        reload_cmd = "systemctl --user daemon-reload"
        self.run_cmd(reload_cmd, user=self.test_username)
        self.log.info("✓ Systemd daemon reloaded")

    def systemd_start_service(self, service_name):
        """
        Start a systemd user service.
        
        :param service_name: Service name (without .service extension)
        :return: True if started successfully, False otherwise
        """
        self.log.info("Starting service: %s", service_name)
        start_cmd = f"systemctl --user start {service_name}.service"
        result = process.run(
            f"su - {self.test_username} -c '{start_cmd}'",
            shell=True, sudo=True, ignore_status=True
        )
        
        if result.exit_status == 0:
            self.log.info("✓ Service started: %s", service_name)
            self.active_services.append(service_name)
            return True
        else:
            self.log.error("✗ Failed to start service: %s", service_name)
            self.log.error("Error: %s", result.stderr_text)
            return False

    def systemd_stop_service(self, service_name):
        """
        Stop a systemd user service.
        
        :param service_name: Service name (without .service extension)
        :return: True if stopped successfully, False otherwise
        """
        self.log.info("Stopping service: %s", service_name)
        stop_cmd = f"systemctl --user stop {service_name}.service"
        result = process.run(
            f"su - {self.test_username} -c '{stop_cmd}'",
            shell=True, sudo=True, ignore_status=True
        )
        
        if result.exit_status == 0:
            self.log.info("✓ Service stopped: %s", service_name)
            if service_name in self.active_services:
                self.active_services.remove(service_name)
            return True
        else:
            self.log.error("✗ Failed to stop service: %s", service_name)
            return False

    def collect_journalctl_logs(self, service_name, output_file=None):
        """
        Collect journalctl logs for a service.
        
        :param service_name: Service name (without .service extension)
        :param output_file: Optional output file path
        :return: Log content as string
        """
        if not output_file:
            output_file = f"/tmp/{service_name}.log"
        
        self.log.info("Collecting journalctl logs for %s to %s", service_name, output_file)
        
        log_cmd = f"journalctl --user -u {service_name}.service > {output_file}"
        self.run_cmd(log_cmd, user=self.test_username)
        
        # Read and return log content
        try:
            with open(output_file, 'r') as f:
                log_content = f.read()
            self.log.info("✓ Logs collected: %s (%d bytes)", output_file, len(log_content))
            return log_content
        except Exception as ex:
            self.log.warning("Failed to read log file: %s", ex)
            return ""

    def wait_for_vllm_startup_journalctl(self, service_name, timeout=600, check_interval=10):
        """
        Wait for VLLM to start by monitoring journalctl logs.
        
        :param service_name: Service name to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :return: True if startup successful, False otherwise
        """
        self.log.info("Monitoring journalctl for VLLM startup: %s", service_name)
        elapsed = 0
        
        while elapsed < timeout:
            try:
                # Get recent logs
                log_cmd = f"journalctl --user -u {service_name}.service -n 100 --no-pager"
                log_output = self.run_cmd_out(log_cmd, user=self.test_username)
                
                # Display logs to stdout
                if log_output:
                    self.log.info("Recent logs from %s:", service_name)
                    for line in log_output.split('\n')[-10:]:  # Show last 10 lines
                        self.log.info("  %s", line)
                
                # Check for BACKTRACE (indicates crash)
                if "BACKTRACE" in log_output:
                    self.log.error("BACKTRACE detected in journalctl logs - service crashed")
                    return False
                
                # Check for successful startup
                if "Application startup complete." in log_output:
                    self.log.info("✓ VLLM started successfully for %s", service_name)
                    return True
                
                # Check for VFIO errors
                if "VFIO" in log_output and "fail" in log_output.lower():
                    self.log.error("VFIO device access failure detected")
                    return False
                
                self.log.info("Waiting for VLLM startup... (%d/%d seconds)", elapsed, timeout)
                time.sleep(check_interval)
                elapsed += check_interval
                
            except Exception as ex:
                self.log.warning("Error checking journalctl: %s", ex)
                time.sleep(check_interval)
                elapsed += check_interval
        
        self.log.error("Timeout waiting for VLLM startup")
        return False

    def test_entity_extraction_quadlet(self):
        """Test Entity Extraction use case using quadlet."""
        self.log.info("=" * 80)
        self.log.info("Test: Entity Extraction (Quadlet)")
        self.log.info("=" * 80)
        
        # Get parameters from YAML
        image = self.params.get("IMAGE", default="")
        all_pcie_ids = self.params.get("PCIE_IDS", default="0301:50:00.0")
        pcie_id_list = all_pcie_ids.split()
        aiu_pcie_ids = pcie_id_list[0] if pcie_id_list else "0301:50:00.0"
        memory = self.params.get("EE_MEMORY", default="200G")
        model_path = self.params.get("EE_MODEL_PATH", default="/models/granite-3.3-8b-instruct")
        tensor_parallel = self.params.get("EE_TENSOR_PARALLEL", default=1)
        max_model_len = self.params.get("EE_MAX_MODEL_LEN", default=3072)
        max_num_seqs = self.params.get("EE_MAX_NUM_SEQS", default=16)
        max_num_batched_tokens = self.params.get("EE_MAX_NUM_BATCHED_TOKENS", default=512)
        
        # Generate quadlet file
        self.generate_quadlet_file(
            usecase="entity_extraction",
            image=image,
            aiu_pcie_ids=aiu_pcie_ids,
            memory=memory,
            model_path=model_path,
            tensor_parallel=1,
            max_model_len=3072,
            max_num_seqs=16,
            max_num_batched_tokens=512
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start service
        service_name = self.USECASES["entity_extraction"]["service_name"]
        if not self.systemd_start_service(service_name):
            self.fail("Failed to start Entity Extraction service")
        
        # Wait for VLLM startup
        if not self.wait_for_vllm_startup_journalctl(service_name):
            self.fail("VLLM failed to start for Entity Extraction")
        
        # Collect logs
        self.collect_journalctl_logs(service_name, f"/tmp/{service_name}.log")
        
        # Stop service
        self.systemd_stop_service(service_name)
        
        self.log.info("✓ Entity Extraction test completed successfully")

    def test_embedding_quadlet(self):
        """Test Embedding use case using quadlet."""
        self.log.info("=" * 80)
        self.log.info("Test: Embedding (Quadlet)")
        self.log.info("=" * 80)
        
        # Get parameters from YAML
        image = self.params.get("IMAGE", default="")
        all_pcie_ids = self.params.get("PCIE_IDS", default="0301:50:00.0")
        pcie_id_list = all_pcie_ids.split()
        aiu_pcie_ids = pcie_id_list[0] if pcie_id_list else "0301:50:00.0"
        memory = self.params.get("EMB_MEMORY", default="1500G")
        model_path = self.params.get("EMB_MODEL_PATH", default="/models/granite-embedding-125m-english")
        tensor_parallel = self.params.get("EMB_TENSOR_PARALLEL", default=1)
        max_model_len = self.params.get("EMB_MAX_MODEL_LEN", default=512)
        max_num_seqs = self.params.get("EMB_MAX_NUM_SEQS", default=4)
        max_num_batched_tokens = self.params.get("EMB_MAX_NUM_BATCHED_TOKENS", default=512)
        
        # Generate quadlet file
        self.generate_quadlet_file(
            usecase="embedding",
            image=image,
            aiu_pcie_ids=aiu_pcie_ids,
            memory=memory,
            model_path=model_path,
            tensor_parallel=1,
            max_model_len=512,
            max_num_seqs=4,
            max_num_batched_tokens=512
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start service
        service_name = self.USECASES["embedding"]["service_name"]
        if not self.systemd_start_service(service_name):
            self.fail("Failed to start Embedding service")
        
        # Wait for VLLM startup
        if not self.wait_for_vllm_startup_journalctl(service_name):
            self.fail("VLLM failed to start for Embedding")
        
        # Collect logs
        self.collect_journalctl_logs(service_name, f"/tmp/{service_name}.log")
        
        # Stop service
        self.systemd_stop_service(service_name)
        
        self.log.info("✓ Embedding test completed successfully")

    def test_reranker_quadlet(self):
        """Test Reranker use case using quadlet."""
        self.log.info("=" * 80)
        self.log.info("Test: Reranker (Quadlet)")
        self.log.info("=" * 80)
        
        # Get parameters from YAML
        image = self.params.get("IMAGE", default="")
        all_pcie_ids = self.params.get("PCIE_IDS", default="0301:50:00.0")
        pcie_id_list = all_pcie_ids.split()
        aiu_pcie_ids = pcie_id_list[0] if pcie_id_list else "0301:50:00.0"
        memory = self.params.get("RR_MEMORY", default="1500G")
        model_path = self.params.get("RR_MODEL_PATH", default="/models/bge-reranker-v2-m3")
        tensor_parallel = self.params.get("RR_TENSOR_PARALLEL", default=1)
        max_model_len = self.params.get("RR_MAX_MODEL_LEN", default=1024)
        max_num_seqs = self.params.get("RR_MAX_NUM_SEQS", default=4)
        max_num_batched_tokens = self.params.get("RR_MAX_NUM_BATCHED_TOKENS", default=512)
        
        # Generate quadlet file
        self.generate_quadlet_file(
            usecase="reranker",
            image=image,
            aiu_pcie_ids=aiu_pcie_ids,
            memory=memory,
            model_path=model_path,
            tensor_parallel=1,
            max_model_len=1024,
            max_num_seqs=4,
            max_num_batched_tokens=512
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start service
        service_name = self.USECASES["reranker"]["service_name"]
        if not self.systemd_start_service(service_name):
            self.fail("Failed to start Reranker service")
        
        # Wait for VLLM startup
        if not self.wait_for_vllm_startup_journalctl(service_name):
            self.fail("VLLM failed to start for Reranker")
        
        # Collect logs
        self.collect_journalctl_logs(service_name, f"/tmp/{service_name}.log")
        
        # Stop service
        self.systemd_stop_service(service_name)
        
        self.log.info("✓ Reranker test completed successfully")

    def test_rag_quadlet(self):
        """Test RAG use case using quadlet."""
        self.log.info("=" * 80)
        self.log.info("Test: RAG (Quadlet)")
        self.log.info("=" * 80)
        
        # Get parameters from YAML
        image = self.params.get("IMAGE", default="")
        aiu_pcie_ids = self.params.get("PCIE_IDS", default="0233:70:00.0 0234:80:00.0 0333:70:00.0 0334:80:00.0")
        memory = self.params.get("RAG_MEMORY", default="200G")
        shm_size = self.params.get("RAG_SHM_SIZE", default="2G")
        model_path = self.params.get("RAG_MODEL_PATH", default="/models/granite-3.3-8b-instruct")
        tensor_parallel = self.params.get("RAG_TENSOR_PARALLEL", default=4)
        max_model_len = self.params.get("RAG_MAX_MODEL_LEN", default=32768)
        max_num_seqs = self.params.get("RAG_MAX_NUM_SEQS", default=32)
        max_num_batched_tokens = self.params.get("RAG_MAX_NUM_BATCHED_TOKENS", default=512)
        
        # Generate quadlet file
        self.generate_quadlet_file(
            usecase="rag",
            image=image,
            aiu_pcie_ids=aiu_pcie_ids,
            memory=memory,
            model_path=model_path,
            tensor_parallel=tensor_parallel,
            max_model_len=max_model_len,
            max_num_seqs=max_num_seqs,
            max_num_batched_tokens=max_num_batched_tokens,
            shm_size=shm_size
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start service
        service_name = self.USECASES["rag"]["service_name"]
        if not self.systemd_start_service(service_name):
            self.fail("Failed to start RAG service")
        
        # Wait for VLLM startup
        if not self.wait_for_vllm_startup_journalctl(service_name, timeout=900):
            self.fail("VLLM failed to start for RAG")
        
        # Collect logs
        self.collect_journalctl_logs(service_name, f"/tmp/{service_name}.log")
        
        # Stop service
        self.systemd_stop_service(service_name)
        
        self.log.info("✓ RAG test completed successfully")

    def test_all_usecases_quadlet_sequential(self):
        """
        Test all use cases sequentially with proper PCIe ID management.
        
        When YAML has 4 PCIe AIU IDs:
        1. Start first three (EE, Reranker, Embedding) in parallel with single PCIe ID each
        2. Wait for all three to start successfully
        3. Shutdown all three containers
        4. Start RAG with all 4 PCIe IDs
        """
        self.log.info("=" * 80)
        self.log.info("Test: All Use Cases Sequential (Quadlet)")
        self.log.info("=" * 80)
        
        # Get all PCIe IDs from YAML
        all_pcie_ids = self.params.get("PCIE_IDS", default="0233:70:00.0 0234:80:00.0 0333:70:00.0 0334:80:00.0")
        pcie_id_list = all_pcie_ids.split()
        
        self.log.info("Available PCIe IDs: %s", pcie_id_list)
        
        if len(pcie_id_list) < 4:
            self.cancel("This test requires 4 PCIe IDs")
        
        # Phase 1: Start first three containers in parallel
        self.log.info("=" * 80)
        self.log.info("Phase 1: Starting EE, Reranker, and Embedding in parallel")
        self.log.info("=" * 80)
        
        # Get image from YAML (same for EE, Reranker, Embedding)
        image = self.params.get("IMAGE", default="")
        
        # Generate quadlet files for first three
        self.generate_quadlet_file(
            usecase="entity_extraction",
            image=image,
            aiu_pcie_ids=pcie_id_list[0],
            memory=self.params.get("EE_MEMORY", default="200G"),
            model_path=self.params.get("EE_MODEL_PATH", default="/models/granite-3.3-8b-instruct"),
            tensor_parallel=self.params.get("EE_TENSOR_PARALLEL", default=1),
            max_model_len=self.params.get("EE_MAX_MODEL_LEN", default=3072),
            max_num_seqs=self.params.get("EE_MAX_NUM_SEQS", default=16),
            max_num_batched_tokens=self.params.get("EE_MAX_NUM_BATCHED_TOKENS", default=512)
        )
        
        self.generate_quadlet_file(
            usecase="reranker",
            image=image,
            aiu_pcie_ids=pcie_id_list[1],
            memory=self.params.get("RR_MEMORY", default="1500G"),
            model_path=self.params.get("RR_MODEL_PATH", default="/models/bge-reranker-v2-m3"),
            tensor_parallel=self.params.get("RR_TENSOR_PARALLEL", default=1),
            max_model_len=self.params.get("RR_MAX_MODEL_LEN", default=1024),
            max_num_seqs=self.params.get("RR_MAX_NUM_SEQS", default=4),
            max_num_batched_tokens=self.params.get("RR_MAX_NUM_BATCHED_TOKENS", default=512)
        )
        
        self.generate_quadlet_file(
            usecase="embedding",
            image=image,
            aiu_pcie_ids=pcie_id_list[2],
            memory=self.params.get("EMB_MEMORY", default="1500G"),
            model_path=self.params.get("EMB_MODEL_PATH", default="/models/granite-embedding-125m-english"),
            tensor_parallel=self.params.get("EMB_TENSOR_PARALLEL", default=1),
            max_model_len=self.params.get("EMB_MAX_MODEL_LEN", default=512),
            max_num_seqs=self.params.get("EMB_MAX_NUM_SEQS", default=4),
            max_num_batched_tokens=self.params.get("EMB_MAX_NUM_BATCHED_TOKENS", default=512)
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start all three services in parallel using threads
        services_to_start = [
            self.USECASES["entity_extraction"]["service_name"],
            self.USECASES["reranker"]["service_name"],
            self.USECASES["embedding"]["service_name"]
        ]
        
        startup_results = {}
        
        def start_and_wait(service_name):
            """Thread function to start service and wait for VLLM."""
            self.log.info("Starting %s...", service_name)
            if self.systemd_start_service(service_name):
                startup_results[service_name] = self.wait_for_vllm_startup_journalctl(service_name)
            else:
                startup_results[service_name] = False
        
        # Start all three in parallel
        threads = []
        for service_name in services_to_start:
            thread = threading.Thread(target=start_and_wait, args=(service_name,))
            thread.start()
            threads.append(thread)
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        all_started = all(startup_results.values())
        
        if not all_started:
            self.log.error("Not all services started successfully:")
            for service_name, result in startup_results.items():
                status = "✓" if result else "✗"
                self.log.error("  %s %s", status, service_name)
            self.fail("Failed to start all three services")
        
        self.log.info("✓ All three services started successfully")
        
        # Collect logs for all three
        for service_name in services_to_start:
            self.collect_journalctl_logs(service_name, f"/tmp/{service_name}.log")
        
        # Phase 2: Shutdown all three containers
        self.log.info("=" * 80)
        self.log.info("Phase 2: Shutting down EE, Reranker, and Embedding")
        self.log.info("=" * 80)
        
        for service_name in services_to_start:
            self.systemd_stop_service(service_name)
        
        # Wait a bit for cleanup
        time.sleep(5)
        
        # Phase 3: Start RAG with all 4 PCIe IDs
        self.log.info("=" * 80)
        self.log.info("Phase 3: Starting RAG with all 4 PCIe IDs")
        self.log.info("=" * 80)
        
        image = self.params.get("IMAGE", default="")
        
        self.generate_quadlet_file(
            usecase="rag",
            image=image,
            aiu_pcie_ids=all_pcie_ids,
            memory=self.params.get("RAG_MEMORY", default="200G"),
            model_path=self.params.get("RAG_MODEL_PATH", default="/models/granite-3.3-8b-instruct"),
            tensor_parallel=self.params.get("RAG_TENSOR_PARALLEL", default=4),
            max_model_len=self.params.get("RAG_MAX_MODEL_LEN", default=32768),
            max_num_seqs=self.params.get("RAG_MAX_NUM_SEQS", default=32),
            max_num_batched_tokens=self.params.get("RAG_MAX_NUM_BATCHED_TOKENS", default=512),
            shm_size=self.params.get("RAG_SHM_SIZE", default="2G")
        )
        
        # Reload systemd
        self.systemd_daemon_reload()
        
        # Start RAG service
        rag_service = self.USECASES["rag"]["service_name"]
        if not self.systemd_start_service(rag_service):
            self.fail("Failed to start RAG service")
        
        # Wait for VLLM startup (longer timeout for RAG)
        if not self.wait_for_vllm_startup_journalctl(rag_service, timeout=900):
            self.fail("VLLM failed to start for RAG")
        
        # Collect logs
        self.collect_journalctl_logs(rag_service, f"/tmp/{rag_service}.log")
        
        # Stop RAG service
        self.systemd_stop_service(rag_service)
        
        self.log.info("=" * 80)
        self.log.info("✓ All use cases test completed successfully")
        self.log.info("=" * 80)

    def tearDown(self):
        """
        Cleanup after tests.
        
        This includes:
        - Stopping all active systemd services
        - Cleaning up quadlet files
        """
        self.log.info("=" * 80)
        self.log.info("Starting tearDown - Cleaning up test resources")
        self.log.info("=" * 80)
        
        # Stop all active services
        if self.active_services:
            self.log.info("Stopping %d active service(s)", len(self.active_services))
            for service_name in list(self.active_services):
                self.systemd_stop_service(service_name)
        
        self.log.info("=" * 80)
        self.log.info("tearDown completed")
        self.log.info("=" * 80)
