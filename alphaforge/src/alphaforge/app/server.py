"""Local web application (FastAPI). Serves the UI and a JSON API on 127.0.0.1.

Long computations (generation, robustness, walk-forward) run as background
jobs in worker threads; the UI polls their progress. The numerical kernels
release the GIL when compiled with Numba.
"""

from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from .._jit import JIT_ENABLED
from ..data.bars import InstrumentSpec
from ..data.loader import DataError
from ..data.synthetic import make_bars
from ..engine.metrics import FITNESS
from ..engine.spec import BacktestConfig, Strategy
from ..export import TARGETS, export
from ..rules.library import TEMPLATE_LIST, categories
from ..search.generator import GeneratorConfig
from .. import services
from ..workspace import Workspace, new_id

STATIC = Path(__file__).parent / "static"


class Job:
    def __init__(self, kind: str, params: dict):
        self.id = new_id("job")
        self.kind = kind
        self.params = params
        self.status = "queued"
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: str | None = None
        self.created = time.time()
        self.cancel = threading.Event()

    def to_dict(self, with_result: bool = True) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "created": self.created,
        }
        if with_result:
            d["result"] = self.result
        return d


class StrategyRequest(BaseModel):
    dataset_id: str
    strategy: dict
    backtest: dict = {}


class GenerateRequest(BaseModel):
    dataset_id: str
    generator: dict = {}
    backtest: dict = {}


class RobustnessRequest(StrategyRequest):
    fitness: str = "profit_factor"
    quick: bool = False


class WalkForwardRequest(StrategyRequest):
    windows: int = 5
    is_fraction: float = 0.7
    anchored: bool = False
    fitness: str = "profit_factor"


class ExportRequest(BaseModel):
    strategy: dict
    target: str
    backtest: dict = {}
    dataset_id: str | None = None


class SyntheticRequest(BaseModel):
    name: str = "Synthetic"
    bars: int = 2500
    seed: int = 7
    mean_reversion: float = 0.0
    drift: float = 0.0002


class SaveStrategyRequest(BaseModel):
    dataset_id: str | None = None
    strategy: dict
    backtest: dict = {}
    note: str = ""
    metrics: dict | None = None


def create_app(workspace: Workspace | None = None, workers: int = 2) -> FastAPI:
    ws = workspace or Workspace()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="alphaforge-job")
    jobs: dict[str, Job] = {}
    app = FastAPI(title="AlphaForge", version=__version__)

    def submit(kind: str, params: dict, fn) -> dict:
        job = Job(kind, params)
        jobs[job.id] = job

        def runner():
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "cancelled" if job.cancel.is_set() else "done"
            except Exception as exc:  # surfaced to the UI
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()

        pool.submit(runner)
        return job.to_dict(with_result=False)

    def bars_for(ds_id: str):
        try:
            return ws.load_bars(ds_id)
        except KeyError:
            raise HTTPException(404, f"dataset {ds_id} not found")

    def parse_strategy(d: dict) -> Strategy:
        try:
            return Strategy.from_dict(d)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(422, f"invalid strategy: {exc}")

    @app.get("/api/info")
    def info():
        return {
            "version": __version__,
            "jit": JIT_ENABLED,
            "fitness": {k: v[0] for k, v in FITNESS.items()},
            "export_targets": {k: v[0] for k, v in TARGETS.items()},
            "categories": categories(),
            "templates": [{"id": t.id, "category": t.category, "description": t.description} for t in TEMPLATE_LIST],
            "workspace": str(ws.root),
            "generator_defaults": GeneratorConfig().to_dict(),
            "backtest_defaults": BacktestConfig().to_dict(),
        }

    # ---- datasets
    @app.get("/api/datasets")
    def list_datasets():
        return ws.datasets()

    @app.post("/api/datasets")
    async def upload_dataset(
        file: UploadFile = File(...),
        name: str = Form(""),
        symbol: str = Form("UNKNOWN"),
        point_value: float = Form(1.0),
        tick_size: float = Form(0.01),
        timezone: str = Form(""),
    ):
        content = await file.read()
        if len(content) > 200 * 1024 * 1024:
            raise HTTPException(413, "file larger than 200 MB")
        try:
            return ws.add_dataset(name or file.filename or symbol, content, InstrumentSpec(symbol, point_value, tick_size), timezone or None)
        except DataError as exc:
            raise HTTPException(422, str(exc))
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, f"could not read file: {exc}")

    @app.post("/api/datasets/synthetic")
    def synthetic(req: SyntheticRequest):
        if not 100 <= req.bars <= 200_000:
            raise HTTPException(422, "bars must be between 100 and 200000")
        b = make_bars(req.bars, seed=req.seed, mean_reversion=req.mean_reversion, drift=req.drift, symbol="SYNTH")
        return ws.add_bars(req.name, b)

    @app.get("/api/datasets/{ds_id}")
    def dataset(ds_id: str):
        try:
            meta = ws.dataset_meta(ds_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "dataset not found")
        b = bars_for(ds_id)
        step = max(1, len(b) // 1500)
        meta["preview"] = {"t": (b.time[::step] // 1_000_000_000).tolist(), "close": b.close[::step].tolist()}
        return meta

    @app.delete("/api/datasets/{ds_id}")
    def delete_dataset(ds_id: str):
        ws.delete_dataset(ds_id)
        return {"ok": True}

    # ---- synchronous backtest and export
    @app.post("/api/backtest")
    def run_backtest(req: StrategyRequest):
        b = bars_for(req.dataset_id)
        return services.run_backtest(b, parse_strategy(req.strategy), BacktestConfig.from_dict(req.backtest))

    @app.post("/api/export")
    def run_export(req: ExportRequest):
        inst = bars_for(req.dataset_id).instrument if req.dataset_id else None
        try:
            code = export(parse_strategy(req.strategy), req.target, BacktestConfig.from_dict(req.backtest), inst)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"target": req.target, "extension": TARGETS[req.target][1], "code": code}

    # ---- jobs
    @app.post("/api/jobs/generate")
    def start_generate(req: GenerateRequest):
        b = bars_for(req.dataset_id)
        try:
            gcfg = GeneratorConfig.from_dict(req.generator)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        bcfg = BacktestConfig.from_dict(req.backtest)

        def work(job: Job):
            def progress(p):
                job.progress = p

            res = services.run_generation(b, gcfg, bcfg, progress, job.cancel.is_set)
            res["dataset_id"] = req.dataset_id
            res["id"] = job.id.replace("job-", "run-")
            ws.save_run(res)
            return res

        return submit("generate", req.model_dump(), work)

    @app.post("/api/jobs/robustness")
    def start_robustness(req: RobustnessRequest):
        b = bars_for(req.dataset_id)
        s = parse_strategy(req.strategy)
        if req.fitness not in FITNESS:
            raise HTTPException(422, "unknown fitness")
        return submit("robustness", req.model_dump(), lambda job: services.run_robustness(b, s, BacktestConfig.from_dict(req.backtest), req.fitness, req.quick))

    @app.post("/api/jobs/walkforward")
    def start_walkforward(req: WalkForwardRequest):
        b = bars_for(req.dataset_id)
        s = parse_strategy(req.strategy)

        def work(job):
            return services.run_walk_forward(b, s, BacktestConfig.from_dict(req.backtest), windows=req.windows, is_fraction=req.is_fraction, anchored=req.anchored, fitness=req.fitness)

        return submit("walkforward", req.model_dump(), work)

    @app.get("/api/jobs")
    def list_jobs():
        return [j.to_dict(with_result=False) for j in sorted(jobs.values(), key=lambda j: j.created, reverse=True)]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        return jobs[job_id].to_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        jobs[job_id].cancel.set()
        return {"ok": True}

    # ---- runs and saved strategies
    @app.get("/api/runs")
    def runs():
        return ws.runs()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        try:
            return ws.run(run_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "run not found")

    @app.get("/api/strategies")
    def strategies():
        return ws.strategies()

    @app.post("/api/strategies")
    def save_strategy(req: SaveStrategyRequest):
        parse_strategy(req.strategy)
        return ws.save_strategy(req.model_dump())

    @app.delete("/api/strategies/{sid}")
    def delete_strategy(sid: str):
        ws.delete_strategy(sid)
        return {"ok": True}

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
