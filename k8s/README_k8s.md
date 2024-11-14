# Running on K8s

The operator runs fine on K8s, as it's a pretty simple loop. A few things to be aware of:

* Currently there's no native support - meaning you don't get a K8s Service, for your apps to connect to, meaning one
  needs to explicitly handle the Postgres connect string "propagation". See the according [docs/README_integration.md](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md).
  - If the instance is for ad-hoc usage, one can also just use a fixed IP and extract the connect string once from the logs
* The `/app/.ssh` folder should be a persistent mount, otherwise if an unlucky situation happens where both the Spot VM
 and the pod get interrupted close to each other, the new pod will not have SSH / Ansible level access and can't re-try
 the Postgres setup. One can fix that with a manual VM termination / recycle though.
* Nice if also the `/app/.pg-spot-operator` folder is persistent mount, otherwise some unnecessary work will be performed
  on pod recycle.
* If possible one should not feed in AWS credentials anymore explicitly but use integrated / transparent auth, like
  [IAM roles for service accounts](IAM roles for service accounts).
