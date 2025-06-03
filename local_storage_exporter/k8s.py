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


_logger = utils.createLogger(__name__)

class LocalStorageExporter:
    """
    A Kubernetes local storage exporter that monitors persistent volumes and mounted storage.
    
    This class provides functionality to discover and monitor local storage usage in a Kubernetes
    cluster by examining persistent volumes and their corresponding mount points on the current node.
    """
    k8s_client: client.CoreV1Api
    storage_class_names: list[str] = []
    host_path_to_volume_mount: dict[Path, Path] = {}
    node_name: str

    def __init__(
        self,
        storage_class_names: list[str],
    ):
        """
        Initialize the LocalStorageExporter with specified storage classes.
        
        Sets up Kubernetes client configuration, discovers host path to volume mount mappings,
        and identifies the current node name where the exporter is running.
        
        Args:
            storage_class_names: List of storage class names to monitor
            
        Raises:
            config.ConfigException: If Kubernetes configuration cannot be loaded
            RuntimeError: If no hostPath mounted volumes are found
        """
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
        """
        Get the current pod where this exporter is running.
        
        Uses the HOSTNAME environment variable and service account namespace to locate
        the pod in the Kubernetes cluster.
        
        Returns:
            V1Pod: The pod object representing the current exporter pod
            
        Raises:
            LookupError: If exactly one pod cannot be found with the expected hostname
        """
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
        """
        Get the container from the pod that is running the local storage exporter using a name identifier.
        
        Searches through the pod's containers to find the one with the exporter identifier
        in its name. The identifier can be customized via the EXPORTER_CONTAINER_NAME_IDENTIFIER
        environment variable.
        
        Args:
            pod: The pod containing the containers to search
            
        Returns:
            V1Container: The container running the local storage exporter
            
        Raises:
            LookupError: If exactly one container cannot be found with the identifier
        """
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
        """
        Discover the mapping between host paths and container volume mount paths.
        
        Examines the current pod's volumes and volume mounts to create a mapping
        from host filesystem paths to container mount paths. This is essential
        for translating persistent volume paths to accessible container paths.
        
        Returns:
            dict[Path, Path]: Mapping from host paths to volume mount paths
        """
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
        """
        Retrieve persistent volumes filtered by configured storage classes.
        
        Fetches all persistent volumes from the cluster and filters them to only
        include those with storage classes specified in the exporter configuration.
        
        Returns:
            V1PersistentVolumeList: List of persistent volumes matching the storage classes
        """
        pvs: V1PersistentVolumeList = self.k8s_client.list_persistent_volume()
        pvs.items = [
            pv
            for pv in pvs.items
            if pv.spec.storage_class_name in self.storage_class_names
        ]
        return pvs

    def get_pv_usage(self, pv: V1PersistentVolume) -> int | None:
        """
        Calculate the disk usage of a persistent volume in bytes.
        
        Determines the actual disk usage by mapping the persistent volume's path
        to a local container path and using the 'du' command to measure usage.
        
        Args:
            pv: The persistent volume to measure
            
        Returns:
            int | None: Size in bytes, or None if measurement fails
        """
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
        local_path: Path | None = None
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
            # Use 'du' to get the size of the directory in bytes
            # The number and path are separated by a tab character
            # Example output for 'du -sb /path/to/volume': 
            # 12345678  /path/to/volume 
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

    def get_mount_storage_info(self, volume_mount_path: Path) -> tuple[int, int, int]:
        """
        Get filesystem storage information for a mounted volume path.
        
        Uses the 'df' command to retrieve capacity, used space, and available space
        for the filesystem containing the specified mount path.
        
        Args:
            volume_mount_path: Path to the mounted volume
            
        Returns:
            tuple[int, int, int]: Capacity, used, and available space in bytes
            
        Raises:
            subprocess.CalledProcessError: If the df command fails
        """
        result = subprocess.run(
            ["df", "-B1", os.fspath(volume_mount_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.split("\n")
        # The second line contains the disk usage information
        # Example output for 'df -B1 /volumes':
        # Filesystem     1B-blocks       Used    Available Use% Mounted on
        # /dev/root   103865303040 49565679616 54282846208  48% /volumes
        volume_mount_info = lines[1].split()
        volume_mount_capacity = int(volume_mount_info[1])
        volume_mount_used = int(volume_mount_info[2])
        volume_mount_available = int(volume_mount_info[3])
        return volume_mount_capacity, volume_mount_used, volume_mount_available

    def update_pv_metrics(self):
        """
        Update Prometheus metrics for all persistent volumes on the current node.
        
        Iterates through all persistent volumes matching the configured storage classes,
        calculates their usage, and updates the corresponding Prometheus gauges with
        usage and capacity information. Only processes volumes on the current node.
        """
        pvs = self.get_pvs()
        pv: V1PersistentVolume
        for pv in pvs.items:
            pv_node_name = pv.spec.node_affinity.required.node_selector_terms[0].match_expressions[0].values[0]
            if pv_node_name != self.node_name:
                _logger.debug(
                    f"Skipping PV {pv.metadata.name} because it is not on this node ({self.node_name} but in node {pv_node_name})"
                )
                continue
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
        """
        Update Prometheus metrics for all mounted storage volumes.
        
        Iterates through all discovered host path to volume mount mappings,
        retrieves filesystem information for each mount, and updates the
        corresponding Prometheus gauges with capacity, used, and available space.
        """
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
        """
        Update all storage-related Prometheus metrics.
        
        Orchestrates the update of both persistent volume metrics and mounted
        storage metrics by calling the respective update methods. This is the
        main entry point for metric collection.
        """
        self.update_pv_metrics()
        self.update_mount_storage_metrics()
