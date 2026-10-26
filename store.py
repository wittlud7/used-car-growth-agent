from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine import ModelFailure, run_model, run_rules
from fixtures import CASES
from matching import match_buy, match_sell

TRANSITIONS = {"pending": {"approved", "rejected"}, "approved": {"contacted", "rejected"}, "contacted": {"appointment", "lost"}, "appointment": {"won", "lost"}}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, channel TEXT NOT NULL, text TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', result TEXT,
                draft TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, at TEXT NOT NULL, mode TEXT NOT NULL,
                ok INTEGER NOT NULL, result TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS matching_runs (
                id TEXT PRIMARY KEY, at TEXT NOT NULL, direction TEXT NOT NULL,
                result TEXT NOT NULL, shortlist TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS match_tasks (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                direction TEXT NOT NULL, customer TEXT NOT NULL, owner TEXT NOT NULL,
                preferred_at TEXT NOT NULL, note TEXT NOT NULL, snapshot TEXT NOT NULL,
                lead_id TEXT, status TEXT NOT NULL DEFAULT 'pending', version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(run_id,candidate_id)
            );
            CREATE TABLE IF NOT EXISTS match_task_events (
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, at TEXT NOT NULL,
                status TEXT NOT NULL, note TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                state TEXT NOT NULL, messages TEXT NOT NULL, turns TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0
            );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, name, channel, text):
        for value in (name, channel, text):
            if not isinstance(value, str):
                raise ValueError("姓名、渠道和咨询须为文本")
        name, channel, text = name.strip(), channel.strip(), text.strip()
        if not name or len(name) > 40 or not channel or len(channel) > 40 or not 2 <= len(text) <= 4000:
            raise ValueError("姓名和渠道限40字，咨询限2至4000字")
        lead_id = hashlib.sha256((name + "\0" + channel + "\0" + text).encode()).hexdigest()[:16]
        with self.connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO leads(id,name,channel,text,created_at) VALUES(?,?,?,?,?)", (lead_id, name, channel, text, now()))
            if cursor.rowcount:
                db.execute("INSERT INTO events(lead_id,at,kind,detail) VALUES(?,?,?,?)", (lead_id, now(), "import", "导入咨询；未联系客户"))
        return lead_id, bool(cursor.rowcount)

    def seed(self):
        return sum(self.add(c["name"], c["channel"], c["text"])[1] for c in CASES if c["split"] == "demo")

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM leads ORDER BY created_at,id").fetchall()
        return [self.decode(r) for r in rows]

    @staticmethod
    def decode(row):
        data = dict(row)
        data["result"] = json.loads(data["result"]) if data["result"] else None
        return data

    def get(self, lead_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            if not row:
                raise ValueError("线索不存在")
            item = self.decode(row)
            item["events"] = [dict(x) for x in db.execute("SELECT at,kind,detail FROM events WHERE lead_id=? ORDER BY id", (lead_id,))]
            item["runs"] = [dict(x) for x in db.execute("SELECT id,at,mode,ok,result FROM runs WHERE lead_id=? ORDER BY at,rowid", (lead_id,))]
            for run in item["runs"]:
                run["result"] = json.loads(run["result"])
        return item

    def analyze(self, lead_id, mode):
        if mode not in {"rules", "llm"}:
            raise ValueError("未知运行方式")
        lead = self.get(lead_id)
        if lead["status"] not in {"new", "pending", "failed"}:
            raise ValueError("已审核的线索不允许重新分析覆盖")
        run_id = uuid.uuid4().hex
        try:
            result = run_rules(lead["text"]) if mode == "rules" else run_model(lead["text"])
            result["run_id"] = run_id
            ok = True
        except ModelFailure as exc:
            result = {"error": str(exc), "trace": exc.trace, "usage": exc.usage, "mode": mode, "run_id": run_id}
            ok = False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT version FROM leads WHERE id=?", (lead_id,)).fetchone()
            if current["version"] != lead["version"]:
                raise ValueError("线索在运行期间已被修改，请刷新后重试")
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (run_id, lead_id, now(), mode, int(ok), json.dumps(result, ensure_ascii=False)))
            # Failed model calls must never masquerade as a successful rule or model run.
            db.execute("UPDATE leads SET status=?, result=?, draft=?, version=version+1 WHERE id=?", ("pending" if ok else "failed", json.dumps(result, ensure_ascii=False), result.get("draft", ""), lead_id))
            db.execute("INSERT INTO events(lead_id,at,kind,detail) VALUES(?,?,?,?)", (lead_id, now(), "analysis" if ok else "failure", "规则基线生成待审核草稿" if mode == "rules" and ok else ("模型工具流程生成待审核草稿" if ok else result["error"])))
        return self.get(lead_id)

    def transition(self, lead_id, status, version, owner="", draft=None, note=""):
        if not isinstance(owner, str) or not isinstance(note, str) or len(owner) > 40 or len(note) > 2000:
            raise ValueError("负责人或备注格式不正确")
        if draft is not None and (not isinstance(draft, str) or not 1 <= len(draft.strip()) <= 3000):
            raise ValueError("草稿须为1至3000字")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            if not row:
                raise ValueError("线索不存在")
            lead = self.decode(row)
            if type(version) is not int or version != lead["version"]:
                raise ValueError("页面版本已过期，请刷新后重试")
            if status not in TRANSITIONS.get(lead["status"], set()):
                raise ValueError("不允许跳过审核或跟进阶段")
            if status == "approved":
                if lead["result"]["decision"]["stop_contact"]:
                    raise ValueError("拒绝联系的线索不能批准主动跟进，请驳回归档")
                if not owner.strip():
                    raise ValueError("通过审核前请填写负责人")
            if status in {"contacted", "appointment", "won", "lost", "rejected"} and not note.strip():
                raise ValueError("请填写实际跟进结果或驳回原因")
            new_draft = draft.strip() if draft is not None and status == "approved" else lead["draft"]
            new_owner = owner.strip() if status == "approved" else lead["owner"]
            db.execute("UPDATE leads SET status=?,owner=?,draft=?,version=version+1 WHERE id=?", (status, new_owner, new_draft, lead_id))
            detail = json.dumps({"from": lead["status"], "to": status, "owner": new_owner, "note": note.strip(), "draft_edited": new_draft != lead["draft"]}, ensure_ascii=False)
            db.execute("INSERT INTO events(lead_id,at,kind,detail) VALUES(?,?,?,?)", (lead_id, now(), "human_review" if status in {"approved", "rejected"} else "human_outcome", detail))
        return self.get(lead_id)

    def snapshot(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,created_at,updated_at,state,turns,version FROM agent_sessions ORDER BY created_at").fetchall()
        sessions = [{**dict(r), "state": json.loads(r["state"]), "turns": json.loads(r["turns"])} for r in rows]
        return {"exported_at": now(), "data_notice": "本项目初始化数据为合成咨询。后续导入数据来源由使用者标注。", "leads": [self.get(lead["id"]) for lead in self.list()], "matching": self.matching_history(), "tasks": self.tasks(), "agent_sessions": sessions}

    def tasks(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM match_tasks ORDER BY created_at DESC,rowid DESC").fetchall()
            events = db.execute("SELECT task_id,at,status,note FROM match_task_events ORDER BY id").fetchall()
        result = []
        for row in rows:
            task = dict(row)
            task["snapshot"] = json.loads(task["snapshot"])
            task["events"] = [dict(e) for e in events if e["task_id"] == task["id"]]
            result.append(task)
        return result

    def get_task(self, task_id):
        task = next((t for t in self.tasks() if t["id"] == task_id), None)
        if task is None:
            raise ValueError("待办不存在")
        return task

    @staticmethod
    def task_text(value, label, limit, required=False):
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise ValueError(f"请正确填写{label}，最多{limit}字")
        return value.strip()

    def create_match_task(self, run_id, candidate_id, customer, owner, preferred_at="", note=""):
        owner = self.task_text(owner, "负责人", 40, True)
        customer = self.task_text(customer, "客户称呼", 40)
        note = self.task_text(note, "备注", 2000)
        preferred_at = self.task_text(preferred_at, "期望时间", 40)
        if preferred_at:
            try:
                moment = datetime.fromisoformat(preferred_at)
            except ValueError:
                raise ValueError("期望时间格式不正确") from None
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone(timedelta(hours=8)))
            preferred_at = moment.isoformat(timespec="minutes")
        record = self.get_matching(run_id)
        query = record["result"]["query"]
        # Recheck current inventory/lead eligibility instead of trusting an old matching snapshot.
        fresh = match_buy(query) if record["direction"] == "buy" else match_sell(query, self.list())
        candidate = next((m for m in fresh["matches"] if m["id"] == candidate_id), None)
        if candidate_id not in {m["id"] for m in record["result"]["matches"]} or candidate is None:
            raise ValueError("候选项已不符合条件，请重新匹配")
        lead_id = None
        if record["direction"] == "sell":
            customer = candidate["buyer"]["name"]
            lead_id = candidate_id
        elif not customer:
            raise ValueError("请填写看车客户称呼")
        task_id = uuid.uuid4().hex
        snapshot = {"query": query, "candidate": candidate}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM match_tasks WHERE run_id=? AND candidate_id=?", (run_id, candidate_id)).fetchone()
            if existing:
                task_id = existing["id"]
            else:
                db.execute("INSERT INTO match_tasks(id,run_id,candidate_id,direction,customer,owner,preferred_at,note,snapshot,lead_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (task_id, run_id, candidate_id, record["direction"], customer, owner, preferred_at, note, json.dumps(snapshot, ensure_ascii=False), lead_id, now(), now()))
                db.execute("INSERT INTO match_task_events(task_id,at,status,note) VALUES(?,?,?,?)", (task_id, now(), "pending", "建立本地待办，尚未确认或联系"))
                selected = json.loads(db.execute("SELECT shortlist FROM matching_runs WHERE id=?", (run_id,)).fetchone()["shortlist"])
                if candidate_id not in selected:
                    selected.append(candidate_id)
                db.execute("UPDATE matching_runs SET shortlist=? WHERE id=?", (json.dumps(selected), run_id))
        return self.get_task(task_id)

    def update_match_task(self, task_id, status, version, note):
        note = self.task_text(note, "操作记录", 2000, True)
        allowed = {"pending": {"confirmed", "cancelled"}, "confirmed": {"completed", "cancelled"}}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM match_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("待办不存在")
            task = dict(row)
            if type(version) is not int or version != task["version"]:
                raise ValueError("待办已被修改，请刷新后重试")
            if status not in allowed.get(task["status"], set()):
                raise ValueError("不允许跳过确认步骤或修改已结束待办")
            if task["direction"] == "sell" and status in {"confirmed", "completed"}:
                lead_row = db.execute("SELECT * FROM leads WHERE id=?", (task["lead_id"],)).fetchone()
                if not lead_row:
                    raise ValueError("买家咨询已不存在")
                lead = self.decode(lead_row)
                eligible = match_sell(json.loads(task["snapshot"])["query"], [lead])["matches"]
                if not eligible:
                    raise ValueError("买家已不符合条件，请取消待办并重新匹配")
                if lead["status"] not in {"approved", "contacted", "appointment"}:
                    raise ValueError("请先审核通过买家咨询，再确认跟进待办")
                if status == "completed" and lead["status"] == "approved":
                    db.execute("UPDATE leads SET status='contacted',version=version+1 WHERE id=?", (lead["id"],))
                    detail = json.dumps({"from": "approved", "to": "contacted", "owner": task["owner"], "note": note, "task_id": task_id}, ensure_ascii=False)
                    db.execute("INSERT INTO events(lead_id,at,kind,detail) VALUES(?,?,?,?)", (lead["id"], now(), "human_outcome", detail))
            elif task["direction"] == "buy" and status == "confirmed":
                query = json.loads(task["snapshot"])["query"]
                if task["candidate_id"] not in {m["id"] for m in match_buy(query)["matches"]}:
                    raise ValueError("车源已不可匹配，请取消待办并重新匹配")
            db.execute("UPDATE match_tasks SET status=?,version=version+1,updated_at=? WHERE id=?", (status, now(), task_id))
            db.execute("INSERT INTO match_task_events(task_id,at,status,note) VALUES(?,?,?,?)", (task_id, now(), status, note))
        return self.get_task(task_id)

    def save_matching(self, result):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO matching_runs(id,at,direction,result) VALUES(?,?,?,?)", (run_id, now(), result["direction"], json.dumps(result, ensure_ascii=False)))
        return self.get_matching(run_id)

    def get_matching(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM matching_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("匹配记录不存在")
        record = dict(row)
        record["result"] = json.loads(record["result"])
        record["shortlist"] = json.loads(record["shortlist"])
        return record

    def matching_history(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,at,direction,result,shortlist FROM matching_runs ORDER BY at DESC,rowid DESC LIMIT 30").fetchall()
        return [{**dict(row), "result": json.loads(row["result"]), "shortlist": json.loads(row["shortlist"])} for row in rows]

    def shortlist(self, run_id, candidate_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result,shortlist FROM matching_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("匹配记录不存在")
            result = json.loads(row["result"])
            if candidate_id not in {m["id"] for m in result["matches"]}:
                raise ValueError("只能保存本次匹配中的候选项")
            ids = json.loads(row["shortlist"])
            if candidate_id not in ids:
                ids.append(candidate_id)
            db.execute("UPDATE matching_runs SET shortlist=? WHERE id=?", (json.dumps(ids), run_id))
        return self.get_matching(run_id)

    def metrics(self):
        leads = self.list()
        with self.connect() as db:
            events = db.execute("SELECT lead_id,kind,detail FROM events WHERE kind IN ('human_review','human_outcome')").fetchall()
            analyzed_ids = {r[0] for r in db.execute("SELECT DISTINCT lead_id FROM runs WHERE ok=1")}
        reached = {}
        for event in events:
            reached.setdefault(event["lead_id"], set()).add(json.loads(event["detail"])["to"])
        channels = {}
        for lead in leads:
            c = channels.setdefault(lead["channel"], {"channel": lead["channel"], "total": 0, "analyzed": 0, "approved": 0, "contacted": 0, "appointment": 0, "won": 0})
            c["total"] += 1
            c["analyzed"] += int(lead["id"] in analyzed_ids)
            for stage in ("approved", "contacted", "appointment", "won"):
                c[stage] += int(stage in reached.get(lead["id"], set()))
        return {"channels": list(channels.values()), "funnel": {key: sum(c[key] for c in channels.values()) for key in ("total", "analyzed", "approved", "contacted", "appointment", "won")}, "notice": "按去重线索及人工登记的历史阶段计数，预约不等于实际到店。"}
