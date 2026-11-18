#!/usr/bin/env python3
"""Read-only DocumentDB capacity evidence using the active AWS CLI configuration.

Usage: python3 scripts/collect_docdb_capacity.py CLUSTER > capacity.json
Requires Python 3.8+ and AWS CLI v2. kubectl enables optional EKS inventory.
No profile/region overrides, database credentials, pod exec or kubeconfig changes.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


METRICS = {
    "DatabaseConnections": "Maximum",
    "DatabaseConnectionsMax": "Maximum",
    "DatabaseConnectionsLimit": "Minimum",
    "DatabaseConnectionsActiveMax": "Maximum",
    "FreeableMemory": "Minimum",
    "CPUUtilization": "Maximum",
    "CPUCreditBalance": "Minimum",
}
PROCESS_ENV = {
    "GUNICORN_WORKERS", "GUNICORN_WORKER_CONNECTIONS", "GUNICORN_WORKER_CLASS",
    "GUNICORN_PRELOAD", "CELERY_WORKER_CONCURRENCY", "CELERY_CONCURRENCY",
    "CELERYD_CONCURRENCY", "CELERYD_AUTOSCALE", "CELERY_WORKER_POOL",
    "MONGO_MAX_POOL_SIZE", "MONGODB_MAX_POOL_SIZE", "PYMONGO_MAX_POOL_SIZE",
    "MONGO_MIN_POOL_SIZE", "MONGODB_MIN_POOL_SIZE", "MONGO_WAIT_QUEUE_TIMEOUT_MS",
}
KUBE_RESOURCES = (
    "deployments.apps", "statefulsets.apps", "daemonsets.apps", "jobs.batch",
    "cronjobs.batch", "pods", "horizontalpodautoscalers.autoscaling",
    "configmaps",
)


class CollectionError(Exception):
    """A failed collection command; never includes raw CLI output or credentials."""


def run_json(command):
    env = dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off")
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=90, env=env,
        )
    except FileNotFoundError:
        raise CollectionError("missing_executable") from None
    except subprocess.TimeoutExpired:
        raise CollectionError("timeout") from None
    if result.returncode:
        message = result.stderr.lower()
        reason = "command_failed"
        for pattern, category in (
            ("accessdenied", "access_denied"), ("forbidden", "access_denied"),
            ("unauthorized", "unauthorized"), ("expired", "credentials_expired"),
            ("sso", "sso_error"), ("unable to locate credentials", "no_credentials"),
            ("you must specify a region", "no_default_region"),
            ("timed out", "timeout"), ("timeout", "timeout"),
            ("doesn't have a resource type", "resource_not_installed"),
            ("notfound", "not_found"),
        ):
            if pattern in message:
                reason = category
                break
        raise CollectionError(reason)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise CollectionError("invalid_json") from None


def aws(service, operation, *arguments):
    # AWS CLI handles pagination. Inherit profile, region and credentials unchanged.
    return run_json([
        "aws", service, operation, *arguments, "--output", "json", "--no-cli-pager",
    ])


def select(data, *keys):
    return {key: data[key] for key in keys if key in data}


def metric_summary(response, statistic):
    points = sorted(response.get("Datapoints", []), key=lambda point: point["Timestamp"])
    samples = [
        {"timestamp": point["Timestamp"], "value": point[statistic]}
        for point in points if statistic in point
    ]
    return {
        "statistic": statistic,
        "period_seconds": 600,
        "sample_count": len(samples),
        "minimum": min(samples, key=lambda point: point["value"]) if samples else None,
        "maximum": max(samples, key=lambda point: point["value"]) if samples else None,
        "latest": samples[-1] if samples else None,
        "unit": points[0].get("Unit") if points else None,
        "samples": samples,
    }


def endpoint_matches(value, endpoints):
    """Extract evidence without returning a possibly credential-bearing URI."""
    return sorted(
        endpoint for endpoint in endpoints
        if re.search(r"(?<![a-z0-9.-])" + re.escape(endpoint) + r"(?![a-z0-9.-])",
                     str(value).lower())
    )


def safe_process_value(value):
    # No arbitrary environment/command strings enter the report.
    text = str(value)
    if re.fullmatch(r"\d+(?:,\d+)?", text):
        return text
    if text.lower() in {"true", "false", "gevent", "eventlet", "sync", "gthread",
                        "prefork", "threads", "solo"}:
        return text
    return "unresolved_expression"


def container_summary(container, configmaps, namespace, endpoints):
    values = {}
    references = []
    unresolved = False
    for source in container.get("envFrom", []):
        references.append(select(source, "prefix", "configMapRef", "secretRef"))
        name = source.get("configMapRef", {}).get("name")
        if "secretRef" in source or (namespace, name) not in configmaps:
            # An unread source can override any preceding envFrom key.
            values.clear()
            unresolved = True
        for key, value in configmaps.get((namespace, name), {}).items():
            values[source.get("prefix", "") + key] = value
    for variable in container.get("env", []):
        name = variable["name"]
        values.pop(name, None)
        if "value" in variable:
            values[name] = variable["value"]
        elif "configMapKeyRef" in variable.get("valueFrom", {}):
            reference = variable["valueFrom"]["configMapKeyRef"]
            data = configmaps.get((namespace, reference["name"]), {})
            if reference["key"] in data:
                values[name] = data[reference["key"]]
            else:
                unresolved = True
        if "valueFrom" in variable:
            references.append({"env": name, "valueFrom": variable["valueFrom"]})
            if "configMapKeyRef" not in variable["valueFrom"]:
                unresolved = True
    process_settings = {
        key: safe_process_value(value) for key, value in values.items() if key in PROCESS_ENV
    }
    # Shell wrappers are common; inspect only explicit numeric process flags.
    command = " ".join(container.get("command", []) + container.get("args", []))
    process_flags = {}
    for name, flags, value_pattern in (
        ("gunicorn_workers", r"--workers|-w", r"\d+"),
        ("worker_connections", r"--worker-connections", r"\d+"),
        ("celery_concurrency", r"--concurrency|-c", r"\d+"),
        ("celery_autoscale", r"--autoscale", r"\d+,\d+"),
        ("worker_pool", r"--pool|-P", r"prefork|gevent|eventlet|threads|solo"),
    ):
        match = re.search(r"(?:^|\s)(?:" + flags + r")(?:=|\s+)(" + value_pattern + r")(?=\s|$)", command)
        if match:
            process_flags[name] = match.group(1)
    matches = []
    for name, value in values.items():
        if re.search(r"(?:DOCDB|MONGO).*(?:HOST|URL|URI|DSN|ENDPOINT)", name, re.I):
            for endpoint in endpoint_matches(value, endpoints):
                matches.append({"variable": name, "endpoint": endpoint})
    for endpoint in endpoint_matches(command, endpoints):
        matches.append({"source": "command_or_args", "endpoint": endpoint})
    return {
        "name": container["name"],
        "image": container.get("image"),
        "process_settings": process_settings,
        "explicit_process_flags": process_flags,
        "environment_references": references,
        "endpoint_matches": matches,
        "unresolved_environment_sources": unresolved,
    }


def workload_summary(item, autoscalers, configmaps, endpoints):
    metadata, spec = item["metadata"], item.get("spec", {})
    kind, namespace = item["kind"], metadata.get("namespace", "default")
    pod_spec = spec
    if kind == "CronJob":
        pod_spec = spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    elif kind != "Pod":
        pod_spec = spec.get("template", {}).get("spec", {})
    scaling = autoscalers.get((namespace, kind, metadata["name"]), [])
    maximums = [entry["maxReplicas"] for entry in scaling if entry.get("maxReplicas") is not None]
    replicas = spec.get("replicas", 1) if kind in {"Deployment", "StatefulSet"} else None
    maximum = max([replicas] + maximums) if replicas is not None else None
    strategy = spec.get("strategy", spec.get("updateStrategy", {}))
    rollout_target = None
    if kind == "Deployment":
        surge = strategy.get("rollingUpdate", {}).get("maxSurge", "25%")
        if strategy.get("type", "RollingUpdate") == "Recreate":
            surge = 0
        surge_count = math.ceil(maximum * int(surge[:-1]) / 100) if isinstance(surge, str) and surge.endswith("%") else int(surge)
        rollout_target = maximum + surge_count
    return {
        "kind": kind, "namespace": namespace, "name": metadata["name"],
        "owners": [select(owner, "kind", "name") for owner in metadata.get("ownerReferences", [])],
        "deletion_timestamp": metadata.get("deletionTimestamp"),
        "replicas": replicas,
        "observed_status": select(item.get("status", {}), "replicas", "readyReplicas", "availableReplicas", "currentReplicas", "desiredNumberScheduled", "active", "phase", "terminatingReplicas"),
        "autoscalers": scaling,
        "configured_replica_max_including_current_desired": maximum,
        "rollout_strategy": strategy,
        "nonterminating_rollout_target_at_configured_max": rollout_target,
        "termination_grace_period_seconds": pod_spec.get("terminationGracePeriodSeconds", 30),
        "job_settings": select(spec, "parallelism", "completions", "schedule", "concurrencyPolicy", "suspend", "startingDeadlineSeconds"),
        "containers": [
            {**container_summary(container, configmaps, namespace, endpoints),
             "container_role": role, "restart_policy": container.get("restartPolicy")}
            for role, containers in (("application", pod_spec.get("containers", [])),
                                     ("init", pod_spec.get("initContainers", [])))
            for container in containers
        ],
    }


class Collector:
    def __init__(self, cluster_name):
        self.cluster_name = cluster_name
        self.errors = []
        self.end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.start = self.end - timedelta(days=7)

    def optional(self, label, callback, default=None):
        try:
            return callback()
        except CollectionError as error:
            self.errors.append({"collection": label, "reason": str(error)})
            print("Could not collect {}: {}".format(label, error), file=sys.stderr)
            return default

    def instance_metrics(self, identifier):
        metrics = {}
        for name, statistic in METRICS.items():
            response = self.optional(
                "cloudwatch/{}/{}".format(identifier, name),
                lambda: aws(
                    "cloudwatch", "get-metric-statistics", "--namespace", "AWS/DocDB",
                    "--metric-name", name, "--dimensions",
                    json.dumps([{"Name": "DBInstanceIdentifier", "Value": identifier}]),
                    "--start-time", self.start.isoformat(), "--end-time", self.end.isoformat(),
                    "--period", "600", "--statistics", statistic,
                ),
            )
            metrics[name] = metric_summary(response, statistic) if response is not None else None
        return metrics

    def dms_consumers(self, endpoints):
        response = self.optional("dms/endpoints", lambda: aws("dms", "describe-endpoints"))
        if response is None:
            return None
        matches = []
        for endpoint in response.get("Endpoints", []):
            matched = endpoint_matches(endpoint.get("ServerName", ""), endpoints)
            if matched or endpoint.get("EngineName") in {"docdb", "mongodb"}:
                matches.append({
                    **select(endpoint, "EndpointIdentifier", "EndpointArn", "EndpointType", "EngineName", "DatabaseName", "Status"),
                    "matching_cluster_endpoints": matched,
                    "relationship": "endpoint_match" if matched else "unverified_mongo_candidate",
                })
        tasks = self.optional("dms/tasks", lambda: aws("dms", "describe-replication-tasks", "--without-settings")) if matches else None
        arns = {endpoint["EndpointArn"] for endpoint in matches}
        return {
            "endpoints": matches,
            "tasks": [
                select(task, "ReplicationTaskIdentifier", "ReplicationTaskArn", "SourceEndpointArn", "TargetEndpointArn", "ReplicationInstanceArn", "Status", "MigrationType")
                for task in (tasks or {}).get("ReplicationTasks", [])
                if task.get("SourceEndpointArn") in arns or task.get("TargetEndpointArn") in arns
            ] if tasks is not None else None,
        }

    def eks_consumers(self, endpoints):
        response = self.optional("eks/list-clusters", lambda: aws("eks", "list-clusters"))
        if response is None:
            return None
        reports = []
        for name in response.get("clusters", []):
            data = self.optional("eks/" + name, lambda: aws("eks", "describe-cluster", "--name", name))
            if data is None:
                continue
            cluster = data["cluster"]
            report = select(cluster, "name", "arn", "version", "status")
            report["vpc_id"] = cluster.get("resourcesVpcConfig", {}).get("vpcId")
            report["workloads"] = None
            reports.append(report)
            if not shutil.which("kubectl"):
                self.errors.append({"collection": "eks/" + name + "/workloads", "reason": "kubectl_not_installed"})
                continue
            # Build a temporary context from AWS discovery; never use or modify ~/.kube/config.
            with tempfile.TemporaryDirectory(prefix="docdb-capacity-") as temporary:
                kubeconfig = Path(temporary) / "config.json"
                kubeconfig.write_text(json.dumps({
                    "apiVersion": "v1", "kind": "Config", "current-context": "inventory",
                    "clusters": [{"name": "inventory", "cluster": {
                        "server": cluster["endpoint"],
                        "certificate-authority-data": cluster["certificateAuthority"]["data"],
                    }}],
                    "contexts": [{"name": "inventory", "context": {"cluster": "inventory", "user": "inventory"}}],
                    "users": [{"name": "inventory", "user": {"exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "aws", "args": ["eks", "get-token", "--cluster-name", name, "--output", "json"],
                        "interactiveMode": "Never",
                    }}}],
                }))
                kubeconfig.chmod(0o600)
                command = ["kubectl", "--kubeconfig", str(kubeconfig), "--cache-dir", str(Path(temporary) / "cache"), "--request-timeout=15s"]
                available = self.optional("eks/" + name + "/access", lambda: run_json(command + ["get", "--raw=/version"]))
                if available is None:
                    continue
                resources = {}
                for resource in KUBE_RESOURCES:
                    data = self.optional(
                        "eks/" + name + "/" + resource,
                        lambda: run_json(command + ["get", resource, "--all-namespaces", "-o", "json"]),
                    )
                    resources[resource] = (data or {}).get("items", [])
                configmaps = {
                    (item["metadata"].get("namespace", "default"), item["metadata"]["name"]): item.get("data", {})
                    for item in resources.pop("configmaps")
                }
                autoscalers = {}
                for item in resources.pop("horizontalpodautoscalers.autoscaling"):
                    target = item["spec"]["scaleTargetRef"]
                    key = (item["metadata"].get("namespace", "default"), target["kind"], target["name"])
                    autoscalers.setdefault(key, []).append({
                        "name": item["metadata"]["name"],
                        **select(item["spec"], "minReplicas", "maxReplicas"),
                        "status": select(item.get("status", {}), "currentReplicas", "desiredReplicas"),
                    })
                report["workloads"] = [
                    workload_summary(item, autoscalers, configmaps, endpoints)
                    for items in resources.values() for item in items
                ]
        return reports

    def collect(self):
        caller = aws("sts", "get-caller-identity")
        response = aws("docdb", "describe-db-clusters", "--db-cluster-identifier", self.cluster_name)
        clusters = response.get("DBClusters", [])
        if len(clusters) != 1:
            raise CollectionError("expected_exactly_one_cluster")
        cluster = clusters[0]
        arn = cluster["DBClusterArn"].split(":")
        if arn[4] != caller["Account"]:
            raise CollectionError("cluster_account_does_not_match_active_identity")
        instances = []
        endpoints = {cluster[key].lower() for key in ("Endpoint", "ReaderEndpoint") if cluster.get(key)}
        for member in cluster.get("DBClusterMembers", []):
            identifier = member["DBInstanceIdentifier"]
            data = self.optional("docdb/" + identifier, lambda: aws("docdb", "describe-db-instances", "--db-instance-identifier", identifier))
            instance = (data or {}).get("DBInstances", [{}])[0]
            if instance.get("Endpoint", {}).get("Address"):
                endpoints.add(instance["Endpoint"]["Address"].lower())
            instances.append({
                "identifier": identifier,
                "is_writer": member.get("IsClusterWriter"),
                "promotion_tier": member.get("PromotionTier"),
                "configuration": select(instance, "DBInstanceArn", "DBInstanceClass", "DBInstanceStatus", "EngineVersion", "AvailabilityZone", "Endpoint", "PerformanceInsightsEnabled"),
                "vpc_id": instance.get("DBSubnetGroup", {}).get("VpcId"),
                "metrics": self.instance_metrics(identifier),
            })
        security_groups = []
        for group in cluster.get("VpcSecurityGroups", []):
            group_id = group["VpcSecurityGroupId"]
            data = self.optional("ec2/" + group_id, lambda: aws("ec2", "describe-security-groups", "--group-ids", group_id))
            security_groups.extend(
                select(entry, "GroupId", "GroupName", "OwnerId", "VpcId", "IpPermissions")
                for entry in (data or {}).get("SecurityGroups", [])
            )
        return {
            "schema_version": 1,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "account_id": caller["Account"], "caller_arn": caller["Arn"], "region": arn[3],
            "metric_window": {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": 7, "period_seconds": 600},
            "cluster": select(cluster, "DBClusterIdentifier", "DBClusterArn", "Status", "Engine", "EngineVersion", "Endpoint", "ReaderEndpoint", "Port", "AvailabilityZones", "StorageType", "ServerlessV2ScalingConfiguration"),
            "instances": instances,
            "security_groups": security_groups,
            "dms_consumers": self.dms_consumers(endpoints),
            "eks_clusters": self.eks_consumers(endpoints),
            "collection_errors": self.errors,
            "budget_ready": False,
            "remaining_inputs": [
                "Confirm which inventoried workloads use this cluster; an endpoint match is evidence, a missing match is not proof of non-use.",
                "Confirm effective per-process Mongo aliases, client options and pool limits from application configuration; secret values and image files are not read.",
                "Confirm process counts absent from explicit environment/flags, including Celery pool type, Gunicorn preloading and worker-recycling overlap.",
                "Include terminating pods and overlapping CronJob/Job runs; replicas plus maxSurge is not a strict upper bound on all live processes.",
                "Workload templates and observed Pods describe the same consumers at different levels; do not sum both. Init containers and restartable sidecars need separate lifecycle treatment.",
                "Confirm consumers in other accounts/regions, non-EKS compute (ECS, Lambda, EC2, Batch), serverless DMS and external/manual clients. Discovery covers only the current account and configured region.",
                "Choose per-instance operating headroom and monitoring allowance, including failover and rolling deployment, before assigning per-process pools.",
            ],
            "metric_notes": [
                "DatabaseConnectionsMax preserves the one-minute connection peak within each ten-minute Maximum bucket; DatabaseConnections is the sampled gauge.",
                "DatabaseConnectionsLimit uses Minimum within each bucket. Missing samples are unknown, never zero; no instance-class quota is hardcoded.",
                "Limits and usage are per instance. Do not sum the writer and reader limits into a single shared pool budget.",
                "Different metric extrema may have occurred at different times. Use timestamped samples when comparing pressure and resource exhaustion.",
            ],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cluster", help="DocumentDB cluster identifier in the active AWS account/region")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,62}", args.cluster):
        parser.error("cluster must be a DocumentDB cluster identifier")
    try:
        report = Collector(args.cluster).collect()
    except CollectionError as error:
        print("Collection failed: {}. Check the active AWS login, default region and cluster name.".format(error), file=sys.stderr)
        return 1
    json.dump(report, sys.stdout, indent=2)
    print()
    if report["collection_errors"]:
        print("Report contains collection gaps; see collection_errors.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
