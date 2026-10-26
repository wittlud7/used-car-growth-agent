from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

from engine import POLICY, VERSION, model_config
from evaluate import evaluate
from store import Store
from matching import INVENTORY, MODELS, match_buy, match_sell, parse_request, validate_query
from car_agent import CarAgent
from workflow import Workflow, CASES

ROOT = Path(__file__).parent


def create_handler(store, agent=None):
    agent = agent or CarAgent(store)
    workflow = Workflow(store, agent)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_json(self, data, status=200):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/state":
                    cfg = model_config()
                    return self.send_json({"leads": store.list(), "tasks": store.tasks(), "metrics": store.metrics(), "policy": POLICY, "config": {"llm_ready": cfg["ready"], "model": cfg["model"], "version": VERSION}})
                if path == "/api/agent":
                    cfg = model_config()
                    return self.send_json({"sessions": agent.sessions(), "config": {k: cfg[k] for k in ("ready", "model", "provider")}})
                if path.startswith("/api/agent/session/"):
                    return self.send_json(agent.public(path.rsplit("/", 1)[1]))
                if path == "/api/workflow":
                    return self.send_json({"jobs": workflow.list(), "examples": [{k: c[k] for k in ("name", "channel", "text")} for c in CASES], "ready": model_config()["ready"]})
                if path.startswith("/api/workflow/job/"):
                    return self.send_json(workflow.get(path.rsplit("/", 1)[1]))
                if path.startswith("/api/leads/"):
                    return self.send_json(store.get(path.rsplit("/", 1)[1]))
                if path == "/api/evaluation":
                    return self.send_json(evaluate())
                if path == "/api/matching":
                    return self.send_json({"history": store.matching_history(), "tasks": store.tasks(), "inventory": INVENTORY, "models": list(MODELS)})
                if path == "/api/export":
                    return self.send_json(dict(store.snapshot(), workflow_jobs=[workflow.get(j["id"]) for j in workflow.list()]))
                relative = "index.html" if path == "/" else unquote(path).lstrip("/")
                target = (ROOT / "web" / relative).resolve()
                if not target.is_relative_to((ROOT / "web").resolve()) or not target.is_file():
                    return self.send_json({"error": "页面不存在"}, 404)
                raw = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", (mimetypes.guess_type(target.name)[0] or "application/octet-stream") + "; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)

        def do_POST(self):
            try:
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    return self.send_json({"error": "不接受跨站写入"}, 403)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 512000:
                    raise ValueError("请求体过大或为空")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求必须是JSON对象")
                path = urlparse(self.path).path
                if path == "/api/workflow/start":
                    items = body.get("items")
                    if "ids" in body:
                        ids = body["ids"]
                        if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or any(not isinstance(i, str) for i in ids):
                            raise ValueError("请选择1至20条咨询")
                        items = [{k: store.get(i)[k] for k in ("name", "channel", "text")} for i in dict.fromkeys(ids)]
                    return self.send_json(workflow.start(items, body.get("mode", "agent"), parent=body.get("parent")))
                if path == "/api/workflow/benchmark":
                    return self.send_json(workflow.start(benchmark=True))
                if path == "/api/workflow/feedback":
                    return self.send_json(workflow.feedback(body))
                if path == "/api/workflow/cancel":
                    return self.send_json(workflow.cancel(body.get("job_id")))
                if path == "/api/agent/new":
                    return self.send_json(agent.create())
                if path == "/api/agent/chat":
                    return self.send_json(agent.chat(body.get("session_id"), body.get("message")))
                if path == "/api/agent/confirm":
                    return self.send_json(agent.confirm(body.get("session_id"), body.get("token"), body))
                if path == "/api/tasks/create":
                    return self.send_json(store.create_match_task(body.get("run_id"), body.get("candidate_id"), body.get("customer", ""), body.get("owner", ""), body.get("preferred_at", ""), body.get("note", "")))
                if path == "/api/tasks/update":
                    return self.send_json(store.update_match_task(body.get("id"), body.get("status"), body.get("version"), body.get("note", "")))
                if path == "/api/matching/parse":
                    return self.send_json(parse_request(body.get("text"), body.get("direction")))
                if path == "/api/matching/run":
                    query = validate_query(body)
                    result = match_buy(query) if query["direction"] == "buy" else match_sell(query, store.list())
                    return self.send_json(store.save_matching(result))
                if path == "/api/matching/shortlist":
                    return self.send_json(store.shortlist(body.get("id"), body.get("candidate_id")))
                if path == "/api/import":
                    items = body.get("items")
                    if not isinstance(items, list) or not 1 <= len(items) <= 100:
                        raise ValueError("每次导入1至100条")
                    # Validate the complete batch before writing any rows.
                    for item in items:
                        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("name", "channel", "text")):
                            raise ValueError("每条须包含name、channel、text文本字段")
                        if not 1 <= len(item["name"].strip()) <= 40 or not 1 <= len(item["channel"].strip()) <= 40 or not 2 <= len(item["text"].strip()) <= 4000:
                            raise ValueError("姓名渠道限40字，咨询限2至4000字")
                    ids, added = [], 0
                    for item in items:
                        lead_id, fresh = store.add(item["name"], item["channel"], item["text"])
                        ids.append(lead_id)
                        added += fresh
                    return self.send_json({"ids": ids, "added": added, "duplicates": len(items) - added})
                if path == "/api/seed":
                    return self.send_json({"added": store.seed()})
                if path == "/api/analyze":
                    ids = body.get("ids")
                    mode = body.get("mode", "rules")
                    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(x, str) for x in ids):
                        raise ValueError("请选择1至100条线索")
                    if mode == "llm" and len(ids) > 1:
                        raise ValueError("模型模式请逐条运行，以便观察轨迹和成本")
                    results = []
                    for lead_id in dict.fromkeys(ids):
                        try:
                            item = store.analyze(lead_id, mode)
                            results.append({"id": lead_id, "status": item["status"]})
                        except ValueError as exc:
                            results.append({"id": lead_id, "error": str(exc)})
                    return self.send_json({"results": results})
                if path == "/api/transition":
                    item = store.transition(body.get("id"), body.get("status"), body.get("version"), body.get("owner", ""), body.get("draft"), body.get("note", ""))
                    return self.send_json(item)
                self.send_json({"error": "接口不存在"}, 404)
            except (ValueError, TypeError, KeyError) as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception:
                self.send_json({"error": "处理失败，请稍后重试；未返回成功结果"}, 500)

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(ROOT / "data" / "leads.db"))
    args = parser.parse_args()
    store = Store(args.db)
    store.seed()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), create_handler(store))
    print(f"Local: http://127.0.0.1:{args.port} | synthetic data | v{VERSION}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
