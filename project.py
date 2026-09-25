import math
import random
import sys
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *

# ==========================================================================
# WINDOW LAYOUT (pixel coordinates, origin = bottom-left)
# ==========================================================================
# কী করছে: Fixes the window size and the position of the map window (clip window) and the side panel.
# কেন লাগছে: Cohen-Sutherland and glScissor both need fixed pixel limits to cut against.
# real world-এ এটা কোথায় দেখা যায়: Every app has a fixed viewport region where the map is drawn.
WIN_W, WIN_H = 1100, 700
XMIN, YMIN, XMAX, YMAX = 20, 50, 800, 630          # the map window (clip window)
CX, CY = (XMIN + XMAX) / 2.0, (YMIN + YMAX) / 2.0   # centre of the map window
PANEL_X0, PANEL_X1 = 820, 1080                      # side panel card

# Cohen-Sutherland region codes (one bit per side)
INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8

# ==========================================================================
# COLOUR THEMES (day / night)
# ==========================================================================
# কী করছে: Stores two complete colour sets - one for day and one for night.
# কেন লাগছে: One key press (N) can then restyle the whole map without touching the drawing code.
# real world-এ এটা কোথায় দেখা যায়: Google Maps dark mode; game day-night cycles.
CHROME_BG = (0.07, 0.09, 0.14)
ACCENT = (1.00, 0.82, 0.30)
THEMES = {
    "day": {
        "map_bg": (0.96, 0.95, 0.91), "tint": (1.0, 1.0, 1.0),
        "road_casing": (0.72, 0.73, 0.78), "road_fill": (1.00, 1.00, 1.00),
        "road_center": (0.93, 0.80, 0.30),
        "hw_casing": (0.86, 0.45, 0.10), "hw_fill": (1.00, 0.78, 0.30),
        "bank": (0.45, 0.66, 0.86), "water": (0.66, 0.82, 0.98),
        "outline": (0.60, 0.60, 0.66),
    },
    "night": {
        "map_bg": (0.06, 0.08, 0.13), "tint": (0.36, 0.40, 0.60),
        "road_casing": (0.03, 0.04, 0.07), "road_fill": (0.20, 0.23, 0.31),
        "road_center": (0.65, 0.58, 0.25),
        "hw_casing": (0.30, 0.17, 0.05), "hw_fill": (0.85, 0.52, 0.18),
        "bank": (0.05, 0.11, 0.25), "water": (0.10, 0.24, 0.52),
        "outline": (0.28, 0.32, 0.44),
    },
}

# Paint palette: key -> (name, base colour)
PALETTE = {
    "1": ("Park",        (0.66, 0.86, 0.58)),
    "2": ("Commercial",  (0.99, 0.90, 0.62)),
    "3": ("Hospital",    (0.97, 0.72, 0.70)),
    "4": ("Lake / Water", (0.68, 0.83, 0.97)),
    "5": ("Residential", (0.90, 0.89, 0.86)),
}

# ==========================================================================
# PROGRAM STATE
# ==========================================================================
# কী করছে: Keeps the camera (view), its smooth-animation target, and the on/off switches.
# কেন লাগছে: The camera glides toward "target" every frame, which makes zoom/rotate feel smooth.
# real world-এ এটা কোথায় দেখা যায়: Camera controllers in games and Maps' animated zoom.
DEFAULT_VIEW = {"px": 500.0, "py": 400.0, "zoom": 0.68, "angle": 0.0}
view = dict(DEFAULT_VIEW)        # what is drawn right now
target = dict(DEFAULT_VIEW)      # where the camera is heading
state = {"clip": True, "ctrl": False, "night": False, "paused": False,
         "color": "1", "hover": None}
drag = {"on": False, "x": 0, "y": 0}
last_ms = [0]


def theme():
    # কী করছে: Returns the active colour set (day or night).
    # কেন লাগছে: Every drawing function asks this instead of hard-coding colours.
    # real world-এ এটা কোথায় দেখা যায়: UI theme managers (light / dark mode).
    return THEMES["night" if state["night"] else "day"]


def tint(rgb):
    # কী করছে: Multiplies a colour by the theme tint (dims and blues it at night).
    # কেন লাগছে: Lets park, buildings and so on darken automatically when night mode is on.
    # real world-এ এটা কোথায় দেখা যায়: Colour grading / lighting in games and dark-mode maps.
    t = theme()["tint"]
    return (min(1.0, rgb[0] * t[0]), min(1.0, rgb[1] * t[1]), min(1.0, rgb[2] * t[2]))


# ==========================================================================
# WORLD DATA - the "city" (1000 x 800 world units)
# ==========================================================================
def make_rect(x, y, w, h):
    # কী করছে: Returns the 4 corners of a rectangle whose lower-left corner is (x, y).
    # কেন লাগছে: Every block, building and cross is stored as a polygon (list of points).
    # real world-এ এটা কোথায় দেখা যায়: Building footprints in map data are polygons.
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def build_blocks():
    # কী করছে: Builds 16 city blocks (4 x 4 grid) and, for each, a fixed set of houses, towers, trees and waves.
    # কেন লাগছে: Each block is a clickable region for the paint bucket, and its decoration changes with its type.
    # real world-এ এটা কোথায় দেখা যায়: Land-use layers (park, residential, commercial) in GIS and Maps.
    xs = [0, 250, 500, 750, 1000]
    ys = [0, 200, 400, 600, 800]
    margin = 16
    start = ["1", "5", "2", "5", "5", "3", "5", "1",
             "2", "5", "4", "5", "5", "1", "5", "3"]
    rng = random.Random(7)                      # fixed seed -> same city every run
    blocks, k = [], 0
    for j in range(4):
        for i in range(4):
            x, y = xs[i] + margin, ys[j] + margin
            w, h = 250 - 2 * margin, 200 - 2 * margin
            b = {"pts": make_rect(x, y, w, h), "color": start[k], "flash": 0.0,
                 "name": "%s%d" % ("ABCD"[j], i + 1), "x": x, "y": y, "w": w, "h": h}
            # 3 x 3 small houses
            b["houses"] = []
            cw, ch = w / 3.0, h / 3.0
            for gy in range(3):
                for gx in range(3):
                    hw, hh = cw * rng.uniform(0.45, 0.65), ch * rng.uniform(0.45, 0.65)
                    b["houses"].append((x + gx * cw + (cw - hw) / 2.0,
                                        y + gy * ch + (ch - hh) / 2.0, hw, hh))
            # 2 x 2 bigger commercial towers
            b["towers"] = []
            cw, ch = w / 2.0, h / 2.0
            for gy in range(2):
                for gx in range(2):
                    tw, th_ = cw * rng.uniform(0.55, 0.70), ch * rng.uniform(0.55, 0.70)
                    b["towers"].append((x + gx * cw + (cw - tw) / 2.0,
                                        y + gy * ch + (ch - th_) / 2.0, tw, th_))
            # random trees for parks
            b["trees"] = [(x + rng.uniform(0.1, 0.9) * w, y + rng.uniform(0.1, 0.9) * h,
                           rng.uniform(9, 15)) for _ in range(10)]
            # three sine waves for water
            b["waves"] = [[(x + w * (0.1 + 0.8 * s / 12.0),
                            y + h * (0.25 + 0.25 * n) + 6 * math.sin(s * 1.1 + n))
                           for s in range(13)] for n in range(3)]
            blocks.append(b)
            k += 1
    return blocks, xs, ys


BLOCKS, GRID_X, GRID_Y = build_blocks()

# Grid roads: deliberately longer than the world, so clipping has something to cut.
GRID_ROADS = ([[(-200, y), (1200, y)] for y in GRID_Y] +
              [[(x, -200), (x, 1000)] for x in GRID_X])

# Cubic Bezier control points (P0, P1, P2, P3) in world coordinates
RIVER_CTRL = [(-100, 650), (300, 950), (650, -150), (1100, 350)]
ROAD_CTRL = [(-100, 100), (300, 500), (600, 300), (1100, 750)]


# ==========================================================================
# 2D TRANSFORMATIONS (written by hand - no glTranslate / glScale / glRotate)
# ==========================================================================
def world_to_screen(wx, wy, v=None):
    # কী করছে: Moves a world point relative to the camera centre (translate), rotates it, scales it (zoom),
    #          then places it at the centre of the map window.
    # কেন লাগছে: Every point of the city must go through this before OpenGL can draw it.
    # real world-এ এটা কোথায় দেখা যায়: Pinch-zoom, drag and compass rotation in Google Maps; game cameras.
    v = v or view
    c, s = math.cos(v["angle"]), math.sin(v["angle"])
    dx, dy = wx - v["px"], wy - v["py"]           # translate
    rx, ry = c * dx - s * dy, s * dx + c * dy     # rotate by +angle
    return CX + v["zoom"] * rx, CY + v["zoom"] * ry   # scale + move to window centre


def screen_to_world(sx, sy, v=None):
    # কী করছে: The exact reverse of world_to_screen - converts a mouse position back into world coordinates.
    # কেন লাগছে: To know which block was clicked we must compare the click with polygons in world space.
    # real world-এ এটা কোথায় দেখা যায়: Tapping a building in Maps; "picking" in games and CAD tools.
    v = v or view
    c, s = math.cos(v["angle"]), math.sin(v["angle"])
    dx, dy = (sx - CX) / v["zoom"], (sy - CY) / v["zoom"]     # undo scale
    return v["px"] + c * dx + s * dy, v["py"] - s * dx + c * dy  # undo rotation (rotate by -angle)


def pan_screen(dx, dy, v):
    # কী করছে: Moves the camera by (dx, dy) SCREEN pixels, correcting for the current rotation and zoom.
    # কেন লাগছে: Without the correction, arrow keys would move the map in the wrong direction once it is rotated.
    # real world-এ এটা কোথায় দেখা যায়: Dragging the map with a finger in Google Maps.
    c, s = math.cos(v["angle"]), math.sin(v["angle"])
    v["px"] += (c * dx + s * dy) / v["zoom"]
    v["py"] += (-s * dx + c * dy) / v["zoom"]


def zoom_at(sx, sy, factor):
    # কী করছে: Zooms the target camera but keeps the world point under the mouse cursor fixed on screen.
    # কেন লাগছে: Zooming to the cursor feels natural; zooming around the centre loses what you are looking at.
    # real world-এ এটা কোথায় দেখা যায়: Mouse-wheel zoom in Google Maps, Figma and Photoshop.
    new_zoom = max(0.15, min(5.0, target["zoom"] * factor))
    wx, wy = screen_to_world(sx, sy, target)
    target["zoom"] = new_zoom
    c, s = math.cos(target["angle"]), math.sin(target["angle"])
    dx, dy = (sx - CX) / new_zoom, (sy - CY) / new_zoom
    target["px"] = wx - (c * dx + s * dy)
    target["py"] = wy + s * dx - c * dy


# ==========================================================================
# LINE CLIPPING - Cohen-Sutherland (written by hand)
# ==========================================================================
def outcode(x, y):
    # কী করছে: Builds a 4-bit code telling on which side(s) of the map window a point lies.
    # কেন লাগছে: Lets us decide quickly whether a line is fully inside, fully outside, or partly inside.
    # real world-এ এটা কোথায় দেখা যায়: The clipping stage of the GPU rendering pipeline.
    code = INSIDE
    if x < XMIN:
        code |= LEFT
    elif x > XMAX:
        code |= RIGHT
    if y < YMIN:
        code |= BOTTOM
    elif y > YMAX:
        code |= TOP
    return code


def cohen_sutherland(x0, y0, x1, y1):
    # কী করছে: Cuts a line segment down to the part inside the map window (returns None if nothing is visible).
    # কেন লাগছে: Roads that run outside the map window must not be drawn there.
    # real world-এ এটা কোথায় দেখা যায়: Viewport clipping in GPUs; Maps skipping off-screen roads.
    c0, c1 = outcode(x0, y0), outcode(x1, y1)
    while True:
        if not (c0 | c1):            # both ends inside -> accept the whole line
            return x0, y0, x1, y1
        if c0 & c1:                  # both ends outside on the same side -> reject
            return None
        out = c0 if c0 else c1       # pick an end that is outside
        if out & TOP:
            x, y = x0 + (x1 - x0) * (YMAX - y0) / (y1 - y0), YMAX
        elif out & BOTTOM:
            x, y = x0 + (x1 - x0) * (YMIN - y0) / (y1 - y0), YMIN
        elif out & RIGHT:
            x, y = XMAX, y0 + (y1 - y0) * (XMAX - x0) / (x1 - x0)
        else:                        # LEFT
            x, y = XMIN, y0 + (y1 - y0) * (XMIN - x0) / (x1 - x0)
        if out == c0:                # move that end onto the window edge and test again
            x0, y0 = x, y
            c0 = outcode(x0, y0)
        else:
            x1, y1 = x, y
            c1 = outcode(x1, y1)


# ==========================================================================
# BEZIER CURVES
# ==========================================================================
def bezier_point(t, p0, p1, p2, p3):
    # কী করছে: Evaluates B(t) = (1-t)^3 P0 + 3(1-t)^2 t P1 + 3(1-t) t^2 P2 + t^3 P3 for t between 0 and 1.
    # কেন লাগছে: A river and a curved highway cannot be drawn with straight lines; 4 control points give a smooth curve.
    # real world-এ এটা কোথায় দেখা যায়: Font outlines (TrueType/SVG), car body modelling, Illustrator's pen tool.
    u = 1.0 - t
    b0, b1, b2, b3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0],
            b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1])


def sample_bezier(ctrl, n=40):
    # কী করছে: Splits the curve into n short straight pieces and returns their points.
    # কেন লাগছে: We draw the curve as many tiny lines; more pieces = smoother curve.
    # real world-এ এটা কোথায় দেখা যায়: Font renderers "flatten" curves into small segments before drawing.
    return [bezier_point(i / float(n), *ctrl) for i in range(n + 1)]


RIVER_PTS = sample_bezier(RIVER_CTRL)     # sampled once - the curve never changes
ROAD_PTS = sample_bezier(ROAD_CTRL)


# ==========================================================================
# ANIMATED TRAFFIC (cars on roads, boats on the river)
# ==========================================================================
def make_traffic():
    # কী করছে: Creates cars on every grid road (both directions), on the Bezier highway, and boats on the river.
    # কেন লাগছে: Movement makes the map feel alive and shows the transforms and Bezier curve working live.
    # real world-এ এটা কোথায় দেখা যায়: Live-traffic layers in Maps; vehicle animation in games.
    rng = random.Random(3)
    colors = [(0.90, 0.25, 0.25), (0.20, 0.50, 0.90), (0.95, 0.75, 0.20),
              (0.25, 0.70, 0.40), (0.60, 0.30, 0.80), (0.95, 0.95, 0.95)]
    fleet = []
    for y in GRID_Y:
        for d in (1, -1):
            fleet.append({"kind": "h", "c": y, "dir": d, "pos": rng.uniform(-200, 1200),
                          "speed": rng.uniform(90, 160), "color": rng.choice(colors), "len": 16, "wid": 8})
    for x in GRID_X:
        for d in (1, -1):
            fleet.append({"kind": "v", "c": x, "dir": d, "pos": rng.uniform(-200, 1000),
                          "speed": rng.uniform(90, 160), "color": rng.choice(colors), "len": 16, "wid": 8})
    for _ in range(4):
        fleet.append({"kind": "bez", "ctrl": ROAD_CTRL, "t": rng.random(),
                      "speed": rng.uniform(0.07, 0.12), "color": rng.choice(colors), "len": 16, "wid": 8})
    for _ in range(2):
        fleet.append({"kind": "bez", "ctrl": RIVER_CTRL, "t": rng.random(),
                      "speed": rng.uniform(0.03, 0.05), "color": (1.0, 1.0, 1.0), "len": 26, "wid": 11})
    return fleet


TRAFFIC = make_traffic()


def update_traffic(dt):
    # কী করছে: Moves every vehicle forward by (speed x elapsed time) and wraps it around at the road end.
    # কেন লাগছে: Using real elapsed time keeps the speed the same on fast and slow computers.
    # real world-এ এটা কোথায় দেখা যায়: Delta-time movement in every game loop.
    for c in TRAFFIC:
        if c["kind"] == "bez":
            c["t"] = (c["t"] + c["speed"] * dt) % 1.0
        else:
            lo, hi = (-200, 1200) if c["kind"] == "h" else (-200, 1000)
            c["pos"] += c["dir"] * c["speed"] * dt
            if c["pos"] > hi:
                c["pos"] = lo
            elif c["pos"] < lo:
                c["pos"] = hi


def vehicle_pose(c):
    # কী করছে: Returns a vehicle's world position and its heading (unit direction vector).
    # কেন লাগছে: The car body must point along the road, including along the curved Bezier road.
    # real world-এ এটা কোথায় দেখা যায়: Path-following in games (cars on splines).
    if c["kind"] == "h":
        return (c["pos"], c["c"] - 7 * c["dir"]), (float(c["dir"]), 0.0)
    if c["kind"] == "v":
        return (c["c"] + 7 * c["dir"], c["pos"]), (0.0, float(c["dir"]))
    p = bezier_point(c["t"], *c["ctrl"])
    a = bezier_point(max(c["t"] - 0.005, 0.0), *c["ctrl"])
    b = bezier_point(min(c["t"] + 0.005, 1.0), *c["ctrl"])
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return p, (dx / n, dy / n)


# ==========================================================================
# DRAWING PRIMITIVES
# ==========================================================================
def set_color(color, alpha=1.0):
    # কী করছে: Sets the current OpenGL colour from an (r, g, b) tuple plus an alpha.
    # কেন লাগছে: One helper avoids repeating glColor4f everywhere.
    # real world-এ এটা কোথায় দেখা যায়: Every renderer has a "set brush colour" call.
    glColor4f(color[0], color[1], color[2], alpha)


def scaled(base, lo=1.0, hi=14.0):
    # কী করছে: Scales a line width with the zoom level but keeps it between lo and hi pixels.
    # কেন লাগছে: Roads should get slightly thicker when we zoom in, but never absurdly thick.
    # real world-এ এটা কোথায় দেখা যায়: Google Maps thickens roads as you zoom in.
    return max(lo, min(hi, base * view["zoom"] / 0.68))


def draw_line(a, b):
    # কী করছে: Draws one screen-space line; if clipping is ON it is first cut by Cohen-Sutherland.
    # কেন লাগছে: Pressing C switches clipping off so we can SEE what clipping does (great for the demo).
    # real world-এ এটা কোথায় দেখা যায়: The line primitive plus clipping stage of a 2D renderer.
    if state["clip"]:
        res = cohen_sutherland(a[0], a[1], b[0], b[1])
        if res is None:
            return
        a, b = (res[0], res[1]), (res[2], res[3])
    glBegin(GL_LINES)
    glVertex2f(a[0], a[1])
    glVertex2f(b[0], b[1])
    glEnd()


def draw_polyline(world_pts, color, width, dashed=False, joints=False, alpha=1.0):
    # কী করছে: Converts world points to screen and draws them as connected (clipped) lines; can be dashed or joined with round dots.
    # কেন লাগছে: Roads, rivers and waves are all point sequences, so one function draws them all.
    # real world-এ এটা কোথায় দেখা যায়: Vector polylines for roads and rivers in map data.
    set_color(color, alpha)
    glLineWidth(width)
    pts = [world_to_screen(x, y) for (x, y) in world_pts]
    if dashed:
        glEnable(GL_LINE_STIPPLE)
        glLineStipple(3, 0x00FF)
    for i in range(len(pts) - 1):
        draw_line(pts[i], pts[i + 1])
    if dashed:
        glDisable(GL_LINE_STIPPLE)
    if joints and width >= 4:                   # round dots hide the gaps between thick segments
        glPointSize(width)
        glBegin(GL_POINTS)
        for (sx, sy) in pts:
            if (not state["clip"]) or (XMIN <= sx <= XMAX and YMIN <= sy <= YMAX):
                glVertex2f(sx, sy)
        glEnd()


def fill_poly(pts, color, alpha=1.0):
    # কী করছে: Fills a convex polygon given in screen coordinates.
    # কেন লাগছে: Buildings, blocks, cars and panels are all filled shapes.
    # real world-এ এটা কোথায় দেখা যায়: Filled polygons in Maps, Photoshop's fill, GPU triangle filling.
    set_color(color, alpha)
    glBegin(GL_POLYGON)
    for (x, y) in pts:
        glVertex2f(x, y)
    glEnd()


def fill_rect_world(x, y, w, h, color, alpha=1.0):
    # কী করছে: Transforms a world rectangle to the screen (so it pans/zooms/rotates) and fills it.
    # কেন লাগছে: Houses, towers and hospital parts are rectangles that must follow the camera.
    # real world-এ এটা কোথায় দেখা যায়: Building footprints drawn on a map.
    fill_poly([world_to_screen(px, py) for (px, py) in make_rect(x, y, w, h)], color, alpha)


def fill_circle(cx, cy, r, color, alpha=1.0, seg=20):
    # কী করছে: Fills a circle (screen coordinates) by drawing a fan of triangles.
    # কেন লাগছে: Trees, headlight glow and the compass are circles.
    # real world-এ এটা কোথায় দেখা যায়: Circle markers and tree symbols in maps and games.
    set_color(color, alpha)
    glBegin(GL_TRIANGLE_FAN)
    glVertex2f(cx, cy)
    for i in range(seg + 1):
        a = 2.0 * math.pi * i / seg
        glVertex2f(cx + r * math.cos(a), cy + r * math.sin(a))
    glEnd()


def fill_circle_world(cx, cy, r, color, alpha=1.0):
    # কী করছে: Transforms a world circle (centre and radius) to the screen and fills it.
    # কেন লাগছে: The radius must scale with zoom so trees stay the right size relative to blocks.
    # real world-এ এটা কোথায় দেখা যায়: Tree and marker symbols scaling with the map.
    sx, sy = world_to_screen(cx, cy)
    fill_circle(sx, sy, r * view["zoom"], color, alpha)


def text(x, y, s, color=(1, 1, 1), font=None):
    # কী করছে: Writes a string at screen position (x, y).
    # কেন লাগছে: Needed for the title, controls, status and hover information.
    # real world-এ এটা কোথায় দেখা যায়: HUD text in games; labels in Maps.
    set_color(color)
    glRasterPos2f(x, y)
    for ch in s:
        glutBitmapCharacter(font or GLUT_BITMAP_HELVETICA_12, ord(ch))


def scissor_on():
    # কী করছে: Turns on the GPU scissor test limited to the map window.
    # কেন লাগছে: Filled shapes (blocks, buildings, cars) are cut by the GPU so they never leave the map window.
    # real world-এ এটা কোথায় দেখা যায়: Scroll views and canvas viewports use scissor/clip rectangles.
    glEnable(GL_SCISSOR_TEST)
    glScissor(int(XMIN), int(YMIN), int(XMAX - XMIN), int(YMAX - YMIN))


def scissor_off():
    # কী করছে: Turns the scissor test off again.
    # কেন লাগছে: The compass, frame and side panel are drawn outside the clipped area.
    # real world-এ এটা কোথায় দেখা যায়: Restoring render state after a clipped layer.
    glDisable(GL_SCISSOR_TEST)


# ==========================================================================
# MAP LAYERS
# ==========================================================================
def block_color(b):
    # কী করছে: Returns the block's fill colour for the current theme.
    # কেন লাগছে: A painted block keeps its type; the theme only changes how bright it looks.
    # real world-এ এটা কোথায় দেখা যায়: Land-use colours in day/night map styles.
    return tint(PALETTE[b["color"]][1])


def draw_block_decor(b):
    # কী করছে: Draws what belongs on a block: trees (park), houses (residential), towers (commercial),
    #          a red cross (hospital) or waves (water). Changes automatically when the block is repainted.
    # কেন লাগছে: Makes the city look real instead of flat coloured squares.
    # real world-এ এটা কোথায় দেখা যায়: Detailed 2D city maps and isometric city-builder games.
    kind, night = b["color"], state["night"]
    if kind == "1":                                                # park
        for (tx, ty, r) in b["trees"]:
            fill_circle_world(tx + 3, ty - 3, r, (0, 0, 0), 0.15)
            fill_circle_world(tx, ty, r, tint((0.25, 0.58, 0.30)))
            fill_circle_world(tx - r * 0.3, ty + r * 0.3, r * 0.45, tint((0.42, 0.74, 0.44)))
    elif kind == "5":                                              # residential
        for (hx, hy, hw, hh) in b["houses"]:
            fill_rect_world(hx + 4, hy - 4, hw, hh, (0, 0, 0), 0.15)
            fill_rect_world(hx, hy, hw, hh, tint((0.88, 0.62, 0.52)))
            fill_rect_world(hx + hw * 0.15, hy + hh * 0.15, hw * 0.7, hh * 0.7, tint((0.76, 0.46, 0.38)))
            if night:
                fill_rect_world(hx + hw * 0.38, hy + hh * 0.38, hw * 0.24, hh * 0.24, (1.0, 0.90, 0.40))
    elif kind == "2":                                              # commercial
        for (tx, ty, tw, th_) in b["towers"]:
            fill_rect_world(tx + 6, ty - 6, tw, th_, (0, 0, 0), 0.18)
            fill_rect_world(tx, ty, tw, th_, tint((0.80, 0.62, 0.28)))
            fill_rect_world(tx + tw * 0.12, ty + th_ * 0.12, tw * 0.76, th_ * 0.76, tint((0.96, 0.82, 0.46)))
            if night:
                for gx in range(3):
                    for gy in range(2):
                        fill_rect_world(tx + tw * (0.2 + 0.22 * gx), ty + th_ * (0.25 + 0.3 * gy),
                                        tw * 0.12, th_ * 0.14, (1.0, 0.90, 0.40))
    elif kind == "3":                                              # hospital
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        fill_rect_world(x + w * 0.2 + 6, y + h * 0.2 - 6, w * 0.6, h * 0.6, (0, 0, 0), 0.18)
        fill_rect_world(x + w * 0.2, y + h * 0.2, w * 0.6, h * 0.6, tint((0.98, 0.98, 0.98)))
        cx, cy, arm = x + w / 2.0, y + h / 2.0, min(w, h) * 0.17
        thick = arm * 0.6
        fill_rect_world(cx - arm, cy - thick / 2.0, 2 * arm, thick, tint((0.85, 0.15, 0.15)))
        fill_rect_world(cx - thick / 2.0, cy - arm, thick, 2 * arm, tint((0.85, 0.15, 0.15)))
    elif kind == "4":                                              # water
        for wave in b["waves"]:
            draw_polyline(wave, tint((1.0, 1.0, 1.0)), scaled(2.0, 1.0, 3.0), alpha=0.8)


def draw_block_outline(b, color, width):
    # কী করছে: Draws the 4 edges of a block with clipped lines.
    # কেন লাগছে: Gives each block a clear border; a brighter, thicker one marks the block under the mouse.
    # real world-এ এটা কোথায় দেখা যায়: Selected-feature highlight in GIS and design tools.
    pts = [world_to_screen(x, y) for (x, y) in b["pts"]]
    set_color(color)
    glLineWidth(width)
    for i in range(len(pts)):
        draw_line(pts[i], pts[(i + 1) % len(pts)])


def draw_roads():
    # কী করছে: Draws all grid roads in 3 passes - dark casing, light fill, dashed centre line.
    # কেন লাগছে: Drawing all casings first makes junctions merge cleanly, like real map roads.
    # real world-এ এটা কোথায় দেখা যায়: Road styling ("casing") in Google Maps and OpenStreetMap.
    th = theme()
    for r in GRID_ROADS:
        draw_polyline(r, th["road_casing"], scaled(10))
    for r in GRID_ROADS:
        draw_polyline(r, th["road_fill"], scaled(7))
    for r in GRID_ROADS:
        draw_polyline(r, th["road_center"], 1.2, dashed=True)


def draw_vehicle(c):
    # কী করছে: Draws a car or boat as a rotated rectangle (body + roof) pointing along its heading.
    # কেন লাগছে: Shows the transform pipeline working on moving objects, and adds headlights at night.
    # real world-এ এটা কোথায় দেখা যায়: Vehicle sprites/meshes in driving maps and games.
    (px, py), (dx, dy) = vehicle_pose(c)
    nx, ny = -dy, dx
    half_l, half_w = c["len"] / 2.0, c["wid"] / 2.0

    def corner(sl, sw):
        return world_to_screen(px + dx * half_l * sl + nx * half_w * sw,
                               py + dy * half_l * sl + ny * half_w * sw)

    fill_poly([corner(1, 1), corner(1, -1), corner(-1, -1), corner(-1, 1)], c["color"])
    fill_poly([corner(0.5, 0.65), corner(0.5, -0.65), corner(-0.4, -0.65), corner(-0.4, 0.65)],
              (c["color"][0] * 0.65, c["color"][1] * 0.65, c["color"][2] * 0.65))
    if state["night"] and c["len"] < 20:          # headlights for cars (boats are longer)
        fill_circle_world(px + dx * half_l * 1.5, py + dy * half_l * 1.5, 10, (1.0, 0.90, 0.45), 0.40)


def draw_bezier_points():
    # কী করছে: Shows the Bezier control polygon and labelled control points (P0..P3) when P is pressed.
    # কেন লাগছে: Helps everyone see HOW the 4 points shape the curve; ideal for the viva.
    # real world-এ এটা কোথায় দেখা যায়: The handles you drag in Illustrator, Figma or Inkscape.
    for ctrl, col in ((RIVER_CTRL, (0.90, 0.20, 0.20)), (ROAD_CTRL, (0.10, 0.60, 0.20))):
        draw_polyline(ctrl, col, 1.5, dashed=True)
        glPointSize(9.0)
        for n, (x, y) in enumerate(ctrl):
            sx, sy = world_to_screen(x, y)
            if XMIN + 5 <= sx <= XMAX - 5 and YMIN + 5 <= sy <= YMAX - 5:
                set_color(col)
                glBegin(GL_POINTS)
                glVertex2f(sx, sy)
                glEnd()
                text(sx + 8, sy + 6, "P%d" % n, col)


def draw_compass():
    # কী করছে: Draws a compass whose red needle always points to world "north" and turns as the map rotates.
    # কেন লাগছে: Tells the user how far the map is rotated - it uses the same rotation maths as the map.
    # real world-এ এটা কোথায় দেখা যায়: The compass button in Google Maps and other navigation apps.
    cx, cy, r = XMIN + 50, YMAX - 50, 30
    fill_circle(cx, cy, r, (1, 1, 1), 0.85)
    set_color((0.25, 0.25, 0.30))
    glLineWidth(2.0)
    glBegin(GL_LINE_LOOP)
    for i in range(32):
        a = 2.0 * math.pi * i / 32
        glVertex2f(cx + r * math.cos(a), cy + r * math.sin(a))
    glEnd()
    a = view["angle"]
    nx, ny = -math.sin(a), math.cos(a)            # world-north as seen on screen
    px, py = -ny, nx
    tip = (cx + nx * r * 0.8, cy + ny * r * 0.8)
    tail = (cx - nx * r * 0.8, cy - ny * r * 0.8)
    left = (cx + px * r * 0.22, cy + py * r * 0.22)
    right = (cx - px * r * 0.22, cy - py * r * 0.22)
    fill_poly([tip, left, right], (0.88, 0.15, 0.15))
    fill_poly([tail, left, right], (0.55, 0.55, 0.60))
    text(cx + nx * (r + 9) - 4, cy + ny * (r + 9) - 4, "N", ACCENT)


# ==========================================================================
# WINDOW CHROME - title bar, side panel, status bar
# ==========================================================================
def draw_chrome_background():
    # কী করছে: Draws the gradient title bar, the bottom status bar and the side-panel card.
    # কেন লাগছে: Gives the program a polished, application-like look.
    # real world-এ এটা কোথায় দেখা যায়: Toolbars, sidebars and status bars of every desktop/mobile app.
    glBegin(GL_QUADS)                              # title bar with left-to-right gradient
    glColor3f(0.08, 0.20, 0.42)
    glVertex2f(0, WIN_H - 50)
    glColor3f(0.30, 0.14, 0.45)
    glVertex2f(WIN_W, WIN_H - 50)
    glVertex2f(WIN_W, WIN_H)
    glColor3f(0.08, 0.20, 0.42)
    glVertex2f(0, WIN_H)
    glEnd()
    fill_poly([(0, 0), (WIN_W, 0), (WIN_W, 30), (0, 30)], (0.04, 0.05, 0.09))       # bottom bar
    fill_poly([(PANEL_X0, YMIN), (PANEL_X1, YMIN), (PANEL_X1, YMAX), (PANEL_X0, YMAX)],
              (0.13, 0.16, 0.24))                                                    # panel card
    set_color((0.30, 0.35, 0.50))
    glLineWidth(1.5)
    glBegin(GL_LINE_LOOP)
    glVertex2f(PANEL_X0, YMIN)
    glVertex2f(PANEL_X1, YMIN)
    glVertex2f(PANEL_X1, YMAX)
    glVertex2f(PANEL_X0, YMAX)
    glEnd()


def draw_chrome_text():
    # কী করছে: Writes the title, the key guide, the paint palette, live status values and the hover info.
    # কেন লাগছে: The user (and the teacher) can see what every key does and what state the program is in.
    # real world-এ এটা কোথায় দেখা যায়: Sidebars and HUDs in Maps, games and editors.
    text(24, WIN_H - 32, "MINI CITY MAP VIEWER", (1, 1, 1), GLUT_BITMAP_HELVETICA_18)
    text(WIN_W - 400, WIN_H - 30, "Computer Graphics Sessional   |   Python + PyOpenGL", (0.85, 0.88, 1.0))

    x = PANEL_X0 + 16
    y = YMAX - 30
    text(x, y, "CONTROLS", ACCENT, GLUT_BITMAP_HELVETICA_18)
    keys = [("Arrows / RMB", "Pan"), ("Wheel / + -", "Zoom"), ("Q / E", "Rotate"),
            ("Left click", "Paint block"), ("1 - 5", "Pick colour"), ("C", "Clipping on/off"),
            ("P", "Bezier points"), ("N", "Day / Night"), ("Space", "Pause traffic"),
            ("R", "Reset view"), ("Esc", "Quit")]
    for k, d in keys:
        y -= 20
        text(x, y, k, ACCENT)
        text(x + 100, y, d)

    y -= 36
    text(x, y, "PAINT COLOUR", ACCENT, GLUT_BITMAP_HELVETICA_18)
    for key in sorted(PALETTE):
        y -= 24
        name, col = PALETTE[key]
        fill_poly([(x, y - 3), (x + 16, y - 3), (x + 16, y + 11), (x, y + 11)], col)
        if key == state["color"]:                       # highlight the chosen colour
            set_color(ACCENT)
            glLineWidth(2.0)
            glBegin(GL_LINE_LOOP)
            glVertex2f(x - 3, y - 6)
            glVertex2f(x + 19, y - 6)
            glVertex2f(x + 19, y + 14)
            glVertex2f(x - 3, y + 14)
            glEnd()
        text(x + 30, y, "%s  %s" % (key, name))

    y -= 38
    text(x, y, "STATUS", ACCENT, GLUT_BITMAP_HELVETICA_18)
    rows = [("Clipping", "ON" if state["clip"] else "OFF", (0.5, 1.0, 0.6) if state["clip"] else (1.0, 0.45, 0.45)),
            ("Theme", "Night" if state["night"] else "Day", (1, 1, 1)),
            ("Traffic", "Paused" if state["paused"] else "Running", (1, 1, 1)),
            ("Zoom", "%.2f" % target["zoom"], (1, 1, 1)),
            ("Angle", "%d deg" % (int(round(math.degrees(target["angle"]))) % 360), (1, 1, 1))]
    for label, value, col in rows:
        y -= 20
        text(x, y, label, (0.7, 0.75, 0.9))
        text(x + 100, y, value, col)

    hb = state["hover"]
    if hb:
        info = "Block %s  -  %s   (click to paint it %s)" % (hb["name"], PALETTE[hb["color"]][0],
                                                              PALETTE[state["color"]][0])
    else:
        info = "Move the mouse over a block"
    text(24, 10, info, (0.85, 0.88, 1.0))
    if not state["clip"]:
        text(WIN_W - 470, 10, "CLIPPING OFF - roads leak outside the map window (press C)", (1.0, 0.45, 0.45))


# ==========================================================================
# GLUT CALLBACKS
# ==========================================================================
def display():
    # কী করছে: Draws one complete frame in layers: chrome, block fills + decor, outlines, river, roads, traffic, overlays.
    # কেন লাগছে: GLUT calls this again and again; drawing back-to-front (painter's algorithm) gives correct overlap.
    # real world-এ এটা কোথায় দেখা যায়: The render loop of every game and map renderer.
    th = theme()
    glClearColor(CHROME_BG[0], CHROME_BG[1], CHROME_BG[2], 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    draw_chrome_background()

    # Layer 0 - map background
    fill_poly([(XMIN, YMIN), (XMAX, YMIN), (XMAX, YMAX), (XMIN, YMAX)], th["map_bg"])

    # Layer 1 - COLOR FILL + decoration (GPU scissor keeps them inside the map window)
    scissor_on()
    for b in BLOCKS:
        fill_poly([world_to_screen(x, y) for (x, y) in b["pts"]], block_color(b))
        draw_block_decor(b)
    scissor_off()

    # Layer 2 - block outlines (our own clipped lines)
    for b in BLOCKS:
        draw_block_outline(b, th["outline"], 1.0)

    # Layer 3 - BEZIER river: dark bank first, lighter water on top
    draw_polyline(RIVER_PTS, th["bank"], scaled(15), joints=True)
    draw_polyline(RIVER_PTS, th["water"], scaled(11), joints=True)

    # Layer 4 - grid roads, then the BEZIER highway on top like an overpass
    draw_roads()
    draw_polyline(ROAD_PTS, th["hw_casing"], scaled(10), joints=True)
    draw_polyline(ROAD_PTS, th["hw_fill"], scaled(7), joints=True)

    # Layer 5 - animated traffic and the flash effect of a freshly painted block
    scissor_on()
    for c in TRAFFIC:
        draw_vehicle(c)
    for b in BLOCKS:
        if b["flash"] > 0.0:
            fill_poly([world_to_screen(x, y) for (x, y) in b["pts"]], (1, 1, 1), b["flash"] * 0.7)
    scissor_off()

    # Layer 6 - overlays: hover outline, Bezier control points, compass, frame
    if state["hover"]:
        draw_block_outline(state["hover"], ACCENT, 3.0)
    if state["ctrl"]:
        draw_bezier_points()
    draw_compass()
    set_color((0.35, 0.40, 0.55))
    glLineWidth(2.0)
    glBegin(GL_LINE_LOOP)
    glVertex2f(XMIN, YMIN)
    glVertex2f(XMAX, YMIN)
    glVertex2f(XMAX, YMAX)
    glVertex2f(XMIN, YMAX)
    glEnd()

    draw_chrome_text()
    glutSwapBuffers()


def tick(_value):
    # কী করছে: Runs ~60 times a second: eases the camera toward its target, moves traffic, fades paint flashes.
    # কেন লাগছে: Animation needs a timer; easing makes zoom and rotation glide instead of jumping.
    # real world-এ এটা কোথায় দেখা যায়: Smooth camera transitions in Maps; the update step of a game loop.
    now = glutGet(GLUT_ELAPSED_TIME)
    dt = min((now - last_ms[0]) / 1000.0, 0.05)
    last_ms[0] = now
    k = 1.0 - math.exp(-12.0 * dt)
    for key in view:
        view[key] += (target[key] - view[key]) * k
    if not state["paused"]:
        update_traffic(dt)
    for b in BLOCKS:
        b["flash"] = max(0.0, b["flash"] - dt * 2.2)
    glutPostRedisplay()
    glutTimerFunc(16, tick, 0)


def point_in_polygon(px, py, pts):
    # কী করছে: Ray-casting test - is the point (px, py) inside the polygon?
    # কেন লাগছে: Finds which block the mouse is over (for hover and paint bucket).
    # real world-এ এটা কোথায় দেখা যায়: Tapping a building in Maps; hit-testing in games and UI toolkits.
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > py) != (yj > py):
            if px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def pick_block(sx, sy):
    # কী করছে: Returns the block under a screen position (or None).
    # কেন লাগছে: Shared by the hover highlight and the paint bucket.
    # real world-এ এটা কোথায় দেখা যায়: Object picking in editors and maps.
    if not (XMIN <= sx <= XMAX and YMIN <= sy <= YMAX):
        return None
    wx, wy = screen_to_world(sx, sy)
    for b in BLOCKS:
        if point_in_polygon(wx, wy, b["pts"]):
            return b
    return None


def mouse(button, st, x, y):
    # কী করছে: Left click paints a block; right button starts/stops map dragging; wheel zooms to the cursor.
    # কেন লাগছে: Mouse interaction: paint bucket, panning and zooming.
    # real world-এ এটা কোথায় দেখা যায়: Paint bucket in Photoshop; drag and wheel in Google Maps.
    sx, sy = x, WIN_H - y                    # GLUT's y grows downward, OpenGL's y grows upward
    if button == GLUT_LEFT_BUTTON and st == GLUT_DOWN:
        b = pick_block(sx, sy)
        if b:
            b["color"] = state["color"]
            b["flash"] = 1.0
    elif button == GLUT_RIGHT_BUTTON:
        drag["on"] = (st == GLUT_DOWN)
        drag["x"], drag["y"] = sx, sy
    elif button in (3, 4) and st == GLUT_DOWN:
        if XMIN <= sx <= XMAX and YMIN <= sy <= YMAX:
            zoom_at(sx, sy, 1.12 if button == 3 else 1.0 / 1.12)


def motion(x, y):
    # কী করছে: Tracks the mouse: updates the hovered block, and pans the map while the right button is held.
    # কেন লাগছে: Gives live feedback (highlight) and click-and-drag panning.
    # real world-এ এটা কোথায় দেখা যায়: Hover highlights and drag-to-pan in map apps.
    sx, sy = x, WIN_H - y
    state["hover"] = pick_block(sx, sy)
    if drag["on"]:
        dx, dy = sx - drag["x"], sy - drag["y"]
        pan_screen(-dx, -dy, target)
        pan_screen(-dx, -dy, view)           # move the current view too, so dragging feels instant
        drag["x"], drag["y"] = sx, sy


def keyboard(key, x, y):
    # কী করছে: Handles the letter/number keys: zoom, rotate, clipping, Bezier points, night, pause, colours, reset, quit.
    # কেন লাগছে: Keyboard shortcuts make the program easy to demo in 2 minutes.
    # real world-এ এটা কোথায় দেখা যায়: Keyboard shortcuts in editors, games and map apps.
    k = key.decode("utf-8", "ignore").lower()
    if k in ("+", "="):
        zoom_at(CX, CY, 1.2)
    elif k in ("-", "_"):
        zoom_at(CX, CY, 1.0 / 1.2)
    elif k == "q":
        target["angle"] += math.radians(15)
    elif k == "e":
        target["angle"] -= math.radians(15)
    elif k == "c":
        state["clip"] = not state["clip"]
    elif k == "p":
        state["ctrl"] = not state["ctrl"]
    elif k == "n":
        state["night"] = not state["night"]
    elif k == " ":
        state["paused"] = not state["paused"]
    elif k in PALETTE:
        state["color"] = k
    elif k == "r":
        target.update(DEFAULT_VIEW)
    elif k == "\x1b":
        sys.exit(0)


def special(key, x, y):
    # কী করছে: Arrow keys pan the camera by 40 screen pixels.
    # কেন লাগছে: Lets you look at other parts of the city without the mouse.
    # real world-এ এটা কোথায় দেখা যায়: Arrow-key scrolling in maps and editors.
    step = 40
    if key == GLUT_KEY_LEFT:
        pan_screen(-step, 0, target)
    elif key == GLUT_KEY_RIGHT:
        pan_screen(step, 0, target)
    elif key == GLUT_KEY_UP:
        pan_screen(0, step, target)
    elif key == GLUT_KEY_DOWN:
        pan_screen(0, -step, target)


def reshape(w, h):
    # কী করছে: If the user resizes the window, it is set back to the original size.
    # কেন লাগছে: The clip window and scissor use fixed pixel values, so a fixed window keeps everything aligned.
    # real world-এ এটা কোথায় দেখা যায়: Fixed-size tool windows and fixed-resolution games.
    if (w, h) != (WIN_W, WIN_H):
        glutReshapeWindow(WIN_W, WIN_H)


def init_gl():
    # কী করছে: Sets a 2D orthographic projection (1 unit = 1 pixel) and turns on blending and smooth lines.
    # কেন লাগছে: We do all transformations ourselves, so OpenGL only needs to know the pixel coordinate system.
    # real world-এ এটা কোথায় দেখা যায়: The orthographic camera of 2D games and UI renderers.
    glViewport(0, 0, WIN_W, WIN_H)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_LINE_SMOOTH)
    glEnable(GL_POINT_SMOOTH)


def main():
    # কী করছে: Starts GLUT, creates the window, registers all callbacks and enters the main loop.
    # কেন লাগছে: This is the entry point of the program.
    # real world-এ এটা কোথায় দেখা যায়: The setup + event loop of every OpenGL application.
    glutInit()
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB)
    glutInitWindowSize(WIN_W, WIN_H)
    glutCreateWindow(b"Mini City Map Viewer - CG Sessional Project")
    init_gl()
    glutDisplayFunc(display)
    glutReshapeFunc(reshape)
    glutKeyboardFunc(keyboard)
    glutSpecialFunc(special)
    glutMouseFunc(mouse)
    glutMotionFunc(motion)
    glutPassiveMotionFunc(motion)
    last_ms[0] = glutGet(GLUT_ELAPSED_TIME)
    glutTimerFunc(16, tick, 0)
    glutMainLoop()


if __name__ == "__main__":
    main()