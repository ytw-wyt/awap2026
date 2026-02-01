import random
from collections import deque
from typing import Tuple, Optional, List

from game_constants import Team, TileType, FoodType, ShopCosts
from robot_controller import RobotController
from item import Pan, Plate, Food



class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        self.assembly_counter = None
        self.cooker_loc = None
        self.shop_loc = None
        self.trash_loc = None

        # NEW: support multiple counters/cookers + detect single-resource maps
        self.counters = []
        self.cookers = []
        self.single_counter = False
        self.single_cooker = False

        # NEW: per-bot independent state machines
        self.bot_state = {}     # bot_id -> int
        self.bot_task = {}      # bot_id -> dict like {"order_id":..., "req_idx":..., "food": FoodType}
        self.bot_wait = {}      # bot_id -> bool (parking)

        # NEW: order tracking and alternating assignment
        self.current_order_id = None
        self.order_required = []
        self.next_req_idx = 0

        # NEW: gating to prevent early collisions
        # Bot1 starts only after Bot0 "clears" some critical steps
        self.gate_allow_bot1 = False

        # NEW: simple resource locks (who is currently using the resource)
        self.lock_shop = None
        self.lock_counter = None
        self.lock_cooker = None

    def _scan_landmarks(self, controller: RobotController, refx: int, refy: int):
        m = controller.get_map(controller.get_team())

        # Cache all counters/cookers once
        if not self.counters:
            for x in range(m.width):
                for y in range(m.height):
                    name = m.tiles[x][y].tile_name
                    if name == "COUNTER":
                        self.counters.append((x, y))
                    elif name == "COOKER":
                        self.cookers.append((x, y))

            self.single_counter = (len(self.counters) <= 1)
            self.single_cooker  = (len(self.cookers) <= 1)

        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, refx, refy, "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, refx, refy, "COOKER")
        if self.shop_loc is None:
            self.shop_loc = self.find_nearest_tile(controller, refx, refy, "SHOP")
        if self.trash_loc is None:
            self.trash_loc = self.find_nearest_tile(controller, refx, refy, "TRASH")


    def _pick_active_order(self, controller: RobotController):
        """Choose the earliest-expiring active order (simple heuristic)."""
        orders = controller.get_orders()
        active = [o for o in orders if o.get("is_active") and o.get("completed_turn") is None]
        if not active:
            return None
        # soonest expiry
        active.sort(key=lambda o: o.get("expires_turn", 10**9))
        return active[0]


    def _parse_required_food(self, req_str: str) -> Optional[FoodType]:
        """Map order required strings to FoodType safely."""
        if not isinstance(req_str, str):
            return None
        s = req_str.strip().upper()

        mapping = {
            "EGG": FoodType.EGG,
            "ONION": FoodType.ONION,
            "MEAT": FoodType.MEAT,
            "NOODLES": FoodType.NOODLES,
            "SAUCE": FoodType.SAUCE,
        }
        return mapping.get(s, None)


    def _cheb(self, ax, ay, bx, by):
        return max(abs(ax - bx), abs(ay - by))


    def _is_resource_busy(self, controller: RobotController, team_bots, target_xy, except_bot=None) -> bool:
        """True if any other bot is adjacent to (or on) the resource interaction zone."""
        tx, ty = target_xy
        for bid in team_bots:
            if bid == except_bot:
                continue
            st = controller.get_bot_state(bid)
            if self._cheb(st["x"], st["y"], tx, ty) <= 1:
                return True
        return False


    def _find_parking_spot(self, controller: RobotController, bot_id: int, avoid_xy: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """Find a nearby walkable tile not adjacent to avoid_xy."""
        st = controller.get_bot_state(bot_id)
        bx, by = st["x"], st["y"]
        ax, ay = avoid_xy
        m = controller.get_map(controller.get_team())

        best = None
        best_d = 10**9
        for x in range(m.width):
            for y in range(m.height):
                if not m.is_tile_walkable(x, y):
                    continue
                # don't stand adjacent to the contested resource
                if self._cheb(x, y, ax, ay) <= 1:
                    continue
                d = self._cheb(bx, by, x, y)
                if d < best_d:
                    best_d = d
                    best = (x, y)
        return best
    def _step_cook_one_item(self, controller: RobotController, bot_id: int, team_bots,
                            food: FoodType, counter_xy: Tuple[int, int], cooker_xy: Tuple[int, int]):
        st = controller.get_bot_state(bot_id)
        bx, by = st["x"], st["y"]
        holding = st.get("holding")

        # Ensure init
        if bot_id not in self.bot_state:
            self.bot_state[bot_id] = 0

        state = self.bot_state[bot_id]

        # ---------- Resource waiting rules ----------
        # If only one counter/cooker, later robot must wait until free
        if self.single_counter and state in [1, 2, 3, 6]:
            if self._is_resource_busy(controller, team_bots, counter_xy, except_bot=bot_id):
                # wait/park
                park = self._find_parking_spot(controller, bot_id, counter_xy)
                if park:
                    self.move_towards(controller, bot_id, park[0], park[1])
                return

        if self.single_cooker and state in [4, 5]:
            if self._is_resource_busy(controller, team_bots, cooker_xy, except_bot=bot_id):
                park = self._find_parking_spot(controller, bot_id, cooker_xy)
                if park:
                    self.move_towards(controller, bot_id, park[0], park[1])
                return

        # ---------- State 0: buy ingredient ----------
        if state == 0:
            sx, sy = self.shop_loc
            if self.move_towards(controller, bot_id, sx, sy):
                # lock shop to reduce collision
                if self.lock_shop is None or self.lock_shop == bot_id:
                    self.lock_shop = bot_id
                    if not holding and controller.get_team_money(controller.get_team()) >= food.buy_cost:
                        ok = controller.buy(bot_id, food, sx, sy)
                        if ok:
                            # gate: once bot0 has successfully bought and left shop, bot1 may start
                            # (we release lock immediately; movement next turn leaves the shop)
                            self.lock_shop = None
                            self.bot_state[bot_id] = 1 if food.choppable else (4 if food.cookable else 6)

        # ---------- State 1: place on counter (for chopping) ----------
        elif state == 1:
            cx, cy = counter_xy
            if self.move_towards(controller, bot_id, cx, cy):
                if self.lock_counter is None or self.lock_counter == bot_id:
                    self.lock_counter = bot_id
                    if holding and controller.place(bot_id, cx, cy):
                        self.lock_counter = None
                        self.bot_state[bot_id] = 2

        # ---------- State 2: chop ----------
        elif state == 2:
            cx, cy = counter_xy
            if self.move_towards(controller, bot_id, cx, cy):
                if self.lock_counter is None or self.lock_counter == bot_id:
                    self.lock_counter = bot_id
                    if controller.chop(bot_id, cx, cy):
                        self.lock_counter = None
                        self.bot_state[bot_id] = 3

        # ---------- State 3: pickup chopped ----------
        elif state == 3:
            cx, cy = counter_xy
            if self.move_towards(controller, bot_id, cx, cy):
                if not holding and controller.pickup(bot_id, cx, cy):
                    self.bot_state[bot_id] = 4 if food.cookable else 6

        # ---------- State 4: place into cooker (start cooking) ----------
        elif state == 4:
            kx, ky = cooker_xy
            if self.move_towards(controller, bot_id, kx, ky):
                if self.lock_cooker is None or self.lock_cooker == bot_id:
                    self.lock_cooker = bot_id
                    # place() starts cooking under your current engine assumption
                    if holding and controller.place(bot_id, kx, ky):
                        self.lock_cooker = None
                        self.bot_state[bot_id] = 5

        # ---------- State 5: wait cooked, take from pan ----------
        elif state == 5:
            kx, ky = cooker_xy
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    f = tile.item.food
                    if f.cooked_stage == 1:
                        if not holding and controller.take_from_pan(bot_id, kx, ky):
                            self.bot_state[bot_id] = 6
                    elif f.cooked_stage == 2:
                        # burnt: take and trash
                        if not holding and controller.take_from_pan(bot_id, kx, ky):
                            self.bot_state[bot_id] = 99  # trash mode

        # ---------- State 6: drop finished ingredient on counter staging ----------
        elif state == 6:
            cx, cy = counter_xy
            if self.move_towards(controller, bot_id, cx, cy):
                if holding and controller.place(bot_id, cx, cy):
                    self.bot_state[bot_id] = 100  # done

        # ---------- State 99: trash ----------
        elif state == 99:
            tx, ty = self.trash_loc
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.bot_state[bot_id] = 0  # restart the ingredient

        # Done state: 100 (do nothing here)
    def play_turn(self, controller: RobotController):
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots:
            return

        # Use bot0 as reference for scanning map landmarks
        b0 = my_bots[0]
        b0s = controller.get_bot_state(b0)
        self._scan_landmarks(controller, b0s["x"], b0s["y"])
        if not self.assembly_counter or not self.cooker_loc or not self.shop_loc or not self.trash_loc:
            return

        # Pick an active order
        order = self._pick_active_order(controller)
        if order is None:
            # no orders: park bots near shop
            sx, sy = self.shop_loc
            for bid in my_bots:
                self.move_towards(controller, bid, sx, sy)
            return

        # If new order, reset assignment cursor
        if self.current_order_id != order["order_id"]:
            self.current_order_id = order["order_id"]
            self.order_required = order.get("required", [])
            self.next_req_idx = 0
            self.bot_task.clear()
            self.bot_state.clear()
            self.gate_allow_bot1 = False

        # Parse required foods
        parsed = []
        for r in self.order_required:
            ft = self._parse_required_food(r)
            if ft is not None:
                parsed.append(ft)

        if not parsed:
            return

        # Requirement (1): alternating assignment
        # bot0 gets idx 0,2,4... ; bot1 gets idx 1,3,5... (and wrap if only one item)
        def desired_idx_for_bot(bot_index: int) -> int:
            if len(parsed) == 1:
                # If only one item, bots alternate across time: next_req_idx drives it
                return self.next_req_idx % 1
            # For multi-item, alternate by index parity
            return bot_index

        # Requirement (2): bot1 only starts after bot0 moved to next step
        # We'll interpret "bot0 left shop after buying ingredient" as:
        # - bot0 has advanced past state 0 for its current ingredient at least once.
        # So: if bot0 state >= 1 at any time, allow bot1.
        if b0 in self.bot_state and self.bot_state[b0] >= 1:
            self.gate_allow_bot1 = True

        # Pick shared counter/cooker (you can later extend to multiple)
        counter_xy = self.assembly_counter
        cooker_xy = self.cooker_loc

        # Assign tasks if a bot is free (no task or done)
        for idx, bid in enumerate(my_bots):
            # gating for bot1
            if idx == 1 and not self.gate_allow_bot1:
                continue

            # if bot has finished (state 100) or has no task, assign next
            if bid not in self.bot_task or self.bot_state.get(bid, 0) == 100:
                # Decide which required item this bot should work on now
                if len(parsed) == 1:
                    # alternate over time: next_req_idx toggles who does it
                    ft = parsed[0]
                else:
                    req_i = idx  # bot0 -> 0, bot1 -> 1
                    if req_i >= len(parsed):
                        # if order has fewer items than bots, fallback to round-robin
                        req_i = self.next_req_idx % len(parsed)
                    ft = parsed[req_i]

                self.bot_task[bid] = {"order_id": self.current_order_id, "food": ft}
                self.bot_state[bid] = 0

                # Advance cursor so after bot finishes, "move on to the next"
                self.next_req_idx += 1

        # Requirement (3): if a bot is blocking another bot's next resource, move aside
        # Simple version: if bot0 needs counter/cooker and bot1 is adjacent to it (or vice versa), park the blocking bot.
        # (This avoids deadlocks on narrow layouts.)
        def maybe_yield(blocker_id, needed_xy):
            if self._is_resource_busy(controller, my_bots, needed_xy, except_bot=None):
                # If blocker is adjacent and other needs it, park blocker
                st = controller.get_bot_state(blocker_id)
                if self._cheb(st["x"], st["y"], needed_xy[0], needed_xy[1]) <= 1:
                    park = self._find_parking_spot(controller, blocker_id, needed_xy)
                    if park:
                        self.move_towards(controller, blocker_id, park[0], park[1])
                        return True
            return False

        # Execute bot0 first (priority), then bot1
        for idx, bid in enumerate(my_bots):
            if idx == 1 and not self.gate_allow_bot1:
                continue

            if bid not in self.bot_task:
                continue

            food = self.bot_task[bid]["food"]

            # Yield logic: if other bot is about to use a resource you are blocking, step away
            # We approximate "next resource" by current state:
            s = self.bot_state.get(bid, 0)
            if s in [1,2,3,6]:
                if maybe_yield(bid, counter_xy):
                    continue
            if s in [4,5]:
                if maybe_yield(bid, cooker_xy):
                    continue

            # Do one step of cooking this ingredient
            self._step_cook_one_item(controller, bid, my_bots, food, counter_xy, cooker_xy)
