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
        
        # Cache locations for faster lookups
        self.shop_loc = None
        self.submit_loc = None
        self.trash_loc = None
        
        self.state = 0

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

            # Prioritize diagonal movement for faster traversal
            for dx in [-1, 1, 0]:
                for dy in [-1, 1, 0]:
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

    def play_turn(self, controller: RobotController):
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots: return
    
        self.my_bot_id = my_bots[0]
        bot_id = self.my_bot_id
        
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']

        # Initialize
        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        if self.shop_loc is None:
            self.shop_loc = self.find_nearest_tile(controller, bx, by, "SHOP")
        if self.submit_loc is None:
            self.submit_loc = self.find_nearest_tile(controller, bx, by, "SUBMIT")
        if self.trash_loc is None:
            self.trash_loc = self.find_nearest_tile(controller, bx, by, "TRASH")

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

        # STATE 1: Buy and place pan
        elif self.state == 1:
            if holding:
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        self.state = 2
            else:
                if self.shop_loc:
                    sx, sy = self.shop_loc
                else:
                    shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                    if not shop_pos:
                        return
                    sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        # STATE 2: Buy meat
        elif self.state == 2:
            if self.shop_loc:
                sx, sy = self.shop_loc
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos:
                    return
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

        #state 6: put meat on counter
        elif self.state == 6:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    self.state = 8 # Skip state 7

        #state 7: start the cook, but is cooking so we just go
        elif self.state == 7:
            self.state = 8

        # STATE 8: Buy plate (while meat cooks)
        elif self.state == 8:
            if self.shop_loc:
                sx, sy = self.shop_loc
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos:
                    return
                sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = 9

        #state 9: put the plate on the counter
        elif self.state == 9:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = 10

        # STATE 10: Buy noodles
        elif self.state == 10:
            if self.shop_loc:
                sx, sy = self.shop_loc
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos:
                    return
                sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.state = 11

        #state 11: add noodles to plate
        elif self.state == 11:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.add_food_to_plate(bot_id, cx, cy):
                    self.state = 12

        #state 12: wait and take meat - predictive positioning
        elif self.state == 12:
            tile = controller.get_tile(controller.get_team(), kx, ky)
            if tile and isinstance(tile.item, Pan) and tile.item.food:
                food = tile.item.food
                cook_progress = getattr(tile, 'cook_progress', 0)
                
                # Predictively move closer when almost done (18-19 turns)
                if cook_progress >= 18 and food.cooked_stage == 0:
                    self.move_towards(controller, bot_id, kx, ky)
                # Take it when perfectly cooked
                elif food.cooked_stage == 1:
                    if self.move_towards(controller, bot_id, kx, ky):
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 13
                elif food.cooked_stage == 2:
                    # Burnt - trash it
                    if self.move_towards(controller, bot_id, kx, ky):
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = 16
            else:
                if bot_info.get('holding'):
                    self.state = 16
                else:
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
                    self.state = 2  # Skip pan check, go straight to next order

        #state 16: trash
        elif self.state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.state = 2 #restart
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