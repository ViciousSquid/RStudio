from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont
from PyQt5.QtCore import Qt, QPoint, QRect

class View2D(QWidget):
    def __init__(self, editor, view_type):
        super().__init__()
        self.editor = editor
        self.view_type = view_type  # 'top', 'side', 'front'
        
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
        
        self.drag_mode = 'none' # 'none', 'select', 'move', 'resize', 'new'
        self.resize_handle = '' # 'n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se'
        self.hot_brush_index = -1 # Index of brush under cursor
        self.drag_start_pos = QPoint(0,0)
        self.original_brush_rect = QRect(0,0,0,0)

        self.setMouseTracking(True)

    def get_axes(self):
        return ('x', 'z') if self.view_type == 'top' else ('x', 'y') if self.view_type == 'side' else ('z', 'y')

    def world_to_screen(self, p):
        center = QPoint(self.width() // 2, self.height() // 2)
        return QPoint(int(p.x() * self.zoom), int(p.y() * self.zoom)) + center + self.pan_offset

    def screen_to_world(self, p):
        center = QPoint(self.width() // 2, self.height() // 2)
        pos = p - center - self.pan_offset
        return QPoint(int(pos.x() / self.zoom), int(pos.y() / self.zoom))

    def snap_to_grid(self, pos):
        if not self.snap_to_grid_enabled: return pos
        return QPoint(
            round(pos.x() / self.grid_size) * self.grid_size,
            round(pos.y() / self.grid_size) * self.grid_size
        )

    # --- Event Handlers ---

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()
        world_pos = self.screen_to_world(event.pos())

        if event.button() == Qt.RightButton:
            self.is_panning = True
            self.setCursor(Qt.ClosedHandCursor)
        
        elif event.button() == Qt.LeftButton:
            self.drag_start_pos = self.snap_to_grid(world_pos)
            
            # Check if clicking a resize handle on a selected brush
            if self.editor.selected_brush_index != -1:
                handle = self.get_handle_at(event.pos())
                if handle:
                    self.drag_mode = 'resize'
                    self.resize_handle = handle
                    selected_brush = self.editor.brushes[self.editor.selected_brush_index]
                    self.original_brush_rect = self.get_brush_rect_2d(selected_brush)
                    return

            # Check if clicking a brush
            self.hot_brush_index = self.get_brush_at(world_pos)
            if self.hot_brush_index != -1:
                self.drag_mode = 'move'
                self.editor.selected_brush_index = self.hot_brush_index
                selected_brush = self.editor.brushes[self.editor.selected_brush_index]
                self.original_brush_rect = self.get_brush_rect_2d(selected_brush)
            else:
                # Start drawing a new brush
                self.drag_mode = 'new'
                self.editor.selected_brush_index = -1 # Deselect
                new_brush = {'pos': [0,0,0], 'size': [0,0,0], 'operation': 'add'}
                self.editor.brushes.append(new_brush)
                self.editor.selected_brush_index = len(self.editor.brushes) - 1

            self.update()

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()
        world_pos = self.screen_to_world(event.pos())
        snapped_world_pos = self.snap_to_grid(world_pos)
        delta = self.mouse_pos - self.last_mouse_pos

        if self.is_panning:
            self.pan_offset += delta
            self.update()
        
        elif self.drag_mode != 'none':
            if self.editor.selected_brush_index == -1: return
            brush = self.editor.brushes[self.editor.selected_brush_index]
            ax1, ax2 = self.get_axes()
            ax_map = {'x': 0, 'y': 1, 'z': 2}
            
            if self.drag_mode == 'move':
                drag_delta = snapped_world_pos - self.drag_start_pos
                brush['pos'][ax_map[ax1]] = self.original_brush_rect.x() + drag_delta.x() + self.original_brush_rect.width() // 2
                brush['pos'][ax_map[ax2]] = self.original_brush_rect.y() + drag_delta.y() + self.original_brush_rect.height() // 2
            
            elif self.drag_mode == 'resize':
                self.resize_brush(snapped_world_pos)

            elif self.drag_mode == 'new':
                rect = QRect(self.drag_start_pos, snapped_world_pos).normalized()
                brush['pos'][ax_map[ax1]] = rect.center().x()
                brush['pos'][ax_map[ax2]] = rect.center().y()
                brush['size'][ax_map[ax1]] = rect.width()
                brush['size'][ax_map[ax2]] = rect.height()
                # Give it a default depth
                depth_ax = list({'x','y','z'} - {ax1, ax2})[0]
                brush['size'][ax_map[depth_ax]] = self.grid_size * 4

            self.editor.update_views()

        else: # Not dragging, just hovering
            self.update_cursor(event.pos())
        
        self.last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)

        elif event.button() == Qt.LeftButton:
            if self.drag_mode == 'new':
                # Prevent tiny brushes
                if self.editor.selected_brush_index != -1:
                    brush = self.editor.brushes[self.editor.selected_brush_index]
                    if brush['size'][0] < self.grid_size or brush['size'][1] < self.grid_size or brush['size'][2] < self.grid_size:
                        self.editor.brushes.pop()
                        self.editor.selected_brush_index = -1
                    else:
                        self.editor.save_state()
            elif self.drag_mode in ['move', 'resize']:
                self.editor.save_state()

            self.drag_mode = 'none'
            self.resize_handle = ''
            self.editor.update_views()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        zoom_factor = 1.1 if delta > 0 else 1 / 1.1
        self.zoom *= zoom_factor
        self.update()

    # --- Drawing Logic ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        self.draw_grid(painter)
        self.draw_brushes(painter)
        painter.end()

    def draw_grid(self, painter):
        painter.setPen(QPen(QColor(70, 70, 70)))
        center = self.world_to_screen(QPoint(0,0))
        painter.drawLine(0, center.y(), self.width(), center.y())
        painter.drawLine(center.x(), 0, center.x(), self.height())

    def draw_brushes(self, painter):
        for i, brush in enumerate(self.editor.brushes):
            rect = self.get_brush_rect_2d(brush)
            screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
            
            color = QColor(200, 50, 50) if i == self.editor.selected_brush_index else QColor(200, 200, 200)
            painter.setPen(QPen(color, 2))
            
            fill_color = QColor(100, 100, 200, 100) if brush.get('operation') == 'subtract' else QColor(200, 200, 200, 50)
            painter.setBrush(QBrush(fill_color))

            painter.drawRect(screen_rect)

            if i == self.editor.selected_brush_index:
                self.draw_resize_handles(painter, screen_rect)
    
    def draw_resize_handles(self, painter, rect):
        painter.setBrush(QBrush(QColor(255, 255, 0)))
        painter.setPen(QPen(QColor(0,0,0)))
        handle_size = 8
        hs = handle_size // 2
        
        handles = {
            'n': QRect(rect.center().x() - hs, rect.top() - hs, handle_size, handle_size),
            's': QRect(rect.center().x() - hs, rect.bottom() - hs, handle_size, handle_size),
            'w': QRect(rect.left() - hs, rect.center().y() - hs, handle_size, handle_size),
            'e': QRect(rect.right() - hs, rect.center().y() - hs, handle_size, handle_size),
            'nw': QRect(rect.left() - hs, rect.top() - hs, handle_size, handle_size),
            'ne': QRect(rect.right() - hs, rect.top() - hs, handle_size, handle_size),
            'sw': QRect(rect.left() - hs, rect.bottom() - hs, handle_size, handle_size),
            'se': QRect(rect.right() - hs, rect.bottom() - hs, handle_size, handle_size),
        }
        for handle in handles.values():
            painter.drawRect(handle)

    # --- Helper Methods ---
    def get_brush_rect_2d(self, brush):
        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        pos_x = brush['pos'][ax_map[ax1]]
        pos_y = brush['pos'][ax_map[ax2]]
        size_x = brush['size'][ax_map[ax1]]
        size_y = brush['size'][ax_map[ax2]]
        return QRect(pos_x - size_x // 2, pos_y - size_y // 2, size_x, size_y)

    def get_brush_at(self, world_pos):
        for i, brush in reversed(list(enumerate(self.editor.brushes))):
            if self.get_brush_rect_2d(brush).contains(world_pos):
                return i
        return -1

    def get_handle_at(self, screen_pos):
        if self.editor.selected_brush_index == -1: return None
        rect = self.get_brush_rect_2d(self.editor.brushes[self.editor.selected_brush_index])
        screen_rect = QRect(self.world_to_screen(rect.topLeft()), self.world_to_screen(rect.bottomRight()))
        
        handle_size = 12 # Larger for clicking
        hs = handle_size // 2
        handles = {
            'n': QRect(screen_rect.center().x() - hs, screen_rect.top() - hs, handle_size, handle_size),
            's': QRect(screen_rect.center().x() - hs, screen_rect.bottom() - hs, handle_size, handle_size),
            'w': QRect(screen_rect.left() - hs, screen_rect.center().y() - hs, handle_size, handle_size),
            'e': QRect(screen_rect.right() - hs, screen_rect.center().y() - hs, handle_size, handle_size),
            'nw': QRect(screen_rect.left() - hs, screen_rect.top() - hs, handle_size, handle_size),
            'ne': QRect(screen_rect.right() - hs, screen_rect.top() - hs, handle_size, handle_size),
            'sw': QRect(screen_rect.left() - hs, screen_rect.bottom() - hs, handle_size, handle_size),
            'se': QRect(screen_rect.right() - hs, screen_rect.bottom() - hs, handle_size, handle_size),
        }
        for name, handle_rect in handles.items():
            if handle_rect.contains(screen_pos):
                return name
        return None
    
    def update_cursor(self, screen_pos):
        handle = self.get_handle_at(screen_pos)
        if handle:
            if handle in ['n', 's']: self.setCursor(Qt.SizeVerCursor)
            elif handle in ['e', 'w']: self.setCursor(Qt.SizeHorCursor)
            elif handle in ['nw', 'se']: self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ['ne', 'sw']: self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def resize_brush(self, world_pos):
        if self.editor.selected_brush_index == -1: return
        brush = self.editor.brushes[self.editor.selected_brush_index]
        new_rect = QRect(self.original_brush_rect)

        if 'n' in self.resize_handle: new_rect.setTop(world_pos.y())
        if 's' in self.resize_handle: new_rect.setBottom(world_pos.y())
        if 'w' in self.resize_handle: new_rect.setLeft(world_pos.x())
        if 'e' in self.resize_handle: new_rect.setRight(world_pos.x())

        new_rect = new_rect.normalized()

        ax1, ax2 = self.get_axes()
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        brush['pos'][ax_map[ax1]] = new_rect.center().x()
        brush['pos'][ax_map[ax2]] = new_rect.center().y()
        brush['size'][ax_map[ax1]] = new_rect.width()
        brush['size'][ax_map[ax2]] = new_rect.height()