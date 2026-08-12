from typing import List, Tuple, Optional
from src.core.model import Diagram, ActivityBox, Point, simplify_path
import re

def natural_sort_key(s):
    """Natural sort key for IDEF0 IDs (e.g., A1, A2, A10)"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def calculate_diagonal_layout(diagram: Diagram, start_x=150, start_y=150, spacing_x=250, spacing_y=200):
    # Sort boxes naturally by ID to ensure A1 -> A2 -> A3 sequence diagonally
    sorted_boxes = sorted(diagram.boxes, key=lambda b: natural_sort_key(b.id))
    for i, box in enumerate(sorted_boxes):
        box.x = start_x + (i * spacing_x)
        box.y = start_y + (i * spacing_y)

# Spacing between adjacent arrow lanes to prevent overlap
LANE_SPACING = 15

def manhattan_route(start_pt: Tuple[float, float], end_pt: Tuple[float, float], 
                    start_dir: str, end_dir: str, obstacles: Optional[List[ActivityBox]] = None,
                    arrow_type: str = None, padding: float = 20, salt: int = 0,
                    lane_offset: int = 0) -> List[Point]:
    """
    Improved Manhattan Router for IDEF0 with obstacle avoidance and feedback routing.
    Ensures lines leave and enter correctly relative to boxes and never pass over them.
    
    Feedback arrows (going backwards):
    - To Control: route "up and over" (above all boxes)
    - To Input/Mechanism: route "down and under" (below all boxes)
    """
    x1, y1 = start_pt
    x2, y2 = end_pt
    points = [Point(x1, y1)]
    
    if obstacles is None:
        obstacles = []
    
    # Helper function to check if a line segment intersects any obstacle
    def line_intersects_box(p1_x, p1_y, p2_x, p2_y, box):
        """Check if a line segment penetrates inside a box's interior."""
        box_left = box.x + 1.0
        box_right = box.x + box.width - 1.0
        box_top = box.y + 1.0
        box_bottom = box.y + box.height - 1.0
        
        # Get line bounds
        line_left = min(p1_x, p2_x)
        line_right = max(p1_x, p2_x)
        line_top = min(p1_y, p2_y)
        line_bottom = max(p1_y, p2_y)
        
        # Check if line bounding box intersects obstacle bounding box
        if (line_right <= box_left or line_left >= box_right or
            line_bottom <= box_top or line_top >= box_bottom):
            return False
        
        return True
    
    def find_clear_horizontal_path(x_start, x_end, y, boxes):
        """Find a Y coordinate that provides a clear horizontal path.
        Iteratively tries positions above and below the ideal Y, expanding outward."""
        # Try the current Y first
        if not any(line_intersects_box(x_start, y, x_end, y, box) for box in boxes):
            return y
        
        # Iteratively search above and below, expanding outward from ideal position
        for step in range(1, 15):
            offset = step * 25
            # Try above
            candidate = y - offset
            if not any(line_intersects_box(x_start, candidate, x_end, candidate, box) for box in boxes):
                return candidate
            # Try below
            candidate = y + offset
            if not any(line_intersects_box(x_start, candidate, x_end, candidate, box) for box in boxes):
                return candidate
        
        return y  # Fallback
    
    def find_clear_vertical_path(y_start, y_end, x, boxes):
        """Find an X coordinate that provides a clear vertical path.
        Iteratively tries positions right and left of the ideal X, expanding outward."""
        # Try the current X first
        if not any(line_intersects_box(x, y_start, x, y_end, box) for box in boxes):
            return x
        
        # Iteratively search right and left, expanding outward from ideal position
        for step in range(1, 15):
            offset = step * 25
            # Try right first for forward flow (prefer continuing rightward past obstacles)
            candidate = x + offset
            if not any(line_intersects_box(candidate, y_start, candidate, y_end, box) for box in boxes):
                return candidate
            # Try left
            candidate = x - offset
            if not any(line_intersects_box(candidate, y_start, candidate, y_end, box) for box in boxes):
                return candidate
        
        return x  # Fallback
    
    
    # Padding to get away from the box (suppress if it moves us away from target)
    # Using padding from function argument
    
    # 1. First Point - Move away from Source
    curr_x, curr_y = x1, y1
    if start_dir == 'right': 
        if x2 > x1: curr_x += padding
    elif start_dir == 'left': 
        if x2 < x1: curr_x -= padding
    elif start_dir == 'top': 
        if y2 < y1: curr_y -= padding
    elif start_dir == 'bottom': 
        if y2 > y1: curr_y += padding
    
    p1 = Point(curr_x, curr_y)
    points.append(p1)
    
    # 2. Last Point - Approach Target (suppress if it moves us away from current position)
    target_padding = padding if padding == 0 else max(20.0, padding)
    target_approach_x, target_approach_y = x2, y2
    if end_dir == 'right': 
        if curr_x > x2: target_approach_x += target_padding
    elif end_dir == 'left': 
        if curr_x < x2: target_approach_x -= target_padding
    elif end_dir == 'top': 
        if curr_y < y2: target_approach_y -= target_padding
    elif end_dir == 'bottom': 
        if curr_y > y2: target_approach_y += target_padding
    
    p_last = Point(target_approach_x, target_approach_y)
    
    # 3. Intermediate Routing with obstacle avoidance
    dx = target_approach_x - curr_x

    # Specialized Feedback Routing (Going backwards: target is left of source)
    is_feedback = False
    if target_approach_x < curr_x:
        is_feedback = True
    
    # Check if start and end are on vertical faces of the SAME box region (even if moving forward/back)
    # feedback detection is primarily X-based.
    
    if is_feedback and start_dir == 'right':
        # Create a stable, deterministic stagger offset to prevent exact overlaps of parallel feedback lines
        # Salt 0, 1, 2... provides unique lanes for stacked loops
        # Use separate exit and loop offsets so the vertical exit segment and the
        # horizontal clearance loop both shift, producing clear daylight between
        # parallel feedback paths.
        stagger_gap = LANE_SPACING
        exit_stagger = salt * stagger_gap     # Staggers the vertical exit stub
        loop_stagger = salt * stagger_gap     # Staggers the horizontal clearance loop
        stagger_x_exit = 20 + exit_stagger    # Exit right from source
        stagger_x_entry = 20 + exit_stagger   # Entry left into target
        
        # Determine routing strategy based on semantic type:
        # ONLY Control feedback (targeting top of box) routes UP AND OVER.
        # Input (left) and Mechanism (bottom) feedback strictly route DOWN AND UNDER.
        is_control = False
        if arrow_type == "Control":
            is_control = True
        elif not arrow_type and end_dir == 'bottom':
            is_control = True
        
        if is_control:
            # UP AND OVER (Right -> Top for Control feedback)
            relevant_obs = [box.y for box in obstacles if box.x + box.width >= target_approach_x and box.x <= curr_x]
            highest_top = min(relevant_obs + [y1, y2]) if relevant_obs else min(y1, y2)
            # Compact escape distance to 40 pixels to look more integrated
            loop_top = highest_top - 40 - loop_stagger
            
            points.append(Point(curr_x + stagger_x_exit, curr_y))
            points.append(Point(curr_x + stagger_x_exit, loop_top))
            points.append(Point(target_approach_x - exit_stagger, loop_top))
            # Connect to the target's X coordinate
            if abs(target_approach_x - exit_stagger - target_approach_x) > 1:
                points.append(Point(target_approach_x, loop_top))
            # Continues automatically to target_approach_x, target_approach_y (down into top)
            
        else:
            # DOWN AND UNDER (Right -> Bottom for Mechanism, Right -> Left for Input)
            relevant_obs = [box.y + box.height for box in obstacles if box.x + box.width >= target_approach_x and box.x <= curr_x]
            lowest_bottom = max(relevant_obs + [y1, y2]) if relevant_obs else max(y1, y2)
            # Compact escape distance to 40 pixels 
            loop_bottom = lowest_bottom + 40 + loop_stagger
            
            points.append(Point(curr_x + stagger_x_exit, curr_y))
            points.append(Point(curr_x + stagger_x_exit, loop_bottom))
            
            if end_dir == 'left':
                points.append(Point(target_approach_x - stagger_x_entry, loop_bottom))
                points.append(Point(target_approach_x - stagger_x_entry, target_approach_y))
            else:
                points.append(Point(target_approach_x, loop_bottom))
            # Continues automatically to p_last
            
        return simplify_path(points + [p_last, Point(x2, y2)])
    
    # Case: Normal Output (Right -> Forward) -> Input (Left)
    if start_dir == 'right' and end_dir == 'left':
        if x2 > curr_x:
            mid_x = x2 - 35 - (lane_offset * 20)
        else:
            mid_x = curr_x + dx / 2 + (lane_offset * LANE_SPACING)
            
        colliding_box = next((b for b in obstacles if line_intersects_box(curr_x, curr_y, mid_x, curr_y, b)), None)
        if colliding_box and curr_x < colliding_box.x:
            # Route around obstacle box by dropping down BEFORE the box in the left margin
            turn_x1 = find_clear_vertical_path(curr_y, target_approach_y, min(curr_x + 40, colliding_box.x - 20), obstacles)
            points.append(Point(turn_x1, curr_y))
            points.append(Point(turn_x1, target_approach_y))
        else:
            # Check if vertical segment intersects obstacles
            mid_x = find_clear_vertical_path(curr_y, target_approach_y, mid_x, obstacles)
            points.append(Point(mid_x, curr_y))
            points.append(Point(mid_x, target_approach_y))
    
    # Case: Normal Output (Right -> Forward) -> Merge Junction (Top or Bottom)
    elif start_dir == 'right' and end_dir in ['top', 'bottom']:
        turn_x = x2
        colliding_box = next((b for b in obstacles if line_intersects_box(curr_x, curr_y, turn_x, curr_y, b)), None)
        if colliding_box and curr_x < colliding_box.x:
            # Route around obstacle box (underneath for top target, overhead for bottom target)
            turn_x1 = find_clear_vertical_path(curr_y, y2, min(curr_x + 40, colliding_box.x - 20), obstacles)
            if end_dir == 'top':
                pass_y = (colliding_box.y + colliding_box.height + y2) / 2
            else:
                pass_y = (colliding_box.y + y2) / 2
            turn_x2 = find_clear_vertical_path(pass_y, y2, x2, obstacles)
            points.append(Point(turn_x1, curr_y))
            points.append(Point(turn_x1, pass_y))
            points.append(Point(turn_x2, pass_y))
            points.append(Point(turn_x2, y2))
            return simplify_path(points)
        else:
            turn_x = find_clear_vertical_path(curr_y, y2, turn_x, obstacles)
            points.append(Point(turn_x, curr_y))
            points.append(Point(turn_x, y2))
            return simplify_path(points)

    # Default Orthogonal Helper
    if len(points) == 2:
        if points[-1].x != target_approach_x and points[-1].y != target_approach_y:
            # Plan mid point based on start direction
            if start_dir in ['top', 'bottom']:
                # Prefer vertical first to get away from horizontal boundaries
                mid_x = curr_x
                mid_y = target_approach_y
                # Check for obstacles
                if any(line_intersects_box(curr_x, curr_y, mid_x, mid_y, box) for box in obstacles):
                    # Try horizontal first instead
                    mid_x = target_approach_x
                    mid_y = curr_y
            else:
                # Prefer horizontal first (standard for inputs/outputs)
                mid_x = target_approach_x
                mid_y = curr_y
                # Check for obstacles
                if any(line_intersects_box(curr_x, curr_y, mid_x, mid_y, box) for box in obstacles):
                    # Try vertical first instead
                    mid_x = curr_x
                    mid_y = target_approach_y
            points.append(Point(mid_x, mid_y))
    
    points.append(p_last)
    points.append(Point(x2, y2))
    
    return simplify_path(points)
