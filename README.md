# K8s Local Storage Metrics Exporter
This repository contains the code, Dockerfile, Helm chart and a Grafana dashboard for a local storage metrics exporter for k8s storage providers that are using host path, such as openebs-hostpath, microk8s-hostpath, standard storage class for minikube, kind and k3s.

## Repository Organization

The local storage metrics exporter is written in python and the code is (currently) in one python file `local_storage_exporter.py`.
It is designed to be deployed as a kubernetes pod, therefore running it as is will not work.
To run it, first you need to build it as a container image. Below is the steps to build and push it to gcp docker registry:
```bash
# Example env values
# REGISTRY=europe-west3-docker.pkg.dev
# PROJECT=my-project
# PLATFORM=amd64
docker build -t $REGISTRY/$PROJECT/prokube/local-storage-exporter:$PLATFORM --platform=linux/$PLATFORM .
docker push $REGISTRY/$PROJECT/prokube/local-storage-exporter:$PLATFORM
```

After building the image and push it to your registry, you can deploy it using the provided helm chart after providing a values file.
You can check `local-storage-exporter-helm/values.yaml` to see the values you can use for the helm chart.
Example values.yaml:
```yaml
# values.yaml
# serviceMonitor requires monitoring.coreos.com/v1 api, which can be installed through prometheus-operator
serviceMonitor:
  enabled: true

image:
  tag: amd64
  imagePullPolicy: Always
  registry: <registry>

imagePullSecrets:
  - name: <registry credentials> # Don't forget to create the secret!

updateInterval: 15s

storageClassNames: [openebs-hostpath]
storagePath: /var/openebs/local/
```

```bash
helm install -n <namespace> <release name> ./local-storage-exporter-helm --create-namespace --values=values.yaml
```

After deploying the helm release, you can check if the exporter is working by port-forwarding to the created service and using a http client to check the endpoint. 
If you enabled serviceMonitor and have a prometheus instance running (such as after deploying the helm chart `kube-prometheus-stack`), you should see the metrics show at your prometheus instance.