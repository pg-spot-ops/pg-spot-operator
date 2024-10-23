# Monitoring

By default, there's no out-of-the-box monitoring besides AWS instance level metrics that you get automatically, whereby
better (1min) resolution can be enabled (default is 5min) via `vm.detailed_monitoring` for an extra cost.

For additional high-frequency metrics overload one could though enable Prometheus + [node_exporter](https://github.com/prometheus/node_exporter)
and make it accessible via Grafana, using self-signed certificates or plain http.

PS Beware - when setting `monitoring.grafana.enabled` admin password is automatically set to equal the instance name
for convenience by default, if `monitoring.grafana.admin_password` not set!

PS2 Note that for public Grafana access to work, your Security Group of choice needs to have port 3000 open.

Relevant manifest attributes/defaults:

```
monitoring:
  prometheus_node_exporter:
    enabled: false
    externally_accessible: false
  grafana:
    enabled: false
    externally_accessible: true
    admin_user: pgspotops
    admin_password: "{{ instance_name }}"
    anonymous_access: true
    protocol: https
```

Relevant CLI flags:

```
--monitoring
--grafana-externally-accessible
--grafana-anonymous
```
