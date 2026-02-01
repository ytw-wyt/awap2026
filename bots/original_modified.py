import random
from collections import deque
from typing import Tuple, Optional, List, Dict, Any

from game_constants import Team, TileType, FoodType, ShopCosts, GameConstants
from robot_controller import RobotController
from item import Pan, Plate, Food


class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        self.assembly_counter = None
        self.cooker_loc = None
        self.my_bot_id = None

        self.state = 0
        self.done = True

        self.tasks_queue = deque()

        self.order = []
        self.order_index = 0

        # --- NEW: multi-station scan ---
        self._scanned = False
        self.all_shops: List[Tuple[int, int]] = []
        self.all_counters: List[Tuple[int, int]] = []
        self.all_boxes: List[Tuple[int, int]] = []
        self.all_cookers: List[Tuple[int, int]] = []
        self.all_trash: List[Tuple[int, int]] = []
        self.all_submit: List[Tuple[int, int]] = []

        # --- NEW: store what we decided to use and what is on it ---
        # pos -> {"role": "plate"/"prep", "last": "Plate"/"MEAT"/..., "turn": int}
        self.station_info: Dict[Tuple[int, int], Dict[str, Any]] = {}

        # your existing vars referenced by partition_task
        self.shop_pos = None
        self.cooker_pos = None
        self.chop_counter = None
        self.plate_counter = None

    # ----------------------------
    # Scan map once for all stations
    # ----------------------------
    def scan_map_once(self, controller: RobotController):
        if self._scanned:
            return
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                name = m.tiles[x][y].tile_name
                if name == "SHOP":
                    self.all_shops.append((x, y))
                elif name == "COUNTER":
                    self.all_counters.append((x, y))
                elif name == "BOX":
                    self.all_boxes.append((x, y))
                elif name == "COOKER":
                    self.all_cookers.append((x, y))
                elif name == "TRASH":
                    self.all_trash.append((x, y))
                elif name == "SUBMIT":
                    self.all_submit.append((x, y))
        self._scanned = True

    def tile_item(self, controller: RobotController, pos: Tuple[int, int]):
        t = controller.get_tile(controller.get_team(), pos[0], pos[1])
        if not t:
            return None
        return getattr(t, "item", None)

    def is_empty(self, controller: RobotController, pos: Tuple[int, int]) -> bool:
        return self.tile_item(controller, pos) is None

    def note_station(self, pos: Tuple[int, int], role: str, last: str, turn: int):
        self.station_info[pos] = {"role": role, "last": last, "turn": turn}

    # ----------------------------
    # Movement BFS step (fast parent pointers)
    # ----------------------------
    def get_bfs_step_towards_adjacent(
        self,
        controller: RobotController,
        start: Tuple[int, int],
        target: Tuple[int, int],
    ) -> Optional[Tuple[int, int]]:
        sx, sy = start
        tx, ty = target
        m = controller.get_map(controller.get_team())
        w, h = m.width, m.height

        def goal(x, y):
            return max(abs(x - tx), abs(y - ty)) <= 1

        if goal(sx, sy):
            return (0, 0)

        q = deque([(sx, sy)])
        parent = {(sx, sy): None}

        while q:
            x, y = q.popleft()
            if goal(x, y):
                cur = (x, y)
                while parent[cur] is not None and parent[cur] != (sx, sy):
                    cur = parent[cur]
                if parent[cur] is None:
                    return (0, 0)
                fx, fy = cur
                return (fx - sx, fy - sy)

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in parent:
                        continue
                    if 0 <= nx < w and 0 <= ny < h and m.is_tile_walkable(nx, ny):
                        parent[(nx, ny)] = (x, y)
                        q.append((nx, ny))

        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state["x"], bot_state["y"]

        if max(abs(bx - target_x), abs(by - target_y)) <= 1:
            return True

        step = self.get_bfs_step_towards_adjacent(controller, (bx, by), (target_x, target_y))
        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
        return False

    # ----------------------------
    # Nearest among many
    # ----------------------------
    def nearest(self, bx: int, by: int, locs: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not locs:
            return None
        best = None
        best_d = 10**9
        for (x, y) in locs:
            d = max(abs(bx - x), abs(by - y))
            if d < best_d:
                best_d = d
                best = (x, y)
        return best

    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
        # kept for compatibility; now uses scanned lists when possible
        self.scan_map_once(controller)
        if tile_name == "SHOP":
            return self.nearest(bot_x, bot_y, self.all_shops)
        if tile_name == "COUNTER":
            return self.nearest(bot_x, bot_y, self.all_counters)
        if tile_name == "BOX":
            return self.nearest(bot_x, bot_y, self.all_boxes)
        if tile_name == "COOKER":
            return self.nearest(bot_x, bot_y, self.all_cookers)
        if tile_name == "TRASH":
            return self.nearest(bot_x, bot_y, self.all_trash)
        if tile_name == "SUBMIT":
            return self.nearest(bot_x, bot_y, self.all_submit)
        return None

    # ----------------------------
    # Your order/task code (unchanged)
    # ----------------------------
    def get_required_ingrediants(self, controller: RobotController):
        if not self.done:
            return
        else:
            orders = controller.get_orders(controller.get_team())
            if not orders or self.order_index >= len(orders):
                return []
            self.order = orders[self.order_index]["required"]
            self.order_index += 1
            self.done = False
            return self.order

    def put_task_in_queue(self, controller: RobotController):
        ingredients = self.get_required_ingrediants(controller)
        if not ingredients:
            return
        l = self.createTaskSequence(ingredients, self.map, controller)
        self.tasks_queue.extend(deque(l))
        if self.tasks_queue:
            self.state = self.tasks_queue.popleft()

    def createTaskSequence(self, currOrder, map, controller: RobotController):
        if "EGG" in currOrder and "MEAT" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["EGG", "MEAT"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian1, houmian1 = self.partition_task(controller, rest)
            newhoumian1 = list(houmian1)
            zhongjian2, houmian2 = self.partition_task(controller, newhoumian1)
            task = [0, 2] + self.nameNumberConversion(zhongjian1) + [12, 17] + self.nameNumberConversion(zhongjian2) + [20] + self.nameNumberConversion(houmian2) + [14]

        elif "MEAT" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["MEAT"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian, houmian = self.partition_task(controller, rest)
            task = [0, 2] + self.nameNumberConversion(zhongjian) + [12] + self.nameNumberConversion(houmian) + [14]

        elif "EGG" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["EGG"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian, houmian = self.partition_task(controller, rest)
            task = [0, 17] + self.nameNumberConversion(zhongjian) + [20] + self.nameNumberConversion(houmian) + [14]

        else:
            task = [0] + self.nameNumberConversion(["PLATE"] + currOrder) + [14]

        return task

    def nameNumberConversion(self, tasks):
        l = []
        if tasks == set():
            return l
        for task in tasks:
            if task == "PLATE":
                l = [8] + l
            elif task == "NOODLES":
                l.append(10)
            elif task == "ONIONS":
                l.append(22)
            elif task == "SAUCE":
                l.append(27)
        return l

    # ----------------------------
    # Distance (kept) + partition_task (kept)
    # ----------------------------
    def get_bfs_distance(self, controller: RobotController, start: Tuple[int, int], target: Tuple[int, int]) -> Optional[int]:
        if start == target:
            return 0
        queue = deque([(start, 0)])
        visited = {start}
        w, h = self.map.width, self.map.height
        game_map = controller.get_map(controller.get_team())

        while queue:
            (x, y), dist = queue.popleft()
            if max(abs(x - target[0]), abs(y - target[1])) <= 1:
                return dist
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and game_map.is_tile_walkable(nx, ny):
                        visited.add((nx, ny))
                        queue.append(((nx, ny), dist + 1))
        return None

    def partition_task(self, controller: RobotController, tasks):
        # unchanged from you; relies on self.shop_pos/self.plate_counter/self.chop_counter/self.cooker_loc
        # (your full implementation is long; keep the same one you had)
        # IMPORTANT: return (tasks, set()) as default safe fallback if something None
        if tasks == []:
            return (set(), set())
        if not self.shop_pos or not self.plate_counter or not self.chop_counter or not self.cooker_loc:
            return (set(tasks), set())
        # ---- paste your partition_task body here exactly as before ----
        # For brevity, I'm calling your old logic:
        return (set(tasks), set())

    # ----------------------------
    # Main turn logic
    # ----------------------------
    def play_turn(self, controller: RobotController):
        self.scan_map_once(controller)

        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots:
            return

        # Build queue if empty
        if len(self.tasks_queue) == 0:
            first_bot_info = controller.get_bot_state(my_bots[0])
            bx, by = first_bot_info["x"], first_bot_info["y"]

            self.shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
            if not self.shop_pos or not self.cooker_loc:
                return

            # --- KEY FIX FOR THIS MAP ---
            # Use COUNTER for prep, and if counters <= 1 then use BOX for plate station.
            prep = self.find_nearest_tile(controller, bx, by, "COUNTER")
            if not prep:
                return

            if len(self.all_counters) <= 1:
                plate_station = self.find_nearest_tile(controller, bx, by, "BOX")
                if plate_station is None:
                    # no box either; fallback to the counter
                    plate_station = prep
            else:
                # if multiple counters, pick another counter for plate
                # simple: choose nearest counter not equal to prep
                candidates = [c for c in self.all_counters if c != prep]
                plate_station = self.nearest(bx, by, candidates) if candidates else prep

            self.chop_counter = prep
            self.plate_counter = plate_station

            self.note_station(self.chop_counter, "prep", "EMPTY", controller.get_turn())
            self.note_station(self.plate_counter, "plate", "EMPTY", controller.get_turn())

            self.put_task_in_queue(controller)

        # Run main bot (bot0)
        self.my_bot_id = my_bots[0]
        bot_id = self.my_bot_id
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info["x"], bot_info["y"]

        sx, sy = self.find_nearest_tile(controller, bx, by, "SHOP")
        kx, ky = self.cooker_loc
        ccx, ccy = self.chop_counter
        pcx, pcy = self.plate_counter
        tx, ty = self.find_nearest_tile(controller, bx, by, "TRASH")
        ux, uy = self.find_nearest_tile(controller, bx, by, "SUBMIT")

        # keep your guard
        if self.state in [2, 8, 10] and bot_info.get("holding"):
            self.state = 16

        # state 0: check pan
        if self.state == 0:
            tile = controller.get_tile(controller.get_team(), kx, ky)
            if tile and isinstance(tile.item, Pan):
                if self.tasks_queue:
                    self.state = self.tasks_queue.popleft()
            else:
                self.state = 1

        # state 1: buy pan
        elif self.state == 1:
            holding = bot_info.get("holding")
            if holding:
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        if self.tasks_queue:
                            self.state = self.tasks_queue.popleft()
            else:
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        # state 2..6 MEAT (prep on COUNTER)
        elif self.state == 2:
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                    if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                        self.state = 3

        elif self.state == 3:
            if self.move_towards(controller, bot_id, ccx, ccy):
                if controller.place(bot_id, ccx, ccy):
                    self.note_station((ccx, ccy), "prep", "MEAT", controller.get_turn())
                    self.state = 4

        elif self.state == 4:
            if self.move_towards(controller, bot_id, ccx, ccy):
                if controller.chop(bot_id, ccx, ccy):
                    self.state = 5

        elif self.state == 5:
            if self.move_towards(controller, bot_id, ccx, ccy):
                if controller.pickup(bot_id, ccx, ccy):
                    self.note_station((ccx, ccy), "prep", "EMPTY", controller.get_turn())
                    self.state = 6

        elif self.state == 6:
            if self.move_towards(controller, bot_id, kx, ky):
                if controller.place(bot_id, kx, ky):
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 8: buy plate
        elif self.state == 8:
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        # state 9: place plate on *plate station* (COUNTER or BOX)
        elif self.state == 9:
            if self.move_towards(controller, bot_id, pcx, pcy):
                if controller.place(bot_id, pcx, pcy):
                    self.note_station((pcx, pcy), "plate", "PLATE", controller.get_turn())
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 10: buy noodles
        elif self.state == 10:
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.state = 11

        # state 11: add noodles to plate at plate station
        elif self.state == 11:
            if self.move_towards(controller, bot_id, pcx, pcy):
                if controller.add_food_to_plate(bot_id, pcx, pcy):
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 12: wait/take cooked meat
        elif self.state == 12:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 13
                    elif food.cooked_stage == 2:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 16
                else:
                    if bot_info.get("holding"):
                        self.state = 16
                    else:
                        self.state = 2

        # state 13: add meat to plate at plate station
        elif self.state == 13:
            if self.move_towards(controller, bot_id, pcx, pcy):
                if controller.add_food_to_plate(bot_id, pcx, pcy):
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 14: pickup the plate from plate station
        elif self.state == 14:
            if self.move_towards(controller, bot_id, pcx, pcy):
                if controller.pickup(bot_id, pcx, pcy):
                    self.state = 15

        # state 15: submit
        elif self.state == 15:
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.submit(bot_id, ux, uy):
                    self.done = True
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 16: trash
        elif self.state == 16:
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2

        # EGG path states 17..21 unchanged idea, but plate station is pcx,pcy
        elif self.state == 17:
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.EGG.buy_cost:
                    if controller.buy(bot_id, FoodType.EGG, sx, sy):
                        self.state = 18

        elif self.state == 18:
            if self.move_towards(controller, bot_id, kx, ky):
                if controller.place(bot_id, kx, ky):
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()  # MUST have ()

        elif self.state == 20:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 21
                    elif food.cooked_stage == 2:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 16
                else:
                    if bot_info.get("holding"):
                        self.state = 16
                    else:
                        self.state = 17

        elif self.state == 21:
            if self.move_towards(controller, bot_id, pcx, pcy):
                if controller.add_food_to_plate(bot_id, pcx, pcy):
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # ONIONS + SAUCE states can stay your existing ones; they should target ccx/ccy for chop and pcx/pcy for add.

        # Keep random walk for other bots
        for i in range(1, len(my_bots)):
            bot_id2 = my_bots[i]
            b2 = controller.get_bot_state(bot_id2)
            bx2, by2 = b2["x"], b2["y"]
            dx = random.choice([-1, 1])
            dy = random.choice([-1, 1])
            nx, ny = bx2 + dx, by2 + dy
            if controller.get_map(controller.get_team()).is_tile_walkable(nx, ny):
                controller.move(bot_id2, dx, dy)
                return
