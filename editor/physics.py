import math
import glm

class SpatialGrid:
    """
    A 2D spatial partitioning grid to optimize collision detection.
    Groups static brushes into cells to reduce O(N) collision checks to O(1).
    """
    def __init__(self, cell_size=512.0):
        self.cell_size = cell_size
        self.cells = {}

    def clear(self):
        self.cells.clear()

    def populate(self, brushes):
        """Builds the grid from a list of static brushes."""
        self.clear()
        for brush in brushes:
            # Skip non-solid or dynamic brushes (handled separately)
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            
            is_dynamic = brush.get('is_mover') or brush.get('is_door')
            if brush.get('is_trigger') and not is_dynamic:
                continue

            pos = brush['pos']
            size = brush['size']
            
            # Calculate AABB bounds
            min_x = int(math.floor((pos[0] - size[0] * 0.5) / self.cell_size))
            max_x = int(math.floor((pos[0] + size[0] * 0.5) / self.cell_size))
            min_z = int(math.floor((pos[2] - size[2] * 0.5) / self.cell_size))
            max_z = int(math.floor((pos[2] + size[2] * 0.5) / self.cell_size))

            # Insert brush into all overlapping cells
            for x in range(min_x, max_x + 1):
                for z in range(min_z, max_z + 1):
                    cell = (x, z)
                    if cell not in self.cells:
                        self.cells[cell] = []
                    self.cells[cell].append(brush)

    def get_potential_colliders(self, player_min, player_max):
        """Returns a list of unique brushes that share grid cells with the player's AABB."""
        min_x = int(math.floor(player_min.x / self.cell_size))
        max_x = int(math.floor(player_max.x / self.cell_size))
        min_z = int(math.floor(player_min.z / self.cell_size))
        max_z = int(math.floor(player_max.z / self.cell_size))

        colliders = []
        seen = set()
        
        for x in range(min_x, max_x + 1):
            for z in range(min_z, max_z + 1):
                cell = (x, z)
                if cell in self.cells:
                    for brush in self.cells[cell]:
                        bid = id(brush)
                        if bid not in seen:
                            seen.add(bid)
                            colliders.append(brush)
                            
        return colliders