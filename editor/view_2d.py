from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QPoint, QRect

class View2D(QWidget):
    def __init__(self, editor, view_type='top'):
        super().__init__()
        self.editor = editor
        self.view_type = view_type
        self.setMinimumSize(200, 200)

        self.creation_state = None
        self.creation_start_pos = QPoint()
        self.creation_rect = QRect()

        self.grid_size = 16
        self.world_size = 1024
        self.snap_to_grid_enabled = True

        self.editing_state = None
        self.drag_start_pos = QPoint()
        self.original_brush_pos = None
        self.original_brush_size = None
        self.resize_handle = None # Initialize resize_handle

        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        self.draw_grid(painter)
        self.draw_brushes(painter)

        if self.creation_state in ["drawing", "drawn"]:
            painter.setPen(QPen(QColor(255, 255, 0), 1, Qt.DotLine))
            painter.setBrush(QColor(255, 255, 0, 30))
            painter.drawRect(self.creation_rect)

    def draw_grid(self, painter):
        painter.setPen(QPen(QColor(70, 70, 70), 1, Qt.SolidLine))
        center_x, center_y = self.width() / 2, self.height() / 2

        for i in range(-self.world_size // (2 * self.grid_size), self.world_size // (2 * self.grid_size) + 1):
            offset = i * self.grid_size
            painter.drawLine(int(center_x + offset), 0, int(center_x + offset), self.height())
            painter.drawLine(0, int(center_y + offset), self.width(), int(center_y + offset))


    def draw_brushes(self, painter):
        for i, brush in enumerate(self.editor.brushes):
            if self.creation_state and i == self.editor.selected_brush_index:
                continue

            is_selected = (i == self.editor.selected_brush_index)
            pen_color = QColor(255, 255, 0) if is_selected else QColor(255, 255, 255)
            painter.setPen(QPen(pen_color, 2, Qt.SolidLine))

            rect = self.get_brush_rect(brush)
            painter.drawRect(rect)

            if is_selected and self.editor.view_3d.edit_mode == 'resize':
                handle_size = 8
                painter.setBrush(QColor(0, 255, 255)) # Cyan handles

                # Top-left corner
                painter.drawRect(rect.topLeft().x() - handle_size // 2,
                                 rect.topLeft().y() - handle_size // 2,
                                 handle_size, handle_size)
                # Top-right corner
                painter.drawRect(rect.topRight().x() - handle_size // 2,
                                 rect.topRight().y() - handle_size // 2,
                                 handle_size, handle_size)
                # Bottom-left corner
                painter.drawRect(rect.bottomLeft().x() - handle_size // 2,
                                 rect.bottomLeft().y() - handle_size // 2,
                                 handle_size, handle_size)
                # Bottom-right corner
                painter.drawRect(rect.bottomRight().x() - handle_size // 2,
                                  rect.bottomRight().y() - handle_size // 2,
                                  handle_size, handle_size)

                # Mid-point handles (left, right, top, bottom)
                painter.drawRect(rect.left() - handle_size // 2,
                                 rect.center().y() - handle_size // 2,
                                 handle_size, handle_size)
                painter.drawRect(rect.right() - handle_size // 2,
                                 rect.center().y() - handle_size // 2,
                                 handle_size, handle_size)
                painter.drawRect(rect.center().x() - handle_size // 2,
                                 rect.top() - handle_size // 2,
                                 handle_size, handle_size)
                painter.drawRect(rect.center().x() - handle_size // 2,
                                 rect.bottom() - handle_size // 2,
                                 handle_size, handle_size)


    def get_brush_rect(self, brush):
        center_x, center_y = self.width() / 2, self.height() / 2
        if self.view_type == 'top':
            x, z = brush['pos'][0], brush['pos'][2]
            w, d = brush['size'][0], brush['size'][2]
            return QRect(int(center_x + x - w / 2), int(center_y + z - d / 2), int(w), int(d))
        elif self.view_type == 'side':
            x, y = brush['pos'][0], brush['pos'][1]
            w, h = brush['size'][0], brush['size'][1]
            return QRect(int(center_x + x - w / 2), int(center_y + y - h / 2), int(w), int(h))
        elif self.view_type == 'front':
            z, y = brush['pos'][2], brush['pos'][1]
            d, h = brush['size'][2], brush['size'][1]
            return QRect(int(center_x + z - d / 2), int(center_y + y - h / 2), int(d), int(h))
        return QRect()

    def to_world_coords(self, pos):
        center_x, center_y = self.width() / 2, self.height() / 2
        return QPoint(int(pos.x() - center_x), int(pos.y() - center_y))

    def to_view_coords(self, pos):
        center_x, center_y = self.width() / 2, self.height() / 2
        return QPoint(int(pos.x() + center_x), int(pos.y() + center_y))

    def snap_to_grid(self, pos, use_world_coords=False):
        if not self.snap_to_grid_enabled:
            return pos

        coords = self.to_world_coords(pos) if not use_world_coords else pos
        x = round(coords.x() / self.grid_size) * self.grid_size
        y = round(coords.y() / self.grid_size) * self.grid_size
        snapped_coords = QPoint(int(x), int(y))

        return self.to_view_coords(snapped_coords) if not use_world_coords else snapped_coords

    def get_resize_handle(self, pos, rect):
        """
        Determines if the given position `pos` is on a resize handle of the `rect`.
        Returns a string indicating the handle ('left', 'right', 'top', 'bottom', 'top-left', etc.)
        or None if no handle is hit.
        """
        handle_threshold = 10 # Pixels around the edge to consider a handle
        
        # Check corners first
        if rect.topLeft().x() - handle_threshold <= pos.x() <= rect.topLeft().x() + handle_threshold and \
           rect.topLeft().y() - handle_threshold <= pos.y() <= rect.topLeft().y() + handle_threshold:
            return 'top-left'
        if rect.topRight().x() - handle_threshold <= pos.x() <= rect.topRight().x() + handle_threshold and \
           rect.topRight().y() - handle_threshold <= pos.y() <= rect.topRight().y() + handle_threshold:
            return 'top-right'
        if rect.bottomLeft().x() - handle_threshold <= pos.x() <= rect.bottomLeft().x() + handle_threshold and \
           rect.bottomLeft().y() - handle_threshold <= pos.y() <= rect.bottomLeft().y() + handle_threshold:
            return 'bottom-left'
        if rect.bottomRight().x() - handle_threshold <= pos.x() <= rect.bottomRight().x() + handle_threshold and \
           rect.bottomRight().y() - handle_threshold <= pos.y() <= rect.bottomRight().y() + handle_threshold:
            return 'bottom-right'

        # Check edges
        if rect.left() - handle_threshold <= pos.x() <= rect.left() + handle_threshold and \
           rect.top() <= pos.y() <= rect.bottom():
            return 'left'
        if rect.right() - handle_threshold <= pos.x() <= rect.right() + handle_threshold and \
           rect.top() <= pos.y() <= rect.bottom():
            return 'right'
        if rect.top() - handle_threshold <= pos.y() <= rect.top() + handle_threshold and \
           rect.left() <= pos.x() <= rect.right():
            return 'top'
        if rect.bottom() - handle_threshold <= pos.y() <= rect.bottom() + handle_threshold and \
           rect.left() <= pos.x() <= rect.right():
            return 'bottom'
        
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.editor.selected_brush_index != -1 and self.editor.view_3d.edit_mode == 'resize':
                brush = self.editor.brushes[self.editor.selected_brush_index]
                rect = self.get_brush_rect(brush)
                handle = self.get_resize_handle(event.pos(), rect)
                if handle:
                    self.editing_state = "resizing"
                    self.drag_start_pos = self.snap_to_grid(event.pos())
                    self.original_brush_pos = brush['pos'][:]
                    self.original_brush_size = brush['size'][:]
                    self.resize_handle = handle
                    self.editor.update_views()
                    return

            if self.creation_state is None:
                for i, brush in reversed(list(enumerate(self.editor.brushes))):
                    rect = self.get_brush_rect(brush)
                    if rect.contains(event.pos()):
                        self.editor.selected_brush_index = i
                        self.editing_state = "dragging"
                        self.drag_start_pos = self.snap_to_grid(event.pos())
                        self.original_brush_pos = brush['pos'][:]
                        self.editor.update_views()
                        return

            if self.editor.view_3d.edit_mode == 'resize':
                return

            self.creation_state = "drawing"
            self.creation_start_pos = self.snap_to_grid(event.pos())
            self.creation_rect = QRect(self.creation_start_pos, self.creation_start_pos)

            self.editor.add_brush()
            self.editor.brushes[-1]['size'] = [0, 0, 0]

            self.editor.update_views()

    def mouseMoveEvent(self, event):
        snapped_pos = self.snap_to_grid(event.pos())

        if self.editing_state == "resizing":
            delta = self.to_world_coords(snapped_pos) - self.to_world_coords(self.drag_start_pos)
            if self.editor.selected_brush_index != -1:
                brush = self.editor.brushes[self.editor.selected_brush_index]

                # Store original values to avoid cumulative changes
                ox, oy, oz = self.original_brush_pos
                sx, sy, sz = self.original_brush_size

                # Apply resizing based on view type and handle
                if self.view_type == 'top':
                    if 'left' in self.resize_handle:
                        brush['size'][0] = int(sx - delta.x())
                        brush['pos'][0] = int(ox + delta.x() / 2)
                    if 'right' in self.resize_handle:
                        brush['size'][0] = int(sx + delta.x())
                        brush['pos'][0] = int(ox + delta.x() / 2)
                    if 'top' in self.resize_handle: # Corresponds to Z in top view
                        brush['size'][2] = int(sz - delta.y())
                        brush['pos'][2] = int(oz + delta.y() / 2)
                    if 'bottom' in self.resize_handle: # Corresponds to Z in top view
                        brush['size'][2] = int(sz + delta.y())
                        brush['pos'][2] = int(oz + delta.y() / 2)
                elif self.view_type == 'side': # X-Y plane
                    if 'left' in self.resize_handle:
                        brush['size'][0] = int(sx - delta.x())
                        brush['pos'][0] = int(ox + delta.x() / 2)
                    if 'right' in self.resize_handle:
                        brush['size'][0] = int(sx + delta.x())
                        brush['pos'][0] = int(ox + delta.x() / 2)
                    if 'top' in self.resize_handle:
                        brush['size'][1] = int(sy - delta.y())
                        brush['pos'][1] = int(oy + delta.y() / 2)
                    if 'bottom' in self.resize_handle:
                        brush['size'][1] = int(sy + delta.y())
                        brush['pos'][1] = int(oy + delta.y() / 2)
                elif self.view_type == 'front': # Z-Y plane
                    if 'left' in self.resize_handle: # Corresponds to Z in front view
                        brush['size'][2] = int(sz - delta.x())
                        brush['pos'][2] = int(oz + delta.x() / 2)
                    if 'right' in self.resize_handle: # Corresponds to Z in front view
                        brush['size'][2] = int(sz + delta.x())
                        brush['pos'][2] = int(oz + delta.x() / 2)
                    if 'top' in self.resize_handle:
                        brush['size'][1] = int(sy - delta.y())
                        brush['pos'][1] = int(oy + delta.y() / 2)
                    if 'bottom' in self.resize_handle:
                        brush['size'][1] = int(sy + delta.y())
                        brush['pos'][1] = int(oy + delta.y() / 2)

                # Ensure minimum size
                brush['size'][0] = max(brush['size'][0], self.grid_size)
                brush['size'][1] = max(brush['size'][1], self.grid_size)
                brush['size'][2] = max(brush['size'][2], self.grid_size)

                self.editor.update_views()
        elif self.creation_state == "drawing":
            self.creation_rect = QRect(self.creation_start_pos, snapped_pos).normalized()
            self.update()
        elif self.editing_state == "dragging":
            delta = self.to_world_coords(snapped_pos) - self.to_world_coords(self.drag_start_pos)
            if self.editor.selected_brush_index != -1:
                brush = self.editor.brushes[self.editor.selected_brush_index]
                new_pos = self.original_brush_pos[:]

                if self.view_type == 'top':
                    new_pos[0] = self.original_brush_pos[0] + delta.x()
                    new_pos[2] = self.original_brush_pos[2] + delta.y()
                elif self.view_type == 'side':
                    new_pos[0] = self.original_brush_pos[0] + delta.x()
                    new_pos[1] = self.original_brush_pos[1] + delta.y()
                elif self.view_type == 'front':
                    new_pos[2] = self.original_brush_pos[2] + delta.x()
                    new_pos[1] = self.original_brush_pos[1] + delta.y()

                brush['pos'] = new_pos
                self.editor.update_views()

    def mouseReleaseEvent(self, event):
        if self.creation_state == "drawing":
            self.creation_state = "drawn"
            self.update()

            world_rect = self.creation_rect.translated(int(-self.width() / 2), int(-self.height() / 2))
            brush = self.editor.brushes[-1]

            # Ensure minimum size for newly created brushes
            width = max(world_rect.width(), self.grid_size)
            height = max(world_rect.height(), self.grid_size)

            if self.view_type == 'top':
                brush['pos'] = [world_rect.center().x(), 0, world_rect.center().y()]
                brush['size'] = [width, self.grid_size, height]
            elif self.view_type == 'side':
                brush['pos'] = [world_rect.center().x(), world_rect.center().y(), 0]
                brush['size'] = [width, height, self.grid_size]
            elif self.view_type == 'front':
                brush['pos'] = [0, world_rect.center().y(), world_rect.center().x()]
                brush['size'] = [self.grid_size, height, width]

            self.creation_state = None
            self.creation_rect = QRect()
            self.editor.update_views()
        elif self.editing_state in ["dragging", "resizing"]:
            self.editing_state = None
            self.original_brush_pos = None
            self.original_brush_size = None
            self.resize_handle = None