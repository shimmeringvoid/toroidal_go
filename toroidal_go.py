#!/usr/bin/env python3
"""
Toroidal Go — a Go variant played on the surface of a torus.

Features:
  • User-selectable board dimensions (5×5 to 19×19)
  • Two display modes: Rectangular (flat) and Torus (3-D wireframe)
  • Rectangular mode: right-click to re-centre; left-drag to translate
  • Torus mode: left-drag to slide mesh on surface; right-drag to rotate
    the entire torus in 3-D
  • Left-click to place a stone (alternating Black / White)
  • Full undo / redo with branching game tree
  • Save / load games as .tgo JSON files (in-app file picker — no tkinter)
  • Replay loaded games; explore alternate lines from any point
  • Scoring: when both players pass consecutively, territory is tallied
    (area scoring) and the winner is displayed

Controls summary (also shown in-app):
  Left-click           Place stone / press button
  Left-drag (rect)     Translate board (wrapping)
  Right-click (rect)   Re-centre board on that intersection
  Left-drag (torus)    Slide mesh on torus surface
  Right-drag (torus)   Rotate entire torus in 3-D
  U / ←                Undo
  R / →                Redo (main line) ;  ↑↓ pick variation
  P                    Pass
  V                    Toggle view (rectangular ↔ torus)
  Ctrl+S               Save game
  Ctrl+O               Open game
  Ctrl+N               New game
  +/-  / scroll        Zoom torus view
"""

import pygame
import numpy as np
import math
import json
import os
import sys
import glob
from copy import deepcopy

# ─── Constants ───────────────────────────────────────────────────────
EMPTY, BLACK, WHITE = 0, 1, 2
COLOR_NAMES = {BLACK: "Black", WHITE: "White"}
STONE_CHARS = {BLACK: "B", WHITE: "W"}

# Colours (RGB)
COL_BG           = (42, 44, 52)
COL_BOARD        = (222, 184, 110)
COL_BOARD_EDGE   = (180, 140, 70)
COL_GRID         = (60, 50, 30)
COL_GRID_WRAP    = (200, 80, 80)
COL_BLACK_STONE  = (25, 25, 30)
COL_WHITE_STONE  = (240, 240, 235)
COL_PANEL        = (55, 58, 68)
COL_PANEL_LIGHT  = (72, 76, 90)
COL_TEXT          = (220, 220, 220)
COL_TEXT_DIM      = (150, 150, 160)
COL_HIGHLIGHT    = (100, 180, 255)
COL_BUTTON       = (80, 85, 100)
COL_BUTTON_HOV   = (100, 110, 135)
COL_BUTTON_TEXT  = (230, 230, 230)
COL_TORUS_BG     = (210, 215, 210)
COL_TORUS_LINE   = (50, 40, 20)
COL_TORUS_LINE_B = (190, 180, 150)
COL_LAST_MOVE    = (220, 60, 60)
COL_STAR         = (50, 40, 25)
COL_VARIATION    = (255, 200, 60)

INITIAL_W, INITIAL_H = 1280, 820
PANEL_W = 300

# These are mutable — updated on window resize
WINDOW_W, WINDOW_H = INITIAL_W, INITIAL_H
BOARD_AREA_W = WINDOW_W - PANEL_W
BOARD_AREA_H = WINDOW_H

FPS = 40
KOMI = 6.5   # white's compensation


# ─── Game tree node ──────────────────────────────────────────────────
class GameNode:
    __slots__ = ("move", "parent", "children", "board", "captures",
                 "move_number")

    def __init__(self, move=None, parent=None):
        self.move = move
        self.parent = parent
        self.children: list["GameNode"] = []
        self.board: np.ndarray | None = None
        self.captures = {BLACK: 0, WHITE: 0}
        self.move_number = 0

    def add_child(self, child: "GameNode") -> "GameNode":
        child.parent = self
        child.move_number = self.move_number + 1
        self.children.append(child)
        return child


# ─── Toroidal Go logic ──────────────────────────────────────────────
class ToroidalGoGame:
    def __init__(self, size: int = 9):
        self.size = size
        self.root = GameNode()
        self.root.board = np.zeros((size, size), dtype=np.int8)
        self.root.captures = {BLACK: 0, WHITE: 0}
        self.root.move_number = 0
        self.current = self.root
        self.turn = BLACK
        self.game_over = False
        self.score_result: dict | None = None

    def neighbors(self, r, c):
        N = self.size
        return [((r - 1) % N, c), ((r + 1) % N, c),
                (r, (c - 1) % N), (r, (c + 1) % N)]

    def _group_liberties(self, board, r, c):
        colour = board[r, c]
        if colour == EMPTY:
            return set(), set()
        group, liberties, stack = set(), set(), [(r, c)]
        while stack:
            pr, pc = stack.pop()
            if (pr, pc) in group:
                continue
            group.add((pr, pc))
            for nr, nc in self.neighbors(pr, pc):
                v = board[nr, nc]
                if v == EMPTY:
                    liberties.add((nr, nc))
                elif v == colour and (nr, nc) not in group:
                    stack.append((nr, nc))
        return group, liberties

    # -- scoring (Chinese-style area scoring) --
    def compute_score(self) -> dict:
        board = self.current.board
        N = self.size
        visited = np.zeros((N, N), dtype=bool)
        territory = {BLACK: 0, WHITE: 0}
        stones = {BLACK: 0, WHITE: 0}

        for r in range(N):
            for c in range(N):
                if board[r, c] in (BLACK, WHITE):
                    stones[board[r, c]] += 1

        for r in range(N):
            for c in range(N):
                if board[r, c] != EMPTY or visited[r, c]:
                    continue
                region = []
                borders = set()
                queue = [(r, c)]
                visited[r, c] = True
                while queue:
                    pr, pc = queue.pop(0)
                    region.append((pr, pc))
                    for nr, nc in self.neighbors(pr, pc):
                        if board[nr, nc] != EMPTY:
                            borders.add(board[nr, nc])
                        elif not visited[nr, nc]:
                            visited[nr, nc] = True
                            queue.append((nr, nc))
                if len(borders) == 1:
                    owner = borders.pop()
                    territory[owner] += len(region)

        black_total = stones[BLACK] + territory[BLACK]
        white_total = stones[WHITE] + territory[WHITE] + KOMI
        if black_total > white_total:
            winner = "Black"
        elif white_total > black_total:
            winner = "White"
        else:
            winner = "Tie"

        return {
            "black_stones": stones[BLACK],
            "black_territory": territory[BLACK],
            "black_total": black_total,
            "white_stones": stones[WHITE],
            "white_territory": territory[WHITE],
            "white_total": white_total,
            "komi": KOMI,
            "winner": winner,
        }

    def make_move(self, row: int, col: int) -> bool:
        if self.game_over:
            return False
        board = self.current.board.copy()
        if board[row, col] != EMPTY:
            return False

        colour = self.turn
        opp = WHITE if colour == BLACK else BLACK
        board[row, col] = colour

        captured = set()
        for nr, nc in self.neighbors(row, col):
            if board[nr, nc] == opp:
                grp, libs = self._group_liberties(board, nr, nc)
                if not libs:
                    captured |= grp
        for r, c in captured:
            board[r, c] = EMPTY

        if not captured:
            _, libs = self._group_liberties(board, row, col)
            if not libs:
                return False

        if self.current.parent is not None:
            if np.array_equal(board, self.current.parent.board):
                return False

        for ch in self.current.children:
            if ch.move == (colour, row, col):
                self.current = ch
                self.turn = opp
                self.game_over = False
                self.score_result = None
                return True

        node = GameNode(move=(colour, row, col), parent=self.current)
        node.board = board
        node.captures = dict(self.current.captures)
        node.captures[colour] += len(captured)
        self.current.add_child(node)
        self.current = node
        self.turn = opp
        self.game_over = False
        self.score_result = None
        return True

    def pass_move(self):
        if self.game_over:
            return
        colour = self.turn
        opp = WHITE if colour == BLACK else BLACK

        for ch in self.current.children:
            if ch.move == (colour, "pass"):
                self.current = ch
                self.turn = opp
                self._check_double_pass()
                return

        node = GameNode(move=(colour, "pass"), parent=self.current)
        node.board = self.current.board.copy()
        node.captures = dict(self.current.captures)
        self.current.add_child(node)
        self.current = node
        self.turn = opp
        self._check_double_pass()

    def _check_double_pass(self):
        cur = self.current
        if (cur.move and cur.move[1] == "pass" and
                cur.parent and cur.parent.move and
                cur.parent.move[1] == "pass"):
            self.game_over = True
            self.score_result = self.compute_score()

    def undo(self) -> bool:
        if self.current.parent is None:
            return False
        move = self.current.move
        if move is not None:
            self.turn = move[0]
        self.current = self.current.parent
        self.game_over = False
        self.score_result = None
        return True

    def redo(self, variation: int = 0) -> bool:
        if not self.current.children:
            return False
        idx = max(0, min(variation, len(self.current.children) - 1))
        self.current = self.current.children[idx]
        move = self.current.move
        if move is not None:
            self.turn = WHITE if move[0] == BLACK else BLACK
        self._check_double_pass()
        return True

    def move_count(self) -> int:
        return self.current.move_number

    def variation_count(self) -> int:
        return len(self.current.children)


# ─── Save / Load (.tgo JSON) ────────────────────────────────────────
def _node_to_dict(node: GameNode) -> dict:
    d: dict = {}
    if node.move is not None:
        colour, *rest = node.move
        if rest and rest[0] == "pass":
            d["move"] = {"c": STONE_CHARS[colour], "pass": True}
        else:
            d["move"] = {"c": STONE_CHARS[colour], "r": int(rest[0]),
                         "col": int(rest[1])}
    if node.children:
        d["children"] = [_node_to_dict(ch) for ch in node.children]
    return d


def _dict_to_node(d: dict, parent: GameNode, game: ToroidalGoGame) -> GameNode:
    if "move" not in d:
        return parent
    m = d["move"]
    colour = BLACK if m["c"] == "B" else WHITE
    if m.get("pass"):
        move = (colour, "pass")
    else:
        move = (colour, m["r"], m["col"])
    node = GameNode(move=move, parent=parent)

    board = parent.board.copy()
    opp = WHITE if colour == BLACK else BLACK
    if not m.get("pass"):
        r, c = m["r"], m["col"]
        board[r, c] = colour
        captured = set()
        for nr, nc in game.neighbors(r, c):
            if board[nr, nc] == opp:
                grp, libs = game._group_liberties(board, nr, nc)
                if not libs:
                    captured |= grp
        for cr, cc in captured:
            board[cr, cc] = EMPTY
        node.captures = dict(parent.captures)
        node.captures[colour] += len(captured)
    else:
        node.captures = dict(parent.captures)

    node.board = board
    parent.add_child(node)

    for ch in d.get("children", []):
        _dict_to_node(ch, node, game)
    return node


def save_game(game: ToroidalGoGame, path: str):
    data = {
        "format": "toroidal-go",
        "version": 1,
        "board_size": game.size,
        "tree": _node_to_dict(game.root),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_game(path: str) -> ToroidalGoGame:
    with open(path) as f:
        data = json.load(f)
    size = data["board_size"]
    game = ToroidalGoGame(size)
    for ch in data["tree"].get("children", []):
        _dict_to_node(ch, game.root, game)
    game.current = game.root
    game.turn = BLACK
    return game


# ─── UI helpers ──────────────────────────────────────────────────────
class Button:
    def __init__(self, rect: pygame.Rect, label: str, key_hint: str = "",
                 callback=None):
        self.rect = rect
        self.label = label
        self.key_hint = key_hint
        self.callback = callback
        self.hovered = False

    def draw(self, surf, font, small_font):
        col = COL_BUTTON_HOV if self.hovered else COL_BUTTON
        pygame.draw.rect(surf, col, self.rect, border_radius=6)
        pygame.draw.rect(surf, (100, 105, 120), self.rect, 1, border_radius=6)
        lbl = font.render(self.label, True, COL_BUTTON_TEXT)
        surf.blit(lbl, lbl.get_rect(center=self.rect.center))
        if self.key_hint:
            h = small_font.render(self.key_hint, True, COL_TEXT_DIM)
            surf.blit(h, (self.rect.right - h.get_width() - 6,
                          self.rect.bottom - h.get_height() - 2))

    def check_hover(self, pos):
        self.hovered = self.rect.collidepoint(pos)

    def check_click(self, pos) -> bool:
        if self.rect.collidepoint(pos):
            if self.callback:
                self.callback()
            return True
        return False


# ─── In-app file picker (no tkinter dependency) ─────────────────────
class FilePicker:
    def __init__(self, mode="save", extension=".tgo",
                 start_dir=None, title="File"):
        self.mode = mode
        self.extension = extension
        self.title = title
        self.active = True
        self.result: str | None = None

        self.directory = start_dir or os.path.expanduser("~")
        self.files: list[str] = []
        self.dirs: list[str] = []
        self.scroll = 0
        self.selected_idx = -1
        self.input_text = ""
        self.cursor_blink = 0
        self._scan_dir()

    def _scan_dir(self):
        self.files = []
        self.dirs = []
        self.scroll = 0
        self.selected_idx = -1
        try:
            entries = sorted(os.listdir(self.directory), key=str.lower)
        except PermissionError:
            entries = []
        for e in entries:
            full = os.path.join(self.directory, e)
            if os.path.isdir(full) and not e.startswith("."):
                self.dirs.append(e)
            elif os.path.isfile(full) and e.endswith(self.extension):
                self.files.append(e)

    @property
    def _entries(self):
        return [".. (up)"] + [d + "/" for d in self.dirs] + self.files

    def handle_event(self, ev):
        if not self.active:
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.active = False
                return
            if self.mode == "save":
                if ev.key == pygame.K_RETURN:
                    name = self.input_text.strip()
                    if name:
                        if not name.endswith(self.extension):
                            name += self.extension
                        self.result = os.path.join(self.directory, name)
                        self.active = False
                    return
                elif ev.key == pygame.K_BACKSPACE:
                    self.input_text = self.input_text[:-1]
                else:
                    ch = ev.unicode
                    if ch and ch.isprintable() and ch not in '/\\:*?"<>|':
                        self.input_text += ch
            if self.mode == "load":
                if ev.key == pygame.K_RETURN and self.selected_idx >= 0:
                    self._activate_entry(self.selected_idx)
                elif ev.key == pygame.K_UP:
                    self.selected_idx = max(0, self.selected_idx - 1)
                elif ev.key == pygame.K_DOWN:
                    self.selected_idx = min(len(self._entries) - 1,
                                            self.selected_idx + 1)

        if ev.type == pygame.MOUSEBUTTONDOWN:
            bx, by = ev.pos
            list_rect = self._list_rect()
            if list_rect.collidepoint(bx, by) and ev.button == 1:
                row = (by - list_rect.top + self.scroll) // 24
                if 0 <= row < len(self._entries):
                    self.selected_idx = row
                    self._activate_entry(row)
            cancel_r = pygame.Rect(WINDOW_W // 2 + 60, WINDOW_H // 2 + 155,
                                   100, 32)
            if cancel_r.collidepoint(bx, by) and ev.button == 1:
                self.active = False
            if self.mode == "save":
                ok_r = pygame.Rect(WINDOW_W // 2 - 160, WINDOW_H // 2 + 155,
                                   100, 32)
                if ok_r.collidepoint(bx, by) and ev.button == 1:
                    name = self.input_text.strip()
                    if name:
                        if not name.endswith(self.extension):
                            name += self.extension
                        self.result = os.path.join(self.directory, name)
                        self.active = False
            if ev.button == 4:
                self.scroll = max(0, self.scroll - 24)
            elif ev.button == 5:
                self.scroll += 24

    def _activate_entry(self, idx):
        entries = self._entries
        if idx < 0 or idx >= len(entries):
            return
        name = entries[idx]
        if name == ".. (up)":
            parent = os.path.dirname(self.directory)
            if parent and parent != self.directory:
                self.directory = parent
                self._scan_dir()
        elif name.endswith("/"):
            self.directory = os.path.join(self.directory, name[:-1])
            self._scan_dir()
        else:
            if self.mode == "load":
                self.result = os.path.join(self.directory, name)
                self.active = False
            else:
                self.input_text = name

    def _list_rect(self):
        return pygame.Rect(WINDOW_W // 2 - 200, WINDOW_H // 2 - 120,
                           400, 240)

    def draw(self, screen, font, font_sm):
        if not self.active:
            return
        self.cursor_blink = (self.cursor_blink + 1) % 60

        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))

        dlg = pygame.Rect(WINDOW_W // 2 - 220, WINDOW_H // 2 - 180,
                          440, 400)
        pygame.draw.rect(screen, COL_PANEL, dlg, border_radius=10)
        pygame.draw.rect(screen, COL_HIGHLIGHT, dlg, 2, border_radius=10)

        t = font.render(self.title, True, COL_HIGHLIGHT)
        screen.blit(t, (dlg.x + 20, dlg.y + 12))

        d_text = self.directory
        if len(d_text) > 50:
            d_text = "..." + d_text[-47:]
        dt = font_sm.render(d_text, True, COL_TEXT_DIM)
        screen.blit(dt, (dlg.x + 20, dlg.y + 38))

        lr = self._list_rect()
        pygame.draw.rect(screen, (35, 37, 45), lr, border_radius=4)
        clip_prev = screen.get_clip()
        screen.set_clip(lr)
        entries = self._entries
        for i, name in enumerate(entries):
            y = lr.top + i * 24 - self.scroll
            if y < lr.top - 24 or y > lr.bottom:
                continue
            if i == self.selected_idx:
                pygame.draw.rect(screen, (60, 80, 120),
                                 (lr.x, y, lr.w, 24))
            col = (COL_HIGHLIGHT if name.endswith("/") or name.startswith("..")
                   else COL_TEXT)
            et = font_sm.render(name, True, col)
            screen.blit(et, (lr.x + 8, y + 3))
        screen.set_clip(clip_prev)
        pygame.draw.rect(screen, (80, 85, 100), lr, 1, border_radius=4)

        if self.mode == "save":
            lbl = font_sm.render("Filename:", True, COL_TEXT)
            screen.blit(lbl, (dlg.x + 20, dlg.y + 310))
            inp_r = pygame.Rect(dlg.x + 20, dlg.y + 328, 400, 26)
            pygame.draw.rect(screen, (35, 37, 45), inp_r, border_radius=4)
            pygame.draw.rect(screen, COL_HIGHLIGHT, inp_r, 1, border_radius=4)
            cursor = "|" if self.cursor_blink < 30 else ""
            it = font_sm.render(self.input_text + cursor, True, COL_TEXT)
            screen.blit(it, (inp_r.x + 6, inp_r.y + 5))

            ok_r = pygame.Rect(WINDOW_W // 2 - 160, WINDOW_H // 2 + 155,
                               100, 32)
            pygame.draw.rect(screen, COL_BUTTON, ok_r, border_radius=6)
            st = font_sm.render("Save", True, COL_BUTTON_TEXT)
            screen.blit(st, st.get_rect(center=ok_r.center))

        cancel_r = pygame.Rect(WINDOW_W // 2 + 60, WINDOW_H // 2 + 155,
                               100, 32)
        pygame.draw.rect(screen, COL_BUTTON, cancel_r, border_radius=6)
        ct = font_sm.render("Cancel", True, COL_BUTTON_TEXT)
        screen.blit(ct, ct.get_rect(center=cancel_r.center))


# ─── 3-D helpers ─────────────────────────────────────────────────────
def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)

def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)

def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


# ─── MAIN APPLICATION ────────────────────────────────────────────────
class ToroidalGoApp:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("Toroidal Go")
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("dejavusans", 16)
        self.font_sm = pygame.font.SysFont("dejavusans", 12)
        self.font_lg = pygame.font.SysFont("dejavusans", 22, bold=True)
        self.font_xl = pygame.font.SysFont("dejavusans", 36, bold=True)
        self.font_score = pygame.font.SysFont("dejavusans", 18, bold=True)

        self.game: ToroidalGoGame | None = None
        self.view_mode = "rect"
        self.running = True
        self.selecting_size = True
        self.selected_size = 9
        self.status_msg = ""
        self.status_timer = 0
        self.selected_variation = 0

        # Rect view
        self.offset_r = 0
        self.offset_c = 0
        self.rect_dragging = False
        self.rect_drag_start = (0, 0)
        self.rect_drag_offset_r0 = 0
        self.rect_drag_offset_c0 = 0

        # Torus view
        self.u_offset = 0.0
        self.v_offset = 0.0
        self.torus_zoom = 1.0
        self.view_tilt = 0.55
        self.view_spin = 0.3
        # Left-drag: slide mesh
        self.dragging_torus_surface = False
        self.surf_drag_start = (0, 0)
        self.surf_drag_u0 = 0.0
        self.surf_drag_v0 = 0.0
        # Right-drag: rotate 3-D
        self.dragging_torus_rotate = False
        self.rot_drag_start = (0, 0)
        self.rot_drag_tilt0 = 0.0
        self.rot_drag_spin0 = 0.0

        self.file_picker: FilePicker | None = None

        self.buttons: list[Button] = []
        self._build_buttons()

    def _build_buttons(self):
        x = BOARD_AREA_W + 20
        w = PANEL_W - 40
        bh = 34
        gap = 6
        y0 = WINDOW_H - 8 * (bh + gap) - 20
        def bpos(i):
            return pygame.Rect(x, y0 + i * (bh + gap), w, bh)
        self.buttons = [
            Button(bpos(0), "New Game", "Ctrl+N", self._on_new),
            Button(bpos(1), "Save", "Ctrl+S", self._on_save),
            Button(bpos(2), "Load", "Ctrl+O", self._on_load),
            Button(bpos(3), "Undo", "U / \u2190", self._on_undo),
            Button(bpos(4), "Redo", "R / \u2192", self._on_redo),
            Button(bpos(5), "Pass", "P", self._on_pass),
            Button(bpos(6), "Toggle View", "V", self._on_toggle_view),
        ]

    def _handle_resize(self, w, h):
        """Update globals and rebuild layout after window resize."""
        global WINDOW_W, WINDOW_H, BOARD_AREA_W, BOARD_AREA_H
        WINDOW_W = max(800, w)
        WINDOW_H = max(500, h)
        BOARD_AREA_W = WINDOW_W - PANEL_W
        BOARD_AREA_H = WINDOW_H
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self._build_buttons()

    def _toggle_large_window(self):
        """Toggle between default size and near-screen-size window."""
        global WINDOW_W, WINDOW_H, BOARD_AREA_W, BOARD_AREA_H
        if WINDOW_W > INITIAL_W + 50:
            # Go back to default
            self._handle_resize(INITIAL_W, INITIAL_H)
        else:
            # Go large — query screen size, leave margin for taskbar
            info = pygame.display.Info()
            self._handle_resize(info.current_w - 40, info.current_h - 80)

    def _set_status(self, msg):
        self.status_msg = msg
        self.status_timer = FPS * 3

    def _on_new(self):
        self.selecting_size = True
    def _on_save(self):
        if self.game is None:
            return
        self.file_picker = FilePicker(mode="save", extension=".tgo",
                                      start_dir=os.path.expanduser("~"),
                                      title="Save Game")
    def _on_load(self):
        self.file_picker = FilePicker(mode="load", extension=".tgo",
                                      start_dir=os.path.expanduser("~"),
                                      title="Open Game")
    def _finish_save(self, path):
        try:
            save_game(self.game, path)
            self._set_status(f"Saved to {os.path.basename(path)}")
        except Exception as e:
            self._set_status(f"Save failed: {e}")
    def _finish_load(self, path):
        try:
            self.game = load_game(path)
            self.offset_r = self.offset_c = 0
            self.u_offset = self.v_offset = 0.0
            self.selected_variation = 0
            self._set_status(f"Loaded {os.path.basename(path)}")
        except Exception as e:
            self._set_status(f"Load failed: {e}")

    def _on_undo(self):
        if self.game and self.game.undo():
            self.selected_variation = 0
    def _on_redo(self):
        if self.game:
            self.game.redo(self.selected_variation)
    def _on_pass(self):
        if self.game:
            self.game.pass_move()
            who = COLOR_NAMES[WHITE if self.game.turn == BLACK else BLACK]
            self._set_status(f"{who} passes")
            if self.game.game_over and self.game.score_result:
                s = self.game.score_result
                self._set_status(
                    f"Game over! {s['winner']} wins  "
                    f"(B {s['black_total']:.1f} \u2013 W {s['white_total']:.1f})")
    def _on_toggle_view(self):
        self.view_mode = "torus" if self.view_mode == "rect" else "rect"

    # ── Size selection ──
    def _draw_size_selection(self):
        self.screen.fill(COL_BG)
        title = self.font_xl.render("Toroidal Go", True, COL_HIGHLIGHT)
        self.screen.blit(title, title.get_rect(centerx=WINDOW_W // 2, y=80))
        sub = self.font.render("Select board size:", True, COL_TEXT)
        self.screen.blit(sub, sub.get_rect(centerx=WINDOW_W // 2, y=150))

        sizes = [5, 7, 9, 11, 13, 15, 17, 19]
        bw, bh = 70, 50
        total_w = len(sizes) * bw + (len(sizes) - 1) * 10
        sx = (WINDOW_W - total_w) // 2
        sy = 200
        self._size_rects = {}
        mx, my = pygame.mouse.get_pos()
        for i, s in enumerate(sizes):
            r = pygame.Rect(sx + i * (bw + 10), sy, bw, bh)
            self._size_rects[s] = r
            hov = r.collidepoint(mx, my)
            sel = (s == self.selected_size)
            col = COL_HIGHLIGHT if sel else (COL_BUTTON_HOV if hov else COL_BUTTON)
            pygame.draw.rect(self.screen, col, r, border_radius=8)
            lbl = self.font.render(f"{s}\u00d7{s}", True, COL_BUTTON_TEXT)
            self.screen.blit(lbl, lbl.get_rect(center=r.center))

        start_r = pygame.Rect(WINDOW_W // 2 - 80, 300, 160, 50)
        self._start_rect = start_r
        hov = start_r.collidepoint(mx, my)
        pygame.draw.rect(self.screen, COL_HIGHLIGHT if hov else COL_BUTTON,
                         start_r, border_radius=10)
        sl = self.font_lg.render("Start", True, (255, 255, 255))
        self.screen.blit(sl, sl.get_rect(center=start_r.center))

        instructions = [
            "Left-click: place stone   Left-drag (rect): translate",
            "Right-click (rect): re-centre   Right-drag (torus): rotate 3-D",
            "Left-drag (torus): slide mesh   U/\u2190: undo   R/\u2192: redo",
            "P: pass   V: toggle view   Ctrl+S: save   Ctrl+O: load",
            "Both players pass \u2192 score & winner displayed",
            "F11: toggle large window",
        ]
        for i, line in enumerate(instructions):
            t = self.font_sm.render(line, True, COL_TEXT_DIM)
            self.screen.blit(t, t.get_rect(centerx=WINDOW_W // 2, y=400 + i * 22))

    def _handle_size_click(self, pos):
        for s, r in self._size_rects.items():
            if r.collidepoint(pos):
                self.selected_size = s
                return
        if hasattr(self, "_start_rect") and self._start_rect.collidepoint(pos):
            self.game = ToroidalGoGame(self.selected_size)
            self.selecting_size = False
            self.offset_r = self.offset_c = 0
            self.u_offset = self.v_offset = 0.0
            self.selected_variation = 0

    # ── Rectangular view ──
    def _rect_params(self):
        N = self.game.size
        margin = 45
        usable = min(BOARD_AREA_W, BOARD_AREA_H) - 2 * margin
        cell = usable / max(N - 1, 1)
        ox = (BOARD_AREA_W - (N - 1) * cell) / 2
        oy = (BOARD_AREA_H - (N - 1) * cell) / 2
        return N, cell, ox, oy

    def _rect_screen_to_logical(self, sx, sy):
        N, cell, ox, oy = self._rect_params()
        gi = round((sy - oy) / cell)
        gj = round((sx - ox) / cell)
        if 0 <= gi < N and 0 <= gj < N:
            dist = math.hypot(sx - (ox + gj * cell), sy - (oy + gi * cell))
            if dist < cell * 0.45:
                lr = (gi + self.offset_r) % N
                lc = (gj + self.offset_c) % N
                return lr, lc
        return None

    def _draw_rect_view(self):
        N, cell, ox, oy = self._rect_params()
        board = self.game.current.board

        pad = cell * 0.6
        board_rect = pygame.Rect(ox - pad, oy - pad,
                                 (N - 1) * cell + 2 * pad,
                                 (N - 1) * cell + 2 * pad)
        pygame.draw.rect(self.screen, COL_BOARD, board_rect, border_radius=4)
        pygame.draw.rect(self.screen, COL_BOARD_EDGE, board_rect, 2, border_radius=4)

        strip = 4
        for sc in [COL_GRID_WRAP]:
            pygame.draw.rect(self.screen, sc, (board_rect.left, board_rect.top, board_rect.width, strip))
            pygame.draw.rect(self.screen, sc, (board_rect.left, board_rect.bottom - strip, board_rect.width, strip))
            pygame.draw.rect(self.screen, sc, (board_rect.left, board_rect.top, strip, board_rect.height))
            pygame.draw.rect(self.screen, sc, (board_rect.right - strip, board_rect.top, strip, board_rect.height))

        for i in range(N):
            y = oy + i * cell
            pygame.draw.line(self.screen, COL_GRID, (ox, y), (ox + (N-1)*cell, y), 1)
            x = ox + i * cell
            pygame.draw.line(self.screen, COL_GRID, (x, oy), (x, oy + (N-1)*cell), 1)

        for sr, sc_ in self._star_points(N):
            gi = (sr - self.offset_r) % N
            gj = (sc_ - self.offset_c) % N
            pygame.draw.circle(self.screen, COL_STAR,
                               (int(ox + gj * cell), int(oy + gi * cell)),
                               max(3, int(cell * 0.08)))

        for i in range(N):
            lr = (i + self.offset_r) % N
            lc = (i + self.offset_c) % N
            rl = self.font_sm.render(str(lr), True, COL_TEXT_DIM)
            self.screen.blit(rl, (ox - 25, oy + i * cell - rl.get_height() // 2))
            cl = self.font_sm.render(str(lc), True, COL_TEXT_DIM)
            self.screen.blit(cl, (ox + i * cell - cl.get_width() // 2, oy - 22))

        last_move = self.game.current.move
        radius = max(4, int(cell * 0.43))
        for i in range(N):
            for j in range(N):
                lr = (i + self.offset_r) % N
                lc = (j + self.offset_c) % N
                stone = board[lr, lc]
                if stone == EMPTY:
                    continue
                ssx = int(ox + j * cell)
                ssy = int(oy + i * cell)
                col = COL_BLACK_STONE if stone == BLACK else COL_WHITE_STONE
                pygame.draw.circle(self.screen, col, (ssx, ssy), radius)
                hoff = max(1, radius // 4)
                hcol = (70, 70, 80) if stone == BLACK else (255, 255, 255)
                pygame.draw.circle(self.screen, hcol, (ssx - hoff, ssy - hoff), max(1, radius // 3))
                pygame.draw.circle(self.screen, (30, 30, 30), (ssx, ssy), radius, 1)
                if last_move and last_move[0] == stone and len(last_move) == 3:
                    if last_move[1] == lr and last_move[2] == lc:
                        mcol = COL_WHITE_STONE if stone == BLACK else COL_BLACK_STONE
                        pygame.draw.circle(self.screen, mcol, (ssx, ssy), max(2, radius // 3), 2)

        for ch in self.game.current.children:
            if ch.move and len(ch.move) == 3:
                _, cr, cc = ch.move
                gi = (cr - self.offset_r) % N
                gj = (cc - self.offset_c) % N
                if board[cr, cc] == EMPTY:
                    pygame.draw.circle(self.screen, COL_VARIATION,
                                       (int(ox + gj * cell), int(oy + gi * cell)),
                                       max(2, int(cell * 0.12)), 2)

    @staticmethod
    def _star_points(N):
        pts = []
        if N >= 9:
            edge = 2 if N <= 9 else 3
            mid = N // 2
            corners = [edge, N - 1 - edge]
            for r in corners:
                for c in corners:
                    pts.append((r, c))
            if N % 2 == 1:
                pts.append((mid, mid))
                if N >= 13:
                    for p in corners:
                        pts.append((p, mid))
                        pts.append((mid, p))
        return pts

    # ── Torus view ──
    def _torus_point(self, i, j, N, R=3.0, r=1.2):
        u = 2 * math.pi * i / N + self.u_offset
        v = 2 * math.pi * j / N + self.v_offset
        return np.array([(R + r * math.cos(v)) * math.cos(u),
                         (R + r * math.cos(v)) * math.sin(u),
                         r * math.sin(v)])

    def _torus_point_uv(self, u, v, R=3.0, r=1.2):
        return np.array([(R + r * math.cos(v)) * math.cos(u),
                         (R + r * math.cos(v)) * math.sin(u),
                         r * math.sin(v)])

    def _torus_normal(self, i, j, N):
        u = 2 * math.pi * i / N + self.u_offset
        v = 2 * math.pi * j / N + self.v_offset
        return np.array([math.cos(v) * math.cos(u),
                         math.cos(v) * math.sin(u),
                         math.sin(v)])

    def _project(self, p3d, rot, cx, cy):
        """Orthographic projection: no perspective distortion."""
        p = rot @ p3d
        scale = 70.0 * self.torus_zoom
        sx = p[0] * scale + cx
        sy = -p[1] * scale + cy
        return sx, sy, p[2]

    def _draw_torus_view(self):
        N = self.game.size
        board = self.game.current.board
        R, r_minor = 3.0, 1.2
        cx = BOARD_AREA_W / 2
        cy = BOARD_AREA_H / 2
        rot = _rot_x(self.view_tilt) @ _rot_y(self.view_spin)

        pygame.draw.rect(self.screen, COL_TORUS_BG, (0, 0, BOARD_AREA_W, BOARD_AREA_H))

        def _normal_uv(u, v):
            return np.array([math.cos(v) * math.cos(u),
                             math.cos(v) * math.sin(u),
                             math.sin(v)])

        def _is_front_uv(u, v):
            n_rot = rot @ _normal_uv(u, v)
            return n_rot[2] < 0

        # ── Filled surface quads (board-coloured) ──
        # Subdivide the torus into small patches; draw front-facing ones
        SURF_DIV = max(N * 2, 24)   # smooth enough but fast
        surf_quads = []     # (depth, [4 screen points])
        TWO_PI = 2 * math.pi
        for si in range(SURF_DIV):
            for sj in range(SURF_DIV):
                u0 = TWO_PI * si / SURF_DIV + self.u_offset
                u1 = TWO_PI * (si + 1) / SURF_DIV + self.u_offset
                v0 = TWO_PI * sj / SURF_DIV + self.v_offset
                v1 = TWO_PI * (sj + 1) / SURF_DIV + self.v_offset
                # Check center normal
                u_mid = (u0 + u1) * 0.5
                v_mid = (v0 + v1) * 0.5
                if not _is_front_uv(u_mid, v_mid):
                    continue
                # Project 4 corners
                corners_3d = [
                    self._torus_point_uv(u0, v0, R, r_minor),
                    self._torus_point_uv(u1, v0, R, r_minor),
                    self._torus_point_uv(u1, v1, R, r_minor),
                    self._torus_point_uv(u0, v1, R, r_minor),
                ]
                screen_pts = []
                total_depth = 0.0
                for p3d in corners_3d:
                    sx, sy, d = self._project(p3d, rot, cx, cy)
                    screen_pts.append((int(sx), int(sy)))
                    total_depth += d
                surf_quads.append((total_depth / 4, screen_pts))

        # Draw surface quads (far first)
        surf_quads.sort(key=lambda x: -x[0])
        for _, pts in surf_quads:
            pygame.draw.polygon(self.screen, COL_BOARD, pts)

        # ── Grid lines (only front-facing segments) ──
        SEGS = 30
        front_lines = []   # (depth, p1, p2)

        for i in range(N):
            # u-circle (fixed i, sweep j)
            u_fixed = 2 * math.pi * i / N + self.u_offset
            pts = []
            fronts = []
            for s in range(SEGS + 1):
                j_f = s / SEGS * N
                v = 2 * math.pi * j_f / N + self.v_offset
                p3d = self._torus_point_uv(u_fixed, v, R, r_minor)
                sx, sy, depth = self._project(p3d, rot, cx, cy)
                pts.append((sx, sy, depth))
                fronts.append(_is_front_uv(u_fixed, v))
            for s in range(SEGS):
                if not (fronts[s] or fronts[s + 1]):
                    continue  # both back-facing → skip
                avg_d = (pts[s][2] + pts[s + 1][2]) / 2
                # Partial front: use weaker alpha
                both_front = fronts[s] and fronts[s + 1]
                front_lines.append((avg_d,
                    (pts[s][0], pts[s][1]),
                    (pts[s+1][0], pts[s+1][1]),
                    both_front))

            # v-circle (fixed j=i, sweep i_f)
            v_fixed = 2 * math.pi * i / N + self.v_offset
            pts2 = []
            fronts2 = []
            for s in range(SEGS + 1):
                i_f = s / SEGS * N
                u = 2 * math.pi * i_f / N + self.u_offset
                p3d = self._torus_point_uv(u, v_fixed, R, r_minor)
                sx, sy, depth = self._project(p3d, rot, cx, cy)
                pts2.append((sx, sy, depth))
                fronts2.append(_is_front_uv(u, v_fixed))
            for s in range(SEGS):
                if not (fronts2[s] or fronts2[s + 1]):
                    continue
                avg_d = (pts2[s][2] + pts2[s + 1][2]) / 2
                both_front = fronts2[s] and fronts2[s + 1]
                front_lines.append((avg_d,
                    (pts2[s][0], pts2[s][1]),
                    (pts2[s+1][0], pts2[s+1][1]),
                    both_front))

        # Grid intersection positions (front-facing only for stones/dots)
        grid_screen = {}
        grid_depth = {}
        grid_front = {}
        for i in range(N):
            for j in range(N):
                p3d = self._torus_point(i, j, N, R, r_minor)
                sx, sy, depth = self._project(p3d, rot, cx, cy)
                grid_screen[(i, j)] = (sx, sy)
                grid_depth[(i, j)] = depth
                n_rot = rot @ self._torus_normal(i, j, N)
                grid_front[(i, j)] = n_rot[2] < 0

        # Front-facing stones only
        stone_data = []
        last_move = self.game.current.move
        for i in range(N):
            for j in range(N):
                if board[i, j] == EMPTY:
                    continue
                if not grid_front[(i, j)]:
                    continue  # skip back-facing stones entirely
                sx, sy = grid_screen[(i, j)]
                stone_data.append((grid_depth[(i, j)], i, j,
                                   board[i, j], sx, sy))

        # Sort by depth (painter's: far first)
        front_lines.sort(key=lambda x: -x[0])
        stone_data.sort(key=lambda x: -x[0])

        # Draw grid lines
        for d, p1, p2, both_front in front_lines:
            if both_front:
                col = COL_TORUS_LINE
                width = 2
            else:
                # Edge segment (transitioning to back) — lighter
                col = COL_TORUS_LINE_B
                width = 1
            pygame.draw.line(self.screen, col,
                             (int(p1[0]), int(p1[1])),
                             (int(p2[0]), int(p2[1])), width)

        # Compute a UNIFORM stone radius from torus geometry.
        # Collect screen-distances between all adjacent front-facing pairs,
        # then use a low percentile so the inner-hole tightest spots don't
        # shrink everything to microscopic.
        adj_dists = []
        for i in range(N):
            for j in range(N):
                if not grid_front[(i, j)]:
                    continue
                sx0, sy0 = grid_screen[(i, j)]
                for ni, nj in [((i+1)%N, j), (i, (j+1)%N)]:
                    if not grid_front.get((ni, nj)):
                        continue
                    nsx, nsy = grid_screen[(ni, nj)]
                    d = math.hypot(nsx - sx0, nsy - sy0)
                    if d < 150 * self.torus_zoom:
                        adj_dists.append(d)
        if adj_dists:
            adj_dists.sort()
            # 15th percentile — generous but still safe
            idx = max(0, int(len(adj_dists) * 0.15))
            ref_dist = adj_dists[idx]
            stone_rad = max(4, int(ref_dist * 0.40))
        else:
            stone_rad = 6

        # Draw front-facing stones — uniform radius
        for d, i, j, stone, sx, sy in stone_data:
            rad = stone_rad
            if stone == BLACK:
                col = (25, 25, 30)
            else:
                col = (240, 240, 235)
            isx, isy = int(sx), int(sy)
            pygame.draw.circle(self.screen, col, (isx, isy), rad)
            pygame.draw.circle(self.screen, (30, 30, 30), (isx, isy), rad, 1)
            # 3-D highlight
            if rad > 5:
                hoff = max(1, rad // 4)
                hcol = (70, 70, 80) if stone == BLACK else (255, 255, 255)
                pygame.draw.circle(self.screen, hcol,
                                   (isx - hoff, isy - hoff),
                                   max(2, rad // 3))
            # Last-move marker
            if last_move and len(last_move) == 3:
                if last_move[1] == i and last_move[2] == j:
                    mcol = (220, 220, 220) if stone == BLACK else (30, 30, 30)
                    pygame.draw.circle(self.screen, mcol, (isx, isy),
                                       max(2, rad // 3), 2)

        # Small empty-intersection dots (front-facing only)
        for i in range(N):
            for j in range(N):
                if board[i, j] == EMPTY and grid_front[(i, j)]:
                    sx, sy = grid_screen[(i, j)]
                    pygame.draw.circle(self.screen, (100, 90, 60),
                                       (int(sx), int(sy)), 2)

        self._torus_grid_screen = grid_screen
        self._torus_grid_front = grid_front

    def _torus_screen_to_logical(self, mx, my):
        if not hasattr(self, "_torus_grid_screen"):
            return None
        best, best_dist = None, float("inf")
        for (i, j), (sx, sy) in self._torus_grid_screen.items():
            if not self._torus_grid_front.get((i, j)):
                continue
            dist = math.hypot(mx - sx, my - sy)
            if dist < best_dist:
                best_dist = dist
                best = (i, j)
        if best and best_dist < 50 * self.torus_zoom:
            return best
        return None

    # ── Score overlay ──
    def _draw_score_overlay(self):
        if not self.game or not self.game.score_result:
            return
        s = self.game.score_result
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.screen.blit(overlay, (0, 0))

        bw, bh_box = 440, 270
        bx = (BOARD_AREA_W - bw) // 2
        by = (BOARD_AREA_H - bh_box) // 2
        pygame.draw.rect(self.screen, COL_PANEL, (bx, by, bw, bh_box), border_radius=12)
        pygame.draw.rect(self.screen, COL_HIGHLIGHT, (bx, by, bw, bh_box), 2, border_radius=12)

        y = by + 18
        title_str = (f"Game Over \u2014 {s['winner']} wins!" if s["winner"] != "Tie"
                     else "Game Over \u2014 Tie!")
        title = self.font_lg.render(title_str, True, COL_HIGHLIGHT)
        self.screen.blit(title, title.get_rect(centerx=bx + bw // 2, y=y))
        y += 44

        lines = [
            f"\u25cf Black:  {s['black_stones']} stones + {s['black_territory']} territory = {s['black_total']:.1f}",
            f"\u25cb White:  {s['white_stones']} stones + {s['white_territory']} territory + {s['komi']} komi = {s['white_total']:.1f}",
            "",
            f"Margin: {abs(s['black_total'] - s['white_total']):.1f} points",
        ]
        for line in lines:
            t = self.font_score.render(line, True, COL_TEXT)
            self.screen.blit(t, (bx + 25, y))
            y += 28

        y += 14
        hint = self.font_sm.render("Press Undo to continue, or start New Game", True, COL_TEXT_DIM)
        self.screen.blit(hint, hint.get_rect(centerx=bx + bw // 2, y=y))

    # ── Side panel ──
    def _draw_panel(self):
        panel_x = BOARD_AREA_W
        pygame.draw.rect(self.screen, COL_PANEL, (panel_x, 0, PANEL_W, WINDOW_H))
        pygame.draw.line(self.screen, (40, 42, 50), (panel_x, 0), (panel_x, WINDOW_H), 2)

        y = 18
        title = self.font_lg.render("Toroidal Go", True, COL_HIGHLIGHT)
        self.screen.blit(title, (panel_x + 20, y)); y += 38

        if self.game is None:
            return

        turn_str = "\u25cf Black" if self.game.turn == BLACK else "\u25cb White"
        info = [
            f"Board: {self.game.size}\u00d7{self.game.size}  (torus)",
            f"Move: {self.game.move_count()}",
            f"Turn: {turn_str}",
            f"Captures  \u25cf: {self.game.current.captures[BLACK]}  \u25cb: {self.game.current.captures[WHITE]}",
            f"View: {'Rectangular' if self.view_mode == 'rect' else 'Torus 3-D'}",
        ]
        if self.game.game_over:
            info.append("** GAME OVER **")
        if self.game.variation_count() > 0:
            info.append(f"Variations: {self.game.variation_count()} (\u2191\u2193 idx={self.selected_variation})")

        for line in info:
            t = self.font_sm.render(line, True, COL_TEXT)
            self.screen.blit(t, (panel_x + 20, y)); y += 20
        y += 6

        ind_col = COL_BLACK_STONE if self.game.turn == BLACK else COL_WHITE_STONE
        pygame.draw.circle(self.screen, ind_col, (panel_x + PANEL_W - 30, 56), 12)
        pygame.draw.circle(self.screen, (100, 100, 100), (panel_x + PANEL_W - 30, 56), 12, 1)

        for btn in self.buttons:
            btn.draw(self.screen, self.font_sm, self.font_sm)

        if self.status_timer > 0:
            st = self.font_sm.render(self.status_msg, True, COL_VARIATION)
            self.screen.blit(st, (panel_x + 20, WINDOW_H - 28))

        y_hist = y + 8
        self.screen.blit(self.font_sm.render("Recent moves:", True, COL_TEXT_DIM), (panel_x + 20, y_hist))
        y_hist += 18
        node = self.game.current
        moves = []
        while node.parent and len(moves) < 12:
            m = node.move
            if m:
                c = "B" if m[0] == BLACK else "W"
                moves.append(f"{node.move_number}. {c}({m[1]},{m[2]})" if len(m) == 3 else f"{node.move_number}. {c} pass")
            node = node.parent
        moves.reverse()
        for mstr in moves:
            self.screen.blit(self.font_sm.render(mstr, True, COL_TEXT_DIM), (panel_x + 20, y_hist))
            y_hist += 16
            if y_hist > self.buttons[0].rect.top - 20:
                break

    # ── Events ──
    def _handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return

            if self.file_picker and self.file_picker.active:
                self.file_picker.handle_event(ev)
                if not self.file_picker.active:
                    if self.file_picker.result:
                        if self.file_picker.mode == "save":
                            self._finish_save(self.file_picker.result)
                        else:
                            self._finish_load(self.file_picker.result)
                    self.file_picker = None
                continue

            if self.selecting_size:
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self._handle_size_click(ev.pos)
                continue

            # Motion
            if ev.type == pygame.MOUSEMOTION:
                for btn in self.buttons:
                    btn.check_hover(ev.pos)

                if self.dragging_torus_surface and self.view_mode == "torus":
                    dx = ev.pos[0] - self.surf_drag_start[0]
                    dy = ev.pos[1] - self.surf_drag_start[1]
                    self.u_offset = self.surf_drag_u0 + dx * 0.008
                    self.v_offset = self.surf_drag_v0 - dy * 0.008

                if self.dragging_torus_rotate and self.view_mode == "torus":
                    dx = ev.pos[0] - self.rot_drag_start[0]
                    dy = ev.pos[1] - self.rot_drag_start[1]
                    self.view_spin = self.rot_drag_spin0 + dx * 0.005
                    self.view_tilt = max(-1.5, min(1.5, self.rot_drag_tilt0 + dy * 0.005))

                if self.rect_dragging and self.view_mode == "rect" and self.game:
                    N, cell, ox, oy = self._rect_params()
                    dx = ev.pos[0] - self.rect_drag_start[0]
                    dy = ev.pos[1] - self.rect_drag_start[1]
                    self.offset_r = (self.rect_drag_offset_r0 - int(round(dy / cell))) % N
                    self.offset_c = (self.rect_drag_offset_c0 - int(round(dx / cell))) % N

            # Button down
            if ev.type == pygame.MOUSEBUTTONDOWN:
                if ev.button == 1:
                    btn_hit = any(btn.check_click(ev.pos) for btn in self.buttons)
                    if btn_hit:
                        continue
                    if ev.pos[0] < BOARD_AREA_W and self.game:
                        if self.view_mode == "rect":
                            self.rect_dragging = True
                            self.rect_drag_start = ev.pos
                            self.rect_drag_offset_r0 = self.offset_r
                            self.rect_drag_offset_c0 = self.offset_c
                        elif self.view_mode == "torus":
                            self.dragging_torus_surface = True
                            self.surf_drag_start = ev.pos
                            self.surf_drag_u0 = self.u_offset
                            self.surf_drag_v0 = self.v_offset

                elif ev.button == 3:
                    if ev.pos[0] < BOARD_AREA_W and self.game:
                        if self.view_mode == "rect":
                            lrc = self._rect_screen_to_logical(*ev.pos)
                            if lrc:
                                N = self.game.size
                                self.offset_r = (lrc[0] - N // 2) % N
                                self.offset_c = (lrc[1] - N // 2) % N
                                self._set_status(f"Centred on ({lrc[0]}, {lrc[1]})")
                        elif self.view_mode == "torus":
                            self.dragging_torus_rotate = True
                            self.rot_drag_start = ev.pos
                            self.rot_drag_tilt0 = self.view_tilt
                            self.rot_drag_spin0 = self.view_spin

                elif ev.button == 4:
                    if self.view_mode == "torus":
                        self.torus_zoom = min(3.0, self.torus_zoom * 1.1)
                elif ev.button == 5:
                    if self.view_mode == "torus":
                        self.torus_zoom = max(0.3, self.torus_zoom / 1.1)

            # Button up
            if ev.type == pygame.MOUSEBUTTONUP:
                if ev.button == 1:
                    if self.dragging_torus_surface:
                        self.dragging_torus_surface = False
                    if self.rect_dragging:
                        dist = math.hypot(ev.pos[0] - self.rect_drag_start[0],
                                          ev.pos[1] - self.rect_drag_start[1])
                        if dist < 5 and self.game and self.view_mode == "rect":
                            lrc = self._rect_screen_to_logical(*ev.pos)
                            if lrc:
                                self.game.make_move(*lrc)
                                self.selected_variation = 0
                        self.rect_dragging = False
                if ev.button == 3:
                    self.dragging_torus_rotate = False

            # Keyboard
            if ev.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                ctrl = mods & pygame.KMOD_CTRL
                if ev.key == pygame.K_ESCAPE:
                    self.running = False
                elif ev.key == pygame.K_F11:
                    self._toggle_large_window()
                elif ctrl and ev.key == pygame.K_n: self._on_new()
                elif ctrl and ev.key == pygame.K_s: self._on_save()
                elif ctrl and ev.key == pygame.K_o: self._on_load()
                elif ctrl and ev.key == pygame.K_z: self._on_undo()
                elif ev.key in (pygame.K_u, pygame.K_LEFT): self._on_undo()
                elif ev.key in (pygame.K_r, pygame.K_RIGHT): self._on_redo()
                elif ev.key == pygame.K_p: self._on_pass()
                elif ev.key == pygame.K_v: self._on_toggle_view()
                elif ev.key == pygame.K_UP:
                    if self.game and self.game.variation_count() > 0:
                        self.selected_variation = max(0, self.selected_variation - 1)
                elif ev.key == pygame.K_DOWN:
                    if self.game:
                        self.selected_variation = min(self.game.variation_count() - 1, self.selected_variation + 1)
                elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    if self.view_mode == "torus": self.torus_zoom = min(3.0, self.torus_zoom * 1.15)
                elif ev.key == pygame.K_MINUS:
                    if self.view_mode == "torus": self.torus_zoom = max(0.3, self.torus_zoom / 1.15)

    def run(self):
        while self.running:
            self._handle_events()
            self.screen.fill(COL_BG)
            if self.selecting_size:
                self._draw_size_selection()
            else:
                if self.game:
                    if self.view_mode == "rect":
                        self._draw_rect_view()
                    else:
                        self._draw_torus_view()
                self._draw_panel()
                if self.game and self.game.game_over and self.game.score_result:
                    self._draw_score_overlay()

            if self.file_picker and self.file_picker.active:
                self.file_picker.draw(self.screen, self.font, self.font_sm)

            if self.status_timer > 0:
                self.status_timer -= 1

            pygame.display.flip()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == "__main__":
    app = ToroidalGoApp()
    app.run()
