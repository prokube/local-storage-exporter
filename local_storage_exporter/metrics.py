from prometheus_client import Gauge


_BASE_PV_LABELNAMES = [
    "node_name",
    "pvc_name",
    "pvc_namespace",
    "pv_name",
    "storage_path",
    "pv_capacity",
    "storage_class_name",
]


def create_pv_gauges(extra_labelnames: list[str], include_pvc_labels_blob: bool = False) -> tuple[Gauge, Gauge]:
    """
    Create and return the PV used/capacity gauges with the given extra label names appended.
    Called once at exporter startup based on the configured PVC label keys.
    """
    labelnames = _BASE_PV_LABELNAMES + extra_labelnames
    if include_pvc_labels_blob:
        labelnames = labelnames + ["pvc_labels"]
    pv_used_bytes_gauge = Gauge(
        name="local_storage_pv_used_bytes",
        documentation="The amount of bytes used by local storage volume",
        labelnames=labelnames,
    )
    pv_capacity_bytes_gauge = Gauge(
        name="local_storage_pv_capacity_bytes",
        documentation="The capacity of local storage volume",
        labelnames=labelnames,
    )
    return pv_used_bytes_gauge, pv_capacity_bytes_gauge


mounted_disk_used_gauge = Gauge(
    name="local_storage_mounted_disk_used_bytes",
    documentation="The amount of bytes used by mounted disk",
    labelnames=["node_name", "host_path", "volume_mount_path"],
)
mounted_disk_capacity_gauge = Gauge(
    name="local_storage_mounted_disk_capacity_bytes",
    documentation="The capacity of mounted disk",
    labelnames=["node_name", "host_path", "volume_mount_path"],
)
mounted_disk_available_gauge = Gauge(
    name="local_storage_mounted_disk_available_bytes",
    documentation="The amount of bytes available in mounted disk",
    labelnames=["node_name", "host_path", "volume_mount_path"],
)
