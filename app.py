from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import sqlite3
from datetime import datetime
import os
import io
import qrcode
from functools import wraps

app = Flask(__name__)
app.secret_key = "farfasha_secret_key_change_this"

# مهم لـ PythonAnywhere
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "farfasha_cafe.db")

ADMIN_PIN = "837291"


# ================= GET SITE URL =================

def get_site_base_url():
    """
    هذه الدالة تجيب رابط الموقع الحقيقي تلقائياً.
    على PythonAnywhere ستعطي:
    https://username.pythonanywhere.com
    """
    base_url = request.url_root.rstrip("/")

    # تصحيح https في بعض الاستضافات
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and base_url.startswith("http://"):
        base_url = "https://" + base_url.replace("http://", "", 1)

    return base_url


# ================= MENU DATA =================

MENU_ITEMS = [
    {
        "id": 1,
        "name": "قهوة تركي",
        "price": 15,
        "category": "hot",
        "image": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=600"
    },
    {
        "id": 2,
        "name": "شاي",
        "price": 10,
        "category": "hot",
        "image": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=600"
    },
    {
        "id": 3,
        "name": "كابتشينو",
        "price": 25,
        "category": "hot",
        "image": "https://images.unsplash.com/photo-1534778101976-62847782c213?w=600"
    },
    {
        "id": 4,
        "name": "موكا",
        "price": 30,
        "category": "hot",
        "image": "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=600"
    },
    {
        "id": 5,
        "name": "قهوة مثلجة",
        "price": 25,
        "category": "cold",
        "image": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=600"
    },
    {
        "id": 6,
        "name": "عصير برتقال",
        "price": 20,
        "category": "juice",
        "image": "https://images.unsplash.com/photo-1621506289937-a8e4df240d0b?w=600"
    },
    {
        "id": 7,
        "name": "كيك شوكولاتة",
        "price": 30,
        "category": "dessert",
        "image": "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=600"
    },
    {
        "id": 8,
        "name": "ساندوتش دجاج",
        "price": 35,
        "category": "sandwich",
        "image": "https://images.unsplash.com/photo-1553909489-cd47e0907980?w=600"
    },
]


# ================= DATABASE =================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ================= HELPERS =================

def get_item_by_id(item_id):
    for item in MENU_ITEMS:
        if item["id"] == item_id:
            return item
    return None


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


# ================= CUSTOMER PAGE =================

@app.route("/")
def home():
    table_number = request.args.get("table", "5")
    base_url = get_site_base_url()

    qr_url = f"{base_url}/qr?table={table_number}"
    menu_url = f"{base_url}/?table={table_number}"

    return render_template_string(
        HOME_HTML,
        menu=MENU_ITEMS,
        table_number=table_number,
        qr_url=qr_url,
        menu_url=menu_url
    )


@app.route("/send-order", methods=["POST"])
def send_order():
    data = request.get_json()

    table_number = data.get("table_number")
    cart = data.get("cart", [])

    if not cart:
        return jsonify({"success": False, "message": "السلة فارغة"})

    total = 0
    clean_items = []

    for cart_item in cart:
        item = get_item_by_id(int(cart_item["id"]))
        qty = int(cart_item["qty"])

        if item and qty > 0:
            total += item["price"] * qty
            clean_items.append({
                "name": item["name"],
                "qty": qty,
                "price": item["price"]
            })

    if not clean_items:
        return jsonify({"success": False, "message": "لا توجد عناصر صحيحة"})

    conn = get_db()
    cur = conn.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    cur.execute("""
        INSERT INTO orders (table_number, total, status, created_at)
        VALUES (?, ?, ?, ?)
    """, (table_number, total, "قيد التحضير", created_at))

    order_id = cur.lastrowid

    for item in clean_items:
        cur.execute("""
            INSERT INTO order_items (order_id, item_name, qty, price)
            VALUES (?, ?, ?, ?)
        """, (order_id, item["name"], item["qty"], item["price"]))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "تم إرسال الطلب بنجاح",
        "order_id": order_id,
        "total": total
    })


# ================= ADMIN LOGIN =================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        pin = request.form.get("pin")

        if pin == ADMIN_PIN:
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            error = "كود الدخول غير صحيح"

    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================= ADMIN DASHBOARD =================

@app.route("/admin")
@admin_required
def admin():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM orders
        ORDER BY id DESC
    """)
    orders_rows = cur.fetchall()

    orders = []

    for order in orders_rows:
        cur.execute("""
            SELECT * FROM order_items
            WHERE order_id = ?
        """, (order["id"],))

        items = cur.fetchall()

        orders.append({
            "id": order["id"],
            "table_number": order["table_number"],
            "total": order["total"],
            "status": order["status"],
            "created_at": order["created_at"],
            "items": items
        })

    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE status = 'قيد التحضير'")
    new_orders = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE created_at LIKE ?", (today + "%",))
    today_orders = cur.fetchone()["count"]

    cur.execute("SELECT SUM(total) AS total FROM orders WHERE created_at LIKE ?", (today + "%",))
    sales = cur.fetchone()["total"] or 0

    cur.execute("SELECT COUNT(DISTINCT table_number) AS count FROM orders WHERE created_at LIKE ?", (today + "%",))
    active_tables = cur.fetchone()["count"]

    conn.close()

    base_url = get_site_base_url()
    menu_url = f"{base_url}/?table=5"
    qr_url = f"{base_url}/qr?table=5"

    return render_template_string(
        ADMIN_HTML,
        orders=orders,
        new_orders=new_orders,
        today_orders=today_orders,
        sales=sales,
        active_tables=active_tables,
        menu_url=menu_url,
        qr_url=qr_url
    )


@app.route("/update-status/<int:order_id>/<status>")
@admin_required
def update_status(order_id, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders
        SET status = ?
        WHERE id = ?
    """, (status, order_id))

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/delete-order/<int:order_id>")
@admin_required
def delete_order(order_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
    cur.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


# ================= QR CODE =================

@app.route("/qr")
def qr_code():
    table_number = request.args.get("table", "5")

    base_url = get_site_base_url()
    url = f"{base_url}/?table={table_number}"

    img = qrcode.make(url)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")


# ================= HTML TEMPLATES =================

HOME_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>كافيه فرفشة</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        * {
            box-sizing: border-box;
            font-family: Arial, Tahoma, sans-serif;
        }

        body {
            margin: 0;
            background: #f6f2ee;
            color: #2d1a10;
        }

        .app {
            display: grid;
            grid-template-columns: 260px 1fr 330px;
            min-height: 100vh;
        }

        .sidebar {
            background: linear-gradient(180deg, #1d0f08, #100803);
            color: white;
            padding: 25px 18px;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 30px;
        }

        .logo-icon {
            font-size: 36px;
        }

        .logo h1 {
            margin: 0;
            color: #f4b06a;
            font-size: 24px;
        }

        .logo p {
            margin: 3px 0 0;
            color: #c9b6a8;
            font-size: 13px;
        }

        .user-card {
            background: rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 15px;
            margin-bottom: 30px;
        }

        .menu-link {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 14px 15px;
            border-radius: 13px;
            color: #eee;
            margin-bottom: 8px;
            text-decoration: none;
            font-weight: bold;
        }

        .menu-link.active {
            background: #8b542e;
        }

        .main {
            padding: 22px;
        }

        .topbar {
            background: #fff;
            border-radius: 20px;
            padding: 16px 22px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 20px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }

        .welcome {
            text-align: center;
        }

        .welcome h2 {
            margin: 0 0 8px;
            font-size: 22px;
        }

        .table-number {
            display: inline-block;
            background: #f0e1d6;
            color: #5b2f18;
            padding: 6px 18px;
            border-radius: 10px;
            font-weight: bold;
        }

        .info-box {
            background: #fff7ef;
            border: 1px solid #ead7c8;
            padding: 12px;
            border-radius: 15px;
            margin-bottom: 15px;
            font-size: 14px;
            line-height: 1.8;
        }

        .info-box a {
            color: #7a3f20;
            font-weight: bold;
        }

        .categories {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            overflow-x: auto;
        }

        .cat-btn {
            border: 1px solid #eaded5;
            background: #fff;
            padding: 12px 20px;
            border-radius: 12px;
            cursor: pointer;
            font-weight: bold;
            color: #4d2b19;
            min-width: 130px;
        }

        .cat-btn.active {
            background: #5b2f18;
            color: #fff;
        }

        .products {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 18px;
        }

        .card {
            background: white;
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 4px 18px rgba(0,0,0,0.06);
        }

        .card img {
            width: 100%;
            height: 115px;
            object-fit: cover;
        }

        .card-body {
            padding: 14px;
            text-align: center;
        }

        .card-body h3 {
            margin: 0 0 8px;
            font-size: 17px;
        }

        .price {
            color: #8b542e;
            font-weight: bold;
            margin-bottom: 12px;
        }

        .qty-row {
            display: flex;
            gap: 8px;
            justify-content: center;
            align-items: center;
        }

        .qty-row button {
            border: none;
            padding: 8px 12px;
            border-radius: 9px;
            cursor: pointer;
            font-weight: bold;
        }

        .add-btn {
            background: #5b2f18;
            color: white;
            width: 55px;
        }

        .cart {
            background: white;
            margin: 22px 22px 22px 0;
            padding: 20px;
            border-radius: 22px;
            height: fit-content;
            box-shadow: 0 4px 20px rgba(0,0,0,0.05);
        }

        .cart h2 {
            margin-top: 0;
        }

        .cart-item {
            display: grid;
            grid-template-columns: 1fr 35px 70px 32px;
            gap: 8px;
            align-items: center;
            border-bottom: 1px dashed #ddd;
            padding: 12px 0;
        }

        .remove {
            border: none;
            background: #f4eeee;
            border-radius: 8px;
            cursor: pointer;
            padding: 7px;
        }

        .total {
            margin: 25px 0 15px;
            font-size: 22px;
            font-weight: bold;
        }

        .send-btn {
            width: 100%;
            padding: 15px;
            border: none;
            border-radius: 14px;
            background: #7a3f20;
            color: white;
            font-size: 17px;
            font-weight: bold;
            cursor: pointer;
        }

        .clear-btn {
            width: 100%;
            margin-top: 12px;
            padding: 13px;
            border: 1px solid #ddd;
            border-radius: 14px;
            background: white;
            color: #333;
            font-weight: bold;
            cursor: pointer;
        }

        .stats {
            margin-top: 18px;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
        }

        .stat-card {
            background: white;
            border-radius: 16px;
            padding: 18px;
            box-shadow: 0 4px 18px rgba(0,0,0,0.04);
        }

        .stat-card strong {
            font-size: 24px;
            color: #7a3f20;
        }

        @media (max-width: 1100px) {
            .app {
                grid-template-columns: 1fr;
            }

            .sidebar {
                display: none;
            }

            .cart {
                margin: 20px;
            }

            .products {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (max-width: 600px) {
            .products {
                grid-template-columns: 1fr;
            }

            .topbar {
                flex-direction: column;
                gap: 10px;
            }

            .stats {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>

<body>

<div class="app">

    <aside class="sidebar">
        <div class="logo">
            <div class="logo-icon">☕</div>
            <div>
                <h1>كافيه فرفشة</h1>
                <p>نكهة كل لحظة</p>
            </div>
        </div>

        <div class="user-card">
            <strong>مدير النظام</strong>
            <p>مدير</p>
        </div>

        <a class="menu-link active" href="/">🏠 لوحة الطلب</a>
        <a class="menu-link" href="/admin">📋 الطلبات</a>
        <a class="menu-link" href="{{ qr_url }}" target="_blank">📱 QR للطاولة</a>
        <a class="menu-link" href="/login">⚙️ دخول المدير</a>
    </aside>

    <main class="main">

        <div class="topbar">
            <div>🔔 <b>2</b></div>

            <div class="welcome">
                <h2>👋 مرحباً بك في كافيه فرفشة</h2>
                <div>رقم الطاولة: <span class="table-number">{{ table_number }}</span></div>
            </div>

            <div>
                ☀️ جاهز للطلب
            </div>
        </div>

        <div class="info-box">
            رابط المنيو:
            <a href="{{ menu_url }}" target="_blank">{{ menu_url }}</a>
            <br>
            رابط الباركود:
            <a href="{{ qr_url }}" target="_blank">{{ qr_url }}</a>
        </div>

        <div class="categories">
            <button class="cat-btn active" onclick="filterCategory('all', this)">كل الأصناف</button>
            <button class="cat-btn" onclick="filterCategory('hot', this)">☕ المشروبات الساخنة</button>
            <button class="cat-btn" onclick="filterCategory('cold', this)">🥤 المشروبات الباردة</button>
            <button class="cat-btn" onclick="filterCategory('juice', this)">🍊 العصائر</button>
            <button class="cat-btn" onclick="filterCategory('dessert', this)">🍰 الحلويات</button>
            <button class="cat-btn" onclick="filterCategory('sandwich', this)">🥪 السندوتشات</button>
        </div>

        <div class="products">

            {% for item in menu %}
            <div class="card product-card" data-category="{{ item.category }}">
                <img src="{{ item.image }}">
                <div class="card-body">
                    <h3>{{ item.name }}</h3>
                    <div class="price">{{ item.price }} جنيه</div>

                    <div class="qty-row">
                        <button onclick="changeQty({{ item.id }}, -1)">-</button>
                        <span id="qty-{{ item.id }}">0</span>
                        <button onclick="changeQty({{ item.id }}, 1)">+</button>
                        <button class="add-btn" onclick="addToCart({{ item.id }})">🛒</button>
                    </div>
                </div>
            </div>
            {% endfor %}

        </div>

        <div class="stats">
            <div class="stat-card"><strong>4</strong><br>طلبات جديدة</div>
            <div class="stat-card"><strong>12</strong><br>إجمالي الطلبات اليوم</div>
            <div class="stat-card"><strong>620</strong><br>إجمالي المبيعات اليوم</div>
            <div class="stat-card"><strong>5</strong><br>عدد الطاولات النشطة</div>
        </div>

    </main>

    <aside class="cart">
        <h2>طلبك الحالي 🛒</h2>

        <div id="cartItems"></div>

        <div class="total">
            الإجمالي: <span id="totalPrice">0</span> جنيه
        </div>

        <button class="send-btn" onclick="sendOrder()">إرسال الطلب ✈️</button>
        <button class="clear-btn" onclick="clearCart()">مسح الطلب 🗑️</button>
    </aside>

</div>


<script>
    const menu = {{ menu|tojson }};
    const tableNumber = "{{ table_number }}";

    let quantities = {};
    let cart = [];

    function filterCategory(category, btn) {
        document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        document.querySelectorAll(".product-card").forEach(card => {
            if (category === "all" || card.dataset.category === category) {
                card.style.display = "block";
            } else {
                card.style.display = "none";
            }
        });
    }

    function changeQty(id, change) {
        if (!quantities[id]) {
            quantities[id] = 0;
        }

        quantities[id] += change;

        if (quantities[id] < 0) {
            quantities[id] = 0;
        }

        document.getElementById("qty-" + id).innerText = quantities[id];
    }

    function addToCart(id) {
        let qty = quantities[id] || 0;

        if (qty <= 0) {
            alert("اختار الكمية أولاً");
            return;
        }

        let item = menu.find(x => x.id === id);
        let exists = cart.find(x => x.id === id);

        if (exists) {
            exists.qty += qty;
        } else {
            cart.push({
                id: item.id,
                name: item.name,
                price: item.price,
                qty: qty
            });
        }

        quantities[id] = 0;
        document.getElementById("qty-" + id).innerText = 0;

        renderCart();
    }

    function renderCart() {
        let cartBox = document.getElementById("cartItems");
        let total = 0;

        cartBox.innerHTML = "";

        if (cart.length === 0) {
            cartBox.innerHTML = "<p>لا يوجد طلبات حالياً</p>";
        }

        cart.forEach((item, index) => {
            total += item.price * item.qty;

            cartBox.innerHTML += `
                <div class="cart-item">
                    <div>${item.name}</div>
                    <div>${item.qty}</div>
                    <div>${item.price * item.qty} جنيه</div>
                    <button class="remove" onclick="removeItem(${index})">×</button>
                </div>
            `;
        });

        document.getElementById("totalPrice").innerText = total;
    }

    function removeItem(index) {
        cart.splice(index, 1);
        renderCart();
    }

    function clearCart() {
        cart = [];
        renderCart();
    }

    function sendOrder() {
        if (cart.length === 0) {
            alert("السلة فارغة");
            return;
        }

        fetch("/send-order", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                table_number: tableNumber,
                cart: cart
            })
        })
        .then(res => res.json())
        .then(data => {
            alert(data.message);

            if (data.success) {
                clearCart();
            }
        });
    }

    renderCart();
</script>

</body>
</html>
"""


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>دخول المدير</title>

    <style>
        body {
            margin: 0;
            background: #f6f2ee;
            font-family: Arial, Tahoma, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
        }

        .login-box {
            background: white;
            width: 360px;
            padding: 30px;
            border-radius: 22px;
            box-shadow: 0 5px 25px rgba(0,0,0,0.08);
            text-align: center;
        }

        h1 {
            color: #6b371d;
        }

        input {
            width: 100%;
            padding: 14px;
            border: 1px solid #ddd;
            border-radius: 12px;
            font-size: 18px;
            text-align: center;
            margin-bottom: 15px;
        }

        button {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 12px;
            background: #6b371d;
            color: white;
            font-size: 17px;
            font-weight: bold;
            cursor: pointer;
        }

        .error {
            color: red;
            margin-bottom: 10px;
        }
    </style>
</head>

<body>

<div class="login-box">
    <h1>☕ كافيه فرفشة</h1>
    <h2>دخول المدير</h2>

    {% if error %}
        <div class="error">{{ error }}</div>
    {% endif %}

    <form method="POST">
        <input type="password" name="pin" placeholder="ادخل كود المدير">
        <button type="submit">دخول</button>
    </form>

    <p>كود المدير موجود داخل ملف app.py</p>
</div>

</body>
</html>
"""


ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>لوحة مدير كافيه فرفشة</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        * {
            box-sizing: border-box;
            font-family: Arial, Tahoma, sans-serif;
        }

        body {
            margin: 0;
            background: #f6f2ee;
            color: #2d1a10;
        }

        .layout {
            display: grid;
            grid-template-columns: 260px 1fr;
            min-height: 100vh;
        }

        .sidebar {
            background: linear-gradient(180deg, #1d0f08, #100803);
            color: white;
            padding: 25px 18px;
        }

        .logo h1 {
            color: #f4b06a;
            margin-bottom: 5px;
        }

        .logo p {
            color: #c9b6a8;
        }

        .link {
            display: block;
            padding: 14px;
            margin: 10px 0;
            color: white;
            text-decoration: none;
            border-radius: 12px;
            font-weight: bold;
        }

        .link.active {
            background: #8b542e;
        }

        .main {
            padding: 25px;
        }

        .topbar {
            background: white;
            padding: 18px 22px;
            border-radius: 18px;
            box-shadow: 0 4px 18px rgba(0,0,0,0.05);
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }

        .info-box {
            background: #fff7ef;
            border: 1px solid #ead7c8;
            padding: 12px;
            border-radius: 15px;
            margin-bottom: 15px;
            font-size: 14px;
            line-height: 1.8;
        }

        .info-box a {
            color: #7a3f20;
            font-weight: bold;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 18px;
            margin-bottom: 25px;
        }

        .stat {
            background: white;
            padding: 22px;
            border-radius: 18px;
            box-shadow: 0 4px 18px rgba(0,0,0,0.05);
        }

        .stat strong {
            font-size: 28px;
            color: #7a3f20;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 4px 18px rgba(0,0,0,0.05);
        }

        th, td {
            padding: 14px;
            border-bottom: 1px solid #eee;
            text-align: center;
            vertical-align: top;
        }

        th {
            background: #7a3f20;
            color: white;
        }

        .status {
            padding: 7px 12px;
            border-radius: 10px;
            background: #fff0d9;
            color: #9a6200;
            font-weight: bold;
        }

        .done {
            background: #e0f7e9;
            color: #11803b;
        }

        .btn {
            padding: 8px 12px;
            text-decoration: none;
            border-radius: 9px;
            color: white;
            display: inline-block;
            margin: 3px;
            font-size: 13px;
        }

        .btn-done {
            background: #218c4b;
        }

        .btn-wait {
            background: #b87916;
        }

        .btn-delete {
            background: #c0392b;
        }

        @media (max-width: 900px) {
            .layout {
                grid-template-columns: 1fr;
            }

            .sidebar {
                display: none;
            }

            .stats {
                grid-template-columns: 1fr;
            }

            table {
                font-size: 12px;
            }
        }
    </style>
</head>

<body>

<div class="layout">

    <aside class="sidebar">
        <div class="logo">
            <h1>☕ كافيه فرفشة</h1>
            <p>لوحة الإدارة</p>
        </div>

        <a class="link" href="/">🏠 صفحة الطلب</a>
        <a class="link active" href="/admin">📋 الطلبات</a>
        <a class="link" href="{{ qr_url }}" target="_blank">📱 QR طاولة 5</a>
        <a class="link" href="/logout">🚪 تسجيل الخروج</a>
    </aside>

    <main class="main">

        <div class="topbar">
            <h2>لوحة تحكم الطلبات</h2>
            <div>مرحباً بك 👋</div>
        </div>

        <div class="info-box">
            رابط فتح المنيو:
            <a href="{{ menu_url }}" target="_blank">{{ menu_url }}</a>
            <br>
            رابط الباركود:
            <a href="{{ qr_url }}" target="_blank">{{ qr_url }}</a>
        </div>

        <div class="stats">
            <div class="stat">
                <strong>{{ new_orders }}</strong>
                <br>طلبات قيد التحضير
            </div>

            <div class="stat">
                <strong>{{ today_orders }}</strong>
                <br>إجمالي الطلبات اليوم
            </div>

            <div class="stat">
                <strong>{{ sales }}</strong>
                <br>إجمالي المبيعات
            </div>

            <div class="stat">
                <strong>{{ active_tables }}</strong>
                <br>الطاولات النشطة
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>رقم الطلب</th>
                    <th>رقم الطاولة</th>
                    <th>الوقت</th>
                    <th>العناصر</th>
                    <th>الإجمالي</th>
                    <th>الحالة</th>
                    <th>الإجراء</th>
                </tr>
            </thead>

            <tbody>
                {% for order in orders %}
                <tr>
                    <td>#{{ order.id }}</td>
                    <td>{{ order.table_number }}</td>
                    <td>{{ order.created_at }}</td>
                    <td>
                        {% for item in order.items %}
                            {{ item.item_name }} × {{ item.qty }}<br>
                        {% endfor %}
                    </td>
                    <td>{{ order.total }} جنيه</td>
                    <td>
                        {% if order.status == "تم التنفيذ" %}
                            <span class="status done">{{ order.status }}</span>
                        {% else %}
                            <span class="status">{{ order.status }}</span>
                        {% endif %}
                    </td>
                    <td>
                        <a class="btn btn-wait" href="/update-status/{{ order.id }}/قيد التحضير">تحضير</a>
                        <a class="btn btn-done" href="/update-status/{{ order.id }}/تم التنفيذ">تم التنفيذ</a>
                        <a class="btn btn-delete" href="/delete-order/{{ order.id }}">حذف</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

    </main>

</div>

</body>
</html>
"""


# ================= RUN APP =================

if __name__ == "__main__":
    app.run(debug=False)