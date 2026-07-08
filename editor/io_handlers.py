"""
Input Handlers for Fio I/O System

This module registers all input handlers that define what happens when
an input is called on an entity.

Handler signature: (entity, parameter: str, logic_thread) -> None
"""

from .io_system import IOManager
import glm
import os

# Import debug logger - with fallback to print if not available
try:
    from .debug_console import debug_log
except ImportError:
    try:
        from editor.debug_console import debug_log
    except ImportError:
        def debug_log(category, message):
            print(f"[{category}] {message}")

try:
    from editor.things import ENTITY_TYPES
except ImportError:
    ENTITY_TYPES = {}


def register_all_input_handlers(io_manager: IOManager):
    """Register all input handlers with the I/O manager."""
    
    # ==========================================================================
    # LIGHT INPUTS
    # ==========================================================================
    
    def light_turn_on(entity, param, logic):
        entity.properties['state'] = 'on'
        logic.io_manager.fire_output(entity, 'OnTurnedOn')
    
    def light_turn_off(entity, param, logic):
        entity.properties['state'] = 'off'
        logic.io_manager.fire_output(entity, 'OnTurnedOff')
    
    def light_toggle(entity, param, logic):
        current = entity.properties.get('state', 'on')
        if current == 'on':
            light_turn_off(entity, param, logic)
        else:
            light_turn_on(entity, param, logic)
    
    def light_set_brightness(entity, param, logic):
        try:
            value = float(param) if param else 1.0
            entity.properties['intensity'] = max(0.0, min(10.0, value))
        except ValueError:
            pass
    
    def light_set_color(entity, param, logic):
        """Set color from 'R G B' string (0-255)."""
        try:
            parts = param.split()
            if len(parts) >= 3:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                entity.properties['colour'] = [r, g, b]
        except (ValueError, IndexError):
            pass
    
    io_manager.register_input_handler('light', 'turnon', light_turn_on)
    io_manager.register_input_handler('light', 'turnoff', light_turn_off)
    io_manager.register_input_handler('light', 'toggle', light_toggle)
    io_manager.register_input_handler('light', 'setbrightness', light_set_brightness)
    io_manager.register_input_handler('light', 'setcolor', light_set_color)
    
    # ==========================================================================
    # DOOR INPUTS
    # ==========================================================================
    
    def door_open(entity, param, logic):
        """Open a door brush."""
        idx = _get_brush_index(entity, logic)
        if idx < 0:
            return
        
        if idx not in logic.door_states:
            if 'original_pos' not in entity:
                entity['original_pos'] = list(entity['pos'])
            logic.door_states[idx] = {
                'progress': 0.0,
                'state': 'closed',
                'open_timer': 0.0
            }
        
        state = logic.door_states[idx]
        if state['state'] == 'closed':
            state['state'] = 'opening'
            logic.io_manager.fire_output(entity, 'OnOpen')
    
    def door_close(entity, param, logic):
        """Close a door brush."""
        idx = _get_brush_index(entity, logic)
        if idx < 0 or idx not in logic.door_states:
            return
        
        state = logic.door_states[idx]
        if state['state'] == 'open':
            state['state'] = 'closing'
            logic.io_manager.fire_output(entity, 'OnClose')
    
    def door_toggle(entity, param, logic):
        """Toggle door open/closed."""
        idx = _get_brush_index(entity, logic)
        if idx < 0:
            return
        
        if idx in logic.door_states:
            state = logic.door_states[idx]
            if state['state'] == 'closed':
                door_open(entity, param, logic)
            elif state['state'] == 'open':
                door_close(entity, param, logic)
        else:
            door_open(entity, param, logic)
    
    def door_lock(entity, param, logic):
        entity['door_locked'] = True
    
    def door_unlock(entity, param, logic):
        entity['door_locked'] = False
    
    def door_set_speed(entity, param, logic):
        try:
            entity['speed'] = float(param) if param else 128.0
        except ValueError:
            pass
    
    io_manager.register_input_handler('door', 'open', door_open)
    io_manager.register_input_handler('door', 'close', door_close)
    io_manager.register_input_handler('door', 'toggle', door_toggle)
    io_manager.register_input_handler('door', 'lock', door_lock)
    io_manager.register_input_handler('door', 'unlock', door_unlock)
    io_manager.register_input_handler('door', 'setspeed', door_set_speed)
    
    # ==========================================================================
    # MOVER INPUTS
    # ==========================================================================
    
    def mover_open(entity, param, logic):
        entity['start_on'] = True
        idx = _get_brush_index(entity, logic)
        if idx >= 0 and idx in logic.mover_states:
            logic.mover_states[idx]['forward'] = True
    
    def mover_close(entity, param, logic):
        entity['start_on'] = True
        idx = _get_brush_index(entity, logic)
        if idx >= 0 and idx in logic.mover_states:
            logic.mover_states[idx]['forward'] = False
    
    def mover_toggle(entity, param, logic):
        entity['start_on'] = not entity.get('start_on', False)
    
    def mover_set_position(entity, param, logic):
        idx = _get_brush_index(entity, logic)
        if idx < 0:
            return
        try:
            value = max(0.0, min(1.0, float(param)))
            if idx in logic.mover_states:
                logic.mover_states[idx]['progress'] = value
        except ValueError:
            pass
    
    def mover_enable(entity, param, logic):
        entity['start_on'] = True
    
    def mover_disable(entity, param, logic):
        entity['start_on'] = False
    
    io_manager.register_input_handler('mover', 'open', mover_open)
    io_manager.register_input_handler('mover', 'close', mover_close)
    io_manager.register_input_handler('mover', 'toggle', mover_toggle)
    io_manager.register_input_handler('mover', 'setposition', mover_set_position)
    io_manager.register_input_handler('mover', 'enable', mover_enable)
    io_manager.register_input_handler('mover', 'disable', mover_disable)

    # ==========================================================================
    # MOVER — PathNode waypoint inputs
    # ==========================================================================

    def mover_follow_path(entity, param, logic):
        """Switch a mover from direction-based to PathNode chain movement."""
        idx = _get_brush_index(entity, logic)
        if idx < 0:
            return
        target = param or entity.get('path_target', '')
        if not target:
            return

        # ✅ Guard: ensure the state dictionary exists
        if not hasattr(logic, 'mover_path_states'):
            logic.mover_path_states = {}

        entity['path_target'] = target
        entity['start_on'] = True
        if idx not in logic.mover_path_states:
            logic.mover_path_states[idx] = {
                'current_node': target,
                'lerp_t':       0.0,
                'origin':       list(entity['pos']),
                'waiting':      False,
                'wait_remaining': 0.0,
            }
        logic.mover_states.pop(idx, None)

    def mover_stop_path(entity, param, logic):
        """Stop PathNode following and hold position."""
        idx = _get_brush_index(entity, logic)
        if idx >= 0:
            # ✅ Guard: use getattr with default empty dict, then pop safely
            states = getattr(logic, 'mover_path_states', None)
            if states is not None:
                states.pop(idx, None)

    def mover_set_path_target(entity, param, logic):
        """Change the target PathNode name for this mover."""
        if param:
            entity['path_target'] = param

    io_manager.register_input_handler('mover', 'followpath',    mover_follow_path)
    io_manager.register_input_handler('mover', 'stoppath',      mover_stop_path)
    io_manager.register_input_handler('mover', 'setpathtarget', mover_set_path_target)

    # ==========================================================================
    # TRIGGER INPUTS
    # ==========================================================================
    
    def trigger_enable(entity, param, logic):
        entity['disabled'] = False
        debug_log('Trigger', f"Enabled trigger '{entity.get('name', 'unnamed')}'")
    
    def trigger_disable(entity, param, logic):
        entity['disabled'] = True
        debug_log('Trigger', f"Disabled trigger '{entity.get('name', 'unnamed')}'")
    
    def trigger_toggle(entity, param, logic):
        entity['disabled'] = not entity.get('disabled', False)
    
    def trigger_touch_test(entity, param, logic):
        if not logic.player:
            return
        
        pos = glm.vec3(entity['pos'])
        size = glm.vec3(entity['size'])
        half_size = size / 2.0
        min_b = pos - half_size
        max_b = pos + half_size
        
        player_pos = logic.player.pos
        if (min_b.x <= player_pos.x <= max_b.x and
            min_b.y <= player_pos.y <= max_b.y and
            min_b.z <= player_pos.z <= max_b.z):
            logic.io_manager.fire_output(entity, 'OnTrigger')
    
    io_manager.register_input_handler('trigger', 'enable', trigger_enable)
    io_manager.register_input_handler('trigger', 'disable', trigger_disable)
    io_manager.register_input_handler('trigger', 'toggle', trigger_toggle)
    io_manager.register_input_handler('trigger', 'touchtest', trigger_touch_test)

    # ==========================================================================
    # TRIGGER — teleport inputs
    # ==========================================================================

    def trigger_teleport(entity, param, logic):
        """Teleport the player to the named PathNode."""
        target_name = param or entity.get('target_node', '')
        node = logic._find_path_node_by_name(target_name)
        if not node or not logic.player:
            return
        dest = glm.vec3(node.pos[0], node.pos[1], node.pos[2])
        logic.player.pos = dest
        # Zero velocity to prevent carry-over momentum
        logic.player.velocity = glm.vec3(0, 0, 0)
        if logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnTeleport')
        debug_log("IO", f"Trigger teleported player → '{target_name}' ({dest.x:.0f}, {dest.y:.0f}, {dest.z:.0f})")

    def trigger_set_target_node(entity, param, logic):
        """Change the target PathNode name for this trigger."""
        if param:
            entity['target_node'] = param

    io_manager.register_input_handler('trigger', 'teleport',      trigger_teleport)
    io_manager.register_input_handler('trigger', 'settargetnode', trigger_set_target_node)

    # ==========================================================================
    # SPEAKER INPUTS
    # ==========================================================================
    
    def speaker_play(entity, param, logic):
        """Start playing sound - queues to main thread via game_state."""
        entity_name = entity.properties.get('name', 'unnamed')
        sound_file = entity.properties.get('sound_file', '')
        volume = float(entity.properties.get('volume', 1.0))
        
        debug_log('Speaker', f"PlaySound called on '{entity_name}'")
        debug_log('Speaker', f"  sound_file='{sound_file}', volume={volume}")
        
        entity.properties['state'] = 'on'
        speaker_id = id(entity)
        logic.active_speakers.add(speaker_id)
        
        if not sound_file:
            debug_log('Error', f"No sound file configured for speaker '{entity_name}'!")
            return
        
        # Get game_state - try multiple paths for robustness
        game_state = None
        
        # Path 1: From logic thread directly
        if hasattr(logic, 'game_state') and logic.game_state is not None:
            game_state = logic.game_state
            debug_log('Speaker', f"  Found game_state via logic.game_state")
        
        # Path 2: From io_manager
        if game_state is None and hasattr(logic, 'io_manager'):
            gs = logic.io_manager.get_game_state()
            if gs is not None:
                game_state = gs
                debug_log('Speaker', f"  Found game_state via io_manager")
        
        if game_state is None:
            debug_log('Error', f"Could not find game_state for speaker '{entity_name}'!")
            return
        
        # Queue the sound for the main thread to play (thread-safe)
        game_state.queue_sound({
            'file': sound_file,
            'volume': volume,
            'entity_id': speaker_id
        })
        debug_log('Speaker', f"  Queued '{sound_file}'")
        
        # Fire output event
        logic.io_manager.fire_output(entity, 'OnSoundStarted')
    
    def speaker_stop(entity, param, logic):
        entity.properties['state'] = 'off'
        speaker_id = id(entity)
        logic.active_speakers.discard(speaker_id)
        debug_log('Speaker', f"Stopped speaker '{entity.properties.get('name', 'unnamed')}'")
        logic.io_manager.fire_output(entity, 'OnSoundFinished')
    
    def speaker_toggle(entity, param, logic):
        current = entity.properties.get('state', 'off')
        if current == 'on':
            speaker_stop(entity, param, logic)
        else:
            speaker_play(entity, param, logic)
    
    def speaker_set_volume(entity, param, logic):
        try:
            entity.properties['volume'] = max(0.0, min(1.0, float(param)))
        except ValueError:
            pass
    
    io_manager.register_input_handler('speaker', 'playsound', speaker_play)
    io_manager.register_input_handler('speaker', 'stopsound', speaker_stop)
    io_manager.register_input_handler('speaker', 'toggle', speaker_toggle)
    io_manager.register_input_handler('speaker', 'setvolume', speaker_set_volume)
    
    # ==========================================================================
    # PICKUP INPUTS
    # ==========================================================================
    
    def pickup_enable(entity, param, logic):
        entity.properties['disabled'] = False
    
    def pickup_disable(entity, param, logic):
        entity.properties['disabled'] = True
    
    def pickup_respawn(entity, param, logic):
        entity.properties['collected'] = False
        # FIX#3: use id(entity) — matches new collected_pickups key scheme
        logic.collected_pickups.discard(id(entity))
        logic.io_manager.fire_output(entity, 'OnRespawn')
    
    def pickup_set_value(entity, param, logic):
        try:
            entity.properties['value'] = int(param)
        except ValueError:
            pass
    
    io_manager.register_input_handler('pickup', 'enable', pickup_enable)
    io_manager.register_input_handler('pickup', 'disable', pickup_disable)
    io_manager.register_input_handler('pickup', 'respawn', pickup_respawn)
    io_manager.register_input_handler('pickup', 'setvalue', pickup_set_value)
    
    # ==========================================================================
    # LOGIC_RELAY INPUTS
    # ==========================================================================
    
    def relay_trigger(entity, param, logic):
        if entity.properties.get('disabled', False):
            return
        logic.io_manager.fire_output(entity, 'OnTrigger')
    
    def relay_enable(entity, param, logic):
        entity.properties['disabled'] = False
    
    def relay_disable(entity, param, logic):
        entity.properties['disabled'] = True
    
    def relay_toggle(entity, param, logic):
        entity.properties['disabled'] = not entity.properties.get('disabled', False)
    
    io_manager.register_input_handler('logic_relay', 'trigger', relay_trigger)
    io_manager.register_input_handler('logic_relay', 'enable', relay_enable)
    io_manager.register_input_handler('logic_relay', 'disable', relay_disable)
    io_manager.register_input_handler('logic_relay', 'toggle', relay_toggle)
    
    # ==========================================================================
    # LOGIC_GATE INPUTS
    # ==========================================================================
    
    def gate_trigger(entity, param, logic):
        if entity.properties.get('disabled', False):
            return
        
        gate_name = entity.name
        logic_type = entity.properties.get('logic_type', 'AND')
        
        if gate_name not in logic.gate_inputs:
            logic.gate_inputs[gate_name] = set()
        
        source_name = param if param else 'anonymous'
        if source_name in logic.gate_inputs[gate_name]:
            logic.gate_inputs[gate_name].remove(source_name)
        else:
            logic.gate_inputs[gate_name].add(source_name)
        
        active_inputs = len(logic.gate_inputs[gate_name])
        
        total_possible = 0
        from .io_system import get_connections
        for b in logic.brushes:
            for conn in get_connections(b):
                if conn.target_name == gate_name:
                    total_possible += 1
        for t in logic.things:
            if t is not entity:
                for conn in get_connections(t):
                    if conn.target_name == gate_name:
                        total_possible += 1
        
        if total_possible == 0:
            total_possible = 1
        
        should_fire = False
        if logic_type == 'AND':
            should_fire = (active_inputs >= total_possible)
        elif logic_type == 'OR':
            should_fire = (active_inputs > 0)
        elif logic_type == 'XOR':
            should_fire = (active_inputs == 1)
        elif logic_type == 'NAND':
            should_fire = (active_inputs < total_possible)
        elif logic_type == 'NOR':
            should_fire = (active_inputs == 0)
        
        if should_fire:
            logic.io_manager.fire_output(entity, 'OnTrigger')
    
    def gate_reset(entity, param, logic):
        gate_name = entity.name
        if gate_name in logic.gate_inputs:
            logic.gate_inputs[gate_name].clear()
    
    io_manager.register_input_handler('logic_gate', 'trigger', gate_trigger)
    io_manager.register_input_handler('logic_gate', 'reset', gate_reset)
    io_manager.register_input_handler('logic_gate', 'enable', relay_enable)
    io_manager.register_input_handler('logic_gate', 'disable', relay_disable)
    
    # ==========================================================================
    # LOGIC_TIMER INPUTS
    # ==========================================================================
    
    def timer_enable(entity, param, logic):
        entity.properties['timer_enabled'] = True
        if not hasattr(logic, 'timer_states'):
            logic.timer_states = {}
        entity_id = id(entity)
        interval = float(entity.properties.get('interval', 1.0))
        logic.timer_states[entity_id] = {
            'remaining': interval,
            'interval': interval
        }
    
    def timer_disable(entity, param, logic):
        entity.properties['timer_enabled'] = False
    
    def timer_toggle(entity, param, logic):
        if entity.properties.get('timer_enabled', False):
            timer_disable(entity, param, logic)
        else:
            timer_enable(entity, param, logic)
    
    def timer_fire(entity, param, logic):
        logic.io_manager.fire_output(entity, 'OnTimer')
    
    def timer_set_time(entity, param, logic):
        try:
            entity.properties['interval'] = max(0.1, float(param))
        except ValueError:
            pass
    
    io_manager.register_input_handler('logic_timer', 'enable', timer_enable)
    io_manager.register_input_handler('logic_timer', 'disable', timer_disable)
    io_manager.register_input_handler('logic_timer', 'toggle', timer_toggle)
    io_manager.register_input_handler('logic_timer', 'firetimer', timer_fire)
    io_manager.register_input_handler('logic_timer', 'settime', timer_set_time)
    
    # ==========================================================================
    # MODEL INPUTS
    # ==========================================================================
    
    def model_enable(entity, param, logic):
        entity.properties['hidden'] = False
    
    def model_disable(entity, param, logic):
        entity.properties['hidden'] = True
    
    io_manager.register_input_handler('model', 'enable', model_enable)
    io_manager.register_input_handler('model', 'disable', model_disable)
    
    # ==========================================================================
    # MONSTER INPUTS
    # ==========================================================================
    
    def monster_kill(entity, param, logic):
        entity.properties['_kill'] = True
        logic.io_manager.fire_output(entity, 'OnDeath')
    
    io_manager.register_input_handler('monster', 'kill', monster_kill)
    io_manager.register_input_handler('monster', 'enable', relay_enable)
    io_manager.register_input_handler('monster', 'disable', relay_disable)

    def monster_wake(entity, param, logic):
        """Wake a dormant (triggered=True) monster via I/O."""
        entity.properties['awake'] = True
        entity.properties['triggered'] = False   # clear dormant flag

    def monster_set_target(entity, param, logic):
        """Override pursuit target by entity name (empty string = back to player)."""
        entity.properties['target_name'] = param.strip() if param else ''

    io_manager.register_input_handler('monster', 'wake', monster_wake)
    io_manager.register_input_handler('monster', 'settarget', monster_set_target)

    # ==========================================================================
    # BRUSH HIDE / SHOW / TINT INPUTS
    # (Brushes are dicts — these handlers work for brush, door, mover, trigger)
    # ==========================================================================

    def brush_hide(entity, param, logic):
        """Hide a brush (set hidden flag — renderer skips it)."""
        entity['hidden'] = True
        name = entity.get('name', 'unnamed')
        debug_log('IO', f"Brush '{name}' hidden")

    def brush_show(entity, param, logic):
        """Show a brush (clear hidden flag)."""
        entity['hidden'] = False
        name = entity.get('name', 'unnamed')
        debug_log('IO', f"Brush '{name}' shown")

    def brush_toggle_vis(entity, param, logic):
        """Toggle brush visibility."""
        entity['hidden'] = not entity.get('hidden', False)
        name = entity.get('name', 'unnamed')
        state = "hidden" if entity.get('hidden') else "visible"
        debug_log('IO', f"Brush '{name}' toggled → {state}")

    def brush_set_tint(entity, param, logic):
        """Set tint colour on a brush.  Param: 'R G B' (0-255)."""
        try:
            parts = param.split()
            if len(parts) >= 3:
                r = max(0, min(255, int(parts[0])))
                g = max(0, min(255, int(parts[1])))
                b = max(0, min(255, int(parts[2])))
                entity['tint'] = [r, g, b]
                name = entity.get('name', 'unnamed')
                debug_log('IO', f"Brush '{name}' tint set to ({r}, {g}, {b})")
        except (ValueError, IndexError):
            debug_log('Error', f"SetTint: bad parameter '{param}' — expected 'R G B'")

    def brush_clear_tint(entity, param, logic):
        """Remove tint override from a brush."""
        entity.pop('tint', None)
        name = entity.get('name', 'unnamed')
        debug_log('IO', f"Brush '{name}' tint cleared")

    # Register for every brush-based type
    for btype in ('brush', 'door', 'mover', 'trigger'):
        io_manager.register_input_handler(btype, 'hide', brush_hide)
        io_manager.register_input_handler(btype, 'show', brush_show)
        io_manager.register_input_handler(btype, 'togglevisibility', brush_toggle_vis)
        io_manager.register_input_handler(btype, 'settint', brush_set_tint)
        io_manager.register_input_handler(btype, 'cleartint', brush_clear_tint)

    # ==========================================================================
    # THING (ENTITY) HIDE / SHOW INPUTS
    # (Things have .properties dict — covers monster, light, speaker, pickup, model)
    # ==========================================================================

    def thing_hide(entity, param, logic):
        """Hide a thing entity."""
        entity.properties['hidden'] = True
        name = entity.properties.get('name', 'unnamed')
        debug_log('IO', f"Entity '{name}' hidden")

    def thing_show(entity, param, logic):
        """Show a thing entity."""
        entity.properties['hidden'] = False
        name = entity.properties.get('name', 'unnamed')
        debug_log('IO', f"Entity '{name}' shown")

    def thing_toggle_vis(entity, param, logic):
        """Toggle thing visibility."""
        entity.properties['hidden'] = not entity.properties.get('hidden', False)
        name = entity.properties.get('name', 'unnamed')
        state = "hidden" if entity.properties.get('hidden') else "visible"
        debug_log('IO', f"Entity '{name}' toggled → {state}")

    # Register for every thing-based type that declares Hide/Show
    for ttype in ('monster', 'light', 'speaker', 'pickup', 'model'):
        io_manager.register_input_handler(ttype, 'hide', thing_hide)
        io_manager.register_input_handler(ttype, 'show', thing_show)
        io_manager.register_input_handler(ttype, 'togglevisibility', thing_toggle_vis)

    # ==========================================================================
    # LEVEL CHANGER INPUTS
    # ==========================================================================
    
    def levelchanger_changelevel(entity, param, logic):
        # We route to change_level() because it is more robust
        if hasattr(entity, 'change_level'):
            entity.change_level(param)
            
    io_manager.register_input_handler('levelchanger', 'changelevel', levelchanger_changelevel)
    io_manager.register_input_handler('levelchanger', 'trigger', levelchanger_changelevel)

    # ==========================================================================
    # LOGIC CAMERA INPUTS
    # ==========================================================================

    def camera_start(entity, param, logic):
        """Begin the cinematic camera sequence along a PathNode chain."""
        target = entity.properties.get('path_target', '')
        node = logic._find_path_node_by_name(target)
        if not node:
            debug_log("IO", f"LogicCamera '{entity.name}': path_target "
                      f"'{target}' not found — aborting start.")
            return
        speed = float(entity.properties.get('speed', 200.0))
        fov   = float(entity.properties.get('fov_override', 0.0))
        logic.cinematic_state = {
            'active':       True,
            'paused':       False,
            'entity':       entity,
            'current_node': target,
            'lerp_t':       0.0,
            'origin':       list(node.pos),
            'speed':        speed,
            'fov':          fov if fov > 0 else None,
            'look_ahead':   entity.properties.get('look_ahead', True),
        }
        if logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnStart')

    def camera_stop(entity, param, logic):
        """Abort and return camera to the player."""
        logic.cinematic_state = None

    def camera_pause(entity, param, logic):
        """Freeze camera at current chain position."""
        if logic.cinematic_state:
            logic.cinematic_state['paused'] = True

    def camera_resume(entity, param, logic):
        """Continue a paused sequence."""
        if logic.cinematic_state:
            logic.cinematic_state['paused'] = False

    def camera_set_speed(entity, param, logic):
        """Override travel speed."""
        if logic.cinematic_state:
            try:
                logic.cinematic_state['speed'] = max(1.0, float(param))
            except (TypeError, ValueError):
                pass

    io_manager.register_input_handler('logic_camera', 'start',    camera_start)
    io_manager.register_input_handler('logic_camera', 'stop',     camera_stop)
    io_manager.register_input_handler('logic_camera', 'pause',    camera_pause)
    io_manager.register_input_handler('logic_camera', 'resume',   camera_resume)
    io_manager.register_input_handler('logic_camera', 'setspeed', camera_set_speed)

    # ==========================================================================
    # LOGIC SPAWNER INPUTS
    # ==========================================================================

    def spawner_spawn(entity, param, logic):
        """Spawn one entity at the target PathNode."""
        if entity.properties.get('disabled', False):
            return

        # ---- target node resolution with fallback ----
        target_name = entity.properties.get('target_node', '')
        node = None
        if target_name:
            node = logic._find_path_node_by_name(target_name)
            if not node:
                debug_log("IO", f"LogicSpawner '{entity.name}': target_node '{target_name}' not found. Falling back to spawner position.")
        else:
            debug_log("IO", f"LogicSpawner '{entity.name}': no target_node set. Using spawner position.")

        spawn_pos = list(node.pos) if node else list(entity.pos)

        # ---- spawn count limit ----
        max_spawn = int(entity.properties.get('max_spawn', 0))
        spawn_count = entity.properties.get('_spawn_count', 0)
        if max_spawn > 0 and spawn_count >= max_spawn:
            if logic.io_manager:
                logic.io_manager.fire_output(entity, 'OnMaxReached')
            debug_log("IO", f"LogicSpawner '{entity.name}': max_spawn reached ({max_spawn})")
            return

        # ---- spawn type (case‑insensitive) ----
        spawn_type = entity.properties.get('spawn_type', 'Monster')
        # ENTITY_TYPES is now imported from editor.things
        cls = ENTITY_TYPES.get(spawn_type)
        if cls is None:
            # case‑insensitive fallback
            for key, value in ENTITY_TYPES.items():
                if key.lower() == spawn_type.lower():
                    cls = value
                    break
        if cls is None:
            debug_log("Error", f"LogicSpawner: unknown spawn_type '{spawn_type}'")
            return

        # ---- extra properties (spawn_properties) ----
        extra_props = dict(entity.properties.get('spawn_properties', {}))

        # ---- RANDOM MONSTER HANDLING ----
        if spawn_type == 'Monster' and extra_props.get('random', False):
            import random
            from engine.monster_constants import MONSTER_VARIANTS

            # Choose random monster type
            monster_types = ['human', 'flying']
            chosen_type = random.choice(monster_types)
            extra_props['monster_type'] = chosen_type

            # Choose random variant for that type (including <None>)
            variants = ['<None>'] + MONSTER_VARIANTS.get(chosen_type, [])
            chosen_variant = random.choice(variants)
            extra_props['variant'] = chosen_variant

            debug_log("IO", f"LogicSpawner random spawn: type={chosen_type}, variant={chosen_variant}")

        # ---- create the new entity ----
        new_thing = cls(pos=spawn_pos, properties=extra_props)
        logic.editor_state.things.append(new_thing)
        entity.properties['_spawn_count'] = spawn_count + 1

        # ---- rebuild caches so the new entity can be found by name/id ----
        if hasattr(logic, '_build_entity_caches'):
            logic._build_entity_caches()

        # ---- fire outputs ----
        if logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnSpawn')

        debug_log("IO", f"LogicSpawner '{entity.name}' spawned '{spawn_type}' at {spawn_pos}")

    def spawner_enable(entity, param, logic):
        entity.properties['disabled'] = False

    def spawner_disable(entity, param, logic):
        entity.properties['disabled'] = True

    def spawner_set_target(entity, param, logic):
        """Change spawn location to a different PathNode."""
        if param:
            entity.properties['target_node'] = param

    io_manager.register_input_handler('logic_spawner', 'spawn',         spawner_spawn)
    io_manager.register_input_handler('logic_spawner', 'enable',        spawner_enable)
    io_manager.register_input_handler('logic_spawner', 'disable',       spawner_disable)
    io_manager.register_input_handler('logic_spawner', 'settargetnode', spawner_set_target)

    # ==========================================================================
    # LOGIC KEYVALUE STORE INPUTS
    # ==========================================================================

    def keyvalue_setvalue(entity, param, logic):
        """Set a key/value pair. Parameter format: 'key=value' or just 'key' (value='1')."""
        if not param:
            return
        if '=' in param:
            key, value = param.split('=', 1)
        else:
            key, value = param.strip(), "1"
        success = entity.set_value(key.strip(), value.strip())
        store_name = entity.properties.get('store_name', entity.properties.get('name', 'unknown'))
        if success:
            debug_log("IO", f"LogicKeyValueStore '{store_name}': set '{key}' = '{value}'")
            logic.io_manager.fire_output(entity, 'OnValueSet')
        else:
            debug_log("IO", f"LogicKeyValueStore '{store_name}': FAILED to set '{key}' (store full?)")
            logic.io_manager.fire_output(entity, 'OnStoreFull')

    def keyvalue_getvalue(entity, param, logic):
        """Read a key and fire OnValueRead with the value as parameter."""
        if not param:
            logic.io_manager.fire_output(entity, 'OnKeyNotFound')
            return
        key = param.strip()
        value = entity.get_value(key, "<missing>")
        if value == "<missing>":
            logic.io_manager.fire_output(entity, 'OnKeyNotFound')
        else:
            logic.io_manager.fire_output(entity, 'OnValueRead')

    def keyvalue_clearkey(entity, param, logic):
        """Remove a single key."""
        if not param:
            return
        key = param.strip()
        existed = entity.clear_key(key)
        if existed:
            logic.io_manager.fire_output(entity, 'OnKeyCleared')

    def keyvalue_clearall(entity, param, logic):
        """Remove all keys."""
        entity.clear_all()

    def keyvalue_copyfrom(entity, param, logic):
        """Copy all keys from another LogicKeyValueStore by store_name."""
        if not param:
            return
        other_name = param.strip()
        success = entity.copy_from(other_name)
        if success and logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnValueSet')

    def keyvalue_increment(entity, param, logic):
        """Increment an integer value. Parameter: 'key,amount' or just 'key'."""
        if not param:
            return
        if ',' in param:
            key, amount_str = param.split(',', 1)
            try:
                amount = int(amount_str.strip())
            except ValueError:
                amount = 1
        else:
            key, amount = param.strip(), 1
        new_val = entity.increment(key.strip(), amount)
        if logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnValueSet')

    def keyvalue_decrement(entity, param, logic):
        """Decrement an integer value. Parameter: 'key,amount' or just 'key'."""
        if not param:
            return
        if ',' in param:
            key, amount_str = param.split(',', 1)
            try:
                amount = int(amount_str.strip())
            except ValueError:
                amount = 1
        else:
            key, amount = param.strip(), 1
        new_val = entity.decrement(key.strip(), amount)
        if logic.io_manager:
            logic.io_manager.fire_output(entity, 'OnValueSet')

    io_manager.register_input_handler('logic_keyvalue', 'setvalue',   keyvalue_setvalue)
    io_manager.register_input_handler('logic_keyvalue', 'getvalue',   keyvalue_getvalue)
    io_manager.register_input_handler('logic_keyvalue', 'clearkey',   keyvalue_clearkey)
    io_manager.register_input_handler('logic_keyvalue', 'clearall',   keyvalue_clearall)
    io_manager.register_input_handler('logic_keyvalue', 'copyfrom',   keyvalue_copyfrom)
    io_manager.register_input_handler('logic_keyvalue', 'increment',  keyvalue_increment)
    io_manager.register_input_handler('logic_keyvalue', 'decrement',  keyvalue_decrement)


    # ==========================================================================
    # PORTAL INPUTS
    # ==========================================================================

    def portal_enable(entity, param, logic):
        """Activate the portal — fades it in."""
        entity.properties['active'] = True
        if hasattr(entity, '_fade_target'):
            entity._fade_target = 1.0        # fade in
        name = entity.properties.get('name', 'unnamed')
        debug_log('IO', f"Portal '{name}' enabled")
        logic.io_manager.fire_output(entity, 'OnEnabled')

    def portal_disable(entity, param, logic):
        """Deactivate the portal — fades it out."""
        entity.properties['active'] = False
        if hasattr(entity, '_fade_target'):
            entity._fade_target = 0.0        # fade out
        name = entity.properties.get('name', 'unnamed')
        debug_log('IO', f"Portal '{name}' disabled")
        logic.io_manager.fire_output(entity, 'OnDisabled')

    def portal_toggle(entity, param, logic):
        """Toggle portal active state with fade."""
        was_active = entity.properties.get('active', False)
        entity.properties['active'] = not was_active
        if hasattr(entity, '_fade_target'):
            entity._fade_target = 1.0 if entity.properties['active'] else 0.0
        name = entity.properties.get('name', 'unnamed')
        state = "enabled" if entity.properties['active'] else "disabled"
        debug_log('IO', f"Portal '{name}' toggled → {state}")
        logic.io_manager.fire_output(entity, 'OnToggled')

    def portal_set_color(entity, param, logic):
        """Set rim/glow color from 'R G B' string (0-255)."""
        try:
            parts = param.split()
            if len(parts) >= 3:
                r = max(0, min(255, int(parts[0])))
                g = max(0, min(255, int(parts[1])))
                b = max(0, min(255, int(parts[2])))
                entity.properties['color'] = [r, g, b]
                name = entity.properties.get('name', 'unnamed')
                debug_log('IO', f"Portal '{name}' color set to ({r}, {g}, {b})")
        except (ValueError, IndexError):
            debug_log('Error', f"SetColor: bad parameter '{param}' — expected 'R G B'")

    def portal_set_target(entity, param, logic):
        """Change the paired portal target by name."""
        if param:
            entity.properties['portal_target'] = param.strip()
            name = entity.properties.get('name', 'unnamed')
            debug_log('IO', f"Portal '{name}' target set to '{param.strip()}'")

    def portal_show_rim(entity, param, logic):
        entity.properties['show_rim'] = True

    def portal_hide_rim(entity, param, logic):
        entity.properties['show_rim'] = False

    def portal_set_width(entity, param, logic):
        try:
            entity.properties['width'] = max(16.0, float(param))
        except (ValueError, TypeError):
            pass

    def portal_set_height(entity, param, logic):
        try:
            entity.properties['height'] = max(16.0, float(param))
        except (ValueError, TypeError):
            pass

    io_manager.register_input_handler('portal', 'enable',    portal_enable)
    io_manager.register_input_handler('portal', 'disable',   portal_disable)
    io_manager.register_input_handler('portal', 'toggle',    portal_toggle)
    io_manager.register_input_handler('portal', 'setcolor',  portal_set_color)
    io_manager.register_input_handler('portal', 'settarget', portal_set_target)
    io_manager.register_input_handler('portal', 'showrim',   portal_show_rim)
    io_manager.register_input_handler('portal', 'hiderim',   portal_hide_rim)
    io_manager.register_input_handler('portal', 'setwidth',  portal_set_width)
    io_manager.register_input_handler('portal', 'setheight', portal_set_height)

    # ==========================================================================
    # LOG SUMMARY
    # ==========================================================================

    # Retrieve version from version.txt in the same directory
    version_str = "Unknown"
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        version_path = os.path.join(current_dir, 'version.txt')
        if os.path.exists(version_path):
            with open(version_path, 'r') as f:
                version_str = f.read().strip()
    except (OSError, IOError):
        pass

    debug_log('Info', f"<b>Fio {version_str}</b>")
    debug_log('Info', f"Registered {len(io_manager._input_handlers)} input handlers")
    debug_log('Info', f"Type 'help' to see all available commands")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_brush_index(brush: dict, logic) -> int:
    """Get the index of a brush in the brushes list."""
    try:
        return logic.brushes.index(brush)
    except ValueError:
        return -1



