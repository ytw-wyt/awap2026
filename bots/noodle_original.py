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
        

        self.shop_pos = self.find_nearest_tile(RobotController, 0, 0, "SHOP")
        self.cooker_pos = self.find_nearest_tile(RobotController, 0, 0, "COOKER")

        self.chop_counter = self.find_nearest_tile(RobotController, self.shop_pos(0), self.shop_pos(1), "COUNTER")
        self.plate_counter = self.find_nearest_tile_not_current(RobotController, self.chop_counter(0), self.chop_counter(1), "COUNTER")
        if self.plate_counter == None: 
            self.plate_counter = self.chop_counter #ERROR: 1 counter only
        

        self.state = 0
    
        self.tasks_queue = deque()

        self.order = None
        self.order_index = 0

    # get list of ingredients for current order
    def get_required_ingrediants(self):
        orders = self.get_orders()  
        neworder = orders[self.order_index]["required"] # list[foodtype]
        for i in neworder:
            self.order.append(i.food_name)

        self.order_index += 1

    def put_task_in_queue(self):
        l = self.createTaskSequence(self.get_required_ingrediants(), self.map)
        self.tasks_queue.extend(deque(l))
        self.state = self.tasks_queue.popleft()

    def createTaskSequence(self, currOrder, map):
        if "EGG" in currOrder and "MEAT" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["EGG", "MEAT"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian1, houmian1 = self.partition_task(rest)
            zhongjian2, houmian2 = self.partition_task(rest)
            task = [0, 2] + self.nameNumberConversion(zhongjian1) + [12, 17] + self.nameNumberConversion(zhongjian2) + [20] + self.nameNumberConversion(houmian2) + [14]
        
        elif "MEAT" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["MEAT"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian, houmian = self.partition_task(rest)
            task = [0, 2] + self.nameNumberConversion(zhongjian) + [12] + self.nameNumberConversion(houmian) + [14]

        elif "EGG" in currOrder:
            currOrder_copy = [item for item in currOrder if item not in ["EGG"]]
            rest = currOrder_copy + ["PLATE"]
            zhongjian, houmian = self.partition_task(rest)
            task = [0, 17] + self.nameNumberConversion(zhongjian) + [20] + self.nameNumberConversion(houmian) + [14]

        else:
            task = [0, 2] + list(currOrder) + [14]
        
        return task
    
    def nameNumberConversion(self, tasks):
        l = []
        for task in tasks:
            if task == "PLATE":
                l.append(8)
            elif task == "NOODLES":
                l.append(10)
            elif task == "ONIONS":
                l.append(22)
            elif task == "SAUCE":
                l.append(27)
        return l

    def find_nearest_tile_not_current(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
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


    def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], target_predicate) -> Optional[Tuple[int, int]]:
        queue = deque([(start, [])]) 
        visited = set([start])
        w, h = self.map.width, self.map.height

        while queue:
            (curr_x, curr_y), path = queue.popleft()
            tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
            if target_predicate(curr_x, curr_y, tile):
                if not path: return (0, 0) 
                return path[0] 

            for dx in [0, -1, 1]:
                for dy in [0, -1, 1]:
                    if dx == 0 and dy == 0: continue
                    nx, ny = curr_x + dx, curr_y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if controller.get_map(controller.get_team()).is_tile_walkable(nx, ny):
                            visited.add((nx, ny))
                            queue.append(((nx, ny), path + [(dx, dy)]))
        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        def is_adjacent_to_target(x, y, tile):
            return max(abs(x - target_x), abs(y - target_y)) <= 1
        if is_adjacent_to_target(bx, by, None): return True
        step = self.get_bfs_path(controller, (bx, by), is_adjacent_to_target)
        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
            return False 
        return False 

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
    
     # Estimate the distance between two points using BFS
    def get_bfs_distance(
        self,
        controller: RobotController,
        start: Tuple[int, int],
        target: Tuple[int, int],
    ) -> Optional[int]:


        if start == target:
            return 0


        queue = deque([(start, 0)])
        visited = {start}
        w, h = self.map.width, self.map.height
        game_map = controller.get_map(controller.get_team())


        while queue:
            (x, y), dist = queue.popleft()


            # If current position is adjacent to the target (chebyshev distance ≤ 1),
            # we can consider the target "reached" for the purposes of station interaction.
            # This lets callers ask the distance to a COUNTER/COOKER (non-walkable tile).
            if max(abs(x - target[0]), abs(y - target[1])) <= 1:
                return dist


            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue


                    nx, ny = x + dx, y + dy


                    if (
                        0 <= nx < w
                        and 0 <= ny < h
                        and (nx, ny) not in visited
                        and game_map.is_tile_walkable(nx, ny)
                    ):
                        visited.add((nx, ny))
                        queue.append(((nx, ny), dist + 1))


        return None




    def partition_task(self, controller: RobotController, tasks) -> Tuple[set[str], set[str]]:
        cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos)
        shop_to_plate = self.get_bfs_distance(controller, self.shop_pos, self.plate_counter)
        plate_to_cooker = self.get_bfs_distance(controller, self.plate_counter, self.cooker_loc)


        T = cooker_to_shop + shop_to_plate + plate_to_cooker


        shop_to_chop = self.get_bfs_distance(controller, self.shop_pos, self.chop_counter)
        chop_to_plate = self.get_bfs_distance(controller, self.chop_counter, self.plate_counter)
        plate_to_shop = self.get_bfs_distance(controller, self.plate_counter, self.shop_pos)


        tasks = set(tasks)


        if T > 37:
            return (set(), tasks)
        else:
            if tasks == {"PLATE"}:
                return (tasks, set())
            else:
                if tasks == {'PLATE', 'SAUCE'} or tasks == {'PLATE', 'NOODLES'}:
                    comb_T = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                    if comb_T > 37:
                        return ({"PLATE"}, tasks - {"PLATE"})
                    else:
                        return (tasks, set())
                elif tasks == {'PLATE', 'ONIONS'}:
                    comb_T = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                    if comb_T > 37:
                        return ({"PLATE"}, tasks - {"PLATE"})
                    else:
                        return (tasks, set())
                elif tasks == {'PLATE', 'NOODLES', 'SAUCE'}:
                    two_T = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                    three_T = two_T + plate_to_shop + shop_to_plate
                    if two_T > 37:
                        return ({"PLATE"}, tasks - {"PLATE"})
                    else:
                        if three_T > 37:
                            return ({"PLATE", "NOODLES"}, {"SAUCE"})
                        else:
                            return (tasks, set())
                    
                        return (tasks, set())
                elif tasks == {'PLATE', 'NOODLES', 'ONIONS', 'SAUCE'}:
                    plate_onion  = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                    plate_with_one = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                    plate_onion_with_one = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                    plate_with_two = plate_with_one + plate_to_shop + shop_to_plate
                    plate_with_three = plate_onion_with_one + plate_to_shop


                    if plate_onion > 37 and plate_with_one > 37:
                        return ({"PLATE"}, tasks - {"PLATE"})
                    else:
                        if plate_onion <= 37 and plate_with_one > 37:
                            return ({"PLATE", "ONIONS"}, tasks - {"PLATE", "ONIONS"})
                        elif plate_with_one <= 37 and plate_onion > 37:
                            return ({"PLATE", "NOODLES"}, tasks - {"PLATE", "NOODLES"})
                        # plate_with_one <= 37 and plate_onion <= 37:
                        else:
                            return ({"PLATE", "NOODLES", "ONIONS"}, {"SAUCE"})


    def play_turn(self, controller: RobotController):
        if self.tasks_queue.empty():
            self.put_task_in_queue()

        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots: return
    
        self.my_bot_id = my_bots[0]
        bot_id = self.my_bot_id
        
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']

        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")

        if not self.assembly_counter or not self.cooker_loc: return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc

        if self.state in [2, 8, 10] and bot_info.get('holding'):
            self.state = 16

        #state 0: init + checking the pan
        if self.state == 0:
            tile = controller.get_tile(controller.get_team(), kx, ky)
            if tile and isinstance(tile.item, Pan):
                self.state = 2
            else:
                self.state = 1

        #state 1: buy pan
        elif self.state == 1:
            holding = bot_info.get('holding')
            if holding: # assume it's the pan
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        self.state = self.tasks_queue.popleft()
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos: return
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        #state 2: buy meat
        elif self.state == 2:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                    if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                        self.state = 3

        #state 3: put meat on counter
        elif self.state == 3:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = 4

        #state 4: chop meat
        elif self.state == 4:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state = 5

        #state 5: pickup meat
        elif self.state == 5:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 6

        #state 6: put meat on cooker
        elif self.state == 6:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    self.state = self.tasks_queue.popleft()

        #state 7: start the cook, but is cooking so we just go
        elif self.state == 7:
            self.state = 8

        #state 8: buy the plate
        elif self.state == 8:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        #state 9: put the plate on the counter
        elif self.state == 9:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = self.tasks_queue.popleft()

        #state 10: buy noodle
        elif self.state == 10:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.state = 11

        #state 11: add noodles to plate
        elif self.state == 11:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    self.state = self.tasks_queue.popleft()

        #state 12: wait and take meat
        elif self.state == 12:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 13
                    elif food.cooked_stage == 2:

                        #trash
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 16 
                else:
                    if bot_info.get('holding'):
                        #trash
                        self.state = 16
                    else:
                        #restart
                        self.state = 2 

        #state 13: add meat to plate
        elif self.state == 13:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    self.state = 14

        #state 14: pick up the plate
        elif self.state == 14:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 15

        #state 15: submit
        elif self.state == 15:
            submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
            ux, uy = submit_pos
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.submit(bot_id, ux, uy):
                    self.state = self.tasks_queue.popleft()

        #state 16: trash
        elif self.state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2 #restart
        
        #state 17: buy egg
        elif self.state == 17:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.EGG.buy_cost:
                    if controller.buy(bot_id, FoodType.EGG, sx, sy):
                        self.state = 18

        #state 18: put egg on cooker
        elif self.state == 18:
                if self.move_towards(controller, bot_id, kx, ky):
                    # Using the NEW logic where place() starts cooking automatically
                    if controller.place(bot_id, kx, ky):
                        self.state = self.tasks_queue.popleft()


        #state 19: start the cook egg, but is cooking so we just go
        elif self.state == 19:
            self.state = 20


        #state 20: wait and take egg
        elif self.state == 20:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 21
                    elif food.cooked_stage == 2:
                        #trash
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 16
                else:
                    if bot_info.get('holding'):
                        #trash
                        self.state = 16
                    else:
                        #restart
                        self.state = 17


        #state 21: add egg to plate
        elif self.state == 21:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # self.state = 14
                    self.state = self.tasks_queue.popleft()

        #state 22: buy onion
        elif self.state == 22:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.ONION.buy_cost:
                    if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                        self.state = 23
        
        #state 23: put onion on counter
        elif self.state == 23:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = 24
        
        #state 25: chop onion
        elif self.state == 24:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state = 25
        
        #state 26: pickup onion
        elif self.state == 25:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 26
        
        #state 26: add onion to the plate
        elif self.state == 26:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # self.state = 27
                    self.state = self.tasks_queue.popleft()
        
        #state 27: Buy Sauce
        elif self.state == 27:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.SAUCE.buy_cost:
                    if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                        self.state = 28

        #state 28: Add sauce to the plate
        elif self.state == 28:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # self.state = 14
                    self.state = self.tasks_queue.popleft()

        for i in range(1, len(my_bots)):
            self.my_bot_id = my_bots[i]
            bot_id = self.my_bot_id
            
            bot_info = controller.get_bot_state(bot_id)
            bx, by = bot_info['x'], bot_info['y']

            dx = random.choice([-1, 1])
            dy = random.choice([-1, 1])
            nx,ny = bx + dx, by + dy
            if controller.get_map(controller.get_team()).is_tile_walkable(nx, ny):
                controller.move(bot_id, dx, dy)
                return
