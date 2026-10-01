from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Iterable

from .database import Database
from .security import hash_password, verify_password

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AppError(Exception):
    pass


class ValidationError(AppError):
    pass


class AuthenticationError(AppError):
    pass


class AuthorizationError(AppError):
    pass


class NotFoundError(AppError):
    pass


@dataclass(frozen=True)
class SessionUser:
    id: int
    full_name: str
    email: str
    role: str


def naira(kobo: int) -> str:
    return f"₦{kobo / 100:,.2f}"


class MarketplaceService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def register(self, full_name: str, email: str, password: str, role: str) -> int:
        full_name = full_name.strip()
        email = email.strip().lower()
        if len(full_name) < 2:
            raise ValidationError("Enter a valid full name")
        if not EMAIL_RE.match(email):
            raise ValidationError("Enter a valid email address")
        if role not in {"buyer", "seller"}:
            raise ValidationError("Role must be buyer or seller")
        try:
            encoded = hash_password(password)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        try:
            with self.db.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO users(full_name,email,password_hash,role) VALUES (?,?,?,?)",
                    (full_name, email, encoded, role),
                )
                return int(cur.lastrowid)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValidationError("An account already exists for this email") from exc
            raise

    def login(self, email: str, password: str) -> SessionUser:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id,full_name,email,password_hash,role,is_active FROM users WHERE email=? COLLATE NOCASE",
                (email.strip(),),
            ).fetchone()
        if row is None or not row["is_active"] or not verify_password(password, row["password_hash"]):
            raise AuthenticationError("Invalid email or password")
        return SessionUser(row["id"], row["full_name"], row["email"], row["role"])

    def list_products(self, query: str = "", category: str = "") -> list[dict]:
        sql = """SELECT p.*, u.full_name AS seller_name
                 FROM products p JOIN users u ON u.id=p.seller_id
                 WHERE p.status='active' AND p.stock > 0"""
        params: list[object] = []
        if query.strip():
            q = f"%{query.strip()}%"
            sql += " AND (p.title LIKE ? OR p.author LIKE ? OR p.isbn LIKE ? OR p.description LIKE ?)"
            params.extend([q, q, q, q])
        if category.strip():
            sql += " AND p.category=?"
            params.append(category.strip())
        sql += " ORDER BY p.created_at DESC, p.id DESC"
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def categories(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT DISTINCT category FROM products WHERE status='active' ORDER BY category").fetchall()
        return [r[0] for r in rows]

    def seller_products(self, seller_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM products WHERE seller_id=? ORDER BY id DESC", (seller_id,)).fetchall()
        return [dict(r) for r in rows]

    def save_product(
        self,
        seller: SessionUser,
        title: str,
        author: str,
        isbn: str,
        category: str,
        description: str,
        price_naira: float,
        stock: int,
        product_id: int | None = None,
    ) -> int:
        if seller.role not in {"seller", "admin"}:
            raise AuthorizationError("Seller access is required")
        title, author, category = title.strip(), author.strip(), category.strip()
        if not title or not author or not category:
            raise ValidationError("Title, author and category are required")
        if price_naira < 0 or stock < 0:
            raise ValidationError("Price and stock must not be negative")
        price_kobo = int(round(price_naira * 100))
        with self.db.transaction() as conn:
            if product_id is None:
                cur = conn.execute(
                    """INSERT INTO products(seller_id,title,author,isbn,category,description,price_kobo,stock)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (seller.id, title, author, isbn.strip(), category, description.strip(), price_kobo, int(stock)),
                )
                return int(cur.lastrowid)
            existing = conn.execute("SELECT seller_id FROM products WHERE id=?", (product_id,)).fetchone()
            if existing is None:
                raise NotFoundError("Product not found")
            if seller.role != "admin" and existing["seller_id"] != seller.id:
                raise AuthorizationError("You cannot edit another seller's product")
            conn.execute(
                """UPDATE products SET title=?,author=?,isbn=?,category=?,description=?,price_kobo=?,stock=?
                   WHERE id=?""",
                (title, author, isbn.strip(), category, description.strip(), price_kobo, int(stock), product_id),
            )
            return product_id

    def set_product_status(self, user: SessionUser, product_id: int, status: str) -> None:
        if status not in {"active", "inactive"}:
            raise ValidationError("Invalid product status")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT seller_id FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise NotFoundError("Product not found")
            if user.role != "admin" and not (user.role == "seller" and row["seller_id"] == user.id):
                raise AuthorizationError("You cannot change this product")
            conn.execute("UPDATE products SET status=? WHERE id=?", (status, product_id))

    def add_to_cart(self, buyer: SessionUser, product_id: int, quantity: int = 1) -> None:
        if buyer.role != "buyer":
            raise AuthorizationError("Buyer access is required")
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero")
        with self.db.transaction() as conn:
            product = conn.execute("SELECT stock,status FROM products WHERE id=?", (product_id,)).fetchone()
            if product is None or product["status"] != "active":
                raise NotFoundError("Product is unavailable")
            current = conn.execute(
                "SELECT quantity FROM cart_items WHERE buyer_id=? AND product_id=?", (buyer.id, product_id)
            ).fetchone()
            new_qty = quantity + (current["quantity"] if current else 0)
            if new_qty > product["stock"]:
                raise ValidationError("Requested quantity exceeds available stock")
            conn.execute(
                """INSERT INTO cart_items(buyer_id,product_id,quantity) VALUES (?,?,?)
                   ON CONFLICT(buyer_id,product_id) DO UPDATE SET quantity=excluded.quantity""",
                (buyer.id, product_id, new_qty),
            )

    def update_cart(self, buyer: SessionUser, product_id: int, quantity: int) -> None:
        if buyer.role != "buyer":
            raise AuthorizationError("Buyer access is required")
        with self.db.transaction() as conn:
            if quantity <= 0:
                conn.execute("DELETE FROM cart_items WHERE buyer_id=? AND product_id=?", (buyer.id, product_id))
                return
            product = conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
            if product is None or quantity > product["stock"]:
                raise ValidationError("Requested quantity exceeds available stock")
            conn.execute(
                "UPDATE cart_items SET quantity=? WHERE buyer_id=? AND product_id=?",
                (quantity, buyer.id, product_id),
            )

    def cart(self, buyer_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT c.product_id,c.quantity,p.title,p.author,p.price_kobo,p.stock,
                          (c.quantity*p.price_kobo) AS subtotal_kobo
                   FROM cart_items c JOIN products p ON p.id=c.product_id
                   WHERE c.buyer_id=? ORDER BY c.id""",
                (buyer_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def checkout(self, buyer: SessionUser, shipping_address: str, payment_method: str) -> int:
        if buyer.role != "buyer":
            raise AuthorizationError("Buyer access is required")
        if len(shipping_address.strip()) < 8:
            raise ValidationError("Enter a complete delivery address")
        if payment_method not in {"bank_transfer", "cash_on_delivery", "demo_card"}:
            raise ValidationError("Select a valid payment method")

        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT c.product_id,c.quantity,p.title,p.seller_id,p.price_kobo,p.stock,p.status
                   FROM cart_items c JOIN products p ON p.id=c.product_id
                   WHERE c.buyer_id=?""",
                (buyer.id,),
            ).fetchall()
            if not rows:
                raise ValidationError("Your cart is empty")
            total = 0
            for row in rows:
                if row["status"] != "active" or row["quantity"] > row["stock"]:
                    raise ValidationError(f"Insufficient stock for {row['title']}")
                total += row["quantity"] * row["price_kobo"]

            payment_status = "paid" if payment_method == "demo_card" else "pending"
            order_status = "processing" if payment_status == "paid" else "pending"
            cur = conn.execute(
                """INSERT INTO orders(buyer_id,total_kobo,shipping_address,payment_method,payment_status,order_status)
                   VALUES (?,?,?,?,?,?)""",
                (buyer.id, total, shipping_address.strip(), payment_method, payment_status, order_status),
            )
            order_id = int(cur.lastrowid)
            for row in rows:
                subtotal = row["quantity"] * row["price_kobo"]
                conn.execute(
                    """INSERT INTO order_items(order_id,product_id,seller_id,title_snapshot,quantity,unit_price_kobo,subtotal_kobo)
                       VALUES (?,?,?,?,?,?,?)""",
                    (order_id, row["product_id"], row["seller_id"], row["title"], row["quantity"], row["price_kobo"], subtotal),
                )
                conn.execute(
                    "UPDATE products SET stock=stock-? WHERE id=? AND stock>=?",
                    (row["quantity"], row["product_id"], row["quantity"]),
                )
            reference = "BB-" + secrets.token_hex(6).upper()
            conn.execute(
                "INSERT INTO payments(order_id,reference,amount_kobo,method,status) VALUES (?,?,?,?,?)",
                (order_id, reference, total, payment_method, payment_status),
            )
            conn.execute("DELETE FROM cart_items WHERE buyer_id=?", (buyer.id,))
            return order_id

    def buyer_orders(self, buyer_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC", (buyer_id,)).fetchall()
        return [dict(r) for r in rows]

    def order_items(self, order_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
        return [dict(r) for r in rows]

    def seller_orders(self, seller_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT oi.*,o.buyer_id,o.shipping_address,o.payment_status,o.created_at,
                          u.full_name AS buyer_name
                   FROM order_items oi
                   JOIN orders o ON o.id=oi.order_id
                   JOIN users u ON u.id=o.buyer_id
                   WHERE oi.seller_id=? ORDER BY oi.id DESC""",
                (seller_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_fulfilment(self, seller: SessionUser, order_item_id: int, status: str) -> None:
        if status not in {"pending", "processing", "shipped", "delivered", "cancelled"}:
            raise ValidationError("Invalid fulfilment status")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT seller_id,order_id FROM order_items WHERE id=?", (order_item_id,)).fetchone()
            if row is None:
                raise NotFoundError("Order item not found")
            if seller.role != "admin" and not (seller.role == "seller" and row["seller_id"] == seller.id):
                raise AuthorizationError("You cannot update this order")
            conn.execute("UPDATE order_items SET fulfilment_status=? WHERE id=?", (status, order_item_id))
            statuses = [r[0] for r in conn.execute("SELECT fulfilment_status FROM order_items WHERE order_id=?", (row["order_id"],))]
            overall = self._derive_order_status(statuses)
            conn.execute("UPDATE orders SET order_status=? WHERE id=?", (overall, row["order_id"]))

    @staticmethod
    def _derive_order_status(statuses: Iterable[str]) -> str:
        values = list(statuses)
        if values and all(v == "cancelled" for v in values):
            return "cancelled"
        if values and all(v in {"delivered", "cancelled"} for v in values):
            return "delivered"
        if any(v == "shipped" for v in values):
            return "shipped"
        if any(v == "processing" for v in values):
            return "processing"
        return "pending"

    def admin_metrics(self) -> dict:
        with self.db.connect() as conn:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            revenue = conn.execute("SELECT COALESCE(SUM(total_kobo),0) FROM orders WHERE payment_status='paid'").fetchone()[0]
        return {"users": users, "products": products, "orders": orders, "revenue_kobo": revenue}
