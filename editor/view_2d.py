from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QImage
from PyQt5.QtCore import Qt, QPoint, QRect, QSize
from editor.things import PlayerStart, Light, Thing
import os
import math

class View2D(QWidget):
    def __init__(self, parent, editor, view_type):
        super().__init__(parent)
        self.editor = editor
        self.view_type = view_type

        # View properties
        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.world_size = 1024
        self.grid_size = 16
        self.snap_to_grid_enabled = True

        # Interaction state
        self.mouse_pos = QPoint(0, 0)
        self.last_mouse_pos = QPoint(0, 0)
        self.is_panning = False

        self.drag_mode = 'none'
        self.resize_handle = ''
        self.hot_object = None
        self.drag_start_pos = QPoint(0,0)
        self.original_object_pos = [0,0,0] # Unified position for brushes and things
        self.original_brush_rect = QRect(0,0,0,0)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)


    def contextMenuEvent(self, event):
        """Handles right-click to show a context menu for adding Things."""
        menu = QMenu(self)
        add_thing_menu = menu.addMenu("Add Thing")
        add_player_start_action = add_thing_menu.addAction("Player Start")
        add_light_action = add_thing_menu.addAction("Light")

        menu.addSeparator()
        place_camera_action = menu.addAction("Place camera here")

        action = menu.exec_(self.mapToGlobal(event.pos()))

        world_pos = self.screen_to_world(event.pos())
        snapped_pos = self.snap_to_grid(world_pos)

        pos3d = [0, 0, 0]
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        pos3d[ax_map[ax1]] = snapped_pos.x()
        pos3d[ax_map[ax2]] = snapped_pos.y()

        if action == place_camera_action:
            self.editor.view_3d.camera.pos[ax_map[ax1]] = snapped_pos.x()
            self.editor.view_3d.camera.pos[ax_map[ax2]] = snapped_pos.y()
            self.editor.update_views()
            return

        new_thing = None
        if action == add_player_start_action:
            new_thing = PlayerStart(pos3d)
        elif action == add_light_action:
            new_thing = Light(pos3d)

        if new_thing:
            self.editor.save_state()
            self.editor.things.append(new_thing)
            self.editor.set_selected_object(new_thing)
            self.update()

    def get_object_at(self, world_pos):
        """Finds the topmost object (brush or thing) at a world position."""
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}

        # Check things first as they are generally smaller
        for thing in reversed(self.editor.things):
            thing_pos_2d = QPoint(int(thing.pos[ax_map[ax1]]), int(thing.pos[ax_map[ax2]]))
            # Use a small radius for picking things
            if (world_pos - thing_pos_2d).manhattanLength() < self.grid_size / self.zoom:
                return thing

        # Check brushes
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
        
        cam_pos = self.editor.view_3d.camera.pos
        cam_angle = self.editor.view_3d.camera.yaw
        
        pos_2d = QPoint(int(cam_pos[ax_map[ax1]]), int(cam_pos[ax_map[ax2]]))
        screen_pos = self.world_to_screen(pos_2d)

        painter.setPen(QPen(QColor(255, 0, 255), 2))
        painter.setBrush(QBrush(QColor(255, 0, 255, 100)))
        painter.drawEllipse(screen_pos, 8, 8)

        line_len = 30
        if self.view_type == 'top':
            end_x = screen_pos.x() + line_len * math.cos(math.radians(cam_angle))
            end_y = screen_pos.y() + line_len * math.sin(math.radians(cam_angle))
            painter.drawLine(screen_pos.x(), screen_pos.y(), int(end_x), int(end_y))

    def draw_things(self, painter):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}

        for thing in self.editor.things:
            pos_2d = QPoint(int(thing.pos[ax_map[ax1]]), int(thing.pos[ax_map[ax2]]))
            screen_pos = self.world_to_screen(pos_2d)
            is_selected = (thing == self.editor.selected_object)

            painter.setPen(QPen(QColor(255, 255, 0) if is_selected else QColor(0, 255, 0), 2))
            painter.setBrush(Qt.NoBrush)

            if isinstance(thing, PlayerStart):
                painter.drawEllipse(screen_pos, 16, 16)
                angle = thing.properties.get('angle', 0.0)
                line_len = 20
                end_x = screen_pos.x() + line_len * math.cos(math.radians(angle))
                end_y = screen_pos.y() - line_len * math.sin(math.radians(angle))
                painter.drawLine(screen_pos.x(), screen_pos.y(), int(end_x), int(end_y))

            elif isinstance(thing, Light):
                if Light.pixmap:
                    size = Light.pixmap.size()
                    painter.drawPixmap(screen_pos.x() - size.width() // 2, screen_pos.y() - size.height() // 2, Light.pixmap)
                else: # Fallback drawing if pixmap fails
                    painter.drawRect(screen_pos.x() - 8, screen_pos.y() - 8, 16, 16)


            if is_selected:
                painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(screen_pos.x() - 21, screen_pos.y() - 21, 42, 42)

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()
        world_pos = self.screen_to_world(event.pos())

        if event.button() == Qt.RightButton:
            self.is_panning = True
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.LeftButton:
            self.drag_start_pos = self.snap_to_grid(world_pos)

            if isinstance(self.editor.selected_object, dict): # is a brush
                handle = self.get_handle_at(event.pos())
                if handle:
                    self.editor.save_state()
                    self.drag_mode = 'resize'
                    self.resize_handle = handle
                    self.original_brush_rect = self.get_brush_rect_2d(self.editor.selected_object)
                    return

            self.hot_object = self.get_object_at(world_pos)
            if self.hot_object != self.editor.selected_object:
                self.editor.set_selected_object(self.hot_object)

            if self.hot_object:
                self.editor.save_state()
                self.drag_mode = 'move'
                if isinstance(self.hot_object, dict): # Brush
                    self.original_object_pos = self.hot_object['pos'][:]
                else: # Thing
                    self.original_object_pos = self.hot_object.pos[:]
            else: # Clicked on empty space, start new brush
                self.drag_mode = 'new'
                new_brush = {'pos': [0,0,0], 'size': [0,0,0], 'operation': 'add'}
                self.editor.brushes.append(new_brush)
                self.editor.set_selected_object(new_brush)

            self.update()

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()

        if self.is_panning:
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

            if self.drag_mode == 'move':
                drag_delta = snapped_world_pos - self.drag_start_pos
                if isinstance(obj, dict): # Brush
                    obj['pos'][ax_map[ax1]] = self.original_object_pos[ax_map[ax1]] + drag_delta.x()
                    obj['pos'][ax_map[ax2]] = self.original_object_pos[ax_map[ax2]] + drag_delta.y()
                elif isinstance(obj, Thing): # Thing
                    obj.pos[ax_map[ax1]] = self.original_object_pos[ax_map[ax1]] + drag_delta.x()
                    obj.pos[ax_map[ax2]] = self.original_object_pos[ax_map[ax2]] + drag_delta.y()
                self.editor.property_editor.set_object(obj) # Refresh property editor
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
                if obj['size'][depth_ax] == 0:
                    obj['size'][depth_ax] = self.grid_size * 4
                self.editor.update_views()
        else:
            self.update_cursor(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if (event.pos() - self.last_mouse_pos).manhattanLength() < 3:
                 self.contextMenuEvent(event)
            self.is_panning = False
            self.update_cursor(event.pos())

        elif event.button() == Qt.LeftButton:
            if self.drag_mode == 'new':
                selected = self.editor.selected_object
                if selected and isinstance(selected, dict):
                    size = selected['size']
                    if abs(size[0]) < self.grid_size or abs(size[1]) < self.grid_size or abs(size[2]) < self.grid_size:
                        self.editor.brushes.remove(selected)
                        self.editor.set_selected_object(None)
                    else:
                        self.editor.save_state()
            
            self.drag_mode, self.resize_handle = 'none', ''
            self.editor.update_views()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        zoom_factor = 1.1 if delta > 0 else 1 / 1.1
        self.zoom *= zoom_factor
        self.update()

    def zoom_in(self):
        self.zoom *= 1.1
        self.update()

    def zoom_out(self):
        self.zoom /= 1.1
        self.update()

    def get_axes(self):
        # Defines which 3D axes map to the 2D view's X and Y
        if self.view_type == 'top':
            return ('x', 'z')  # X-axis horizontal, Z-axis vertical
        elif self.view_type == 'front':
            return ('x', 'y')  # X-axis horizontal, Y-axis vertical
        elif self.view_type == 'side':
            return ('z', 'y')  # Z-axis horizontal, Y-axis vertical
        return ('x', 'z') # Default

    def world_to_screen(self, p):
        center_x = self.width() / 2 + self.pan_offset.x()
        center_y = self.height() / 2 + self.pan_offset.y()
        # Invert Y-axis for standard screen coordinates (Y increases downwards)
        screen_x = p.x() * self.zoom + center_x
        screen_y = -p.y() * self.zoom + center_y
        return QPoint(int(screen_x), int(screen_y))

    def screen_to_world(self, p):
        center_x = self.width() / 2 + self.pan_offset.x()
        center_y = self.height() / 2 + self.pan_offset.y()
        # Invert Y-axis for standard screen coordinates
        world_x = (p.x() - center_x) / self.zoom
        world_y = -(p.y() - center_y) / self.zoom
        return QPoint(int(world_x), int(world_y))

    def snap_to_grid(self, p):
        if not self.snap_to_grid_enabled or self.grid_size == 0: return p
        return QPoint(round(p.x() / self.grid_size) * self.grid_size, round(p.y() / self.grid_size) * self.grid_size)

    def draw_grid(self, painter):
        painter.setPen(QPen(QColor(70, 70, 70)))
        if self.grid_size > 0 and self.zoom > 0.05:
            start_world = self.screen_to_world(QPoint(0,0))
            end_world = self.screen_to_world(QPoint(self.width(), self.height()))
            for x in range(start_world.x() - self.grid_size, end_world.x() + self.grid_size, self.grid_size):
                p1, p2 = self.world_to_screen(QPoint(x, start_world.y())), self.world_to_screen(QPoint(x, end_world.y()))
                painter.drawLine(p1, p2)
            for y in range(start_world.y() - self.grid_size, end_world.y() + self.grid_size, self.grid_size):
                p1, p2 = self.world_to_screen(QPoint(start_world.x(), y)), self.world_to_screen(QPoint(end_world.x(), y))
                painter.drawLine(p1, p2)
        # Draw origin lines
        painter.setPen(QPen(QColor(90, 90, 90), 2))
        p1, p2 = self.world_to_screen(QPoint(-self.world_size,0)), self.world_to_screen(QPoint(self.world_size,0))
        painter.drawLine(p1,p2)
        p1, p2 = self.world_to_screen(QPoint(0,-self.world_size)), self.world_to_screen(QPoint(0,self.world_size))
        painter.drawLine(p1,p2)

    def draw_brushes(self, painter):
        for brush in self.editor.brushes:
            rect = self.get_brush_rect_2d(brush)
            screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
            is_selected = (brush == self.editor.selected_object)
            is_subtract = brush.get('operation') == 'subtract'

            pen_color = QColor(255,255,0) if is_selected else QColor(100,100,200) if is_subtract else QColor(200,200,200)
            painter.setPen(QPen(pen_color, 2 if is_selected else 1))

            fill_color = QColor(100,100,200,100) if is_subtract else QColor(200,200,200,50)
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(screen_rect)

            if is_selected:
                self.draw_resize_handles(painter, screen_rect)

    def get_brush_rect_2d(self, brush):
        ax1, ax2 = self.get_axes()
        ax_map = {'x':0, 'y':1, 'z':2}
        pos_x = brush['pos'][ax_map[ax1]]
        pos_y = brush['pos'][ax_map[ax2]]
        size_x = brush['size'][ax_map[ax1]]
        size_y = brush['size'][ax_map[ax2]]

        left = int(pos_x - size_x / 2)
        top = int(pos_y - size_y / 2)
        width = int(size_x)
        height = int(size_y)

        return QRect(left, top, width, height)

    def update_cursor(self, screen_pos):
        if self.is_panning:
            self.setCursor(Qt.ClosedHandCursor)
            return

        handle = self.get_handle_at(screen_pos)
        if handle:
            if handle in ['n','s']: self.setCursor(Qt.SizeVerCursor)
            elif handle in ['e','w']: self.setCursor(Qt.SizeHorCursor)
            elif handle in ['nw','se']: self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ['ne','sw']: self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def get_handle_rects(self, screen_rect):
        s = 12
        hs = s // 2
        return {
            'n': QRect(screen_rect.center().x() - hs, screen_rect.top() - hs, s, s),
            's': QRect(screen_rect.center().x() - hs, screen_rect.bottom() - hs, s, s),
            'w': QRect(screen_rect.left() - hs, screen_rect.center().y() - hs, s, s),
            'e': QRect(screen_rect.right() - hs, screen_rect.center().y() - hs, s, s),
            'nw': QRect(screen_rect.left() - hs, screen_rect.top() - hs, s, s),
            'ne': QRect(screen_rect.right() - hs, screen_rect.top() - hs, s, s),
            'sw': QRect(screen_rect.left() - hs, screen_rect.bottom() - hs, s, s),
            'se': QRect(screen_rect.right() - hs, screen_rect.bottom() - hs, s, s)
        }

    def get_handle_at(self, screen_pos):
        if not isinstance(self.editor.selected_object, dict): return None
        rect = self.get_brush_rect_2d(self.editor.selected_object)
        screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
        handles = self.get_handle_rects(screen_rect)
        for name, handle_rect in handles.items():
            if handle_rect.contains(screen_pos):
                return name
        return None

    def draw_resize_handles(self, painter, rect):
        painter.setBrush(QBrush(QColor(255,255,0)))
        painter.setPen(QPen(QColor(0,0,0)))
        handles = self.get_handle_rects(rect)
        for handle in handles.values():
            painter.drawRect(handle)

    def resize_brush(self, world_pos):
        if not isinstance(self.editor.selected_object, dict): return
        brush = self.editor.selected_object
        new_rect = QRect(self.original_brush_rect)

        if 'n' in self.resize_handle: new_rect.setTop(world_pos.y())
        if 's' in self.resize_handle: new_rect.setBottom(world_pos.y())
        if 'w' in self.resize_handle: new_rect.setLeft(world_pos.x())
        if 'e' in self.resize_handle: new_rect.setRight(world_pos.x())

        new_rect = new_rect.normalized()
        ax1, ax2 = self.get_axes()
        ax_map = {'x':0, 'y':1, 'z':2}

        brush['pos'][ax_map[ax1]] = new_rect.center().x()
        brush['pos'][ax_map[ax2]] = new_rect.center().y()
        brush['size'][ax_map[ax1]] = new_rect.width()
        brush['size'][ax_map[ax2]] = new_rect.height()