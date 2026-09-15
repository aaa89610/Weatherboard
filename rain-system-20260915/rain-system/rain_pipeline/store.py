"""SQLite 歷史庫：每次原始預報、實測快照、實測視窗、配對、校正狀態。Excel 只是它的檢視。"""
from __future__ import annotations

import array
import json
import sqlite3
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from .config import TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, run_time TEXT, fetched_at TEXT, status TEXT,
  info TEXT, version INTEGER);
CREATE TABLE IF NOT EXISTS fc(
  run_id TEXT, loc TEXT, model TEXT, start_time TEXT, n INTEGER,
  precip BLOB, prob BLOB, PRIMARY KEY(run_id, loc, model));
CREATE TABLE IF NOT EXISTS stations(
  station_id TEXT PRIMARY KEY, name TEXT, county TEXT, town TEXT, lat REAL, lon REAL, alt TEXT);
CREATE TABLE IF NOT EXISTS obs_snap(
  station_id TEXT, obs_time TEXT, now REAL, p10m REAL, p1h REAL, p3h REAL, p6h REAL,
  p12h REAL, p24h REAL, PRIMARY KEY(station_id, obs_time));
CREATE TABLE IF NOT EXISTS obs_win(
  loc TEXT, station_id TEXT, dist_km REAL, t_start TEXT, t_end TEXT, mm REAL, method TEXT,
  qc TEXT, PRIMARY KEY(loc, t_start, t_end));
CREATE TABLE IF NOT EXISTS pairs(
  loc TEXT, run_id TEXT, model TEXT, t_start TEXT, t_end TEXT, lead_h REAL,
  fc_mm REAL, fc_prob REAL, obs_mm REAL, PRIMARY KEY(loc, run_id, model, t_start, t_end));
CREATE TABLE IF NOT EXISTS calib(
  loc TEXT, bucket TEXT, model TEXT, factor REAL, n_train INTEGER, n_test INTEGER,
  n_wet_test INTEGER, mae_raw REAL, mae_cal REAL, improve REAL, ci_low REAL,
  enabled INTEGER, status TEXT, updated TEXT, PRIMARY KEY(loc, bucket, model));
CREATE INDEX IF NOT EXISTS ix_fc_run ON fc(run_id);
CREATE INDEX IF NOT EXISTS ix_pairs_loc ON pairs(loc, model);
CREATE INDEX IF NOT EXISTS ix_pairs_tend ON pairs(t_end);
"""


def enc(vals) -> bytes | None:
    if vals is None:
        return None
    a = array.array("h", [-1 if v is None else int(round(float(v) * 10)) for v in vals])
    return zlib.compress(a.tobytes(), 9)


def dec(blob) -> list[float | None] | None:
    if blob is None:
        return None
    a = array.array("h")
    a.frombytes(zlib.decompress(blob))
    return [None if v < 0 else v / 10 for v in a]


def iso(t: datetime) -> str:
    return t.astimezone(TZ).isoformat(timespec="minutes")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(TZ)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        # PERSIST：交易日誌檔保留不刪除（共享資料夾可能禁止刪檔）；不用 WAL 以免產生暫存檔
        self.db.execute("PRAGMA journal_mode=PERSIST")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.commit()
        self.db.close()

    # ---------- 預報 ----------
    def save_run(self, run_id: str, run_time: datetime, fc: dict, info: dict, status: str):
        cur = self.db.cursor()
        ver = (cur.execute("SELECT COALESCE(MAX(version),0) FROM runs").fetchone()[0] or 0) + 1
        cur.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?)",
                    (run_id, iso(run_time), info.get("fetched_at"), status,
                     json.dumps(info, ensure_ascii=False), ver))
        for loc, models in fc.items():
            for m, s in models.items():
                if not s["times"]:
                    continue
                cur.execute("INSERT OR REPLACE INTO fc VALUES(?,?,?,?,?,?,?)",
                            (run_id, loc, m, iso(s["times"][0]), len(s["times"]),
                             enc(s["precip"]), enc(s["prob"])))
        self.db.commit()
        return ver

    def update_run_status(self, run_id: str, status: str, info: dict | None = None):
        if info is None:
            self.db.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
        else:
            self.db.execute("UPDATE runs SET status=?, info=? WHERE run_id=?",
                            (status, json.dumps(info, ensure_ascii=False), run_id))
        self.db.commit()

    def runs(self, limit: int | None = None) -> list[dict]:
        q = "SELECT run_id, run_time, fetched_at, status, info, version FROM runs ORDER BY run_time DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(run_id=r[0], run_time=parse(r[1]), fetched_at=r[2], status=r[3],
                     info=json.loads(r[4] or "{}"), version=r[5]) for r in self.db.execute(q)]

    def previous_ok_run(self, before_run_id: str) -> str | None:
        r = self.db.execute("SELECT run_id FROM runs WHERE run_id<? AND status LIKE 'ok%' "
                            "ORDER BY run_id DESC LIMIT 1", (before_run_id,)).fetchone()
        return r[0] if r else None

    def load_run(self, run_id: str) -> dict:
        out: dict = {}
        for loc, m, st, n, p, pr in self.db.execute(
                "SELECT loc, model, start_time, n, precip, prob FROM fc WHERE run_id=?", (run_id,)):
            t0 = parse(st)
            out.setdefault(loc, {})[m] = {"times": [t0 + timedelta(hours=i) for i in range(n)],
                                          "precip": dec(p), "prob": dec(pr)}
        return out

    def runs_between(self, t_from: datetime, t_to: datetime) -> list[tuple[str, datetime]]:
        return [(r[0], parse(r[1])) for r in self.db.execute(
            "SELECT run_id, run_time FROM runs WHERE run_time>=? AND run_time<=? AND status LIKE 'ok%'",
            (iso(t_from), iso(t_to)))]

    # ---------- 實測 ----------
    def save_stations(self, stations: list[dict]):
        self.db.executemany("INSERT OR REPLACE INTO stations VALUES(?,?,?,?,?,?,?)",
                            [(s["station_id"], s["name"], s["county"], s["town"], s["lat"], s["lon"],
                              str(s.get("alt"))) for s in stations])
        self.db.commit()

    def stations(self) -> list[dict]:
        cols = ["station_id", "name", "county", "town", "lat", "lon", "alt"]
        return [dict(zip(cols, r)) for r in self.db.execute("SELECT * FROM stations")]

    def save_snaps(self, snaps: list[dict]) -> int:
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO obs_snap VALUES(?,?,?,?,?,?,?,?,?)",
            [(s["station_id"], iso(s["obs_time"]), s.get("now"), s.get("p10m"), s.get("p1h"),
              s.get("p3h"), s.get("p6h"), s.get("p12h"), s.get("p24h")) for s in snaps])
        self.db.commit()
        return cur.rowcount

    def snaps_for(self, station_id: str, since: datetime) -> list[dict]:
        cols = ["station_id", "obs_time", "now", "p10m", "p1h", "p3h", "p6h", "p12h", "p24h"]
        rows = self.db.execute("SELECT * FROM obs_snap WHERE station_id=? AND obs_time>=? "
                               "ORDER BY obs_time", (station_id, iso(since))).fetchall()
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["obs_time"] = parse(d["obs_time"])
            out.append(d)
        return out

    def save_windows(self, rows: list[tuple]) -> int:
        cur = self.db.executemany("INSERT OR IGNORE INTO obs_win VALUES(?,?,?,?,?,?,?,?)", rows)
        self.db.commit()
        return cur.rowcount

    def windows(self, since: datetime | None = None) -> list[dict]:
        q, args = "SELECT loc, station_id, dist_km, t_start, t_end, mm, method, qc FROM obs_win", ()
        if since:
            q, args = q + " WHERE t_end>=?", (iso(since),)
        cols = ["loc", "station_id", "dist_km", "t_start", "t_end", "mm", "method", "qc"]
        return [dict(zip(cols, r)) for r in self.db.execute(q + " ORDER BY t_end", args)]

    def save_pairs(self, rows: list[tuple]) -> int:
        cur = self.db.executemany("INSERT OR IGNORE INTO pairs VALUES(?,?,?,?,?,?,?,?,?)", rows)
        self.db.commit()
        return cur.rowcount

    def pairs(self, model: str | None = None, since: datetime | None = None,
              limit: int | None = None) -> list[dict]:
        cols = ["loc", "run_id", "model", "t_start", "t_end", "lead_h", "fc_mm", "fc_prob", "obs_mm"]
        cond, args = [], []
        if model:
            cond.append("model=?"); args.append(model)
        if since:
            cond.append("t_end>=?"); args.append(iso(since))
        q = "SELECT * FROM pairs" + (" WHERE " + " AND ".join(cond) if cond else "")
        if limit:
            q = f"SELECT * FROM ({q} ORDER BY t_end DESC, run_id DESC LIMIT {int(limit)})"
        return [dict(zip(cols, r)) for r in self.db.execute(q + " ORDER BY t_end", args)]

    def save_calib(self, rows: list[tuple]):
        self.db.executemany("INSERT OR REPLACE INTO calib VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.db.commit()

    def calib(self) -> dict:
        cols = ["loc", "bucket", "model", "factor", "n_train", "n_test", "n_wet_test", "mae_raw",
                "mae_cal", "improve", "ci_low", "enabled", "status", "updated"]
        return {(r[0], r[1], r[2]): dict(zip(cols, r)) for r in self.db.execute("SELECT * FROM calib")}
