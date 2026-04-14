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

# ---------------------------------------------------------------------------
# Projectile constants  (flying monster ranged attack)
# ---------------------------------------------------------------------------
MONSTER_PROJECTILE_SPEED    = 160.0   # world-units / second
MONSTER_PROJECTILE_MAX_DIST = 1024.0  # despawn after travelling this far
MONSTER_PROJECTILE_SPRITE_SIZE = (40.0, 40.0)   # billboard size in world units

# ---------------------------------------------------------------------------
# Monster physics & collision
# ---------------------------------------------------------------------------
MONSTER_GRAVITY        = -500.0   # same gravity as player
MONSTER_TERMINAL_VEL   = -500.0
MONSTER_MIN_WIDTH      = 200.0    # monsters are always at least 200px wide
MONSTER_WALL_MARGIN    = 100.0    # half of MONSTER_MIN_WIDTH — keep this far from wall surfaces
MONSTER_DEAD_FALL_SPEED = 300.0   # world-units/sec the dead sprite falls

# ---------------------------------------------------------------------------
# Weapon damage per gun type
# ---------------------------------------------------------------------------
WEAPON_DAMAGE = {
    'gun1': 25,
    'gun2': 75,    # shotgun — 3× gun1
}

# ---------------------------------------------------------------------------
# Per-weapon shoot sound
# ---------------------------------------------------------------------------
WEAPON_SHOOT_SOUND = {
    'gun1': 'shoot.wav',
    'gun2': 'shoot2.wav',
}
