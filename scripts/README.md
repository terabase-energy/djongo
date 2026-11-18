# DocumentDB capacity evidence

Run once in staging and once in production, after selecting the environment's
normal AWS login/profile and default region:

```bash
python3 scripts/collect_docdb_capacity.py CLUSTER_NAME > docdb-capacity.json
```

Only the cluster identifier is a parameter. The script uses the current AWS CLI
configuration and records the actual account ID, caller ARN and cluster region
in the JSON so reports from separate accounts can be distinguished. Save the
two runs to separate files. Requires Python 3.8+ and AWS CLI v2. Install `kubectl`
as well for EKS workload collection. No Python packages are needed.

The script makes read-only AWS and Kubernetes API calls. It does not connect to
DocumentDB, read Kubernetes Secrets or AWS secret values, run commands inside
pods, assume another role, or change AWS configuration or the current kubeconfig.
EKS access uses a temporary kubeconfig built from discovered clusters and the
current AWS identity; it requires network access to their API endpoints and
Kubernetes RBAC. ConfigMaps are read to resolve selected environment settings;
their raw data, arbitrary environment values and full command lines are omitted.

The report contains:

- Cluster engine/version, writer/reader endpoints and each member's role,
  instance class, availability zone and VPC.
- Seven days of per-instance CloudWatch samples, with ten-minute aggregation:
  `DatabaseConnections` and `DatabaseConnectionsMax` maxima,
  `DatabaseConnectionsLimit` minima, active connection maxima, memory minima,
  CPU maxima and CPU credit minima. Each series includes its sample count,
  timestamped extrema and latest bucket. Missing metrics remain unknown.
- Database security-group ingress, including source group/account references
  that can point to consumers outside the current account.
- Classic DMS endpoints/tasks matching a cluster endpoint, plus unverified
  Mongo/DocumentDB endpoint candidates. Serverless DMS is not inventoried.
- EKS workload templates, live pod state, HPA limits, deployment rollout
  strategies, job concurrency settings, termination grace periods, selected
  Gunicorn/Celery/pool environment settings and explicit worker flags.
  ConfigMap values are resolved; Secret references remain unresolved.
  Workloads are included across namespaces, with endpoint-match evidence where
  visible, so clients hidden behind secret configuration are not silently lost.

`budget_ready` is deliberately `false`: this is evidence for a reviewed budget,
not an automatically approved pool size. Check `remaining_inputs` and
`collection_errors`. Client discovery covers the active AWS account and region;
other accounts, other regions, ECS/EC2/Lambda/Batch, external clients and
application settings inside images still need confirmation. EKS may itself be
in another account from DocumentDB. Zero discovered clusters or endpoint matches
does not prove there are no consumers. No process multiplier is inferred from
an image name or an application default that is not visible in the deployment.

Do not add template counts and their observed pods together. The deployment
`nonterminating_rollout_target_at_configured_max` includes rounded-up surge at
the larger of desired replicas and HPA maxima; terminating pods can exceed that
number. It is not a bound on total processes. CronJob overlap, worker recycling,
preload, Celery pool type, separate aliases/result backends and monitor sockets
also affect the final budget. Compare usage with limits **per instance** and
reserve agreed operating headroom; do not sum writer and reader capacity.

Exit status is `0` when collection calls succeeded, `2` when optional collection
failed but a JSON report was written, and `1` when AWS identity or the requested
cluster could not be read. Empty metrics are represented by zero sample count
and null summaries, not a fabricated zero usage/limit. Some instance classes do
not publish CPU credit metrics. Neither exit `0` nor a complete AWS inventory
establishes that all consumers or runtime client settings are known.

Read access used: `sts:GetCallerIdentity`, `rds:DescribeDBClusters`,
`rds:DescribeDBInstances` (DocumentDB uses the `rds` IAM prefix),
`cloudwatch:GetMetricStatistics`, `ec2:DescribeSecurityGroups`,
`dms:DescribeEndpoints`, `dms:DescribeReplicationTasks`, `eks:ListClusters`,
`eks:DescribeCluster`, EKS authentication and Kubernetes list/get for Deployments,
StatefulSets, DaemonSets, Jobs, CronJobs, Pods, HPAs and ConfigMaps. Missing
optional permissions are recorded rather than turning an unknown into zero.

Run the offline tests with:

```bash
python3 -m unittest discover -s tests/mock_tests -p 'test_collect_docdb_capacity.py' -v
```

References: [DocumentDB metrics](https://docs.aws.amazon.com/documentdb/latest/devguide/cloud_watch.html),
[DocumentDB quotas](https://docs.aws.amazon.com/documentdb/latest/devguide/limits.html),
[CloudWatch statistics](https://docs.aws.amazon.com/cli/latest/reference/cloudwatch/get-metric-statistics.html),
[EKS tokens](https://docs.aws.amazon.com/cli/latest/reference/eks/get-token.html),
and [deployment rollout semantics](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/).
