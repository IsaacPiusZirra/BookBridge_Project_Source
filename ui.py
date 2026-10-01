from __future__ import annotations

import flet as ft

from .services import AppError, MarketplaceService, SessionUser, naira


class BookBridgeUI:
    def __init__(self, page: ft.Page, service: MarketplaceService) -> None:
        self.page = page
        self.service = service
        self.user: SessionUser | None = None
        self.page.title = "BookBridge Marketplace"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.padding = 18
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_route_change = self.route_change
        self.page.on_view_pop = self.view_pop

    def start(self) -> None:
        self.page.go("/login")

    def notify(self, message: str, error: bool = False) -> None:
        self.page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=ft.Colors.RED_600 if error else ft.Colors.GREEN_600)
        self.page.snack_bar.open = True
        self.page.update()

    def guarded(self, func):
        def wrapper(e=None):
            try:
                return func(e)
            except AppError as exc:
                self.notify(str(exc), True)
            except ValueError:
                self.notify("Enter values in the required format", True)
        return wrapper

    def route_change(self, e) -> None:
        self.page.views.clear()
        if self.page.route == "/register":
            self.page.views.append(self.register_view())
        elif self.page.route == "/market":
            self.require_login()
            self.page.views.append(self.market_view())
        elif self.page.route == "/cart":
            self.require_role("buyer")
            self.page.views.append(self.cart_view())
        elif self.page.route == "/orders":
            self.require_login()
            self.page.views.append(self.orders_view())
        elif self.page.route == "/seller":
            self.require_role("seller", "admin")
            self.page.views.append(self.seller_view())
        elif self.page.route == "/admin":
            self.require_role("admin")
            self.page.views.append(self.admin_view())
        else:
            self.page.views.append(self.login_view())
        self.page.update()

    def view_pop(self, e) -> None:
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.go(self.page.views[-1].route)
        else:
            self.page.go("/market" if self.user else "/login")

    def require_login(self) -> None:
        if self.user is None:
            self.page.route = "/login"
            raise RuntimeError("Authentication required")

    def require_role(self, *roles: str) -> None:
        self.require_login()
        if self.user and self.user.role not in roles:
            self.page.route = "/market"
            raise RuntimeError("Role not permitted")

    def appbar(self, title: str) -> ft.AppBar:
        actions = []
        if self.user:
            actions.extend([
                ft.TextButton("Marketplace", on_click=lambda e: self.page.go("/market")),
                ft.TextButton("Orders", on_click=lambda e: self.page.go("/orders")),
            ])
            if self.user.role == "buyer":
                actions.append(ft.TextButton("Cart", on_click=lambda e: self.page.go("/cart")))
            if self.user.role in {"seller", "admin"}:
                actions.append(ft.TextButton("Seller", on_click=lambda e: self.page.go("/seller")))
            if self.user.role == "admin":
                actions.append(ft.TextButton("Admin", on_click=lambda e: self.page.go("/admin")))
            actions.append(ft.TextButton("Logout", on_click=self.logout))
        return ft.AppBar(title=ft.Text(title), actions=actions)

    def logout(self, e=None) -> None:
        self.user = None
        self.page.go("/login")

    def login_view(self) -> ft.View:
        email = ft.TextField(label="Email", autofocus=True, width=420)
        password = ft.TextField(label="Password", password=True, can_reveal_password=True, width=420)

        @self.guarded
        def submit(e):
            self.user = self.service.login(email.value or "", password.value or "")
            self.page.go("/market")

        body = ft.Column([
            ft.Text("BookBridge", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("Marketplace for new and pre-owned books"),
            email,
            password,
            ft.FilledButton("Sign in", on_click=submit),
            ft.TextButton("Create buyer or seller account", on_click=lambda e: self.page.go("/register")),
            ft.Divider(),
            ft.Text("Demo accounts: buyer@bookbridge.local / Buyer123!, seller@bookbridge.local / Seller123!, admin@bookbridge.local / Admin123!", size=12),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16)
        return ft.View("/login", [ft.Container(body, alignment=ft.alignment.center, padding=30)])

    def register_view(self) -> ft.View:
        name = ft.TextField(label="Full name", width=420)
        email = ft.TextField(label="Email", width=420)
        password = ft.TextField(label="Password", password=True, can_reveal_password=True, width=420)
        role = ft.Dropdown(label="Account type", width=420, value="buyer", options=[ft.dropdown.Option("buyer"), ft.dropdown.Option("seller")])

        @self.guarded
        def submit(e):
            self.service.register(name.value or "", email.value or "", password.value or "", role.value or "buyer")
            self.notify("Registration successful. Sign in with your new account.")
            self.page.go("/login")

        return ft.View("/register", [
            self.appbar("Create Account"),
            ft.Column([name, email, password, role, ft.FilledButton("Register", on_click=submit)], spacing=14),
        ])

    def market_view(self) -> ft.View:
        query = ft.TextField(label="Search title, author, ISBN or keyword", expand=True)
        category = ft.Dropdown(label="Category", width=220, options=[ft.dropdown.Option("")] + [ft.dropdown.Option(x) for x in self.service.categories()])
        results = ft.Column(spacing=10)

        def reload(e=None):
            products = self.service.list_products(query.value or "", category.value or "")
            cards = []
            for p in products:
                controls = [
                    ft.Text(p["title"], size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{p['author']}  |  {p['category']}"),
                    ft.Text(f"Seller: {p['seller_name']}  |  Stock: {p['stock']}"),
                    ft.Text(naira(p["price_kobo"]), size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(p["description"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ]
                if self.user and self.user.role == "buyer":
                    pid = p["id"]
                    controls.append(ft.FilledButton("Add to cart", on_click=self.guarded(lambda e, product_id=pid: self._add_cart(product_id))))
                cards.append(ft.Card(ft.Container(ft.Column(controls), padding=14)))
            results.controls = cards or [ft.Text("No matching books found.")]
            self.page.update()

        query.on_submit = reload
        reload()
        header = ft.Row([query, category, ft.FilledButton("Search", on_click=reload)])
        return ft.View("/market", [self.appbar("BookBridge Marketplace"), header, results])

    def _add_cart(self, product_id: int) -> None:
        assert self.user
        self.service.add_to_cart(self.user, product_id, 1)
        self.notify("Book added to cart")

    def cart_view(self) -> ft.View:
        assert self.user
        rows = ft.Column()
        total_text = ft.Text(size=18, weight=ft.FontWeight.BOLD)
        address = ft.TextField(label="Delivery address", multiline=True, min_lines=2)
        payment = ft.Dropdown(
            label="Payment method",
            value="bank_transfer",
            options=[
                ft.dropdown.Option("bank_transfer", "Bank transfer"),
                ft.dropdown.Option("cash_on_delivery", "Cash on delivery"),
                ft.dropdown.Option("demo_card", "Demo card payment"),
            ],
        )

        def reload():
            items = self.service.cart(self.user.id)
            controls = []
            total = 0
            for item in items:
                total += item["subtotal_kobo"]
                pid = item["product_id"]
                qty = ft.TextField(value=str(item["quantity"]), width=70, keyboard_type=ft.KeyboardType.NUMBER)

                @self.guarded
                def update_qty(e, product_id=pid, field=qty):
                    self.service.update_cart(self.user, product_id, int(field.value or "0"))
                    self.page.go("/cart")

                controls.append(ft.Card(ft.Container(ft.Row([
                    ft.Column([ft.Text(item["title"], weight=ft.FontWeight.BOLD), ft.Text(item["author"]), ft.Text(naira(item["price_kobo"]))], expand=True),
                    qty,
                    ft.OutlinedButton("Update", on_click=update_qty),
                    ft.Text(naira(item["subtotal_kobo"]), width=120),
                ]), padding=10)))
            rows.controls = controls or [ft.Text("Your cart is empty.")]
            total_text.value = f"Cart total: {naira(total)}"

        @self.guarded
        def checkout(e):
            order_id = self.service.checkout(self.user, address.value or "", payment.value or "")
            self.notify(f"Order #{order_id} created")
            self.page.go("/orders")

        reload()
        return ft.View("/cart", [self.appbar("Shopping Cart"), rows, total_text, address, payment, ft.FilledButton("Place order", on_click=checkout)])

    def orders_view(self) -> ft.View:
        assert self.user
        content = ft.Column(spacing=10)
        if self.user.role == "buyer":
            for order in self.service.buyer_orders(self.user.id):
                item_text = ", ".join(f"{x['title_snapshot']} x{x['quantity']}" for x in self.service.order_items(order["id"]))
                content.controls.append(ft.Card(ft.Container(ft.Column([
                    ft.Text(f"Order #{order['id']}", weight=ft.FontWeight.BOLD),
                    ft.Text(item_text),
                    ft.Text(f"Total: {naira(order['total_kobo'])}"),
                    ft.Text(f"Payment: {order['payment_status']}  |  Status: {order['order_status']}"),
                ]), padding=12)))
        else:
            content.controls.append(ft.Text("Seller fulfilment orders are available in the Seller dashboard."))
        return ft.View("/orders", [self.appbar("Orders"), content])

    def seller_view(self) -> ft.View:
        assert self.user
        title = ft.TextField(label="Title")
        author = ft.TextField(label="Author")
        isbn = ft.TextField(label="ISBN")
        category = ft.TextField(label="Category")
        description = ft.TextField(label="Description", multiline=True)
        price = ft.TextField(label="Price (₦)", keyboard_type=ft.KeyboardType.NUMBER)
        stock = ft.TextField(label="Stock", keyboard_type=ft.KeyboardType.NUMBER)

        @self.guarded
        def add_product(e):
            self.service.save_product(self.user, title.value or "", author.value or "", isbn.value or "", category.value or "", description.value or "", float(price.value or 0), int(stock.value or 0))
            self.notify("Product saved")
            self.page.go("/seller")

        product_cards = []
        for p in self.service.seller_products(self.user.id) if self.user.role == "seller" else self.service.list_products():
            product_cards.append(ft.Text(f"#{p['id']} {p['title']} | {naira(p['price_kobo'])} | Stock {p['stock']} | {p['status']}"))

        order_cards = []
        if self.user.role == "seller":
            for item in self.service.seller_orders(self.user.id):
                status = ft.Dropdown(value=item["fulfilment_status"], width=150, options=[ft.dropdown.Option(x) for x in ["pending", "processing", "shipped", "delivered", "cancelled"]])
                oid = item["id"]

                @self.guarded
                def save_status(e, order_item_id=oid, field=status):
                    self.service.update_fulfilment(self.user, order_item_id, field.value)
                    self.notify("Fulfilment status updated")

                order_cards.append(ft.Card(ft.Container(ft.Row([
                    ft.Column([ft.Text(item["title_snapshot"], weight=ft.FontWeight.BOLD), ft.Text(f"Buyer: {item['buyer_name']}"), ft.Text(f"Qty {item['quantity']} | Payment {item['payment_status']}")], expand=True),
                    status,
                    ft.OutlinedButton("Save", on_click=save_status),
                ]), padding=10)))
        form = ft.Column([ft.Text("Add a book", size=20, weight=ft.FontWeight.BOLD), title, author, isbn, category, description, ft.Row([price, stock]), ft.FilledButton("Save product", on_click=add_product)], spacing=10)
        return ft.View("/seller", [self.appbar("Seller Dashboard"), form, ft.Divider(), ft.Text("My products", size=20, weight=ft.FontWeight.BOLD), *product_cards, ft.Divider(), ft.Text("Orders to fulfil", size=20, weight=ft.FontWeight.BOLD), *order_cards])

    def admin_view(self) -> ft.View:
        metrics = self.service.admin_metrics()
        cards = ft.Row([
            ft.Card(ft.Container(ft.Column([ft.Text("Users"), ft.Text(str(metrics["users"]), size=28)]), padding=16)),
            ft.Card(ft.Container(ft.Column([ft.Text("Products"), ft.Text(str(metrics["products"]), size=28)]), padding=16)),
            ft.Card(ft.Container(ft.Column([ft.Text("Orders"), ft.Text(str(metrics["orders"]), size=28)]), padding=16)),
            ft.Card(ft.Container(ft.Column([ft.Text("Paid revenue"), ft.Text(naira(metrics["revenue_kobo"]), size=24)]), padding=16)),
        ], wrap=True)
        return ft.View("/admin", [self.appbar("Administration"), cards, ft.Text("Admin role provides oversight of marketplace activity. Production deployment should add audit logs, moderation queues, account suspension controls and reports.")])
