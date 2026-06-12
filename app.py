from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import psycopg2
import psycopg2.extras
from datetime import datetime
import os
import io
import qrcode
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "farfasha_secret_key_change_this_2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "837291")

DEFAULT_MENU = [
    (1, "قهوة تركي", "قهوة تركية أصلية بطعم غني ورائحة مميزة", 15, "مشروبات ساخنة", "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd%sw=900", 1),
    (2, "شاي", "شاي أحمر نقي ومنعش", 10, "مشروبات ساخنة", "https://images.unsplash.com/photo-1576092768241-dec231879fc3%sw=900", 1),
    (3, "كابتشينو", "اسبريسو مع حليب مبخر ورغوة ناعمة", 25, "مشروبات ساخنة", "https://images.unsplash.com/photo-1534778101976-62847782c213%sw=900", 1),
    (4, "موكا", "مزيج رائع من القهوة والشوكولاتة", 30, "مشروبات ساخنة", "https://images.unsplash.com/photo-1572442388796-11668a67e53d%sw=900", 1),
    (5, "قهوة مثلجة", "قهوة باردة ومنعشة", 25, "مشروبات باردة", "https://images.unsplash.com/photo-1461023058943-07fcbe16d735%sw=900", 1),
    (6, "عصير برتقال", "عصير طبيعي طازج", 20, "مشروبات باردة", "https://images.unsplash.com/photo-1621506289937-a8e4df240d0b%sw=900", 1),
    (7, "كيك شوكولاتة", "قطعة كيك غنية بالشوكولاتة", 30, "حلويات", "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62%sw=900", 1),
    (8, "ساندوتش دجاج", "ساندوتش دجاج طازج", 35, "وجبات خفيفة", "https://images.unsplash.com/photo-1553909489-cd47e0907980%sw=900", 1),
]

ORDER_STATUSES = ["جديد", "قيد التحضير", "جاهز", "تم التسليم", "ملغي"]
CATEGORIES = ["مشروبات ساخنة", "مشروبات باردة", "شيشة", "حلويات", "وجبات خفيفة"]


def get_site_base_url():
    base_url = request.url_root.rstrip("/")
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and base_url.startswith("http://"):
        base_url = "https://" + base_url.replace("http://", "", 1)
    return base_url


def get_db():
    """اتصال PostgreSQL على Render باستخدام DATABASE_URL.
    هذا يحفظ الطلبات بشكل دائم ولا تعتمد على ملفات SQLite المؤقتة.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Add PostgreSQL DATABASE_URL in Render Environment Variables."
        )
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )


def column_exists(cur, table, column):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def add_column_if_missing(cur, table, column, definition):
    if not column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def log_action(action):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO activity_log (user_name, action, created_at) VALUES (%s, %s, %s)",
            ("مدير", action, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            table_number TEXT DEFAULT '',
            order_place TEXT DEFAULT '',
            customer_name TEXT DEFAULT 'عميل',
            total NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'جديد',
            created_at TEXT NOT NULL
        )
    """)
    add_column_if_missing(cur, "orders", "customer_name", "TEXT DEFAULT 'عميل'")
    add_column_if_missing(cur, "orders", "order_place", "TEXT DEFAULT ''")
    add_column_if_missing(cur, "orders", "table_number", "TEXT DEFAULT ''")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            item_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price NUMERIC NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price NUMERIC NOT NULL,
            category TEXT NOT NULL,
            image TEXT DEFAULT '',
            available INTEGER DEFAULT 1,
            created_at TEXT DEFAULT ''
        )
    """)

    cur.execute("SELECT COUNT(*) AS c FROM menu_items")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            """
            INSERT INTO menu_items (id, name, description, price, category, image, available, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(x[0], x[1], x[2], x[3], x[4], x[5], x[6], datetime.now().strftime("%Y-%m-%d %H:%M")) for x in DEFAULT_MENU]
        )
        cur.execute("SELECT setval(pg_get_serial_sequence('menu_items','id'), COALESCE((SELECT MAX(id) FROM menu_items), 1), true)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id SERIAL PRIMARY KEY,
            item_name TEXT NOT NULL,
            quantity NUMERIC DEFAULT 0,
            unit TEXT DEFAULT 'وحدة',
            min_quantity NUMERIC DEFAULT 5,
            updated_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id SERIAL PRIMARY KEY,
            user_name TEXT DEFAULT 'مدير',
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)
    defaults = {
        "cafe_name": "كافيه فرفشة",
        "phone": "",
        "logo": "☕",
        "printer": "Default",
        "qr_note": "امسح QR لفتح المنيو"
    }
    for key, value in defaults.items():
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (key, value),
        )

    conn.commit()
    cur.close()
    conn.close()


init_db()


def get_menu_items(active_only=False):
    conn = get_db()
    cur = conn.cursor()
    if active_only:
        cur.execute("SELECT * FROM menu_items WHERE available = 1 ORDER BY id")
    else:
        cur.execute("SELECT * FROM menu_items ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_item_by_id(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM menu_items WHERE id = %s AND available = 1", (item_id,))
    item = cur.fetchone()
    conn.close()
    return dict(item) if item else None


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    menu_items = get_menu_items(active_only=True)
    base_url = get_site_base_url()
    return render_template_string(
        HOME_HTML,
        menu=menu_items,
        qr_url=f"{base_url}/qr",
        menu_url=f"{base_url}/"
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
        item = get_item_by_id(int(cart_item.get("id", 0)))
        qty = int(cart_item.get("qty", 0))
        if item and qty > 0:
            total += float(item["price"]) * qty
            clean_items.append({"name": item["name"], "qty": qty, "price": float(item["price"])})

    if not clean_items:
        return jsonify({"success": False, "message": "لا توجد عناصر صحيحة"})

    conn = get_db()
    cur = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute(
        """
        INSERT INTO orders (table_number, order_place, customer_name, total, status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (order_place, order_place, customer_name, total, "جديد", created_at)
    )
    order_id = cur.fetchone()["id"]
    for item in clean_items:
        cur.execute("INSERT INTO order_items (order_id, item_name, qty, price) VALUES (%s, %s, %s, %s)", (order_id, item["name"], item["qty"], item["price"]))
    cur.execute("INSERT INTO notifications (message, created_at) VALUES (%s, %s)", (f"طلب جديد رقم #{order_id} من {customer_name} - {order_place}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("INSERT INTO activity_log (user_name, action, created_at) VALUES (%s, %s, %s)", (customer_name, f"إضافة طلب رقم #{order_id}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "تم إرسال الطلب بنجاح ✅", "order_id": order_id, "total": total})


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
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders ORDER BY id DESC")
    orders_rows = cur.fetchall()
    orders = []
    for order in orders_rows:
        cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order["id"],))
        order_items = [dict(item) for item in cur.fetchall()]
        orders.append({
            "id": order["id"],
            "order_place": order["order_place"] or order["table_number"],
            "customer_name": order["customer_name"] or "عميل",
            "total": order["total"],
            "status": order["status"],
            "created_at": order["created_at"],
            "order_items": order_items,
        })

    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('جديد','قيد التحضير','جاهز')")
    current_orders = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status = 'تم التسليم' AND created_at LIKE %s", (today + "%",))
    completed_today = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status = 'جديد'")
    waiting_orders = cur.fetchone()["c"]
    cur.execute("SELECT SUM(total) AS s FROM orders WHERE status != 'ملغي' AND created_at LIKE %s", (today + "%",))
    sales_today = cur.fetchone()["s"] or 0
    cur.execute("SELECT SUM(total) AS s FROM orders WHERE status != 'ملغي' AND created_at LIKE %s", (month + "%",))
    sales_month = cur.fetchone()["s"] or 0
    cur.execute("SELECT COUNT(DISTINCT order_place) AS c FROM orders WHERE created_at LIKE %s", (today + "%",))
    active_places = cur.fetchone()["c"]

    cur.execute("""
        SELECT item_name, SUM(qty) AS qty
        FROM order_items
        GROUP BY item_name
        ORDER BY qty DESC
        LIMIT 1
    """)
    top_row = cur.fetchone()
    top_item = top_row["item_name"] if top_row else "لا يوجد"

    cur.execute("""
        SELECT item_name, SUM(qty) AS qty
        FROM order_items
        GROUP BY item_name
        ORDER BY qty DESC
        LIMIT 5
    """)
    top_items = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT item_name, SUM(qty) AS qty
        FROM order_items
        GROUP BY item_name
        ORDER BY qty ASC
        LIMIT 5
    """)
    low_items = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT status, COUNT(*) AS c FROM orders GROUP BY status")
    status_counts = {r["status"]: r["c"] for r in cur.fetchall()}

    cur.execute("SELECT * FROM menu_items ORDER BY id DESC")
    menu_items = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM inventory ORDER BY id DESC")
    inventory = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM employees ORDER BY id DESC")
    employees = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    notifications = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50")
    activity_log = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in cur.fetchall()}

    conn.close()

    base_url = get_site_base_url()
    return render_template_string(
        ADMIN_HTML,
        orders=orders,
        current_orders=current_orders,
        completed_today=completed_today,
        waiting_orders=waiting_orders,
        sales_today=sales_today,
        sales_month=sales_month,
        active_places=active_places,
        top_item=top_item,
        top_items=top_items,
        low_items=low_items,
        status_counts=status_counts,
        menu_items=menu_items,
        inventory=inventory,
        employees=employees,
        notifications=notifications,
        activity_log=activity_log,
        settings=settings,
        statuses=ORDER_STATUSES,
        categories=CATEGORIES,
        menu_url=f"{base_url}/",
        qr_url=f"{base_url}/qr"
    )


@app.route("/update-status/<int:order_id>/<status>")
@admin_required
def update_status(order_id, status):
    if status not in ORDER_STATUSES:
        status = "قيد التحضير"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
    cur.execute("INSERT INTO activity_log (user_name, action, created_at) VALUES (%s, %s, %s)", ("مدير", f"تغيير حالة الطلب #{order_id} إلى {status}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    session["admin_notice"] = f"تم تغيير حالة الطلب #{order_id} إلى {status}"
    return redirect(url_for("admin") + "#orders")


@app.route("/delete-order/<int:order_id>")
@admin_required
def delete_order(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    cur.execute("INSERT INTO activity_log (user_name, action, created_at) VALUES (%s, %s, %s)", ("مدير", f"حذف الطلب #{order_id}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#orders")


@app.route("/invoice/<int:order_id>")
@admin_required
def invoice(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cur.fetchone()
    cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    if not order:
        return "Order not found", 404
    return render_template_string(INVOICE_HTML, order=dict(order), items=items)


@app.route("/menu/add", methods=["POST"])
@admin_required
def menu_add():
    name = request.form.get("name", "").strip()
    price = float(request.form.get("price", 0) or 0)
    category = request.form.get("category", "مشروبات ساخنة")
    description = request.form.get("description", "")
    image = request.form.get("image", "")
    if name and price > 0:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO menu_items (name, description, price, category, image, available, created_at) VALUES (%s, %s, %s, %s, %s, 1, %s)", (name, description, price, category, image, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        conn.close()
        log_action(f"إضافة صنف {name}")
    return redirect(url_for("admin") + "#menu")


@app.route("/menu/toggle/<int:item_id>")
@admin_required
def menu_toggle(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE menu_items SET available = CASE WHEN available = 1 THEN 0 ELSE 1 END WHERE id = %s", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#menu")


@app.route("/menu/delete/<int:item_id>")
@admin_required
def menu_delete(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM menu_items WHERE id = %s", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#menu")


@app.route("/inventory/add", methods=["POST"])
@admin_required
def inventory_add():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO inventory (item_name, quantity, unit, min_quantity, updated_at) VALUES (%s, %s, %s, %s, %s)", (
        request.form.get("item_name", "خامة"),
        float(request.form.get("quantity", 0) or 0),
        request.form.get("unit", "وحدة"),
        float(request.form.get("min_quantity", 5) or 5),
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#inventory")


@app.route("/employees/add", methods=["POST"])
@admin_required
def employees_add():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO employees (name, role, active, created_at) VALUES (%s, %s, 1, %s)", (request.form.get("name", "موظف"), request.form.get("role", "عامل كافيه"), datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#employees")


@app.route("/settings/save", methods=["POST"])
@admin_required
def settings_save():
    conn = get_db()
    cur = conn.cursor()
    for key in ["cafe_name", "phone", "logo", "printer", "qr_note"]:
        cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, request.form.get(key, "")))
    conn.commit()
    conn.close()
    return redirect(url_for("admin") + "#settings")


@app.route("/export.csv")
@admin_required
def export_csv():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, customer_name, order_place, total, status, created_at FROM orders ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    data = "id,customer_name,order_place,total,status,created_at\n"
    for r in rows:
        data += f'{r["id"]},{r["customer_name"]},{r["order_place"]},{r["total"]},{r["status"]},{r["created_at"]}\n'
    buffer = io.BytesIO(data.encode("utf-8-sig"))
    return send_file(buffer, mimetype="text/csv", as_attachment=True, download_name="farfasha_orders.csv")


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
:root{--brown:#5b2b12;--brown2:#7a3d1d;--dark:#1e0f08;--cream:#fffaf4;--paper:#fff;--muted:#84756b;--line:#eaded5;--shadow:0 14px 45px rgba(70,35,15,.10)}*{box-sizing:border-box}body{margin:0;font-family:'Cairo',Tahoma,sans-serif;background:linear-gradient(180deg,#fffaf4,#f5eee7);color:#20120a;padding-bottom:96px}.wrap{max-width:980px;margin:0 auto;padding:14px}.header{position:sticky;top:0;z-index:50;background:rgba(255,250,244,.96);backdrop-filter:blur(18px);padding:12px 14px;border-bottom:1px solid rgba(91,43,18,.08);display:flex;align-items:center;justify-content:space-between}.icon-btn{width:46px;height:46px;border:0;background:#fff;border-radius:17px;box-shadow:0 8px 25px rgba(70,35,15,.08);font-size:23px;position:relative}.header h1{margin:0;font-size:23px;font-weight:900}.count{position:absolute;top:-4px;right:-4px;background:var(--brown);color:#fff;border-radius:99px;min-width:22px;height:22px;font-size:12px;display:grid;place-items:center}.hero{margin-top:14px;border-radius:28px;min-height:235px;background:linear-gradient(90deg,rgba(18,9,5,.98),rgba(42,20,10,.58)),url('https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1400') center/cover;box-shadow:var(--shadow);padding:26px;color:#fff;display:flex;align-items:center;justify-content:flex-end}.hero h2{font-size:32px;margin:8px 0 8px}.tabs{display:flex;gap:12px;overflow:auto;padding:15px 0;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{min-width:110px;height:82px;border:1px solid var(--line);background:#fff;border-radius:18px;box-shadow:0 8px 22px rgba(70,35,15,.07);font-weight:900;color:#3c2516}.tab.active{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.products{display:flex;flex-direction:column;gap:14px}.product{background:#fff;border-radius:22px;box-shadow:0 12px 35px rgba(70,35,15,.08);display:grid;grid-template-columns:140px 1fr;overflow:hidden}.photo{height:150px}.photo img{width:100%;height:100%;object-fit:cover}.info{padding:12px}.info h3{font-size:20px;margin:0 0 4px}.desc{font-size:12px;color:var(--muted);margin:0 0 10px}.bottom{display:flex;justify-content:space-between;gap:6px;align-items:center}.price{font-weight:900;color:var(--brown2)}.qty{display:flex;gap:6px;align-items:center}.qty button,.add{border:0;border-radius:11px;height:32px;font-weight:900}.qty button{width:31px;background:#f1ebe5}.add{width:40px;background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.drawer{position:fixed;left:12px;right:12px;bottom:12px;background:#fff;border-radius:24px;padding:14px;box-shadow:0 22px 70px rgba(50,24,10,.22);z-index:60}.summary{display:flex;align-items:center;justify-content:space-between}.send,.view{border:0;border-radius:15px;padding:12px 14px;font-family:inherit;font-weight:900}.send{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.view{background:#f3eee9}.cart-list{display:none;margin-top:10px;border-top:1px dashed #e7d9ce;padding-top:10px;max-height:50vh;overflow:auto}.cart-list.open{display:block}.form-box{margin-bottom:10px}.form-box label{font-weight:900;color:var(--brown);display:block;margin-bottom:6px}.form-box input,.form-box select{width:100%;border:1px solid var(--line);border-radius:15px;padding:12px;font-family:inherit;background:#fffaf6}.cart-item{display:grid;grid-template-columns:1fr 35px 75px 28px;gap:6px;padding:9px 0;border-bottom:1px dashed #eee}.remove{border:0;background:#fff0ed;color:#c0392b;border-radius:9px}.toast{position:fixed;top:80px;left:50%;transform:translateX(-50%);background:#20120a;color:#fff;padding:12px 18px;border-radius:16px;z-index:90;display:none}.menu-overlay{position:fixed;inset:0;background:rgba(0,0,0,.48);z-index:100;display:none}.menu-overlay.show{display:block}.mobile-menu{position:fixed;top:0;right:-310px;width:300px;height:100vh;background:linear-gradient(180deg,#241107,#100703);color:#fff;z-index:110;padding:24px;transition:.28s}.mobile-menu.show{right:0}.mobile-menu a{display:block;color:#fff;text-decoration:none;padding:15px;border-radius:16px;background:rgba(255,255,255,.08);margin-bottom:10px;font-weight:900}.close-menu{position:absolute;left:16px;top:16px;border:0;background:#fff;color:#5b2b12;width:42px;height:42px;border-radius:50%;font-size:28px}@media(min-width:900px){body{padding-bottom:0}.wrap{margin-right:280px;max-width:900px}.drawer{right:auto;left:22px;top:22px;bottom:auto;width:340px}.cart-list{display:block}.products{display:grid;grid-template-columns:1fr 1fr}.product{grid-template-columns:1fr}.photo{height:185px}.sidebar{display:block}.header{display:none}}

/* ===== FIX: Desktop right sidebar for customer page ===== */
.desktop-sidebar{
    display:none;
}
@media(min-width:900px){
    .desktop-sidebar{
        display:block !important;
        position:fixed !important;
        top:22px !important;
        right:22px !important;
        bottom:22px !important;
        width:245px !important;
        background:linear-gradient(180deg,#241107,#100703) !important;
        border-radius:28px !important;
        color:#fff !important;
        padding:22px !important;
        box-shadow:0 14px 45px rgba(70,35,15,.18) !important;
        z-index:80 !important;
        overflow:auto !important;
    }
    .desktop-sidebar .brand-box{
        margin-bottom:24px;
    }
    .desktop-sidebar h2{
        color:#ffc17d;
        margin:0 0 4px;
        font-size:22px;
        font-weight:900;
    }
    .desktop-sidebar p{
        color:#c9b6a8;
        margin:0 0 18px;
        font-size:13px;
    }
    .desktop-sidebar a{
        display:flex;
        align-items:center;
        gap:12px;
        color:#fff;
        text-decoration:none;
        padding:14px;
        border-radius:16px;
        margin-bottom:8px;
        font-weight:900;
        background:rgba(255,255,255,.05);
    }
    .desktop-sidebar a.active,
    .desktop-sidebar a:hover{
        background:rgba(198,132,63,.30);
    }
    .desktop-sidebar .side-note{
        margin-top:24px;
        padding:14px;
        border-radius:18px;
        background:rgba(255,255,255,.07);
        color:#e8d7c8;
        line-height:1.8;
        font-size:12px;
    }
    .wrap{
        margin-right:290px !important;
        margin-left:390px !important;
        max-width:none !important;
        width:auto !important;
    }
    .drawer{
        position:fixed !important;
        right:auto !important;
        left:22px !important;
        top:22px !important;
        bottom:auto !important;
        width:340px !important;
        max-height:calc(100vh - 44px) !important;
        overflow:auto !important;
    }
    .header{display:none !important;}
}
@media(max-width:899px){
    .desktop-sidebar{display:none !important;}
}
</style>
</head>
<body>
<div class="toast" id="toast"></div>
<div class="menu-overlay" id="overlay"></div>

<aside class="desktop-sidebar">
    <div class="brand-box">
        <h2>☕ كافيه فرفشة</h2>
        <p>نكهة كل لحظة</p>
    </div>
    <a class="active" href="/">🏠 المنيو</a>
    <a href="/login">📋 لوحة المدير</a>
    <a href="{{ qr_url }}" target="_blank">▦ QR للطاولة</a>
    <a href="#cartBox">🛒 السلة</a>
    <div class="side-note">اختر طلبك وحدد مكان التوصيل ثم اضغط إرسال الطلب.</div>
</aside>

<aside class="mobile-menu" id="mobileMenu"><button class="close-menu" id="closeMenu">×</button><h2>☕ كافيه فرفشة</h2><a href="/">🏠 المنيو</a><a href="/login">📋 لوحة المدير</a><a href="{{ qr_url }}" target="_blank">▦ QR</a><a href="#cartBox" onclick="toggleCart();closeMenu();">🛒 السلة</a></aside>
<header class="header"><button class="icon-btn" id="menuBtn">☰</button><h1>كافيه فرفشة ☕</h1><button class="icon-btn" onclick="toggleCart()">🛒<span class="count" id="cartCount">0</span></button></header>
<main class="wrap">
<section class="hero"><div><small>مرحباً بك في</small><h2>كافيه فرفشة 👋</h2><p>اختار طلبك وحدد مكان التوصيل</p></div></section>
<nav class="tabs"><button class="tab active" onclick="filterCategory('all',this)">الكل</button><button class="tab" onclick="filterCategory('مشروبات ساخنة',this)">☕ ساخنة</button><button class="tab" onclick="filterCategory('مشروبات باردة',this)">🥤 باردة</button><button class="tab" onclick="filterCategory('شيشة',this)">💨 شيشة</button><button class="tab" onclick="filterCategory('حلويات',this)">🍰 حلويات</button><button class="tab" onclick="filterCategory('وجبات خفيفة',this)">🥪 خفيفة</button></nav>
<section class="products">{% for item in menu %}<article class="product product-card" data-category="{{ item.category }}"><div class="photo"><img src="{{ item.image }}"></div><div class="info"><h3>{{ item.name }}</h3><p class="desc">{{ item.description }}</p><div class="bottom"><div class="price">{{ item.price }} جنيه</div><div class="qty"><button onclick="changeQty({{ item.id }},-1)">-</button><b id="qty-{{ item.id }}">0</b><button onclick="changeQty({{ item.id }},1)">+</button><button class="add" onclick="addToCart({{ item.id }})">🛒</button></div></div></div></article>{% endfor %}</section>
</main>
<section class="drawer" id="cartBox"><div class="summary"><div><b>الإجمالي</b><br><span id="totalPrice">0</span> جنيه</div><div><button class="view" onclick="toggleCart()">عرض</button><button class="send" onclick="sendOrder()">إرسال</button></div></div><div class="cart-list" id="cartList"><div class="form-box"><label>اسم صاحب الطلب</label><input id="customerName" placeholder="مثال: أحمد محمد"></div><div class="form-box"><label>نوع المكان</label><select id="placeType" onchange="updatePlaceOptions()"><option value="">اختر نوع المكان</option><option value="admin">النيابة الإدارية</option><option value="cafe">الكافيه</option></select></div><div class="form-box"><label>مكان الطلب</label><select id="orderPlace"><option value="">اختر نوع المكان أولاً</option></select></div><div id="cartItems"></div><button class="view" style="width:100%" onclick="clearCart()">مسح الطلب</button></div></section>
<script>
const menu={{ menu|tojson }};let quantities={};let cart=[];
function toast(m){let t=document.getElementById('toast');t.innerText=m;t.style.display='block';setTimeout(()=>t.style.display='none',1800)}
function openMenu(){document.getElementById('mobileMenu').classList.add('show');document.getElementById('overlay').classList.add('show')}function closeMenu(){document.getElementById('mobileMenu').classList.remove('show');document.getElementById('overlay').classList.remove('show')}
document.addEventListener('DOMContentLoaded',()=>{document.getElementById('menuBtn').onclick=openMenu;document.getElementById('closeMenu').onclick=closeMenu;document.getElementById('overlay').onclick=closeMenu});
function toggleCart(){document.getElementById('cartList').classList.toggle('open')}
function updatePlaceOptions(){let type=document.getElementById('placeType').value;let p=document.getElementById('orderPlace');p.innerHTML='';if(type==='admin'){['الدور الأرضي','الأول علوي','الثاني علوي','الثالث علوي','الرابع علوي'].forEach(f=>p.innerHTML+=`<option value="النيابة الإدارية - ${f}">النيابة الإدارية - ${f}</option>`)}else if(type==='cafe'){for(let i=1;i<=20;i++){p.innerHTML+=`<option value="الكافيه - طاولة رقم ${i}">الكافيه - طاولة رقم ${i}</option>`}}else{p.innerHTML='<option value="">اختر نوع المكان أولاً</option>'}}
function filterCategory(c,b){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.product-card').forEach(card=>card.style.display=(c==='all'||card.dataset.category===c)?'grid':'none')}
function changeQty(id,d){quantities[id]=(quantities[id]||0)+d;if(quantities[id]<0)quantities[id]=0;document.getElementById('qty-'+id).innerText=quantities[id]}
function addToCart(id){let q=quantities[id]||0;if(q<=0){toast('اختار الكمية أولاً');return}let item=menu.find(x=>x.id===id);let ex=cart.find(x=>x.id===id);if(ex){ex.qty+=q}else{cart.push({id:item.id,name:item.name,price:item.price,qty:q})}quantities[id]=0;document.getElementById('qty-'+id).innerText=0;renderCart();toast('تمت الإضافة')}
function renderCart(){let box=document.getElementById('cartItems');let total=0,count=0;box.innerHTML='';if(cart.length===0)box.innerHTML='<p>لا يوجد طلبات حالياً</p>';cart.forEach((it,i)=>{total+=it.price*it.qty;count+=it.qty;box.innerHTML+=`<div class="cart-item"><div>${it.name}</div><b>${it.qty}</b><div>${it.price*it.qty}</div><button class="remove" onclick="removeItem(${i})">×</button></div>`});document.getElementById('totalPrice').innerText=total;document.getElementById('cartCount').innerText=count}
function removeItem(i){cart.splice(i,1);renderCart()}function clearCart(){cart=[];renderCart()}
function sendOrder(){if(cart.length===0){toast('السلة فارغة');return}let customerName=document.getElementById('customerName').value.trim();let orderPlace=document.getElementById('orderPlace').value;if(!customerName){toggleCart();toast('اكتب اسم صاحب الطلب');return}if(!orderPlace){toggleCart();toast('اختر مكان الطلب');return}fetch('/send-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_name:customerName,order_place:orderPlace,cart:cart})}).then(r=>r.json()).then(d=>{toast(d.message);if(d.success){alert('✅ تم إرسال الطلب');clearCart();document.getElementById('customerName').value='';document.getElementById('cartList').classList.remove('open')}})}renderCart();
</script></body></html>
'''

LOGIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>دخول المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;800&display=swap" rel="stylesheet"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#2b1308,#fbf4ed);font-family:'Cairo',Tahoma}.box{width:min(92%,420px);background:#fff;border-radius:28px;padding:34px;box-shadow:0 20px 70px rgba(0,0,0,.18);text-align:center}input{width:100%;box-sizing:border-box;padding:16px;border:1px solid #eadfd6;border-radius:16px;text-align:center;font-size:20px;margin:16px 0;font-family:inherit}button{width:100%;padding:16px;border:0;border-radius:16px;background:#5b2b12;color:#fff;font-weight:900;font-family:inherit}.error{background:#fff0ef;color:#c0392b;border-radius:14px;padding:10px}</style></head><body><div class="box"><h1>☕ كافيه فرفشة</h1><p>تسجيل دخول المدير</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="password" name="pin" placeholder="ادخل كود المدير"><button>دخول لوحة التحكم</button></form></div></body></html>
'''

ADMIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>لوحة مدير فرفشة</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet"><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
:root{--dark:#160a04;--brown:#5b2b12;--brown2:#7a3d1d;--bg:#f7efe8;--card:#fff;--line:#eaded5;--muted:#7d6f67;--green:#1f9d55;--red:#c0392b;--orange:#c47b13;--blue:#2563eb;--shadow:0 16px 45px rgba(55,30,15,.10)}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fffaf4,#f5eee7);font-family:'Cairo',Tahoma;color:#24150d}.layout{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#251107,#100703);color:#fff;padding:22px;position:sticky;top:0;height:100vh}.brand{margin-bottom:25px}.brand h1{color:#ffc17d;margin:0}.brand p{color:#c9b6a8;margin:0}.nav a{display:flex;gap:10px;align-items:center;color:#fff;text-decoration:none;padding:13px 14px;border-radius:15px;margin-bottom:8px;font-weight:800}.nav a:hover,.nav a.active{background:rgba(198,132,63,.28)}.main{padding:24px;min-width:0}.top{background:#fff;border-radius:24px;box-shadow:var(--shadow);padding:18px 22px;display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.top h2{margin:0}.top a{background:#f4eee8;color:#3a2518;border-radius:14px;padding:10px 14px;text-decoration:none;font-weight:800}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.stat{background:#fff;border-radius:22px;padding:20px;box-shadow:var(--shadow)}.stat .ico{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;background:#fff2e8;font-size:26px;margin-bottom:10px}.stat b{font-size:30px;color:var(--brown)}.stat p{color:var(--muted);font-weight:800;margin:4px 0}.section{display:none}.section.active{display:block}.panel{background:#fff;border-radius:24px;box-shadow:var(--shadow);padding:20px;margin-top:18px;border:1px solid rgba(90,45,21,.06)}.panel h3{margin:0 0 10px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}input,select,textarea{border:1px solid var(--line);border-radius:14px;padding:11px 12px;font-family:inherit;width:100%;background:#fffaf6}button,.btn{border:0;border-radius:12px;padding:10px 13px;font-family:inherit;font-weight:900;text-decoration:none;display:inline-block;color:#fff;cursor:pointer}.btn-brown{background:var(--brown)}.btn-green{background:var(--green)}.btn-red{background:var(--red)}.btn-orange{background:var(--orange)}.btn-blue{background:var(--blue)}.filters{display:grid;grid-template-columns:1fr 190px 190px;gap:10px;margin:12px 0}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:16px}table{width:100%;border-collapse:collapse;min-width:850px}th{background:linear-gradient(135deg,#693519,#3b1d0f);color:#fff;padding:13px;text-align:right}td{border-bottom:1px solid #f0e5dc;padding:12px;vertical-align:top}.badge{border-radius:12px;padding:6px 10px;font-weight:900;display:inline-block}.badge-new{background:#eaf2ff;color:#2563eb}.badge-work{background:#fff0d2;color:#b8730c}.badge-ready{background:#efe6ff;color:#7c3aed}.badge-done{background:#e5f7ed;color:#148346}.badge-cancel{background:#ffe5e5;color:#c0392b}.cards-list{display:grid;gap:10px}.mini-card{border:1px solid var(--line);background:#fffaf6;border-radius:16px;padding:12px}.muted{color:var(--muted)}.print-only{display:none}@media(max-width:1000px){.layout{display:block}.side{height:auto;position:static}.nav{display:grid;grid-template-columns:1fr 1fr;gap:8px}.main{padding:12px}.stats{grid-template-columns:1fr 1fr}.grid2,.grid3{grid-template-columns:1fr}.filters{grid-template-columns:1fr}.top{display:block}.top a{margin-top:10px}.panel{padding:14px}}@media(max-width:560px){.stats{grid-template-columns:1fr}.nav{grid-template-columns:1fr}th,td{font-size:13px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand"><h1>☕ كافيه فرفشة</h1><p>لوحة المدير الاحترافية</p></div><nav class="nav"><a class="active" href="#dashboard" onclick="showSection('dashboard',this)">🏠 الرئيسية</a><a href="#orders" onclick="showSection('orders',this)">🛒 الطلبات</a><a href="#places" onclick="showSection('places',this)">📍 أماكن الطلب</a><a href="#menu" onclick="showSection('menu',this)">🍹 المنيو</a><a href="#inventory" onclick="showSection('inventory',this)">📦 المخزون</a><a href="#reports" onclick="showSection('reports',this)">📊 التقارير</a><a href="#employees" onclick="showSection('employees',this)">👥 الموظفين</a><a href="#notifications" onclick="showSection('notifications',this)">🔔 الإشعارات</a><a href="#settings" onclick="showSection('settings',this)">⚙️ الإعدادات</a><a href="#logs" onclick="showSection('logs',this)">🧾 سجل العمليات</a><a href="/logout">🚪 خروج</a></nav></aside><main class="main"><div class="top"><h2>لوحة تحكم كافيه فرفشة</h2><div><a href="/">فتح المنيو</a> <a href="{{ qr_url }}" target="_blank">QR</a></div></div><section class="stats"><div class="stat"><div class="ico">🛒</div><b>{{ current_orders }}</b><p>الطلبات الحالية</p></div><div class="stat"><div class="ico">💰</div><b>{{ sales_today }}</b><p>مبيعات اليوم</p></div><div class="stat"><div class="ico">✅</div><b>{{ completed_today }}</b><p>الطلبات المكتملة</p></div><div class="stat"><div class="ico">👑</div><b style="font-size:20px">{{ top_item }}</b><p>أكثر صنف مبيعاً</p></div></section>
<section id="dashboard" class="section active"><div class="grid2"><div class="panel"><h3>إحصائيات المبيعات</h3><canvas id="salesChart"></canvas></div><div class="panel"><h3>حالات الطلبات</h3><canvas id="statusChart"></canvas></div></div><div class="grid3"><div class="panel"><h3>طلبات جديدة قيد الانتظار</h3><b style="font-size:36px;color:var(--brown)">{{ waiting_orders }}</b></div><div class="panel"><h3>المبيعات الشهرية</h3><b style="font-size:36px;color:var(--brown)">{{ sales_month }}</b> جنيه</div><div class="panel"><h3>الأماكن النشطة</h3><b style="font-size:36px;color:var(--brown)">{{ active_places }}</b></div></div></section>
<section id="orders" class="section"><div class="panel"><h3>إدارة الطلبات</h3><div class="filters"><input id="orderSearch" onkeyup="filterOrders()" placeholder="بحث برقم الطلب أو اسم العميل أو المكان"><select id="placeFilter" onchange="filterOrders()"><option value="">كل الأماكن</option><option>النيابة الإدارية</option><option>الكافيه</option></select><select id="statusFilter" onchange="filterOrders()"><option value="">كل الحالات</option>{% for st in statuses %}<option>{{ st }}</option>{% endfor %}</select></div><div class="table-wrap"><table id="ordersTable"><thead><tr><th>رقم</th><th>العميل</th><th>المكان</th><th>الوقت</th><th>العناصر</th><th>الإجمالي</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>{% for o in orders %}<tr data-status="{{ o.status }}"><td>#{{ o.id }}</td><td><b>{{ o.customer_name }}</b></td><td>{{ o.order_place }}</td><td>{{ o.created_at }}</td><td>{% for i in o.order_items %}• {{ i.item_name }} × {{ i.qty }}<br>{% endfor %}</td><td><b>{{ o.total }}</b> جنيه</td><td><span class="badge {% if o.status=='جديد' %}badge-new{% elif o.status=='قيد التحضير' %}badge-work{% elif o.status=='جاهز' %}badge-ready{% elif o.status=='تم التسليم' %}badge-done{% else %}badge-cancel{% endif %}">{{ o.status }}</span></td><td>{% for st in statuses %}<a class="btn btn-blue" href="/update-status/{{ o.id }}/{{ st }}">{{ st }}</a> {% endfor %}<a class="btn btn-brown" target="_blank" href="/invoice/{{ o.id }}">طباعة</a> <a class="btn btn-red" onclick="return confirm('حذف الطلب؟')" href="/delete-order/{{ o.id }}">حذف</a></td></tr>{% endfor %}</tbody></table></div></div></section>
<section id="places" class="section"><div class="panel"><h3>إدارة أماكن الطلب</h3><div class="grid2"><div><h4>النيابة الإدارية</h4><div class="mini-card">الدور الأرضي</div><div class="mini-card">الأول علوي</div><div class="mini-card">الثاني علوي</div><div class="mini-card">الثالث علوي</div><div class="mini-card">الرابع علوي</div></div><div><h4>الكافيه</h4>{% for n in range(1,21) %}<span class="badge badge-work">طاولة {{ n }}</span> {% endfor %}</div></div><p class="muted">استخدم فلتر المكان في إدارة الطلبات لعرض الطلبات حسب المكان.</p></div></section>
<section id="menu" class="section"><div class="panel"><h3>إدارة المنيو</h3><form method="post" action="/menu/add" class="grid3"><input name="name" placeholder="اسم الصنف"><input name="price" type="number" step="0.01" placeholder="السعر"><select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select><input name="image" placeholder="رابط صورة الصنف"><textarea name="description" placeholder="وصف الصنف"></textarea><button class="btn-brown">إضافة صنف</button></form><div class="table-wrap"><table><thead><tr><th>الصنف</th><th>التصنيف</th><th>السعر</th><th>الحالة</th><th>إجراء</th></tr></thead><tbody>{% for m in menu_items %}<tr><td>{{ m.name }}</td><td>{{ m.category }}</td><td>{{ m.price }}</td><td>{{ 'متاح' if m.available else 'متوقف' }}</td><td><a class="btn btn-orange" href="/menu/toggle/{{ m.id }}">إيقاف/تشغيل</a> <a class="btn btn-red" href="/menu/delete/{{ m.id }}">حذف</a></td></tr>{% endfor %}</tbody></table></div></div></section>
<section id="inventory" class="section"><div class="panel"><h3>إدارة المخزون</h3><form method="post" action="/inventory/add" class="grid3"><input name="item_name" placeholder="اسم الخامة"><input name="quantity" type="number" step="0.01" placeholder="الكمية"><input name="unit" placeholder="الوحدة"><input name="min_quantity" type="number" step="0.01" placeholder="حد التنبيه"><button class="btn-brown">إضافة مخزون</button></form><div class="table-wrap"><table><thead><tr><th>الخامة</th><th>الكمية</th><th>تنبيه النفاد</th><th>آخر تحديث</th></tr></thead><tbody>{% for x in inventory %}<tr><td>{{ x.item_name }}</td><td>{{ x.quantity }} {{ x.unit }}</td><td>{% if x.quantity <= x.min_quantity %}<span class="badge badge-cancel">قرب النفاد</span>{% else %}<span class="badge badge-done">جيد</span>{% endif %}</td><td>{{ x.updated_at }}</td></tr>{% endfor %}</tbody></table></div></div></section>
<section id="reports" class="section"><div class="panel"><h3>التقارير</h3><div class="grid3"><div class="mini-card">مبيعات اليوم: <b>{{ sales_today }}</b></div><div class="mini-card">مبيعات الشهر: <b>{{ sales_month }}</b></div><div class="mini-card">الأرباح: <b>{{ sales_today }}</b></div></div><h4>أكثر المنتجات مبيعاً</h4>{% for i in top_items %}<div class="mini-card">{{ i.item_name }} - {{ i.qty }}</div>{% endfor %}<h4>أقل المنتجات مبيعاً</h4>{% for i in low_items %}<div class="mini-card">{{ i.item_name }} - {{ i.qty }}</div>{% endfor %}<br><a class="btn btn-green" href="/export.csv">تصدير Excel CSV</a> <button class="btn-brown" onclick="window.print()">تصدير PDF / طباعة</button></div></section>
<section id="employees" class="section"><div class="panel"><h3>إدارة الموظفين</h3><form method="post" action="/employees/add" class="grid3"><input name="name" placeholder="اسم الموظف"><select name="role"><option>مدير</option><option>كاشير</option><option>عامل كافيه</option></select><button class="btn-brown">إضافة موظف</button></form>{% for e in employees %}<div class="mini-card">{{ e.name }} - {{ e.role }} - {{ 'نشط' if e.active else 'متوقف' }}</div>{% endfor %}</div></section>
<section id="notifications" class="section"><div class="panel"><h3>الإشعارات</h3>{% for n in notifications %}<div class="mini-card">🔔 {{ n.message }}<br><span class="muted">{{ n.created_at }}</span></div>{% endfor %}</div></section>
<section id="settings" class="section"><div class="panel"><h3>الإعدادات</h3><form method="post" action="/settings/save" class="grid2"><input name="cafe_name" value="{{ settings.cafe_name }}" placeholder="اسم الكافيه"><input name="phone" value="{{ settings.phone }}" placeholder="رقم الهاتف"><input name="logo" value="{{ settings.logo }}" placeholder="الشعار"><input name="printer" value="{{ settings.printer }}" placeholder="إعدادات الطباعة"><input name="qr_note" value="{{ settings.qr_note }}" placeholder="إعدادات QR"><button class="btn-brown">حفظ الإعدادات</button></form><p>كلمة مرور المدير الحالية من متغير ADMIN_PIN أو داخل الكود.</p></div></section>
<section id="logs" class="section"><div class="panel"><h3>سجل العمليات</h3>{% for l in activity_log %}<div class="mini-card">{{ l.user_name }} - {{ l.action }}<br><span class="muted">{{ l.created_at }}</span></div>{% endfor %}</div></section>
</main></div><script>
function showSection(id,el){document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('.nav a').forEach(a=>a.classList.remove('active'));if(el)el.classList.add('active')}
function filterOrders(){let q=document.getElementById('orderSearch').value.toLowerCase();let st=document.getElementById('statusFilter').value;let pl=document.getElementById('placeFilter').value;document.querySelectorAll('#ordersTable tbody tr').forEach(r=>{let txt=r.innerText.toLowerCase();let ok=txt.includes(q)&&(!st||r.dataset.status===st)&&(!pl||txt.includes(pl));r.style.display=ok?'':'none'})}
new Chart(document.getElementById('salesChart'),{type:'bar',data:{labels:['اليوم','الشهر'],datasets:[{label:'المبيعات',data:[{{ sales_today }},{{ sales_month }}]}]}});
new Chart(document.getElementById('statusChart'),{type:'doughnut',data:{labels:['جديد','تحضير','جاهز','تم','ملغي'],datasets:[{data:[{{ status_counts.get('جديد',0) }},{{ status_counts.get('قيد التحضير',0) }},{{ status_counts.get('جاهز',0) }},{{ status_counts.get('تم التسليم',0) }},{{ status_counts.get('ملغي',0) }}]}]}});
if(location.hash){let id=location.hash.replace('#','');let link=document.querySelector(`.nav a[href="#${id}"]`);if(document.getElementById(id))showSection(id,link)}
</script></body></html>
'''

INVOICE_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>فاتورة #{{ order.id }}</title><style>body{font-family:Tahoma;padding:25px}table{width:100%;border-collapse:collapse}td,th{border:1px solid #ddd;padding:10px}button{padding:12px 18px}</style></head><body><h2>فاتورة كافيه فرفشة</h2><p>رقم الطلب: #{{ order.id }}</p><p>العميل: {{ order.customer_name }}</p><p>المكان: {{ order.order_place }}</p><p>التاريخ: {{ order.created_at }}</p><table><tr><th>الصنف</th><th>الكمية</th><th>السعر</th></tr>{% for i in items %}<tr><td>{{ i.item_name }}</td><td>{{ i.qty }}</td><td>{{ i.price }}</td></tr>{% endfor %}</table><h3>الإجمالي: {{ order.total }} جنيه</h3><button onclick="window.print()">طباعة</button></body></html>
'''

if __name__ == "__main__":
    app.run(debug=False)
