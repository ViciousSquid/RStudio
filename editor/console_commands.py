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
    FULL console control with clear mode-specific messages.
    """
    def __init__(self, main_window):
        self.main_window = main_window
        self.editor_state = main_window.state

        self.commands = {
            'help': self.cmd_help,
            'list': self.cmd_list_entities,
            'entities': self.cmd_list_entities,
            'ents': self.cmd_list_entities,
            'ls': self.cmd_list_entities,

            'ent': self.cmd_info,
            'info': self.cmd_info,

            'fire': self.cmd_fire_output,
            'ent_fire': self.cmd_fire_output,
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

    # ===================================================================
    # HELP
    # ===================================================================
    def cmd_help(self, args):
        help_text = """
<i>Here is a full list of available commands:</i><br><br>
<b style="color:orange;">clear</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Clears the console<br>
<b style="color:orange;">connect</b> ... &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Create I/O link<br>
<b style="color:orange;">delete</b> <span style="color:yellow;">&lt;name&gt;</span> / <b style="color:orange;">kill</b> <span style="color:yellow;">&lt;name&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Delete entity<br>
<b style="color:orange;">ent</b> <span style="color:yellow;">&lt;name&gt;</span> / <b style="color:orange;">info</b> <span style="color:yellow;">&lt;name&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  Detailed info + I/O connections<br>
<b style="color:orange;">fire</b> <span style="color:yellow;">&lt;entity&gt;</span> <span style="color:yellow;">&lt;output&gt;</span> <span style="color:yellow;">[param]</span> &nbsp; &nbsp; &nbsp; -  Fire any output<br>
<b style="color:orange;">fps</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  Toggle FPS display<br>
<b style="color:orange;">getprop</b> <span style="color:yellow;">&lt;entity&gt;</span> <span style="color:yellow;">&lt;key&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  Read a property <i>(use with setprop)</i><br>
<b style="color:orange;">inputs</b> <span style="color:yellow;">&lt;entity&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  List available inputs<br>
<b style="color:orange;">list</b> / <b style="color:orange;">entities</b> / <b style="color:orange;">ents</b> / <b style="color:orange;">ls</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  List every named brush & thing<br>
<b style="color:orange;">list_connections</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Show all I/O connections<br>
<b style="color:orange;">map</b> <span style="color:yellow;">&lt;name&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;-  Load a map<br>
<b style="color:orange;">noclip</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Disable clipping<br>
<b style="color:orange;">outputs</b> <span style="color:yellow;">&lt;entity&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  List available outputs<br>
<b style="color:orange;">physics</b> <span style="color:yellow;">on/off/toggle</span><br>
<b style="color:orange;">send</b> <span style="color:yellow;">&lt;entity&gt;</span> <span style="color:yellow;">&lt;input&gt;</span> <span style="color:yellow;">[param]</span> &nbsp; &nbsp; &nbsp; &nbsp; -  Send any input<br>
<b style="color:orange;">setpos</b> <span style="color:yellow;">x y z</span> / <b style="color:orange;">teleport</b> <span style="color:yellow;">x y z</span> &nbsp; &nbsp; &nbsp; &nbsp; -  Teleport player<br>
<b style="color:orange;">spawn</b> light &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Spawn light<br>
<b style="color:orange;">spawn</b> pickup TYPE , VALUE <br>
<b style="color:orange;">setprop</b> <span style="color:yellow;">&lt;key&gt;</span> <span style="color:yellow;">&lt;value&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  Change any property <i>(use with getprop)</i><br>
<b style="color:orange;">trigger</b> <span style="color:yellow;">&lt;entity&gt;</span> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; -  SMART toggle for doors/movers<br>
"""
        debug_log("Info", help_text)

    # ===================================================================
    # MODE CHECK HELPER
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
            debug_log("Error", "Usage: ent <name>")
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

    def cmd_fire_output(self, args):
        if not IO_AVAILABLE:
            debug_log("Error", "I/O system not available")
            return
        parts = args.split()
        if len(parts) < 2:
            debug_log("Error", "Usage: fire <entity> <output> [parameter]")
            return
        entity_name = parts[0]
        output_name = parts[1]
        param = " ".join(parts[2:]) if len(parts) > 2 else ""

        entity = self.editor_state.find_entity_by_name(entity_name)
        if not entity:
            debug_log("Error", f"Entity '{entity_name}' not found")
            return

        debug_log("Info", f"🔥 Firing {output_name} on {entity_name} (param='{param}')")
        fire_output(entity, output_name, param)

    def cmd_trigger(self, args):
        if not args:
            debug_log("Error", "Usage: trigger <entity>")
            return
        entity_name = args.strip()
        entity = self.editor_state.find_entity_by_name(entity_name)
        if not entity:
            debug_log("Error", f"Entity '{entity_name}' not found")
            return

        if isinstance(entity, dict) and (entity.get('is_door') or entity.get('is_mover')):
            debug_log("Info", f"🔄 Toggling {entity_name}")
            send_input(entity, "Toggle", "")
        else:
            self.cmd_fire_output(f"{entity_name} OnTrigger")

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
            debug_log("Error", "Usage: connect <source> <output> <target> <input> [delay] [param]")
            return
        src = parts[0]
        outp = parts[1]
        tgt = parts[2]
        inp = parts[3]
        delay = float(parts[4]) if len(parts) > 4 else 0.0
        param = " ".join(parts[5:]) if len(parts) > 5 else ""

        source_ent = self.editor_state.find_entity_by_name(src)
        if not source_ent:
            debug_log("Error", f"Source '{src}' not found")
            return

        conn = OutputConnection(outp, tgt, inp, param, delay, fire_once=False)
        if hasattr(source_ent, 'add_output_connection'):
            source_ent.add_output_connection(conn)
        else:
            if '_io_connections' not in source_ent:
                source_ent['_io_connections'] = []
            source_ent['_io_connections'].append(conn)

        debug_log("Info", f"Connected {src}.{outp} → {tgt}.{inp}")
        self.editor_state.save_state()

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
        map_name = args[0]
        if not map_name.endswith('.json'):
            map_name += '.json'
        map_path = os.path.join(self.main_window.root_dir, 'maps', map_name)
        if os.path.exists(map_path):
            self.main_window.load_level_file(map_path)
            debug_log("Info", f"Loaded map {map_name}")
        else:
            debug_log("Error", f"Map not found: {map_name}")