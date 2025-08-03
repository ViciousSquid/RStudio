from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu, QAction, QHeaderView
from PyQt5.QtGui import QIcon, QColor, QBrush, QFont
from PyQt5.QtCore import Qt

class SceneHierarchy(QTreeWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        # Remove the header by setting its height to 0 and set column count to 2
        self.header().setVisible(False) 
        self.setColumnCount(2) # Set two columns
        self.header().setStretchLastSection(False) # Don't stretch the last section
        self.header().setSectionResizeMode(0, QHeaderView.Stretch) # Stretch the first column
        self.header().setSectionResizeMode(1, QHeaderView.Fixed) # Fixed size for the second column
        self.setColumnWidth(1, 20) # Set a small fixed width for the second column (for icons)


        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_menu)
        self.lock_icon = QIcon("assets/lock.png")
        self.hidden_icon = QIcon("assets/hidden.png")
        self.itemSelectionChanged.connect(self.handle_selection_change)

        # Load color icons
        self.color_icons = {
            'blue': QIcon("assets/circ_blue.png"),
            'green': QIcon("assets/circ_green.png"),
            'orange': QIcon("assets/circ_orange.png"),
            'pink': QIcon("assets/circ_pink.png"),
            'red': QIcon("assets/circ_red.png"),
            'white': QIcon("assets/circ_white.png"),
        }
        self.color_names = {
            "circ_blue.png": "blue",
            "circ_green.png": "green",
            "circ_orange.png": "orange",
            "circ_pink.png": "pink",
            "circ_red.png": "red",
            "circ_white.png": "white",
        }


    def refresh_list(self):
        self.blockSignals(True)
        self.clear()
        
        # Define font for headers
        header_font = QFont()
        header_font.setBold(True)

        # Add Brushes Header
        brushes_header = QTreeWidgetItem(self, ["Brushes"])
        brushes_header.setFlags(brushes_header.flags() & ~Qt.ItemIsSelectable)
        brushes_header.setForeground(0, QBrush(QColor("white")))
        brushes_header.setFont(0, header_font)
        brushes_header.setExpanded(True)
        
        # Add Brushes
        for i, brush_dict in enumerate(self.main_window.brushes):
            item_text = brush_dict.get('name', f'Brush {i+1}')
            item = QTreeWidgetItem(brushes_header, [item_text, ""]) # Add an empty string for the second column
            item.setData(0, Qt.UserRole, ('brush', i))
            
            # Check for lock status and apply icon
            if brush_dict.get('lock', False):
                item.setIcon(0, self.lock_icon)
            if brush_dict.get('hidden', False):
                item.setIcon(0, self.hidden_icon)
            
            # Display color icon if assigned
            if 'color' in brush_dict and brush_dict['color'] in self.color_icons:
                item.setIcon(1, self.color_icons[brush_dict['color']]) # Set icon in the second column
            
            if self.main_window.selected_object is brush_dict:
                item.setSelected(True)

        # Add Things Header
        things_header = QTreeWidgetItem(self, ["Things"])
        things_header.setFlags(things_header.flags() & ~Qt.ItemIsSelectable)
        things_header.setForeground(0, QBrush(QColor("white")))
        things_header.setFont(0, header_font)
        things_header.setExpanded(True)
        
        # Add Things
        for i, thing_obj in enumerate(self.main_window.things):
            item_text = thing_obj.name if thing_obj.name else f'Thing {i+1}'
            item = QTreeWidgetItem(things_header, [item_text, ""]) # Add an empty string for the second column
            item.setData(0, Qt.UserRole, ('thing', i))

            if self.main_window.selected_object is thing_obj:
                item.setSelected(True)
                
        self.blockSignals(False)

    def handle_selection_change(self):
        selected_items = self.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        
        if data:
            obj_type, obj_index = data
            if obj_type == 'brush':
                self.main_window.set_selected_object(self.main_window.brushes[obj_index])
            elif obj_type == 'thing':
                self.main_window.set_selected_object(self.main_window.things[obj_index])
        else:
             self.main_window.set_selected_object(None)

    def open_menu(self, position):
        menu = QMenu()
        selected_items = self.selectedItems()

        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'brush':
            brush_dict = self.main_window.brushes[data[1]]
            
            # Lock/Unlock Action
            is_locked = brush_dict.get('lock', False)
            lock_action_text = "Unlock" if is_locked else "Lock"
            lock_action = menu.addAction(lock_action_text)
            
            # Hide/Show Action
            is_hidden = brush_dict.get('hidden', False)
            hide_action_text = "Show" if is_hidden else "Hide"
            hide_action = menu.addAction(hide_action_text)
            
            menu.addSeparator()

            # Tag Submenu
            color_menu = menu.addMenu("Tag")

            # Add 'None' option
            none_action = color_menu.addAction("None")
            none_action.setCheckable(True)
            if 'color' not in brush_dict:
                none_action.setChecked(True)
            none_action.triggered.connect(lambda checked: self.set_brush_color(brush_dict, None, checked))
            
            color_menu.addSeparator() # Separator after "None"

            for color_name, icon in self.color_icons.items():
                action = color_menu.addAction(icon, color_name.capitalize())
                action.setCheckable(True)
                if brush_dict.get('color') == color_name:
                    action.setChecked(True)
                action.triggered.connect(lambda checked, c=color_name: self.set_brush_color(brush_dict, c, checked))
            
            action = menu.exec_(self.viewport().mapToGlobal(position))

            if action == lock_action:
                self.main_window.save_state()
                brush_dict['lock'] = not is_locked
                self.main_window.update_all_ui()
            elif action == hide_action:
                self.main_window.save_state()
                brush_dict['hidden'] = not is_hidden
                self.main_window.update_all_ui()

    def set_brush_color(self, brush_dict, color_name, checked):
        self.main_window.save_state()
        if checked:
            if color_name is None:
                if 'color' in brush_dict:
                    del brush_dict['color']
            else:
                brush_dict['color'] = color_name
        else: # If unchecked
            if 'color' in brush_dict and brush_dict['color'] == color_name:
                del brush_dict['color']
            # If the "None" option is unchecked, it implies a color *should* be selected, but since this is
            # about unsetting, we only act if 'color_name' is None
            elif color_name is None and 'color' not in brush_dict:
                # If "None" was unchecked and no color was set, do nothing.
                pass
        self.main_window.update_all_ui()