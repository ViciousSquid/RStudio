"""
Monster AI – all enemy behaviour, patrol logic, sight, shooting, and physics.
Extracted from LogicThread for easier maintenance and extension.

PERF: All brush collision/raycast methods now delegate to SpatialGrid,
reducing per-monster cost from O(all_brushes) to O(nearby_brushes).
"""

import glm
import math
from typing import Dict, List, Any, Optional, Tuple
from editor.debug_console import debug_log
from .monster_constants import (
    MONSTER_SIGHT_RANGE,
    MONSTER_SHOOT_INTERVAL,
    MONSTER_SHOOT_ANIM_TIME,
    MONSTER_MOVE_SPEED,
    MONSTER_STOP_DISTANCE,
    MONSTER_GRAVITY,
    MONSTER_TERMINAL_VEL,
    MONSTER_WALL_MARGIN,
    MONSTER_STUCK_THRESHOLD,
    MONSTER_DETOUR_RANGE,
    WEAPON_DAMAGE,
)

try:
    from editor.things import PathNode, Monster as MonsterThing
except ImportError:
    PathNode = None
    MonsterThing = None


class MonsterAI:
    """Handles all monster AI updates, patrol, sight, combat, and debug visualisation."""

    def __init__(self, logic_thread):
        self.lt = logic_thread                     # parent LogicThread
        self.monster_states: Dict[int, Dict[str, Any]] = {}
        self._debug_rays: List[Dict[str, Any]] = []   # for F7 debug lines
        self.monster_debug_active = False
        self._grid = None                          # SpatialGrid, set by LogicThread

    def set_spatial_grid(self, grid):
        """Called by LogicThread after populating the grid."""
        self._grid = grid

    # -------------------------------------------------------------------------
    # Main update entry point
    # -------------------------------------------------------------------------

    def update(self, delta: float):
        """Called every tick from LogicThread._tick_play_mode."""
        if not self.lt.player or not MonsterThing:
            return

        if self.lt.player_dead:
            return

        player_pos = self.lt.player.pos
        self._debug_rays.clear()

        for thing in self.lt.things:
            if not isinstance(thing, MonsterThing):
                continue

            if thing.properties.get('hidden', False):
                thing.properties.pop('is_shooting', None)
                continue
            if thing.properties.get('disabled', False):
                continue

            mid = id(thing)

            # ---- Dead monsters: sprite falls ----
            if thing.properties.get('dead', False):
                thing.properties.pop('is_shooting', None)
                vel_y = thing.properties.get('_vel_y', 0.0)
                pos = thing.pos
                ground_y = self._monster_raycast_down(pos[0], pos[2], pos[1])
                if ground_y is not None:
                    sprite_h = thing.properties.get('sprite_height', 128)
                    target_y = ground_y + sprite_h / 2.0
                    if pos[1] > target_y + 1.0:
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_y = pos[1] + vel_y * delta
                        if new_y <= target_y:
                            new_y = target_y
                            vel_y = 0.0
                        thing.pos = [pos[0], new_y, pos[2]]
                        thing.properties['_vel_y'] = vel_y
                    else:
                        if abs(pos[1] - target_y) > 1.0:
                            thing.pos = [pos[0], target_y, pos[2]]
                        thing.properties['_vel_y'] = 0.0
                else:
                    thing.properties['_vel_y'] = 0.0
                continue

            # ---- Awake / triggered logic ----
            triggered = thing.properties.get('triggered', False)
            wake_sight = thing.properties.get('wake_on_sight', True)
            awake = thing.properties.get('awake', False)

            if not awake:
                if triggered:
                    continue
                elif not wake_sight:
                    thing.properties['awake'] = True
                    awake = True
                else:
                    dist_to_player = glm.distance(player_pos, glm.vec3(thing.pos))
                    if dist_to_player <= MONSTER_SIGHT_RANGE:
                        thing.properties['awake'] = True
                        awake = True
                    else:
                        continue

            # ---- Kill input handling ----
            if thing.properties.pop('_kill', False):
                thing.properties['dead'] = True
                thing.properties.pop('is_shooting', None)
                continue

            mtype = thing.properties.get('monster_type', 'human')
            thing_pos = glm.vec3(thing.pos)

            # ---- Per‑monster state initialisation ----
            if mid not in self.monster_states:
                self.monster_states[mid] = {
                    'shoot_timer': MONSTER_SHOOT_INTERVAL,
                    'anim_timer': 0.0,
                    'in_sight': False,
                    'vel_y': 0.0,
                }

            state = self.monster_states[mid]

            # ---- Gravity for ground monsters ----
            if mtype != 'flying':
                vel_y = state.get('vel_y', 0.0)
                ground_y = self._monster_raycast_down(thing_pos.x, thing_pos.z, thing_pos.y + 10.0)
                sprite_height = thing.properties.get('sprite_height', 128)
                half_height = sprite_height / 2.0
                if ground_y is not None:
                    foot_y = thing_pos.y - half_height
                    if foot_y > ground_y + 1.0:
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_foot_y = foot_y + vel_y * delta
                        if new_foot_y <= ground_y:
                            new_foot_y = ground_y
                            vel_y = 0.0
                        new_center_y = new_foot_y + half_height
                        thing.pos = [thing_pos.x, new_center_y, thing_pos.z]
                    else:
                        desired_center_y = ground_y + half_height
                        if abs(thing_pos.y - desired_center_y) > 1.0:
                            thing.pos = [thing_pos.x, desired_center_y, thing_pos.z]
                        vel_y = 0.0
                state['vel_y'] = vel_y

            # ---- Notarget: skip all player-targeting when cheat is active ----
            #      Monsters still gravity-fall and patrol, just don't chase/attack.
            if self.lt.notarget:
                thing.properties['is_shooting'] = False
                if mid in self.monster_states:
                    self.monster_states[mid]['anim_timer'] = 0.0
                self._update_monster_patrol(thing, state, mtype, delta)
                continue

            # ---- Resolve target (player or aggro monster for infighting) ----
            aggro_id = thing.properties.get('_aggro_target', None)
            aggro_monster = None
            if aggro_id is not None:
                aggro_monster = self._find_monster_by_id(aggro_id)
                if aggro_monster is None or aggro_monster.properties.get('dead', False):
                    # Aggro target gone — revert to player
                    thing.properties.pop('_aggro_target', None)
                    aggro_monster = None

            if aggro_monster is not None:
                target_pos = glm.vec3(aggro_monster.pos)
            else:
                target_pos = player_pos

            # ---- Line of sight check ----
            monster_eye = glm.vec3(thing_pos.x, thing_pos.y + 64.0, thing_pos.z)
            if aggro_monster is not None:
                target_eye = glm.vec3(target_pos.x, target_pos.y + 64.0, target_pos.z)
            else:
                target_eye = glm.vec3(player_pos.x, player_pos.y + self.lt.player.camera_height, player_pos.z)
            has_los = self._has_line_of_sight(monster_eye, target_eye)

            if self.monster_debug_active:
                self._debug_rays.append({
                    'start': [monster_eye.x, monster_eye.y, monster_eye.z],
                    'end':   [target_eye.x, target_eye.y, target_eye.z],
                    'color': 'green' if has_los else 'red',
                })

            distance = glm.distance(thing_pos, target_pos)

            if distance <= MONSTER_SIGHT_RANGE:
                # ---- Entered sight range ----
                if not state['in_sight']:
                    state['in_sight'] = True
                    if aggro_monster is None and self.lt.io_manager:
                        self.lt.io_manager.fire_output(thing, 'OnSeePlayer')
                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        tgt = aggro_monster.properties.get('name', '?') if aggro_monster else 'player'
                        debug_log("MonsterAI", f"{name} sees {tgt} (dist={distance:.0f})")

                # ---- Move toward target ----
                if distance > MONSTER_STOP_DISTANCE:
                    direction = target_pos - thing_pos
                    dir_len = glm.length(direction)
                    if dir_len > 0.001:
                        direction = direction / dir_len
                        if mtype != 'flying':
                            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
                        step = direction * MONSTER_MOVE_SPEED * delta
                        new_pos = thing_pos + step

                        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
                            thing.pos = [new_pos.x, new_pos.y, new_pos.z]
                        else:
                            # slide along walls
                            slide_x = glm.vec3(thing_pos.x + step.x, thing_pos.y, thing_pos.z)
                            slide_z = glm.vec3(thing_pos.x, thing_pos.y, thing_pos.z + step.z)
                            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_x.x, slide_x.y, slide_x.z]
                            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_z.x, slide_z.y, slide_z.z]
                            # else: blocked on both axes – no movement

                # ---- Shooting ----
                state['shoot_timer'] -= delta
                if state['shoot_timer'] <= 0.0 and has_los:
                    state['shoot_timer'] = MONSTER_SHOOT_INTERVAL
                    state['anim_timer'] = MONSTER_SHOOT_ANIM_TIME

                    damage = int(thing.properties.get('damage', 10))

                    if aggro_monster is not None:
                        # ---- Infighting: damage the aggro target monster ----
                        self._apply_monster_damage(aggro_monster, damage, attacker=thing)
                    else:
                        # ---- Check for crossfire (Doom-style infighting) ----
                        crossfire_victim = self._find_monster_in_crossfire(
                            thing, monster_eye, target_eye)
                        if crossfire_victim is not None:
                            self._apply_monster_damage(
                                crossfire_victim, damage, attacker=thing)
                            if self.monster_debug_active:
                                v_name = crossfire_victim.properties.get('name', '?')
                                a_name = thing.properties.get('name', '?')
                                debug_log("MonsterAI",
                                          f"CROSSFIRE: {a_name} hit {v_name} — infighting!")
                        else:
                            self.lt._apply_player_damage(damage)

                    self.lt.game_state.queue_sound({
                        'file': 'shoot.wav',
                        'volume': 0.6,
                        'entity_id': mid,
                    })

                    if self.lt.io_manager:
                        self.lt.io_manager.fire_output(thing, 'OnAttack')

                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        tgt = aggro_monster.properties.get('name', '?') if aggro_monster else 'player'
                        debug_log("MonsterAI", f"{name} attacks {tgt} for {damage} damage (LOS clear)")

                elif state['shoot_timer'] <= 0.0 and not has_los:
                    state['shoot_timer'] = 0.1   # re-check soon

                if state['anim_timer'] > 0.0:
                    state['anim_timer'] -= delta
                    thing.properties['is_shooting'] = True
                else:
                    thing.properties['is_shooting'] = False

            else:
                # ---- Out of sight ----
                if state['in_sight']:
                    state['in_sight'] = False
                    if aggro_monster is None and self.lt.io_manager:
                        self.lt.io_manager.fire_output(thing, 'OnLostPlayer')
                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{name} lost target (dist={distance:.0f})")

                thing.properties['is_shooting'] = False
                state['anim_timer'] = 0.0

                # If we had an aggro target but it's out of range, drop it
                if aggro_monster is not None:
                    thing.properties.pop('_aggro_target', None)

                # ---- Patrol behaviour (only when target not in sight) ----
                self._update_monster_patrol(thing, state, mtype, delta)

        # ---- Player death check (after all monsters processed) ----
        if self.lt.player_health <= 0 and not self.lt.player_dead:
            self.lt.player_dead = True
            if self.lt.io_manager:
                try:
                    from editor.things import PlayerStart
                    for thing in self.lt.things:
                        if isinstance(thing, PlayerStart):
                            self.lt.io_manager.fire_output(thing, 'OnPlayerDeath')
                            break
                except ImportError:
                    pass
            debug_log("MonsterAI", "Player has died.")

    # -------------------------------------------------------------------------
    # Monster infighting helpers
    # -------------------------------------------------------------------------

    def _find_monster_by_id(self, monster_id: int):
        """Return a living Monster thing by Python id, or None."""
        for t in self.lt.things:
            if isinstance(t, MonsterThing) and id(t) == monster_id:
                return t
        return None

    def _find_monster_in_crossfire(self, shooter, ray_start: glm.vec3,
                                    ray_end: glm.vec3):
        """Check if a living monster (other than the shooter) intersects
        the ray from ray_start to ray_end.  Returns the closest hit monster
        or None.  Used for Doom-style infighting — when monster A fires at
        the player and monster B is in the way, B takes the hit instead."""
        ray_dir = ray_end - ray_start
        ray_len = glm.length(ray_dir)
        if ray_len < 1.0:
            return None
        ray_dir = ray_dir / ray_len

        best_t = ray_len
        best_victim = None

        for t in self.lt.things:
            if not isinstance(t, MonsterThing):
                continue
            if t is shooter:
                continue
            if t.properties.get('dead', False) or t.properties.get('hidden', False):
                continue

            # Sphere intersection (same radius used by player shooting)
            radius = 64.0
            center = glm.vec3(t.pos[0], t.pos[1] + 64.0, t.pos[2])
            oc = ray_start - center
            a = glm.dot(ray_dir, ray_dir)
            b = 2.0 * glm.dot(oc, ray_dir)
            c = glm.dot(oc, oc) - radius * radius
            disc = b * b - 4.0 * a * c
            if disc < 0.0:
                continue
            hit_t = (-b - math.sqrt(disc)) / (2.0 * a)
            if 0.0 < hit_t < best_t:
                best_t = hit_t
                best_victim = t

        return best_victim

    def _apply_monster_damage(self, victim, damage: int, attacker=None):
        """Deal damage to a monster from another monster (infighting).
        Sets the victim's aggro target to the attacker so it retaliates."""
        health_raw = victim.properties.get('health', 100)
        try:
            health = int(health_raw)
        except (ValueError, TypeError):
            health = 100

        new_health = health - damage
        victim.properties['health'] = new_health

        if self.monster_debug_active:
            v_name = victim.properties.get('name', '?')
            a_name = attacker.properties.get('name', '?') if attacker else '?'
            debug_log("MonsterAI",
                       f"Infighting: {v_name} took {damage} dmg from {a_name} "
                       f"(health {health} -> {new_health})")

        if new_health <= 0:
            victim.properties['dead'] = True
            victim.properties.pop('is_shooting', None)
            victim.properties.pop('_aggro_target', None)
            if self.lt.io_manager:
                self.lt.io_manager.fire_output(victim, 'OnDeath')
        elif attacker is not None:
            # Retaliate — set aggro toward the attacker
            victim.properties['_aggro_target'] = id(attacker)
            # Wake the victim if it was asleep
            victim.properties['awake'] = True

    # -------------------------------------------------------------------------
    # Patrol system (PathNode navigation) — UNCHANGED
    # -------------------------------------------------------------------------

    def _update_monster_patrol(self, monster, state: Dict, mtype: str, delta: float):
        """Move monster along a chain of PathNodes when player is out of sight."""
        if not monster.properties.get('patrol', False):
            if state.get('patrol_at_target'):
                state['patrol_at_target'] = False
                state['patrol_chain'] = []
            state.pop('detour_node', None)
            return

        target_name = monster.properties.get('patrol_target', '') or ''
        if not target_name:
            return

        mname = monster.properties.get('name', '?')
        patrol_mode = str(monster.properties.get('patrol_mode', 'loop')).lower()
        if patrol_mode not in ('loop', 'ping_pong', 'once'):
            patrol_mode = 'loop'

        # ---- Build / rebuild chain when target changes ----
        chain_built_from = state.get('patrol_chain_built_from', '')
        if chain_built_from != target_name or not state.get('patrol_chain'):
            chain = self._build_patrol_chain(target_name, mtype)
            if not chain:
                if state.get('patrol_warn_missing') != target_name:
                    state['patrol_warn_missing'] = target_name
                    node = self._find_path_node_by_name(target_name)
                    if node is None:
                        debug_log("Pathfinding", f"Monster '{mname}' patrol_target '{target_name}' not found.")
                    else:
                        debug_log("Pathfinding", f"Monster '{mname}' (type={mtype}) rejected by PathNode '{target_name}' (affects_type={node.get_affects_type()}).")
                return
            state['patrol_chain'] = chain
            state['patrol_chain_built_from'] = target_name
            state['patrol_chain_idx'] = 0
            state['patrol_chain_dir'] = 1
            state['patrol_at_target'] = False
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            state['patrol_finished'] = False
            state['patrol_warn_missing'] = ''
            state['patrol_walking_to'] = ''
            state['detour_node'] = ''
            debug_log("Pathfinding", f"'{mname}' patrol chain built: {' -> '.join(chain)}  (mode={patrol_mode})")

        chain = state.get('patrol_chain', [])
        if not chain:
            return

        if state.get('patrol_finished'):
            return

        idx = state.get('patrol_chain_idx', 0)
        if idx < 0 or idx >= len(chain):
            idx = 0
            state['patrol_chain_idx'] = 0

        current_node_name = chain[idx]
        node = self._find_path_node_by_name(current_node_name)
        if node is None:
            state['patrol_chain'] = []
            return

        # ---- Waiting at node? ----
        if state.get('patrol_waiting'):
            remaining = state.get('patrol_wait_remaining', 0.0) - delta
            if remaining > 0.0:
                state['patrol_wait_remaining'] = remaining
                return
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            if self.lt.io_manager:
                self.lt.io_manager.fire_output(node, 'OnWaitEnd')
            debug_log("Pathfinding", f"'{mname}' finished waiting at '{current_node_name}'")
            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)
            if state.get('patrol_finished'):
                return
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return

        # ---- Distance to target node ----
        m_pos = glm.vec3(monster.pos)
        n_pos = glm.vec3(node.pos)
        if mtype == 'flying':
            to_node = n_pos - m_pos
            dist_to_node = glm.length(to_node)
        else:
            flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist_to_node = glm.length(flat)
            to_node = flat

        radius = node.get_radius()

        # ---- Arrived at current node? ----
        if dist_to_node <= radius:
            if not state.get('patrol_at_target'):
                state['patrol_at_target'] = True
                if self.lt.io_manager:
                    self.lt.io_manager.fire_output(node, 'OnMonsterArrived')
                debug_log("Pathfinding", f"'{mname}' arrived at '{current_node_name}' (dist={dist_to_node:.0f}, radius={radius:.0f})")

            wait = node.get_wait_time()
            if wait > 0.0 and not state.get('patrol_waiting'):
                state['patrol_waiting'] = True
                state['patrol_wait_remaining'] = wait
                if self.lt.io_manager:
                    self.lt.io_manager.fire_output(node, 'OnWaitStart')
                debug_log("Pathfinding", f"'{mname}' waiting {wait:.1f}s at '{current_node_name}'")
                return

            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)
            if state.get('patrol_finished'):
                return
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return
            n_pos = glm.vec3(node.pos)
            if mtype == 'flying':
                to_node = n_pos - m_pos
                dist_to_node = glm.length(to_node)
            else:
                flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
                dist_to_node = glm.length(flat)
                to_node = flat
            radius = node.get_radius()
            if dist_to_node <= radius:
                return

        # ---- Left a node? ----
        if state.get('patrol_at_target'):
            prev_name = chain[state.get('patrol_chain_idx', 0)]
            prev_node = self._find_path_node_by_name(prev_name)
            if prev_node is not None and self.lt.io_manager:
                self.lt.io_manager.fire_output(prev_node, 'OnMonsterLeft')
            state['patrol_at_target'] = False
            debug_log("Pathfinding", f"'{mname}' left radius of '{prev_name}'")

        if state.get('patrol_walking_to') != current_node_name:
            state['patrol_walking_to'] = current_node_name
            debug_log("Pathfinding", f"'{mname}' patrolling -> '{current_node_name}' (dist={dist_to_node:.0f})")

        # ---- Detour handling ----
        detour_name = state.get('detour_node', '')
        if detour_name:
            detour_node = self._find_path_node_by_name(detour_name)
            if detour_node is None or detour_node.properties.get('disabled', False):
                state['detour_node'] = ''
                debug_log("Pathfinding", f"'{mname}' detour node '{detour_name}' gone – resuming normal patrol")
            else:
                d_pos = glm.vec3(detour_node.pos)
                if mtype == 'flying':
                    d_vec = d_pos - m_pos
                else:
                    d_vec = glm.vec3(d_pos.x - m_pos.x, 0.0, d_pos.z - m_pos.z)
                d_dist = glm.length(d_vec)
                d_radius = detour_node.get_radius()
                if d_dist <= d_radius:
                    state['detour_node'] = ''
                    state['patrol_blocked_count'] = 0
                    debug_log("Pathfinding", f"'{mname}' reached detour node '{detour_name}' – resuming patrol toward '{current_node_name}'")
                    return
                to_node = d_vec
                dist_to_node = d_dist
                speed_mult = detour_node.get_patrol_speed()
        else:
            speed_mult = node.get_patrol_speed()

        # ---- Movement toward node ----
        dir_len = glm.length(to_node)
        if dir_len <= 0.001:
            return
        direction = to_node / dir_len
        if mtype != 'flying':
            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))

        step = direction * MONSTER_MOVE_SPEED * speed_mult * delta
        new_pos = m_pos + step

        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
            monster.pos = [new_pos.x, new_pos.y, new_pos.z]
            state['patrol_blocked_count'] = 0
        else:
            slide_x = glm.vec3(m_pos.x + step.x, m_pos.y, m_pos.z)
            slide_z = glm.vec3(m_pos.x, m_pos.y, m_pos.z + step.z)
            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_x.x, slide_x.y, slide_x.z]
                state['patrol_blocked_count'] = 0
            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_z.x, slide_z.y, slide_z.z]
                state['patrol_blocked_count'] = 0
            else:
                blocked_count = state.get('patrol_blocked_count', 0) + 1
                state['patrol_blocked_count'] = blocked_count
                if blocked_count == 1 or blocked_count % 120 == 0:
                    debug_log("Pathfinding", f"'{mname}' blocked by wall en route to '{current_node_name}' (stuck for {blocked_count} ticks)")

                if blocked_count >= MONSTER_STUCK_THRESHOLD and not state.get('detour_node'):
                    detour = self._find_nearby_detour_node(m_pos, current_node_name, mtype)
                    if detour:
                        state['detour_node'] = detour
                        state['patrol_blocked_count'] = 0
                        debug_log("Pathfinding", f"'{mname}' DETOUR: blocked at '{current_node_name}', switching to '{detour}'")

    def _advance_patrol_index(self, monster, state: Dict, chain: List[str], patrol_mode: str, mname: str):
        """Advance patrol index and fire OnMonsterLeft on the node we leave."""
        if not chain:
            return

        old_idx = state.get('patrol_chain_idx', 0)
        old_name = chain[old_idx] if old_idx < len(chain) else ''
        direction = state.get('patrol_chain_dir', 1)

        if old_name:
            old_node = self._find_path_node_by_name(old_name)
            if old_node is not None and self.lt.io_manager:
                self.lt.io_manager.fire_output(old_node, 'OnMonsterLeft')
        state['patrol_at_target'] = False
        state['patrol_walking_to'] = ''

        new_idx = old_idx + direction

        if patrol_mode == 'loop':
            if new_idx >= len(chain):
                new_idx = 0
            elif new_idx < 0:
                new_idx = len(chain) - 1

        elif patrol_mode == 'ping_pong':
            if new_idx >= len(chain):
                direction = -1
                new_idx = max(0, old_idx - 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding", f"'{mname}' ping_pong reverse at end of chain")
            elif new_idx < 0:
                direction = 1
                new_idx = min(len(chain) - 1, old_idx + 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding", f"'{mname}' ping_pong reverse at start of chain")
            state['patrol_chain_dir'] = direction

        elif patrol_mode == 'once':
            if new_idx >= len(chain) or new_idx < 0:
                state['patrol_finished'] = True
                debug_log("Pathfinding", f"'{mname}' completed 'once' patrol – holding at '{old_name}'")
                return

        state['patrol_chain_idx'] = new_idx
        next_name = chain[new_idx] if new_idx < len(chain) else ''
        if next_name:
            debug_log("Pathfinding", f"'{mname}' advancing → '{next_name}' (chain idx {new_idx}/{len(chain)-1})")

    def _build_patrol_chain(self, start_name: str, mtype: str) -> List[str]:
        """Walk next_node links to build an ordered patrol chain."""
        chain = []
        visited = set()
        current = start_name
        while current and current not in visited:
            node = self._find_path_node_by_name(current)
            if node is None:
                break
            if not node.accepts_monster_type(mtype):
                break
            visited.add(current)
            chain.append(current)
            current = node.get_next_node_name()
        return chain

    def _find_path_node_by_name(self, name: str):
        """Return PathNode thing with given name, or None.
        Uses LogicThread's name cache for O(1) lookup."""
        if not name or PathNode is None:
            return None
        # Use the O(1) name cache on the parent LogicThread
        entity = self.lt._name_cache.get(name)
        if entity is not None and isinstance(entity, PathNode):
            return entity
        return None

    def _find_nearby_detour_node(self, m_pos: glm.vec3, blocked_node_name: str, mtype: str) -> str:
        """Find a nearby PathNode that accepts this monster type to route around an obstacle."""
        if PathNode is None:
            return ''

        best_name = ''
        best_dist = MONSTER_DETOUR_RANGE + 1.0

        for t in self.lt.things:
            if not isinstance(t, PathNode):
                continue
            node_name = t.properties.get('name', '')
            if not node_name or node_name == blocked_node_name:
                continue
            if t.properties.get('disabled', False):
                continue
            if not t.accepts_monster_type(mtype):
                continue

            n_pos = glm.vec3(t.pos)
            if mtype == 'flying':
                diff = n_pos - m_pos
            else:
                diff = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist = glm.length(diff)
            if dist > MONSTER_DETOUR_RANGE or dist < 1.0:
                continue
            if dist >= best_dist:
                continue

            direction = diff / dist
            test_pos = m_pos + direction * MONSTER_MOVE_SPEED * 0.016
            if self._monster_overlaps_wall(test_pos.x, test_pos.y, test_pos.z, MONSTER_WALL_MARGIN):
                continue

            best_dist = dist
            best_name = node_name

        if best_name:
            debug_log("Pathfinding", f"Detour found: {best_name} at distance {best_dist:.0f}")
        return best_name

    # -------------------------------------------------------------------------
    # Helper methods — NOW DELEGATE TO SPATIAL GRID
    # -------------------------------------------------------------------------

    def _has_line_of_sight(self, start: glm.vec3, end: glm.vec3) -> bool:
        """Return True if ray from start to end hits no solid wall brush."""
        if self._grid:
            return self._grid.has_line_of_sight(start, end, self.lt.intersect_ray_aabb)

        # Fallback: full brush scan (should not happen in play mode)
        ray_dir = end - start
        ray_len = glm.length(ray_dir)
        if ray_len < 0.001:
            return True
        ray_dir = ray_dir / ray_len

        for brush in self.lt.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5
            hit, dist = self.lt.intersect_ray_aabb(start, ray_dir, b_min, b_max)
            if hit and dist < ray_len - 0.1:
                return False
        return True

    def _monster_raycast_down(self, x: float, z: float, start_y: float = 10000.0) -> Optional[float]:
        """Return Y of the highest solid brush surface below (x, z), or None."""
        if self._grid:
            return self._grid.raycast_down(x, z, start_y)

        # Fallback
        best_y = None
        for brush in self.lt.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5
            by_max = pos[1] + size[1] * 0.5

            if bx_min <= x <= bx_max and bz_min <= z <= bz_max:
                if by_max <= start_y:
                    if best_y is None or by_max > best_y:
                        best_y = by_max
        return best_y

    def _monster_overlaps_wall(self, mx: float, my: float, mz: float, margin: float) -> bool:
        """Check if a monster-sized box at (mx, my, mz) overlaps any solid wall brush."""
        if self._grid:
            return self._grid.overlaps_wall(mx, my, mz, margin)

        # Fallback
        for brush in self.lt.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            by_min = pos[1] - size[1] * 0.5
            by_max = pos[1] + size[1] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5

            m_xmin = mx - margin
            m_xmax = mx + margin
            m_ymin = my
            m_ymax = my + 128.0
            m_zmin = mz - margin
            m_zmax = mz + margin

            if (m_xmax > bx_min and m_xmin < bx_max and
                m_ymax > by_min and m_ymin < by_max and
                m_zmax > bz_min and m_zmin < bz_max):
                return True
        return False
