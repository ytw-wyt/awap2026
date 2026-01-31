import random
from collections import deque
from typing import Tuple, Optional, List

from game_constants import Team, TileType, FoodType, ShopCosts, GameConstants
from robot_controller import RobotController
from item import Pan, Plate, Food

class BotPlayer:
    """Optimized single-bot strategy with tight cooking loop"""
    
    def __init__(self, map_copy):
        self.map = map_copy
        
        # Resource locations
        self.counter_loc = None
        self.cooker_loc = None
        self.shop_loc = None
        self.submit_loc = None
        self.trash_loc = None
        
        # State machine
        self.state = 0
        self.my_bot_id = None
        
    def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], 
                     target_predicate, avoid_pos: Optional[Tuple[int, int]] = None) -> Optional[Tuple[int, int]]:
        """BFS with collision avoidance"""
        queue = deque([(start, [])]) 
        visited = set([start])
        w, h = self.map.width, self.map.height

        while queue:
            (curr_x, curr_y), path = queue.popleft()
            tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
            if target_predicate(curr_x, curr_y, tile):
                if not path: 
                    return (0, 0) 
                return path[0] 

            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0: 
                        continue
                    nx, ny = curr_x + dx, curr_y + dy
                    
                    if avoid_pos and (nx, ny) == avoid_pos:
                        continue
                        
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if controller.get_map(controller.get_team()).is_tile_walkable(nx, ny):
                            visited.add((nx, ny))
                            queue.append(((nx, ny), path + [(dx, dy)]))
        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, 
                     target_y: int, avoid_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Returns True if adjacent to target"""
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        
        def is_adjacent(x, y, tile):
            return max(abs(x - target_x), abs(y - target_y)) <= 1
            
        if is_adjacent(bx, by, None): 
            return True
            
        step = self.get_bfs_path(controller, (bx, by), is_adjacent, avoid_pos)
        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
        return False

    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, 
                          tile_name: str) -> Optional[Tuple[int, int]]:
        """Find nearest tile"""
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
    
    def find_all_tiles(self, controller: RobotController, tile_name: str) -> List[Tuple[int, int]]:
        """Find all tiles of a given type"""
        positions = []
        m = controller.get_map(controller.get_team())
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == tile_name:
                    positions.append((x, y))
        return positions

    def initialize(self, controller: RobotController):
        """One-time initialization - find all resources"""
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots:
            return False
            
        bot1_state = controller.get_bot_state(my_bots[0])
        b1x, b1y = bot1_state['x'], bot1_state['y']
        
        # Find ALL counters and cookers for parallel work
        counters = self.find_all_tiles(controller, "COUNTER")
        cookers = self.find_all_tiles(controller, "COOKER")
        
        # Assign dedicated resources
        if len(counters) >= 2:
            self.counter1_loc = counters[0]  # Bot1 uses first counter
            self.counter2_loc = counters[1]  # Bot2 uses second counter
        elif len(counters) == 1:
            self.counter1_loc = counters[0]
            self.counter2_loc = counters[0]  # Fallback to shared
        
        if len(cookers) >= 2:
            self.cooker1_loc = cookers[0]  # Primary cooker
            self.cooker2_loc = cookers[1]  # Secondary cooker
        elif len(cookers) == 1:
            self.cooker1_loc = cookers[0]
            self.cooker2_loc = cookers[0]  # Fallback to shared
        
        self.shop_loc = self.find_nearest_tile(controller, b1x, b1y, "SHOP")
        self.submit_loc = self.find_nearest_tile(controller, b1x, b1y, "SUBMIT")
        self.trash_loc = self.find_nearest_tile(controller, b1x, b1y, "TRASH")
        
        return (self.counter1_loc is not None and self.cooker1_loc is not None 
                and self.shop_loc is not None)

    def check_counter_status(self, controller: RobotController, counter_loc: Tuple[int, int]) -> Dict[str, Any]:
        """Check what's on a specific counter"""
        if not counter_loc:
            return {"empty": True, "item_type": None}
        
        cx, cy = counter_loc
        tile = controller.get_tile(controller.get_team(), cx, cy)
        
        if tile and hasattr(tile, 'item') and tile.item:
            item = tile.item
            if isinstance(item, Food):
                return {
                    "empty": False,
                    "item_type": "Food",
                    "food_name": item.food_name,
                    "chopped": item.chopped,
                    "cooked_stage": item.cooked_stage
                }
            elif isinstance(item, Plate):
                return {
                    "empty": False,
                    "item_type": "Plate",
                    "num_foods": len(item.food) if hasattr(item, 'food') else 0
                }
            else:
                return {"empty": False, "item_type": type(item).__name__}
        
        return {"empty": True, "item_type": None}

    def check_cooker_status(self, controller: RobotController, cooker_loc: Tuple[int, int]) -> Dict[str, Any]:
        """Check specific cooker status"""
        if not cooker_loc:
            return {"has_food": False}
        
        kx, ky = cooker_loc
        tile = controller.get_tile(controller.get_team(), kx, ky)
        
        if tile and hasattr(tile, 'item') and isinstance(tile.item, Pan):
            pan = tile.item
            if pan.food:
                return {
                    "has_food": True,
                    "cooked_stage": pan.food.cooked_stage,
                    "cook_progress": getattr(tile, 'cook_progress', 0),
                    "food_name": pan.food.food_name
                }
        return {"has_food": False}

    def bot1_logic(self, controller: RobotController, bot_id: int, bot2_pos: Optional[Tuple[int, int]]):
        """Bot 1: Cook meat continuously using counter1 and dual cookers"""
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']
        holding = bot_info.get('holding')
        
        sx, sy = self.shop_loc
        cx, cy = self.counter1_loc  # Bot1's dedicated counter
        tx, ty = self.trash_loc
        
        # State machine
        if self.bot1_state == "init":
            # Check if pan exists on either cooker
            cooker1_status = self.check_cooker_status(controller, self.cooker1_loc)
            cooker2_status = self.check_cooker_status(controller, self.cooker2_loc)
            if cooker1_status.get("has_food") is not None or cooker2_status.get("has_food") is not None:
                self.pan_ready = True
                self.bot1_state = "buy_meat"
            else:
                self.bot1_state = "buy_pan"
        
        elif self.bot1_state == "buy_pan":
            if holding and holding.get('type') == 'Pan':
                # Place pan on cooker1
                kx, ky = self.cooker1_loc
                if self.move_towards(controller, bot_id, kx, ky, bot2_pos):
                    controller.place(bot_id, kx, ky)
                    self.pan_ready = True
                    self.bot1_state = "buy_meat"
            else:
                if self.move_towards(controller, bot_id, sx, sy, bot2_pos):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)
        
        elif self.bot1_state == "buy_meat":
            if holding and holding.get('type') == 'Food':
                self.bot1_state = "chop_meat"
            else:
                if self.move_towards(controller, bot_id, sx, sy, bot2_pos):
                    if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                        controller.buy(bot_id, FoodType.MEAT, sx, sy)
        
        elif self.bot1_state == "chop_meat":
            # Counter1 is Bot1's dedicated counter - no waiting needed!
            counter_status = self.check_counter_status(controller, self.counter1_loc)
            if not counter_status["empty"]:
                # Counter occupied (should be rare with stockpiling)
                pass
            else:
                # Place meat on counter1
                if self.move_towards(controller, bot_id, cx, cy, bot2_pos):
                    if controller.place(bot_id, cx, cy):
                        self.bot1_state = "chopping"
        
        elif self.bot1_state == "chopping":
            if self.move_towards(controller, bot_id, cx, cy, bot2_pos):
                if controller.chop(bot_id, cx, cy):
                    self.bot1_state = "pickup_chopped"
        
        elif self.bot1_state == "pickup_chopped":
            if self.move_towards(controller, bot_id, cx, cy, bot2_pos):
                if controller.pickup(bot_id, cx, cy):
                    self.bot1_state = "start_cooking"
        
        elif self.bot1_state == "start_cooking":
            # Try both cookers for parallel cooking
            cooker1_status = self.check_cooker_status(controller, self.cooker1_loc)
            cooker2_status = self.check_cooker_status(controller, self.cooker2_loc)
            
            # Choose available cooker
            if not cooker1_status.get("has_food"):
                # Cooker1 is free
                kx, ky = self.cooker1_loc
                if self.move_towards(controller, bot_id, kx, ky, bot2_pos):
                    if controller.place(bot_id, kx, ky):
                        self.bot1_active_cooker = self.cooker1_loc
                        self.bot1_state = "monitor_cooking"
            elif not cooker2_status.get("has_food"):
                # Cooker2 is free
                kx, ky = self.cooker2_loc
                if self.move_towards(controller, bot_id, kx, ky, bot2_pos):
                    if controller.place(bot_id, kx, ky):
                        self.bot1_active_cooker = self.cooker2_loc
                        self.bot1_state = "monitor_cooking"
            # else: both busy, wait
        
        elif self.bot1_state == "monitor_cooking":
            # Monitor the active cooker
            if not self.bot1_active_cooker:
                self.bot1_active_cooker = self.cooker1_loc
            
            kx, ky = self.bot1_active_cooker
            cooker_status = self.check_cooker_status(controller, self.bot1_active_cooker)
            
            if not cooker_status.get("has_food"):
                # Food was taken or disappeared, restart
                self.bot1_state = "buy_meat"
            elif cooker_status["cooked_stage"] == 1:
                # Perfectly cooked!
                if self.move_towards(controller, bot_id, kx, ky, bot2_pos):
                    if controller.take_from_pan(bot_id, kx, ky):
                        self.bot1_state = "place_cooked_meat"
            elif cooker_status["cooked_stage"] == 2:
                # Burnt! Trash it
                if self.move_towards(controller, bot_id, kx, ky, bot2_pos):
                    if controller.take_from_pan(bot_id, kx, ky):
                        self.bot1_state = "trash"
        
        elif self.bot1_state == "place_cooked_meat":
            # Place cooked meat on available counter (counter1 or counter2)
            counter1_status = self.check_counter_status(controller, self.counter1_loc)
            counter2_status = self.check_counter_status(controller, self.counter2_loc)
            
            # Try counter1 first
            if counter1_status["empty"]:
                cx, cy = self.counter1_loc
                if self.move_towards(controller, bot_id, cx, cy, bot2_pos):
                    if controller.place(bot_id, cx, cy):
                        self.meat_stockpile += 1
                        self.bot1_state = "buy_meat"  # Start next batch
            # If counter1 full, try counter2
            elif counter2_status["empty"]:
                cx, cy = self.counter2_loc
                if self.move_towards(controller, bot_id, cx, cy, bot2_pos):
                    if controller.place(bot_id, cx, cy):
                        self.meat_stockpile += 1
                        self.bot1_state = "buy_meat"  # Start next batch
            # Both full, wait
            else:
                pass
        
        elif self.bot1_state == "trash":
            if self.move_towards(controller, bot_id, tx, ty, bot2_pos):
                if controller.trash(bot_id, tx, ty):
                    self.bot1_state = "buy_meat"

    def bot2_logic(self, controller: RobotController, bot_id: int, bot1_pos: Optional[Tuple[int, int]]):
        """Bot 2: Assemble and submit orders using counter2"""
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']
        holding = bot_info.get('holding')
        
        sx, sy = self.shop_loc
        c2x, c2y = self.counter2_loc  # Bot2's dedicated counter
        c1x, c1y = self.counter1_loc  # Bot1's counter (for getting meat)
        ux, uy = self.submit_loc
        tx, ty = self.trash_loc
        
        if self.bot2_state == "init":
            self.bot2_state = "buy_plate"
        
        elif self.bot2_state == "buy_plate":
            if holding and holding.get('type') == 'Plate':
                self.bot2_state = "buy_noodles"
            else:
                if self.move_towards(controller, bot_id, sx, sy, bot1_pos):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                        controller.buy(bot_id, ShopCosts.PLATE, sx, sy)
        
        elif self.bot2_state == "buy_noodles":
            if holding and holding.get('type') == 'Food':
                # Have noodles, now wait for meat while holding both
                self.bot2_state = "wait_for_meat"
            else:
                # Still holding plate, need to buy noodles
                if self.move_towards(controller, bot_id, sx, sy, bot1_pos):
                    # Check counter2 (Bot2's dedicated counter)
                    counter_status = self.check_counter_status(controller, self.counter2_loc)
                    if counter_status["empty"]:
                        # Go place plate on counter2 so we can buy noodles
                        self.bot2_state = "place_plate_temp"
                    # Otherwise keep trying to get to shop
        
        elif self.bot2_state == "place_plate_temp":
            counter_status = self.check_counter_status(controller, self.counter2_loc)
            if not counter_status["empty"]:
                # Counter2 busy (shouldn't happen, it's dedicated to Bot2)
                pass  
            else:
                if holding and holding.get('type') == 'Plate':
                    # Make sure plate is NOT dirty before placing
                    if holding.get('dirty', False):
                        # Holding dirty plate! Trash it first
                        self.bot2_state = "trash"
                    else:
                        if self.move_towards(controller, bot_id, c2x, c2y, bot1_pos):
                            if controller.place(bot_id, c2x, c2y):
                                self.bot2_state = "buying_noodles"
                else:
                    # Not holding plate anymore? Restart
                    self.bot2_state = "buy_plate"
        
        elif self.bot2_state == "buying_noodles":
            if self.move_towards(controller, bot_id, sx, sy, bot1_pos):
                if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                    if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                        self.bot2_state = "add_noodles"
        
        elif self.bot2_state == "add_noodles":
            # Add noodles to plate on counter2
            counter_status = self.check_counter_status(controller, self.counter2_loc)
            if counter_status.get("item_type") == "Plate":
                if self.move_towards(controller, bot_id, c2x, c2y, bot1_pos):
                    if controller.add_food_to_plate(bot_id, c2x, c2y):
                        # Immediately pick up the plate
                        self.bot2_state = "pickup_plate_with_noodles"
            else:
                # Plate gone? Restart
                self.bot2_state = "trash"
        
        elif self.bot2_state == "pickup_plate_with_noodles":
            # Pick up plate with noodles from counter2, then get meat from counter1
            if self.move_towards(controller, bot_id, c2x, c2y, bot1_pos):
                if controller.pickup(bot_id, c2x, c2y):
                    # Now holding plate with noodles, go get meat from counter1
                    self.bot2_state = "wait_for_meat"
        
        elif self.bot2_state == "wait_for_meat":
            # Check BOTH counters for meat (Bot1 can place on either)
            # At this point Bot2 should be holding the plate with noodles
            counter1_status = self.check_counter_status(controller, self.counter1_loc)
            counter2_status = self.check_counter_status(controller, self.counter2_loc)
            
            # Check counter1 first
            if (counter1_status.get("item_type") == "Food" and 
                counter1_status.get("food_name") == "MEAT" and
                counter1_status.get("chopped") and
                counter1_status.get("cooked_stage") == 1):
                # Cooked meat is ready on counter1!
                if self.move_towards(controller, bot_id, c1x, c1y, bot1_pos):
                    if controller.add_food_to_plate(bot_id, c1x, c1y):
                        self.meat_stockpile = max(0, self.meat_stockpile - 1)
                        self.bot2_state = "submit"  # Plate complete, go submit!
            # Check counter2 as backup
            elif (counter2_status.get("item_type") == "Food" and 
                  counter2_status.get("food_name") == "MEAT" and
                  counter2_status.get("chopped") and
                  counter2_status.get("cooked_stage") == 1):
                # Cooked meat is ready on counter2!
                if self.move_towards(controller, bot_id, c2x, c2y, bot1_pos):
                    if controller.add_food_to_plate(bot_id, c2x, c2y):
                        self.meat_stockpile = max(0, self.meat_stockpile - 1)
                        self.bot2_state = "submit"  # Plate complete, go submit!
        
        elif self.bot2_state == "submit":
            if self.move_towards(controller, bot_id, ux, uy, bot1_pos):
                if controller.submit(bot_id, ux, uy):
                    self.orders_completed += 1
                    # After submit, plate becomes dirty - need to trash it
                    self.bot2_state = "trash"
                else:
                    # Submit failed
                    self.bot2_state = "trash"
        
        elif self.bot2_state == "trash":
            if holding:
                if self.move_towards(controller, bot_id, tx, ty, bot1_pos):
                    if controller.trash(bot_id, tx, ty):
                        self.bot2_state = "buy_plate"
            else:
                self.bot2_state = "buy_plate"

    def play_turn(self, controller: RobotController):
        """Main game loop"""
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots:
            return
        
        # Initialize
        if self.counter1_loc is None:
            if not self.initialize(controller):
                return
        
        # Get bot positions
        bot1_pos = None
        bot2_pos = None
        
        if len(my_bots) >= 1:
            bot1_state = controller.get_bot_state(my_bots[0])
            bot1_pos = (bot1_state['x'], bot1_state['y'])
        
        if len(my_bots) >= 2:
            bot2_state = controller.get_bot_state(my_bots[1])
            bot2_pos = (bot2_state['x'], bot2_state['y'])
        
        # Run both bots
        if len(my_bots) >= 1:
            self.bot1_logic(controller, my_bots[0], bot2_pos)
        
        if len(my_bots) >= 2:
            self.bot2_logic(controller, my_bots[1], bot1_pos)
