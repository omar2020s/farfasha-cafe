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

# =====================================================
# PostgreSQL DATABASE SETTINGS
# =====================================================
# على Render لازم تضيف Environment Variable باسم DATABASE_URL
# مثال:
# postgresql://user:password@host:5432/database
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "837291")

MENU_ITEMS = [
    {"id": 1, "name": "قهوة تركي", "desc": "قهوة تركية أصلية بطعم غني", "price": 15, "category": "hot", "image": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=900"},
    {"id": 2, "name": "شاي", "desc": "شاي أحمر نقي ومنعش", "price": 10, "category": "hot", "image": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=900"},
    {"id": 3, "name": "كابتشينو", "desc": "اسبريسو مع حليب مبخر ورغوة ناعمة", "price": 25, "category": "hot", "image": "https://images.unsplash.com/photo-1534778101976-62847782c213?w=900"},
    {"id": 4, "name": "موكا", "desc": "مزيج القهوة والشوكولاتة", "price": 30, "category": "hot", "image": "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=900"},
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
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Add PostgreSQL DATABASE_URL in Render Environment Variables."
        )
    # sslmode=require مناسب لقواعد بيانات Render الخارجية والداخلية
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            table_number INTEGER NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            item_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# إنشاء الجداول تلقائياً عند تشغيل Render
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
        qr_url=f"{base_url}/qr?table={table_number}",
        menu_url=f"{base_url}/?table={table_number}"
    )


@app.route("/send-order", methods=["POST"])
def send_order():
    data = request.get_json() or {}
    table_number = data.get("table_number", "5")
    cart = data.get("cart", [])

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
        """
        INSERT INTO orders (table_number, total, status, created_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (int(table_number), total, "قيد التحضير", created_at)
    )
    order_id = cur.fetchone()["id"]

    for item in clean_items:
        cur.execute(
            """
            INSERT INTO order_items (order_id, item_name, qty, price)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, item["name"], item["qty"], item["price"])
        )

    conn.commit()
    cur.close()
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
        cur.execute("SELECT * FROM order_items WHERE order_id = %s ORDER BY id", (order["id"],))
        order_items = cur.fetchall()
        orders.append({
            "id": order["id"],
            "table_number": order["table_number"],
            "total": order["total"],
            "status": order["status"],
            "created_at": order["created_at"],
            "order_items": order_items
        })

    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE status = %s", ("قيد التحضير",))
    new_orders = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE created_at LIKE %s", (today + "%",))
    today_orders = cur.fetchone()["count"]

    cur.execute("SELECT COALESCE(SUM(total), 0) AS total FROM orders WHERE created_at LIKE %s", (today + "%",))
    sales = cur.fetchone()["total"] or 0

    cur.execute("SELECT COUNT(DISTINCT table_number) AS count FROM orders WHERE created_at LIKE %s", (today + "%",))
    active_tables = cur.fetchone()["count"]

    cur.close()
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
        qr_url=f"{base_url}/qr?table=5"
    )


@app.route("/update-status/<int:order_id>/<status>")
@admin_required
def update_status(order_id, status):
    if status not in ["قيد التحضير", "تم التنفيذ"]:
        status = "قيد التحضير"

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/delete-order/<int:order_id>")
@admin_required
def delete_order(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/qr")
def qr_code():
    table_number = request.args.get("table", "5")
    url = f"{get_site_base_url()}/?table={table_number}"
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--brown:#5a2d15;--brown2:#7b3f20;--gold:#c6843f;--cream:#fbf7f2;--card:#fff;--text:#24150d;--muted:#7d6f67;--line:#eee3da;--shadow:0 18px 50px rgba(55,30,15,.10);}
*{box-sizing:border-box} body{margin:0;font-family:'Cairo',Tahoma,sans-serif;background:linear-gradient(180deg,#fffaf4,#f5efe8);color:var(--text)}
.mobile-top{display:none}.app{max-width:1280px;margin:auto;display:grid;grid-template-columns:240px 1fr 340px;gap:22px;min-height:100vh;padding:22px}.sidebar{background:linear-gradient(180deg,#241107,#120804);border-radius:28px;color:#fff;padding:22px;position:sticky;top:22px;height:calc(100vh - 44px);box-shadow:var(--shadow);overflow:hidden}.brand{display:flex;align-items:center;gap:12px;margin-bottom:28px}.brand-icon{width:50px;height:50px;border-radius:17px;background:rgba(255,255,255,.08);display:grid;place-items:center;font-size:28px;color:#ffc17d}.brand h1{font-size:22px;margin:0;color:#ffc17d}.brand p{margin:0;color:#c9b6a8;font-size:12px}.nav a{display:flex;align-items:center;gap:12px;color:#f6efe9;text-decoration:none;padding:14px 15px;border-radius:16px;margin-bottom:8px;font-weight:700}.nav a.active,.nav a:hover{background:rgba(198,132,63,.28)}
.main{min-width:0}.hero{position:relative;min-height:255px;border-radius:30px;padding:34px;overflow:hidden;background:linear-gradient(90deg,rgba(20,8,2,.95),rgba(55,25,12,.72)),url('https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1400') center/cover;box-shadow:var(--shadow);color:#fff;display:flex;align-items:center;justify-content:flex-end}.hero h2{font-size:42px;margin:6px 0 12px}.hero p{font-size:19px;color:#f7dcc6;margin:0}.table-pill{display:inline-flex;gap:12px;align-items:center;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.18);padding:10px 18px;border-radius:16px;margin-top:18px;font-weight:800}.table-pill b{background:#fff;color:var(--brown);border-radius:12px;padding:3px 16px}.links-box{margin:18px 0;padding:16px;border:1px solid var(--line);background:#fff7ef;border-radius:22px;display:grid;grid-template-columns:1fr 1fr;gap:12px;box-shadow:0 8px 25px rgba(55,30,15,.05)}.link-card{display:flex;align-items:center;gap:12px;padding:10px}.link-card .ico{width:48px;height:48px;border-radius:16px;display:grid;place-items:center;background:#f2e8df;color:var(--brown);font-size:22px}.link-card a{color:var(--brown);font-weight:800;word-break:break-word}.categories{display:flex;gap:13px;margin:20px 0;overflow:auto;padding-bottom:6px}.cat-btn{min-width:130px;padding:14px 16px;border:1px solid var(--line);background:#fff;border-radius:18px;box-shadow:0 8px 20px rgba(55,30,15,.06);font-family:inherit;font-weight:800;color:#3a2518;cursor:pointer}.cat-btn.active{background:linear-gradient(135deg,#7b3f20,#4b230f);color:white;border-color:transparent}.section-title{font-size:25px;text-align:center;margin:22px 0}.products{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.product{background:var(--card);border-radius:24px;overflow:hidden;box-shadow:0 12px 30px rgba(55,30,15,.08);display:grid;grid-template-columns:42% 1fr;min-height:190px;border:1px solid rgba(90,45,21,.06)}.product-img{position:relative;min-height:190px}.product-img img{width:100%;height:100%;object-fit:cover}.heart{position:absolute;top:14px;right:14px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,.8);display:grid;place-items:center;color:#fff;text-shadow:0 1px 8px #000;font-size:20px}.product-info{padding:22px;display:flex;flex-direction:column;justify-content:space-between}.product h3{font-size:22px;margin:0}.desc{color:var(--muted);font-size:14px;margin:7px 0 10px}.price{font-weight:900;color:var(--brown2);font-size:19px}.actions{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:12px}.qty{display:flex;align-items:center;gap:8px}.qty button{border:0;background:#f3f0ed;width:36px;height:36px;border-radius:12px;font-weight:900;cursor:pointer}.add{border:0;background:var(--brown);color:#fff;width:52px;height:40px;border-radius:14px;font-size:18px;cursor:pointer}.cart{background:#fff;border:1px solid rgba(90,45,21,.08);border-radius:28px;padding:20px;box-shadow:var(--shadow);position:sticky;top:22px;height:fit-content}.cart h2{margin:0 0 15px;font-size:22px}.cart-item{display:grid;grid-template-columns:1fr 34px 70px 28px;align-items:center;gap:7px;padding:12px 0;border-bottom:1px dashed #e4d8ce;font-size:14px}.remove{border:0;background:#fff0ed;color:#c0392b;border-radius:9px;width:28px;height:28px}.total-box{background:#fbf4ed;border-radius:18px;padding:15px;margin:17px 0;display:flex;justify-content:space-between;font-size:20px;font-weight:900}.send-btn,.clear-btn{width:100%;border:0;border-radius:16px;padding:15px;font-family:inherit;font-weight:900;cursor:pointer}.send-btn{background:linear-gradient(135deg,#7b3f20,#4b230f);color:#fff}.clear-btn{margin-top:10px;background:#fff;border:1px solid var(--line);color:#4b3224}.floating-cart{display:none}
@media(max-width:1050px){.app{display:block;padding:14px}.sidebar{display:none}.mobile-top{display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:20;background:rgba(255,250,244,.92);backdrop-filter:blur(12px);padding:14px 16px;border-bottom:1px solid #eee}.mobile-top h1{font-size:22px;margin:0}.mobile-btn{width:46px;height:46px;border:0;border-radius:16px;background:#fff;box-shadow:0 8px 20px rgba(55,30,15,.08);font-size:21px}.hero{min-height:230px;padding:26px;border-radius:25px;margin-top:12px}.hero h2{font-size:32px}.links-box{grid-template-columns:1fr}.products{grid-template-columns:1fr}.product{grid-template-columns:38% 1fr;min-height:160px}.product-img{min-height:160px}.cart{margin-top:18px;position:static}.floating-cart{display:flex;position:sticky;bottom:12px;background:#fff;border-radius:20px;padding:12px;box-shadow:0 15px 45px rgba(55,30,15,.18);align-items:center;justify-content:space-between;z-index:30}.floating-cart button{background:var(--brown);color:#fff;border:0;border-radius:14px;padding:13px 25px;font-weight:900;font-family:inherit}}
@media(max-width:540px){.hero{min-height:210px}.hero h2{font-size:28px}.categories{gap:10px}.cat-btn{min-width:118px;font-size:13px;padding:12px}.product{grid-template-columns:1fr;border-radius:22px}.product-img{height:170px}.product-info{padding:18px}.product h3{font-size:21px}.cart{border-radius:22px}.cart-item{grid-template-columns:1fr 28px 62px 26px}.links-box{font-size:13px}.section-title{font-size:22px}}
</style>
</head><body>
<div class="mobile-top"><button class="mobile-btn">☰</button><h1>كافيه فرفشة ☕</h1><button class="mobile-btn" onclick="document.getElementById('cartBox').scrollIntoView({behavior:'smooth'})">🛒</button></div>
<div class="app">
<aside class="sidebar"><div class="brand"><div class="brand-icon">☕</div><div><h1>كافيه فرفشة</h1><p>نكهة كل لحظة</p></div></div><nav class="nav"><a class="active" href="/">🏠 المنيو</a><a href="/login">📋 لوحة المدير</a><a href="{{ qr_url }}" target="_blank">📱 QR للطاولة</a></nav></aside>
<main class="main">
<section class="hero"><div><p>مرحباً بك في</p><h2>كافيه فرفشة 👋</h2><p>اطلب بسهولة من الطاولة</p><div class="table-pill">رقم الطاولة <b>{{ table_number }}</b></div></div></section>
<div class="links-box"><div class="link-card"><div class="ico">🔗</div><div><b>رابط المنيو</b><br><a href="{{ menu_url }}">{{ menu_url }}</a></div></div><div class="link-card"><div class="ico">▦</div><div><b>رابط الباركود</b><br><a href="{{ qr_url }}">{{ qr_url }}</a></div></div></div>
<div class="categories"><button class="cat-btn active" onclick="filterCategory('all',this)">▦ كل الأصناف</button><button class="cat-btn" onclick="filterCategory('hot',this)">☕ الساخنة</button><button class="cat-btn" onclick="filterCategory('cold',this)">🥤 الباردة</button><button class="cat-btn" onclick="filterCategory('juice',this)">🍊 العصائر</button><button class="cat-btn" onclick="filterCategory('dessert',this)">🍰 الحلويات</button><button class="cat-btn" onclick="filterCategory('sandwich',this)">🥪 السندوتشات</button></div>
<h2 class="section-title">المشروبات والأصناف المتاحة</h2>
<div class="products">{% for item in menu %}<article class="product product-card" data-category="{{ item.category }}"><div class="product-img"><img src="{{ item.image }}" alt="{{ item.name }}"><span class="heart">♡</span></div><div class="product-info"><div><h3>{{ item.name }}</h3><p class="desc">{{ item.desc }}</p></div><div><div class="price">{{ item.price }} جنيه</div><div class="actions"><div class="qty"><button onclick="changeQty({{ item.id }},-1)">-</button><b id="qty-{{ item.id }}">0</b><button onclick="changeQty({{ item.id }},1)">+</button></div><button class="add" onclick="addToCart({{ item.id }})">🛒</button></div></div></div></article>{% endfor %}</div>
</main>
<aside class="cart" id="cartBox"><h2>طلبك الحالي 🛒</h2><div id="cartItems"></div><div class="total-box"><span>الإجمالي</span><span><b id="totalPrice">0</b> جنيه</span></div><button class="send-btn" onclick="sendOrder()">إرسال الطلب ✈️</button><button class="clear-btn" onclick="clearCart()">مسح الطلب 🗑️</button></aside>
</div>
<div class="floating-cart"><b>الإجمالي: <span id="floatTotal">0</span> جنيه</b><button onclick="document.getElementById('cartBox').scrollIntoView({behavior:'smooth'})">عرض الطلب</button></div>
<script>
const menu={{ menu|tojson }}; const tableNumber="{{ table_number }}"; let quantities={}; let cart=[];
function filterCategory(cat,btn){document.querySelectorAll('.cat-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.product-card').forEach(card=>card.style.display=(cat==='all'||card.dataset.category===cat)?'grid':'none')}
function changeQty(id,change){quantities[id]=(quantities[id]||0)+change;if(quantities[id]<0)quantities[id]=0;document.getElementById('qty-'+id).innerText=quantities[id]}
function addToCart(id){let qty=quantities[id]||0;if(qty<=0){alert('اختار الكمية أولاً');return}let item=menu.find(x=>x.id===id);let ex=cart.find(x=>x.id===id);if(ex){ex.qty+=qty}else{cart.push({id:item.id,name:item.name,price:item.price,qty:qty})}quantities[id]=0;document.getElementById('qty-'+id).innerText=0;renderCart()}
function renderCart(){let box=document.getElementById('cartItems');let total=0;box.innerHTML='';if(cart.length===0)box.innerHTML='<p style="color:#7d6f67">لا يوجد طلبات حالياً</p>';cart.forEach((it,i)=>{total+=it.price*it.qty;box.innerHTML+=`<div class="cart-item"><div>${it.name}</div><b>${it.qty}</b><div>${it.price*it.qty}</div><button class="remove" onclick="removeItem(${i})">×</button></div>`});document.getElementById('totalPrice').innerText=total;document.getElementById('floatTotal').innerText=total}
function removeItem(i){cart.splice(i,1);renderCart()} function clearCart(){cart=[];renderCart()}
function sendOrder(){if(cart.length===0){alert('السلة فارغة');return}fetch('/send-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({table_number:tableNumber,cart:cart})}).then(r=>r.json()).then(d=>{alert(d.message);if(d.success)clearCart()})}
renderCart();
</script></body></html>
'''

LOGIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>دخول المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#2b1308,#fbf4ed);font-family:'Cairo',Tahoma,sans-serif}.box{width:min(92%,420px);background:#fff;border-radius:28px;padding:34px;box-shadow:0 20px 70px rgba(0,0,0,.18);text-align:center}.logo{font-size:50px}.box h1{margin:8px 0;color:#5a2d15}.box p{color:#77685f}input{width:100%;box-sizing:border-box;padding:16px;border:1px solid #eadfd6;border-radius:16px;text-align:center;font-size:20px;margin:16px 0;font-family:inherit}button{width:100%;padding:16px;border:0;border-radius:16px;background:linear-gradient(135deg,#7b3f20,#4b230f);color:#fff;font-weight:900;font-size:17px;font-family:inherit}.error{background:#fff0ef;color:#c0392b;border-radius:14px;padding:10px;margin:10px 0}</style></head><body><div class="box"><div class="logo">☕</div><h1>كافيه فرفشة</h1><p>تسجيل دخول المدير</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="password" name="pin" placeholder="ادخل كود المدير"><button type="submit">دخول لوحة التحكم</button></form></div></body></html>
'''

ADMIN_HTML = r'''
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>لوحة المدير</title><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet"><style>
:root{--brown:#3b1d0f;--brown2:#7b3f20;--gold:#c6843f;--cream:#fbf7f2;--line:#eee1d7;--muted:#7d6f67;--green:#209653;--red:#c0392b;--orange:#c47b13;--shadow:0 16px 45px rgba(55,30,15,.10)}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fffaf4,#f5efe8);font-family:'Cairo',Tahoma,sans-serif;color:#24150d}.layout{display:grid;grid-template-columns:250px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#251107,#120804);color:#fff;padding:22px;position:sticky;top:0;height:100vh;overflow:hidden}.brand{display:flex;gap:12px;align-items:center;margin-bottom:30px}.brand .icon{width:52px;height:52px;border-radius:18px;background:rgba(255,255,255,.08);display:grid;place-items:center;font-size:30px}.brand h1{font-size:22px;color:#ffc17d;margin:0}.brand p{margin:0;color:#ccb8a7;font-size:12px}.nav a{display:flex;align-items:center;gap:12px;text-decoration:none;color:#fff;padding:14px;border-radius:16px;margin-bottom:8px;font-weight:800}.nav a.active,.nav a:hover{background:rgba(198,132,63,.28)}.coffee{position:absolute;bottom:20px;left:20px;right:20px;border-radius:24px;opacity:.9}.main{padding:26px;min-width:0}.top{height:70px;background:#fff;border:1px solid rgba(90,45,21,.06);border-radius:24px;box-shadow:var(--shadow);display:flex;align-items:center;justify-content:space-between;padding:0 22px;margin-bottom:24px}.top h2{margin:0;font-size:28px}.top-actions{display:flex;gap:10px}.top-actions a,.top-actions button{border:0;text-decoration:none;background:#f4eee8;color:#3a2518;border-radius:14px;padding:11px 15px;font-family:inherit;font-weight:800}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stat{background:#fff;border-radius:24px;padding:22px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06);min-height:150px}.stat .circle{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:#fff2e8;font-size:27px;margin-bottom:12px}.stat b{font-size:32px;color:#5a2d15}.stat p{margin:6px 0;color:var(--muted);font-weight:700}.links{margin:18px 0;background:#fff7ef;border:1px solid var(--line);border-radius:22px;padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px}.links a{color:#5a2d15;font-weight:800;word-break:break-word}.panel{background:#fff;border-radius:26px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06);padding:22px;margin-top:18px}.panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.panel h3{margin:0;font-size:24px}.filters{display:flex;gap:10px;margin-bottom:14px}.filters input,.filters select{border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-family:inherit;min-width:160px}.table-wrap{overflow:auto;border-radius:18px;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;background:#fff;min-width:850px}th{background:linear-gradient(135deg,#693519,#3b1d0f);color:#fff;padding:15px;text-align:right}td{padding:15px;border-bottom:1px solid #f0e5dc;vertical-align:top}.badge{display:inline-flex;align-items:center;gap:6px;border-radius:12px;padding:7px 11px;font-weight:800;font-size:13px}.wait{background:#fff0d2;color:#b8730c}.done{background:#e5f7ed;color:#148346}.actions{display:flex;gap:7px;flex-wrap:wrap}.btn{border:0;text-decoration:none;border-radius:12px;padding:9px 12px;color:#fff;font-family:inherit;font-weight:800;display:inline-block}.b-orange{background:var(--orange)}.b-green{background:var(--green)}.b-red{background:var(--red)}.mini-panels{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:18px}.mini{background:#fff;border-radius:24px;padding:20px;box-shadow:var(--shadow);border:1px solid rgba(90,45,21,.06)}.mini h4{font-size:18px;margin:0 0 10px}.rank{display:flex;justify-content:space-between;border-bottom:1px dashed #eadfd6;padding:9px 0}.mobile-title{display:none}
@media(max-width:1000px){.layout{display:block}.side{display:none}.main{padding:14px}.mobile-title{display:block;position:sticky;top:0;z-index:10;background:rgba(255,250,244,.92);backdrop-filter:blur(12px);padding:15px 10px;border-bottom:1px solid #eee}.mobile-title h1{margin:0;font-size:24px}.top{display:none}.grid{grid-template-columns:1fr 1fr}.links{grid-template-columns:1fr}.mini-panels{grid-template-columns:1fr}.panel{padding:14px;border-radius:22px}.panel-head{display:block}.filters{display:block}.filters input,.filters select{width:100%;margin-bottom:8px}.stat{min-height:130px}.stat b{font-size:28px}}
@media(max-width:560px){.grid{grid-template-columns:1fr}.main{padding:10px}.stat{display:flex;align-items:center;gap:18px;min-height:110px}.stat .circle{margin:0}.links{font-size:13px}.table-wrap{border-radius:16px}th,td{padding:12px;font-size:13px}.actions{display:grid}.btn{text-align:center}.panel h3{font-size:21px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand"><div class="icon">☕</div><div><h1>كافيه فرفشة</h1><p>لوحة تحكم المدير</p></div></div><nav class="nav"><a class="active" href="/admin">📊 الرئيسية</a><a href="/admin">📋 الطلبات</a><a href="/">☕ فتح المنيو</a><a href="{{ qr_url }}" target="_blank">▦ رابط الباركود</a><a href="/logout">🚪 تسجيل خروج</a></nav><img class="coffee" src="https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=700"></aside><main class="main"><div class="mobile-title"><h1>لوحة تحكم الطلبات ☕</h1></div><div class="top"><h2>نظرة عامة</h2><div class="top-actions"><a href="/">فتح المنيو</a><a href="{{ qr_url }}" target="_blank">QR</a><a href="/logout">تسجيل خروج</a></div></div><section class="grid"><div class="stat"><div class="circle">⏱️</div><div><b>{{ new_orders }}</b><p>طلبات قيد التحضير</p></div></div><div class="stat"><div class="circle">📋</div><div><b>{{ today_orders }}</b><p>إجمالي الطلبات اليوم</p></div></div><div class="stat"><div class="circle">💰</div><div><b>{{ sales }}</b><p>إجمالي المبيعات</p></div></div><div class="stat"><div class="circle">🪑</div><div><b>{{ active_tables }}</b><p>الطاولات النشطة</p></div></div></section><div class="links"><div><b>رابط فتح المنيو:</b><br><a href="{{ menu_url }}">{{ menu_url }}</a></div><div><b>رابط الباركود:</b><br><a href="{{ qr_url }}">{{ qr_url }}</a></div></div><section class="panel"><div class="panel-head"><div><h3>الطلبات الأخيرة</h3><p style="color:#7d6f67;margin:4px 0">عرض وإدارة جميع الطلبات</p></div></div><div class="filters"><input id="searchInput" onkeyup="filterOrders()" placeholder="بحث برقم الطلب أو الطاولة..."><select id="statusFilter" onchange="filterOrders()"><option value="">كل الحالات</option><option value="قيد التحضير">قيد التحضير</option><option value="تم التنفيذ">تم التنفيذ</option></select></div><div class="table-wrap"><table id="ordersTable"><thead><tr><th>رقم الطلب</th><th>الطاولة</th><th>الوقت</th><th>العناصر</th><th>الإجمالي</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>{% for order in orders %}<tr data-status="{{ order.status }}"><td>#{{ order.id }}</td><td>{{ order.table_number }}</td><td>{{ order.created_at }}</td><td>{% for item in order.order_items %}• {{ item["item_name"] }} × {{ item["qty"] }}<br>{% endfor %}</td><td><b>{{ order.total }}</b><br>جنيه</td><td>{% if order.status == "تم التنفيذ" %}<span class="badge done">● {{ order.status }}</span>{% else %}<span class="badge wait">● {{ order.status }}</span>{% endif %}</td><td><div class="actions"><a class="btn b-orange" href="/update-status/{{ order.id }}/قيد التحضير">تحضير</a><a class="btn b-green" href="/update-status/{{ order.id }}/تم التنفيذ">تم</a><a class="btn b-red" href="/delete-order/{{ order.id }}" onclick="return confirm('هل تريد حذف الطلب؟')">حذف</a></div></td></tr>{% endfor %}</tbody></table></div></section><section class="mini-panels"><div class="mini"><h4>إحصائيات سريعة ⚡</h4><p>متوسط قيمة الطلب: <b>{{ (sales / today_orders)|round(1) if today_orders else 0 }}</b> جنيه</p><p>عدد الطلبات الجديدة: <b>{{ new_orders }}</b></p></div><div class="mini"><h4>أكثر المنتجات طلبًا 👑</h4><div class="rank"><span>شاي</span><b>4</b></div><div class="rank"><span>كابتشينو</span><b>3</b></div><div class="rank"><span>قهوة تركي</span><b>2</b></div></div><div class="mini"><h4>ملاحظات سريعة 📝</h4><p style="color:#7d6f67">لا توجد ملاحظات حالياً</p></div></section></main></div><script>function filterOrders(){let q=document.getElementById('searchInput').value.toLowerCase();let s=document.getElementById('statusFilter').value;document.querySelectorAll('#ordersTable tbody tr').forEach(r=>{let text=r.innerText.toLowerCase();let okText=text.includes(q);let okStatus=!s||r.dataset.status===s;r.style.display=(okText&&okStatus)?'':'none';});}</script></body></html>
'''

if __name__ == "__main__":
    app.run(debug=False)
