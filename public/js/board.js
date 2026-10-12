// The interactive board: 64 buttons, tap-tap and drag input, promotion picker, keyboard.
// It renders only what it is given and asks the page to send moves; it never decides
// legality beyond reading the server's `legal` list (REQ-UI-02..05, REQ-UI-12, REQ-UI-14).

import {
  coordinates,
  displayOrder,
  glyph,
  isDark,
  kingSquare,
  movesBetween,
  moveSquares,
  needsPromotion,
  neighbour,
  parseFen,
  pieceColour,
  previewMove,
  squareLabel,
  targetsFrom,
} from "./board-model.js";

const DRAG_THRESHOLD_PX = 6;
const PROMOTION_PIECES = ["q", "r", "b", "n"];
const PROMOTION_NAMES = { q: "Queen", r: "Rook", b: "Bishop", n: "Knight" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export class BoardView {
  /**
   * @param {HTMLElement} board   the .board element
   * @param {HTMLElement} frame   the element the promotion picker overlays
   * @param {{onMove: (uci: string) => void, onPromotionOpen?: (open: boolean) => void}} hooks
   */
  constructor(board, frame, hooks) {
    this.board = board;
    this.frame = frame;
    this.hooks = hooks;
    this.view = null;
    this.pieces = new Map();
    this.bottom = null;
    this.cells = new Map();
    this.selected = null;
    this.focusSquare = null;
    this.drag = null;
    this.promo = null;
    this._build();
    board.addEventListener("pointerdown", (event) => this._onPointerDown(event));
    board.addEventListener("pointermove", (event) => this._onPointerMove(event));
    board.addEventListener("pointerup", (event) => this._onPointerUp(event));
    board.addEventListener("pointercancel", () => this._cancelDrag());
    board.addEventListener("lostpointercapture", () => this._cancelDrag());
    board.addEventListener("keydown", (event) => this._onKeyDown(event));
    board.addEventListener("contextmenu", (event) => event.preventDefault());
    // Screen readers (VoiceOver's activate, NVDA browse-mode Enter) send a bare click with
    // detail 0. Pointer input is handled above and keyboard Enter/Space in _onKeyDown.
    board.addEventListener("click", (event) => {
      if (event.detail !== 0) return;
      const cell = event.target.closest(".sq");
      if (cell) this.activate(cell.dataset.square);
    });
    board.addEventListener("focusin", (event) => {
      const cell = event.target.closest(".sq");
      if (cell) this.focusSquare = cell.dataset.square;
    });
  }

  /**
   * view = { fen, you, bottom, legal, lastMove, check, turn, interactive, pending, outline }
   *   interactive: true only when it's your turn, the socket is live and no move is pending.
   *   pending:     UCI shown faded while waiting for the server (B4), or null.
   *   outline:     squares to outline (opponent's move offered for takeback, B13a).
   */
  update(view) {
    this.view = view;
    this.pieces = view.pending ? previewMove(parseFen(view.fen), view.pending) : parseFen(view.fen);
    if (view.bottom !== this.bottom) {
      this.bottom = view.bottom;
      this._layout();
    }
    if (this.selected) {
      const piece = this.pieces.get(this.selected);
      if (!piece || pieceColour(piece) !== view.you || view.pending) this.selected = null;
    }
    if (!view.interactive) this._closePromotion();
    this._paint();
  }

  clearSelection() {
    this.selected = null;
    this._closePromotion();
    if (this.view) this._paint();
  }

  get promotionOpen() {
    return this.promo !== null;
  }

  // -------------------------------------------------------------- building

  _build() {
    this.board.replaceChildren();
    for (let index = 0; index < 64; index += 1) {
      const cell = el("button", "sq");
      cell.type = "button";
      cell.tabIndex = -1;
      const rank = el("span", "sq__coord sq__coord--rank");
      const file = el("span", "sq__coord sq__coord--file");
      const target = el("span", "sq__target");
      const piece = el("span", "piece");
      rank.setAttribute("aria-hidden", "true");
      file.setAttribute("aria-hidden", "true");
      target.setAttribute("aria-hidden", "true");
      piece.setAttribute("aria-hidden", "true");
      cell.append(rank, file, target, piece);
      this.board.append(cell);
    }
  }

  _layout() {
    const order = displayOrder(this.bottom);
    this.cells.clear();
    Array.from(this.board.children).forEach((cell, index) => {
      const square = order[index];
      cell.dataset.square = square;
      const coords = coordinates(square, this.bottom);
      cell.children[0].textContent = coords.rank;
      cell.children[1].textContent = coords.file;
      cell.classList.toggle("sq--dark", isDark(square));
      this.cells.set(square, cell);
    });
    if (!this.focusSquare) this.focusSquare = this.bottom === "white" ? "e2" : "e7";
  }

  _paint() {
    const view = this.view;
    const last = new Set(moveSquares(view.lastMove));
    const outline = new Set(view.outline || []);
    const checkSquare = view.check ? kingSquare(this.pieces, view.turn) : null;
    const targets = this.selected && view.interactive ? targetsFrom(view.legal, this.selected) : new Map();
    const pendingTo = view.pending ? view.pending.slice(2, 4) : null;
    this.board.classList.toggle("board--locked", !view.interactive);

    for (const [square, cell] of this.cells) {
      const piece = this.pieces.get(square);
      const pieceNode = cell.children[3];
      const targetNode = cell.children[2];
      pieceNode.textContent = glyph(piece);
      pieceNode.className = "piece";
      if (piece) pieceNode.classList.add(pieceColour(piece) === "white" ? "piece--white" : "piece--black");
      if (square === pendingTo) pieceNode.classList.add("piece--pending");
      if (this.drag && this.drag.active && square === this.drag.from) pieceNode.classList.add("piece--lifted");

      const isTarget = targets.has(square);
      targetNode.hidden = !isTarget;
      targetNode.className = isTarget && piece ? "sq__target sq__target--capture" : "sq__target";

      cell.classList.toggle("sq--last", last.has(square));
      cell.classList.toggle("sq--selected", square === this.selected);
      cell.classList.toggle("sq--check", square === checkSquare);
      cell.classList.toggle("sq--outlined", outline.has(square));
      cell.tabIndex = square === this.focusSquare ? 0 : -1;

      let label = squareLabel(square, piece);
      if (square === this.selected) label += ", selected";
      if (isTarget) label += piece ? ", capture available" : ", move available";
      if (square === checkSquare) label += ", in check";
      if (last.has(square)) label += ", last move";
      cell.setAttribute("aria-label", label);
    }
  }

  // ------------------------------------------------------------ interaction

  _isOwn(square) {
    const piece = this.pieces.get(square);
    return Boolean(piece) && pieceColour(piece) === this.view.you;
  }

  _canSelect() {
    return this.view && this.view.status === "active" && !this.view.pending;
  }

  _isTarget(square) {
    if (!this.selected || !this.view.interactive) return false;
    return targetsFrom(this.view.legal, this.selected).has(square);
  }

  /** Shared by tap and keyboard: select, move or clear. Returns what happened. */
  activate(square) {
    if (!this.view || this.promo) return "none";
    if (this._isTarget(square)) {
      this._tryMove(this.selected, square);
      return "move";
    }
    if (this._canSelect() && this._isOwn(square)) {
      this.selected = this.selected === square ? null : square;
      this._paint();
      return this.selected ? "select" : "clear";
    }
    if (this.selected) {
      this.selected = null;
      this._paint();
      return "clear";
    }
    return "none";
  }

  _tryMove(from, to) {
    const candidates = movesBetween(this.view.legal, from, to);
    if (candidates.length === 0) return;
    if (needsPromotion(candidates)) {
      this._openPromotion(from, to);
      return;
    }
    this.selected = null;
    this.hooks.onMove(candidates[0]);
  }

  _squareAt(x, y) {
    const hit = document.elementFromPoint(x, y);
    const cell = hit ? hit.closest(".sq") : null;
    return cell && this.board.contains(cell) ? cell.dataset.square : null;
  }

  _onPointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    const cell = event.target.closest(".sq");
    if (!cell || !this.view || this.promo) return;
    event.preventDefault();
    const square = cell.dataset.square;
    this.focusSquare = square;

    if (this._isTarget(square)) {
      this._tryMove(this.selected, square);
      return;
    }
    if (this._canSelect() && this._isOwn(square)) {
      const wasSelected = this.selected === square;
      this.selected = square;
      this.drag = {
        from: square,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        active: false,
        wasSelected,
        ghost: null,
        hover: null,
      };
      try {
        this.board.setPointerCapture(event.pointerId);
      } catch (error) {
        // capture is a nicety; dragging still works within the board
      }
      this._paint();
      return;
    }
    if (this.selected) {
      this.selected = null;
      this._paint();
    }
  }

  _onPointerMove(event) {
    const drag = this.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.active) {
      const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
      if (distance < DRAG_THRESHOLD_PX) return;
      drag.active = true;
      const cell = this.cells.get(drag.from);
      const size = cell.getBoundingClientRect().width;
      const ghost = el("div", `drag-ghost ${cell.children[3].className}`, cell.children[3].textContent);
      ghost.classList.remove("piece--pending", "piece");
      ghost.setAttribute("aria-hidden", "true");
      ghost.style.fontSize = `${Math.round(size * 0.83)}px`;
      ghost.style.width = `${size}px`;
      ghost.style.height = `${size}px`;
      ghost.style.display = "flex";
      ghost.style.alignItems = "center";
      ghost.style.justifyContent = "center";
      document.body.append(ghost);
      drag.ghost = ghost;
      drag.size = size;
      this._paint();
    }
    const half = drag.size / 2;
    drag.ghost.style.transform = `translate(${event.clientX - half}px, ${event.clientY - half}px)`;
    const over = this._squareAt(event.clientX, event.clientY);
    if (over !== drag.hover) {
      if (drag.hover) this.cells.get(drag.hover)?.classList.remove("sq--drop-hover");
      drag.hover = over;
      if (over && this._isTarget(over)) this.cells.get(over).classList.add("sq--drop-hover");
    }
  }

  _onPointerUp(event) {
    const drag = this.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    this.drag = null;
    this._removeGhost(drag);
    if (drag.active) {
      const drop = this._squareAt(event.clientX, event.clientY);
      if (drop && drop !== drag.from && this._isTarget(drop)) {
        this._tryMove(drag.from, drop);
      }
      // Any other drop snaps back silently; the piece stays selected.
      if (this.view) this._paint();
      return;
    }
    if (drag.wasSelected) {
      this.selected = null; // second tap on the same piece deselects it
      this._paint();
    }
  }

  _cancelDrag() {
    const drag = this.drag;
    if (!drag) return;
    this.drag = null;
    this._removeGhost(drag);
    if (this.view) this._paint();
  }

  _removeGhost(drag) {
    if (drag.ghost) drag.ghost.remove();
    if (drag.hover) this.cells.get(drag.hover)?.classList.remove("sq--drop-hover");
  }

  _onKeyDown(event) {
    if (this.promo) return; // the picker handles its own keys
    const cell = event.target.closest(".sq");
    if (!cell) return;
    const square = cell.dataset.square;
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next = neighbour(square, event.key, this.bottom);
      this.focusSquare = next;
      this._paint();
      this.cells.get(next).focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      this.activate(square);
      return;
    }
    if (event.key === "Escape" && this.selected) {
      event.preventDefault();
      this.selected = null;
      this._paint();
    }
  }

  // -------------------------------------------------------------- promotion

  _openPromotion(from, to) {
    this._closePromotion();
    const overlay = el("div", "promo");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Choose a piece");
    const panel = el("div", "promo__panel");
    const title = el("p", "promo__title", "Choose a piece");
    const choices = el("div", "promo__choices");
    const colourClass = this.view.you === "white" ? "piece--white" : "piece--black";
    for (const letter of PROMOTION_PIECES) {
      const button = el("button", `promo__choice ${colourClass}`);
      button.type = "button";
      button.dataset.piece = letter;
      button.setAttribute("aria-label", PROMOTION_NAMES[letter]);
      button.textContent = glyph(this.view.you === "white" ? letter.toUpperCase() : letter);
      button.addEventListener("click", () => {
        this._closePromotion();
        this.selected = null;
        this.focusSquare = to;
        this.hooks.onMove(`${from}${to}${letter}`);
        const cell = this.cells.get(to);
        if (cell) cell.focus(); // keep keyboard focus on the board
      });
      choices.append(button);
    }
    const cancel = el("button", "btn btn--small btn--ghost", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", () => this._cancelPromotion());
    panel.append(title, choices, cancel);
    overlay.append(panel);
    overlay.addEventListener("pointerdown", (event) => {
      if (event.target === overlay) this._cancelPromotion(); // tap outside cancels
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        this._cancelPromotion();
      }
    });
    this.frame.append(overlay);
    this.promo = overlay;
    if (this.hooks.onPromotionOpen) this.hooks.onPromotionOpen(true);
    choices.firstChild.focus();
  }

  _cancelPromotion() {
    const from = this.selected;
    this._closePromotion();
    this.selected = null; // start again from a clean board
    if (this.view) this._paint();
    const cell = from && this.cells.get(from);
    if (cell) cell.focus();
  }

  _closePromotion() {
    if (!this.promo) return;
    this.promo.remove();
    this.promo = null;
    if (this.hooks.onPromotionOpen) this.hooks.onPromotionOpen(false);
  }
}
