import time

import pytest
from fastapi.testclient import TestClient

from alphaforge.app.server import create_app
from alphaforge.workspace import Workspace


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(Workspace(tmp_path)))


def wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise TimeoutError


def test_end_to_end(client):
    info = client.get("/api/info").json()
    assert "python" in info["export_targets"]
    ds = client.post("/api/datasets/synthetic", json={"bars": 1200, "seed": 4, "mean_reversion": 0.1}).json()
    assert client.get(f"/api/datasets/{ds['id']}").json()["preview"]["close"]
    job = client.post("/api/jobs/generate", json={"dataset_id": ds["id"], "generator": {"population": 20, "generations": 2, "min_trades_is": 10, "min_trades_oos": 0, "quantity": 100}}).json()
    j = wait(client, job["id"])
    assert j["status"] == "done", j["error"]
    res = j["result"]["results"]
    assert res and 0 <= res[0]["selection"]["dsr"] <= 1
    strat = res[0]["strategy"]
    bt = client.post("/api/backtest", json={"dataset_id": ds["id"], "strategy": strat}).json()
    assert bt["metrics"]["all"]["trades"] == len(bt["trades"])
    code = client.post("/api/export", json={"strategy": strat, "target": "pine", "dataset_id": ds["id"]}).json()["code"]
    assert "strategy(" in code
    rob = wait(client, client.post("/api/jobs/robustness", json={"dataset_id": ds["id"], "strategy": strat, "quick": True}).json()["id"])
    assert rob["status"] == "done", rob["error"]
    saved = client.post("/api/strategies", json={"dataset_id": ds["id"], "strategy": strat}).json()
    assert client.get("/api/strategies").json()[0]["id"] == saved["id"]
    assert client.get("/api/runs").json()


def test_upload_validation(client):
    bad = client.post("/api/datasets", files={"file": ("x.csv", b"a,b\n1,2\n")}, data={"symbol": "X"})
    assert bad.status_code == 422
    good = client.post("/api/datasets", files={"file": ("x.csv", b"Date,Open,High,Low,Close\n2024-01-02,1,2,0.5,1.5\n2024-01-03,1.5,2,1,1.8\n2024-01-04,1.8,2,1.5,1.9\n")}, data={"symbol": "X"})
    assert good.status_code == 200 and good.json()["report"]["rows"] == 3


def test_invalid_strategy_rejected(client):
    ds = client.post("/api/datasets/synthetic", json={"bars": 300}).json()
    r = client.post("/api/backtest", json={"dataset_id": ds["id"], "strategy": {"direction": "up", "entry": [], "exits": {}}})
    assert r.status_code == 422
    assert client.get("/api/datasets/../../etc").status_code in (404, 422)
