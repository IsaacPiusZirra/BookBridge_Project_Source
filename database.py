from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .security import hash_password

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('buyer','seller','admin')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT,
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_kobo INTEGER NOT NULL CHECK(price_kobo >= 0),
    stock INTEGER NOT NULL CHECK(stock >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(seller_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    UNIQUE(buyer_id, product_id),
    FOREIGN KEY(buyer_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL,
    total_kobo INTEGER NOT NULL CHECK(total_kobo >= 0),
    shipping_address TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    payment_status TEXT NOT NULL CHECK(payment_status IN ('pending','paid','failed')),
    order_status TEXT NOT NULL CHECK(order_status IN ('pending','processing','shipped','delivered','cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(buyer_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    title_snapshot TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_kobo INTEGER NOT NULL CHECK(unit_price_kobo >= 0),
    subtotal_kobo INTEGER NOT NULL CHECK(subtotal_kobo >= 0),
    fulfilment_status TEXT NOT NULL DEFAULT 'pending' CHECK(fulfilment_status IN ('pending','processing','shipped','delivered','cancelled')),
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(seller_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE,
    reference TEXT NOT NULL UNIQUE,
    amount_kobo INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','paid','failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_products_search ON products(title, author, category);
CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_seller ON order_items(seller_id, fulfilment_status);
"""


class Database:
    def __init__(self, path: str | Path = "bookbridge.db") -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, seed_demo: bool = True) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        if seed_demo:
            self.seed_demo_data()

    def seed_demo_data(self) -> None:
        with self.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            if count:
                return
            admin_id = conn.execute(
                "INSERT INTO users(full_name,email,password_hash,role) VALUES (?,?,?,?)",
                ("System Administrator", "admin@bookbridge.local", hash_password("Admin123!"), "admin"),
            ).lastrowid
            seller_id = conn.execute(
                "INSERT INTO users(full_name,email,password_hash,role) VALUES (?,?,?,?)",
                ("Demo Bookseller", "seller@bookbridge.local", hash_password("Seller123!"), "seller"),
            ).lastrowid
            conn.execute(
                "INSERT INTO users(full_name,email,password_hash,role) VALUES (?,?,?,?)",
                ("Demo Buyer", "buyer@bookbridge.local", hash_password("Buyer123!"), "buyer"),
            )
            demo_products = [
                (seller_id, "Things Fall Apart", "Chinua Achebe", "9780385474542", "Literature", "Classic African novel.", 650000, 12),
                (seller_id, "Half of a Yellow Sun", "Chimamanda Ngozi Adichie", "9780007200283", "Literature", "Historical fiction set during the Nigerian civil war.", 850000, 8),
                (seller_id, "Clean Code", "Robert C. Martin", "9780132350884", "Computing", "A handbook of agile software craftsmanship.", 2400000, 5),
                (seller_id, "Introduction to Algorithms", "Cormen et al.", "9780262046305", "Computing", "Algorithms and data structures reference.", 4200000, 3),
            ]
            conn.executemany(
                """INSERT INTO products(seller_id,title,author,isbn,category,description,price_kobo,stock)
                   VALUES (?,?,?,?,?,?,?,?)""",
                demo_products,
            )
            _ = admin_id
