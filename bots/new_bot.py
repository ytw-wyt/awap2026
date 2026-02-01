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
        self.my_bot_id = None

        self.state = 0
        self.done = True

        self.tasks_queue = deque()

        self.order = []
        self.order_index = 0

        # multi-station caches
        self.all_counters: List[Tuple[int, int]] = []
        self.all_shops: List[Tuple[int, int]] = []
        self.initialized_multi = False

        # your existing station attrs used by partition_task
        self.shop_pos = None
        self.cooker_pos = None
        self.chop_counter = None
        self.plate_counter = None

    # ----------------------------
    # Find ALL tiles of a type (one-time cache)
    # ----------------------------
    def find_all_tiles(self, controller: RobotController, tile_name: str) -> List[Tuple[int, int]]:
        out = []
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                if m.tiles[x][y].tile_name == tile_name:
                    out.append((x, y))
        return out

    # ----------------------------
    # Orders / tasks
    # ----------------------------
    def get_required_ingrediants(self, controller: RobotController):
        if not self.done:
            return
        orders = controller.get_orders(controller.get_team())
        if not orders or self.order_index >= len(orders):
            return []
        self.order = orders[self.order_index]["required"]  # list[str]
        self.order_index += 1
        self.done = False
        return self.order

    def put_task_in_queue(self, controller: RobotController):
        ingredients = self.get_required_ingrediants(controller)
        if not ingredients:
            return
        l = self.createTaskSequence(ingredients, self.map, controller)
        self.tasks_queue.extend(deque(l))
        self.state = self.tasks_queue.popleft()

    def createTaskSequence(self, currOrder, map, controller: RobotController):
        if "EGG" in currOrder and "MEAT" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["EGG", "MEAT"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian1, houmian1 = self.partition_task(controller, rest)
            newhoumian1 = list(houmian1)
            zhongjian2, houmian2 = self.partition_task(controller, newhoumian1)
            task = (
                [0, 2]
                + self.nameNumberConversion(zhongjian1)
                + [12, 17]
                + self.nameNumberConversion(zhongjian2)
                + [20]
                + self.nameNumberConversion(houmian2)
                + [14]
            )

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
    # Nearest tile (cheap scan)
    # ----------------------------
    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
        best_dist = 9999
        best_pos = None
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == tile_name:
                    dist = max(abs(bot_x - x), abs(bot_y - y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        return best_pos

    def find_nearest_tile_not_current(
        self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str
    ) -> Optional[Tuple[int, int]]:
        best_dist = 9999
        best_pos = None
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                if x == 0 and y == 0:
                    continue
                tile = m.tiles[x][y]
                if tile.tile_name == tile_name:
                    dist = max(abs(bot_x - x), abs(bot_y - y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        return best_pos

    # ----------------------------
    # Multiple shops/counters selection (fast)
    # ----------------------------
    def choose_best_shop(self, controller: RobotController, bot_x: int, bot_y: int) -> Optional[Tuple[int, int]]:
        if not self.all_shops:
            self.all_shops = self.find_all_tiles(controller, "SHOP")
        if not self.all_shops:
            return None
        best = None
        best_d = 10**9
        for sx, sy in self.all_shops:
            d = max(abs(bot_x - sx), abs(bot_y - sy))
            if d < best_d:
                best_d = d
                best = (sx, sy)
        return best

    def init_multi_counters(self, controller: RobotController, bx: int, by: int):
        if self.initialized_multi:
            return

        self.all_counters = self.find_all_tiles(controller, "COUNTER")
        if not self.all_shops:
            self.all_shops = self.find_all_tiles(controller, "SHOP")

        if self.shop_pos is None:
            self.shop_pos = self.choose_best_shop(controller, bx, by)
        if self.shop_pos is None:
            return

        # chop counter: nearest to shop (your original idea)
        self.chop_counter = self.find_nearest_tile(controller, self.shop_pos[0], self.shop_pos[1], "COUNTER")
        if not self.chop_counter:
            return

        # plate counter: prefer a different counter near submit
        submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
        best = None
        if submit_pos is not None:
            ux, uy = submit_pos
            best_d = 10**9
            for c in self.all_counters:
                if c == self.chop_counter:
                    continue
                d = max(abs(c[0] - ux), abs(c[1] - uy))
                if d < best_d:
                    best_d = d
                    best = c

        if best is None:
            best = self.find_nearest_tile_not_current(controller, self.chop_counter[0], self.chop_counter[1], "COUNTER")

        if best is None:
            best = self.chop_counter  # single counter fallback

        self.plate_counter = best

        # keep your later logic happy: assembly_counter is where plates/assembly happen
        self.assembly_counter = self.plate_counter

        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")

        self.initialized_multi = True

    # ----------------------------
    # FAST BFS: returns first step toward becoming adjacent to target
    # ----------------------------
    def get_bfs_first_step_to_adjacent(
        self,
        controller: RobotController,
        start: Tuple[int, int],
        target: Tuple[int, int],
        game_map,
    ) -> Optional[Tuple[int, int]]:
        sx, sy = start
        tx, ty = target
        w, h = self.map.width, self.map.height

        # already adjacent
        if max(abs(sx - tx), abs(sy - ty)) <= 1:
            return (0, 0)

        q = deque([(sx, sy)])
        parent = {(sx, sy): None}

        def is_goal(x, y):
            return max(abs(x - tx), abs(y - ty)) <= 1

        while q:
            x, y = q.popleft()
            if is_goal(x, y):
                # backtrack to find first move from start
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
                    if 0 <= nx < w and 0 <= ny < h and game_map.is_tile_walkable(nx, ny):
                        parent[(nx, ny)] = (x, y)
                        q.append((nx, ny))

        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int, game_map=None) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state["x"], bot_state["y"]

        if max(abs(bx - target_x), abs(by - target_y)) <= 1:
            return True

        if game_map is None:
            game_map = controller.get_map(controller.get_team())

        step = self.get_bfs_first_step_to_adjacent(controller, (bx, by), (target_x, target_y), game_map)
        if step and step != (0, 0):
            controller.move(bot_id, step[0], step[1])
        return False

    # ----------------------------
    # BFS distance (kept, but uses game_map passed in to avoid repeated get_map)
    # ----------------------------
    def get_bfs_distance(self, controller: RobotController, start: Tuple[int, int], target: Tuple[int, int], game_map=None) -> Optional[int]:
        if start == target:
            return 0
        if game_map is None:
            game_map = controller.get_map(controller.get_team())

        w, h = self.map.width, self.map.height
        q = deque([(start, 0)])
        visited = {start}

        while q:
            (x, y), dist = q.popleft()
            if max(abs(x - target[0]), abs(y - target[1])) <= 1:
                return dist
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and game_map.is_tile_walkable(nx, ny):
                        visited.add((nx, ny))
                        q.append(((nx, ny), dist + 1))
        return None

    def partition_task(self, controller: RobotController, tasks) -> Tuple[set[str], set[str]]:
        if tasks == []:
            return (set(), set())

        # NOTE: relies on self.shop_pos / self.plate_counter / self.chop_counter / self.cooker_loc
        game_map = controller.get_map(controller.get_team())

        cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos, game_map)
        shop_to_plate = self.get_bfs_distance(controller, self.shop_pos, self.plate_counter, game_map)
        plate_to_cooker = self.get_bfs_distance(controller, self.plate_counter, self.cooker_loc, game_map)

        T = cooker_to_shop + shop_to_plate + plate_to_cooker

        shop_to_chop = self.get_bfs_distance(controller, self.shop_pos, self.chop_counter, game_map)
        chop_to_plate = self.get_bfs_distance(controller, self.chop_counter, self.plate_counter, game_map)
        plate_to_shop = self.get_bfs_distance(controller, self.plate_counter, self.shop_pos, game_map)

        tasks = set(tasks)

        # (UNCHANGED) your original branching logic below
        if "PLATE" in tasks:
            if T > 37:
                return (set(), tasks)
            else:
                if tasks == {"PLATE"}:
                    return (tasks, set())
                else:
                    if tasks == {"PLATE", "SAUCE"} or tasks == {"PLATE", "NOODLES"}:
                        comb_T = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                        if comb_T > 37:
                            return ({"PLATE"}, tasks - {"PLATE"})
                        else:
                            return (tasks, set())
                    elif tasks == {"PLATE", "ONIONS"}:
                        comb_T = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                        if comb_T > 37:
                            return ({"PLATE"}, tasks - {"PLATE"})
                        else:
                            return (tasks, set())
                    elif tasks == {"PLATE", "NOODLES", "SAUCE"}:
                        two_T = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                        three_T = two_T + plate_to_shop + shop_to_plate
                        if two_T > 37:
                            return ({"PLATE"}, tasks - {"PLATE"})
                        else:
                            if three_T > 37:
                                return ({"PLATE", "NOODLES"}, {"SAUCE"})
                            else:
                                return (tasks, set())
                    elif tasks == {"PLATE", "NOODLES", "ONIONS", "SAUCE"}:
                        plate_onion = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                        plate_with_one = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                        plate_onion_with_one = (
                            cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                        )

                        if plate_onion > 37 and plate_with_one > 37:
                            return ({"PLATE"}, tasks - {"PLATE"})
                        else:
                            if plate_onion <= 37 and plate_with_one > 37:
                                return ({"PLATE", "ONIONS"}, tasks - {"PLATE", "ONIONS"})
                            elif plate_with_one <= 37 and plate_onion > 37:
                                return ({"PLATE", "NOODLES"}, tasks - {"PLATE", "NOODLES"})
                            else:
                                return ({"PLATE", "NOODLES", "ONIONS"}, {"SAUCE"})
                    else:
                        return (tasks, set())
        else:
            if tasks == {"NOODLES"} or tasks == {"SAUCE"}:
                t = cooker_to_shop + shop_to_plate + plate_to_cooker
                if t > 37:
                    return (set(), tasks)
                else:
                    return (tasks, set())
            elif tasks == {"ONIONS"}:
                t = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                if t > 37:
                    return (set(), tasks)
                else:
                    return (tasks, set())
            elif tasks == {"NOODLES", "SAUCE"}:
                t = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"NOODLES"}, {"SAUCE"})
                else:
                    return (tasks, set())
            elif tasks == {"NOODLES", "ONIONS"}:
                t = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"NOODLES"}, {"ONIONS"})
                else:
                    return (tasks, set())
            elif tasks == {"ONIONS", "SAUCE"}:
                t = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"SAUCE"}, {"ONIONS"})
                else:
                    return (tasks, set())
            elif tasks == {"NOODLES", "ONIONS", "SAUCE"}:
                onion = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                any_one = cooker_to_shop + shop_to_plate + plate_to_cooker
                any_two = any_one + plate_to_shop + shop_to_plate
                onion_with_one = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                onion_with_two = onion_with_one + plate_to_shop + shop_to_plate

                if any_one > 37:
                    return (set(), tasks)
                else:
                    if onion_with_two <= 37:
                        return (tasks, set())
                    elif onion_with_one <= 37:
                        return ({"ONIONS", "NOODLES"}, {"SAUCE"})
                    elif any_two <= 37:
                        return ({"NOODLES", "SAUCE"}, {"ONIONS"})
                    elif onion <= 37:
                        return ({"ONIONS"}, {"NOODLES", "SAUCE"})
                    else:
                        return ({"NOODLES"}, {"ONIONS", "SAUCE"})
            else:
                return (tasks, set())

    # ----------------------------
    # Main loop
    # ----------------------------
    def play_turn(self, controller: RobotController):
        team = controller.get_team()
        game_map = controller.get_map(team)

        my_bots = controller.get_team_bot_ids(team)
        if not my_bots:
            return

        # bot0 is chef
        bot_id = my_bots[0]
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info["x"], bot_info["y"]

        # init multi stations once
        if self.shop_pos is None:
            self.shop_pos = self.choose_best_shop(controller, bx, by)
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        self.init_multi_counters(controller, bx, by)

        # fill tasks if empty
        if len(self.tasks_queue) == 0:
            if not self.shop_pos or not self.cooker_loc:
                return
            self.put_task_in_queue(controller)

        if self.assembly_counter is None:
            self.assembly_counter = self.plate_counter or self.find_nearest_tile(controller, bx, by, "COUNTER")

        if not self.assembly_counter or not self.cooker_loc:
            return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc

        if self.state in [2, 8, 10] and bot_info.get("holding"):
            self.state = 16

        # state 0: init + checking the pan
        if self.state == 0:
            tile = controller.get_tile(team, kx, ky)
            if tile and isinstance(tile.item, Pan):
                self.state = self.tasks_queue.popleft()
            else:
                self.state = 1

        # state 1: buy pan
        elif self.state == 1:
            holding = bot_info.get("holding")
            if holding:
                if self.move_towards(controller, bot_id, kx, ky, game_map):
                    if controller.place(bot_id, kx, ky):
                        self.state = self.tasks_queue.popleft()
            else:
                shop_pos = self.choose_best_shop(controller, bx, by)
                if not shop_pos:
                    return
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy, game_map):
                    if controller.get_team_money(team) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        # state 2: buy meat
        elif self.state == 2:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= FoodType.MEAT.buy_cost:
                    if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                        self.state = 3

        # state 3: put meat on counter (use chop_counter)
        elif self.state == 3:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.place(bot_id, tx, ty):
                    self.state = 4

        # state 4: chop meat
        elif self.state == 4:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.chop(bot_id, tx, ty):
                    self.state = 5

        # state 5: pickup meat
        elif self.state == 5:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.pickup(bot_id, tx, ty):
                    self.state = 6

        # state 6: put meat on cooker
        elif self.state == 6:
            if self.move_towards(controller, bot_id, kx, ky, game_map):
                if controller.place(bot_id, kx, ky):
                    self.state = self.tasks_queue.popleft()

        # state 8: buy the plate
        elif self.state == 8:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        # state 9: put the plate on the counter (plate_counter)
        elif self.state == 9:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.place(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # state 10: buy noodles
        elif self.state == 10:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.state = 11

        # state 11: add noodles to plate
        elif self.state == 11:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.add_food_to_plate(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # state 12: wait and take meat
        elif self.state == 12:
            if self.move_towards(controller, bot_id, kx, ky, game_map):
                tile = controller.get_tile(team, kx, ky)
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

        # state 13: add meat to plate
        elif self.state == 13:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.add_food_to_plate(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # state 14: pick up the plate
        elif self.state == 14:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.pickup(bot_id, tx, ty):
                    self.state = 15

        # state 15: submit
        elif self.state == 15:
            submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
            if not submit_pos:
                return
            ux, uy = submit_pos
            if self.move_towards(controller, bot_id, ux, uy, game_map):
                if controller.submit(bot_id, ux, uy):
                    self.done = True
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        # state 16: trash
        elif self.state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos:
                return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2

        # state 17: buy egg
        elif self.state == 17:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= FoodType.EGG.buy_cost:
                    if controller.buy(bot_id, FoodType.EGG, sx, sy):
                        self.state = 18

        # state 18: put egg on cooker
        elif self.state == 18:
            if self.move_towards(controller, bot_id, kx, ky, game_map):
                if controller.place(bot_id, kx, ky):
                    self.state = self.tasks_queue.popleft()

        # state 20: wait and take egg
        elif self.state == 20:
            if self.move_towards(controller, bot_id, kx, ky, game_map):
                tile = controller.get_tile(team, kx, ky)
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

        # state 21: add egg to plate
        elif self.state == 21:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.add_food_to_plate(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # state 22: buy onion
        elif self.state == 22:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= FoodType.ONIONS.buy_cost:
                    if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                        self.state = 23

        # state 23: put onion on counter
        elif self.state == 23:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.place(bot_id, tx, ty):
                    self.state = 24

        # state 24: chop onion
        elif self.state == 24:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.chop(bot_id, tx, ty):
                    self.state = 25

        # state 25: pickup onion
        elif self.state == 25:
            tx, ty = self.chop_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.pickup(bot_id, tx, ty):
                    self.state = 26

        # state 26: add onion to plate
        elif self.state == 26:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.add_food_to_plate(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # state 27: buy sauce
        elif self.state == 27:
            shop_pos = self.choose_best_shop(controller, bx, by)
            if not shop_pos:
                return
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy, game_map):
                if controller.get_team_money(team) >= FoodType.SAUCE.buy_cost:
                    if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                        self.state = 28

        # state 28: add sauce to plate
        elif self.state == 28:
            tx, ty = self.plate_counter or (cx, cy)
            if self.move_towards(controller, bot_id, tx, ty, game_map):
                if controller.add_food_to_plate(bot_id, tx, ty):
                    self.state = self.tasks_queue.popleft()

        # other bots: random walk (unchanged)
        for i in range(1, len(my_bots)):
            bot_id2 = my_bots[i]
            b2 = controller.get_bot_state(bot_id2)
            x2, y2 = b2["x"], b2["y"]
            dx = random.choice([-1, 1])
            dy = random.choice([-1, 1])
            nx, ny = x2 + dx, y2 + dy
            if 0 <= nx < game_map.width and 0 <= ny < game_map.height and game_map.is_tile_walkable(nx, ny):
                controller.move(bot_id2, dx, dy)
                return
