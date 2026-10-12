"""Browser tests for the lobby and board (docs/ui-spec.md states; REQ-UI-*).

Run locally:  CHROMIUM_PATH=/path/to/chromium uv run pytest tests/e2e
In CI:        E2E_BROWSERS=chromium,webkit uv run pytest tests/e2e   (after `playwright install`)
Screenshots go to $E2E_ARTIFACTS when set, for review in the CI run.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ViewportSize,
    expect,
    sync_playwright,
)

pytestmark = pytest.mark.e2e

BROWSERS = [
    name.strip() for name in os.environ.get("E2E_BROWSERS", "chromium").split(",") if name.strip()
]
ARTIFACTS = Path(os.environ["E2E_ARTIFACTS"]) if os.environ.get("E2E_ARTIFACTS") else None
IPHONE: ViewportSize = {"width": 390, "height": 844}
NOT_FOUND_ID = "00000000-0000-4000-8000-000000000000"

expect.set_options(timeout=10_000)


@pytest.fixture(scope="session")
def pw() -> Iterator[Playwright]:
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="session", params=BROWSERS)
def browser(request: pytest.FixtureRequest, pw: Playwright) -> Iterator[Browser]:
    name = request.param
    kwargs: dict[str, Any] = {}
    if name == "chromium" and os.environ.get("CHROMIUM_PATH"):
        kwargs = {
            "executable_path": os.environ["CHROMIUM_PATH"],
            "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        }
    browser = getattr(pw, name).launch(**kwargs)
    yield browser
    browser.close()


class Player:
    def __init__(self, key: str, context: BrowserContext, base_url: str) -> None:
        self.key = key
        self.context = context
        self.base_url = base_url
        self.page: Page = context.new_page()
        self.problems: list[str] = []
        self.page.on("console", self._console)
        self.page.on("pageerror", lambda error: self.problems.append(f"pageerror: {error}"))
        # One request with ?as= sets the development identity cookie for this browser context.
        response = self.page.request.get(f"{base_url}/api/me", params={"as": key})
        assert response.ok, response.text()

    def _console(self, message: Any) -> None:
        if message.type == "error":
            where = message.location.get("url") or "unknown source"
            self.problems.append(f"console: {message.text} [{where}]")

    def goto(self, path: str) -> None:
        self.page.goto(f"{self.base_url}{path}")

    def square(self, name: str) -> Any:
        return self.page.locator(f'[data-square="{name}"]')

    def wait_live(self) -> None:
        expect(self.page.locator(".pill--live")).to_be_visible()

    def wait_ply(self, ply: int) -> None:
        # The move strip holds ply SANs plus move numbers; wait on the board state instead.
        expect(self.page.locator("#moves .moves__san")).to_have_count(ply)

    def tap_move(self, uci: str) -> None:
        self.square(uci[:2]).click()
        self.square(uci[2:4]).click()

    def diag(self, game_id: str, uci: str) -> None:
        response = self.page.request.post(
            f"{self.base_url}/api/diag/move", data={"game_id": game_id, "uci": uci}
        )
        assert response.ok and response.json()["ok"], response.text()

    def shot(self, name: str) -> None:
        if ARTIFACTS:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            browser = self.context.browser.browser_type.name if self.context.browser else "browser"
            # caret="initial": by default Playwright injects a stylesheet to hide the caret, and
            # WebKit applies the page's CSP to it, which would log a false CSP violation.
            self.page.screenshot(
                path=str(ARTIFACTS / f"{browser}-{name}.png"), full_page=True, caret="initial"
            )


@pytest.fixture
def players(browser: Browser, base_url: str) -> Iterator[tuple[Player, Player]]:
    contexts = [
        browser.new_context(viewport=IPHONE, device_scale_factor=2, locale="en-GB")
        for _ in range(2)
    ]
    harry = Player("harry", contexts[0], base_url)
    partner = Player("partner", contexts[1], base_url)
    yield harry, partner
    problems = harry.problems + partner.problems
    for context in contexts:
        context.close()
    # CSP violations and script errors show up here.
    assert not problems, problems


def start_game(harry: Player, partner: Player, colour: str = "white") -> str:
    harry.goto("/")
    harry.page.locator(f'#colour-choice [data-colour="{colour}"]').click()
    harry.page.locator("#start").click()
    harry.page.wait_for_url(re.compile(r"/game/[0-9a-f-]{36}$"))
    game_id = harry.page.url.rsplit("/", 1)[1]
    partner.goto(f"/game/{game_id}")
    harry.wait_live()
    partner.wait_live()
    return game_id


def no_horizontal_scroll(page: Page) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))


# ------------------------------------------------------------------------ lobby


def test_lobby_name_box_and_emails(players: tuple[Player, Player]) -> None:
    harry, _ = players
    harry.goto("/")
    page = harry.page
    save = page.locator("#name-save")
    name = page.locator("#name-input")
    expect(name).to_have_value(re.compile(r".+"))
    expect(save).to_be_disabled()  # L9: disabled until the text changes
    name.fill("   ")
    save.click()
    expect(page.locator("#name-error")).to_be_visible()
    name.fill("Harry G")
    save.click()
    expect(page.locator("#name-saved")).to_be_visible()
    expect(page.locator("#me-chip")).to_have_text("Harry G")
    name.fill("Harry")
    save.click()
    expect(page.locator("#me-chip")).to_have_text("Harry")

    # L8: switches save at once; the gap timer is inert while move emails are off.
    your_move = page.locator("#your-move")
    expect(your_move).to_have_attribute("aria-checked", "true")
    page.locator("#gap-up").click()
    expect(page.locator("#gap-value")).to_have_text("45 min")
    page.locator("#gap-down").click()
    expect(page.locator("#gap-value")).to_have_text("30 min")
    your_move.click()
    expect(your_move).to_have_attribute("aria-checked", "false")
    expect(page.locator("#gap-up")).to_be_disabled()
    page.reload()
    expect(page.locator("#your-move")).to_have_attribute("aria-checked", "false")
    page.locator("#your-move").click()
    expect(page.locator("#your-move")).to_have_attribute("aria-checked", "true")
    expect(page.locator("#gap-up")).to_be_enabled()
    assert no_horizontal_scroll(page)
    harry.shot("lobby")


def test_lobby_lists_games_for_both(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    partner.goto("/")
    card = partner.page.locator(f'[data-testid="waiting"] [data-game-id="{game_id}"]')
    expect(card).to_be_visible()  # White (Harry) to move: partner is waiting
    harry.goto("/")
    expect(
        harry.page.locator(f'[data-testid="your-move"] [data-game-id="{game_id}"]')
    ).to_be_visible()


# ------------------------------------------------------------------------ board


def test_orientation_tap_move_and_broadcast(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    # REQ-UI-01: your colour at the bottom.
    expect(harry.page.locator(".sq").first).to_have_attribute("data-square", "a8")
    expect(partner.page.locator(".sq").first).to_have_attribute("data-square", "h1")
    expect(harry.square("a1")).to_have_class(re.compile(r"sq--dark"))  # a1 is dark, h1 light
    expect(harry.square("h1")).not_to_have_class(re.compile(r"sq--dark"))
    expect(harry.page.locator('[data-testid="turn"]')).to_have_text("Your move")
    expect(partner.page.locator('[data-testid="status"]')).to_have_text(re.compile(r"'s move$"))

    # REQ-UI-03: selecting shows only the server's legal targets.
    harry.square("g1").click()
    expect(harry.page.locator(".sq__target:not([hidden])")).to_have_count(2)
    harry.shot("selected")
    harry.square("f3").click()
    partner.wait_ply(1)
    expect(partner.page.locator('[data-testid="turn"]')).to_have_text("Your move")
    expect(partner.square("g1")).to_have_class(re.compile(r"sq--last"))
    expect(partner.square("f3")).to_have_class(re.compile(r"sq--last"))
    expect(partner.page.locator("#moves")).to_contain_text("1. Nf3")
    # Not your turn: no targets, nothing sent.
    harry.square("e2").click()
    expect(harry.page.locator(".sq__target:not([hidden])")).to_have_count(0)
    assert no_horizontal_scroll(harry.page)
    partner.shot("black-to-move")


def test_drag_and_drop(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    harry.square("e2").drag_to(harry.square("e4"))
    partner.wait_ply(1)
    # Dropping on an illegal square snaps back and sends nothing.
    partner.square("e7").drag_to(partner.square("e4"))
    partner.page.wait_for_timeout(300)
    expect(partner.page.locator("#moves .moves__san")).to_have_count(1)
    partner.square("e7").drag_to(partner.square("e5"))
    harry.wait_ply(2)
    expect(harry.page.locator("#moves")).to_contain_text("1. e4 e5")


def test_promotion_picker(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    for uci in ["h2h4", "g7g5", "h4g5", "h7h6", "g5h6", "f8g7", "h6g7", "g8f6"]:
        harry.diag(game_id, uci)
    harry.wait_ply(8)
    harry.tap_move("g7h8")
    dialog = harry.page.get_by_role("dialog", name="Choose a piece")
    expect(dialog).to_be_visible()  # B9
    harry.shot("promotion")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    expect(harry.page.locator("#moves .moves__san")).to_have_count(8)
    harry.tap_move("g7h8")
    harry.page.get_by_role("dialog").get_by_role("button", name="Knight").click()
    expect(harry.square("h8")).to_be_focused()  # focus stays on the board
    partner.wait_ply(9)
    expect(partner.page.locator("#moves")).to_contain_text("gxh8=N")


def test_resign_confirmation_and_rematch(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    resign = harry.page.locator('[data-testid="resign"]')
    resign.click()
    expect(resign).to_contain_text("Tap again to resign")  # REQ-UI-11
    resign.click()
    expect(harry.page.locator('[data-testid="status"]')).to_contain_text("You resigned")
    expect(partner.page.locator('[data-testid="status"]')).to_contain_text("resigned — you win")
    partner.shot("resigned")
    harry.page.locator('[data-testid="rematch"]').click()
    expect(partner.page.locator('[data-testid="rematch-offer"]')).to_be_visible()  # B15
    partner.page.locator('[data-testid="rematch-accept"]').click()
    # B16: both pages move to the new game, colours swapped.
    harry.page.wait_for_url(re.compile(r"/game/(?!" + game_id + r")[0-9a-f-]{36}$"))
    partner.page.wait_for_url(re.compile(r"/game/(?!" + game_id + r")[0-9a-f-]{36}$"))
    harry.wait_live()
    expect(harry.page.locator(".sq").first).to_have_attribute("data-square", "h1")


def test_draw_offer_and_takeback_banners(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    harry.tap_move("e2e4")
    partner.wait_ply(1)
    harry.page.locator('[data-testid="takeback"]').click()
    expect(harry.page.locator('[data-testid="takeback-requested"]')).to_be_visible()
    expect(partner.page.locator('[data-testid="takeback-offer"]')).to_be_visible()
    partner.shot("takeback-offer")
    partner.page.locator('[data-testid="takeback-accept"]').click()
    expect(harry.page.locator(".toast")).to_contain_text("Move taken back")
    expect(harry.page.locator("#moves")).to_contain_text("No moves yet")
    harry.page.locator('[data-testid="draw"]').click()
    expect(harry.page.locator('[data-testid="draw-offered"]')).to_be_visible()
    partner.page.locator('[data-testid="draw-accept"]').click()
    expect(harry.page.locator('[data-testid="status"]')).to_have_text("Draw — agreed")
    expect(partner.page.locator('[data-testid="pgn"]')).to_be_visible()


def test_checkmate_and_error_toast(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    for uci in ["f2f3", "e7e5", "g2g4"]:
        harry.diag(game_id, uci)
    partner.wait_ply(3)
    partner.tap_move("d8h4")
    expect(harry.page.locator('[data-testid="status"]')).to_have_text("Checkmate — Partner wins")
    expect(partner.page.locator('[data-testid="status"]')).to_have_text("Checkmate — you win")
    expect(harry.square("e1")).to_have_class(re.compile(r"sq--check"))
    harry.shot("checkmated")


def test_keyboard_play(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    harry.square("e2").focus()
    harry.page.keyboard.press("Enter")
    expect(harry.square("e2")).to_have_class(re.compile(r"sq--selected"))
    harry.page.keyboard.press("ArrowUp")
    harry.page.keyboard.press("ArrowUp")
    expect(harry.square("e4")).to_be_focused()
    harry.page.keyboard.press("Enter")
    partner.wait_ply(1)
    expect(partner.page.locator("#announcer")).to_contain_text("Pawn to e4")  # REQ-UI-12


def test_menu_flip_and_pgn_link(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    harry.page.get_by_role("button", name="Game menu").click()
    harry.page.get_by_role("menuitem", name="Flip board").click()
    expect(harry.page.locator(".sq").first).to_have_attribute("data-square", "h1")
    harry.page.reload()
    harry.wait_live()
    expect(harry.page.locator(".sq").first).to_have_attribute("data-square", "h1")  # remembered
    expect(harry.page.locator("#menu-pgn")).to_have_attribute("href", f"/api/games/{game_id}/pgn")


def test_unknown_game(players: tuple[Player, Player]) -> None:
    harry, _ = players
    harry.goto(f"/game/{NOT_FOUND_ID}")
    expect(harry.page.get_by_role("heading", name="This game doesn't exist.")).to_be_visible()
    # The page's own snapshot request is the expected 404; anything else still counts.
    harry.problems = [p for p in harry.problems if "status of 404" not in p]


@pytest.mark.parametrize("width", [320, 430])
def test_narrow_and_wide_phones_do_not_scroll_sideways(
    players: tuple[Player, Player], width: int
) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    for player in (harry, partner):
        player.page.set_viewport_size({"width": width, "height": 700})
        assert no_horizontal_scroll(player.page)
        player.goto("/")
        expect(player.page.locator("#start")).to_be_enabled()
        assert no_horizontal_scroll(player.page)
    harry.shot(f"lobby-{width}")


def test_sound_off_by_default_and_remembered(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    menu = harry.page.get_by_role("button", name="Game menu")
    menu.click()
    expect(harry.page.get_by_role("menuitem", name="Sound: off")).to_be_visible()  # REQ-UI-09
    harry.page.get_by_role("menuitem", name="Sound: off").click()
    harry.page.reload()
    harry.wait_live()
    menu.click()
    expect(harry.page.get_by_role("menuitem", name="Sound: on")).to_be_visible()


def test_reconnects_and_locks_input_while_down(players: tuple[Player, Player]) -> None:
    harry, partner = players
    game_id = start_game(harry, partner, "white")
    routes: list[Any] = []

    def through(ws: Any) -> None:
        ws.connect_to_server()
        routes.append(ws)

    harry.page.route_web_socket(re.compile(r"/ws/games/"), through)
    harry.page.reload()
    harry.wait_live()
    # Drop the connection from the "network" side: the page must notice, lock the board
    # and reconnect with a fresh hello (REQ-UI-06, REQ-UI-07).
    routes[-1].close(code=1006)
    expect(harry.page.locator(".pill--reconnecting, .pill:not(.pill--live)").first).to_be_visible()
    expect(harry.page.locator(".board--locked")).to_be_visible()
    harry.wait_live()
    assert len(routes) >= 2
    harry.tap_move("e2e4")
    partner.wait_ply(1)
    assert game_id in harry.page.url


def test_move_stays_pending_through_unrelated_state(players: tuple[Player, Player]) -> None:
    """B4: a same-ply state (opponent offers a draw) must not unlock a move in flight."""
    harry, partner = players
    start_game(harry, partner, "white")
    held: list[str] = []
    routes: list[Any] = []

    def hold_moves(ws: Any) -> None:
        server = ws.connect_to_server()

        def from_page(message: Any) -> None:
            if isinstance(message, str) and '"type":"move"' in message.replace(" ", ""):
                held.append(message)
            else:
                server.send(message)

        ws.on_message(from_page)
        routes.append(server)

    harry.page.route_web_socket(re.compile(r"/ws/games/"), hold_moves)
    harry.page.reload()
    harry.wait_live()
    harry.tap_move("e2e4")
    expect(harry.page.locator('[data-testid="turn"]')).to_have_text("Sending…")
    partner.page.locator('[data-testid="draw"]').click()
    expect(harry.page.locator('[data-testid="draw-offer"]')).to_be_visible()
    expect(harry.page.locator('[data-testid="turn"]')).to_have_text("Sending…")
    expect(harry.page.locator(".board--locked")).to_be_visible()
    routes[-1].send(held.pop())
    partner.wait_ply(1)
    expect(harry.page.locator('[data-testid="status"]')).to_have_text(re.compile(r"'s move$"))


def test_takeback_outline_marks_requesters_move(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    harry.tap_move("e2e4")
    partner.wait_ply(1)
    partner.tap_move("e7e5")
    harry.wait_ply(2)
    harry.page.locator('[data-testid="takeback"]').click()  # two plies: e5 and e4
    expect(partner.page.locator('[data-testid="takeback-offer"]')).to_be_visible()
    expect(partner.square("e2")).to_have_class(re.compile(r"sq--outlined"))
    expect(partner.square("e4")).to_have_class(re.compile(r"sq--outlined"))
    expect(partner.square("e5")).not_to_have_class(re.compile(r"sq--outlined"))


def test_screen_reader_activation_and_keyboard_resign(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    # Assistive tech "activate" is a bare click (detail 0).
    harry.page.evaluate("document.querySelector('[data-square=\"e2\"]').click()")
    expect(harry.square("e2")).to_have_class(re.compile(r"sq--selected"))
    harry.page.evaluate("document.querySelector('[data-square=\"e4\"]').click()")
    partner.wait_ply(1)
    # Resign from the keyboard: focus survives the re-render between the two presses.
    resign = partner.page.locator('[data-testid="resign"]')
    resign.focus()
    partner.page.keyboard.press("Enter")
    expect(resign).to_contain_text("Tap again to resign")
    expect(resign).to_be_focused()
    partner.page.keyboard.press("Enter")
    expect(partner.page.locator('[data-testid="status"]')).to_contain_text("You resigned")


def test_signed_out_pill_fits_narrow_phone(players: tuple[Player, Player]) -> None:
    harry, partner = players
    start_game(harry, partner, "white")
    routes: list[Any] = []

    def through(ws: Any) -> None:
        ws.connect_to_server()
        routes.append(ws)

    harry.page.set_viewport_size({"width": 320, "height": 700})
    harry.page.route_web_socket(re.compile(r"/ws/games/"), through)
    harry.page.reload()
    harry.wait_live()
    routes[-1].close(code=1008, reason="signed out")
    expect(harry.page.locator(".pill--signedout")).to_contain_text("Signed out")
    expect(harry.page.locator(".board--locked")).to_be_visible()
    assert no_horizontal_scroll(harry.page)
