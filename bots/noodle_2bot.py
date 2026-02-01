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
        self.bot1_queue = deque()
        self.bot2_queue = deque()

        self.bot1_state = deque()
        self.bot2_state = deque()

        self.order = []
        self.order_index = 0
        self.cooker_loc_egg = None
        self.cooker_loc = None

        self.all_counters = {} # dictionary, key: counter, value: order_num
        # -1 means empty counter
        self.all_cookers = [] # all cooker (x, y)
        # plate positions dict
        self.plate_positions = {} # key: order_num, value: (x, y)

        self.bot1_order = -1
        self.bot2_order = -1

        self.cookers = []


    # find all empty counters in map
    def find_empty_counters(self, controller: RobotController) -> List[Tuple[int, int]]:
        empty_counters = {}
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == "COUNTER":
                    if tile.item is None:
                        empty_counters[(x, y)] = -1
        return empty_counters
    
    def find_cookers(self, controller: RobotController) -> List[Tuple[int, int]]:
        empty_counters = {}
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == "COOKER":
                    if tile.item is None:
                        empty_counters.append((x, y))
        return empty_counters


    # get list of ingredients for current order
    def get_required_ingrediants(self, controller: RobotController):
        if not self.done:
            return 
        else: 
            orders = controller.get_orders(controller.get_team())
            if not orders or self.order_index >= len(orders):
                # No more orders available, reset or return empty
                return []
            
            self.order = orders[self.order_index]["required"] # list[foodtype]
            # print('order', self.order)
            self.order_index += 1
            self.done = False
            return self.order

    def put_task_in_queue(self, controller: RobotController):
        ingredients = self.get_required_ingrediants(controller)
        if not ingredients:
            # No orders available, just wait
            return
        bigl, bot1l, bot2l = self.createTaskSequence(ingredients, self.map, controller)
        self.tasks_queue.extend(deque(bigl))
        self.bot1_queue.extend(deque(bot1l))
        self.bot2_queue.extend(deque(bot2l))

        self.state = self.tasks_queue.popleft()
        print(self.tasks_queue)

    def createTaskSequence(self, currOrder, map, controller: RobotController):

        if "EGG" in currOrder and "MEAT" in currOrder:

            cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos)
            shop_to_egg_cooker = self.get_bfs_distance(controller, self.shop_pos, self.cooker_loc_egg)
            egg_cooker_to_cooker = self.get_bfs_distance(controller, self.cooker_loc_egg, self.cooker_loc)
            T = cooker_to_shop + shop_to_egg_cooker + egg_cooker_to_cooker

            mc = currOrder.count("MEAT")
            ec = currOrder.count("EGG")
            if T < 37: 
                bot2tasks = []
                while True:
                    bot2tasks += [(2, self.cooker_loc), (17, self.cooker_loc_egg), (12, self.cooker_loc), (20, self.cooker_loc_egg)]
                    ec -= 1
                    mc -= 1
                    if ec == 0:
                        bot2tasks += [ (2, self.cooker_loc), (12, self.cooker_loc) ] * mc
                        break 
                    if mc == 0:
                        bot2tasks += [ (17, self.cooker_loc_egg), (20, self.cooker_loc_egg) ] * ec
                        break
            else:
                bot2tasks = [(2, self.cooker_loc), (12, self.cooker_loc)] * mc + [(17, self.cooker_loc),  (20, self.cooker_loc)] * ec

        elif "MEAT" in currOrder:
            cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos)
            shop_to_chopper = self.get_bfs_distance(controller, self.shop_pos, self.chop_counter)
            chopper_to_egg_cooker = self.get_bfs_distance(controller, self.chop_counter, self.cooker_loc_egg)
            egg_cooker_to_cooker = self.get_bfs_distance(controller, self.cooker_loc_egg, self.cooker_loc)
            T = cooker_to_shop + shop_to_chopper + chopper_to_egg_cooker + egg_cooker_to_cooker

            if T < 37: 
                mc = currOrder.count("MEAT")
                while mc > 1:
                    bot2tasks = [(2, self.cooker_loc), (2, self.cooker_loc_egg), (12, self.cooker_loc), (12, self.cooker_loc_egg)]
                    mc -= 2
                    if mc == 1:
                        bot2tasks += [(2, self.cooker_loc), (12, self.cooker_loc)]
                else:
                    bot2tasks = [(2, self.cooker_loc), (12, self.cooker_loc)] * currOrder.count("MEAT")
        
        elif "EGG" in currOrder:
            cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos)
            shop_to_egg_cooker = self.get_bfs_distance(controller, self.shop_pos, self.cooker_loc_egg)
            egg_cooker_to_cooker = self.get_bfs_distance(controller, self.cooker_loc_egg, self.cooker_loc)
            T = cooker_to_shop + shop_to_egg_cooker + egg_cooker_to_cooker

            if T < 37: 
                ec = currOrder.count("EGG")
                while ec > 1:
                    bot2tasks = [(17, self.cooker_loc), (17, self.cooker_loc_egg), (20, self.cooker_loc), (20, self.cooker_loc_egg)]
                    ec -= 2
                    if ec == 1:
                        bot2tasks += [(17, self.cooker_loc), (20, self.cooker_loc)]
                else:
                    bot2tasks = [(17, self.cooker_loc), (20, self.cooker_loc)] * ec
    
        else:
            bot2tasks = []
        
        bot1tasks = self.nameNumberConversion([item for item in currOrder if item not in ["MEAT", "EGG"]])
        
        return bot1tasks, bot2tasks
    
    def nameNumberConversion(self, tasks):
        l = []
        if tasks == set():
            return l
        for task in tasks:
            if task == "PLATE":
                l = [(8, self.plate_counter)] + l
            elif task == "NOODLES":
                l.append((10, self.plate_counter))
            elif task == "ONIONS":
                l.append((22, self.plate_counter))
            elif task == "SAUCE":
                l.append((27, self.plate_counter))
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
        if tasks == []:
            return (set(), set())
        cooker_to_shop = self.get_bfs_distance(controller, self.cooker_loc, self.shop_pos)
        shop_to_plate = self.get_bfs_distance(controller, self.shop_pos, self.plate_counter)
        plate_to_cooker = self.get_bfs_distance(controller, self.plate_counter, self.cooker_loc)




        T = cooker_to_shop + shop_to_plate + plate_to_cooker




        shop_to_chop = self.get_bfs_distance(controller, self.shop_pos, self.chop_counter)
        chop_to_plate = self.get_bfs_distance(controller, self.chop_counter, self.plate_counter)
        plate_to_shop = self.get_bfs_distance(controller, self.plate_counter, self.shop_pos)




        tasks = set(tasks)


        if "PLATE" in tasks:
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
        else:
            if tasks =={"NOODLES"} or tasks == {"SAUCE"}:
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
            elif tasks == {'NOODLES', 'SAUCE'}:
                t = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"NOODLES"}, {"SAUCE"})
                else:
                    return (tasks, set())
            elif tasks == {'NOODLES', 'ONIONS'}:
                t = cooker_to_shop + shop_to_plate + plate_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"NOODLES"}, {"ONIONS"})
                else:
                    return (tasks, set())
            elif tasks == {'ONIONS', 'SAUCE'}:
                t = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_shop + shop_to_plate + plate_to_cooker
                if t > 37:
                    t1 = cooker_to_shop + shop_to_plate + plate_to_cooker
                    if t1 > 37:
                        return (set(), tasks)
                    else:
                        return ({"SAUCE"}, {"ONIONS"})
                else:
                    return (tasks, set())
            elif tasks == {'NOODLES', 'ONIONS', 'SAUCE'}:
                onion  = cooker_to_shop + shop_to_chop + chop_to_plate + plate_to_cooker
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




    def play_turn(self, controller: RobotController):
        # find all counters if not already found
        if self.all_counters == dict():
            self.all_counters = self.find_empty_counters(controller)
        if self.all_cookers == dict():
            self.all_cookers = self.find_cookers(controller)
        
        print("task order:", self.order_index)
        if len(self.tasks_queue) == 0:
            print("hahahahah")
            # Initialize positions first
            my_bots = controller.get_team_bot_ids(controller.get_team())
            if not my_bots: return
            bot1_info = controller.get_bot_state(my_bots[0])
            bx1, by1 = bot1_info['x'], bot1_info['y']
            bot2_info = controller.get_bot_state(my_bots[1]) #cooker
            bx2, by2 = bot2_info['x'], bot2_info['y']
            
            self.shop1_pos = self.find_nearest_tile(controller, bx1, by1, "SHOP")
            self.shop2_pos = self.find_nearest_tile(controller, bx2, by2, "SHOP")

            self.cooker1_pos = self.find_nearest_tile(controller, bx1, by1, "COOKER")
            self.cooker2_pos = self.find_nearest_tile(controller, bx2, by2, "COOKER")
            
            if not self.shop1_pos or not self.cooker1_pos or not self.shop2_pos or not self.cooker2_pos:
                return
            
            self.chop_counter = self.find_nearest_tile(controller, self.shop1_pos[0], self.shop1_pos[1], "COUNTER")
            if not self.chop_counter:
                return
                
            plate_position = self.find_nearest_tile_not_current(controller, self.chop_counter[0], self.chop_counter[1], "COUNTER")
            self.plate_counter[self.order[self.order_index]] = plate_position

            if self.plate_counter == None: 
                return
                #self.plate_counter = self.chop_counter #ERROR: 1 counter only
            
            # Initialize cooker_loc for partition_task
            if self.cookers is None:
                self.cooker_loc = [self.cooker_loc, self.cooker_loc_egg]
                self.find_nearest_tile(controller, bx1, by1, "COOKER")
                ##############################################################
            for loc in self.assmbly_counter:
                self.all_counters[loc] = None




            if self.cooker_loc is None:
                self.cooker_loc = self.find_nearest_tile(controller, self.shop_pos[0], self.shop_pos[1], "COOKER")

            if self.cooker_loc_egg is None:
                self.cooker_loc_egg = self.find_nearest_tile_not_current(controller, self.cooker_loc[0], self.cooker_loc[1], "COOKER")
            

            print("initial q:", self.tasks_queue)
            self.put_task_in_queue(controller)
            print("after q:", self.tasks_queue)

        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots: return
    
        self.bot1_id = my_bots[0]
        self.bot2_id = my_bots[1]
        bot1_id = self.bot1_id
        bot2_id = self.bot2_id
        
        bot1_info = controller.get_bot_state(bot1_id)
        bx1, by1 = bot1_info['x'], bot1_info['y']

        bot2_info = controller.get_bot_state(bot2_id)
        bx2, by2 = bot2_info['x'], bot2_info['y']

        #if self.assembly_counter is None:
        #    self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        #if self.cooker_loc is None:
        #    self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")

        

        if not self.assembly_counter or not self.cooker_loc: return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc

        if self.bot1_state in [22, 27, 10, 8] and bot_info.get('holding'):
            self.bot1_state = 16

        if self.bot2_state in [2, 0, 17, 8] and bot_info.get('holding'):
            self.bot2_state = 16
        #####
        #8 14
        #bot1 = 10 22 27
        #bot2 - 0, 2, 17
        #state 0: init + checking the pan
        if self.bot2_tate == 0:
            tile = controller.get_tile(controller.get_team(), kx, ky)
            if tile and isinstance(tile.item, Pan):
                self.bot2_tate = self.tasks_queue.popleft()
            else:
                self.bot2_tate = 1

        #state 1: buy pan
        elif self.bot2_state == 1:
            holding = bot_info.get('holding')
            if holding: # assume it's the pan
                if self.move_towards(controller, bot2_id, kx, ky):
                    if controller.place(bot2_id, kx, ky):
                        self.bot2_tate = self.tasks_queue.popleft()
            else:
                shop_pos = self.find_nearest_tile(controller, bx2, by2, "SHOP")
                if not shop_pos: return
                sx, sy = shop_pos
                if self.move_towards(controller, bot2_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot2_id, ShopCosts.PAN, sx, sy)

        #state 2: buy meat
        elif self.not2_state == 2:
            shop_pos = self.find_nearest_tile(controller, bx2, by2, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot2_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                    if controller.buy(bot2_id, FoodType.MEAT, sx, sy):
                        self.state = 3

        #state 3: put meat on counter
        elif self.bot2_state == 3:
            if self.move_towards(controller, bot2_id, cx, cy):
                if controller.place(bot2_id, cx, cy):
                    self.state = 4

        #state 4: chop meat
        elif self.bot2_state == 4:
            if self.move_towards(controller, bot2_id, cx, cy):
                if controller.chop(bot2_id, cx, cy):
                    self.state = 5

        #state 5: pickup meat
        elif self.bot2_state == 5:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 6

        #state 6: put meat on cooker
        elif self.bot2_state == 6:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    print('placed meat on cooker', self.tasks_queue)
                    self.state = self.tasks_queue.popleft()

        #state 7: start the cook, but is cooking so we just go
        elif self.bot2_state == 7:
            #self.state = 8
            pass

        #state 8: buy the plate
        elif self.bot2_state == 8:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        #state 9: put the plate on the counter
        elif self.bot2_state == 9:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    bot_info = controller.get_bot_state(bot_id)
                    tile = controller.get_tile(controller.get_team(), cx, cy)
                    self.state = self.tasks_queue.popleft()
                    print('place() succeeded — bot holding:', bot_info.get('holding'))
                    print('place() succeeded — counter tile:', tile.item)

        #state 12: wait and take meat
        elif self.bot2_state == 12:
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
        elif self.bot2_state == 13:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    self.state = self.tasks_queue.popleft()
        
        #state 17: buy egg
        elif self.bot2_state == 17:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.EGG.buy_cost:
                    if controller.buy(bot_id, FoodType.EGG, sx, sy):
                        self.state = 18

        #state 18: put egg on cooker
        elif self.bot2_state == 18:
                if self.move_towards(controller, bot_id, kx, ky):
                    # Using the NEW logic where place() starts cooking automatically
                    if controller.place(bot_id, kx, ky):
                        print('placed egg on cooker', self.tasks_queue)
                        self.state = self.tasks_queue.popleft()


        #state 19: start the cook egg, but is cooking so we just go
        elif self.bot2_state == 19:
            self.state = 20


        #state 20: wait and take egg
        elif self.bot2_state == 20:
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
        elif self.bot2_state == 21:
            # print for debugging
            print('holding item in state 21:', bot_info.get('holding'))
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # self.state = 14
                    self.state = self.tasks_queue.popleft()
                    print(self.state)
                    # print the counter status
                    print('counter status:', controller.get_tile(controller.get_team(), cx, cy).item)
                    print('holding item in state 211111:', bot_info.get('holding'))
        
        #state 14: pick up the plate
        elif self.bot2_state == 14:
            print('holding item in state 14:', bot_info.get('holding'))
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 15

        #state 15: submit
        elif self.bot2_state == 15:
            submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
            ux, uy = submit_pos
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.submit(bot_id, ux, uy):
                    self.done = True
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        #state 16: trash
        elif self.bot2_state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2 #restart
        








        #state 10: buy noodle
         #state 8: buy the plate
        if self.bot1_state == 8:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        #state 9: put the plate on the counter
        elif self.bot1_state == 9:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    bot_info = controller.get_bot_state(bot_id)
                    tile = controller.get_tile(controller.get_team(), cx, cy)
                    self.state = self.tasks_queue.popleft()
                    print('place() succeeded — bot holding:', bot_info.get('holding'))
                    print('place() succeeded — counter tile:', tile.item)

        elif self.bot1_state == 10:
            print('holding item in state 10:', bot_info.get('holding'))
            tile = controller.get_tile(controller.get_team(), cx, cy)
            print("counter item:", tile.item)              # engine object or None
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.state = 11

        #state 11: add noodles to plate
        elif self.bot1_state == 11:
            # print holding 
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # refresh snapshots from the engine (controller) so we print live state
                    bot_info = controller.get_bot_state(bot_id)
                    tile = controller.get_tile(controller.get_team(), cx, cy)
                    self.state = self.tasks_queue.popleft()
                    print('after add_food_to_plate — bot holding:', bot_info.get('holding'))
                    print('after add_food_to_plate — counter item (public):', controller.item_to_public_dict(getattr(tile, 'item', None)))

        
        #state 14: pick up the plate
        elif self.bot1_state == 14:
            print('holding item in state 14:', bot_info.get('holding'))
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 15

        #state 15: submit
        elif self.bot1_state == 15:
            submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
            ux, uy = submit_pos
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.submit(bot_id, ux, uy):
                    self.done = True
                    if self.tasks_queue:
                        self.state = self.tasks_queue.popleft()

        #state 16: trash
        elif self.bot1_state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2 #restart
        
        
        #state 22: buy onion
        elif self.bot1_state == 22:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.ONION.buy_cost:
                    if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                        self.state = 23
        
        #state 23: put onion on counter
        elif self.bot1_state == 23:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = 24
        
        #state 25: chop onion
        elif self.bot1_state == 24:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state = 25
        
        #state 26: pickup onion
        elif self.bot1_state == 25:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    self.state = 26
        
        #state 26: add onion to the plate
        elif self.bot1_state == 26:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    # self.state = 27
                    self.state = self.tasks_queue.popleft()
        
        #state 27: Buy Sauce
        elif self.bot1_state == 27:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.SAUCE.buy_cost:
                    if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                        self.state = 28

        #state 28: Add sauce to the plate
        elif self.bot1_state == 28:
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
