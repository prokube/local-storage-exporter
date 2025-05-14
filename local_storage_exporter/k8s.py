from __future__ import annotations
import logging
import subprocess
import os
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.models.v1_persistent_volume_list import V1PersistentVolumeList
from kubernetes.client.models.v1_persistent_volume import V1PersistentVolume
from kubernetes.client.models.v1_pod_list import V1PodList
from kubernetes.client.models.v1_pod import V1Pod

from . import utils, metrics


_logger = logging.getLogger(__name__)


class LocalStorageExporter:
    k8s_client: client.CoreV1Api
    storage_class_names: list[str] = []
    host_path_to_volume_mount: dict[Path, Path] = {}
    node_name: str

    def __init__(
        self,
        storage_class_names: list[str],
    ):
        try:
            config.load_incluster_config()
            self.k8s_client = client.CoreV1Api()
        except config.ConfigException as e:
            _logger.error(f"Failed to load k8s config: {e}")
            raise

        # Find the host path to volume mount mapping
        self.host_path_to_volume_mount = self.find_host_path_to_volume_mount()
        if len(self.host_path_to_volume_mount) == 0:
            _logger.error("Could not find any hostPath mounted volume.")
            raise RuntimeError("no hostPath mounted volume found")

        self.node_name = self.get_pod().spec.node_name
        self.storage_class_names = storage_class_names

    def get_pod(self) -> V1Pod:
        pod_hostname = os.getenv("HOSTNAME")
        with open(
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
        ) as file:
            pod_namespace = file.read().strip()

        pods: V1PodList = self.k8s_client.list_namespaced_pod(
            namespace=pod_namespace, field_selector=f"metadata.name={pod_hostname}"
        )
        if len(pods.items) != 1:
            pod_names = [pod.metadata.name for pod in pods.items]
            raise LookupError(
                f"Expected to find one pod with name '{pod_hostname}' in namespace '{pod_namespace}', but found {len(pods.items)}. Found pods: {', '.join(pod_names)}"
            )

        pod: V1Pod = pods.items[0]
        return pod

    @staticmethod
    def get_container(pod: V1Pod) -> client.V1Container:
        container_name_identifier = os.getenv(
            "EXPORTER_CONTAINER_NAME_IDENTIFIER", "local-storage-exporter"
        )
        containers = [
            c for c in pod.spec.containers if container_name_identifier in c.name
        ]
        if len(containers) != 1:
            raise LookupError(
                f"Expected to find one container with '{container_name_identifier}' in its name, but found {len(containers)}"
            )
        return containers[0]

    def find_host_path_to_volume_mount(self) -> dict[Path, Path]:
        pod = self.get_pod()
        container = LocalStorageExporter.get_container(pod)
        mount_paths = {}
        for volume in pod.spec.volumes:
            if volume.host_path:
                for volume_mount in container.volume_mounts:
                    if volume_mount.name == volume.name:
                        mount_paths[Path(volume.host_path.path)] = Path(
                            volume_mount.mount_path
                        )
                        break
        return mount_paths

    def get_pvs(self) -> V1PersistentVolumeList:
        pvs: V1PersistentVolumeList = self.k8s_client.list_persistent_volume()
        pvs.items = [
            pv
            for pv in pvs.items
            if pv.spec.storage_class_name in self.storage_class_names
        ]
        return pvs

    def get_pv_usage(self, pv: V1PersistentVolume) -> int | None:
        if pv.spec.local is not None:
            pv_path = Path(pv.spec.local.path)
        elif pv.spec.host_path is not None:
            pv_path = Path(pv.spec.host_path.path)
        else:
            _logger.error(
                f"PV {pv.metadata.name} does not have local or host path spec"
            )
            return None

        # Find the local path for the mounted volume
        local_path: Path = None
        for parent in pv_path.parents:
            if parent in self.host_path_to_volume_mount:
                relative = pv_path.relative_to(parent)
                local_path = self.host_path_to_volume_mount[parent] / relative
                break

        if local_path is None:
            _logger.error(
                f"Could not find host path mount path for {pv_path}. Did you mount the correct path?"
            )
            return None
        if not local_path.exists():
            # Should not happen, but just in case
            _logger.error(f"Path {local_path} does not exist")
            return None

        try:
            result = result = subprocess.run(
                ["du", "-sb", os.fspath(local_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            size = result.stdout.split("\t")[0]
            return int(size)
        except Exception as e:
            _logger.error(f"Failed to get volume usage for {local_path}: {e}")
            return None

    def get_mount_storage_info(self, volume_mount_path: Path) -> tuple[int, int]:
        result = subprocess.run(
            ["df", "-B1", os.fspath(volume_mount_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.split("\n")
        # The second line contains the disk usage information
        # Example output:
        # Filesystem     1B-blocks       Used    Available Use% Mounted on
        # /dev/root   103865303040 49565679616 54282846208  48% /volumes
        volume_mount_info = lines[1].split()
        volume_mount_capacity = int(volume_mount_info[1])
        volume_mount_used = int(volume_mount_info[2])
        volume_mount_available = int(volume_mount_info[3])
        return volume_mount_capacity, volume_mount_used, volume_mount_available

    def update_pv_metrics(self):
        pvs = self.get_pvs()
        for pv in pvs.items:
            usage = self.get_pv_usage(pv)
            pvc_name = pv.spec.claim_ref.name
            pvc_namespace = pv.spec.claim_ref.namespace
            pv_name = pv.metadata.name
            storage_path = (
                pv.spec.local.path if pv.spec.local else pv.spec.host_path.path
            )
            pv_capacity = utils.convert_storage_capacity_to_bytes(
                pv.spec.capacity["storage"]
            )
            storage_class_name = pv.spec.storage_class_name
            pv_used_bytes_gauge = metrics.pv_used_bytes_gauge.labels(
                node_name=self.node_name,
                pvc_name=pvc_name,
                pvc_namespace=pvc_namespace,
                pv_name=pv_name,
                storage_path=storage_path,
                pv_capacity=pv_capacity,
                storage_class_name=storage_class_name,
            )
            if usage is not None:
                pv_used_bytes_gauge.set(usage)
            else:
                pv_used_bytes_gauge.set(-1)
                _logger.error(
                    f"Failed to get usage for PV {pv_name}, so setting it to -1"
                )

            # This is a constant value, so we don't need to update it every time
            # However this is a simple way to ensure that the metric is always updated when there was a change instead of tracking creation/deletion events
            # If we can just extract this information from the used_bytes_gauge label using promql (or different method), we can remove this gauge.
            metrics.pv_capacity_bytes_gauge.labels(
                node_name=self.node_name,
                pvc_name=pvc_name,
                pvc_namespace=pvc_namespace,
                pv_name=pv_name,
                storage_path=storage_path,
                pv_capacity=pv_capacity,
                storage_class_name=storage_class_name,
            ).set(pv_capacity)

    def update_mount_storage_metrics(self):
        for host_path, volume_mount_path in self.host_path_to_volume_mount.items():
            capacity, used, available = self.get_mount_storage_info(volume_mount_path)
            metrics.mounted_disk_capacity_gauge.labels(
                node_name=self.node_name,
                host_path=host_path,
                volume_mount_path=volume_mount_path,
            ).set(capacity)
            metrics.mounted_disk_used_gauge.labels(
                node_name=self.node_name,
                host_path=host_path,
                volume_mount_path=volume_mount_path,
            ).set(used)
            metrics.mounted_disk_available_gauge.labels(
                node_name=self.node_name,
                host_path=host_path,
                volume_mount_path=volume_mount_path,
            ).set(available)

    def update_metrics(self):
        self.update_pv_metrics()
        self.update_mount_storage_metrics()
