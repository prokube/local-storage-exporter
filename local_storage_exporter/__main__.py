import logging
import time
import os

from prometheus_client import start_http_server

from local_storage_exporter.k8s import LocalStorageExporter
from local_storage_exporter import utils


def main():
    # Set up logging and create handler for info logs
    _logger = utils.createLogger(__name__)
    _logger.info("Starting local storage exporter...")
    try:
        # PVs that we want to monitor should have storage class name that is in the list
        # Expect comma separated list
        storage_class_names = os.environ.get("STORAGE_CLASS_NAMES")
        storage_class_names = (
            storage_class_names.split(",") if storage_class_names else []
        )
        if storage_class_names == []:
            _logger.error("No storage class names provided. Exiting...")
            exit(1)

        # Port to expose metrics
        port = int(os.environ.get("METRICS_PORT", 9100))

        # Update interval with ms, s, m, h suffixes, no suffix means seconds
        update_interval = os.environ.get("UPDATE_INTERVAL")
        if update_interval:
            update_interval = utils.convert_str_to_seconds(update_interval)
        else:
            update_interval = 30

        _logger.info(f"Storageclass names: {storage_class_names}")
        _logger.info(f"Metrics port: {port}")
        _logger.info(f"Update interval: {update_interval} seconds")

        pvc_label_keys_raw = os.environ.get("PVC_LABEL_KEYS", "")
        pvc_label_keys = [k.strip() for k in pvc_label_keys_raw.split(",") if k.strip()]
        include_pvc_labels_blob = os.environ.get("PVC_LABELS_BLOB", "false").lower() == "true"

        lse = LocalStorageExporter(
            storage_class_names=storage_class_names,
            pvc_label_keys=pvc_label_keys,
            include_pvc_labels_blob=include_pvc_labels_blob,
        )
        start_http_server(port)  # Metrics exporter server
        _logger.info(f"Started local storage exporter on port {port}")
        while True:
            lse.update_metrics()
            time.sleep(update_interval)
    except Exception as e:
        _logger.error(f"Caught exception in main: {e}")
        raise


if __name__ == "__main__":
    main()
