"""
鹰眼·告警记录服务
职责：
  1. 接收 Alertmanager webhook，把告警写入 MySQL（hawk_eye.alert_record）
  2. 提供告警列表 / 汇总查询接口给前端页面
  3. 提供值班表接口（同库 oncall 表）
  4. 启动时自动建库建表（使用 root 账号，避免手工初始化）
数据库复用项目一的 MySQL 容器（yizhan-mysql），只新建 hawk_eye 库，互不干扰。
"""
import os
import time
import logging

from flask import Flask, request, jsonify
import pymysql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hawk-alertservice")

DB_HOST = os.getenv("DB_HOST", "yizhan-mysql")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root123456")
DB_NAME = os.getenv("DB_NAME", "hawk_eye")

app = Flask(__name__)


def connect(database=DB_NAME):
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def wait_db_ready(retries=30, interval=3):
    """等待 MySQL 就绪（首次启动时项目一的库可能还在初始化）。"""
    for i in range(1, retries + 1):
        try:
            conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, charset="utf8mb4")
            conn.close()
            log.info("MySQL 连接就绪")
            return
        except Exception as e:
            log.warning("等待 MySQL 就绪（%d/%d）: %s", i, retries, e)
            time.sleep(interval)
    raise RuntimeError("MySQL 长时间未就绪，请检查 yizhan-mysql 容器")


def init_schema():
    """建库建表（幂等）。"""
    conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, charset="utf8mb4", autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARSET utf8mb4")
            cur.execute(f"USE `{DB_NAME}`")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alert_record (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    alert_name VARCHAR(100) NOT NULL,
                    severity VARCHAR(20),
                    instance VARCHAR(200),
                    status VARCHAR(20) DEFAULT 'firing',
                    summary VARCHAR(500),
                    fired_at DATETIME NOT NULL,
                    resolved_at DATETIME,
                    INDEX idx_name (alert_name),
                    INDEX idx_status (status),
                    INDEX idx_fired (fired_at)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS oncall (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(50) NOT NULL,
                    phone VARCHAR(20),
                    duty_date DATE NOT NULL,
                    INDEX idx_date (duty_date)
                )
            """)
            # 首次运行写入本周值班示例数据（只写一次）
            cur.execute("SELECT COUNT(*) AS c FROM oncall")
            if cur.fetchone()["c"] == 0:
                cur.execute("""
                    INSERT INTO oncall (name, phone, duty_date) VALUES
                    ('张三', '13800000001', CURDATE()),
                    ('李四', '13800000002', DATE_ADD(CURDATE(), INTERVAL 1 DAY)),
                    ('王五', '13800000003', DATE_ADD(CURDATE(), INTERVAL 2 DAY))
                """)
                log.info("已写入值班示例数据")
        log.info("数据库结构初始化完成")
    finally:
        conn.close()


def ensure_monitor_user():
    """为 mysqld-exporter 创建只读监控账号（幂等）。"""
    try:
        conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, charset="utf8mb4", autocommit=True)
        with conn.cursor() as cur:
            cur.execute("CREATE USER IF NOT EXISTS 'hawk_monitor'@'%' IDENTIFIED BY 'hawk123456'")
            cur.execute("GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'hawk_monitor'@'%'")
        conn.close()
        log.info("监控账号 hawk_monitor 已就绪")
    except Exception as e:
        log.warning("创建监控账号失败（不影响主流程）: %s", e)


@app.route("/api/health")
def health():
    return jsonify({"code": 200, "message": "ok", "data": "hawk-alertservice running"})


@app.route("/api/alert/webhook", methods=["POST"])
def webhook():
    """
    Alertmanager webhook 格式：
    {"status": "firing|resolved", "alerts": [{"status":..., "labels":{alertname,severity,instance}, "annotations":{summary}, "startsAt":..., "endsAt":...}]}
    """
    payload = request.get_json(silent=True) or {}
    alerts = payload.get("alerts", [])
    if not alerts:
        return jsonify({"code": 200, "message": "empty", "data": 0})

    conn = connect()
    written = 0
    try:
        with conn.cursor() as cur:
            for a in alerts:
                labels = a.get("labels", {}) or {}
                annotations = a.get("annotations", {}) or {}
                name = labels.get("alertname", "unknown")
                severity = labels.get("severity", "info")
                instance = labels.get("instance", "-")
                summary = annotations.get("summary", "")[:500]
                status = a.get("status", "firing")

                if status == "resolved":
                    # 恢复：把该告警最近一条 firing 记录更新为 resolved
                    cur.execute(
                        """UPDATE alert_record SET status='resolved', resolved_at=NOW()
                           WHERE alert_name=%s AND instance=%s AND status='firing'
                           ORDER BY fired_at DESC LIMIT 1""",
                        (name, instance),
                    )
                    written += 1
                else:
                    # 触发：若同一告警+实例已有未恢复记录则跳过，避免重复入库
                    cur.execute(
                        "SELECT id FROM alert_record WHERE alert_name=%s AND instance=%s AND status='firing' LIMIT 1",
                        (name, instance),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        """INSERT INTO alert_record (alert_name, severity, instance, status, summary, fired_at)
                           VALUES (%s, %s, %s, 'firing', %s, NOW())""",
                        (name, severity, instance, summary),
                    )
                    written += 1
        log.info("webhook 收到 %d 条告警，处理 %d 条", len(alerts), written)
    finally:
        conn.close()
    return jsonify({"code": 200, "message": "ok", "data": written})


@app.route("/api/alert/list")
def alert_list():
    """查询告警列表，支持状态/名称/时间范围过滤，并附带汇总统计。"""
    status = request.args.get("status", "").strip()
    name = request.args.get("alertName", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    where = []
    params = []
    if status:
        where.append("status = %s")
        params.append(status)
    if name:
        where.append("alert_name = %s")
        params.append(name)
    if date_from:
        where.append("fired_at >= %s")
        params.append(date_from + " 00:00:00")
    if date_to:
        where.append("fired_at <= %s")
        params.append(date_to + " 23:59:59")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM alert_record {where_sql} ORDER BY fired_at DESC LIMIT 200", params)
            rows = cur.fetchall()
            for r in rows:
                for k in ("fired_at", "resolved_at"):
                    if r.get(k):
                        r[k] = r[k].strftime("%Y-%m-%d %H:%M:%S")
            # 汇总（今日口径）
            cur.execute("SELECT COUNT(*) c FROM alert_record WHERE DATE(fired_at)=CURDATE()")
            total = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) c FROM alert_record WHERE status='firing'")
            firing = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) c FROM alert_record WHERE status='resolved' AND DATE(resolved_at)=CURDATE()")
            resolved_today = cur.fetchone()["c"]
    finally:
        conn.close()

    return jsonify({
        "code": 200, "message": "ok",
        "data": {
            "list": rows,
            "summary": {"total": total, "firing": firing, "resolved": resolved_today},
        },
    })


@app.route("/api/oncall/list")
def oncall_list():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oncall ORDER BY duty_date ASC LIMIT 62")
            rows = cur.fetchall()
            for r in rows:
                r["duty_date"] = r["duty_date"].strftime("%Y-%m-%d")
    finally:
        conn.close()
    return jsonify({"code": 200, "message": "ok", "data": {"list": rows}})


@app.route("/api/oncall/add", methods=["POST"])
def oncall_add():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()
    duty_date = (body.get("dutyDate") or "").strip()
    if not name or not duty_date:
        return jsonify({"code": 400, "message": "姓名和日期必填", "data": None}), 200
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO oncall (name, phone, duty_date) VALUES (%s, %s, %s)", (name, phone, duty_date))
    finally:
        conn.close()
    return jsonify({"code": 200, "message": "ok", "data": None})


if __name__ == "__main__":
    wait_db_ready()
    init_schema()
    ensure_monitor_user()
    log.info("hawk-alertservice 启动完成，监听 8080")
    app.run(host="0.0.0.0", port=8080)
