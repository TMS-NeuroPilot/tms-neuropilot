# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 16:20:22 2026

@author: abdul
"""

# -*- coding: utf-8 -*-
"""
Created on Tue Apr  7 14:05:32 2026

@author: abdul
"""

import sys
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QGridLayout,
                             QLabel, QPushButton, QSizePolicy)
from PyQt5.QtCore import Qt


class ModeSelectionDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.mode = "simulation"  # Default state: "simulation" | "real" | "manual"
        self.init_ui()

    def init_ui(self):
        # 1. Window Setup
        self.setWindowTitle("TMS NeuroPilot")
        # to remove the '?' button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(760, 350)
        # Set a clean white background for the dialog
        self.setStyleSheet("QDialog { background-color: #ffffff; }")

        # 2. Main Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(48, 36, 48, 36)
        layout.setSpacing(24)

        # 3. Typography
        title = QLabel("Select mode:")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 26px;
            font-weight: bold;
            color: #2c3e50;
            font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        """)

        # 4. Buttons Layout
        btn_layout = QGridLayout()
        btn_layout.setSpacing(18)

        self.btn_sim = QPushButton("Stimulation")
        self.btn_real = QPushButton("Robotic TMS")
        self.btn_manual = QPushButton("Manual TMS")
        self.btn_training = QPushButton("Training")

        # Base button style with smooth transitions
        base_btn_style = """
            QPushButton {
                color: white;
                border: none;
                outline: none; /* Kills the native Linux focus glow */
                border-radius: 10px;
                padding: 16px 24px;
                font-size: 22px;
                font-weight: 600;
                font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
            }
        """
        for button in (self.btn_sim, self.btn_real,
                       self.btn_manual, self.btn_training):
            button.setMinimumHeight(76)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Stimulation Button Style (Blue theme)
        self.btn_sim.setStyleSheet(base_btn_style + """
            QPushButton { background-color: #3498db; }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:pressed { background-color: #1c5980; }
        """)

        # Robotic TMS Button Style (Green theme)
        self.btn_real.setStyleSheet(base_btn_style + """
            QPushButton { background-color: #2ecc71; }
            QPushButton:hover { background-color: #27ae60; }
            QPushButton:pressed { background-color: #1e8449; }
            QPushButton:focus { background-color: #2ecc71; } /* Matches base color so it doesn't shift */
        """)

        # Manual TMS Button Style (Orange theme)
        self.btn_manual.setStyleSheet(base_btn_style + """
            QPushButton { background-color: #e67e22; }
            QPushButton:hover { background-color: #d35400; }
            QPushButton:pressed { background-color: #a04000; }
            QPushButton:focus { background-color: #e67e22; }
        """)

        # Training Button Style (Purple theme)
        self.btn_training.setStyleSheet(base_btn_style + """
            QPushButton { background-color: #8e44ad; }
            QPushButton:hover { background-color: #732d91; }
            QPushButton:pressed { background-color: #5e2277; }
            QPushButton:focus { background-color: #8e44ad; }
        """)

        # 5. Connections
        self.btn_sim.clicked.connect(self.select_simulation)
        self.btn_real.clicked.connect(self.select_real)
        self.btn_manual.clicked.connect(self.select_manual)
        self.btn_training.clicked.connect(self.select_training)

        # 6. Assemble
        btn_layout.addWidget(self.btn_sim, 0, 0)
        btn_layout.addWidget(self.btn_real, 0, 1)
        btn_layout.addWidget(self.btn_manual, 1, 0)
        btn_layout.addWidget(self.btn_training, 1, 1)

        layout.addWidget(title)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def select_simulation(self):
        self.mode = "simulation"
        self.accept()  # Closes the dialog and returns QDialog.Accepted

    def select_real(self):
        self.mode = "real"
        self.accept()

    def select_manual(self):
        self.mode = "manual"
        self.accept()

    def select_training(self):
        self.mode = "training"
        self.accept()

    @property
    def is_simulation(self):
        return self.mode == "simulation"

    @property
    def is_manual(self):
        return self.mode == "manual"

    @property
    def is_training(self):
        return self.mode == "training"


# --- Main Application Logic ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Create and show our custom dialog
    dialog = ModeSelectionDialog()

    # exec_() blocks until the user clicks a button
    if dialog.exec_() == QDialog.Accepted:
        is_simulation = dialog.is_simulation
        print(f"Is Simulation: {is_simulation}")

    else:
        print("User closed the dialog without selecting.")