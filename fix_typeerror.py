import re

for filename in ['algo_base.py', 'algo_piles.py']:
    with open(f"/app/{filename}", "r") as f:
        content = f.read()

    # Change draw_coordinate_table definition
    # original: def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float) -> float:
    # new: def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float = 1.0) -> float:
    
    content = content.replace(
        "def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float) -> float:",
        "def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float = 1.0) -> float:"
    )
    content = content.replace(
        "def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]]) -> float:",
        "def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float = 1.0) -> float:"
    )

    with open(f"/app/{filename}", "w") as f:
        f.write(content)

