import os
import json
from PyQt5.QtWidgets import QMessageBox

from editor.debug_console import debug_log

# Try to import I/O system (available in both editor and play mode)
try:
    from .io_system import (
        fire_output, send_input, get_connections,
        OutputConnection, get_output_names, get_input_names,
        get_entity_type_for_io
    )
    IO_AVAILABLE = True
except ImportError:
    IO_AVAILABLE = False
    # debug_log("Warning", "I/O system not fully loaded in console")

# For spawn command
from editor.things import Pickup, Light, PlayerStart


class ConsoleCommandHandler:
    """
    FULL console control with clear mode-specific messages + extensive render commands.
    """
    def __init__(self, main_window):
        self.main_window = main_window
        self.editor_state = main_window.state

        self.commands = {
            'bind': self.cmd_bind,
            'help': self.cmd_help,
            'list': self.cmd_list_entities,
            'entities': self.cmd_list_entities,
            'ents': self.cmd_list_entities,
            'ls': self.cmd_list_entities,
            'monster_kill': self.cmd_monster_kill,
            'kill_monster': self.cmd_monster_kill,
            'monster_revive':     self.cmd_monster_revive,
            'monster_revive_all': self.cmd_monster_revive_all,

            'ent': self.cmd_info,
            'info': self.cmd_info,

            'fire': self.cmd_fire,
            'ent_fire': self.cmd_fire,
            'trigger': self.cmd_trigger,
            'send': self.cmd_send_input,
            'toggle': self.cmd_toggle,

            'setprop': self.cmd_set_property,
            'set': self.cmd_set_property,
            'getprop': self.cmd_get_property,
            'get': self.cmd_get_property,

            'outputs': self.cmd_list_outputs,
            'inputs': self.cmd_list_inputs,

            'connect': self.cmd_connect_io,
            'disconnect': self.cmd_disconnect_io,

            'spawn': self.cmd_spawn,
            'delete': self.cmd_delete,
            'kill': self.cmd_delete,
            'list_connections': self.cmd_list_connections,
            'connections': self.cmd_list_connections,

            # Play Mode only commands
            'physics': self.cmd_physics,
            'setpos': self.cmd_setpos,
            'teleport': self.cmd_setpos,

            # Original commands
            'noclip': self.cmd_noclip,
            'clear': self.cmd_clear,
            'fps': self.cmd_fps,
            'map': self.cmd_map,

            # ==================== NEW RENDER COMMANDS ====================
            'r_list': self.cmd_render_list,
            'r_wireframe': self.cmd_render_wireframe,
            'r_shadows': self.cmd_render_shadows,
            'r_fog': self.cmd_render_fog,
            'r_water': self.cmd_render_water,
            'r_glass': self.cmd_render_glass,
            'r_lighting': self.cmd_render_lighting,
            'r_deferred': self.cmd_render_deferred,
            'r_vsync': self.cmd_render_vsync,
            'r_clearcolor': self.cmd_render_clearcolor,
            'r_reloadshaders': self.cmd_reload_shaders,
            'r_info': self.cmd_render_info,

            # Short aliases
            'wireframe': self.cmd_render_wireframe,
            'shadows': self.cmd_render_shadows,
            'fog': self.cmd_render_fog,
            'water': self.cmd_render_water,
            'glass': self.cmd_render_glass,
            'lighting': self.cmd_render_lighting,
            'deferred': self.cmd_render_deferred,
            'vsync': self.cmd_render_vsync,
            'reloadshaders': self.cmd_reload_shaders,
        }

    def handle_command(self, cmd_string):
        parts = cmd_string.strip().split(maxsplit=1)
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        handler = self.commands.get(cmd)
        if handler:
            handler(args)
        else:
            debug_log("Error", f"Unknown command: {cmd}. Type 'help' for list.")

    def cmd_bind(self, args):
        """bind <key> <command>   or   bind (opens dialog)"""
        if not args.strip():
            self._open_bind_dialog()
            return
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            debug_log("Error", "Usage: bind <key> <command>")
            return
        key_str, command = parts
        # Store binding in main_window
        self.main_window.set_key_binding(key_str, command)
        debug_log("Info", f"Bound '{key_str}' to '{command}'")

    def _open_bind_dialog(self):
        from PyQt5.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QLabel, QKeySequenceEdit, QPushButton
        from PyQt5.QtCore import Qt

        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Bind Key")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Press the key combination to bind:"))
        key_edit = QKeySequenceEdit()
        key_edit.setPlaceholderText("Press a key...")
        layout.addWidget(key_edit)
        layout.addWidget(QLabel("Enter the command to execute:"))
        cmd_edit = QLineEdit()
        layout.addWidget(cmd_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            key_seq = key_edit.keySequence()
            if key_seq.isEmpty():
                debug_log("Error", "No key selected")
                return
            key_str = key_seq.toString()
            command = cmd_edit.text().strip()
            if not command:
                debug_log("Error", "No command entered")
                return
            self.main_window.set_key_binding(key_str, command)
            debug_log("Info", f"Bound '{key_str}' to '{command}'")

    # ===================================================================
    # MONSTER COMMANDS
    # ===================================================================

    def cmd_monster_kill(self, args):
        """
        Usage: monster_kill <monster_name>
        Instantly kills the named monster (sets health to 0, marks dead/hidden, fires OnDeath).
        """
        if not args:
            debug_log("Error", "Usage: monster_kill <monster_name>")
            return

        name = args.strip()
        entity = self.editor_state.find_entity_by_name(name)
        if not entity:
            debug_log("Error", f"Entity '{name}' not found")
            return

        # Check if it's a monster
        from editor.things import Monster
        if not isinstance(entity, Monster):
            debug_log("Error", f"Entity '{name}' is not a Monster (type: {type(entity).__name__})")
            return

        # Kill the monster
        entity.properties['health'] = 0
        entity.properties['dead'] = True
        entity.properties['hidden'] = True

        # Fire I/O output if available
        try:
            from editor.io_system import get_connections, fire_output
            # Since we don't have IOManager reference here, we can use the logic_thread's io_manager if in play mode
            if hasattr(self.main_window, 'view_3d') and self.main_window.view_3d.logic_thread:
                io_manager = self.main_window.view_3d.logic_thread.io_manager
                if io_manager:
                    io_manager.fire_output(entity, 'OnDeath')
        except Exception as e:
            debug_log("Warning", f"Could not fire OnDeath: {e}")

        debug_log("Info", f"Monster '{name}' killed (health set to 0, hidden=True)")
        self.main_window.update_all_ui()

    def cmd_monster_revive(self, args):
        """
        Usage: monster_revive <monster_name>
        Restores a single named monster to full health and clears its dead/hidden state.
        Works in both editor and play mode.
        """
        if not args:
            debug_log("Error", "Usage: monster_revive <monster_name>")
            return

        name = args.strip()
        entity = self.editor_state.find_entity_by_name(name)
        if not entity:
            debug_log("Error", f"Entity '{name}' not found")
            return

        from editor.things import Monster
        if not isinstance(entity, Monster):
            debug_log("Error", f"Entity '{name}' is not a Monster (type: {type(entity).__name__})")
            return

        self._revive_monster(entity)

        # If in play mode, clear this monster's stale AI state so it doesn't
        # inherit a near-zero shoot timer from before it died.
        try:
            if hasattr(self.main_window, 'view_3d') and self.main_window.view_3d.logic_thread:
                lt = self.main_window.view_3d.logic_thread
                lt.monster_states.pop(id(entity), None)
        except Exception as e:
            debug_log("Warning", f"Could not reset monster AI state: {e}")

        debug_log("Info", f"Monster '{name}' revived")
        self.main_window.update_all_ui()

    def cmd_monster_revive_all(self, args):
        """
        Usage: monster_revive_all
        Restores every monster in the level to full health and clears dead/hidden/awake state.
        Safe to run in editor or play mode.
        """
        from editor.things import Monster

        monsters = [t for t in self.editor_state.things if isinstance(t, Monster)]
        if not monsters:
            debug_log("Info", "No monsters found in the level")
            return

        for monster in monsters:
            self._revive_monster(monster)

        # If we're in play mode, clear the entire monster AI state dict so no
        # monster inherits a stale shoot timer or animation state from before death.
        try:
            if hasattr(self.main_window, 'view_3d') and self.main_window.view_3d.logic_thread:
                lt = self.main_window.view_3d.logic_thread
                lt.monster_states = {}
        except Exception as e:
            debug_log("Warning", f"Could not reset monster AI states: {e}")

        debug_log("Info", f"Revived {len(monsters)} monster(s)")
        self.main_window.update_all_ui()

    def _revive_monster(self, entity):
        """
        Shared helper — reset a Monster entity back to its full alive state.
        Respects the entity's configured health value if positive; falls back to 100.
        """
        # Restore health: use the entity's current health value if it's still positive
        # (meaning the designer set a custom value), otherwise default to 100.
        current_health = entity.properties.get('health', 0)
        try:
            current_health = int(current_health)
        except (ValueError, TypeError):
            current_health = 0

        restored_health = current_health if current_health > 0 else 100
        entity.properties['health']      = restored_health
        entity.properties['dead']        = False
        entity.properties['hidden']      = False
        # Reset awake so triggered/sight-gated monsters go dormant again —
        # wake logic will re-apply correctly on next play mode start.
        entity.properties['awake']       = False
        entity.properties.pop('is_shooting', None)

        # Clear the sprite cache so the editor 2D views and 3D billboard
        # switch back to idle.png immediately rather than staying on dead.png.
        try:
            from editor.things import Monster
            Monster.clear_sprite_cache()
        except Exception:
            pass

    # ===================================================================
    # HELP
    # ===================================================================
    def cmd_help(self, args):
        
        sep = '<span style="color:white;"> / </span>'
        
        help_text = f"""
<i>Here is a full list of all available commands:</i><br><br>

<b style="color:orange;">clear</b> — Clear console<br>
<b style="color:orange;">help</b> — Show this help<br>
<b style="color:orange;">fps</b> — Toggle FPS display<br>
<b style="color:orange;">map &lt;name&gt;</b> — Load a different map<br>
<b style="color:cyan;">=== Entity / I/O Commands ===</b><br>
<b style="color:orange;">list</b>{sep}<b style="color:orange;">ents</b>{sep}<b style="color:orange;">ls</b>{sep}<b style="color:orange;">entities</b> — List all entities<br>
<b style="color:orange;">ent</b>{sep}<b style="color:orange;">info</b> &lt;name&gt; — Show entity details<br>
<b style="color:orange;">spawn</b> &lt;type&gt; — Spawn a new entity (thing)<br>
<b style="color:orange;">delete</b>{sep}<b style="color:orange;">kill</b> &lt;name&gt; — Remove an entity from the scene<br>
<b style="color:orange;">set</b>{sep}<b style="color:orange;">setprop</b> &lt;ent&gt; &lt;prop&gt; &lt;val&gt; — Modify a property<br>
<b style="color:orange;">get</b>{sep}<b style="color:orange;">getprop</b> &lt;ent&gt; &lt;prop&gt; — Read a property value<br>
<b style="color:orange;">fire</b>{sep}<b style="color:orange;">ent_fire</b> &lt;ent&gt; &lt;output&gt; [param]<br>
<b style="color:orange;">send</b> &lt;ent&gt; &lt;input&gt; [param]<br>
<b style="color:orange;">trigger</b> — Smart toggle for doors/triggers<br>
<b style="color:orange;">toggle</b> — Flip an entity's state<br>
<b style="color:cyan;">=== Connection Management ===</b><br>
<b style="color:orange;">outputs</b> &lt;ent&gt; — List available outputs for type<br>
<b style="color:orange;">inputs</b> &lt;ent&gt; — List available inputs for type<br>
<b style="color:orange;">connections</b>{sep}<b style="color:orange;">list_connections</b> &lt;ent&gt; — Show active I/O links<br>
<b style="color:orange;">connect</b> &lt;src&gt; &lt;out&gt; &lt;tgt&gt; &lt;in&gt; [delay]<br>
<b style="color:orange;">disconnect</b> &lt;src&gt; &lt;out&gt; &lt;tgt&gt; &lt;in&gt;<br>
<b style="color:cyan;">=== Monsters ===</b><br>
<b style="color:orange;">monster_kill</b> &lt;name&gt; — Instantly kill a named monster<br>
<b style="color:orange;">monster_revive</b> &lt;name&gt; — Restore a named monster to full health<br>
<b style="color:orange;">monster_revive_all</b> — Restore every monster in the level<br>
<b style="color:cyan;">=== Rendering ===</b><br>
<b style="color:orange;">r_list</b> — Show all current render settings<br>
<b style="color:orange;">r_wireframe</b>{sep}<b style="color:orange;">wireframe</b> — Toggle wireframe mode<br>
<b style="color:orange;">r_shadows</b>{sep}<b style="color:orange;">shadows</b> — Toggle shadows<br>
<b style="color:orange;">r_fog</b>{sep}<b style="color:orange;">fog</b> — Toggle volumetric fog<br>
<b style="color:orange;">r_lighting</b>{sep}<b style="color:orange;">lighting</b> — Toggle real-time lighting<br>
<b style="color:orange;">r_reloadshaders</b> — Hot-reload all shaders<br>
<b style="color:orange;">r_clearcolor</b> r g b — Set background colour<br>
<b style="color:cyan;">=== Movement & Physics ===</b><br>
<b style="color:orange;">noclip</b> — Toggle noclip<br>
<b style="color:orange;">physics</b> on/off/toggle<br>
<b style="color:orange;">setpos</b>{sep}<b style="color:orange;">teleport</b> x y z<br>
"""
        debug_log("Info", help_text)

    # ===================================================================
    # HELPER: Get renderer safely
    # ===================================================================
    def _get_renderer(self):
        """Safely retrieve the active renderer from the 3D view."""
        try:
            if hasattr(self.main_window, 'view_3d') and hasattr(self.main_window.view_3d, 'renderer'):
                return self.main_window.view_3d.renderer
        except:
            pass
        debug_log("Error", "Renderer not accessible (not in 3D view).")
        return None

    # ===================================================================
    # RENDER COMMANDS
    # ===================================================================

    def cmd_render_list(self, args):
        """Show all current render settings in a clean table."""
        renderer = self._get_renderer()
        if not renderer:
            return

        lines = ["<b>=== Current Render Settings ===</b><br>"]

        def add_line(name, value):
            lines.append(f"<b>{name}:</b> {value}")

        add_line("Wireframe", "ON" if getattr(renderer, 'wireframe', False) else "OFF")
        add_line("Shadows", "ON" if getattr(renderer, 'shadows_enabled', False) else "OFF")
        add_line("Volumetric Fog", "ON" if getattr(renderer, 'fog_enabled', True) else "OFF")
        add_line("Water Shader", "ON" if getattr(renderer, 'water_enabled', True) else "OFF")
        add_line("Glass Shader", "ON" if getattr(renderer, 'glass_enabled', True) else "OFF")
        add_line("Real-time Lighting", "ON" if getattr(renderer, 'lighting_enabled', True) else "OFF")
        add_line("Deferred Rendering", "ON" if getattr(renderer, 'use_deferred', False) else "OFF")
        add_line("ARM Mode", "ON" if getattr(renderer, 'arm_mode', True) else "OFF")

        # Clear color
        cc = getattr(renderer, 'clear_color', [0.02, 0.02, 0.05])
        add_line("Clear Color", f"[{cc[0]:.2f}, {cc[1]:.2f}, {cc[2]:.2f}]")

        debug_log("Info", "<br>".join(lines))

    def cmd_render_info(self, args):
        """Detailed renderer status"""
        self.cmd_render_list(args)

    def cmd_render_wireframe(self, args):
        renderer = self._get_renderer()
        if not renderer:
            return
        renderer.wireframe = not getattr(renderer, 'wireframe', False)
        state = "ON" if renderer.wireframe else "OFF"
        debug_log("Info", f"Wireframe: {state}")
        if hasattr(self.main_window.view_3d, 'update'):
            self.main_window.view_3d.update()

    def cmd_render_shadows(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.shadows_enabled = not getattr(renderer, 'shadows_enabled', False)
        debug_log("Info", f"Shadows: {'ON' if renderer.shadows_enabled else 'OFF'}")

    def cmd_render_fog(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.fog_enabled = not getattr(renderer, 'fog_enabled', True)
        debug_log("Info", f"Volumetric Fog: {'ON' if renderer.fog_enabled else 'OFF'}")

    def cmd_render_water(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.water_enabled = not getattr(renderer, 'water_enabled', True)
        debug_log("Info", f"Water shader: {'ON' if renderer.water_enabled else 'OFF'}")

    def cmd_render_glass(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.glass_enabled = not getattr(renderer, 'glass_enabled', True)
        debug_log("Info", f"Glass shader: {'ON' if renderer.glass_enabled else 'OFF'}")

    def cmd_render_lighting(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.lighting_enabled = not getattr(renderer, 'lighting_enabled', True)
        debug_log("Info", f"Real-time lighting: {'ON' if renderer.lighting_enabled else 'OFF'}")

    def cmd_render_deferred(self, args):
        renderer = self._get_renderer()
        if not renderer: return
        renderer.use_deferred = not getattr(renderer, 'use_deferred', False)
        debug_log("Info", f"Deferred rendering: {'ON' if renderer.use_deferred else 'OFF'}")

    def cmd_render_vsync(self, args):
        config = self.main_window.config
        current = config.getboolean('Display', 'vsync', fallback=True)
        new_state = not current
        if not config.has_section('Display'):
            config.add_section('Display')
        config.set('Display', 'vsync', str(new_state))
        self.main_window.save_config()

        debug_log("Info", f"VSync: {'ON' if new_state else 'OFF'}")

    def cmd_render_clearcolor(self, args):
        renderer = self._get_renderer()
        if not renderer:
            return
        try:
            parts = [float(x) for x in args.split()]
            if len(parts) == 3:
                renderer.clear_color = [max(0.0, min(1.0, c)) for c in parts]
                debug_log("Info", f"Clear color set to {renderer.clear_color}")
            else:
                debug_log("Error", "Usage: r_clearcolor r g b   (values 0.0 to 1.0)")
        except:
            debug_log("Error", "Usage: r_clearcolor r g b")

    def cmd_reload_shaders(self, args):
        renderer = self._get_renderer()
        if not renderer:
            return
        try:
            if hasattr(renderer, 'reload_shaders') and callable(renderer.reload_shaders):
                success = renderer.reload_shaders()
                if success:
                    debug_log("Info", "✅ Shaders reloaded successfully")
                else:
                    debug_log("Warning", "Some shaders failed to reload")
            else:
                debug_log("Error", "Renderer does not support hot-reloading shaders")
        except Exception as e:
            debug_log("Error", f"Failed to reload shaders: {e}")

    # ===================================================================
    # EXISTING COMMANDS (unchanged)
    # ===================================================================

    def _require_play_mode(self, command_name):
        """Returns True if in Play Mode, else logs error and returns False."""
        if not self.main_window.view_3d.play_mode:
            debug_log("Error", f"Command '{command_name}' can only be used in Play Mode.")
            return False
        return True

    def cmd_list_entities(self, args):
        debug_log("Info", f"--- BRUSHES ({len(self.editor_state.brushes)}) ---")
        for i, b in enumerate(self.editor_state.brushes):
            name = b.get('name', f'unnamed_brush_{i}')
            typ = "Trigger" if b.get('is_trigger') else "Mover" if b.get('is_mover') else "Door" if b.get('is_door') else "Brush"
            debug_log("Info", f"  {name}  [{typ}]")

        debug_log("Info", f"--- THINGS ({len(self.editor_state.things)}) ---")
        for t in self.editor_state.things:
            name = t.properties.get('name', 'unnamed')
            typ = t.properties.get('type', 'unknown')
            debug_log("Info", f"  {name}  (type={typ})")

    def cmd_info(self, args):
        if not args:
            debug_log("Error", "Usage: ent <n>")
            return
        entity = self.editor_state.find_entity_by_name(args)
        if not entity:
            debug_log("Error", f"Entity '{args}' not found")
            return

        debug_log("Info", f"─── INFO: {args} ───")
        if isinstance(entity, dict):
            for k, v in list(entity.items())[:20]:
                if k != '_io_connections':
                    debug_log("Info", f"  {k}: {v}")
            conns = get_connections(entity) if IO_AVAILABLE else entity.get('_io_connections', [])
            if conns:
                debug_log("Info", "  I/O Connections:")
                for c in conns:
                    debug_log("Info", f"    {c.output_name} → {c.target_name}.{c.input_name}")
            else:
                debug_log("Info", "  No I/O connections")
        else:
            for k, v in entity.properties.items():
                debug_log("Info", f"  {k}: {v}")

    def cmd_fire(self, args):
        """ent_fire <entity_name> <input_name> [parameter]
        Works in both Editor mode and Play Mode."""
        if not args:
            debug_log("Error", "Usage: ent_fire <entity_name> <input_name> [parameter]")
            return

        parts = args.split(maxsplit=2)
        if len(parts) < 2:
            debug_log("Error", "Usage: ent_fire <entity_name> <input_name> [parameter]")
            return

        entity_name = parts[0]
        input_name = parts[1]
        parameter = " ".join(parts[2:]) if len(parts) > 2 else ""

        entity = self.editor_state.find_entity_by_name(entity_name)
        if not entity:
            debug_log("Error", f"Entity '{entity_name}' not found.")
            return

        debug_log("Info", f"[Editor Fire] {entity_name}.{input_name}({parameter})")

        # === Handle entities that implement on_input() (LevelChanger, etc.) ===
        if hasattr(entity, 'on_input') and callable(entity.on_input):
            try:
                success = entity.on_input(input_name, parameter)
                if success:
                    debug_log("Info", f"✓ Input '{input_name}' handled successfully")
                else:
                    debug_log("Warning", f"Input '{input_name}' was not handled")
            except Exception as e:
                debug_log("Error", f"Exception in {entity.__class__.__name__}.on_input(): {e}")
        else:
            debug_log("Warning", f"Entity '{entity_name}' does not support inputs (no on_input method)")

        # Optional: forward to IOManager in Play Mode
        if hasattr(self.main_window, 'iomanager') and self.main_window.iomanager is not None:
            try:
                self.main_window.iomanager.fire_output(entity, input_name, parameter)
            except:
                pass

    def cmd_trigger(self, args):
        if not args:
            debug_log("Error", "Usage: trigger <entity>")
            return

        entity_name = args.strip()
        entity = self.editor_state.find_entity_by_name(entity_name)
        if not entity:
            debug_log("Error", f"Entity '{entity_name}' not found")
            return

        # Brush-based toggle
        if isinstance(entity, dict) and (entity.get('is_door') or entity.get('is_mover')):
            debug_log("Info", f"🔄 Toggling {entity_name}")
            if IO_AVAILABLE:
                send_input(entity, "Toggle", "")
            return

        # Generic entity fallback
        debug_log("Info", f"Triggering {entity_name}")
        self.cmd_fire(f"{entity_name} Trigger")

    def cmd_send_input(self, args):
        if not IO_AVAILABLE or len(args.split()) < 2:
            debug_log("Error", "Usage: send <entity> <input> [param]")
            return
        parts = args.split()
        entity_name = parts[0]
        input_name = parts[1]
        param = " ".join(parts[2:]) if len(parts) > 2 else ""
        entity = self.editor_state.find_entity_by_name(entity_name)
        if entity:
            send_input(entity, input_name, param)
            debug_log("Info", f"Sent input '{input_name}' to {entity_name}")
        else:
            debug_log("Error", f"Entity '{entity_name}' not found")

    def cmd_toggle(self, args):
        if not args:
            debug_log("Error", "Usage: toggle <entity>")
            return
        self.cmd_send_input(f"{args} Toggle")

    def cmd_set_property(self, args):
        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            debug_log("Error", "Usage: setprop <entity> <key> <value>")
            return
        name, key, value = parts
        entity = self.editor_state.find_entity_by_name(name)
        if not entity:
            debug_log("Error", f"Entity '{name}' not found")
            return

        if isinstance(entity, dict):
            entity[key] = value
        else:
            entity.properties[key] = value

        debug_log("Info", f"Set {name}.{key} = {value}")
        self.editor_state.save_state()

    def cmd_get_property(self, args):
        parts = args.split()
        if len(parts) < 2:
            debug_log("Error", "Usage: getprop <entity> <key>")
            return
        name, key = parts
        entity = self.editor_state.find_entity_by_name(name)
        if not entity:
            debug_log("Error", f"Entity '{name}' not found")
            return

        if isinstance(entity, dict):
            val = entity.get(key, "<not found>")
        else:
            val = entity.properties.get(key, "<not found>")
        debug_log("Info", f"{name}.{key} = {val}")

    def cmd_list_outputs(self, args):
        if not args:
            debug_log("Error", "Usage: outputs <entity>")
            return
        entity = self.editor_state.find_entity_by_name(args)
        if entity:
            typ = get_entity_type_for_io(entity) if IO_AVAILABLE else "unknown"
            outs = get_output_names(typ) if IO_AVAILABLE else ["(I/O not loaded)"]
            debug_log("Info", f"Outputs for {args}: {', '.join(outs)}")
        else:
            debug_log("Error", f"Entity '{args}' not found")

    def cmd_list_inputs(self, args):
        if not args:
            debug_log("Error", "Usage: inputs <entity>")
            return
        entity = self.editor_state.find_entity_by_name(args)
        if entity:
            typ = get_entity_type_for_io(entity) if IO_AVAILABLE else "unknown"
            ins = get_input_names(typ) if IO_AVAILABLE else ["(I/O not loaded)"]
            debug_log("Info", f"Inputs for {args}: {', '.join(ins)}")
        else:
            debug_log("Error", f"Entity '{args}' not found")

    def cmd_connect_io(self, args):
        parts = args.split()

        if len(parts) < 4:
            debug_log("Error", "Usage: connect <source> <o> <target> <input> [delay] [param]")
            return

        src, outp, tgt, inp = parts[:4]

        # --- Safe delay parsing ---
        delay = 0.0
        if len(parts) > 4:
            try:
                delay = float(parts[4])
            except ValueError:
                debug_log("Error", f"Invalid delay '{parts[4]}' (must be a number)")
                return

        # --- Parameter ---
        param = " ".join(parts[5:]) if len(parts) > 5 else ""

        # --- Resolve source ---
        source_ent = self.editor_state.find_entity_by_name(src)
        if not source_ent:
            debug_log("Error", f"Source '{src}' not found")
            return

        # --- Resolve target (prevents silent broken connections) ---
        target_ent = self.editor_state.find_entity_by_name(tgt)
        if not target_ent:
            debug_log("Warning", f"Target '{tgt}' not found (connection will still be created)")

        # --- Create connection ---
        try:
            conn = OutputConnection(outp, tgt, inp, param, delay, fire_once=False)
        except Exception as e:
            debug_log("Error", f"Failed to create connection: {e}")
            return

        # --- Attach connection safely ---
        try:
            if hasattr(source_ent, 'add_output_connection'):
                source_ent.add_output_connection(conn)
            else:
                if not isinstance(source_ent, dict):
                    debug_log("Error", f"Source '{src}' cannot store IO connections")
                    return

                source_ent.setdefault('_io_connections', []).append(conn)

        except Exception as e:
            debug_log("Error", f"Failed to attach connection: {e}")
            return

        # --- Persist state ---
        try:
            self.editor_state.save_state()
        except Exception as e:
            debug_log("Warning", f"Connection created but failed to save state: {e}")

        # --- Final log ---
        debug_log(
            "Info",
            f"Connected {src}.{outp} → {tgt}.{inp}"
            + (f" (delay={delay})" if delay else "")
            + (f" param='{param}'" if param else "")
        )

    def cmd_disconnect_io(self, args):
        debug_log("Warning", "disconnect command not fully implemented yet (use property editor for now)")

    def cmd_spawn(self, args):
        if not args:
            debug_log("Error", "Usage: spawn pickup health 25   or   spawn light")
            return
        parts = args.split()
        spawn_type = parts[0].lower()

        if spawn_type == "pickup":
            if len(parts) < 2:
                debug_log("Error", "Usage: spawn pickup <health|ammo|gun1|key> [value]")
                return
            item = parts[1]
            value = parts[2] if len(parts) > 2 else "25"

            new_pickup = Pickup(pos=[0, 0, 0])
            new_pickup.properties['item_type'] = item
            new_pickup.properties['value'] = value
            new_pickup.properties['name'] = f"Pickup_{item}"
            self.editor_state.things.append(new_pickup)
            debug_log("Info", f"Spawned pickup: {item} (value={value})")
            self.editor_state.save_state()
            self.main_window.update_all_ui()

        elif spawn_type == "light":
            new_light = Light(pos=[0, 100, 0])
            new_light.properties['name'] = "Light_new"
            self.editor_state.things.append(new_light)
            debug_log("Info", "Spawned light at [0, 100, 0]")
            self.editor_state.save_state()
            self.main_window.update_all_ui()

        elif spawn_type == "levelchanger":
            new_changer = LevelChanger(pos=[0, 40, 0])
            new_changer.properties['name'] = "LevelChanger_new"
            new_changer.properties['target_map'] = "Simple_Map_Test.json"  # default
            self.editor_state.things.append(new_changer)
            debug_log("Info", "Spawned LevelChanger at [0, 40, 0]")
            self.editor_state.save_state()
            self.main_window.update_all_ui()

        else:
            debug_log("Error", f"Unknown spawn type '{spawn_type}'. Try: pickup or light")

    def cmd_delete(self, args):
        if not args:
            debug_log("Error", "Usage: delete <entity_name>")
            return
        name = args.strip()
        entity = self.editor_state.find_entity_by_name(name)
        if not entity:
            debug_log("Error", f"Entity '{name}' not found")
            return

        self.editor_state.save_state()
        if isinstance(entity, dict):
            if entity in self.editor_state.brushes:
                self.editor_state.brushes.remove(entity)
        else:
            if entity in self.editor_state.things:
                self.editor_state.things.remove(entity)

        debug_log("Info", f"Deleted entity: {name}")
        self.main_window.update_all_ui()

    def cmd_list_connections(self, args):
        debug_log("Info", "=== ALL I/O CONNECTIONS ===")
        count = 0
        for brush in self.editor_state.brushes:
            name = brush.get('name', 'unnamed_brush')
            conns = get_connections(brush) if IO_AVAILABLE else brush.get('_io_connections', [])
            for c in conns:
                debug_log("Info", f"{name}.{c.output_name} → {c.target_name}.{c.input_name}")
                count += 1

        for thing in self.editor_state.things:
            name = thing.properties.get('name', 'unnamed_thing')
            conns = get_connections(thing) if IO_AVAILABLE else []
            for c in conns:
                debug_log("Info", f"{name}.{c.output_name} → {c.target_name}.{c.input_name}")
                count += 1

        debug_log("Info", f"Total connections: {count}")

    def cmd_noclip(self, args):
        if not self._require_play_mode("noclip"):
            return
        view_3d = self.main_window.view_3d
        player = view_3d.player
        player.physics_enabled = not player.physics_enabled
        state = "OFF" if not player.physics_enabled else "ON"
        self.main_window.show_toast(f"Noclip: {state}")
        debug_log("Info", f"Noclip set to {state}")

    def cmd_physics(self, args):
        if not self._require_play_mode("physics"):
            return

        player = self.main_window.view_3d.player
        arg = args.lower().strip() if args else "toggle"

        if arg in ("on", "1", "true"):
            player.physics_enabled = True
        elif arg in ("off", "0", "false"):
            player.physics_enabled = False
        else:
            player.physics_enabled = not getattr(player, 'physics_enabled', True)

        state = "ON" if player.physics_enabled else "OFF"
        self.main_window.show_toast(f"Physics: {state}")
        debug_log("Info", f"Physics set to {state}")

    def cmd_setpos(self, args):
        if not self._require_play_mode("setpos"):
            return

        try:
            parts = args.split()
            if len(parts) != 3:
                raise ValueError
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])

            self.main_window.view_3d.player.position = [x, y, z]
            debug_log("Info", f"Player teleported to [{x:.1f}, {y:.1f}, {z:.1f}]")
            self.main_window.show_toast(f"Teleported to {x:.1f}, {y:.1f}, {z:.1f}")
        except:
            debug_log("Error", "Usage: setpos x y z   (example: setpos 0 50 100)")

    def cmd_clear(self, args):
        self.main_window.debug_console.clear()

    def cmd_fps(self, args):
        config = self.main_window.config
        show = not config.getboolean('Display', 'show_fps', fallback=False)
        if not config.has_section('Display'):
            config.add_section('Display')
        config.set('Display', 'show_fps', str(show))
        if hasattr(self.main_window, 'show_fps_checkbox'):
            self.main_window.show_fps_checkbox.setChecked(show)
        self.main_window.save_config()
        self.main_window.view_3d.update()
        debug_log("Info", f"FPS display {'ON' if show else 'OFF'}")

    def cmd_map(self, args):
        if not args:
            debug_log("Warning", "Usage: map <mapname>")
            return
        map_name = args if isinstance(args, str) else args[0]
        if not map_name.endswith('.json'):
            map_name += '.json'
        map_path = os.path.join(self.main_window.root_dir, 'maps', map_name)
        if os.path.exists(map_path):
            self.main_window.load_level_file(map_path)
            debug_log("Info", f"Loaded map {map_name}")
        else:
            debug_log("Error", f"Map not found: {map_name}")
