from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush
from PyQt5.QtCore import Qt, QPoint, QRect
from editor.things import PlayerStart, Light, Thing

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

    def contextMenuEvent(self, event):
        """Handles right-click to show a context menu for adding Things."""
        menu = QMenu(self)
        things_menu = menu.addMenu("Things >")
        
        add_player_start_action = things_menu.addAction("Player Start")
        add_light_action = things_menu.addAction("Light")
        
        action = menu.exec_(self.mapToGlobal(event.pos()))
        
        world_pos = self.screen_to_world(event.pos())
        snapped_pos = self.snap_to_grid(world_pos)
        
        pos3d = [0, 0, 0]
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        pos3d[ax_map[ax1]] = snapped_pos.x()
        pos3d[ax_map[ax2]] = snapped_pos.y()

        new_thing = None
        if action == add_player_start_action:
            new_thing = PlayerStart(pos3d)
        elif action == add_light_action:
            new_thing = Light(pos3d)
            
        if new_thing:
            self.editor.save_state()
            self.editor.things.append(new_thing)
            self.editor.set_selected_object(new_thing)

    def get_object_at(self, world_pos):
        """Finds the topmost object (brush or thing) at a world position."""
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        
        for thing in reversed(self.editor.things):
            thing_pos_2d = QPoint(thing.pos[ax_map[ax1]], thing.pos[ax_map[ax2]])
            if (world_pos - thing_pos_2d).manhattanLength() < 20 / self.zoom:
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
        painter.end()

    def draw_things(self, painter):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        
        for thing in self.editor.things:
            pos_2d = QPoint(thing.pos[ax_map[ax1]], thing.pos[ax_map[ax2]])
            screen_pos = self.world_to_screen(pos_2d)
            
            if isinstance(thing, PlayerStart):
                painter.setPen(QPen(QColor(0, 255, 0), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(screen_pos, 16, 16)
                painter.drawLine(screen_pos.x() - 16, screen_pos.y(), screen_pos.x() + 16, screen_pos.y())
                painter.drawLine(screen_pos.x(), screen_pos.y() - 16, screen_pos.x(), screen_pos.y() + 16)
            
            elif isinstance(thing, Light) and Light.pixmap:
                size = Light.pixmap.size()
                painter.drawPixmap(screen_pos.x() - size.width() // 2, screen_pos.y() - size.height() // 2, Light.pixmap)
            
            if thing == self.editor.selected_object:
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
            
            if self.editor.selected_object and isinstance(self.editor.selected_object, dict):
                handle = self.get_handle_at(event.pos())
                if handle:
                    self.drag_mode = 'resize'
                    self.resize_handle = handle
                    self.original_brush_rect = self.get_brush_rect_2d(self.editor.selected_object)
                    return

            self.hot_object = self.get_object_at(world_pos)
            if self.hot_object != self.editor.selected_object:
                self.editor.set_selected_object(self.hot_object)
            
            if self.hot_object:
                self.drag_mode = 'move'
                # Store the original position for dragging
                if isinstance(self.hot_object, dict): # Brush
                    self.original_object_pos = self.hot_object['pos'][:]
                else: # Thing
                    self.original_object_pos = self.hot_object.pos[:]
            else: # Clicked on empty space
                self.drag_mode = 'new'
                new_brush = {'pos': [0,0,0], 'size': [0,0,0], 'operation': 'add', 'properties': {}}
                self.editor.brushes.append(new_brush)
                self.editor.set_selected_object(new_brush)
            self.update()
            
    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()
        delta = self.mouse_pos - self.last_mouse_pos

        if self.is_panning:
            self.pan_offset += delta
            self.last_mouse_pos = event.pos()
            self.update()
            return
            
        world_pos = self.screen_to_world(event.pos())
        snapped_world_pos = self.snap_to_grid(world_pos)
        
        if self.drag_mode != 'none' and self.editor.selected_object:
            ax1, ax2 = self.get_axes()
            ax_map = {'x': 0, 'y': 1, 'z': 2}
            
            if self.drag_mode == 'move':
                drag_delta = snapped_world_pos - self.drag_start_pos
                obj = self.editor.selected_object
                
                # Simplified and corrected position update logic
                if isinstance(obj, dict): # Brush
                    obj['pos'][ax_map[ax1]] = self.original_object_pos[ax_map[ax1]] + drag_delta.x()
                    obj['pos'][ax_map[ax2]] = self.original_object_pos[ax_map[ax2]] + drag_delta.y()
                elif isinstance(obj, Thing): # Thing
                    obj.pos[ax_map[ax1]] = self.original_object_pos[ax_map[ax1]] + drag_delta.x()
                    obj.pos[ax_map[ax2]] = self.original_object_pos[ax_map[ax2]] + drag_delta.y()
                    if hasattr(obj, 'update_from_properties'):
                        obj.update_from_properties()
                self.editor.update_views()

            elif self.drag_mode == 'resize':
                self.resize_brush(snapped_world_pos)
                self.editor.update_views()
                
            elif self.drag_mode == 'new':
                rect = QRect(self.drag_start_pos, snapped_world_pos).normalized()
                self.editor.selected_object['pos'][ax_map[ax1]] = rect.center().x()
                self.editor.selected_object['pos'][ax_map[ax2]] = rect.center().y()
                self.editor.selected_object['size'][ax_map[ax1]] = rect.width()
                self.editor.selected_object['size'][ax_map[ax2]] = rect.height()
                depth_ax = list({'x','y','z'} - {ax1, ax2})[0]
                self.editor.selected_object['size'][ax_map[depth_ax]] = self.grid_size * 4
                self.editor.update_views()
        else:
            self.update_cursor(event.pos())
        self.last_mouse_pos = event.pos()
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if not self.is_panning or (event.pos() - self.last_mouse_pos).manhattanLength() < 3:
                 self.contextMenuEvent(event)
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)
            
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
            elif self.drag_mode in ['move', 'resize']:
                self.editor.save_state()
                
            self.drag_mode, self.resize_handle = 'none', ''
            self.editor.update_views()

    def get_axes(self):
        return ('x','z') if self.view_type=='top' else ('x','y') if self.view_type=='side' else ('z','y')

    def world_to_screen(self,p):
        center=QPoint(self.width()//2,self.height()//2)
        return QPoint(int(p.x()*self.zoom),int(p.y()*self.zoom))+center+self.pan_offset

    def screen_to_world(self,p):
        center=QPoint(self.width()//2,self.height()//2)
        pos=p-center-self.pan_offset
        return QPoint(int(pos.x()/self.zoom),int(pos.y()/self.zoom))

    def snap_to_grid(self,p):
        if not self.snap_to_grid_enabled or self.grid_size==0: return p
        return QPoint(round(p.x()/self.grid_size)*self.grid_size,round(p.y()/self.grid_size)*self.grid_size)

    def draw_grid(self, painter):
        painter.setPen(QPen(QColor(70, 70, 70)))
        if self.grid_size > 0 and self.zoom > 0.05:
            for x in range(-self.world_size, self.world_size + 1, self.grid_size):
                p1, p2 = self.world_to_screen(QPoint(x, -self.world_size)), self.world_to_screen(QPoint(x, self.world_size))
                painter.drawLine(p1, p2)
            for y in range(-self.world_size, self.world_size + 1, self.grid_size):
                p1, p2 = self.world_to_screen(QPoint(-self.world_size, y)), self.world_to_screen(QPoint(self.world_size, y))
                painter.drawLine(p1, p2)
        painter.setPen(QPen(QColor(90, 90, 90), 2))
        p1, p2 = self.world_to_screen(QPoint(-self.world_size,0)), self.world_to_screen(QPoint(self.world_size,0))
        painter.drawLine(p1,p2)
        p1, p2 = self.world_to_screen(QPoint(0,-self.world_size)), self.world_to_screen(QPoint(0,self.world_size))
        painter.drawLine(p1,p2)

    def draw_brushes(self, painter):
        for brush in self.editor.brushes:
            rect = self.get_brush_rect_2d(brush)
            screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
            color = QColor(200,50,50) if brush == self.editor.selected_object else QColor(200,200,200)
            painter.setPen(QPen(color, 2))
            fill_color = QColor(100,100,200,100) if brush.get('operation') == 'subtract' else QColor(200,200,200,50)
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(screen_rect)
            if brush == self.editor.selected_object:
                self.draw_resize_handles(painter, screen_rect)

    def get_brush_rect_2d(self, brush):
        ax1, ax2 = self.get_axes()
        ax_map = {'x':0, 'y':1, 'z':2}
        pos_x,pos_y,size_x,size_y = brush['pos'][ax_map[ax1]],brush['pos'][ax_map[ax2]],brush['size'][ax_map[ax1]],brush['size'][ax_map[ax2]]
        return QRect(pos_x-size_x//2, pos_y-size_y//2, size_x, size_y)

    def wheelEvent(self, event):
        self.zoom *= 1.1 if event.angleDelta().y() > 0 else 1/1.1
        self.update()

    def update_cursor(self, screen_pos):
        handle = self.get_handle_at(screen_pos)
        if handle:
            if handle in ['n','s']: self.setCursor(Qt.SizeVerCursor)
            elif handle in ['e','w']: self.setCursor(Qt.SizeHorCursor)
            elif handle in ['nw','se']: self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ['ne','sw']: self.setCursor(Qt.SizeBDiagCursor)
        else: self.setCursor(Qt.ArrowCursor)

    def get_handle_at(self, screen_pos):
        if not isinstance(self.editor.selected_object, dict): return None
        rect = self.get_brush_rect_2d(self.editor.selected_object)
        screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
        s=12
        hs=s//2
        handles = {
            'n': QRect(screen_rect.center().x()-hs, screen_rect.top()-hs,s,s),
            's': QRect(screen_rect.center().x()-hs, screen_rect.bottom()-hs,s,s),
            'w': QRect(screen_rect.left()-hs, screen_rect.center().y()-hs,s,s),
            'e': QRect(screen_rect.right()-hs, screen_rect.center().y()-hs,s,s),
            'nw': QRect(screen_rect.left()-hs, screen_rect.top()-hs,s,s),
            'ne': QRect(screen_rect.right()-hs, screen_rect.top()-hs,s,s),
            'sw': QRect(screen_rect.left()-hs, screen_rect.bottom()-hs,s,s),
            'se': QRect(screen_rect.right()-hs, screen_rect.bottom()-hs,s,s)
        }
        for name, handle_rect in handles.items():
            if handle_rect.contains(screen_pos): return name
        return None

    def draw_resize_handles(self, painter, rect):
        painter.setBrush(QBrush(QColor(255,255,0)))
        painter.setPen(QPen(QColor(0,0,0)))
        s=8
        hs=s//2
        handles = {
            'n': QRect(rect.center().x()-hs, rect.top()-hs,s,s),
            's': QRect(rect.center().x()-hs, rect.bottom()-hs,s,s),
            'w': QRect(rect.left()-hs, rect.center().y()-hs,s,s),
            'e': QRect(rect.right()-hs, rect.center().y()-hs,s,s),
            'nw': QRect(rect.left()-hs, rect.top()-hs,s,s),
            'ne': QRect(rect.right()-hs, rect.top()-hs,s,s),
            'sw': QRect(rect.left()-hs, rect.bottom()-hs,s,s),
            'se': QRect(rect.right()-hs, rect.bottom()-hs,s,s)
        }
        for handle in handles.values(): painter.drawRect(handle)

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