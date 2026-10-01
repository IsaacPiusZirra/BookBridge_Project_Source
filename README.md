# BookBridge Marketplace

BookBridge is a Python/Flet marketplace prototype for buying and selling books. One codebase targets desktop, web and mobile deployments supported by Flet.

## Features

- Buyer and seller registration
- PBKDF2 password hashing and role-based access
- Product listing, search and category filtering
- Seller product management
- Shopping cart with stock validation
- Atomic checkout transaction
- Demo payment, bank transfer and cash-on-delivery options
- Buyer order history
- Seller fulfilment workflow
- Admin metrics dashboard
- SQLite prototype database with a migration-ready three-tier structure

## Installation

1. Install Python 3.11 or later.
2. Create and activate a virtual environment.
3. Run `pip install -r requirements.txt`.
4. Run `python main.py`.

Flet opens the desktop client by default. For web deployment, follow the Flet deployment command for the installed version. Mobile packaging requires the platform SDK/toolchain supported by the installed Flet release.

## Demo credentials

- Buyer: `buyer@bookbridge.local` / `Buyer123!`
- Seller: `seller@bookbridge.local` / `Seller123!`
- Admin: `admin@bookbridge.local` / `Admin123!`

## Tests

Run:

`python -m unittest discover -s tests -v`

The business logic tests do not require a Flet runtime.

## Security notes

The prototype hashes passwords using PBKDF2, uses parameterized SQL and applies role checks. Real deployment should terminate TLS, use a hosted payment page or gateway tokenization, protect secrets in environment variables, add MFA/rate limiting, implement CSRF protections where applicable, collect audit logs and use a production database such as PostgreSQL.
