from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QFrame, QCheckBox, QRadioButton, \
    QButtonGroup
import pyvista as pv
from pyvistaqt import QtInteractor
import h5py
import numpy as np

# Initial camera direction for the 3D view (unit-norm on use): from the
# subject's upper left, slightly posterior — nose pointing left, vertex up.
# Same home view for head and ROI meshes.
HOME_VIEW_DIRECTION = np.array([-0.75, -0.30, 0.58])


class MeshWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- 1. Main Layout ---
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # --- 2. Top Control Bar ---
        self.controls_frame = QFrame()
        # Minimum height; the layout grows the bar with the (scaled) fonts.
        self.controls_frame.setMinimumHeight(40)
        self.controls_frame.setStyleSheet("background-color: #f0f0f0; border-bottom: 1px solid #ccc;")
        self.controls_layout = QHBoxLayout(self.controls_frame)
        self.controls_layout.setContentsMargins(10, 5, 10, 5)

        lbl = QLabel("Color Data:")
        lbl.setStyleSheet("font-weight: bold; color: #333;")
        self.controls_layout.addWidget(lbl)

        self.scalar_selector = QComboBox()
        # Wide enough for the longest entry; grows with the available space.
        self.scalar_selector.setMinimumWidth(280)
        from PyQt5.QtWidgets import QSizePolicy
        self.scalar_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scalar_selector.setStyleSheet("""
                    /* 1. Main Box Styling */
                    QComboBox {
                        border: 2px solid #5dade2;
                        border-radius: 8px;
                        padding: 4px 10px;
                        background-color: #ffffff;
                        color: #333333;
                        font-size: 14px;
                    }

                    /* Hover state for the main box */
                    QComboBox:hover {
                        border: 2px solid #4A90E2; 
                    }

                    /* 2. The Drop-down Button area */
                    QComboBox::drop-down {
                        subcontrol-origin: padding;
                        subcontrol-position: top right;
                        width: 28px;
                        border-left: 1px solid #e0e0e0; /* Subtle divider */
                        border-top-right-radius: 8px;
                        border-bottom-right-radius: 8px;
                        background-color: #f4f7fa;
                    }

                    /* The Arrow itself */
                    QComboBox::down-arrow {
                        image: url(:/qt-project.org/styles/commonstyle/images/arrowdown.png);
                        width: 10px; 
                        height: 10px;
                    }

                    /* Disabled arrow (optional but good practice) */
                    QComboBox::down-arrow:disabled {
                        image: url(:/qt-project.org/styles/commonstyle/images/arrowdown_disabled.png);
                    }

                    /* 3. The Pop-up List (Menu) */
                    QComboBox QAbstractItemView {
                        border: 2px solid #5dade2;
                        border-radius: 4px;
                        background-color: #ffffff;
                        color: #333333;
                        selection-background-color: #5dade2;
                        selection-color: #ffffff;
                        outline: none;     /* Completely removes the thin black focus line */
                        padding: 0px;      /* Removes the gap inside the box */
                        margin: 0px;       /* Removes the gap outside the box */
                    }

                    /* Add some spacing to the items inside the list */
                    QComboBox QAbstractItemView::item {
                        min-height: 28px;
                        padding-left: 8px; /* Restores the text padding nicely */
                        border: none;
                    }
                """)
        self.scalar_selector.addItem("Solid Color (No Data)")
        self.scalar_selector.currentIndexChanged.connect(self.update_scalars)
        self.controls_layout.addWidget(self.scalar_selector)

        # Checkbox to toggle edges
        self.edge_checkbox = QCheckBox("Show Mesh Lines")
        self.edge_checkbox.setChecked(False)  # Set to False by default
        # Pixel-based font: the app default font scales with the X screen DPI
        # and renders ~2x on high-DPI screens, larger than the rest of the panel.
        self.edge_checkbox.setStyleSheet("margin-left: 15px; font-weight: bold; color: #333; font-size: 13px;")
        self.edge_checkbox.stateChanged.connect(self.refresh_current_view)
        self.controls_layout.addWidget(self.edge_checkbox)

        # Radio Buttons for Mesh Type
        self.radio_group = QButtonGroup(self)
        self.radio_head = QRadioButton("Mesh Head")
        self.radio_roi = QRadioButton("Mesh ROI")
        self.radio_head.setChecked(True)
        # Pixel-based fonts (see edge_checkbox above)
        self.radio_head.setStyleSheet("margin-left: 15px; font-weight: bold; color: #333; font-size: 13px;")
        self.radio_roi.setStyleSheet("margin-left: 10px; font-weight: bold; color: #333; font-size: 13px;")

        self.radio_group.addButton(self.radio_head)
        self.radio_group.addButton(self.radio_roi)

        self.controls_layout.addWidget(self.radio_head)
        self.controls_layout.addWidget(self.radio_roi)

        self.radio_head.toggled.connect(self.toggle_mesh_view)
        self.radio_roi.toggled.connect(self.toggle_mesh_view)

        self.controls_layout.addStretch()

        self.controls_layout.addStretch()
        self.layout.addWidget(self.controls_frame)

        # --- 3. The 3D Plotter ---
        self.plotter = QtInteractor(self)
        self.layout.addWidget(self.plotter)

        # <--- ADD THIS: PERFORMANCE SETTINGS --->
        # <--- start --->
        # This allows the resolution to drop slightly ONLY while you rotate
        # self.plotter.ren_win.SetDesiredUpdateRate(5.0)

        # This uses a faster lighting system
        # self.plotter.enable_lightkit()
        # <--- END --->

        self.plotter.set_background("white")
        self.plotter.add_axes()
        self.plotter.view_isometric()

        self.current_mesh = None
        self.mesh_head = None
        self.mesh_roi = None
        self._cell_markers_info = []  # list of (cell_idx, color, label) tuples

    def mark_cells(self, cell_indices, colors, labels=None):
        """Add callout arrows pointing at cells + connecting line between first two."""
        self._cell_markers_info = list(zip(cell_indices, colors, labels or [''] * len(cell_indices)))
        self._render_cell_markers()

    def _render_cell_markers(self):
        """Render stored cell markers on the plotter."""
        # Remove old markers by name
        for name in ["cell_arrow_true", "cell_arrow_best", "cell_connect_line"]:
            self.plotter.remove_actor(name)

        if self.current_mesh is None or not self._cell_markers_info:
            self.plotter.render()
            return

        centers = self.current_mesh.cell_centers().points
        normals = self.current_mesh.face_normals
        bounds = self.current_mesh.bounds
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        offset = span * 0.055

        arrow_names = ["cell_arrow_true", "cell_arrow_best"]
        for i, (cell_idx, color, label) in enumerate(self._cell_markers_info):
            center = centers[cell_idx]
            normal = normals[cell_idx]
            arrow_start = center + normal * offset
            direction = -normal

            arrow = pv.Arrow(start=arrow_start, direction=direction, scale=3,
                             tip_length=0.43, tip_radius=0.23, shaft_radius=0.08)
            name = arrow_names[i] if i < len(arrow_names) else f"cell_arrow_{i}"
            self.plotter.add_mesh(arrow, color=color, name=name)

        # Draw geodesic path between first two cells (follows mesh surface)
        if len(self._cell_markers_info) >= 2:
            c1 = centers[self._cell_markers_info[0][0]]
            c2 = centers[self._cell_markers_info[1][0]]
            v1 = self.current_mesh.find_closest_point(c1)
            v2 = self.current_mesh.find_closest_point(c2)
            path = self.current_mesh.geodesic(v1, v2)
            self.plotter.add_mesh(path, color='yellow', line_width=7, name="cell_connect_line")

        self.plotter.render()

    def toggle_mesh_view(self):
        """Switches the current mesh between Head and ROI based on radio button selection."""
        # 1. Save the current selection state before switching
        previous_data_key = self.scalar_selector.currentData()
        previous_text = self.scalar_selector.currentText()

        # 2. Switch the active mesh
        if self.radio_head.isChecked():
            self.current_mesh = self.mesh_head
        elif self.radio_roi.isChecked():
            self.current_mesh = self.mesh_roi

        # 3. Refresh dropdown contents for the new mesh
        self.refresh_dropdown()

        # 4. Attempt to restore the previous selection
        if previous_text:
            index_by_text = self.scalar_selector.findText(previous_text)
            if index_by_text >= 0:
                self.scalar_selector.setCurrentIndex(index_by_text)
            else:
                # If the exact array isn't found, check if "Solid Color" exists as fallback
                fallback_index = self.scalar_selector.findText("Solid Color (No Data)")
                if fallback_index >= 0:
                    self.scalar_selector.setCurrentIndex(fallback_index)

        # 5. Redraw the scene based on the (restored) selection
        self.update_scalars(self.scalar_selector.currentIndex())

    # A helper function to toggle the visibility of the edges
    def refresh_current_view(self):
        """Forces the plotter to redraw with the new edge settings."""
        if self.current_mesh is not None:
            # Simply re-trigger the current scalar selection to redraw
            self.update_scalars(self.scalar_selector.currentIndex())

    def apply_scores(self, scores_dict):
        """
        Adds regression scores to the mesh and updates the dropdown.
        scores_dict: {'ADC 0': np.array, 'ADC 1': np.array}
        """
        if self.current_mesh is None:
            return

        try:

            # 1. Memorize exactly what the user is looking at right now
            #    (If "Solid Color", this will likely be None)
            previous_data_key = self.scalar_selector.currentData()
            previous_text = self.scalar_selector.currentText()

            # 2. Add every channel's score to the mesh data
            for channel_name, scores in scores_dict.items():

                # Check dimensions (Cell Data vs Point Data)
                if len(scores) == self.current_mesh.n_cells:
                    # Naming convention: "Score ADC 0"
                    data_name = f"Score {channel_name}"
                    #--- BEGIN NORMALIZATION SCORE BLOCK
                    # NEW: Normalize scores to [0, 1]
                   # scores_min = scores.min()
                   # scores_max = scores.max()
                   # if scores_max > scores_min:
                    #    scores = (scores - scores_min) / (scores_max - scores_min)
                    #else:
                    #    scores = np.zeros_like(scores)  # All same → map to 0
                    # --- END NORMALIZATION SCORE BLOCK

                    self.current_mesh.cell_data[data_name] = scores

                elif len(scores) == self.current_mesh.n_points:
                    data_name = f"Score {channel_name}"
                    # --- BEGIN NORMALIZATION SCORE BLOCK
                    # NEW: Normalize scores to [0, 1]
                   # scores_min = scores.min()
                   # scores_max = scores.max()
                   # if scores_max > scores_min:
                     #   scores = (scores - scores_min) / (scores_max - scores_min)
                    #else:
                     #   scores = np.zeros_like(scores)  # All same → map to 0
                    # --- END NORMALIZATION SCORE BLOCK
                    self.current_mesh.point_data[data_name] = scores

                else:
                    print(f"Skipping {channel_name}: Data length {len(scores)} matches neither Cells nor Points.")

            # 3. Refresh the dropdown
            # (This scans the mesh again and will find the new 'Score ADC X' arrays)
            self.refresh_dropdown()

            # 4. RESTORE SELECTION
            # We look for the item that has the same data key as before.
            index = self.scalar_selector.findData(previous_data_key)

            if index >= 0:
                # Found it! Switch back to it immediately.
                self.scalar_selector.setCurrentIndex(index)
            else:
                # If we couldn't match the data key (maybe it was Solid Color with no data),
                # try to match the text label (e.g. "Solid Color (No Data)")
                index_by_text = self.scalar_selector.findText(previous_text)
                if index_by_text >= 0:
                    self.scalar_selector.setCurrentIndex(index_by_text)

            # Note: We do NOT force an update to a new channel here.
            # If the user was watching "Score ADC 1", they stay on "Score ADC 1".
            # If they were watching "Solid Color", they stay on "Solid Color".

            # Force the 3D window to redraw just in case the numbers changed
            # for the *current* view (e.g. Analysis updated the heatmap you are currently watching)
            self.plotter.render()

        except Exception as e:
            print(f"Error applying scores: {e}")

    def load_hdf5_mesh(self, file_path, mesh_type="head"):
        """
        Loads mesh data and creates a PyVista PolyData object.
        mesh_type can be "head" or "roi".

        Supported formats:
        - SimNIBS ``*.msh`` (read via simnibs mesh_io; the head mesh in the
          m2m folder) — triangles and their tissue tags
        - ``*.hdf5`` meshes with ``/mesh/nodes/node_coord`` and
          ``/mesh/elm/triangle_number_list`` (ROI geo files)
        """
        # 1. Guard Clause: Handle the empty state
        if not file_path:
            print(f"3D Viewer: Empty path received for {mesh_type}. Wiping corresponding mesh.")
            if mesh_type == "head":
                self.mesh_head = None
            elif mesh_type == "roi":
                self.mesh_roi = None

            self.toggle_mesh_view()
            return

        # 2. Proceed with loading the actual file
        try:
            if str(file_path).lower().endswith(".msh"):
                loaded_mesh = self._load_simnibs_msh(file_path)
                if loaded_mesh is None:
                    return
                nodes, tr_con, tri_tissue_type = loaded_mesh
            else:
                with h5py.File(file_path, 'r') as f:
                    # Expected shape: (N, 3)
                    nodes = f['mesh/nodes/node_coord'][:]
                    # Expected shape: (M, 3)
                    tr_con = f['/mesh/elm/triangle_number_list'][:]
                    # Optional: one value per triangle
                    tri_tissue_type = (f['/mesh/elm/tri_tissue_type'][:]
                                       if '/mesh/elm/tri_tissue_type' in f else None)

            # --- CONVERT TO PYVISTA (The efficient way) ---

            # VTK requires the faces array to be flat and prefixed with the number of points per face.
            # For triangles, it must look like: [3, p0, p1, p2, 3, p3, p4, p5, ...]

            # Create a column of 3s (because they are triangles)
            n_faces = tr_con.shape[0]
            padding = np.full((n_faces, 1), 3)

            # Stack [3, p1, p2, p3] horizontally
            faces_concatenated = np.hstack((padding, tr_con))

            # Flatten to 1D array for VTK
            faces_flat = faces_concatenated.flatten().astype(int)

            # Create the PyVista PolyData object
            loaded_mesh = pv.PolyData(nodes, faces_flat)

            # --- ADD DATA (Tissue Type) ---
            if tri_tissue_type is not None:
                n_data = len(tri_tissue_type)
                n_points = loaded_mesh.n_points
                n_cells = loaded_mesh.n_cells

                print(f"Data mapping: {n_data} values -> {n_points} Points / {n_cells} Cells")

                if n_data == n_points:
                    print("-> MATCH: Assigning data to POINTS (Vertices)")
                    loaded_mesh.point_data["Tissue Type"] = tri_tissue_type
                elif n_data == n_cells:
                    print("-> MATCH: Assigning data to CELLS (Triangles)")
                    loaded_mesh.cell_data["Tissue Type"] = tri_tissue_type
                else:
                    print(f"[WARNING] Data length ({n_data}) matches neither Points nor Cells.")

            # Assign to the corresponding mesh property
            if mesh_type == "head":
                self.mesh_head = loaded_mesh
                self.radio_head.setChecked(True)
            elif mesh_type == "roi":
                self.mesh_roi = loaded_mesh
                self.radio_roi.setChecked(True)

            # Update the UI
            self.toggle_mesh_view()

            print(f"Successfully loaded HDF5 {mesh_type} Mesh: {n_faces} triangles.")

        except Exception as e:
            print(f"Error loading HDF5 mesh: {e}")
            import traceback
            traceback.print_exc()

    def _load_simnibs_msh(self, file_path):
        """Read a SimNIBS ``*.msh`` mesh: returns ``(nodes, triangles,
        tissue_tags)`` or ``None`` on failure. The tags (1001..1005 for the
        five SimNIBS tissues) are remapped to 1..5 so both mesh sources
        color consistently, and the 1-based node numbers are converted to
        0-based for VTK."""
        try:
            # Imported lazily: simnibs is slow to import and only needed
            # for .msh files (the ROI geo meshes come as HDF5).
            from simnibs import mesh_io
            m = mesh_io.read_msh(file_path)
            tri_mask = m.elm.elm_type == 2  # surface triangles (tets are 4)
            nodes = m.nodes.node_coord[:, :3]
            tr_con = m.elm.node_number_list[tri_mask][:, :3].astype(int) - 1
            tri_tissue_type = m.elm.tag1[tri_mask].astype(int) % 1000  # 1001..1005 -> 1..5
            return nodes, tr_con, tri_tissue_type
        except Exception as e:
            print(f"Error reading SimNIBS mesh {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def refresh_dropdown(self):
        """Populates the dropdown with available data arrays found in the mesh."""
        self.scalar_selector.blockSignals(True)
        self.scalar_selector.clear()
        self.scalar_selector.addItem("Solid Color (No Data)")

        if self.current_mesh:
            items_to_add = []
            # 1. Check Point Data
            for name in self.current_mesh.point_data.keys():
                # self.scalar_selector.addItem(f"[Point] {name}", name)   #delete this if the they will get stored on thursday
                items_to_add.append((name, f"[Point] {name}"))

            # 2. Check Cell Data (This is where 'Tissue Type' will appear)
            for name in self.current_mesh.cell_data.keys():
                # self.scalar_selector.addItem(f"[Cell] {name}", name)     #delete this if the they will get stored on thursday
                items_to_add.append((name, f"[Cell] {name}"))

            # 3. Sort the combined list alphabetically
            items_to_add.sort(key=lambda x: x[0].lower())

            # 4. Populate the dropdown
            for raw_name, display_text in items_to_add:
                self.scalar_selector.addItem(display_text, raw_name)

        self.scalar_selector.blockSignals(False)

    def _set_home_camera(self):
        """Initial perspective: camera on the subject's upper left, slightly
        posterior — the nose points left and the vertex is up. Distance is
        set relative to the mesh diagonal so both the head and the (much
        smaller) ROI frame nicely."""
        if self.current_mesh is None:
            return
        center = np.array(self.current_mesh.center)
        bounds = np.array(self.current_mesh.bounds)
        length = np.linalg.norm(bounds[1::2] - bounds[::2])
        direction = HOME_VIEW_DIRECTION / np.linalg.norm(HOME_VIEW_DIRECTION)
        self.plotter.camera_position = [center + direction * length * 1.9,
                                        center, (0, 0, 1)]

    def update_scene_default(self):
        """Renders the mesh for the first time after loading."""
        self.plotter.clear()
        self.plotter.add_axes()

        # Check if we have data to show automatically
        if not self.current_mesh:
            self.plotter.reset_camera()
            return

        show_lines = self.edge_checkbox.isChecked()  # a variable to toggle the visibility of the edges

        if self.current_mesh and self.current_mesh.cell_data:
            # Select the first available data
            first_key = list(self.current_mesh.cell_data.keys())[0]
            self.scalar_selector.setCurrentIndex(1)  # Point to the data item
            self.plotter.add_mesh(self.current_mesh, scalars=first_key, cmap="turbo", show_edges=show_lines,
                                  edge_color="black", clim=[0.0, 1.0])  # ---> ADDED clim=[0.0, 1.0] <---
            self.plotter.add_scalar_bar(title=first_key)
        else:
            self.plotter.add_mesh(self.current_mesh, color='#d9e6f2', show_edges=True)

        self._set_home_camera()

    def update_scalars(self, index):
        """Called when user changes dropdown."""
        self.plotter.clear()
        self.plotter.add_axes()
        if self.current_mesh is None:
            self._render_cell_markers()
            self.plotter.render()
            return

        array_name = self.scalar_selector.currentData()
        #self.plotter.clear()
        #self.plotter.add_axes()

        if array_name is None:
            # "Solid Color" mode: force checkbox to be checked and disable it
            self.edge_checkbox.blockSignals(True)
            self.edge_checkbox.setChecked(True)
            self.edge_checkbox.setEnabled(False)
            self.edge_checkbox.blockSignals(False)

            self.plotter.add_mesh(self.current_mesh, color='#d9e6f2', show_edges=True)
        else:
            # Data mode: allow user to toggle edges freely
            self.edge_checkbox.setEnabled(True)
            show_lines = self.edge_checkbox.isChecked()  # a variable to toggle the visibility of the edges
            self.plotter.add_mesh(self.current_mesh, scalars=array_name, cmap="turbo", show_edges=show_lines,
                                  edge_color="black", clim=[0.0, 1.0])  # ---> ADDED clim=[0.0, 1.0] <---
            self.plotter.add_scalar_bar(title=array_name)

        self._set_home_camera()
        self._render_cell_markers()
        self.plotter.render()