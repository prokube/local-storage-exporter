from __future__ import annotations
from dataclasses import dataclass
import logging
import subprocess
import time
import re

from kubernetes import client, config
from prometheus_client import Gauge, start_http_server
from kubernetes.client.models.v1_persistent_volume_list import V1PersistentVolumeList

# Set up logging and create handler for info logs
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)
_logger.addHandler(handler)


@dataclass
class Volume:
    pvc_name: str
    pv_name: str
    storage_path: str
    storage_capacity: str


# Compile the regex pattern once
STORAGE_CAPACITY_PATTERN = re.compile(r"(\d+)([a-zA-Z]+)")
STORAGE_UNITS = {
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6,
    "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15, "E": 10**18
}
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

    def __init__(self, incluster: bool = True, config_file: str | None = None):
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

        self.volumes = []
        self.gauge = Gauge(
            name="lse_pv_used_bytes",
            documentation="The amount of bytes used by local storage volume",
            labelnames=["pvc_name", "pv_name", "storage_path", "storage_capacity"],
        )

    def get_volumes(self) -> list[Volume]:
        volumes = []
        pvs: V1PersistentVolumeList = self.k8s_client.list_persistent_volume()
        for pv in pvs.items:
            if pv.spec.storage_class_name == "openebs-hostpath":
                volumes.append(
                    Volume(
                        pvc_name=pv.spec.claim_ref.name,
                        pv_name=pv.metadata.name,
                        storage_path=pv.spec.local.path,
                        storage_capacity=convert_storage_capacity_to_bytes(pv.spec.capacity["storage"]),
                    )
                )
        return volumes

    @staticmethod
    def get_volume_usage(volume: Volume) -> int | None:
        try:
            result = result = subprocess.run(
                ["du", "-sb", f"/volumes/{volume.pv_name}"],
                capture_output=True,
                text=True,
                check=True,
            )
            size = result.stdout.split("\t")[0]
            return int(size)
        except Exception as e:
            _logger.error(f"Failed to get volume usage for {volume.storage_path}: {e}")
            return None

    def update_metrics(self):
        volumes = self.get_volumes()
        for volume in volumes:
            usage = self.get_volume_usage(volume)
            if usage is not None:
                self.gauge.labels(
                    volume.pvc_name,
                    volume.pv_name,
                    volume.storage_path,
                    volume.storage_capacity,
                ).set(usage)
            else:
                self.gauge.labels(
                    volume.pvc_name,
                    volume.pv_name,
                    volume.storage_path,
                    volume.storage_capacity,
                ).set(-1.0)


def main():
    lse = LocalStorageExporter()
    port = 9100
    start_http_server(port)
    _logger.info(f"Started local storage exporter on port {port}")
    while True:
        lse.update_metrics()
        time.sleep(60)

    volumes = lse.get_volumes()
    total = 0
    for v in volumes:
        # print(lme.get_volume_usage(v))
        result = lse.get_volume_usage(v)
        total += result if result is not None else 0
        print(result, v.pv_name, v.pvc_name)

    print(f"total: {total}")


if __name__ == "__main__":
    main()
