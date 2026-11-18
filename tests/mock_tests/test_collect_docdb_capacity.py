import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import collect_docdb_capacity as inventory


CLUSTER = {
    "DBClusterIdentifier": "example-docdb",
    "DBClusterArn": "arn:aws:rds:eu-west-1:123456789012:cluster:example-docdb",
    "Endpoint": "example.cluster-abc.eu-west-1.docdb.amazonaws.com",
    "ReaderEndpoint": "example.cluster-ro-abc.eu-west-1.docdb.amazonaws.com",
    "DBClusterMembers": [{"DBInstanceIdentifier": "example-1", "IsClusterWriter": True}],
    "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-docdb"}],
}


def aws_response(service, operation, *args):
    responses = {
        ("sts", "get-caller-identity"): {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/readonly/user"},
        ("docdb", "describe-db-clusters"): {"DBClusters": [CLUSTER]},
        ("docdb", "describe-db-instances"): {"DBInstances": [{
            "DBInstanceClass": "db.t3.medium", "DBSubnetGroup": {"VpcId": "vpc-db"},
            "Endpoint": {"Address": "example-1.abc.eu-west-1.docdb.amazonaws.com"},
        }]},
        ("ec2", "describe-security-groups"): {"SecurityGroups": [{
            "GroupId": "sg-docdb", "IpPermissions": [{"UserIdGroupPairs": [{"UserId": "999999999999", "GroupId": "sg-peer"}]}],
        }]},
        ("dms", "describe-endpoints"): {"Endpoints": [{
            "EndpointIdentifier": "feed", "EndpointArn": "arn:endpoint:feed",
            "EngineName": "docdb", "ServerName": CLUSTER["Endpoint"],
            "Password": "must-not-appear", "Username": "also-not-needed",
        }]},
        ("dms", "describe-replication-tasks"): {"ReplicationTasks": [{
            "ReplicationTaskIdentifier": "feed-task", "SourceEndpointArn": "arn:endpoint:feed", "Status": "running",
            "TableMappings": "must-not-appear",
        }]},
        ("eks", "list-clusters"): {"clusters": []},
    }
    if service == "cloudwatch":
        statistic = args[args.index("--statistics") + 1]
        name = args[args.index("--metric-name") + 1]
        value = 1000 if name == "DatabaseConnectionsLimit" else 800
        return {"Datapoints": [{"Timestamp": "2026-11-18T10:00:00Z", statistic: value, "Unit": "Count"}]}
    return responses[(service, operation)]


class TestCapacityCollection(unittest.TestCase):
    def test_report_keeps_account_scope_metric_extrema_and_consumer_evidence(self):
        with patch.object(inventory, "aws", side_effect=aws_response) as aws:
            report = inventory.Collector("example-docdb").collect()
        self.assertEqual(report["account_id"], "123456789012")
        self.assertEqual(report["region"], "eu-west-1")
        self.assertFalse(report["budget_ready"])
        metrics = report["instances"][0]["metrics"]
        self.assertEqual(metrics["DatabaseConnectionsMax"]["maximum"]["value"], 800)
        self.assertEqual(metrics["DatabaseConnectionsLimit"]["minimum"]["value"], 1000)
        self.assertEqual(report["dms_consumers"]["endpoints"][0]["relationship"], "endpoint_match")
        self.assertEqual(report["dms_consumers"]["tasks"][0]["Status"], "running")
        self.assertEqual(report["security_groups"][0]["IpPermissions"][0]["UserIdGroupPairs"][0]["UserId"], "999999999999")
        self.assertNotIn("must-not-appear", json.dumps(report))
        self.assertEqual(report["eks_clusters"], [])
        for call in aws.call_args_list:
            self.assertNotIn("--profile", call.args)
            self.assertNotIn("--region", call.args)

    def test_missing_metrics_are_unknown_and_samples_remain_chronological(self):
        empty = inventory.metric_summary({"Datapoints": []}, "Maximum")
        self.assertIsNone(empty["maximum"])
        self.assertIsNone(empty["latest"])
        actual = inventory.metric_summary({"Datapoints": [
            {"Timestamp": "2026-11-18T11:00:00Z", "Maximum": 0},
            {"Timestamp": "2026-11-18T10:00:00Z", "Maximum": 999},
        ]}, "Maximum")
        self.assertEqual(actual["latest"]["value"], 0)
        self.assertEqual(actual["maximum"]["timestamp"], "2026-11-18T10:00:00Z")

    def test_optional_denial_writes_partial_report_and_nonzero_exit(self):
        def denied(service, operation, *args):
            if service == "eks":
                raise inventory.CollectionError("access_denied")
            return aws_response(service, operation, *args)
        output = io.StringIO()
        with patch.object(inventory, "aws", side_effect=denied), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            status = inventory.main(["example-docdb"])
        self.assertEqual(status, 2)
        report = json.loads(output.getvalue())
        self.assertIsNone(report["eks_clusters"])
        self.assertEqual(report["collection_errors"], [{"collection": "eks/list-clusters", "reason": "access_denied"}])

    def test_wrong_account_stops_before_consumer_discovery(self):
        def wrong_account(service, operation, *args):
            if service == "sts":
                return {"Account": "000000000000", "Arn": "wrong-account"}
            return aws_response(service, operation, *args)
        output = io.StringIO()
        with patch.object(inventory, "aws", side_effect=wrong_account) as aws, contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            status = inventory.main(["example-docdb"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(aws.call_count, 2)

    def test_cli_inherits_aws_settings_and_does_not_expose_raw_errors(self):
        failure = subprocess.CompletedProcess([], 1, stdout="", stderr="AccessDenied: mongodb://admin:secret@example")
        with patch.object(inventory.subprocess, "run", return_value=failure) as run:
            with self.assertRaisesRegex(inventory.CollectionError, "^access_denied$"):
                inventory.aws("docdb", "describe-db-clusters", "--db-cluster-identifier", "example")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[:3], ["aws", "docdb", "describe-db-clusters"])
        self.assertNotIn("--profile", arguments)
        self.assertNotIn("--region", arguments)
        self.assertNotIn("--no-paginate", arguments)


class TestWorkloadEvidence(unittest.TestCase):
    def test_secret_envfrom_cannot_leave_a_stale_worker_count(self):
        maps = {("backend", "settings"): {"GUNICORN_WORKERS": "8"}}
        container = {"name": "api", "envFrom": [
            {"configMapRef": {"name": "settings"}}, {"secretRef": {"name": "credentials"}},
        ]}
        summary = inventory.container_summary(container, maps, "backend", set())
        self.assertEqual(summary["process_settings"], {})
        self.assertTrue(summary["unresolved_environment_sources"])
        container["env"] = [{"name": "GUNICORN_WORKERS", "value": "4"}]
        summary = inventory.container_summary(container, maps, "backend", set())
        self.assertEqual(summary["process_settings"]["GUNICORN_WORKERS"], "4")

    def test_kube_discovery_uses_temporary_aws_context_and_redacts_configuration(self):
        deployment = {
            "kind": "Deployment", "metadata": {"namespace": "backend", "name": "api"},
            "spec": {"replicas": 3, "strategy": {"rollingUpdate": {"maxSurge": "25%"}},
                     "template": {"spec": {"terminationGracePeriodSeconds": 150, "containers": [{
                         "name": "api", "image": "backend:123",
                         "args": ["gunicorn", "--workers", "8", "--password", "do-not-report-this"],
                         "envFrom": [{"configMapRef": {"name": "settings"}}],
                         "env": [{"name": "PASSWORD", "value": "do-not-report-this"}],
                     }]}}},
        }
        fixtures = {resource: {"items": []} for resource in inventory.KUBE_RESOURCES}
        fixtures["deployments.apps"] = {"items": [deployment]}
        fixtures["configmaps"] = {"items": [{"metadata": {"namespace": "backend", "name": "settings"}, "data": {
            "GUNICORN_WORKERS": "8", "MONGODB_URI": "mongodb://admin:do-not-report-this@" + CLUSTER["Endpoint"] + "/app",
            "PASSWORD": "do-not-report-this",
        }}]}
        fixtures["horizontalpodautoscalers.autoscaling"] = {"items": [{
            "metadata": {"namespace": "backend", "name": "api-hpa"},
            "spec": {"scaleTargetRef": {"kind": "Deployment", "name": "api"}, "maxReplicas": 9},
        }]}
        configuration_paths = []

        def eks(service, operation, *args):
            if operation == "list-clusters":
                return {"clusters": ["application-eks"]}
            return {"cluster": {"name": "application-eks", "endpoint": "https://discovered.eks.invalid", "certificateAuthority": {"data": "test-cert"}, "resourcesVpcConfig": {"vpcId": "vpc-app"}}}

        def kubectl(command):
            config_path = Path(command[command.index("--kubeconfig") + 1])
            configuration_paths.append(config_path)
            configuration = json.loads(config_path.read_text())
            self.assertEqual(configuration["clusters"][0]["cluster"]["server"], "https://discovered.eks.invalid")
            token = configuration["users"][0]["user"]["exec"]
            self.assertEqual(token["args"], ["eks", "get-token", "--cluster-name", "application-eks", "--output", "json"])
            self.assertEqual(command[command.index("get")], "get")
            if "--raw=/version" in command:
                return {"gitVersion": "test"}
            return fixtures[command[command.index("get") + 1]]

        with patch.object(inventory, "aws", side_effect=eks), patch.object(inventory, "run_json", side_effect=kubectl), patch.object(inventory.shutil, "which", return_value="/test/kubectl"):
            reports = inventory.Collector("example-docdb").eks_consumers({CLUSTER["Endpoint"]})
        summary = reports[0]["workloads"][0]
        self.assertEqual(summary["configured_replica_max_including_current_desired"], 9)
        self.assertEqual(summary["nonterminating_rollout_target_at_configured_max"], 12)
        self.assertEqual(summary["termination_grace_period_seconds"], 150)
        container = summary["containers"][0]
        self.assertEqual(container["process_settings"]["GUNICORN_WORKERS"], "8")
        self.assertEqual(container["explicit_process_flags"]["gunicorn_workers"], "8")
        self.assertEqual(container["endpoint_matches"], [{"variable": "MONGODB_URI", "endpoint": CLUSTER["Endpoint"]}])
        self.assertNotIn("do-not-report-this", json.dumps(reports))
        self.assertTrue(configuration_paths)
        self.assertTrue(all(not path.exists() for path in configuration_paths))


if __name__ == "__main__":
    unittest.main()
