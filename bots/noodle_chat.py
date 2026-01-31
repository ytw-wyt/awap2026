import random
from collections import deque
from typing import Tuple, Optional, List, Dict, Any

from game_constants import Team, TileType, FoodType, ShopCosts
from robot_controller import RobotController
from item import Pan, Plate, Food


Pos = Tuple[int, int]
Step = Tuple[int, int]


# -----------------------------
# Helpers: safe API wrappers
# -----------------------------
def get_orders_safe(controller: RobotController):
    """Engine variants: get_orders() or get_orders(team)."""
    try:
        return controller.get_orders()
    except TypeError:
        return controller.get_orders(controller.get_team())


def get_team_bot_ids_safe(controller: RobotController):
    """Engine variants: get_team_bot_ids() or get_team_bot_ids(team)."""
    try:
        return controller.get_team_bot_ids()
    except TypeError:
        return controller.get_team_bot_ids(controller.get_team())


def get_team_money_safe(controller: RobotController):
    """Engine variants: get_team_money() or get_team_money(team)."""
    try:
        return controller.get_team_money()
    except TypeError:
        return controller.get_team_money(controller.get_team())


# -----------------------------
# Task / Plan representation
# -----------------------------
class TaskKind:
    IDLE = "IDLE"
    BUY_PAN = "BUY_PAN"
    PLACE_PAN = "PLACE_PAN"

    BUY_PLATE = "BUY_PLATE"
    PLACE_PLATE_ON_COUNTER = "PLACE_PLATE_ON_COUNTER"

    BUY_INGREDIENT = "BUY_INGREDIENT"
    PLACE_ON_COUNTER = "PLACE_ON_COUNTER"
    CHOP_ON_COUNTER = "CHOP_ON_COUNTER"
    PICKUP_FROM_COUNTER = "PICKUP_FROM_COUNTER"

    START_COOK = "START_COOK"              # place food onto cooker/pan (your engine auto-starts cooking on place)
    WAIT_COOK = "WAIT_COOK"
    TAKE_FROM_PAN = "TAKE_FROM_PAN"

    ADD_TO_PLATE = "ADD_TO_PLATE"
    PICKUP_PLATE = "PICKUP_PLATE"
    SUBMIT = "SUBMIT"

    TRASH = "TRASH"


class BotPlan:
    """
    One bot pursuing one order.
    Stages:
      - ensure pan exists (shared cooker)
      - gather ingredients (buy -> optional chop -> optional cook)
      - plate + submit
    """

    def __init__(self):
        self.order_id: Optional[int] = None
        self.required: List[str] = []
        self.stage: str = "INIT"

        # Ingredient pointer
        self.idx: int = 0

        # For cooking steps
        self.awaiting_cook: bool = False

        # For plating
        self.has_plate_ready: bool = False

        # Current task
        self.task: str = TaskKind.IDLE
        self.task_target: Optional[Pos] = None
        self.task_data: Dict[str, Any] = {}

        # Home assembly counter (so bots don't fight for same counter)
        self.counter: Optional[Pos] = None


# -----------------------------
# Main BotPlayer
# -----------------------------
class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        self.inited = False

        # station locations
        self.shop_locs: List[Pos] = []
        self.cooker_locs: List[Pos] = []
        self.counter_locs: List[Pos] = []
        self.submit_locs: List[Pos] = []
        self.trash_locs: List[Pos] = []

        # per-bot persistent plan
        self.bot_plans: Dict[int, BotPlan] = {}

        # simple shared resource reservation (avoid deadlocks)
        # cooker_reserved_by: bot_id or None
        self.cooker_reserved_by: Optional[int] = None

        # If diagonal moves are allowed (your original BFS allowed diagonals), keep True
        self.allow_diagonal = True

    # -----------------------------
    # Map scanning / station finding
    # -----------------------------
    def _scan_stations(self, controller: RobotController):
        team = controller.get_team()
        m = controller.get_map(team)
        self.shop_locs = []
        self.cooker_locs = []
        self.counter_locs = []
        self.submit_locs = []
        self.trash_locs = []

        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                name = tile.tile_name

                # NOTE: your current code searches for string names like "COUNTER", "COOKER", etc.
                # In this engine it looks like tile.tile_name matches these.
                if name == "SHOP":
                    self.shop_locs.append((x, y))
                elif name == "COOKER":
                    self.cooker_locs.append((x, y))
                elif name == "COUNTER":
                    self.counter_locs.append((x, y))
                elif name == "SUBMIT":
                    self.submit_locs.append((x, y))
                elif name == "TRASH":
                    self.trash_locs.append((x, y))

    def _nearest(self, src: Pos, options: List[Pos]) -> Optional[Pos]:
        if not options:
            return None
        sx, sy = src
        # Chebyshev distance (diagonal allowed)
        return min(options, key=lambda p: max(abs(p[0] - sx), abs(p[1] - sy)))

    # -----------------------------
    # Shortest-path movement (BFS)
    # -----------------------------
    def get_bfs_step(self, controller: RobotController, start: Pos, goal: Pos) -> Optional[Step]:
        """
        Returns the first (dx,dy) step along a shortest path from start to goal.
        Movement uses deltas: controller.move(bot_id, dx, dy).
        We treat tiles as walkable via controller.get_map(team).is_tile_walkable(nx, ny).
        """
        if start == goal:
            return None

        team = controller.get_team()
        m = controller.get_map(team)
        w, h = m.width, m.height

        # neighbor deltas
        if self.allow_diagonal:
            deltas = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if not (dx == 0 and dy == 0)]
        else:
            deltas = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        q = deque([start])
        prev: Dict[Pos, Optional[Pos]] = {start: None}

        while q:
            cx, cy = q.popleft()
            if (cx, cy) == goal:
                break

            for dx, dy in deltas:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if (nx, ny) in prev:
                    continue
                if m.is_tile_walkable(nx, ny):
                    prev[(nx, ny)] = (cx, cy)
                    q.append((nx, ny))

        if goal not in prev:
            return None  # no path

        # reconstruct back from goal to start -> find next position
        cur = goal
        while prev[cur] is not None and prev[cur] != start:
            cur = prev[cur]

        # now cur is the next position after start (or goal if adjacent)
        sx, sy = start
        nx, ny = cur
        return (nx - sx, ny - sy)

    def move_towards_adjacent(self, controller: RobotController, bot_id: int, target: Pos) -> bool:
        """
        Moves the bot one step toward being adjacent to target.
        Returns True if already adjacent (Chebyshev <= 1), else False.
        """
        st = controller.get_bot_state(bot_id)
        bx, by = st["x"], st["y"]
        tx, ty = target
        if max(abs(bx - tx), abs(by - ty)) <= 1:
            return True

        # pathfind to a specific adjacent cell: easiest approach
        # pick the best adjacent cell around target that is walkable and BFS to it.
        team = controller.get_team()
        m = controller.get_map(team)

        candidates: List[Pos] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                ax, ay = tx + dx, ty + dy
                if 0 <= ax < m.width and 0 <= ay < m.height and m.is_tile_walkable(ax, ay):
                    candidates.append((ax, ay))
        if not candidates:
            return False

        start = (bx, by)
        # choose nearest candidate by BFS heuristic (chebyshev first; BFS will ensure optimal locally)
        cand = min(candidates, key=lambda p: max(abs(p[0] - bx), abs(p[1] - by)))
        step = self.get_bfs_step(controller, start, cand)
        if step:
            controller.move(bot_id, step[0], step[1])
        return False

    # -----------------------------
    # Order assignment (two bots, different orders)
    # -----------------------------
    def choose_orders_for_bots(self, controller: RobotController, bot_ids: List[int]) -> Dict[int, Optional[Dict]]:
        """
        Assign distinct active orders to bots when possible.
        Uses greedy scoring: highest reward, then earliest expiry.
        """
        orders = get_orders_safe(controller)
        turn = controller.get_turn()

        active: List[Dict] = []
        for o in orders:
            if not o.get("is_active"):
                continue
            if o.get("completed_turn") is not None:
                continue
            exp = o.get("expires_turn", 10**9)
            if exp <= turn:
                continue
            active.append(o)

        def score(o):
            reward = o.get("reward", 0)
            exp = o.get("expires_turn", 10**9)
            # higher reward better, sooner expiry slightly higher priority
            return (reward, -(exp - turn))

        active.sort(key=score, reverse=True)

        assignments: Dict[int, Optional[Dict]] = {bid: None for bid in bot_ids}
        used_order_ids = set()

        for bid in bot_ids:
            # keep existing assignment if still valid
            plan = self.bot_plans.get(bid)
            if plan and plan.order_id is not None:
                for o in active:
                    if o.get("order_id") == plan.order_id:
                        assignments[bid] = o
                        used_order_ids.add(plan.order_id)
                        break

        # assign remaining bots to distinct remaining orders
        for bid in bot_ids:
            if assignments[bid] is not None:
                continue
            for o in active:
                oid = o.get("order_id")
                if oid not in used_order_ids:
                    assignments[bid] = o
                    used_order_ids.add(oid)
                    break

        return assignments

    # -----------------------------
    # Shared cooker / pan logic
    # -----------------------------
    def cooker_has_pan(self, controller: RobotController, cooker: Pos) -> bool:
        tile = controller.get_tile(controller.get_team(), cooker[0], cooker[1])
        return bool(tile and isinstance(tile.item, Pan))

    def cooker_food_state(self, controller: RobotController, cooker: Pos) -> Tuple[bool, Optional[int]]:
        """
        Returns (has_food, cooked_stage) if pan exists.
        cooked_stage: 0 uncooked/cooking, 1 cooked, 2 burnt
        """
        tile = controller.get_tile(controller.get_team(), cooker[0], cooker[1])
        if not tile or not isinstance(tile.item, Pan):
            return (False, None)
        pan: Pan = tile.item
        if not getattr(pan, "food", None):
            return (False, None)
        food = pan.food
        return (True, getattr(food, "cooked_stage", None))

    # -----------------------------
    # Planning: compute next task for a bot
    # -----------------------------
    def foodtype_from_name(self, name: str):
        """
        Map order required strings to FoodType enum.
        Tries common variants.
        """
        n = name.upper()
        # Common names: "MEAT", "NOODLES", "EGG", "ONION", "SAUCE"
        for cand in ["MEAT", "NOODLES", "EGG", "ONION", "SAUCE"]:
            if cand == n:
                return getattr(FoodType, cand, None)
        return getattr(FoodType, n, None)

    def needs_chop(self, ft) -> bool:
        # In your constants: onion/meat are choppable, egg/noodles/sauce not.
        return bool(getattr(ft, "choppable", False))

    def needs_cook(self, ft) -> bool:
        return bool(getattr(ft, "cookable", False))

    def set_task(self, plan: BotPlan, kind: str, target: Optional[Pos], **data):
        plan.task = kind
        plan.task_target = target
        plan.task_data = data

    def ensure_counter_for_bot(self, controller: RobotController, bot_id: int, plan: BotPlan):
        if plan.counter is not None:
            return
        st = controller.get_bot_state(bot_id)
        bx, by = st["x"], st["y"]

        # Try to give bots different counters to reduce collisions
        # pick nearest unused counter
        used = set(p.counter for p in self.bot_plans.values() if p.counter is not None)
        candidates = [c for c in self.counter_locs if c not in used] or self.counter_locs
        plan.counter = self._nearest((bx, by), candidates)

    def plan_next_task(self, controller: RobotController, bot_id: int, plan: BotPlan):
        """
        Decide what the bot should do next, based on its current order + state.
        """
        st = controller.get_bot_state(bot_id)
        holding = st.get("holding")
        bx, by = st["x"], st["y"]

        shop = self._nearest((bx, by), self.shop_locs)
        cooker = self._nearest((bx, by), self.cooker_locs)
        submit = self._nearest((bx, by), self.submit_locs)
        trash = self._nearest((bx, by), self.trash_locs)

        self.ensure_counter_for_bot(controller, bot_id, plan)
        counter = plan.counter

        if not shop or not cooker or not submit or not counter or not trash:
            self.set_task(plan, TaskKind.IDLE, None)
            return

        # If holding something and we need empty hands to buy, drop it on counter (safe) or trash if junk
        # If holding burnt food or dirty plate etc, trash
        if holding:
            # if holding Food and cooked_stage == 2 -> trash
            if isinstance(holding, Food) and getattr(holding, "cooked_stage", 0) == 2:
                self.set_task(plan, TaskKind.TRASH, trash)
                return

        # If no order assigned, idle near shop
        if plan.order_id is None or not plan.required:
            self.set_task(plan, TaskKind.IDLE, shop)
            return

        # ----------------------
        # Shared pan setup
        # ----------------------
        if not self.cooker_has_pan(controller, cooker):
            # Avoid deadlock: only one bot should be responsible for pan at a time.
            if self.cooker_reserved_by is None:
                self.cooker_reserved_by = bot_id
            if self.cooker_reserved_by != bot_id:
                # other bot is placing/buying pan; meanwhile do plate prep (buy plate) to avoid stalling
                if holding is None and get_team_money_safe(controller) >= ShopCosts.PLATE.buy_cost:
                    self.set_task(plan, TaskKind.BUY_PLATE, shop)
                else:
                    self.set_task(plan, TaskKind.IDLE, counter)
                return

            # If we reserved cooker for pan, execute: buy pan -> place pan
            if holding is None:
                if get_team_money_safe(controller) >= ShopCosts.PAN.buy_cost:
                    self.set_task(plan, TaskKind.BUY_PAN, shop)
                else:
                    self.set_task(plan, TaskKind.IDLE, shop)
                return
            # Assume holding pan
            self.set_task(plan, TaskKind.PLACE_PAN, cooker)
            return
        else:
            # if pan exists and we were reserving for pan, release reservation
            if self.cooker_reserved_by == bot_id:
                self.cooker_reserved_by = None

        # ----------------------
        # Plate prep early (avoid cooker deadlocks)
        # ----------------------
        if not plan.has_plate_ready:
            # If holding nothing -> buy plate, place on counter
            if holding is None:
                if get_team_money_safe(controller) >= ShopCosts.PLATE.buy_cost:
                    self.set_task(plan, TaskKind.BUY_PLATE, shop)
                else:
                    self.set_task(plan, TaskKind.IDLE, shop)
                return
            if isinstance(holding, Plate):
                self.set_task(plan, TaskKind.PLACE_PLATE_ON_COUNTER, counter)
                return
            # holding something else -> put on counter to free hands
            self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)
            return

        # ----------------------
        # Ingredient processing loop
        # ----------------------
        if plan.idx >= len(plan.required):
            # all ingredients prepared -> pick up plate and submit
            if holding is None:
                # plate should be on counter
                self.set_task(plan, TaskKind.PICKUP_FROM_COUNTER, counter)
                return
            if isinstance(holding, Plate):
                self.set_task(plan, TaskKind.SUBMIT, submit)
                return
            # holding something else -> add to plate if possible, else place on counter
            self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)
            return

        current_name = plan.required[plan.idx]
        ft = self.foodtype_from_name(current_name)
        if ft is None:
            # unknown food; skip
            plan.idx += 1
            self.set_task(plan, TaskKind.IDLE, counter)
            return

        # If this ingredient needs cooking, we must use cooker carefully.
        # If cooker is currently busy with someone else's food and not ready, do another useful thing (idle / buy next items if you want).
        has_food, cooked_stage = self.cooker_food_state(controller, cooker)

        # If cooker has burnt food, whoever reaches it should trash it to prevent deadlock.
        if has_food and cooked_stage == 2:
            # Only try to clear if hands empty (take_from_pan needs empty hands)
            if holding is None:
                self.set_task(plan, TaskKind.TAKE_FROM_PAN, cooker)
            else:
                self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)
            return

        # If we are awaiting cook completion for this ingredient
        if plan.awaiting_cook:
            if has_food and cooked_stage == 1:
                # cooked ready, take it
                if holding is None:
                    self.set_task(plan, TaskKind.TAKE_FROM_PAN, cooker)
                else:
                    self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)
                return
            # Not ready yet -> do something useful: stay near counter
            self.set_task(plan, TaskKind.WAIT_COOK, cooker)
            return

        # Not awaiting cook: we need to obtain/process this ingredient
        if holding is None:
            # buy ingredient
            if get_team_money_safe(controller) >= ft.buy_cost:
                self.set_task(plan, TaskKind.BUY_INGREDIENT, shop, food=ft)
            else:
                self.set_task(plan, TaskKind.IDLE, shop)
            return

        # If holding ingredient food
        if isinstance(holding, Food):
            # If needs chop, do chop on counter
            if self.needs_chop(ft) and not getattr(holding, "chopped", False):
                # place it, chop, pickup
                self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)
                return

            # If needs cook, move to cooker and place to start cooking
            if self.needs_cook(ft) and getattr(holding, "cooked_stage", 0) == 0:
                # If cooker currently has food cooking, avoid deadlock: wait unless it's our turn (reservation)
                if has_food and cooked_stage in (0, 1):
                    # Cooker busy; do not interfere.
                    self.set_task(plan, TaskKind.IDLE, counter)
                    return

                # reserve cooker for this bot while it starts cooking + waits
                if self.cooker_reserved_by is None:
                    self.cooker_reserved_by = bot_id
                if self.cooker_reserved_by != bot_id:
                    # can't use cooker now
                    self.set_task(plan, TaskKind.IDLE, counter)
                    return

                self.set_task(plan, TaskKind.START_COOK, cooker)
                return

            # If already cooked (or non-cookable), add to plate
            # If plate is on counter, we can add_food_to_plate at counter
            self.set_task(plan, TaskKind.ADD_TO_PLATE, counter)
            return

        # If holding plate, just add ingredient from counter/cooker
        if isinstance(holding, Plate):
            self.set_task(plan, TaskKind.ADD_TO_PLATE, counter)
            return

        # If holding something else (pan?), place it
        self.set_task(plan, TaskKind.PLACE_ON_COUNTER, counter)

    # -----------------------------
    # Execute a planned task (action then movement)
    # -----------------------------
    def do_task(self, controller: RobotController, bot_id: int, plan: BotPlan):
        st = controller.get_bot_state(bot_id)
        holding = st.get("holding")
        bx, by = st["x"], st["y"]

        if plan.task == TaskKind.IDLE:
            # If we have a target, wander toward it; else random nudge
            if plan.task_target is not None:
                self.move_towards_adjacent(controller, bot_id, plan.task_target)
            else:
                dx, dy = random.choice([-1, 0, 1]), random.choice([-1, 0, 1])
                if dx == 0 and dy == 0:
                    return
                team = controller.get_team()
                m = controller.get_map(team)
                nx, ny = bx + dx, by + dy
                if 0 <= nx < m.width and 0 <= ny < m.height and m.is_tile_walkable(nx, ny):
                    controller.move(bot_id, dx, dy)
            return

        if plan.task_target is None:
            return

        tx, ty = plan.task_target
        # Need to be adjacent for actions
        adjacent = max(abs(bx - tx), abs(by - ty)) <= 1

        # Movement first if not adjacent
        if not adjacent:
            self.move_towards_adjacent(controller, bot_id, plan.task_target)
            return

        # Adjacent: attempt action
        k = plan.task

        try:
            if k == TaskKind.BUY_PAN:
                if holding is None and get_team_money_safe(controller) >= ShopCosts.PAN.buy_cost:
                    controller.buy(bot_id, ShopCosts.PAN, tx, ty)

            elif k == TaskKind.PLACE_PAN:
                if holding and isinstance(holding, Pan):
                    if controller.place(bot_id, tx, ty):
                        # release reservation after successful placement
                        if self.cooker_reserved_by == bot_id:
                            self.cooker_reserved_by = None

            elif k == TaskKind.BUY_PLATE:
                if holding is None and get_team_money_safe(controller) >= ShopCosts.PLATE.buy_cost:
                    controller.buy(bot_id, ShopCosts.PLATE, tx, ty)

            elif k == TaskKind.PLACE_PLATE_ON_COUNTER:
                if holding and isinstance(holding, Plate):
                    if controller.place(bot_id, tx, ty):
                        plan.has_plate_ready = True

            elif k == TaskKind.BUY_INGREDIENT:
                ft = plan.task_data.get("food")
                if holding is None and ft is not None and get_team_money_safe(controller) >= ft.buy_cost:
                    controller.buy(bot_id, ft, tx, ty)

            elif k == TaskKind.PLACE_ON_COUNTER:
                if holding is not None:
                    controller.place(bot_id, tx, ty)

            elif k == TaskKind.CHOP_ON_COUNTER:
                controller.chop(bot_id, tx, ty)

            elif k == TaskKind.PICKUP_FROM_COUNTER:
                if holding is None:
                    controller.pickup(bot_id, tx, ty)

            elif k == TaskKind.START_COOK:
                # Your engine: placing food on cooker with pan starts cooking automatically
                if holding is not None and isinstance(holding, Food):
                    if controller.place(bot_id, tx, ty):
                        plan.awaiting_cook = True

            elif k == TaskKind.WAIT_COOK:
                # just stand near cooker; no action needed
                pass

            elif k == TaskKind.TAKE_FROM_PAN:
                if holding is None:
                    if controller.take_from_pan(bot_id, tx, ty):
                        plan.awaiting_cook = False
                        # after taking cooked food, release cooker reservation
                        if self.cooker_reserved_by == bot_id:
                            self.cooker_reserved_by = None

            elif k == TaskKind.ADD_TO_PLATE:
                # attempt add_food_to_plate; if success, advance ingredient index if we were working on one
                if controller.add_food_to_plate(bot_id, tx, ty):
                    # If we were adding an ingredient (not in final stage), advance index
                    if plan.idx < len(plan.required):
                        plan.idx += 1
                    # if we were holding cooked food, it’s now on plate

            elif k == TaskKind.PICKUP_PLATE:
                if holding is None:
                    controller.pickup(bot_id, tx, ty)

            elif k == TaskKind.SUBMIT:
                if controller.submit(bot_id, tx, ty):
                    # reset plan after successful submit
                    plan.order_id = None
                    plan.required = []
                    plan.stage = "INIT"
                    plan.idx = 0
                    plan.awaiting_cook = False
                    plan.has_plate_ready = False

            elif k == TaskKind.TRASH:
                controller.trash(bot_id, tx, ty)
                # if trashing due to burnt, reset cook wait + release cooker reservation
                plan.awaiting_cook = False
                if self.cooker_reserved_by == bot_id:
                    self.cooker_reserved_by = None

        except Exception:
            # Fail silently to avoid crashing the bot
            return

        # Special handling: chopping flow
        # If we placed raw choppable food on counter, we should chop then pickup next turn.
        # We'll detect it by seeing food on counter when adjacent and hands empty.
        if plan.task == TaskKind.PLACE_ON_COUNTER:
            # next turn, if choppable ingredient, chop then pickup
            pass

    # -----------------------------
    # Update chopping micro-flow
    # -----------------------------
    def maybe_set_chop_or_pickup(self, controller: RobotController, bot_id: int, plan: BotPlan):
        """
        If current ingredient requires chopping:
          - if food is on our counter and not chopped -> CHOP
          - if food is chopped and we have empty hands -> PICKUP
        """
        if plan.order_id is None or plan.idx >= len(plan.required) or plan.counter is None:
            return

        name = plan.required[plan.idx]
        ft = self.foodtype_from_name(name)
        if ft is None or not self.needs_chop(ft):
            return

        cx, cy = plan.counter
        tile = controller.get_tile(controller.get_team(), cx, cy)
        if not tile:
            return
        item = getattr(tile, "item", None)
        if isinstance(item, Food):
            if not getattr(item, "chopped", False):
                self.set_task(plan, TaskKind.CHOP_ON_COUNTER, plan.counter)
                return
            # chopped -> pick up if hands empty
            st = controller.get_bot_state(bot_id)
            if st.get("holding") is None:
                self.set_task(plan, TaskKind.PICKUP_FROM_COUNTER, plan.counter)
                return

    # -----------------------------
    # Main entry
    # -----------------------------
    def play_turn(self, controller: RobotController):
        if not self.inited:
            self._scan_stations(controller)
            self.inited = True

        bot_ids = get_team_bot_ids_safe(controller)
        if not bot_ids:
            return

        # Ensure we have plans for all bots
        for bid in bot_ids:
            if bid not in self.bot_plans:
                self.bot_plans[bid] = BotPlan()

        # Assign different orders to bots (when possible)
        assignments = self.choose_orders_for_bots(controller, bot_ids)

        for bid in bot_ids:
            plan = self.bot_plans[bid]
            assigned = assignments.get(bid)

            if assigned is None:
                # No order -> clear
                plan.order_id = None
                plan.required = []
            else:
                oid = assigned.get("order_id")
                req = assigned.get("required", []) or []
                # If new order assignment, reset plan
                if plan.order_id != oid:
                    plan.order_id = oid
                    plan.required = [str(x) for x in req]
                    plan.idx = 0
                    plan.awaiting_cook = False
                    plan.has_plate_ready = False

            # Before main planning, handle chopping micro-flow if needed
            self.maybe_set_chop_or_pickup(controller, bid, plan)

            # If we already set a chop/pickup task, execute it; else plan normally
            if plan.task in (TaskKind.CHOP_ON_COUNTER, TaskKind.PICKUP_FROM_COUNTER):
                self.do_task(controller, bid, plan)
                continue

            # Normal planning + execution
            self.plan_next_task(controller, bid, plan)
            self.do_task(controller, bid, plan)
