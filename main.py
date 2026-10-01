import flet as ft

from bookbridge.database import Database
from bookbridge.services import MarketplaceService
from bookbridge.ui import BookBridgeUI


def main(page: ft.Page) -> None:
    db = Database("bookbridge.db")
    db.initialize(seed_demo=True)
    service = MarketplaceService(db)
    BookBridgeUI(page, service).start()


if __name__ == "__main__":
    ft.app(target=main)
