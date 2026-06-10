from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import sqlite3
from datetime import datetime, timedelta
import os
import io
import csv
import qrcode
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "farfasha_secret_key_change_this_2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "farfasha_cafe.db")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "837291")

ORDER_STATUSES = ["جديد", "قيد التحضير", "جاهز", "تم التسليم", "ملغي"]
ADMIN_FLOORS = ["الدور الأرضي", "الأول علوي", "الثاني علوي", "الثالث علوي", "الرابع علوي"]
CAFE_TABLES = [f"طاولة رقم {i}" for i in range(1, 21)]
CATEGORIES = ["مشروبات ساخنة", "مشروبات باردة", "شيشة", "حلويات", "وجبات خفيفة"]

DEFAULT_MENU = [
    ("قهوة تركي", "قهوة تركية أصلية بطعم غني ورائحة مميزة", 15, "مشروبات ساخنة", "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=900", 1),
    ("شاي", "شاي أحمر نقي ومنعش", 10, "مشروبات ساخنة", "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=900", 1),
    ("كابتشينو", "اسبريسو مع حليب مبخر ورغوة ناعمة", 25, "مشروبات ساخنة", "https://images.unsplash.com/photo-1534778101976-62847782c213?w=900", 1),
    ("موكا", "مزيج رائع من القهوة والشوكولاتة", 30, "مشروبات ساخنة", "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=900", 1),
    ("قهوة مثلجة", "قهوة باردة ومنعشة", 25, "مشروبات باردة", "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=900", 1),
    ("عصير برتقال", "عصير طبيعي طازج", 20, "مشروبات باردة", "https://images.unsplash.com/photo-1621506289937-a8e4df240d0b?w=900", 1),
    ("كيك شوكولاتة", "قطعة كيك غنية بالشوكولاتة", 30, "حلويات", "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=900", 1),
    ("ساندوتش دجاج", "ساندوتش دجاج طازج", 35, "وجبات خفيفة", "https://images.unsplash.com/photo-1553909489-cd47e0907980?w=900", 1),
]


def get_site_base_url():
    base_url = request.url_root.rstrip("/")
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and base_url.startswith("http://"):
        base_url = "https://" + base_url.replace("http://", "", 1)
    return base_url


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def has_column(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cur.fetchall()]


def add_column_if_missing(cur, table, column, definition):
    if not has_column(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def log_action(action, details="", user="مدير"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO operation_logs (user, action, details, created_at) VALUES (?, ?, ?, ?)",
        (user, action, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT DEFAULT 'عميل',
            order_place TEXT DEFAULT '',
            table_number TEXT DEFAULT '',
            total REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'جديد',
            created_at TEXT NOT NULL
        )
    """)
    add_column_if_missing(cur, "orders", "customer_name", "TEXT DEFAULT 'عميل'")
    add_column_if_missing(cur, "orders", "order_place", "TEXT DEFAULT ''")
    add_column_if_missing(cur, "orders", "table_number", "TEXT DEFAULT ''")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_id INTEGER,
            item_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
    """)
    add_column_if_missing(cur, "order_items", "item_id", "INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            category TEXT NOT NULL,
            image TEXT DEFAULT '',
            available INTEGER DEFAULT 1,
            created_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 0,
            unit TEXT DEFAULT 'وحدة',
            min_qty REAL NOT NULL DEFAULT 5,
            last_update TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            phone TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT DEFAULT 'مدير',
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    cur.execute("SELECT COUNT(*) AS c FROM menu_items")
    if cur.fetchone()["c"] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cur.executemany(
            "INSERT INTO menu_items (name, description, price, category, image, available, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(a, b, c, d, e, f, now) for a, b, c, d, e, f in DEFAULT_MENU],
        )

    cur.execute("SELECT COUNT(*) AS c FROM inventory")
    if cur.fetchone()["c"] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cur.executemany(
            "INSERT INTO inventory (item_name, qty, unit, min_qty, last_update) VALUES (?, ?, ?, ?, ?)",
            [("بن قهوة", 12, "كجم", 3, now), ("سكر", 20, "كجم", 5, now), ("أكواب", 150, "قطعة", 50, now), ("حليب", 10, "لتر", 3, now)],
        )

    default_settings = {
        "cafe_name": "كافيه فرفشة",
        "phone": "",
        "logo": "☕",
        "printer": "طباعة المتصفح",
        "qr_note": "امسح QR لفتح المنيو"
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


init_db()


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def get_menu_items(active_only=False):
    conn = get_db()
    cur = conn.cursor()
    if active_only:
        cur.execute("SELECT * FROM menu_items WHERE available = 1 ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM menu_items ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_item_by_id(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM menu_items WHERE id = ? AND available = 1", (item_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def stats_data():
    conn = get_db()
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) c FROM orders WHERE status IN ('جديد','قيد التحضير','جاهز')")
    current_orders = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM orders WHERE status='تم التسليم' AND created_at LIKE ?", (today + "%",))
    completed_today = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(total),0) s FROM orders WHERE status!='ملغي' AND created_at LIKE ?", (today + "%",))
    sales_today = cur.fetchone()["s"]
    cur.execute("SELECT COUNT(*) c FROM orders WHERE status='جديد'")
    new_orders = cur.fetchone()["c"]
    cur.execute("""
        SELECT oi.item_name, SUM(oi.qty) qty
        FROM order_items oi JOIN orders o ON oi.order_id=o.id
        WHERE o.status!='ملغي'
        GROUP BY oi.item_name
        ORDER BY qty DESC LIMIT 1
    """)
    top = cur.fetchone()
    top_item = top["item_name"] if top else "لا يوجد"
    cur.execute("SELECT COUNT(DISTINCT order_place) c FROM orders WHERE created_at LIKE ?", (today + "%",))
    active_places = cur.fetchone()["c"]
    conn.close()
    return {
        "current_orders": current_orders,
        "completed_today": completed_today,
        "sales_today": sales_today,
        "new_orders": new_orders,
        "top_item": top_item,
        "active_places": active_places,
    }


def get_orders():
    place_filter = request.args.get("place", "").strip()
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    conn = get_db()
    cur = conn.cursor()
    sql = "SELECT * FROM orders WHERE 1=1"
    params = []
    if place_filter:
        sql += " AND order_place LIKE ?"
        params.append("%" + place_filter + "%")
    if status_filter:
        sql += " AND status = ?"
        params.append(status_filter)
    if q:
        sql += " AND (customer_name LIKE ? OR CAST(id AS TEXT) LIKE ? OR order_place LIKE ?)"
        params.extend(["%" + q + "%", "%" + q + "%", "%" + q + "%"])
    sql += " ORDER BY id DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()
    orders = []
    for order in rows:
        cur.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],))
        items = [dict(i) for i in cur.fetchall()]
        d = dict(order)
        d["order_items"] = items
        orders.append(d)
    conn.close()
    return orders


def get_notifications():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) c FROM orders WHERE status='جديد'")
    new_order_count = cur.fetchone()["c"]
    cur.execute("SELECT item_name, qty, min_qty FROM inventory WHERE qty <= min_qty ORDER BY qty ASC")
    low_stock = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT name FROM menu_items WHERE available=0 ORDER BY id DESC")
    unavailable = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"new_order_count": new_order_count, "low_stock": low_stock, "unavailable": unavailable}


def get_chart_data():
    conn = get_db()
    cur = conn.cursor()
    labels = []
    values = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        labels.append(day.strftime("%m-%d"))
        cur.execute("SELECT COALESCE(SUM(total),0) s FROM orders WHERE status!='ملغي' AND created_at LIKE ?", (day_str + "%",))
        values.append(float(cur.fetchone()["s"] or 0))
    cur.execute("SELECT status, COUNT(*) c FROM orders GROUP BY status")
    status_counts = {r["status"]: r["c"] for r in cur.fetchall()}
    conn.close()
    return {"labels": labels, "values": values, "status_counts": status_counts}


@app.route("/")
def home():
    base_url = get_site_base_url()
    return render_template_string(
        HOME_HTML,
        menu=get_menu_items(active_only=True),
        admin_floors=ADMIN_FLOORS,
        cafe_tables=CAFE_TABLES,
        categories=CATEGORIES,
        qr_url=f"{base_url}/qr",
        menu_url=f"{base_url}/",
    )


@app.route("/send-order", methods=["POST"])
def send_order():
    data = request.get_json() or {}
    customer_name = (data.get("customer_name") or "").strip()
    order_place = (data.get("order_place") or "").strip()
    cart = data.get("cart", [])
    if not customer_name:
        return jsonify({"success": False, "message": "من فضلك اكتب اسم صاحب الطلب"})
    if not order_place:
        return jsonify({"success": False, "message": "من فضلك اختر مكان الطلب"})
    if not cart:
        return jsonify({"success": False, "message": "السلة فارغة"})
    total = 0
    clean_items = []
    for cart_item in cart:
        try:
            item_id = int(cart_item.get("id", 0))
            qty = int(cart_item.get("qty", 0))
        except Exception:
            continue
        item = get_item_by_id(item_id)
        if item and qty > 0:
            total += float(item["price"]) * qty
            clean_items.append({"id": item["id"], "name": item["name"], "qty": qty, "price": item["price"]})
    if not clean_items:
        return jsonify({"success": False, "message": "لا توجد عناصر صحيحة"})
    conn = get_db()
    cur = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "INSERT INTO orders (customer_name, order_place, table_number, total, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (customer_name, order_place, order_place, total, "جديد", created_at),
    )
    order_id = cur.lastrowid
    for item in clean_items:
        cur.execute(
            "INSERT INTO order_items (order_id, item_id, item_name, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, item["id"], item["name"], item["qty"], item["price"]),
        )
    cur.execute(
        "INSERT INTO operation_logs (user, action, details, created_at) VALUES (?, ?, ?, ?)",
        (customer_name, "إضافة طلب", f"طلب #{order_id} من {order_place}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"تم إرسال الطلب بنجاح ✅ رقم الطلب #{order_id}", "order_id": order_id, "total": total})


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == ADMIN_PIN:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "كود الدخول غير صحيح"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin():
    section = request.args.get("section", "dashboard")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory ORDER BY id DESC")
    inventory = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM employees ORDER BY id DESC")
    employees = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM operation_logs ORDER BY id DESC LIMIT 80")
    logs = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT key, value FROM settings")
    settings_rows = {r["key"]: r["value"] for r in cur.fetchall()}
    conn.close()
    base_url = get_site_base_url()
    return render_template_string(
        ADMIN_HTML,
        section=section,
        stats=stats_data(),
        chart=get_chart_data(),
        orders=get_orders(),
        menu=get_menu_items(active_only=False),
        inventory=inventory,
        employees=employees,
        logs=logs,
        notifications=get_notifications(),
        settings=settings_rows,
        statuses=ORDER_STATUSES,
        categories=CATEGORIES,
        admin_floors=ADMIN_FLOORS,
        cafe_tables=CAFE_TABLES,
        menu_url=f"{base_url}/",
        qr_url=f"{base_url}/qr",
        notice=session.pop("admin_notice", ""),
    )


@app.route("/update-status/<int:order_id>/<status>")
@admin_required
def update_status(order_id, status):
    if status not in ORDER_STATUSES:
        status = "جديد"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    cur.execute(
        "INSERT INTO operation_logs (user, action, details, created_at) VALUES (?, ?, ?, ?)",
        ("مدير", "تغيير حالة طلب", f"طلب #{order_id} إلى {status}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    session["admin_notice"] = f"تم تغيير حالة الطلب #{order_id} إلى {status} ✅"
    return redirect(url_for("admin", section="orders"))


@app.route("/delete-order/<int:order_id>")
@admin_required
def delete_order(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
    cur.execute("DELETE FROM orders WHERE id=?", (order_id,))
    cur.execute(
        "INSERT INTO operation_logs (user, action, details, created_at) VALUES (?, ?, ?, ?)",
        ("مدير", "حذف طلب", f"تم حذف طلب #{order_id}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    session["admin_notice"] = f"تم حذف الطلب #{order_id}"
    return redirect(url_for("admin", section="orders"))


@app.route("/menu/add", methods=["POST"])
@admin_required
def menu_add():
    name = request.form.get("name", "").strip()
    price = float(request.form.get("price", 0) or 0)
    category = request.form.get("category", "مشروبات ساخنة")
    description = request.form.get("description", "").strip()
    image = request.form.get("image", "").strip() or "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=900"
    if name and price > 0:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO menu_items (name, description, price, category, image, available, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (name, description, price, category, image, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        conn.close()
        log_action("إضافة صنف", name)
    return redirect(url_for("admin", section="menu"))


@app.route("/menu/update/<int:item_id>", methods=["POST"])
@admin_required
def menu_update(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE menu_items SET name=?, description=?, price=?, category=?, image=? WHERE id=?",
        (
            request.form.get("name", "").strip(),
            request.form.get("description", "").strip(),
            float(request.form.get("price", 0) or 0),
            request.form.get("category", "مشروبات ساخنة"),
            request.form.get("image", "").strip(),
            item_id,
        ),
    )
    conn.commit()
    conn.close()
    log_action("تعديل صنف", f"صنف #{item_id}")
    return redirect(url_for("admin", section="menu"))


@app.route("/menu/toggle/<int:item_id>")
@admin_required
def menu_toggle(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE menu_items SET available = CASE WHEN available=1 THEN 0 ELSE 1 END WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    log_action("إيقاف/تشغيل صنف", f"صنف #{item_id}")
    return redirect(url_for("admin", section="menu"))


@app.route("/menu/delete/<int:item_id>")
@admin_required
def menu_delete(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM menu_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    log_action("حذف صنف", f"صنف #{item_id}")
    return redirect(url_for("admin", section="menu"))


@app.route("/inventory/add", methods=["POST"])
@admin_required
def inventory_add():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO inventory (item_name, qty, unit, min_qty, last_update) VALUES (?, ?, ?, ?, ?)",
        (
            request.form.get("item_name", "").strip(),
            float(request.form.get("qty", 0) or 0),
            request.form.get("unit", "وحدة").strip(),
            float(request.form.get("min_qty", 0) or 0),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()
    conn.close()
    log_action("إضافة مخزون", request.form.get("item_name", ""))
    return redirect(url_for("admin", section="inventory"))


@app.route("/inventory/update/<int:item_id>", methods=["POST"])
@admin_required
def inventory_update(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE inventory SET item_name=?, qty=?, unit=?, min_qty=?, last_update=? WHERE id=?",
        (
            request.form.get("item_name", "").strip(),
            float(request.form.get("qty", 0) or 0),
            request.form.get("unit", "وحدة").strip(),
            float(request.form.get("min_qty", 0) or 0),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            item_id,
        ),
    )
    conn.commit()
    conn.close()
    log_action("تعديل مخزون", request.form.get("item_name", ""))
    return redirect(url_for("admin", section="inventory"))


@app.route("/employees/add", methods=["POST"])
@admin_required
def employees_add():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO employees (name, role, phone, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (request.form.get("name", "").strip(), request.form.get("role", "كاشير"), request.form.get("phone", ""), datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    conn.close()
    log_action("إضافة موظف", request.form.get("name", ""))
    return redirect(url_for("admin", section="employees"))


@app.route("/employees/toggle/<int:emp_id>")
@admin_required
def employees_toggle(emp_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE employees SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?", (emp_id,))
    conn.commit()
    conn.close()
    log_action("إيقاف/تشغيل موظف", f"موظف #{emp_id}")
    return redirect(url_for("admin", section="employees"))


@app.route("/settings/save", methods=["POST"])
@admin_required
def settings_save():
    conn = get_db()
    cur = conn.cursor()
    for key in ["cafe_name", "phone", "logo", "printer", "qr_note"]:
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, request.form.get(key, "")))
    conn.commit()
    conn.close()
    log_action("تعديل الإعدادات", "تم تحديث بيانات الكافيه")
    return redirect(url_for("admin", section="settings"))


@app.route("/export/orders.csv")
@admin_required
def export_orders_csv():
    orders = get_orders()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["رقم الطلب", "اسم العميل", "مكان الطلب", "الحالة", "الإجمالي", "الوقت"])
    for o in orders:
        writer.writerow([o["id"], o["customer_name"], o["order_place"], o["status"], o["total"], o["created_at"]])
    bio = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(bio, mimetype="text/csv", as_attachment=True, download_name="farfasha_orders.csv")


@app.route("/invoice/<int:order_id>")
@admin_required
def invoice(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = cur.fetchone()
    if not order:
        conn.close()
        return "Order not found", 404
    cur.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,))
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template_string(INVOICE_HTML, order=dict(order), items=items)


@app.route("/qr")
def qr_code():
    url = f"{get_site_base_url()}/"
    img = qrcode.make(url)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


HOME_HTML = r'''
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>كافيه فرفشة</title>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--brown:#5b2b12;--brown2:#7a3d1d;--dark:#1e0f08;--cream:#fffaf4;--paper:#fff;--muted:#84756b;--line:#eaded5;--shadow:0 14px 45px rgba(70,35,15,.10);--soft:#f7efe8}*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}body{margin:0;font-family:'Cairo',Tahoma,sans-serif;background:linear-gradient(180deg,#fffaf4,#f5eee7);color:#20120a;padding-bottom:96px}.wrap{max-width:930px;margin:0 auto;padding:14px}.mobile-header{position:sticky;top:0;z-index:50;background:rgba(255,250,244,.95);backdrop-filter:blur(18px);padding:12px 14px;border-bottom:1px solid rgba(91,43,18,.08);display:flex;align-items:center;justify-content:space-between}.icon-btn{width:46px;height:46px;border:0;background:#fff;border-radius:17px;box-shadow:0 8px 25px rgba(70,35,15,.08);font-size:23px;display:grid;place-items:center;position:relative}.cart-count{position:absolute;top:-4px;right:-4px;background:var(--brown);color:#fff;border-radius:999px;min-width:22px;height:22px;font-size:12px;display:grid;place-items:center}.mobile-header h1{margin:0;font-size:23px;font-weight:900}.hero{margin-top:14px;border-radius:28px;min-height:235px;background:linear-gradient(90deg,rgba(18,9,5,.98),rgba(42,20,10,.58)),url('https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1400') center/cover;box-shadow:var(--shadow);padding:26px;display:flex;align-items:center;justify-content:flex-end;color:#fff;overflow:hidden}.hero small{color:#f3d7be;font-weight:700;font-size:18px}.hero h2{font-size:32px;line-height:1.25;margin:8px 0 14px;font-weight:900}.hero p{margin:0;color:#ffe7cf}.links-card{margin:18px 0;background:#fff;border:1px solid var(--line);box-shadow:0 10px 30px rgba(70,35,15,.06);border-radius:22px;display:grid;grid-template-columns:1fr 1fr;overflow:hidden}.links-card>div{padding:16px;display:flex;align-items:center;justify-content:center;gap:12px}.round-icon{width:48px;height:48px;border-radius:50%;background:#f0e6dd;color:var(--brown);display:grid;place-items:center;font-size:24px;flex:0 0 auto}.tabs{display:flex;gap:12px;overflow:auto;padding:7px 0 13px}.tab{min-width:112px;height:86px;border:1px solid var(--line);background:#fff;border-radius:18px;box-shadow:0 8px 22px rgba(70,35,15,.07);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;font-weight:800;color:#3c2516;cursor:pointer}.tab.active{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.section-title{display:flex;align-items:center;gap:16px;justify-content:center;margin:20px 0 16px;font-size:25px;font-weight:900}.section-title:before,.section-title:after{content:'';height:1px;background:#eaded5;flex:1}.products{display:flex;flex-direction:column;gap:16px}.product{background:#fff;border:1px solid rgba(91,43,18,.06);box-shadow:0 12px 35px rgba(70,35,15,.08);border-radius:23px;display:grid;grid-template-columns:38% 1fr;overflow:hidden;min-height:176px}.photo{position:relative;min-height:176px}.photo img{width:100%;height:100%;object-fit:cover;display:block}.heart{position:absolute;top:13px;right:13px;color:#fff;font-size:28px;text-shadow:0 2px 8px #000}.info{padding:20px;display:flex;flex-direction:column;justify-content:space-between}.info h3{font-size:23px;margin:0 0 6px;font-weight:900}.desc{margin:0;color:var(--muted);font-size:14px}.bottom{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:16px}.price{font-weight:900;color:var(--brown2);font-size:18px}.qty{display:flex;align-items:center;gap:8px}.qty button{border:0;background:#f2efec;width:34px;height:34px;border-radius:12px;font-weight:900}.add{border:0;background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff;width:46px;height:38px;border-radius:14px}.cart-drawer{position:fixed;inset:auto 12px 12px 12px;background:#fff;border:1px solid rgba(91,43,18,.08);border-radius:24px;padding:14px;box-shadow:0 22px 70px rgba(50,24,10,.22);z-index:60}.cart-summary{display:flex;align-items:center;justify-content:space-between;gap:12px}.bag{width:58px;height:58px;border-radius:50%;background:#f3e9e1;display:grid;place-items:center;font-size:25px}.cart-actions{display:flex;gap:8px}.view-cart,.send-order{border:0;border-radius:16px;padding:12px 14px;font-family:inherit;font-weight:900}.view-cart{background:#f3eee9;color:#4b2b1a}.send-order{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.cart-list{display:none;margin-top:12px;border-top:1px dashed #e7d9ce;padding-top:10px;max-height:45vh;overflow:auto}.cart-list.open{display:block}.field{margin-bottom:10px}.field label{display:block;font-weight:900;color:#5b2b12;margin-bottom:6px}.field input,.field select{width:100%;border:1px solid var(--line);border-radius:15px;padding:12px;font-family:inherit;background:#fffaf6}.cart-item{display:grid;grid-template-columns:1fr 34px 80px 30px;align-items:center;gap:8px;padding:10px 0;border-bottom:1px dashed #eee;font-size:14px}.remove{border:0;background:#fff0ed;color:#c0392b;width:30px;height:30px;border-radius:10px}.empty{color:var(--muted);text-align:center;padding:12px}.clear{width:100%;border:1px solid var(--line);background:#fff;color:#4b2b1a;border-radius:15px;padding:12px;margin-top:10px;font-family:inherit;font-weight:800}.toast{position:fixed;top:80px;left:50%;transform:translateX(-50%);background:#20120a;color:#fff;padding:12px 18px;border-radius:16px;z-index:120;display:none}.menu-overlay{position:fixed;inset:0;background:rgba(0,0,0,.48);z-index:100;display:none}.menu-overlay.show{display:block}.mobile-menu{position:fixed;top:0;right:-310px;width:300px;height:100vh;background:linear-gradient(180deg,#241107,#100703);color:#fff;z-index:110;padding:24px;transition:right .28s ease;box-shadow:-15px 0 45px rgba(0,0,0,.28)}.mobile-menu.show{right:0}.mobile-menu h2{margin:50px 0 5px;color:#ffc17d}.mobile-menu p{margin:0 0 24px;color:#c9b6a8}.mobile-menu a{display:flex;gap:12px;align-items:center;text-decoration:none;color:#fff;padding:15px;border-radius:16px;background:rgba(255,255,255,.08);margin-bottom:10px;font-weight:900}.close-menu{position:absolute;left:16px;top:16px;border:0;background:#fff;color:#5b2b12;width:42px;height:42px;border-radius:50%;font-size:28px}@media(min-width:1051px){body{padding-bottom:0}.wrap{max-width:960px;margin-right:300px}.products{display:grid;grid-template-columns:1fr 1fr}.product{grid-template-columns:1fr}.photo{height:185px}.cart-drawer{right:auto;left:22px;top:22px;bottom:auto;width:335px}.cart-list{display:block}.view-cart{display:none}.mobile-header{display:none}.mobile-menu,.menu-overlay{display:none}.desktop-nav{display:block!important;position:fixed;right:22px;top:22px;bottom:22px;width:250px;background:linear-gradient(180deg,#241107,#100703);border-radius:28px;color:#fff;padding:22px}.desktop-nav h2{color:#ffc17d}.desktop-nav a{display:block;color:#fff;text-decoration:none;padding:14px;border-radius:15px;background:rgba(255,255,255,.06);margin:8px 0;font-weight:800}}.desktop-nav{display:none}@media(max-width:620px){.wrap{padding:12px}.hero h2{font-size:27px}.links-card{grid-template-columns:1fr}.product{grid-template-columns:140px 1fr;min-height:145px}.photo{height:145px;min-height:145px}.info{padding:12px}.info h3{font-size:18px}.desc{font-size:12px}.bottom{display:block}.price{font-size:15px;margin-bottom:8px}.qty button{width:30px;height:30px}.add{width:40px;height:34px}.tab{min-width:100px;height:78px;font-size:13px}}
</style></head><body>
<div class="toast" id="toast"></div><div class="menu-overlay" id="menuOverlay"></div>
<aside class="mobile-menu" id="mobileMenu"><button class="close-menu" type="button" id="closeMenuBtn">×</button><h2>☕ كافيه فرفشة</h2><p>نكهة كل لحظة</p><a href="/">🏠 المنيو</a><a href="/login">📋 لوحة المدير</a><a href="{{ qr_url }}" target="_blank">▦ QR</a><a href="#cartBox" id="cartMenuLink">🛒 السلة</a></aside>
<aside class="desktop-nav"><h2>كافيه فرفشة ☕</h2><a href="/">🏠 المنيو</a><a href="/login">📋 لوحة المدير</a><a href="{{ qr_url }}" target="_blank">▦ QR Code</a></aside>
<header class="mobile-header"><button type="button" id="mobileMenuBtn" class="icon-btn">☰</button><h1>كافيه فرفشة ☕</h1><button class="icon-btn" onclick="toggleCart()">🛒<span class="cart-count" id="cartCount">0</span></button></header>
<main class="wrap"><section class="hero"><div><small>مرحباً بك في</small><h2>كافيه فرفشة 👋</h2><p>لذيذ يبدأ من هنا ✨</p></div></section><section class="links-card"><div><div><b>رابط المنيو</b><br><span>شارك المنيو مع أصدقائك</span></div><div class="round-icon">🔗</div></div><div><div><b>رابط الباركود</b><br><span>امسح لفتح المنيو</span></div><div class="round-icon">▦</div></div></section><nav class="tabs"><button class="tab active" onclick="filterCategory('all',this)">▦<span>كل الأصناف</span></button>{% for cat in categories %}<button class="tab" onclick="filterCategory('{{ cat }}',this)">☕<span>{{ cat }}</span></button>{% endfor %}</nav><div class="section-title">المنيو ☕</div><section class="products">{% for item in menu %}<article class="product product-card" data-category="{{ item.category }}"><div class="photo"><img src="{{ item.image }}" alt="{{ item.name }}"><span class="heart">♡</span></div><div class="info"><div><h3>{{ item.name }}</h3><p class="desc">{{ item.description }}</p></div><div class="bottom"><div class="price">{{ item.price }} جنيه</div><div class="qty"><button onclick="changeQty({{ item.id }},-1)">-</button><b id="qty-{{ item.id }}">0</b><button onclick="changeQty({{ item.id }},1)">+</button><button class="add" onclick="addToCart({{ item.id }})">🛒</button></div></div></div></article>{% endfor %}</section></main>
<section class="cart-drawer" id="cartBox"><div class="cart-summary"><div class="bag">🛍️</div><div><b>الإجمالي</b><br><span id="totalPrice">0</span> جنيه</div><div class="cart-actions"><button class="view-cart" onclick="toggleCart()">عرض السلة</button><button class="send-order" onclick="sendOrder()">إرسال</button></div></div><div class="cart-list" id="cartList"><div class="field"><label>اسم صاحب الطلب</label><input id="customerName" placeholder="مثال: أحمد محمد"></div><div class="field"><label>نوع المكان</label><select id="placeType" onchange="updatePlaceOptions()"><option value="">اختر نوع المكان</option><option value="admin">النيابة الإدارية</option><option value="cafe">الكافيه</option></select></div><div class="field"><label>مكان الطلب</label><select id="orderPlace"><option value="">اختر نوع المكان أولاً</option></select></div><div id="cartItems"></div><button class="clear" onclick="clearCart()">مسح الطلب 🗑️</button></div></section>
<script>
const menu={{ menu|tojson }}; const floors={{ admin_floors|tojson }}; const tables={{ cafe_tables|tojson }}; let quantities={}; let cart=[];
function showToast(msg){let t=document.getElementById('toast');t.innerText=msg;t.style.display='block';setTimeout(()=>t.style.display='none',2000)}
function openMobileMenu(){document.getElementById('mobileMenu').classList.add('show');document.getElementById('menuOverlay').classList.add('show');document.body.style.overflow='hidden'}
function closeMobileMenu(){document.getElementById('mobileMenu').classList.remove('show');document.getElementById('menuOverlay').classList.remove('show');document.body.style.overflow=''}
document.addEventListener('DOMContentLoaded',function(){document.getElementById('mobileMenuBtn')?.addEventListener('click',openMobileMenu);document.getElementById('closeMenuBtn')?.addEventListener('click',closeMobileMenu);document.getElementById('menuOverlay')?.addEventListener('click',closeMobileMenu);document.getElementById('cartMenuLink')?.addEventListener('click',function(){closeMobileMenu();document.getElementById('cartList').classList.add('open')});});
function updatePlaceOptions(){let type=document.getElementById('placeType').value;let select=document.getElementById('orderPlace');select.innerHTML='';if(type==='admin'){floors.forEach(f=>select.innerHTML+=`<option value="النيابة الإدارية - ${f}">النيابة الإدارية - ${f}</option>`)}else if(type==='cafe'){tables.forEach(t=>select.innerHTML+=`<option value="الكافيه - ${t}">الكافيه - ${t}</option>`)}else{select.innerHTML='<option value="">اختر نوع المكان أولاً</option>'}}
function toggleCart(){document.getElementById('cartList').classList.toggle('open')} function filterCategory(category,btn){document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.product-card').forEach(card=>{card.style.display=(category==='all'||card.dataset.category===category)?'grid':'none';});}
function changeQty(id,change){quantities[id]=(quantities[id]||0)+change;if(quantities[id]<0)quantities[id]=0;document.getElementById('qty-'+id).innerText=quantities[id]} function addToCart(id){let qty=quantities[id]||0;if(qty<=0){showToast('اختار الكمية أولاً');return}let item=menu.find(x=>x.id===id);let exists=cart.find(x=>x.id===id);if(exists){exists.qty+=qty}else{cart.push({id:item.id,name:item.name,price:item.price,qty:qty})}quantities[id]=0;document.getElementById('qty-'+id).innerText=0;renderCart();showToast('تمت الإضافة إلى السلة')}
function renderCart(){let box=document.getElementById('cartItems');let total=0,count=0;box.innerHTML='';if(cart.length===0)box.innerHTML='<div class="empty">لا يوجد طلبات حالياً</div>';cart.forEach((item,index)=>{total+=item.price*item.qty;count+=item.qty;box.innerHTML+=`<div class="cart-item"><div>${item.name}</div><b>${item.qty}</b><div>${item.price*item.qty} جنيه</div><button class="remove" onclick="removeItem(${index})">×</button></div>`});document.getElementById('totalPrice').innerText=total;document.getElementById('cartCount').innerText=count} function removeItem(index){cart.splice(index,1);renderCart()} function clearCart(){cart=[];renderCart()}
function sendOrder(){if(cart.length===0){showToast('السلة فارغة');return}let customerName=document.getElementById('customerName').value.trim();let orderPlace=document.getElementById('orderPlace').value;if(!customerName){document.getElementById('cartList').classList.add('open');document.getElementById('customerName').focus();showToast('اكتب اسم صاحب الطلب');return}if(!orderPlace){document.getElementById('cartList').classList.add('open');showToast('اختر مكان الطلب');return}fetch('/send-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_name:customerName,order_place:orderPlace,cart:cart})}).then(r=>r.json()).then(data=>{showToast(data.message);if(data.success){alert(data.message);clearCart();document.getElementById('customerName').value='';document.getElementById('cartList').classList.remove('open')}})} renderCart();
</script></body></html>
'''

LOGIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>دخول المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;800&display=swap" rel="stylesheet"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#2b1308,#fbf4ed);font-family:'Cairo',Tahoma,sans-serif}.box{width:min(92%,420px);background:#fff;border-radius:28px;padding:34px;box-shadow:0 20px 70px rgba(0,0,0,.18);text-align:center}.logo{font-size:50px}.box h1{margin:8px 0;color:#5a2d15}.box p{color:#77685f}input{width:100%;box-sizing:border-box;padding:16px;border:1px solid #eadfd6;border-radius:16px;text-align:center;font-size:20px;margin:16px 0;font-family:inherit}button{width:100%;padding:16px;border:0;border-radius:16px;background:linear-gradient(135deg,#7b3f20,#4b230f);color:#fff;font-weight:900;font-size:17px;font-family:inherit}.error{background:#fff0ef;color:#c0392b;border-radius:14px;padding:10px;margin:10px 0}</style></head><body><div class="box"><div class="logo">☕</div><h1>كافيه فرفشة</h1><p>تسجيل دخول المدير</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="password" name="pin" placeholder="ادخل كود المدير"><button type="submit">دخول لوحة التحكم</button></form></div></body></html>
'''

ADMIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>لوحة مدير فرفشة</title><meta name="viewport" content="width=device-width, initial-scale=1"><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet"><style>
:root{--dark:#160b06;--dark2:#2a140b;--brown:#6b3518;--gold:#c9873f;--bg:#fff8f1;--card:#fff;--muted:#827267;--line:#eaded5;--green:#1f9b55;--red:#c0392b;--orange:#c47b13;--shadow:0 18px 50px rgba(61,31,15,.10)}*{box-sizing:border-box}body{margin:0;font-family:'Cairo',Tahoma,sans-serif;background:linear-gradient(180deg,#fffaf4,#f4ede5);color:#211309}.layout{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#241107,#100703);color:#fff;padding:22px;position:sticky;top:0;height:100vh}.brand{display:flex;gap:12px;align-items:center;margin-bottom:24px}.brand-icon{width:54px;height:54px;border-radius:18px;background:rgba(255,255,255,.08);display:grid;place-items:center;font-size:30px}.brand h1{margin:0;color:#ffc17d;font-size:22px}.brand p{margin:0;color:#c9b6a8;font-size:12px}.nav a{display:flex;gap:12px;align-items:center;text-decoration:none;color:#fff;padding:14px;border-radius:16px;margin:7px 0;font-weight:800}.nav a.active,.nav a:hover{background:rgba(198,132,63,.28)}.main{padding:24px;min-width:0}.top{height:76px;background:#fff;border-radius:24px;box-shadow:var(--shadow);display:flex;align-items:center;justify-content:space-between;padding:0 22px;margin-bottom:20px}.top h2{margin:0;font-size:28px}.top a{background:#f4eee8;text-decoration:none;color:#2a160c;border-radius:14px;padding:11px 14px;font-weight:800;margin-right:8px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stat{background:#fff;border-radius:24px;padding:20px;box-shadow:var(--shadow);border:1px solid rgba(107,53,24,.06)}.stat .ico{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:#fff2e8;font-size:28px;margin-bottom:10px}.stat b{font-size:30px;color:var(--brown)}.stat p{margin:4px 0;color:var(--muted);font-weight:700}.grid2{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-top:18px}.panel{background:#fff;border-radius:26px;box-shadow:var(--shadow);border:1px solid rgba(107,53,24,.06);padding:20px;margin-top:18px}.panel h3{margin:0 0 6px;font-size:24px}.sub{color:var(--muted);margin:0 0 14px}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.input,select{border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-family:inherit;background:#fff;min-width:150px}button,.btn{border:0;text-decoration:none;border-radius:13px;padding:10px 13px;font-family:inherit;font-weight:900;cursor:pointer;display:inline-block}.btn-brown{background:var(--brown);color:#fff}.btn-green{background:var(--green);color:#fff}.btn-red{background:var(--red);color:#fff}.btn-orange{background:var(--orange);color:#fff}.btn-soft{background:#f4eee8;color:#2a160c}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:18px}table{width:100%;border-collapse:collapse;min-width:900px;background:#fff}th{background:linear-gradient(135deg,#693519,#3b1d0f);color:#fff;text-align:right;padding:14px}td{padding:13px;border-bottom:1px solid #f0e5dc;vertical-align:top}.badge{display:inline-flex;border-radius:12px;padding:7px 11px;font-weight:800;font-size:13px}.s-new{background:#e7f1ff;color:#1c64b7}.s-prep{background:#fff0d2;color:#b8730c}.s-ready{background:#e8f7ed;color:#18864a}.s-done{background:#e6f6ed;color:#177d43}.s-cancel{background:#ffe8e5;color:#bd3428}.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.form-grid textarea{grid-column:span 3;min-height:80px}.card-list{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.item-card{border:1px solid var(--line);border-radius:20px;padding:14px;background:#fff}.item-card img{width:100%;height:130px;object-fit:cover;border-radius:16px}.item-card h4{margin:8px 0 4px}.low{color:#c0392b;font-weight:900}.ok{color:#198754;font-weight:900}.mobile-title{display:none}@media(max-width:1000px){.layout{display:block}.side{display:none}.main{padding:12px}.mobile-title{display:block;position:sticky;top:0;z-index:20;background:rgba(255,250,244,.94);backdrop-filter:blur(12px);padding:12px;border-bottom:1px solid #eee}.mobile-nav{display:flex;gap:8px;overflow:auto;padding:10px 0}.mobile-nav a{white-space:nowrap;background:#fff;color:#2a160c;text-decoration:none;border-radius:14px;padding:10px 12px;font-weight:800}.top{display:none}.stats{grid-template-columns:1fr 1fr}.grid2{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.form-grid textarea{grid-column:span 1}.card-list{grid-template-columns:1fr}.panel{padding:14px;border-radius:22px}.input,select{width:100%;min-width:0}.filters{display:block}.filters>*{margin-bottom:8px;width:100%}}@media(max-width:560px){.stats{grid-template-columns:1fr}.stat{display:flex;gap:15px;align-items:center}.stat .ico{margin:0}.table-wrap table{min-width:760px}td,th{font-size:13px;padding:10px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand"><div class="brand-icon">☕</div><div><h1>كافيه فرفشة</h1><p>لوحة تحكم المدير</p></div></div><nav class="nav">{% set nav=[('dashboard','🏠 الرئيسية'),('orders','🛒 الطلبات'),('places','📍 أماكن الطلب'),('menu','🍹 المنيو'),('inventory','📦 المخزون'),('reports','📊 التقارير'),('employees','👥 الموظفين'),('notifications','🔔 الإشعارات'),('settings','⚙️ الإعدادات'),('logs','🧾 سجل العمليات')] %}{% for key,label in nav %}<a class="{% if section==key %}active{% endif %}" href="/admin?section={{ key }}">{{ label }}</a>{% endfor %}<a href="/logout">🚪 خروج</a></nav></aside><main class="main"><div class="mobile-title"><h2>لوحة مدير فرفشة</h2><div class="mobile-nav">{% for key,label in nav %}<a href="/admin?section={{ key }}">{{ label }}</a>{% endfor %}</div></div><div class="top"><h2>{% for key,label in nav %}{% if section==key %}{{ label }}{% endif %}{% endfor %}</h2><div><a href="/">فتح المنيو</a><a href="{{ qr_url }}" target="_blank">QR</a></div></div>{% if notice %}<script>alert({{ notice|tojson }});</script>{% endif %}
<section class="stats"><div class="stat"><div class="ico">🛒</div><div><b>{{ stats.current_orders }}</b><p>الطلبات الحالية</p></div></div><div class="stat"><div class="ico">💰</div><div><b>{{ stats.sales_today }}</b><p>مبيعات اليوم</p></div></div><div class="stat"><div class="ico">✅</div><div><b>{{ stats.completed_today }}</b><p>طلبات مكتملة</p></div></div><div class="stat"><div class="ico">👑</div><div><b style="font-size:22px">{{ stats.top_item }}</b><p>أكثر صنف مبيعاً</p></div></div></section>
{% if section=='dashboard' %}<div class="grid2"><div class="panel"><h3>المبيعات آخر 7 أيام</h3><canvas id="salesChart"></canvas></div><div class="panel"><h3>حالة الطلبات</h3><canvas id="statusChart"></canvas></div></div><div class="panel"><h3>الطلبات الجديدة قيد الانتظار</h3>{{ orders_table(orders, statuses) }}</div>
{% elif section=='orders' %}<div class="panel"><h3>إدارة الطلبات</h3><p class="sub">بحث، تغيير حالة، طباعة فاتورة، حذف</p><form class="filters" method="get"><input type="hidden" name="section" value="orders"><input class="input" name="q" placeholder="بحث برقم الطلب أو اسم العميل"><select name="status"><option value="">كل الحالات</option>{% for s in statuses %}<option>{{ s }}</option>{% endfor %}</select><button class="btn-brown">بحث</button><a class="btn btn-soft" href="/export/orders.csv">تصدير Excel/CSV</a></form>{{ orders_table(orders, statuses) }}</div>
{% elif section=='places' %}<div class="panel"><h3>إدارة أماكن الطلب</h3><p class="sub">عرض الطلبات حسب المكان</p><div class="grid2"><div><h4>النيابة الإدارية</h4>{% for f in admin_floors %}<a class="btn btn-soft" href="/admin?section=orders&place={{ 'النيابة الإدارية - ' ~ f }}">{{ f }}</a> {% endfor %}</div><div><h4>الكافيه</h4>{% for t in cafe_tables %}<a class="btn btn-soft" href="/admin?section=orders&place={{ 'الكافيه - ' ~ t }}">{{ t }}</a> {% endfor %}</div></div></div>
{% elif section=='menu' %}<div class="panel"><h3>إدارة المنيو</h3><form class="form-grid" method="post" action="/menu/add"><input class="input" name="name" placeholder="اسم الصنف" required><input class="input" name="price" type="number" step="0.01" placeholder="السعر" required><select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select><input class="input" name="image" placeholder="رابط صورة الصنف"><textarea class="input" name="description" placeholder="وصف الصنف"></textarea><button class="btn-brown">إضافة صنف جديد</button></form></div><div class="panel"><div class="card-list">{% for item in menu %}<div class="item-card"><img src="{{ item.image }}"><form method="post" action="/menu/update/{{ item.id }}"><input class="input" name="name" value="{{ item.name }}"><input class="input" name="price" type="number" step="0.01" value="{{ item.price }}"><select name="category">{% for c in categories %}<option {% if item.category==c %}selected{% endif %}>{{ c }}</option>{% endfor %}</select><input class="input" name="image" value="{{ item.image }}"><textarea class="input" name="description">{{ item.description }}</textarea><button class="btn-green">تعديل</button> <a class="btn btn-orange" href="/menu/toggle/{{ item.id }}">{% if item.available %}إيقاف{% else %}تشغيل{% endif %}</a> <a class="btn btn-red" href="/menu/delete/{{ item.id }}" onclick="return confirm('حذف الصنف؟')">حذف</a></form></div>{% endfor %}</div></div>
{% elif section=='inventory' %}<div class="panel"><h3>إدارة المخزون</h3><form class="form-grid" method="post" action="/inventory/add"><input class="input" name="item_name" placeholder="اسم الخام"><input class="input" name="qty" type="number" step="0.01" placeholder="الكمية"><input class="input" name="unit" placeholder="الوحدة"><input class="input" name="min_qty" type="number" step="0.01" placeholder="حد التنبيه"><button class="btn-brown">إضافة مخزون</button></form></div><div class="panel"><table><tr><th>الخامة</th><th>الكمية</th><th>الوحدة</th><th>حد التنبيه</th><th>الحالة</th><th>تعديل</th></tr>{% for i in inventory %}<tr><form method="post" action="/inventory/update/{{ i.id }}"><td><input class="input" name="item_name" value="{{ i.item_name }}"></td><td><input class="input" name="qty" value="{{ i.qty }}"></td><td><input class="input" name="unit" value="{{ i.unit }}"></td><td><input class="input" name="min_qty" value="{{ i.min_qty }}"></td><td>{% if i.qty <= i.min_qty %}<span class="low">قرب النفاد</span>{% else %}<span class="ok">متوفر</span>{% endif %}</td><td><button class="btn-green">حفظ</button></td></form></tr>{% endfor %}</table></div>
{% elif section=='reports' %}<div class="panel"><h3>التقارير</h3><p>تقرير المبيعات اليومية والشهرية والأرباح والمنتجات الأكثر والأقل مبيعًا.</p><a class="btn btn-brown" href="/export/orders.csv">تصدير Excel/CSV</a><button class="btn-soft" onclick="window.print()">تصدير PDF / طباعة</button></div><div class="grid2"><div class="panel"><canvas id="salesChart"></canvas></div><div class="panel"><canvas id="statusChart"></canvas></div></div>
{% elif section=='employees' %}<div class="panel"><h3>إدارة الموظفين</h3><form class="form-grid" method="post" action="/employees/add"><input class="input" name="name" placeholder="اسم الموظف"><select name="role"><option>مدير</option><option>كاشير</option><option>عامل كافيه</option></select><input class="input" name="phone" placeholder="رقم الهاتف"><button class="btn-brown">إضافة موظف</button></form></div><div class="panel"><table><tr><th>الاسم</th><th>الصلاحية</th><th>الهاتف</th><th>الحالة</th><th>إجراء</th></tr>{% for e in employees %}<tr><td>{{ e.name }}</td><td>{{ e.role }}</td><td>{{ e.phone }}</td><td>{% if e.active %}نشط{% else %}متوقف{% endif %}</td><td><a class="btn btn-orange" href="/employees/toggle/{{ e.id }}">إيقاف/تشغيل</a></td></tr>{% endfor %}</table></div>
{% elif section=='notifications' %}<div class="panel"><h3>الإشعارات</h3><p>طلبات جديدة: <b>{{ notifications.new_order_count }}</b></p><h4>تنبيه انخفاض المخزون</h4>{% for n in notifications.low_stock %}<p class="low">{{ n.item_name }}: {{ n.qty }} / حد التنبيه {{ n.min_qty }}</p>{% else %}<p class="ok">لا توجد خامات منخفضة</p>{% endfor %}<h4>أصناف متوقفة</h4>{% for u in notifications.unavailable %}<p>{{ u.name }}</p>{% else %}<p>لا توجد أصناف متوقفة</p>{% endfor %}</div>
{% elif section=='settings' %}<div class="panel"><h3>الإعدادات</h3><form class="form-grid" method="post" action="/settings/save"><input class="input" name="cafe_name" placeholder="اسم الكافيه" value="{{ settings.cafe_name }}"><input class="input" name="logo" placeholder="الشعار" value="{{ settings.logo }}"><input class="input" name="phone" placeholder="رقم الهاتف" value="{{ settings.phone }}"><input class="input" name="printer" placeholder="إعدادات الطباعة" value="{{ settings.printer }}"><input class="input" name="qr_note" placeholder="إعدادات QR" value="{{ settings.qr_note }}"><button class="btn-brown">حفظ الإعدادات</button></form><p>كلمة مرور المدير الحالية داخل متغير ADMIN_PIN ويمكن تغييرها من Render Environment.</p></div>
{% elif section=='logs' %}<div class="panel"><h3>سجل العمليات</h3><table><tr><th>المستخدم</th><th>العملية</th><th>التفاصيل</th><th>الوقت</th></tr>{% for l in logs %}<tr><td>{{ l.user }}</td><td>{{ l.action }}</td><td>{{ l.details }}</td><td>{{ l.created_at }}</td></tr>{% endfor %}</table></div>{% endif %}
</main></div><script>const chartLabels={{ chart.labels|tojson }};const chartValues={{ chart.values|tojson }};const statusCounts={{ chart.status_counts|tojson }};if(document.getElementById('salesChart')){new Chart(document.getElementById('salesChart'),{type:'line',data:{labels:chartLabels,datasets:[{label:'المبيعات',data:chartValues,tension:.35,fill:true}]}})}if(document.getElementById('statusChart')){new Chart(document.getElementById('statusChart'),{type:'doughnut',data:{labels:Object.keys(statusCounts),datasets:[{data:Object.values(statusCounts)}]}})}</script></body></html>
'''

# Jinja macro injected by replacing marker at runtime
ORDERS_TABLE = r'''
{% macro orders_table(orders, statuses) -%}
<div class="table-wrap"><table><thead><tr><th>رقم</th><th>اسم العميل</th><th>مكان الطلب</th><th>العناصر</th><th>الإجمالي</th><th>الحالة</th><th>الوقت</th><th>إجراء</th></tr></thead><tbody>{% for order in orders %}<tr><td>#{{ order.id }}</td><td><b>{{ order.customer_name }}</b></td><td>{{ order.order_place }}</td><td>{% for item in order.order_items %}• {{ item.item_name }} × {{ item.qty }}<br>{% endfor %}</td><td><b>{{ order.total }}</b> جنيه</td><td>{% set cls={'جديد':'s-new','قيد التحضير':'s-prep','جاهز':'s-ready','تم التسليم':'s-done','ملغي':'s-cancel'} %}<span class="badge {{ cls.get(order.status,'s-new') }}">{{ order.status }}</span></td><td>{{ order.created_at }}</td><td>{% for s in statuses %}<a class="btn btn-soft" href="/update-status/{{ order.id }}/{{ s }}">{{ s }}</a> {% endfor %}<a class="btn btn-brown" href="/invoice/{{ order.id }}" target="_blank">طباعة</a> <a class="btn btn-red" href="/delete-order/{{ order.id }}" onclick="return confirm('حذف الطلب؟')">حذف</a></td></tr>{% else %}<tr><td colspan="8">لا توجد طلبات</td></tr>{% endfor %}</tbody></table></div>
{%- endmacro %}
'''
ADMIN_HTML = ADMIN_HTML.replace("<!DOCTYPE html>", ORDERS_TABLE + "\n<!DOCTYPE html>")

INVOICE_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>فاتورة</title><style>body{font-family:Tahoma;margin:30px}.invoice{max-width:420px;margin:auto;border:1px solid #ddd;padding:20px}h2{text-align:center}.row{display:flex;justify-content:space-between;border-bottom:1px dashed #ddd;padding:8px 0}.total{font-size:22px;font-weight:bold}@media print{button{display:none}}</style></head><body><div class="invoice"><h2>☕ كافيه فرفشة</h2><p>رقم الطلب: #{{ order.id }}</p><p>العميل: {{ order.customer_name }}</p><p>المكان: {{ order.order_place }}</p><p>الوقت: {{ order.created_at }}</p><hr>{% for item in items %}<div class="row"><span>{{ item.item_name }} × {{ item.qty }}</span><b>{{ item.price * item.qty }} جنيه</b></div>{% endfor %}<p class="total">الإجمالي: {{ order.total }} جنيه</p><button onclick="window.print()">طباعة</button></div></body></html>
'''

if __name__ == "__main__":
    app.run(debug=False)
