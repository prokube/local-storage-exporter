from __future__ import annotations
from dataclasses import dataclass
import logging
import subprocess
import time
import re
import os
from pathlib import Path

from kubernetes import client, config
from prometheus_client import Gauge, start_http_server
from kubernetes.client.models.v1_persistent_volume_list import V1PersistentVolumeList
from kubernetes.client.models.v1_persistent_volume import V1PersistentVolume
from kubernetes.client.models.v1_pod_list import V1PodList
from kubernetes.client.models.v1_pod import V1Pod

# Set up logging and create handler for info logs
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)
_logger.addHandler(handler)


# fmt: off
# Compile the regex pattern once
STORAGE_CAPACITY_PATTERN = re.compile(r"(\d+)([a-zA-Z]+)")
STORAGE_UNITS = {
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6,
    "k": 10**3, "M": 10**6,    "G": 10**9,    "T": 10**12,   "P": 10**15,   "E": 10**18
}
# fmt: on
def convert_storage_capacity_to_bytes(storage_capacity: str) -> int:
    global STORAGE_CAPACITY_PATTERN
    global STORAGE_UNITS
    match = STORAGE_CAPACITY_PATTERN.match(storage_capacity)
    if match:
        value, unit = match.groups()
        if unit in STORAGE_UNITS:
            return int(value) * STORAGE_UNITS[unit]
    return int(storage_capacity)


class LocalStorageExporter:
    gauge: Gauge
    k8s_client: client.CoreV1Api
    storage_class_name: str
    hostpath_mount_paths: list[Path]

    def __init__(
        self,
        storage_class_name: str,
        incluster: bool = True,
        config_file: str | None = None,
    ):
        try:
            if incluster:
                config.load_incluster_config()
            elif config_file:
                config.load_config(config_file)
            else:
                config.load_config()
            self.k8s_client = client.CoreV1Api()
        except config.ConfigException as e:
            _logger.error(f"Failed to load k8s config: {e}")
            raise

        self.hostpath_mount_paths = self.find_hostpath_mount_paths()
        if len(self.hostpath_mount_paths) == 0:
            _logger.error("Failed to find any hostpath mount path")
            raise Exception("Failed to find any hostpath mount path")

        self.gauge = Gauge(
            name="local_storage_pv_used_bytes",
            documentation="The amount of bytes used by local storage volume",
            labelnames=[
                "pvc_name",
                "pv_name",
                "storage_path",
                "storage_capacity",
                "storage_class_name",
            ],
        )
        self.storage_class_name = storage_class_name

    def get_pod(self) -> V1Pod:
        pod_hostname = os.getenv("HOSTNAME")
        with open(
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
        ) as file:
            pod_namespace = file.read().strip()

        pods: V1PodList = self.k8s_client.list_namespaced_pod(
            namespace=pod_namespace, field_selector=f"metadata.name={pod_hostname}"
        )
        assert (
            len(pods.items) == 1
        ), f"Expected to find one pod with name {pod_hostname} in namespace {pod_namespace}, but found {len(pods.items)}"

        pod: V1Pod = pods.items[0]
        return pod

    def find_hostpath_mount_paths(self) -> dict[Path, Path]:
        pod = self.get_pod()
        assert len(pod.spec.containers) == 1, "Expected to find one container in pod"
        container = pod.spec.containers[0]
        mount_paths = {}
        for volume in pod.spec.volumes:
            if volume.host_path:
                for volume_mount in container.volume_mounts:
                    if volume_mount.name == volume.name:
                        mount_paths[Path(volume.host_path.path)] = Path(
                            volume_mount.mount_path)
                        break
        return mount_paths

    def get_pvs(self) -> V1PersistentVolumeList:
        pvs: V1PersistentVolumeList = self.k8s_client.list_persistent_volume()
        pvs.items = [pv for pv in pvs.items if pv.spec.storage_class_name == self.storage_class_name] 
        return pvs

    def get_pv_usage(self, pv: V1PersistentVolume) -> int | None:
        base_name = os.path.basename(pv.spec.local.path)
        dir_name = os.path.dirname(pv.spec.local.path)

        path: Path = self.hostpath_mount_paths.get(Path(dir_name))
        if path is None:
            _logger.error(f"Failed to find hostpath mount path for {dir_name}")
            return None
        path = path / base_name    
        if not path.exists():
            _logger.error(f"Path {path} does not exist")
            return None
        
        try:
            result = result = subprocess.run(
                ["du", "-sb", os.fspath(path)],
                capture_output=True,
                text=True,
                check=True,
            )
            size = result.stdout.split("\t")[0]
            return int(size)
        except Exception as e:
            _logger.error(f"Failed to get volume usage for {path}: {e}")
            return None

    def update_metrics(self):
        pvs = self.get_pvs()
        for pv in pvs.items:
            usage = self.get_pv_usage(pv)
            gauge = self.gauge.labels(
                pv.spec.claim_ref.name,
                pv.metadata.name,
                pv.spec.local.path,
                convert_storage_capacity_to_bytes(pv.spec.capacity["storage"]),
                self.storage_class_name,
            )
            if usage is not None:
                gauge.set(usage)
            else:
                gauge.set(-1)


def main():
    try:
        storage_class_name = os.environ.get("STORAGE_CLASS_NAME")
        port = os.environ.get("METRICS_PORT", 9100)
        _logger.info(f"Storageclass name: {storage_class_name}")
        _logger.info(f"Metrics port: {port}")

        lse = LocalStorageExporter(storage_class_name=storage_class_name)
        start_http_server(port)
        _logger.info(f"Started local storage exporter on port {port}")
        while True:
            lse.update_metrics()
            time.sleep(30)
    except Exception as e:
        _logger.error(f"Caught exception in main: {e}")
        raise


if __name__ == "__main__":
    main()