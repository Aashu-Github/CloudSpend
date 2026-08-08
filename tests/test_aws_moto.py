from __future__ import annotations

import pytest

moto = pytest.importorskip("moto")
from moto import mock_aws
import boto3

from cloudspend.config import Settings
from cloudspend.providers.aws_live import AwsProvider


@mock_aws
def test_live_provider_moto_inventory(monkeypatch):
    session = boto3.Session(region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    ec2 = session.client("ec2", region_name="us-east-1")
    result = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    instance_id = result["Instances"][0]["InstanceId"]
    ec2.create_volume(AvailabilityZone="us-east-1a", Size=8, VolumeType="gp3")

    provider = AwsProvider(session=session, regions=["us-east-1"], settings=Settings())
    monkeypatch.setattr(provider, "_load_cost_summary", lambda *a, **k: ({"ResultsByTime": []}, ["account cost stubbed in Moto test"]))
    monkeypatch.setattr(provider, "_load_metrics", lambda *a, **k: ({"MetricDataResults": []}, {}, ["metrics stubbed in Moto test"]))
    monkeypatch.setattr(provider, "_load_resource_cost", lambda *a, **k: ({"ResultsByTime": []}, ["cost stubbed in Moto test"]))
    loaded = provider.load()
    assert any(r.resource_id == instance_id for r in loaded.resources)
    assert any(r.resource_type == "ebs_volume" for r in loaded.resources)
