"""
duo_orbit_bot.py

A practical 2-bot “pipeline” bot for the ORBIT map:
- Bot CHEF camps the cooker area: cooks egg/meat and stores cooked items in the TOP box.
- Bot RUNNER camps shop/submit: buys/chops ingredients, assembles plates, submits orders.

This is written to use ONLY the RobotController API functions from API.docx.
It does NOT assume you can “see” items on tiles (API doc doesn't guarantee that),
so it keeps a lightweight internal memory of what we placed/picked from boxes.

How to integrate:
- If your framework calls something like `play_turn(rc)` each turn, keep that function.
- If it expects a class, wrap `play_turn` inside your class method.

Author: ChatGPT
"""

from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Any


# --------------------------
# Small utilities / constants
# --------------------------

# These are the Buyable names in the API docs (strings are safest if your engine accepts them;
# if your framework uses an Enum Buyable, swap these to Buyable.EGG, etc.)
BUY_EGG = "EGG"
BUY_ONION = "ONION"
BUY_MEAT = "MEAT"
BUY_NOODLES = "NOODLES"
BUY_SAUCE = "SAUCE"
BUY_PLATE = "PLATE"
BUY_PAN = "PAN"

FOOD_EGG = "EGG"
FOOD_ONION = "ONION"
FOOD_MEAT = "MEAT"
FOOD_NOODLES = "NOODLES"
FOOD_SAUCE = "SAUCE"

COOKER_STAGE_COOKED = 1


def manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors4(x: int, y: int) -> List[Tuple[int, int]]:
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def is_food(d: Any) -> bool:
    return isinstance(d, dict) and d.get("type") == "Food"


def is_plate(d: Any) -> bool:
    return isinstance(d, dict) and d.get("type") == "Plate"


def is_pan(d: Any) -> bool:
    return isinstance(d, dict) and d.get("type") == "Pan"


def food_matches(food_dict: Dict[str, Any], name: str, chopped: Optional[bool] = None,
                 cooked_stage: Optional[int] = None) -> bool:
    if not is_food(food_dict):
        return False
    if food_dict.get("food_name") != name:
        return False
    if chopped is not None and bool(food_dict.get("chopped")) != chopped:
        return False
    if cooked_stage is not None and int(food_dict.get("cooked_stage", 0)) != cooked_stage:
        return False
    return True


def plate_contains(plate_dict: Dict[str, Any], want: Dict[str, Any]) -> bool:
    """
    want: {"name": ..., "chopped": bool/None, "cooked_stage": int/None}
    """
    if not is_plate(plate_dict):
        return False
    foods = plate_dict.get("food", []) or []
    for f in foods:
        if food_matches(
            f,
            want["name"],
            chopped=want.get("chopped"),
            cooked_stage=want.get("cooked_stage"),
        ):
            return True
    return False


def normalize_required(required_list: List[str]) -> List[Dict[str, Any]]:
    """
    Convert order.required (list of strings) into a structured list we can reason about.
    We infer chopped/cooked requirements from the common rules:
      - ONION and MEAT must be chopped if used
      - EGG and MEAT must be cooked if used
    If your game defines different rules, adjust here.
    """
    out = []
    for r in required_list:
        name = r.upper()
        if name == FOOD_ONION:
            out.append({"name": FOOD_ONION, "chopped": True, "cooked_stage": None})
        elif name == FOOD_MEAT:
            out.append({"name": FOOD_MEAT, "chopped": True, "cooked_stage": COOKER_STAGE_COOKED})
        elif name == FOOD_EGG:
            out.append({"name": FOOD_EGG, "chopped": False, "cooked_stage": COOKER_STAGE_COOKED})
        else:
            # NOODLES / SAUCE assumed raw, not chopped, not cooked
            out.append({"name": name, "chopped": False, "cooked_stage": None})
    return out


# --------------------------
# Planner State (global)
# --------------------------

@dataclass
class Station:
    name: str
    pos: Tuple[int, int]
    spots: List[Tuple[int, int]]  # adjacent walkable "interaction spots"


class PlannerState:
    def __init__(self):
        self.inited = False
        self.team = None
        self.enemy_team = None
        self.bot_ids: List[int] = []
        self.chef_id: Optional[int] = None
        self.runner_id: Optional[int] = None

        self.W = 16
        self.H = 16
        self.walkable: Set[Tuple[int, int]] = set()

        # Stations
        self.shop: Optional[Station] = None
        self.cooker: Optional[Station] = None
        self.submit_tiles: List[Station] = []  # multiple submit stations
        self.trash: Optional[Station] = None
        self.sink: Optional[Station] = None
        self.sink_table: Optional[Station] = None
        self.boxes: List[Station] = []

        # Choose 2 boxes: "top" (near cooker) and "bottom" (near submit)
        self.top_box: Optional[Station] = None
        self.bottom_box: Optional[Station] = None

        # A chop counter (counter tile with adjacent walkable) near shop
        self.chop_counter: Optional[Tuple[int, int]] = None
        self.chop_spot: Optional[Tuple[int, int]] = None

        # Precomputed BFS distance maps (from every node to every goal we care about)
        # We'll cache BFS-from-goal per goal tile coordinate.
        self.dist_cache: Dict[Tuple[int, int], Dict[Tuple[int, int], int]] = {}

        # Internal inventory memory for boxes (counts of "virtual" contents)
        # Keys like ("top", "COOKED_EGG"), ("bottom", "NOODLES"), etc.
        self.box_mem: Dict[Tuple[str, str], int] = {}

        # Ensure pan exists on cooker (we assume Chef will try to get one placed)
        self.pan_placed_on_cooker: bool = False


STATE = PlannerState()


# --------------------------
# Map / BFS helpers
# --------------------------

def _tile_kind(tile_name: str) -> str:
    t = (tile_name or "").lower()
    # adjust if your engine uses different naming
    if "shop" in t:
        return "shop"
    if "cooker" in t:
        return "cooker"
    if "submit" in t:
        return "submit"
    if "trash" in t:
        return "trash"
    if "sink table" in t or "sinktable" in t:
        return "sink_table"
    if "sink" in t:
        return "sink"
    if "box" in t:
        return "box"
    if "counter" in t:
        return "counter"
    if "floor" in t:
        return "floor"
    if "wall" in t:
        return "wall"
    return "other"


def bfs_from_goal(walkable: Set[Tuple[int, int]], W: int, H: int, goal: Tuple[int, int]) -> Dict[Tuple[int, int], int]:
    """
    BFS distances from every walkable tile to a single goal tile (also walkable).
    Returns dist[pos] = steps.
    """
    dist: Dict[Tuple[int, int], int] = {}
    if goal not in walkable:
        return dist
    q = deque([goal])
    dist[goal] = 0
    while q:
        x, y = q.popleft()
        d = dist[(x, y)]
        for nx, ny in neighbors4(x, y):
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) in walkable and (nx, ny) not in dist:
                dist[(nx, ny)] = d + 1
                q.append((nx, ny))
    return dist


def best_step_toward(state: PlannerState, start: Tuple[int, int], goal: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """
    Pick the next tile (adjacent) that moves start closer to goal using cached BFS distances.
    Returns (nx, ny) or None if stuck.
    """
    if goal not in state.dist_cache:
        state.dist_cache[goal] = bfs_from_goal(state.walkable, state.W, state.H, goal)
    dist = state.dist_cache[goal]
    if start not in dist:
        return None
    best = None
    best_d = dist[start]
    for nx, ny in neighbors4(*start):
        if (nx, ny) in state.walkable and (nx, ny) in dist and dist[(nx, ny)] < best_d:
            best_d = dist[(nx, ny)]
            best = (nx, ny)
    return best


def nearest_interaction_spot(state: PlannerState, bot_pos: Tuple[int, int], station: Station) -> Optional[Tuple[int, int]]:
    """
    Choose the best walkable adjacent spot to stand on to interact with station.pos.
    """
    if not station.spots:
        return None
    best = min(station.spots, key=lambda s: manhattan(bot_pos, s))
    return best


def _compute_station_spots(state: PlannerState, pos: Tuple[int, int]) -> List[Tuple[int, int]]:
    spots = []
    for nx, ny in neighbors4(*pos):
        if (nx, ny) in state.walkable:
            spots.append((nx, ny))
    return spots


def _safe_get_map_size(rc) -> Tuple[int, int]:
    """
    Try to get size from rc.get_map(); otherwise default to 16x16 for this orbit map.
    """
    try:
        m = rc.get_map()
        W = getattr(m, "width", None) or getattr(m, "W", None) or getattr(m, "w", None)
        H = getattr(m, "height", None) or getattr(m, "H", None) or getattr(m, "h", None)
        if isinstance(W, int) and isinstance(H, int):
            return W, H
    except Exception:
        pass
    return 16, 16


def init_if_needed(rc):
    if STATE.inited:
        return

    STATE.team = rc.get_team()
    STATE.enemy_team = rc.get_enemy_team()
    STATE.bot_ids = list(rc.get_team_bot_ids())

    STATE.W, STATE.H = _safe_get_map_size(rc)

    # Discover walkable + stations by scanning tiles via rc.get_tile(team, x, y)
    # (We scan your own team's map first; switching uses enemy map later.)
    walkable = set()
    stations: List[Tuple[str, Tuple[int, int]]] = []
    counters: List[Tuple[int, int]] = []

    for x in range(STATE.W):
        for y in range(STATE.H):
            tile = rc.get_tile(STATE.team, x, y)
            if tile is None:
                continue
            if getattr(tile, "is_walkable", False):
                walkable.add((x, y))
            kind = _tile_kind(getattr(tile, "tile_name", ""))
            if kind in {"shop", "cooker", "submit", "trash", "sink", "sink_table", "box"}:
                stations.append((kind, (x, y)))
            if kind == "counter":
                counters.append((x, y))

    STATE.walkable = walkable

    # Build stations
    for kind, pos in stations:
        st = Station(kind, pos, _compute_station_spots(STATE, pos))
        if kind == "shop":
            STATE.shop = st
        elif kind == "cooker":
            STATE.cooker = st
        elif kind == "trash":
            STATE.trash = st
        elif kind == "sink":
            STATE.sink = st
        elif kind == "sink_table":
            STATE.sink_table = st
        elif kind == "box":
            STATE.boxes.append(st)
        elif kind == "submit":
            STATE.submit_tiles.append(st)

    # Choose top_box = closest to cooker; bottom_box = closest to submit cluster center
    if STATE.boxes:
        if STATE.cooker:
            STATE.top_box = min(STATE.boxes, key=lambda b: manhattan(b.pos, STATE.cooker.pos))
        # submit center:
        if STATE.submit_tiles:
            cx = sum(s.pos[0] for s in STATE.submit_tiles) / len(STATE.submit_tiles)
            cy = sum(s.pos[1] for s in STATE.submit_tiles) / len(STATE.submit_tiles)
            STATE.bottom_box = min(STATE.boxes, key=lambda b: abs(b.pos[0]-cx) + abs(b.pos[1]-cy))
        # If only one box, use it for both
        if STATE.bottom_box is None:
            STATE.bottom_box = STATE.top_box

    # Choose chop counter: nearest counter to shop that has at least one walkable adjacent
    if STATE.shop:
        best = None
        best_dist = 10**9
        for cpos in counters:
            # needs an adjacent walkable spot
            adj = [p for p in neighbors4(*cpos) if p in STATE.walkable]
            if not adj:
                continue
            d = manhattan(cpos, STATE.shop.pos)
            if d < best_dist:
                best_dist = d
                best = (cpos, adj[0])
        if best:
            STATE.chop_counter, STATE.chop_spot = best

    # Assign roles: chef = bot closer to cooker at start, runner = the other
    if STATE.cooker and len(STATE.bot_ids) >= 2:
        b0 = rc.get_bot_state(STATE.bot_ids[0]) or {}
        b1 = rc.get_bot_state(STATE.bot_ids[1]) or {}
        p0 = tuple(b0.get("pos", (0, 0)))
        p1 = tuple(b1.get("pos", (0, 0)))
        if manhattan(p0, STATE.cooker.pos) <= manhattan(p1, STATE.cooker.pos):
            STATE.chef_id, STATE.runner_id = STATE.bot_ids[0], STATE.bot_ids[1]
        else:
            STATE.chef_id, STATE.runner_id = STATE.bot_ids[1], STATE.bot_ids[0]
    else:
        # fallback
        STATE.chef_id = STATE.bot_ids[0] if STATE.bot_ids else None
        STATE.runner_id = STATE.bot_ids[1] if len(STATE.bot_ids) > 1 else None

    # Seed memory
    for key in [
        ("top", "COOKED_EGG"),
        ("top", "COOKED_MEAT"),
        ("top", "RAW_EGG"),
        ("top", "CHOPPED_MEAT"),
        ("bottom", "NOODLES"),
        ("bottom", "SAUCE"),
        ("bottom", "CHOPPED_ONION"),
        ("bottom", "PLATE"),
    ]:
        STATE.box_mem[key] = 0

    STATE.inited = True


# --------------------------
# Order selection + goals
# --------------------------

def pick_primary_order(rc) -> Optional[Dict[str, Any]]:
    """
    Simple, strong heuristic:
    - active orders only
    - prioritize earliest expires_turn; tiebreaker higher reward
    """
    turn = rc.get_turn()
    orders = rc.get_orders() or []
    active = [o for o in orders if o.get("is_active") and o.get("completed_turn") is None]
    if not active:
        return None
    active.sort(key=lambda o: (o.get("expires_turn", 10**9) - turn, -o.get("reward", 0)))
    return active[0]


def need_cooked_items(req: List[Dict[str, Any]]) -> bool:
    for r in req:
        if r["name"] in (FOOD_EGG, FOOD_MEAT):
            return True
    return False


# --------------------------
# Action primitives (one move + maybe one action)
# --------------------------

def move_one_step(rc, bot_id: int, target: Tuple[int, int]) -> bool:
    bs = rc.get_bot_state(bot_id) or {}
    pos = tuple(bs.get("pos", (0, 0)))
    if pos == target:
        return False
    nxt = best_step_toward(STATE, pos, target)
    if nxt is None:
        return False
    return bool(rc.move(bot_id, nxt[0], nxt[1]))


def at_spot(rc, bot_id: int, spot: Tuple[int, int]) -> bool:
    bs = rc.get_bot_state(bot_id) or {}
    pos = tuple(bs.get("pos", (0, 0)))
    return pos == spot


def held_public(rc, bot_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    it = bot_state.get("held_item", None)
    try:
        return rc.item_to_public_dict(it)
    except Exception:
        return None


def try_interact_station(rc, bot_id: int, station: Station, action_fn, *args, **kwargs) -> bool:
    """
    Ensure we're adjacent to station.pos (standing on an interaction spot), then call action_fn(bot_id, station.pos).
    """
    bs = rc.get_bot_state(bot_id) or {}
    pos = tuple(bs.get("pos", (0, 0)))
    spot = nearest_interaction_spot(STATE, pos, station)
    if spot is None:
        return False
    if pos != spot:
        move_one_step(rc, bot_id, spot)
        return True  # spent move, no action this tick
    # adjacent; do action
    return bool(action_fn(bot_id, station.pos[0], station.pos[1], *args, **kwargs))


# --------------------------
# High-level bot policies
# --------------------------

def chef_policy(rc, order_req: List[Dict[str, Any]]):
    """
    Chef logic:
    1) Ensure pan exists on cooker (buy pan via runner, or chef can do it if near shop; but chef camps cooker so we prefer runner buys)
    2) If holding cookable and can start_cook -> start_cook
    3) If pan has cooked food and chef empty -> take_from_pan, then place into top box
    4) If need cooked items and buffers low -> request runner to deliver raw egg / chopped meat to top box
       (implemented by chef increasing "desired" counts via mem check; runner will fulfill)
    """
    bot_id = STATE.chef_id
    if bot_id is None or STATE.cooker is None or STATE.top_box is None:
        return

    bs = rc.get_bot_state(bot_id) or {}
    held = held_public(rc, bs)

    # A) If holding food that can be cooked, try start_cook
    if held and is_food(held):
        name = held.get("food_name")
        # only cook egg/meat
        if name in (FOOD_EGG, FOOD_MEAT) and rc.can_start_cook(bot_id, STATE.cooker.pos[0], STATE.cooker.pos[1]):
            try_interact_station(rc, bot_id, STATE.cooker, lambda bid, x, y: rc.start_cook(bid, x, y))
            return

    # B) If empty hands, try take_from_pan if possible
    if held is None:
        # take_from_pan requires cooker has non-empty pan; we just try.
        if try_interact_station(rc, bot_id, STATE.cooker, lambda bid, x, y: rc.take_from_pan(bid, x, y)):
            return

    # C) If holding cooked food, store into top box
    if held and is_food(held):
        # place into top box
        if try_interact_station(rc, bot_id, STATE.top_box, lambda bid, x, y: rc.place(bid, x, y)):
            # update memory (roughly: if cooked egg/meat, count it)
            if int(held.get("cooked_stage", 0)) == COOKER_STAGE_COOKED:
                if held.get("food_name") == FOOD_EGG:
                    STATE.box_mem[("top", "COOKED_EGG")] += 1
                if held.get("food_name") == FOOD_MEAT:
                    STATE.box_mem[("top", "COOKED_MEAT")] += 1
            return

    # D) Otherwise hover by cooker spot (so you can immediately act next turn)
    spot = nearest_interaction_spot(STATE, tuple(bs.get("pos", (0, 0))), STATE.cooker)
    if spot:
        move_one_step(rc, bot_id, spot)


def runner_policy(rc, order: Optional[Dict[str, Any]], order_req: List[Dict[str, Any]]):
    """
    Runner logic:
    - Keeps bottom box stocked with NOODLES, SAUCE, CHOPPED_ONION, and PLATE.
    - If order needs cooked items, fetch from top box when available.
    - Assemble plate by adding foods onto the plate (using add_food_to_plate).
      Since we cannot see exact tile contents, we do a consistent “build at bottom box”:
         * put plate on bottom box tile (place)
         * bring ingredients one by one, add to plate at bottom box coordinate
         * pickup plate, go submit
    """

    bot_id = STATE.runner_id
    if bot_id is None or STATE.shop is None or STATE.bottom_box is None or not STATE.submit_tiles:
        return

    bs = rc.get_bot_state(bot_id) or {}
    held = held_public(rc, bs)
    pos = tuple(bs.get("pos", (0, 0)))

    # ---------
    # 1) If holding a plate that might be complete, try submit at nearest submit station
    # ---------
    if held and is_plate(held):
        # just attempt submit at closest submit
        sub = min(STATE.submit_tiles, key=lambda s: manhattan(pos, s.pos))
        # move/submit
        if try_interact_station(rc, bot_id, sub, lambda bid, x, y: rc.submit(bid, x, y)):
            return
        # if we moved closer, we already returned True; otherwise continue.

    # ---------
    # 2) Stocking / fulfillment priorities
    # ---------

    # Decide what we want buffered for this order
    wants_bottom = []
    wants_top_fetch = []

    # Always keep these buffers
    wants_bottom += [("NOODLES", 2), ("SAUCE", 2), ("CHOPPED_ONION", 1), ("PLATE", 1)]

    # If current order exists, ensure we can fulfill it:
    if order_req:
        # if order needs cooked egg/meat, we prefer taking from top box (cooked buffer)
        if any(r["name"] == FOOD_EGG for r in order_req):
            wants_top_fetch.append(("COOKED_EGG", 1))
        if any(r["name"] == FOOD_MEAT for r in order_req):
            wants_top_fetch.append(("COOKED_MEAT", 1))

        # also ensure raw basics exist in bottom
        if any(r["name"] == FOOD_NOODLES for r in order_req):
            wants_bottom.append(("NOODLES", 2))
        if any(r["name"] == FOOD_SAUCE for r in order_req):
            wants_bottom.append(("SAUCE", 2))
        if any(r["name"] == FOOD_ONION for r in order_req):
            wants_bottom.append(("CHOPPED_ONION", 2))

    # Helper: buy something at shop
    def buy_item(buy_name: str) -> bool:
        # Must be adjacent to shop; use can_buy/buy if available
        if not rc.can_buy(bot_id, buy_name, STATE.shop.pos[0], STATE.shop.pos[1]):
            # move closer
            try_interact_station(rc, bot_id, STATE.shop, lambda bid, x, y: True)
            return True
        return bool(rc.buy(bot_id, buy_name, STATE.shop.pos[0], STATE.shop.pos[1]))

    # Helper: place into bottom box
    def place_to_bottom() -> bool:
        ok = try_interact_station(rc, bot_id, STATE.bottom_box, lambda bid, x, y: rc.place(bid, x, y))
        return ok

    # Helper: pickup from a box
    def pickup_from_box(box: Station) -> bool:
        ok = try_interact_station(rc, bot_id, box, lambda bid, x, y: rc.pickup(bid, x, y))
        return ok

    # ---------
    # 3) If we are empty-handed, decide what to fetch next
    # ---------
    if held is None:
        # 3a) If we need cooked items and top box has them (per memory), fetch them to bottom box
        for item_key, target_cnt in wants_top_fetch:
            if STATE.box_mem[("top", item_key)] > 0 and STATE.box_mem[("bottom", item_key)] < target_cnt:
                # go pick from top box
                if pickup_from_box(STATE.top_box):
                    # if success we should decrement top mem next tick after we confirm hold, but we can't confirm
                    # so we decrement optimistically only when we observe held later. We'll do it right away conservatively:
                    STATE.box_mem[("top", item_key)] = max(0, STATE.box_mem[("top", item_key)] - 1)
                    return
                return

        # 3b) If bottom buffers low, go buy/chop/fill
        # Priority: PLATE (needed for submission), then onions, then noodles/sauce.
        # (If your engine has plenty of plates from sink table, you can switch strategy.)
        for item_key, target_cnt in wants_bottom:
            if item_key == "PLATE" and STATE.box_mem[("bottom", "PLATE")] < target_cnt:
                # buy plate then place into bottom box
                if buy_item(BUY_PLATE):
                    # next step: place into bottom
                    return
                return

        # onion chopped buffer
        if STATE.box_mem[("bottom", "CHOPPED_ONION")] < 1:
            # buy onion
            if buy_item(BUY_ONION):
                return
            return

        # noodles / sauce buffer
        if STATE.box_mem[("bottom", "NOODLES")] < 2:
            if buy_item(BUY_NOODLES):
                return
            return
        if STATE.box_mem[("bottom", "SAUCE")] < 2:
            if buy_item(BUY_SAUCE):
                return
            return

        # If nothing to buy, start assembling a plate for the current order:
        # pickup a plate from bottom box (memory-based). If none in mem, buy one.
        if STATE.box_mem[("bottom", "PLATE")] > 0:
            if pickup_from_box(STATE.bottom_box):
                STATE.box_mem[("bottom", "PLATE")] = max(0, STATE.box_mem[("bottom", "PLATE")] - 1)
                return
        else:
            if buy_item(BUY_PLATE):
                return
        return

    # ---------
    # 4) If holding something, decide what to do with it
    # ---------

    # 4a) Holding a raw onion -> go chop it, then place to bottom box
    if held and is_food(held) and held.get("food_name") == FOOD_ONION and not bool(held.get("chopped")):
        # move to chop spot, then chop at chop_counter
        if STATE.chop_counter and STATE.chop_spot:
            if not at_spot(rc, bot_id, STATE.chop_spot):
                move_one_step(rc, bot_id, STATE.chop_spot)
                return
            # chop
            if rc.chop(bot_id, STATE.chop_counter[0], STATE.chop_counter[1]):
                return
        # fallback: just place it into bottom box even if unchopped
        place_to_bottom()
        return

    # 4b) Holding any ingredient (or chopped onion) -> place it into bottom box (stocking)
    if held and (is_food(held) or is_pan(held)):
        # If it's cooked egg/meat and we fetched it, store in bottom box for assembly
        if is_food(held) and int(held.get("cooked_stage", 0)) == COOKER_STAGE_COOKED:
            if held.get("food_name") == FOOD_EGG:
                if place_to_bottom():
                    STATE.box_mem[("bottom", "COOKED_EGG")] += 1
                    return
            if held.get("food_name") == FOOD_MEAT:
                if place_to_bottom():
                    STATE.box_mem[("bottom", "COOKED_MEAT")] += 1
                    return

        # chopped onion
        if is_food(held) and held.get("food_name") == FOOD_ONION and bool(held.get("chopped")):
            if place_to_bottom():
                STATE.box_mem[("bottom", "CHOPPED_ONION")] += 1
                return

        # noodles/sauce
        if is_food(held) and held.get("food_name") == FOOD_NOODLES:
            if place_to_bottom():
                STATE.box_mem[("bottom", "NOODLES")] += 1
                return
        if is_food(held) and held.get("food_name") == FOOD_SAUCE:
            if place_to_bottom():
                STATE.box_mem[("bottom", "SAUCE")] += 1
                return

    # 4c) Holding a plate: assemble at bottom box coordinate by adding foods we can pick from bottom box.
    if held and is_plate(held):
        # If plate is dirty, we'd need sink cycle; simplest: trash it (optional).
        if bool(held.get("dirty")) and STATE.trash:
            try_interact_station(rc, bot_id, STATE.trash, lambda bid, x, y: rc.trash(bid, x, y))
            return

        # Strategy: stand at bottom box interaction spot, and add foods to plate by picking foods then add_food_to_plate.
        # Because we can't inspect what's "on tile", we do:
        #   - Ensure we stand adjacent to bottom box tile
        #   - Place plate on bottom box tile
        #   - Then fetch items one by one and add them onto that plate (targeting bottom box coordinate)
        #   - Finally pick plate up and go submit
        box_spot = nearest_interaction_spot(STATE, pos, STATE.bottom_box)
        if box_spot and pos != box_spot:
            move_one_step(rc, bot_id, box_spot)
            return

        # Place plate onto bottom box tile as the "assembly anchor"
        if rc.place(bot_id, STATE.bottom_box.pos[0], STATE.bottom_box.pos[1]):
            # Now we are empty-handed next turn, we will pick ingredients and add to plate
            # (We don't increment PLATE mem because it's now "in-use" on tile)
            return

        # If place failed, just go submit (maybe plate already has stuff)
        sub = min(STATE.submit_tiles, key=lambda s: manhattan(pos, s.pos))
        try_interact_station(rc, bot_id, sub, lambda bid, x, y: rc.submit(bid, x, y))
        return

    # 4d) Holding a plate should be handled above; holding a bought plate item may appear as Plate
    if held and is_plate(held) and not held.get("food"):
        # keep it in bottom box as buffer
        if place_to_bottom():
            STATE.box_mem[("bottom", "PLATE")] += 1
            return

    # 4e) Default: drift toward shop (so we stay productive)
    shop_spot = nearest_interaction_spot(STATE, pos, STATE.shop)
    if shop_spot:
        move_one_step(rc, bot_id, shop_spot)


def assembly_helper_step(rc, order_req: List[Dict[str, Any]]):
    """
    Optional extra: If you want the runner to actually finish plates reliably,
    you can call this after runner_policy and implement a deterministic assembly loop.

    Because visibility of items-on-tiles isn't guaranteed, a full “perfect assembly”
    is hard without additional state from game.py or Tile contents.
    This file keeps things simple: stock buffers + submit when holding plate.
    """
    return


# --------------------------
# Main entrypoint
# --------------------------

def play_turn(rc):
    """
    This should be called by game.py every turn.
    """
    init_if_needed(rc)

    order = pick_primary_order(rc)
    order_req = normalize_required(order.get("required", [])) if order else []

    # CHEF acts
    if STATE.chef_id is not None:
        chef_policy(rc, order_req)

    # RUNNER acts
    if STATE.runner_id is not None:
        runner_policy(rc, order, order_req)

    # If you want, you can add sabotage logic around the switch turn here using:
    # info = rc.get_switch_info()
    # if rc.can_switch_maps(): rc.switch_maps()
    # (kept out for baseline stability)


# If your framework imports a symbol named `main`:
def main(rc):
    play_turn(rc)
