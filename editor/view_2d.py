from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtGui import QPainter, QPainterPath, QPen, QColor, QBrush, QPixmap
from PyQt5.QtCore import QPoint, QRect, Qt, QSize
from editor.things import (PlayerStart, Light, Thing, Monster,
                           Pickup, Trigger)
import os
import math

class View2D(QWidget):
    def __init__(self, parent, editor, view_type):
        super().__init__(parent)
        self.editor = editor
        self.view_type = view_type

        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.world_size = 1024
        self.grid_size = 16
        self.snap_to_grid_enabled = True

        self.mouse_pos = QPoint(0, 0)
        self.last_mouse_pos = QPoint(0, 0)
        self.is_panning = False

        self.drag_mode = 'none'
        self.resize_handle = ''
        self.hot_object = None
        self.drag_start_pos = QPoint(0,0)
        self.original_object_pos = [0,0,0]
        self.original_brush_rect = QRect(0,0,0,0)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        add_thing_menu = menu.addMenu("Add Thing")
        add_player_start_action = add_thing_menu.addAction("Player Start")
        add_light_action = add_thing_menu.addAction("Light")
        add_monster_action = add_thing_menu.addAction("Monster")
        add_pickup_action = add_thing_menu.addAction("Pickup")

        menu.addSeparator()

        convert_to_trigger_action = None
        selected = self.editor.selected_object
        if isinstance(selected, dict) and selected.get('type') != 'trigger':
            convert_to_trigger_action = menu.addAction("Convert Brush to Trigger")

        place_camera_action = menu.addAction("Place camera here")
        action = menu.exec_(self.mapToGlobal(event.pos()))

        world_pos = self.screen_to_world(event.pos())
        snapped_pos = self.snap_to_grid(world_pos)

        pos3d = [0, 0, 0]
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        pos3d[ax_map[ax1]] = snapped_pos.x()
        pos3d[ax_map[ax2]] = snapped_pos.y()

        new_thing = None
        if action == add_player_start_action: new_thing = PlayerStart(pos=pos3d)
        elif action == add_light_action: new_thing = Light(pos=pos3d)
        elif action == add_monster_action: new_thing = Monster(pos=pos3d)
        elif action == add_pickup_action: new_thing = Pickup(pos=pos3d)
        elif action == place_camera_action:
            cam_pos = self.editor.view_3d.camera.pos
            cam_pos[ax_map[ax1]] = snapped_pos.x()
            cam_pos[ax_map[ax2]] = snapped_pos.y()
            self.editor.update_views()
            return
        elif action == convert_to_trigger_action and isinstance(self.editor.selected_object, dict):
            self.editor.save_state()
            brush = self.editor.selected_object
            brush['type'] = 'trigger'
            trigger_defaults = Trigger(pos=[0,0,0]).properties
            for key, value in trigger_defaults.items():
                brush.setdefault(key, value)
            self.editor.property_editor.set_object(brush)
            self.editor.update_views()
            return

        if new_thing:
            self.editor.save_state()
            self.editor.things.append(new_thing)
            self.editor.set_selected_object(new_thing)
            self.editor.update_views()

    def get_object_at(self, world_pos):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}

        for thing in reversed(self.editor.things):
            thing_pos_2d = QPoint(int(thing.pos[ax_map[ax1]]), int(thing.pos[ax_map[ax2]]))
            if (world_pos - thing_pos_2d).manhattanLength() < self.grid_size / self.zoom * 2:
                return thing

        for brush in reversed(self.editor.brushes):
            if self.get_brush_rect_2d(brush).contains(world_pos):
                return brush
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        self.draw_grid(painter)
        self.draw_brushes(painter)
        self.draw_things(painter)
        self.draw_camera(painter)
        painter.end()

    def draw_camera(self, painter):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        cam = self.editor.view_3d.camera
        fov = 45.0
        pos_2d = QPoint(int(cam.pos[ax_map[ax1]]), int(cam.pos[ax_map[ax2]]))
        screen_pos = self.world_to_screen(pos_2d)

        painter.setPen(QPen(QColor(255, 0, 255), 2))
        painter.setBrush(QBrush(QColor(255, 0, 255, 20)))
        painter.drawEllipse(screen_pos, 8, 8)

        if self.view_type == 'top':
            angle_rad = math.radians(cam.yaw)
            fov_rad = math.radians(fov)
            line_len = 100 / self.zoom
            p1 = screen_pos
            p2 = screen_pos + QPoint(int(line_len * math.cos(angle_rad - fov_rad / 2)), int(-line_len * math.sin(angle_rad - fov_rad / 2)))
            p3 = screen_pos + QPoint(int(line_len * math.cos(angle_rad + fov_rad / 2)), int(-line_len * math.sin(angle_rad + fov_rad / 2)))
            path = QPainterPath(); path.moveTo(p1); path.lineTo(p2); path.lineTo(p3); path.closeSubpath()
            painter.drawPath(path)

    def draw_things(self, painter):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        for thing in self.editor.things:
            pos_2d = QPoint(int(thing.pos[ax_map[ax1]]), int(thing.pos[ax_map[ax2]]))
            screen_pos = self.world_to_screen(pos_2d)
            is_selected = (thing == self.editor.selected_object)

            pixmap = thing.get_pixmap()

            if pixmap and not pixmap.isNull():
                size = pixmap.size()
                painter.drawPixmap(screen_pos.x() - size.width() // 2, screen_pos.y() - size.height() // 2, pixmap)
            else:
                painter.setPen(QPen(QColor(255,0,0)))
                painter.drawRect(screen_pos.x() - 8, screen_pos.y() - 8, 16, 16)

            if isinstance(thing, PlayerStart):
                painter.setPen(QPen(QColor(255, 255, 0), 2))
                angle = float(thing.properties.get('angle', 0.0))
                line_len = 20
                end_x = screen_pos.x() + line_len * math.cos(math.radians(angle))
                end_y = screen_pos.y() - line_len * math.sin(math.radians(angle))
                painter.drawLine(screen_pos.x(), screen_pos.y(), int(end_x), int(end_y))

            if is_selected:
                painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                width = pixmap.width() if pixmap and not pixmap.isNull() else 16
                height = pixmap.height() if pixmap and not pixmap.isNull() else 16
                painter.drawRect(screen_pos.x() - width // 2 - 4, screen_pos.y() - height // 2 - 4, width + 8, height + 8)

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()
        world_pos = self.screen_to_world(event.pos())

        if event.button() == Qt.RightButton:
            self.is_panning = False
            return

        if event.button() == Qt.LeftButton:
            self.drag_start_pos = self.snap_to_grid(world_pos)
            obj = self.editor.selected_object

            if isinstance(obj, dict) and obj.get('type') != 'trigger':
                handle = self.get_handle_at(event.pos())
                if handle:
                    self.editor.save_state()
                    self.drag_mode = 'resize'
                    self.resize_handle = handle
                    self.original_brush_rect = self.get_brush_rect_2d(obj)
                    return

            self.hot_object = self.get_object_at(world_pos)
            if self.hot_object != self.editor.selected_object:
                self.editor.set_selected_object(self.hot_object)

            if self.hot_object:
                self.editor.save_state()
                self.drag_mode = 'move'
                self.original_object_pos = self.hot_object.pos[:] if isinstance(self.hot_object, Thing) else self.hot_object['pos'][:]
            else:
                self.editor.save_state()
                self.drag_mode = 'new'
                new_brush = {'pos': [0,0,0], 'size': [0,0,0], 'operation': 'add', 'textures':{f:'default.png' for f in ['north','south','east','west','top','down']}}
                self.editor.brushes.append(new_brush)
                self.editor.set_selected_object(new_brush)

            self.editor.update_views()

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()
        if event.buttons() & Qt.RightButton:
             self.is_panning = True
             self.setCursor(Qt.ClosedHandCursor)
             delta = self.mouse_pos - self.last_mouse_pos
             self.pan_offset += delta
             self.last_mouse_pos = event.pos()
             self.update()
             return

        world_pos = self.screen_to_world(event.pos())
        snapped_world_pos = self.snap_to_grid(world_pos)

        if self.drag_mode != 'none' and self.editor.selected_object:
            ax1, ax2 = self.get_axes()
            ax_map = {'x': 0, 'y': 1, 'z': 2}
            obj = self.editor.selected_object
            target_pos = obj.pos if isinstance(obj, Thing) else obj['pos']

            if self.drag_mode == 'move':
                drag_delta = snapped_world_pos - self.drag_start_pos
                target_pos[ax_map[ax1]] = self.original_object_pos[ax_map[ax1]] + drag_delta.x()
                target_pos[ax_map[ax2]] = self.original_object_pos[ax_map[ax2]] + drag_delta.y()
                self.editor.property_editor.set_object(obj)
                self.editor.update_views()

            elif self.drag_mode == 'resize':
                self.resize_brush(snapped_world_pos)
                self.editor.update_views()

            elif self.drag_mode == 'new' and isinstance(obj, dict):
                rect = QRect(self.drag_start_pos, snapped_world_pos).normalized()
                depth_ax_char = list({'x','y','z'} - {ax1, ax2})[0]
                depth_ax = ax_map[depth_ax_char]

                obj['pos'][ax_map[ax1]] = rect.center().x()
                obj['pos'][ax_map[ax2]] = rect.center().y()
                obj['size'][ax_map[ax1]] = rect.width() if rect.width() > 0 else self.grid_size
                obj['size'][ax_map[ax2]] = rect.height() if rect.height() > 0 else self.grid_size
                if obj['size'][depth_ax] == 0: obj['size'][depth_ax] = self.grid_size * 4
                self.editor.update_views()
        else:
            self.update_cursor(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if not self.is_panning:
                self.contextMenuEvent(event)
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)
            return

        if event.button() == Qt.LeftButton:
            if self.drag_mode == 'new':
                selected = self.editor.selected_object
                if isinstance(selected, dict):
                    size = selected['size']
                    if any(abs(s) < self.grid_size/2 for s in [size[0], size[1], size[2]]):
                        self.editor.brushes.remove(selected)
                        self.editor.set_selected_object(None)
                        if self.editor.undo_stack:
                            self.editor.undo_stack.pop()

            self.drag_mode = 'none'
            self.resize_handle = ''
            self.update_cursor(event.pos())
            self.editor.update_views()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        zoom_factor = 1.1 if delta > 0 else 1 / 1.1

        old_world_pos = self.screen_to_world(event.pos())
        self.zoom *= zoom_factor
        new_world_pos = self.screen_to_world(event.pos())

        delta_world = old_world_pos - new_world_pos
        
        # --- FIX: Convert pan offset calculations to integers ---
        new_pan_x = self.pan_offset.x() - delta_world.x() * self.zoom
        new_pan_y = self.pan_offset.y() + delta_world.y() * self.zoom
        
        self.pan_offset.setX(int(new_pan_x))
        self.pan_offset.setY(int(new_pan_y))
        
        self.update()

    def zoom_in(self): self.zoom *= 1.2; self.update()
    def zoom_out(self): self.zoom /= 1.2; self.update()
    def get_axes(self): return {'top': ('x', 'z'), 'front': ('x', 'y'), 'side': ('z', 'y')}.get(self.view_type, ('x', 'z'))

    def world_to_screen(self, p):
        center_x = self.width() / 2 + self.pan_offset.x()
        center_y = self.height() / 2 + self.pan_offset.y()
        return QPoint(int(p.x() * self.zoom + center_x), int(-p.y() * self.zoom + center_y))

    def screen_to_world(self, p):
        center_x = self.width() / 2 + self.pan_offset.x()
        center_y = self.height() / 2 + self.pan_offset.y()
        if self.zoom == 0: return QPoint(0,0)
        return QPoint(int((p.x() - center_x) / self.zoom), int(-(p.y() - center_y) / self.zoom))

    def snap_to_grid(self, p):
        if not self.snap_to_grid_enabled or self.grid_size == 0: return p
        return QPoint(round(p.x() / self.grid_size) * self.grid_size, round(p.y() / self.grid_size) * self.grid_size)

    def draw_grid(self, painter):
        painter.setPen(QPen(QColor(70, 70, 70)))
        if self.grid_size > 0 and self.zoom > 0.05:
            start_world, end_world = self.screen_to_world(QPoint(0,0)), self.screen_to_world(QPoint(self.width(), self.height()))
            start_x, end_x = math.floor(start_world.x()/self.grid_size)*self.grid_size, math.ceil(end_world.x()/self.grid_size)*self.grid_size
            start_y, end_y = math.floor(start_world.y()/self.grid_size)*self.grid_size, math.ceil(end_world.y()/self.grid_size)*self.grid_size
            for x in range(start_x, end_x + 1, self.grid_size): painter.drawLine(self.world_to_screen(QPoint(x, start_y)), self.world_to_screen(QPoint(x, end_y)))
            for y in range(start_y, end_y + 1, self.grid_size): painter.drawLine(self.world_to_screen(QPoint(start_x, y)), self.world_to_screen(QPoint(end_x, y)))

        painter.setPen(QPen(QColor(90, 90, 90), 2))
        painter.drawLine(self.world_to_screen(QPoint(-self.world_size,0)), self.world_to_screen(QPoint(self.world_size,0)))
        painter.drawLine(self.world_to_screen(QPoint(0,-self.world_size)), self.world_to_screen(QPoint(0,self.world_size)))

    def draw_brushes(self, painter):
        should_show_caulk = self.editor.config.getboolean('Display', 'show_caulk', fallback=True)
        for brush in self.editor.brushes:
            is_caulk = all(tex == 'caulk' for tex in brush.get('textures', {}).values())
            if is_caulk and not should_show_caulk:
                continue

            rect = self.get_brush_rect_2d(brush)
            screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight())).normalized()
            is_selected = (brush == self.editor.selected_object)
            is_trigger = brush.get('type') == 'trigger'

            pen_color = QColor(255,255,0) if is_selected else QColor(0,255,0,180) if is_trigger else QColor(255,165,0, 180) if is_caulk else QColor(100,100,200) if brush.get('operation')=='subtract' else QColor(200,200,200)
            fill_color = QColor(0,255,0,40) if is_trigger else QColor(255,165,0,40) if is_caulk else QColor(100,100,200,100) if brush.get('operation')=='subtract' else QColor(200,200,200,50)

            painter.setPen(QPen(pen_color, 2 if is_selected else 1, Qt.DashLine if is_trigger else Qt.SolidLine))
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(screen_rect)
            if is_selected and not is_trigger: self.draw_resize_handles(painter, screen_rect)

    def get_brush_rect_2d(self, brush):
        ax1, ax2 = self.get_axes()
        ax_map = {'x':0, 'y':1, 'z':2}
        pos_x, pos_y = brush['pos'][ax_map[ax1]], brush['pos'][ax_map[ax2]]
        size_x, size_y = brush['size'][ax_map[ax1]], brush['size'][ax_map[ax2]]
        return QRect(int(pos_x - size_x/2), int(pos_y - size_y/2), int(size_x), int(size_y))

    def update_cursor(self, screen_pos):
        if self.is_panning: self.setCursor(Qt.ClosedHandCursor); return
        obj = self.editor.selected_object
        if isinstance(obj, dict) and obj.get('type') == 'trigger': self.setCursor(Qt.ArrowCursor); return

        handle = self.get_handle_at(screen_pos)
        if handle:
            if handle in ['n','s']: self.setCursor(Qt.SizeVerCursor)
            elif handle in ['e','w']: self.setCursor(Qt.SizeHorCursor)
            elif handle in ['nw','se']: self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ['ne','sw']: self.setCursor(Qt.SizeBDiagCursor)
        else: self.setCursor(Qt.ArrowCursor)

    def get_handle_rects(self, screen_rect):
        s = 12; hs = s//2
        c = screen_rect.center()
        return {
            'n': QRect(c.x()-hs, screen_rect.top()-hs, s, s), 's': QRect(c.x()-hs, screen_rect.bottom()-hs, s, s),
            'w': QRect(screen_rect.left()-hs, c.y()-hs, s, s), 'e': QRect(screen_rect.right()-hs, c.y()-hs, s, s),
            'nw': QRect(screen_rect.left()-hs, screen_rect.top()-hs, s, s), 'ne': QRect(screen_rect.right()-hs, screen_rect.top()-hs, s, s),
            'sw': QRect(screen_rect.left()-hs, screen_rect.bottom()-hs, s, s), 'se': QRect(screen_rect.right()-hs, screen_rect.bottom()-hs, s, s)
        }

    def get_handle_at(self, screen_pos):
        if not isinstance(self.editor.selected_object, dict): return None
        rect = self.get_brush_rect_2d(self.editor.selected_object)
        screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight())).normalized()
        for name, handle_rect in self.get_handle_rects(screen_rect).items():
            if handle_rect.contains(screen_pos): return name
        return None

    def draw_resize_handles(self, painter, rect):
        painter.setBrush(QBrush(QColor(255,255,0))); painter.setPen(QPen(QColor(0,0,0)))
        for handle in self.get_handle_rects(rect).values(): painter.drawRect(handle)

    def resize_brush(self, world_pos):
        if not isinstance(self.editor.selected_object, dict): return

        brush = self.editor.selected_object
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        ax1_idx, ax2_idx = ax_map[ax1], ax_map[ax2]

        orig_rect = self.original_brush_rect
        new_rect = QRect(orig_rect)

        if 'n' in self.resize_handle: new_rect.setTop(world_pos.y())
        if 's' in self.resize_handle: new_rect.setBottom(world_pos.y())
        if 'w' in self.resize_handle: new_rect.setLeft(world_pos.x())
        if 'e' in self.resize_handle: new_rect.setRight(world_pos.x())

        final_rect = new_rect.normalized()

        brush['pos'][ax1_idx] = final_rect.center().x()
        brush['pos'][ax2_idx] = final_rect.center().y()
        brush['size'][ax1_idx] = final_rect.width()
        brush['size'][ax2_idx] = final_rect.height()