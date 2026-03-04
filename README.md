# Toroidal Go

A complete implementation of **Go played on the surface of a torus**, built with Python and Pygame. The game features dual display modes — a flat rectangular board with toroidal wrapping and a 3-D torus visualization — along with full game-tree navigation, save/load support, and automatic scoring.

![Toroidal Go](https://img.shields.io/badge/python-3.10+-blue) ![Pygame](https://img.shields.io/badge/pygame-2.0+-green) ![NumPy](https://img.shields.io/badge/numpy-required-orange)

---

## What Is Toroidal Go?

Standard Go is played on a flat grid where edges and corners create asymmetry — corner and edge positions have fewer liberties than center positions. Toroidal Go eliminates this asymmetry entirely by playing on a torus (the surface of a doughnut). On a torus, every intersection is topologically identical: the board wraps around in both directions, so the top edge connects to the bottom and the left edge connects to the right. This creates a fundamentally different strategic landscape where there are no corners, no edges, and no concept of "the center."

The rules are otherwise identical to standard Go: players alternate placing black and white stones, groups are captured when they have no liberties, suicide is prohibited, and simple ko applies. The game ends when both players pass consecutively, and the winner is determined by Chinese-style area scoring (stones on board + surrounded territory) with 6.5 komi for White.

---

## Requirements

- **Python 3.10+** (uses `X | Y` type-union syntax)
- **Pygame** — for rendering and input handling
- **NumPy** — for board state arrays and 3-D matrix math

### Installation

```bash
pip install pygame numpy
```

No other dependencies are required. The application has no reliance on tkinter or any other GUI toolkit — all dialogs (including the file picker for save/load) are rendered natively within Pygame.

---

## Running the Game

```bash
python toroidal_go.py
```

On startup you will see a board-size selection screen. Choose any even or odd size from 5×5 to 19×19 and click **Start**.

---

## Display Modes

### Rectangular View (default)

The rectangular view presents the board as a traditional flat Go grid. Red strips along all four edges serve as a visual reminder that the board wraps — the top row is adjacent to the bottom row, and the left column is adjacent to the right column.

Coordinate labels along the top and left show logical row/column indices, which update as you translate the board.

**Interactions in rectangular view:**

- **Left-click** on an intersection to place a stone.
- **Left-drag** to translate the board in any direction. The board wraps toroidally, so you can drag continuously in any direction. A short click (less than 5 pixels of movement) is treated as a stone placement.
- **Right-click** on an intersection to snap-centre the board on that position. This is useful for quickly reframing the view around an area of interest.

### Torus 3-D View

Press **V** to switch to the torus view. This renders the current board position on a three-dimensional torus using orthographic projection. The visible (front-facing) surface of the torus is filled with the same wood-brown color as the rectangular board, displayed against a neutral gray background. Grid lines are drawn on the surface, and stones appear at their correct intersections.

The torus view is **display-only** — you cannot place stones on it. It serves as a visualization of the toroidal topology, letting you see at a glance how groups and territory wrap around the surface.

**Interactions in torus view:**

- **Left-drag** to slide the grid mesh along the torus surface (shifts the u/v parametric offsets).
- **Right-drag** to rotate the entire torus in 3-D (changes the camera tilt and spin angles). Tilt is clamped to ±1.5 radians to prevent disorienting flips.
- **Scroll wheel** or **+/-** keys to zoom in and out.

---

## Controls Reference

| Action | Key / Mouse |
|---|---|
| Place stone | Left-click (rectangular view) |
| Translate board | Left-drag (rectangular view) |
| Re-centre board | Right-click (rectangular view) |
| Slide torus mesh | Left-drag (torus view) |
| Rotate torus 3-D | Right-drag (torus view) |
| Zoom torus | Scroll wheel, or **+** / **-** |
| Undo | **U**, **←**, or **Ctrl+Z** |
| Redo (main line) | **R** or **→** |
| Select variation | **↑** / **↓** |
| Pass | **P** |
| Toggle view mode | **V** |
| New game | **Ctrl+N** |
| Save game | **Ctrl+S** |
| Load game | **Ctrl+O** |
| Toggle large window | **F11** |
| Quit | **Escape** |

All of these actions are also accessible via the button panel on the right side of the window.

---

## Game Rules

### Topology

Adjacency wraps in both dimensions using modulo arithmetic. For a board of size N, the neighbors of intersection (r, c) are:

- ((r−1) mod N, c)
- ((r+1) mod N, c)
- (r, (c−1) mod N)
- (r, (c+1) mod N)

Every intersection has exactly four neighbors — there are no edges or corners.

### Captures

When a stone is placed, any opponent groups adjacent to the new stone that have zero liberties are removed from the board. Liberties are counted using flood-fill across the toroidal adjacency.

### Suicide

A move is illegal if it would leave the player's own group with zero liberties *and* does not capture any opponent stones.

### Ko

Simple ko is enforced: a move is illegal if it would return the board to the exact state of the position before the opponent's last move (i.e., the grandparent node in the game tree).

### Scoring

When both players pass consecutively, the game ends and is scored automatically using **Chinese-style area scoring**:

- **Black's score** = black stones on board + empty territory surrounded exclusively by black
- **White's score** = white stones on board + empty territory surrounded exclusively by white + 6.5 komi

Territory is determined by flood-filling empty regions. A region counts as territory for a color only if *every* stone bordering that region is of that color. Regions bordered by both colors (or no stones) are neutral and count for neither player.

The score breakdown and winner are displayed in an overlay. Press **Undo** to continue playing, or **Ctrl+N** to start a new game.

---

## Game Tree and Variations

The game maintains a full tree of moves, not just a linear sequence. This means:

- **Undo/Redo** navigates the tree. Undo goes to the parent node; Redo follows the main line (first child) by default.
- **Branching**: if you undo several moves and then play a different move, a new branch (variation) is created. The original line is preserved.
- **Variation selection**: when the current node has multiple children, the **↑/↓** keys select which variation Redo will follow. The side panel shows the variation count and current index.
- **Variation markers**: in the rectangular view, small gold circles mark intersections where child-node moves exist, giving a visual hint of available branches.

---

## Save / Load

Games are saved as `.tgo` files — human-readable JSON containing the board size and the complete game tree (all variations).

### File Format

```json
{
  "format": "toroidal-go",
  "version": 1,
  "board_size": 9,
  "tree": {
    "children": [
      {
        "move": { "c": "B", "r": 4, "col": 4 },
        "children": [
          {
            "move": { "c": "W", "r": 3, "col": 3 },
            "children": []
          }
        ]
      }
    ]
  }
}
```

Each node stores:
- `move.c` — color (`"B"` or `"W"`)
- `move.r`, `move.col` — row and column (for stone placements)
- `move.pass` — `true` (for pass moves)
- `children` — array of child nodes (variations)

Board states and captures are reconstructed from the move sequence on load, so files remain compact regardless of board size.

### In-App File Picker

Save and Load use a built-in file browser rendered directly in the Pygame window. It supports:

- Directory navigation (click folders, `.. (up)` to go to parent)
- Scrolling through file lists
- Keyboard entry for save filenames (type a name and press Enter, or click Save)
- Cancel with Escape or the Cancel button

No external dependencies (tkinter, etc.) are required.

---

## Window Management

The default window size is 1280×820 pixels. The window layout consists of the board area on the left (980px wide) and a side panel on the right (300px wide).

- **F11** toggles between the default size and a large near-screen-size window (with margins for your taskbar). Press F11 again to return to the default size.
- The window does **not** use Pygame's `RESIZABLE` or `FULLSCREEN` flags, which can cause display conflicts with certain Linux window managers and compositors. All resizing is done by creating a new display surface at the desired dimensions.

---

## Architecture

The code is organized into several classes in a single file (~1400 lines):

### `GameNode`
A node in the game tree. Stores the move that produced it, a pointer to its parent, a list of children (variations), the board state (as a NumPy array), cumulative capture counts, and the move number. Uses `__slots__` for memory efficiency.

### `ToroidalGoGame`
Core game logic. Manages the game tree, turn tracking, move validation, capture detection (flood-fill), suicide prevention, ko detection, and scoring. All adjacency uses modulo-N wrapping.

### `FilePicker`
A self-contained in-app file browser with directory navigation, file filtering by extension, scroll support, and text input for save filenames. Renders as an overlay on the Pygame surface.

### `Button`
Simple clickable UI button with hover highlighting and keyboard-hint labels.

### `ToroidalGoApp`
The main application class. Handles:
- Pygame initialization and main loop
- Event dispatch (mouse, keyboard)
- Rectangular view rendering (grid, stones, star points, coordinate labels, variation markers, last-move indicator)
- Torus view rendering (filled surface quads, grid lines with front-face culling, orthographic projection, stones with uniform sizing)
- Side panel (game info, move history, buttons, status messages)
- Score overlay display
- Size selection screen

### Standalone Functions
- `save_game()` / `load_game()` — serialize/deserialize the game tree to JSON
- `_node_to_dict()` / `_dict_to_node()` — recursive tree conversion helpers
- `_rot_x()`, `_rot_y()`, `_rot_z()` — 3×3 rotation matrix constructors

---

## Torus Rendering Details

The 3-D torus is rendered using a parametric surface with major radius R=3.0 and minor radius r=1.2. The implementation uses:

- **Orthographic projection** — no perspective distortion, so stone sizes are consistent across the surface.
- **Front-face culling** — surface normals are checked against the camera direction. Back-facing grid segments, stones, and intersection dots are hidden entirely, giving the torus a solid appearance.
- **Filled surface quads** — the visible surface is covered with small filled polygons in the board wood color, drawn in depth order (painter's algorithm), before the grid lines are overlaid on top.
- **Uniform stone radius** — computed from the 15th percentile of all adjacent front-facing intersection distances, multiplied by 0.40. This prevents overlap everywhere while keeping stones reasonably sized.
- **Depth-sorted rendering** — grid lines, surface quads, and stones are all sorted by depth and drawn far-to-near.

---

## Known Limitations

- **No AI opponent** — the game is designed for two human players (or solo analysis/study).
- **Simple ko only** — superko (positional or situational) is not enforced. On a torus, superko situations may be more common than on a flat board.
- **No dead-stone removal** — scoring counts all stones on the board as alive. Players should agree on dead stones before both passing (as in real Go with Chinese rules).
- **No time controls** — there is no clock or time limit.
- **Single-file architecture** — the entire application is in one Python file for portability, but this could be refactored into modules for larger-scale development.

---

## License

This project is provided as-is for educational and recreational use.
