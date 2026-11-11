from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QFrame,QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np

# Optional: Set a clean plotting style
plt.style.use('seaborn-v0_8-whitegrid')


class MplGraphWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- 1. Main Layout (Horizontal: Left Panel | Right Graph) ---
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # --- 2. Left Control Panel (Sidebar) ---
        self.control_panel = QFrame()
        # Wide enough for the scaled fonts (labels scale with the window);
        # fixed width so the graph keeps the remaining space.
        self.control_panel.setFixedWidth(230)
        self.control_panel.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa; /* Light Grey Background */
                border-right: 1px solid #dcdcdc;
            }
            QLabel {
                font-weight: bold;
                font-size: 11px;
                color: #555;
                margin-bottom: 8px;
            }
            QCheckBox {
                font-size: 12px;
                padding: 4px;
                spacing: 8px; /* Space between box and text */
            }
            
        """)

        self.sidebar_layout = QVBoxLayout(self.control_panel)
        self.sidebar_layout.setContentsMargins(10, 15, 5, 10)  # Top, Left, Right, Bottom
        self.sidebar_layout.setAlignment(Qt.AlignTop)  # Align items to the top

        # --- make title widget for each Diagramm ---
        # 1. Add a Widget Title at the top of the sidebar
        self.title_label = QLabel("GRAPH TITLE")
        self.title_label.setStyleSheet("""
                    color: #333;
                    font-size: 14px;
                    font-weight: bold;
                    
                    margin-bottom: 5px;
                """)
        self.sidebar_layout.addWidget(self.title_label)

        # Add a small line separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #dcdcdc; margin-bottom: 10px;")
        line.setFixedHeight(1)
        self.sidebar_layout.addWidget(line)
        # --- end of the title widget ---

        # Label Header
        self.sidebar_layout.addWidget(QLabel("CHANNELS"))

        # Define specific colors for each channel (Matplotlib standard colors)
        self.channel_colors = {
            "ADC 0": "#1f77b4",  # Blue
            "ADC 1": "#ff7f0e",  # Orange
            "ADC 2": "#2ca02c"  # Green
        }
        # Create Checkboxes
        self.checkboxes = {}
        self.lines = {}
        self.channel_names = ["ADC 0", "ADC 1", "ADC 2"]
        self.channel_keys = list(self.channel_names)

        for name in self.channel_names:
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setCursor(Qt.PointingHandCursor)

            # Set the TEXT color to match the graph line color
            hex_color = self.channel_colors.get(name, "#333")
            cb.setStyleSheet(f"color: {hex_color}; font-weight: 600;")

            #This wires the checkbox to the logic.
            cb.stateChanged.connect(self.update_visibility) # noqa    to make the warring goes away

            self.sidebar_layout.addWidget(cb)
            self.checkboxes[name] = cb

        # Add stretch to push everything up
        self.sidebar_layout.addStretch()

        # Add sidebar to main layout
        self.layout.addWidget(self.control_panel)

        # --- 3. Right Panel (Graph Canvas) ---
        self.figure = Figure(figsize=(5, 4), dpi=100)
        # Consistent, readable text sizes for axes/ticks/labels (matplotlib's
        # 9-10pt defaults are unreadably small next to the scaled UI fonts).
        self.figure.set_constrained_layout(False)
        self.figure.subplots_adjust(left=0.16, right=0.95, top=0.90, bottom=0.18)
        self.figure.texts  # (no-op) sizes applied per-axes below

        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.tick_params(labelsize=14)

        self.layout.addWidget(self.canvas)

    def set_title(self, title):
        """Allows the main window to set a custom title for this widget."""
        self.title_label.setText(title)

        # extra to make The x and y axis labels already be present when loading the GUI
        # 2. Define the axis mappings
        label_map = {
            "MEPs": {"x": "Coil Placement Index", "y": "MEP amplitude / [mV]","graph_title": "MEP Amplitudes"},
            "Last EMG": {"x": "Time (s)", "y": "Amplitude / [mV]","graph_title": "Raw EMG Signal"}
        }

        # 3. Check if the title exists in our map, and apply the labels
        if title in label_map:
            self.ax.set_title(label_map[title]["graph_title"], fontsize=18, weight='bold')
            self.ax.set_xlabel(label_map[title]["x"], fontsize=15)
            self.ax.set_ylabel(label_map[title]["y"], fontsize=15)

            # --- NEW LOGIC FOR THE MEP PLOT ON LOAD ---
            if title == "MEPs":
                # Force x-axis to only use integers
                self.ax.xaxis.set_major_locator(MaxNLocator(integer=True))
                # Force the x-axis to start at 1 (and give it a dummy right edge like 6)
                self.ax.set_xlim(left=1, right=6)

            # Turn on the grid so it looks ready
           # self.ax.grid(True, linestyle=':', alpha=0.6)

            # Force the canvas to visually update
            self.canvas.draw()
        else:
            print(f"[WARN] No axis labels defined in MplGraphWidget for title: {title}")


    def update_visibility(self):
        """Called when ANY checkbox is clicked."""
        for name, line in self.lines.items():
            if name in self.checkboxes:
                is_checked = self.checkboxes[name].isChecked()
                line.set_visible(is_checked)
        self.canvas.draw()

    # Colors assigned to channels beyond the defaults (matplotlib tab10).
    CHANNEL_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                       "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

    def set_channels(self, names):
        """Configure the channels for display: `names` are the display names
        (from EMG_CHANNELS in .env); the data layer keys stay 'ADC 0..N-1'.
        Rebuilds the sidebar checkboxes (labelled with the display names)
        and recolors the plots."""
        names = list(names)
        data_keys = [f"ADC {i}" for i in range(len(names))]
        if names == self.channel_names:
            return
        self.channel_names = names
        self.channel_keys = data_keys
        self.channel_colors = {key: self.CHANNEL_PALETTE[i % len(self.CHANNEL_PALETTE)]
                               for i, key in enumerate(data_keys)}

        # Rebuild the sidebar checkboxes (the fixed items above them —
        # title, separator, "CHANNELS" label — stay in place). setParent(None)
        # detaches them immediately so pending scaling passes no longer see
        # them; deleteLater then frees them.
        for cb in list(self.checkboxes.values()):
            try:
                cb.stateChanged.disconnect()
            except TypeError:
                pass
            self.sidebar_layout.removeWidget(cb)
            cb.setParent(None)
            cb.deleteLater()
        self.checkboxes = {}
        self.lines = {}
        base_index = 3
        for i, (key, name) in enumerate(zip(data_keys, names)):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setCursor(Qt.PointingHandCursor)
            hex_color = self.channel_colors.get(key, "#333")
            cb.setStyleSheet(f"color: {hex_color}; font-weight: 600;")
            cb.stateChanged.connect(self.update_visibility)
            self.sidebar_layout.insertWidget(base_index + i, cb)
            self.checkboxes[key] = cb
        self.ax.cla()
        self.canvas.draw()

    def update_as_signal(self, time_array, data_dict):
        """Plot EMG timeseries"""
        self.ax.cla()
        self.lines = {}

        for name, data in data_dict.items():
            if name in self.channel_keys:
                # Use the consistent color defined in __init__
                c = self.channel_colors.get(name, 'black')
                line, = self.ax.plot(time_array, data, label=name, color=c, linewidth=1.2, alpha=0.9)
                self.lines[name] = line

        self.ax.set_title("Raw EMG Signal", fontsize=18, weight='bold')
        self.ax.set_xlabel("Time (s)", fontsize=15)
        self.ax.grid(True, linestyle=':', alpha=0.6)

        # Remove legend because the sidebar acts as the legend
        # self.ax.legend(...)

        self.update_visibility()

    def update_as_trend(self, target_indices, history_dict, exclusion=None):
        """Plot MEP amplitudes"""
        self.ax.cla()
        self.lines = {}
        print(f"in update_as_trend: {history_dict}")
        for name, values in history_dict.items():
            if name in self.channel_keys:
                current_x = np.array(target_indices[:len(values)])
                if exclusion is not None and len(exclusion) > 0:
                    print(f"exclusion: {exclusion}")
                    current_x = np.delete(current_x, np.array(list(exclusion)))
                    values = np.delete(values, np.array(list(exclusion)))
                c = self.channel_colors.get(name, 'black')

                line, = self.ax.plot(current_x+1, values, 'o-', label=name, color=c, markersize=7, linewidth=1.8)
                self.lines[name] = line

        self.ax.set_title("MEP Amplitudes", fontsize=18, weight='bold')
        self.ax.set_xlabel("Coil Placement Index", fontsize=15)
        self.ax.set_ylabel("MEP amplitude / [mV]", fontsize=15)
        self.ax.grid(True, linestyle=':', alpha=0.6)


        # Force integers again after clearing the axis
        self.ax.xaxis.set_major_locator(MaxNLocator(integer=True))

        # Ensure it never scales below 1 on the left side
        current_left, current_right = self.ax.get_xlim()
        self.ax.set_xlim(left=0, right=max(6, int(current_right)))

        self.update_visibility()


class EmgNavGraphWidget(MplGraphWidget):
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    inclusion_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. Create a container for the bottom navigation
        self.bottom_bar = QFrame()
        self.bottom_bar.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border-top: 1px solid #dcdcdc;
            }
            /* Basic style for QPushButton */
            QPushButton {
                background-color: #D97706; /* Workstation accent */
                color: white; /* White text */
                border: 1px solid #D97706;
                border-radius: 12px; /* Rounded corners */
                padding: 5px 20px; /* Vertical and horizontal padding */
                font-size: 14px; /* Font size */
                font-weight: bold; /* Bold text */
                text-align: center;
                outline: none; /* Remove the focus outline */
                /* No fixed width: the buttons must grow with the scaled
                   font or the text clips ("Previous E...", "ext EMG"). */

            }
            
            /* Hover effect for QPushButton */
            QPushButton:hover {
                background-color: #B45309;
                border-color: #B45309;
            
            }
            
            /* Pressed (active) effect for QPushButton */
            QPushButton:pressed {
                background-color: #92400E;
                border-color: #92400E;
            
            }
            
            /* Focus effect (when button is focused) */
            QPushButton:focus {
                outline: none; /* Remove the default focus outline */
            }
            
            /* Disabled button style */
            QPushButton:disabled {
                background-color: #F1F3F5; /* Disabled surface */
                color: #4A6B88; /* Medium blue-grey, consistent with the main stylesheets */
                border: 1px solid #E7EAEE;
            
            }
            QCheckBox {
                font-size: 12px;
                padding: 4px;
                spacing: 8px; /* Space between box and text */
                margin-left: 15px; font-weight: bold; color: #333;
            }

        """)

        # Horizontal layout for the bottom bar
        self.nav_layout = QHBoxLayout(self.bottom_bar)
        self.nav_layout.setContentsMargins(0, 20, 0, 0)

        # Add elements to the bottom bar
        self.chk_include = QCheckBox("Include in Mapping")
        self.chk_include.setChecked(True)

        self.btn_prev = QPushButton("< Previous EMG")
        self.btn_next = QPushButton("Next EMG >")

        # Elastic layout: stretches absorb the extra room so the buttons
        # always get their size hint (fixed spacings squeezed them below
        # the hint and clipped the text at scaled font sizes).
        self.nav_layout.addWidget(self.chk_include)
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addSpacing(40)
        self.nav_layout.addWidget(self.btn_next)
        self.nav_layout.addStretch()

        # 2. Re-arrange the main layout
        # Currently, self.layout is a QHBoxLayout [Sidebar | Canvas]
        # We need to wrap the Canvas and Bottom Bar in a Vertical Layout

        # First, remove the canvas from the main horizontal layout
        self.layout.removeWidget(self.canvas)

        # Create a new vertical container for the right side
        self.right_container = QWidget()
        self.right_vbox = QVBoxLayout(self.right_container)
        self.right_vbox.setContentsMargins(0, 0, 0, 0)
        self.right_vbox.setSpacing(0)

        # Add Canvas (Top) and Bottom Bar (Bottom)
        self.right_vbox.addWidget(self.canvas, stretch=1)
        self.right_vbox.addWidget(self.bottom_bar)

        # Add the whole right container back to the main horizontal layout
        self.layout.addWidget(self.right_container)

        # 3. Connections
        self.btn_prev.clicked.connect(self.prev_clicked.emit)
        self.btn_next.clicked.connect(self.next_clicked.emit)
        self.chk_include.toggled.connect(self.inclusion_toggled.emit)

class EmgNavGraphWidget1(MplGraphWidget):
    # Signals for the MainWindow to listen to
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    inclusion_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. Create the extra navigation UI
        self.nav_frame = QFrame()
        self.nav_layout = QVBoxLayout(self.nav_frame)
        self.nav_layout.setContentsMargins(0, 5, 0, 5)

        self.chk_include = QCheckBox("Include in Mapping")
        self.chk_include.setChecked(True)
        self.chk_include.setCursor(Qt.PointingHandCursor)

        btn_row = QHBoxLayout()
        self.btn_prev = QPushButton("< Prev")
        self.btn_next = QPushButton("Next >")
        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_next)

        self.nav_layout.addWidget(self.chk_include)
        self.nav_layout.addLayout(btn_row)

        # 2. Insert it into the existing sidebar_layout
        # (Before the stretch you added in the base class)
        self.sidebar_layout.insertWidget(self.sidebar_layout.count() - 1, self.nav_frame)

        # 3. Connect internal clicks to our custom signals
        self.btn_prev.clicked.connect(self.prev_clicked.emit)
        self.btn_next.clicked.connect(self.next_clicked.emit)
        self.chk_include.toggled.connect(self.inclusion_toggled.emit)