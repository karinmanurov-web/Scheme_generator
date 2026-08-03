import re

with open('/app/algo_walls.py', 'r') as f:
    content = f.read()

# Update excluded_layer_keywords to only exclude 'defpoints', 'штамп', 'рамка', 'frame', 'stamp', 'title'
content = content.replace(
    "excluded_layer_keywords = {'defpoints', 'dim', 'размер', 'штамп', 'рамка', 'frame', 'stamp', 'title'}",
    "excluded_layer_keywords = {'defpoints', 'штамп', 'рамка', 'frame', 'stamp', 'title'}"
)

with open('/app/algo_walls.py', 'w') as f:
    f.write(content)

