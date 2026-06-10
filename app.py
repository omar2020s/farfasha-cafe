from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import sqlite3
from datetime import datetime
import os
import io
import qrcode
from functools import wraps

app = Flask(__name__)
app.secret_key = "farfasha_secret_key_change_this_2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "farfasha_cafe.db")
ADMIN_PIN = "837291"

ORDER_PLACES = ["النيابة الادارية", "طاولة رقم 1", "طاولة رقم 2"]

MENU_ITEMS = [
    {"id": 1, "name": "قهوة تركي", "desc": "قهوة تركية أصلية بطعم غني ورائحة مميزة", "price": 15, "category": "hot", "image": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=900"},
    {"id": 2, "name": "شاي", "desc": "شاي أحمر نقي ومنعش", "price": 10, "category": "hot", "image": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=900"},
    {"id": 3, "name": "كابتشينو", "desc": "اسبريسو مع حليب مبخر ورغوة ناعمة", "price": 25, "category": "hot", "image": "https://images.unsplash.com/photo-1534778101976-62847782c213?w=900"},
    {"id": 4, "name": "موكا", "desc": "مزيج رائع من القهوة والشوكولاتة", "price": 30, "category": "hot", "image": "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=900"},
    {"id": 5, "name": "قهوة مثلجة", "desc": "قهوة باردة ومنعشة", "price": 25, "category": "cold", "image": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=900"},
    {"id": 6, "name": "عصير برتقال", "desc": "عصير طبيعي طازج", "price": 20, "category": "juice", "image": "https://images.unsplash.com/photo-1621506289937-a8e4df240d0b?w=900"},
    {"id": 7, "name": "كيك شوكولاتة", "desc": "قطعة كيك غنية بالشوكولاتة", "price": 30, "category": "dessert", "image": "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=900"},
    {"id": 8, "name": "ساندوتش دجاج", "desc": "ساندوتش دجاج طازج", "price": 35, "category": "sandwich", "image": "https://images.unsplash.com/photo-1553909489-cd47e0907980?w=900"},
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


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL,
            order_place TEXT DEFAULT 'طاولة رقم 1',
            total REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            customer_name TEXT DEFAULT 'عميل'
        )
    """)
    # Migration for old SQLite databases: add new columns if missing
    cur.execute("PRAGMA table_info(orders)")
    existing_columns = [col[1] for col in cur.fetchall()]
    if "customer_name" not in existing_columns:
        cur.execute("ALTER TABLE orders ADD COLUMN customer_name TEXT DEFAULT 'عميل'")
    if "order_place" not in existing_columns:
        cur.execute("ALTER TABLE orders ADD COLUMN order_place TEXT DEFAULT 'طاولة رقم 1'")

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


def get_item_by_id(item_id):
    return next((item for item in MENU_ITEMS if item["id"] == item_id), None)


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    table_number = request.args.get("table", "5")
    base_url = get_site_base_url()
    return render_template_string(
        HOME_HTML,
        menu=MENU_ITEMS,
        table_number=table_number,
        order_places=ORDER_PLACES,
        qr_url=f"{base_url}/qr",
        menu_url=f"{base_url}/"
    )


@app.route("/send-order", methods=["POST"])
def send_order():
    data = request.get_json() or {}
    order_place = (data.get("order_place") or "طاولة رقم 1").strip()
    if order_place not in ORDER_PLACES:
        order_place = "طاولة رقم 1"
    customer_name = (data.get("customer_name") or "").strip()
    cart = data.get("cart", [])

    if not customer_name:
        return jsonify({"success": False, "message": "من فضلك اكتب اسم صاحب الطلب"})

    if not cart:
        return jsonify({"success": False, "message": "السلة فارغة"})

    total = 0
    clean_items = []
    for cart_item in cart:
        item = get_item_by_id(int(cart_item.get("id", 0)))
        qty = int(cart_item.get("qty", 0))
        if item and qty > 0:
            total += item["price"] * qty
            clean_items.append({"name": item["name"], "qty": qty, "price": item["price"]})

    if not clean_items:
        return jsonify({"success": False, "message": "لا توجد عناصر صحيحة"})

    conn = get_db()
    cur = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "INSERT INTO orders (table_number, order_place, total, status, created_at, customer_name) VALUES (?, ?, ?, ?, ?, ?)",
        (0, order_place, total, "قيد التحضير", created_at, customer_name),
    )
    order_id = cur.lastrowid

    for item in clean_items:
        cur.execute(
            "INSERT INTO order_items (order_id, item_name, qty, price) VALUES (?, ?, ?, ?)",
            (order_id, item["name"], item["qty"], item["price"]),
        )

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "تم إرسال الطلب بنجاح", "order_id": order_id, "total": total})


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
        cur.execute("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))
        order_items = [dict(item) for item in cur.fetchall()]
        orders.append({
            "id": order["id"],
            "order_place": order["order_place"] or "طاولة رقم 1",
            "total": order["total"],
            "status": order["status"],
            "created_at": order["created_at"],
            "customer_name": order["customer_name"] or "عميل",
            "order_items": order_items,
        })

    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE status = 'قيد التحضير'")
    new_orders = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE created_at LIKE ?", (today + "%",))
    today_orders = cur.fetchone()["count"]
    cur.execute("SELECT SUM(total) AS total FROM orders WHERE created_at LIKE ?", (today + "%",))
    sales = cur.fetchone()["total"] or 0
    cur.execute("SELECT COUNT(DISTINCT order_place) AS count FROM orders WHERE created_at LIKE ?", (today + "%",))
    active_tables = cur.fetchone()["count"]
    conn.close()

    base_url = get_site_base_url()
    return render_template_string(
        ADMIN_HTML,
        orders=orders,
        new_orders=new_orders,
        today_orders=today_orders,
        sales=sales,
        active_tables=active_tables,
        menu_url=f"{base_url}/?table=5",
        qr_url=f"{base_url}/qr?table=5",
    )


@app.route("/update-status/<int:order_id>/<status>")
@admin_required
def update_status(order_id, status):
    if status not in ["قيد التحضير", "تم التنفيذ"]:
        status = "قيد التحضير"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--brown:#5b2b12;--brown2:#7a3d1d;--dark:#1e0f08;--cream:#fffaf4;--paper:#fff;--muted:#84756b;--line:#eaded5;--shadow:0 14px 45px rgba(70,35,15,.10);--soft:#f7efe8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html{scroll-behavior:smooth}body{margin:0;font-family:'Cairo',Tahoma,sans-serif;background:linear-gradient(180deg,#fffaf4,#f5eee7);color:#20120a;padding-bottom:88px}.desktop-sidebar{display:none}.wrap{max-width:930px;margin:0 auto;padding:14px}.mobile-header{position:sticky;top:0;z-index:50;background:rgba(255,250,244,.94);backdrop-filter:blur(18px);padding:12px 14px;border-bottom:1px solid rgba(91,43,18,.08);display:flex;align-items:center;justify-content:space-between}.icon-btn{width:46px;height:46px;border:0;background:#fff;border-radius:17px;box-shadow:0 8px 25px rgba(70,35,15,.08);font-size:23px;display:grid;place-items:center;position:relative}.cart-count{position:absolute;top:-4px;right:-4px;background:var(--brown);color:#fff;border-radius:999px;min-width:22px;height:22px;font-size:12px;display:grid;place-items:center}.mobile-header h1{margin:0;font-size:23px;font-weight:900}.hero{margin-top:14px;border-radius:28px;min-height:235px;background:linear-gradient(90deg,rgba(18,9,5,.98),rgba(42,20,10,.58)),url('https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1400') center/cover;box-shadow:var(--shadow);padding:26px;display:flex;align-items:center;justify-content:flex-end;color:#fff;overflow:hidden}.hero small{color:#f3d7be;font-weight:700;font-size:18px}.hero h2{font-size:32px;line-height:1.25;margin:8px 0 14px;font-weight:900}.hero p{margin:0;color:#ffe7cf}.table-chip{display:inline-flex;align-items:center;gap:9px;margin-top:14px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.16);border-radius:18px;padding:9px 14px;font-weight:800}.table-chip b{background:#fff;color:var(--brown);border-radius:12px;padding:1px 13px}.links-card{margin:18px 0;background:rgba(255,255,255,.78);border:1px solid var(--line);box-shadow:0 10px 30px rgba(70,35,15,.06);border-radius:22px;display:grid;grid-template-columns:1fr 1fr;overflow:hidden}.links-card>div{padding:16px;display:flex;align-items:center;justify-content:center;gap:12px}.links-card>div:first-child{border-left:1px solid var(--line)}.round-icon{width:48px;height:48px;border-radius:50%;background:#f0e6dd;color:var(--brown);display:grid;place-items:center;font-size:24px;flex:0 0 auto}.links-card b{color:#5b2b12}.links-card span{font-size:13px;color:#5f5047}.tabs{display:flex;gap:12px;overflow:auto;padding:7px 0 13px;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{min-width:112px;height:86px;border:1px solid var(--line);background:#fff;border-radius:18px;box-shadow:0 8px 22px rgba(70,35,15,.07);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;font-weight:800;color:#3c2516;cursor:pointer}.tab.active{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff;border-color:transparent;box-shadow:0 12px 26px rgba(91,43,18,.28)}.section-title{display:flex;align-items:center;gap:16px;justify-content:center;margin:20px 0 16px;font-size:25px;font-weight:900}.section-title:before,.section-title:after{content:'';height:1px;background:#eaded5;flex:1}.products{display:flex;flex-direction:column;gap:16px}.product{background:#fff;border:1px solid rgba(91,43,18,.06);box-shadow:0 12px 35px rgba(70,35,15,.08);border-radius:23px;display:grid;grid-template-columns:38% 1fr;overflow:hidden;min-height:176px}.photo{position:relative;min-height:176px}.photo img{width:100%;height:100%;object-fit:cover;display:block}.heart{position:absolute;top:13px;right:13px;color:#fff;font-size:28px;text-shadow:0 2px 8px #000}.info{padding:22px;display:flex;flex-direction:column;justify-content:space-between;min-width:0}.info h3{font-size:24px;margin:0 0 6px;font-weight:900}.desc{margin:0;color:var(--muted);font-size:14px;line-height:1.7}.bottom{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:16px}.price{font-weight:900;color:var(--brown2);font-size:18px;white-space:nowrap}.qty{display:flex;align-items:center;gap:10px}.qty button{border:0;background:#f2efec;width:36px;height:36px;border-radius:12px;font-weight:900;font-size:18px}.qty b{min-width:18px;text-align:center;font-size:18px}.add{border:0;background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff;width:54px;height:42px;border-radius:14px;font-size:19px;box-shadow:0 10px 22px rgba(91,43,18,.25)}.cart-drawer{position:fixed;inset:auto 12px 12px 12px;background:#fff;border:1px solid rgba(91,43,18,.08);border-radius:24px;padding:14px;box-shadow:0 22px 70px rgba(50,24,10,.22);z-index:60}.cart-summary{display:flex;align-items:center;justify-content:space-between;gap:12px}.bag{width:62px;height:62px;border-radius:50%;background:#f3e9e1;display:grid;place-items:center;font-size:27px}.cart-total b{font-size:20px}.cart-actions{display:flex;gap:10px;align-items:center}.view-cart,.send-order{border:0;border-radius:16px;padding:13px 17px;font-family:inherit;font-weight:900}.view-cart{background:#f3eee9;color:#4b2b1a}.send-order{background:linear-gradient(135deg,#6f3516,#3f1c0a);color:#fff}.cart-list{display:none;margin-top:12px;border-top:1px dashed #e7d9ce;padding-top:10px;max-height:42vh;overflow:auto}.cart-list.open{display:block}.cart-item{display:grid;grid-template-columns:1fr 36px 80px 30px;align-items:center;gap:8px;padding:10px 0;border-bottom:1px dashed #eee;font-size:14px}.remove{border:0;background:#fff0ed;color:#c0392b;width:30px;height:30px;border-radius:10px}.empty{color:var(--muted);text-align:center;padding:12px}.clear{width:100%;border:1px solid var(--line);background:#fff;color:#4b2b1a;border-radius:15px;padding:12px;margin-top:10px;font-family:inherit;font-weight:800}.customer-box{margin-top:12px;border-top:1px dashed #e7d9ce;padding-top:12px}.customer-box label{display:block;font-weight:900;color:#5b2b12;margin-bottom:7px}.customer-box input{width:100%;border:1px solid var(--line);border-radius:16px;padding:13px 14px;font-family:inherit;font-size:15px;background:#fffaf6;outline:none}.customer-box input:focus{border-color:#7a3d1d;box-shadow:0 0 0 3px rgba(122,61,29,.10)}.place-box{margin-top:12px}.place-box label{display:block;font-weight:900;color:#5b2b12;margin-bottom:7px}.place-box select{width:100%;border:1px solid var(--line);border-radius:16px;padding:13px 14px;font-family:inherit;font-size:15px;background:#fffaf6;outline:none;color:#2b170c}.place-box select:focus{border-color:#7a3d1d;box-shadow:0 0 0 3px rgba(122,61,29,.10)}.toast{position:fixed;top:80px;left:50%;transform:translateX(-50%);background:#20120a;color:#fff;padding:12px 18px;border-radius:16px;z-index:90;display:none;box-shadow:0 15px 35px rgba(0,0,0,.22)}
@media(min-width:1051px){body{padding-bottom:0}.desktop-sidebar{display:block;position:fixed;top:22px;right:22px;bottom:22px;width:245px;background:linear-gradient(180deg,#241107,#100703);border-radius:28px;color:#fff;padding:22px;box-shadow:var(--shadow)}.desktop-sidebar h2{color:#ffc17d;margin:0 0 4px}.desktop-sidebar p{color:#c9b6a8;margin:0 0 22px}.desktop-sidebar a{display:flex;gap:12px;color:#fff;text-decoration:none;padding:14px;border-radius:16px;margin-bottom:8px;font-weight:800}.desktop-sidebar a.active,.desktop-sidebar a:hover{background:rgba(198,132,63,.26)}.wrap{margin-right:290px;max-width:1050px}.mobile-header{display:none}.hero{min-height:265px}.products{display:grid;grid-template-columns:1fr 1fr}.product{grid-template-columns:1fr}.photo{height:185px}.cart-drawer{right:auto;left:22px;top:22px;bottom:auto;width:330px}.cart-list{display:block;max-height:55vh}.cart-summary{margin-bottom:8px}.view-cart{display:none}}
@media(max-width:620px){.wrap{padding:12px}.hero{min-height:220px;padding:23px;border-radius:25px;background-position:center}.hero h2{font-size:27px}.hero small{font-size:16px}.links-card{grid-template-columns:1fr}.links-card>div:first-child{border-left:0;border-bottom:1px solid var(--line)}.tab{min-width:100px;height:78px;font-size:13px}.section-title{font-size:21px;gap:10px}.product{grid-template-columns:1fr;min-height:0}.photo{height:178px;min-height:178px}.info{padding:18px}.info h3{font-size:23px}.bottom{gap:8px}.qty{gap:8px}.qty button{width:34px;height:34px}.add{width:48px;height:39px}.cart-actions{gap:7px}.view-cart,.send-order{padding:12px 11px}.cart-item{grid-template-columns:1fr 30px 70px 26px}.bag{width:54px;height:54px}}
</style>
</head>
<body>
<div class="toast" id="toast"></div>
<aside class="desktop-sidebar"><h2>كافيه فرفشة ☕</h2><p>نكهة كل لحظة</p><a class="active" href="/">🏠 المنيو</a><a href="/login">📋 لوحة المدير</a><a href="{{ qr_url }}" target="_blank">▦ QR للطاولة</a></aside>
<header class="mobile-header"><button class="icon-btn">☰</button><h1>كافيه فرفشة ☕</h1><button class="icon-btn" onclick="toggleCart()">🛒<span class="cart-count" id="cartCount">0</span></button></header>
<main class="wrap">
<section class="hero"><div><small>مرحباً بك في</small><h2>كافيه فرفشة 👋</h2><p>لذيذ يبدأ من هنا ✨</p><div class="table-chip">مكان الطلب <b id="selectedPlaceChip">طاولة رقم 1</b></div></div></section>
<section class="links-card"><div><div><b>رابط المنيو</b><br><span>شارك المنيو مع أصدقائك</span></div><div class="round-icon">🔗</div></div><div><div><b>رابط الباركود</b><br><span>امسح لفتح المنيو</span></div><div class="round-icon">▦</div></div></section>
<nav class="tabs"><button class="tab active" onclick="filterCategory('all',this)">▦<span>كل الأصناف</span></button><button class="tab" onclick="filterCategory('hot',this)">☕<span>المشروبات الساخنة</span></button><button class="tab" onclick="filterCategory('cold',this)">🥤<span>المشروبات الباردة</span></button><button class="tab" onclick="filterCategory('juice',this)">🍊<span>العصائر</span></button><button class="tab" onclick="filterCategory('dessert',this)">🍰<span>الحلويات</span></button><button class="tab" onclick="filterCategory('sandwich',this)">🥪<span>السندوتشات</span></button></nav>
<div class="section-title">المشروبات الساخنة ☕</div>
<section class="products">{% for item in menu %}<article class="product product-card" data-category="{{ item.category }}"><div class="photo"><img src="{{ item.image }}" alt="{{ item.name }}"><span class="heart">♡</span></div><div class="info"><div><h3>{{ item.name }}</h3><p class="desc">{{ item.desc }}</p></div><div class="bottom"><div class="price">{{ item.price }} جنيه</div><div class="qty"><button onclick="changeQty({{ item.id }},-1)">-</button><b id="qty-{{ item.id }}">0</b><button onclick="changeQty({{ item.id }},1)">+</button><button class="add" onclick="addToCart({{ item.id }})">🛒</button></div></div></div></article>{% endfor %}</section>
</main>
<section class="cart-drawer" id="cartBox"><div class="cart-summary"><div class="bag">🛍️</div><div class="cart-total"><b>الإجمالي</b><br><span id="totalPrice">0</span> جنيه</div><div class="cart-actions"><button class="view-cart" onclick="toggleCart()">عرض السلة</button><button class="send-order" onclick="sendOrder()">إرسال</button></div></div><div class="cart-list" id="cartList"><div class="customer-box"><label for="customerName">اسم صاحب الطلب</label><input id="customerName" type="text" placeholder="مثال: أحمد محمد" autocomplete="name"></div><div class="place-box"><label for="orderPlace">مكان الطلب</label><select id="orderPlace" onchange="updatePlaceChip()">{% for place in order_places %}<option value="{{ place }}">{{ place }}</option>{% endfor %}</select></div><div id="cartItems"></div><button class="clear" onclick="clearCart()">مسح الطلب 🗑️</button></div></section>
<script>
const menu={{ menu|tojson }}; let quantities={}; let cart=[];
function showToast(msg){let t=document.getElementById('toast');t.innerText=msg;t.style.display='block';setTimeout(()=>t.style.display='none',1800)}
function updatePlaceChip(){const p=document.getElementById('orderPlace');const chip=document.getElementById('selectedPlaceChip');if(p&&chip){chip.innerText=p.value}}
function toggleCart(){document.getElementById('cartList').classList.toggle('open')}
function filterCategory(category,btn){document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.product-card').forEach(card=>{card.style.display=(category==='all'||card.dataset.category===category)?'grid':'none';});}
function changeQty(id,change){quantities[id]=(quantities[id]||0)+change;if(quantities[id]<0)quantities[id]=0;document.getElementById('qty-'+id).innerText=quantities[id];}
function addToCart(id){let qty=quantities[id]||0;if(qty<=0){showToast('اختار الكمية أولاً');return;}let item=menu.find(x=>x.id===id);let exists=cart.find(x=>x.id===id);if(exists){exists.qty+=qty}else{cart.push({id:item.id,name:item.name,price:item.price,qty:qty})}quantities[id]=0;document.getElementById('qty-'+id).innerText=0;renderCart();showToast('تمت الإضافة إلى السلة')}
function renderCart(){let box=document.getElementById('cartItems');let total=0;let count=0;box.innerHTML='';if(cart.length===0)box.innerHTML='<div class="empty">لا يوجد طلبات حالياً</div>';cart.forEach((item,index)=>{total+=item.price*item.qty;count+=item.qty;box.innerHTML+=`<div class="cart-item"><div>${item.name}</div><b>${item.qty}</b><div>${item.price*item.qty} جنيه</div><button class="remove" onclick="removeItem(${index})">×</button></div>`});document.getElementById('totalPrice').innerText=total;document.getElementById('cartCount').innerText=count;}
function removeItem(index){cart.splice(index,1);renderCart()} function clearCart(){cart=[];renderCart()}
function sendOrder(){
    if(cart.length===0){showToast('السلة فارغة');return;}
    const customerNameInput=document.getElementById('customerName');
    const orderPlaceInput=document.getElementById('orderPlace');
    const customerName=customerNameInput ? customerNameInput.value.trim() : '';
    const orderPlace=orderPlaceInput ? orderPlaceInput.value : 'طاولة رقم 1';
    if(!customerName){
        document.getElementById('cartList').classList.add('open');
        if(customerNameInput){customerNameInput.focus();}
        showToast('من فضلك اكتب اسم صاحب الطلب');
        return;
    }
    fetch('/send-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_place:orderPlace,customer_name:customerName,cart:cart})}).then(r=>r.json()).then(data=>{showToast(data.message);if(data.success){alert('✅ تم إرسال الطلب باسم: '+customerName+'\n📍 مكان الطلب: '+orderPlace);clearCart();if(customerNameInput){customerNameInput.value='';}document.getElementById('cartList').classList.remove('open')}})
}
renderCart();
</script>
</body></html>
'''

LOGIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>دخول المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;800&display=swap" rel="stylesheet"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#2b1308,#fbf4ed);font-family:'Cairo',Tahoma,sans-serif}.box{width:min(92%,420px);background:#fff;border-radius:28px;padding:34px;box-shadow:0 20px 70px rgba(0,0,0,.18);text-align:center}.logo{font-size:50px}.box h1{margin:8px 0;color:#5a2d15}.box p{color:#77685f}input{width:100%;box-sizing:border-box;padding:16px;border:1px solid #eadfd6;border-radius:16px;text-align:center;font-size:20px;margin:16px 0;font-family:inherit}button{width:100%;padding:16px;border:0;border-radius:16px;background:linear-gradient(135deg,#7b3f20,#4b230f);color:#fff;font-weight:900;font-size:17px;font-family:inherit}.error{background:#fff0ef;color:#c0392b;border-radius:14px;padding:10px;margin:10px 0}</style></head><body><div class="box"><div class="logo">☕</div><h1>كافيه فرفشة</h1><p>تسجيل دخول المدير</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="password" name="pin" placeholder="ادخل كود المدير"><button type="submit">دخول لوحة التحكم</button></form></div></body></html>
'''

ADMIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>لوحة المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet"><style>
:root{--brown:#3b1d0f;--brown2:#7b3f20;--gold:#c6843f;--cream:#fbf7f2;--line:#eee1d7;--muted:#7d6f67;--green:#209653;--red:#c0392b;--orange:#c47b13;--shadow:0 16px 45px rgba(55,30,15,.10)}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fffaf4,#f5efe8);font-family:'Cairo',Tahoma,sans-serif;color:#24150d}.layout{display:grid;grid-template-columns:250px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#251107,#120804);color:#fff;padding:22px;position:sticky;top:0;height:100vh;overflow:hidden}.brand{display:flex;gap:12px;align-items:center;margin-bottom:30px}.brand .icon{width:52px;height:52px;border-radius:18px;background:rgba(255,255,255,.08);display:grid;place-items:center;font-size:30px}.brand h1{font-size:22px;color:#ffc17d;margin:0}.brand p{margin:0;color:#ccb8a7;font-size:12px}.nav a{display:flex;align-items:center;gap:12px;text-decoration:none;color:#fff;padding:14px;border-radius:16px;margin-bottom:8px;font-weight:800}.nav a.active,.nav a:hover{background:rgba(198,132,63,.28)}.main{padding:26px;min-width:0}.top{height:70px;background:#fff;border:1px solid rgba(90,45,21,.06);border-radius:24px;box-shadow:var(--shadow);display:flex;align-items:center;justify-content:space-between;padding:0 22px;margin-bottom:24px}.top h2{margin:0;font-size:28px}.top-actions{display:flex;gap:10px}.top-actions a{border:0;text-decoration:none;background:#f4eee8;color:#3a2518;border-radius:14px;padding:11px 15px;font-weight:800}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stat{background:#fff;border-radius:24px;padding:22px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06);min-height:150px}.stat .circle{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:#fff2e8;font-size:27px;margin-bottom:12px}.stat b{font-size:32px;color:#5a2d15}.stat p{margin:6px 0;color:var(--muted);font-weight:700}.links{margin:18px 0;background:#fff7ef;border:1px solid var(--line);border-radius:22px;padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px}.links a{color:#5a2d15;font-weight:800;word-break:break-word}.panel{background:#fff;border-radius:26px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06);padding:22px;margin-top:18px}.panel h3{margin:0 0 4px;font-size:24px}.filters{display:flex;gap:10px;margin:14px 0}.filters input,.filters select{border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-family:inherit;min-width:160px}.table-wrap{overflow:auto;border-radius:18px;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;background:#fff;min-width:850px}th{background:linear-gradient(135deg,#693519,#3b1d0f);color:#fff;padding:15px;text-align:right}td{padding:15px;border-bottom:1px solid #f0e5dc;vertical-align:top}.badge{display:inline-flex;align-items:center;gap:6px;border-radius:12px;padding:7px 11px;font-weight:800;font-size:13px}.wait{background:#fff0d2;color:#b8730c}.done{background:#e5f7ed;color:#148346}.actions{display:flex;gap:7px;flex-wrap:wrap}.btn{border:0;text-decoration:none;border-radius:12px;padding:9px 12px;color:#fff;font-weight:800;display:inline-block}.b-orange{background:var(--orange)}.b-green{background:var(--green)}.b-red{background:var(--red)}.mini-panels{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:18px}.mini{background:#fff;border-radius:24px;padding:20px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06)}.mobile-title{display:none}
@media(max-width:1000px){.layout{display:block}.side{display:none}.main{padding:14px}.mobile-title{display:block;position:sticky;top:0;z-index:10;background:rgba(255,250,244,.92);backdrop-filter:blur(12px);padding:15px 10px;border-bottom:1px solid #eee}.mobile-title h1{margin:0;font-size:24px}.top{display:none}.grid{grid-template-columns:1fr 1fr}.links{grid-template-columns:1fr}.mini-panels{grid-template-columns:1fr}.panel{padding:14px;border-radius:22px}.filters{display:block}.filters input,.filters select{width:100%;margin-bottom:8px}.stat{min-height:130px}.stat b{font-size:28px}}
@media(max-width:560px){.grid{grid-template-columns:1fr}.main{padding:10px}.stat{display:flex;align-items:center;gap:18px;min-height:110px}.stat .circle{margin:0}.links{font-size:13px}.table-wrap{border-radius:16px}th,td{padding:12px;font-size:13px}.actions{display:grid}.btn{text-align:center}.panel h3{font-size:21px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand"><div class="icon">☕</div><div><h1>كافيه فرفشة</h1><p>لوحة تحكم المدير</p></div></div><nav class="nav"><a class="active" href="/admin">📊 الرئيسية</a><a href="/admin">📋 الطلبات</a><a href="/">☕ فتح المنيو</a><a href="{{ qr_url }}" target="_blank">▦ رابط الباركود</a><a href="/logout">🚪 تسجيل خروج</a></nav></aside><main class="main"><div class="mobile-title"><h1>لوحة تحكم الطلبات ☕</h1></div><div class="top"><h2>نظرة عامة</h2><div class="top-actions"><a href="/">فتح المنيو</a><a href="{{ qr_url }}" target="_blank">QR</a><a href="/logout">تسجيل خروج</a></div></div><section class="grid"><div class="stat"><div class="circle">⏱️</div><div><b>{{ new_orders }}</b><p>طلبات قيد التحضير</p></div></div><div class="stat"><div class="circle">📋</div><div><b>{{ today_orders }}</b><p>إجمالي الطلبات اليوم</p></div></div><div class="stat"><div class="circle">💰</div><div><b>{{ sales }}</b><p>إجمالي المبيعات</p></div></div><div class="stat"><div class="circle">🪑</div><div><b>{{ active_tables }}</b><p>أماكن الطلب النشطة</p></div></div></section><div class="links"><div><b>رابط فتح المنيو:</b><br><a href="{{ menu_url }}">{{ menu_url }}</a></div><div><b>رابط الباركود:</b><br><a href="{{ qr_url }}">{{ qr_url }}</a></div></div><section class="panel"><h3>الطلبات الأخيرة</h3><p style="color:#7d6f67;margin:4px 0">عرض وإدارة جميع الطلبات</p><div class="filters"><input id="searchInput" onkeyup="filterOrders()" placeholder="بحث باسم العميل أو رقم الطلب أو مكان الطلب..."><select id="statusFilter" onchange="filterOrders()"><option value="">كل الحالات</option><option value="قيد التحضير">قيد التحضير</option><option value="تم التنفيذ">تم التنفيذ</option></select></div><div class="table-wrap"><table id="ordersTable"><thead><tr><th>رقم الطلب</th><th>اسم العميل</th><th>مكان الطلب</th><th>الوقت</th><th>العناصر</th><th>الإجمالي</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>{% for order in orders %}<tr data-status="{{ order.status }}"><td>#{{ order.id }}</td><td><b>{{ order.customer_name }}</b></td><td>{{ order.order_place }}</td><td>{{ order.created_at }}</td><td>{% for item in order.order_items %}• {{ item["item_name"] }} × {{ item["qty"] }}<br>{% endfor %}</td><td><b>{{ order.total }}</b><br>جنيه</td><td>{% if order.status == "تم التنفيذ" %}<span class="badge done">● {{ order.status }}</span>{% else %}<span class="badge wait">● {{ order.status }}</span>{% endif %}</td><td><div class="actions"><a class="btn b-orange" href="/update-status/{{ order.id }}/قيد التحضير">تحضير</a><a class="btn b-green" href="/update-status/{{ order.id }}/تم التنفيذ">تم</a><a class="btn b-red" href="/delete-order/{{ order.id }}" onclick="return confirm('هل تريد حذف الطلب؟')">حذف</a></div></td></tr>{% endfor %}</tbody></table></div></section><section class="mini-panels"><div class="mini"><h4>إحصائيات سريعة ⚡</h4><p>متوسط قيمة الطلب: <b>{{ (sales / today_orders)|round(1) if today_orders else 0 }}</b> جنيه</p><p>عدد الطلبات الجديدة: <b>{{ new_orders }}</b></p></div><div class="mini"><h4>أكثر المنتجات طلبًا 👑</h4><p>شاي - كابتشينو - قهوة تركي</p></div><div class="mini"><h4>ملاحظات سريعة 📝</h4><p style="color:#7d6f67">لا توجد ملاحظات حالياً</p></div></section></main></div><script>function filterOrders(){let q=document.getElementById('searchInput').value.toLowerCase();let s=document.getElementById('statusFilter').value;document.querySelectorAll('#ordersTable tbody tr').forEach(r=>{let text=r.innerText.toLowerCase();let okText=text.includes(q);let okStatus=!s||r.dataset.status===s;r.style.display=(okText&&okStatus)?'':'none';});}</script></body></html>
'''

if __name__ == "__main__":
    app.run(debug=False)
