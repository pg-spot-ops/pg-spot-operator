# Running on K8s

The operator runs just fine on K8s - a few things to be aware of though:

* Currently a native Service is NOT created automatically - meaning one needs to explicitly handle the Postgres connect string
  "propagation" to apps / users using one of the integration options. See [docs/README_integration.md](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md)
  for options.
  - If the instance is for ad-hoc usage, one can also just use a fixed IP and extract the connect string once from the logs
* The `/app/.ssh` folder should be a persistent mount, otherwise if an unlucky situation happens where both the Spot VM
 and the pod get interrupted close to each other, the new pod will not have SSH / Ansible level access and can't re-try
 the Postgres setup. One can fix that with a manual VM termination / recycle though.
* Nice if also the `/app/.pg-spot-operator` folder is a persistent mount, otherwise some unnecessary work will be performed
  on pod recycle.
* If possible one should not feed in AWS credentials anymore explicitly but use integrated / transparent auth, like
  [IAM roles for service accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html).

# Declaring a K8s service to route to the VM

To create a real K8s service for convenient app usage one needs to:
  1. Run in non-floating IP mode (`ip_floating: false`)
  2. Create the deployment as normal via `helm install` and note the created public IP
  3. Create a K8s service with a fixed IP endpoint, pointing from the K8s cluster to the VM
  4. Clean up if the instance is destroyed

```
$ cat example_service.yaml
---
apiVersion: v1
kind: Service
metadata:
  name: MY_INSTANCE
spec:
  ports:
  - port: 5432
    targetPort: 5432
  clusterIP: None # Ensures the Service acts as a selector-less service
---
apiVersion: v1
kind: Endpoints
metadata:
  name: MY_INSTANCE
subsets:
  - addresses:
      - ip: X.X.X.X # Replace with the external IP address
    ports:
      - port: 5432

# PS change the name and external IP address!!
$ kubectl apply -f example_service.yaml
```
