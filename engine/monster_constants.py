"""
Monster AI constants
All distances are in world units. All times are in seconds.
"""

# How far away (units) a monster can detect the player
MONSTER_SIGHT_RANGE = 512.0

# Seconds between each attack (per-monster cooldown)
MONSTER_SHOOT_INTERVAL = 1.5

# How long the shoot sprite is displayed after firing before reverting to idle
MONSTER_SHOOT_ANIM_TIME = 0.35


# World-units per second that a monster moves toward the player
MONSTER_MOVE_SPEED = 80.0

# Monster stops moving when it gets this close (to avoid clipping into player)
MONSTER_STOP_DISTANCE = 60.0

# ---------------------------------------------------------------------------
# Sprite frame filenames (relative to assets/sprites/monsters/<type>/)
# ---------------------------------------------------------------------------

MONSTER_SPRITE_IDLE  = "idle.png"
MONSTER_SPRITE_SHOOT = "shoot.png"
MONSTER_SPRITE_DEAD  = "dead.png"

# ---------------------------------------------------------------------------
# Billboard size (world units) — used by the 3D renderer for each subtype.
# These are the defaults; individual monsters can override them via the
# Customise Sprites dialog (stored as sprite_width / sprite_height in their
# properties dict).
# ---------------------------------------------------------------------------

MONSTER_SPRITE_SIZES = {
    'human':  (128, 192),   # width, height — upright humanoid enemy
    'flying': (160, 160),    # wider, shorter — airborne creature
}

# Fallback used when monster_type is not listed above
MONSTER_SPRITE_SIZE_DEFAULT = (128, 128)

