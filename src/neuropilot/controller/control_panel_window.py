import sys
import asyncio
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QDoubleSpinBox, QHBoxLayout
from qasync import QEventLoop, asyncSlot
from PyQt5.QtCore import Qt, QTimer
from functools import partial
from .systems.system import SystemStatus
import time

class ControlPanelWindow(QWidget):
    def initialize(self, all_error_recoveries):
        self.setWindowTitle("NeuroPilot Control Panel")
        self.resize(1000, 200)
        self.controller = None
        #self.setStyleSheet("background-color: white; color: black;")

        main_layout = QVBoxLayout()

        # Title
        header = QLabel("Pipeline Control Panel")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 24px; font-weight: bold;")
        main_layout.addWidget(header, stretch=0)

        # Sub-systems
        system_panel_layout = QHBoxLayout()
        self.system_panels = {}
        for system, err_rec in all_error_recoveries.items():
            system_panel = self.SystemWidget(system, err_rec)
            self.system_panels[system] = system_panel
            system_panel_frame = QFrame()
            system_panel_frame.setLayout(QVBoxLayout())
            system_panel_frame.layout().addWidget(system_panel)
            system_panel_frame.setFrameShape(QFrame.StyledPanel)
            system_panel_layout.addWidget(system_panel_frame)

        # skip button
        self.skip_button = QPushButton("Skip Step")
        self.skip_button.clicked.connect(self.on_skip_step_clicked)
        main_layout.addWidget(self.skip_button)

        self.zapid = QLabel("Not Initialized")
        main_layout.addWidget(self.zapid)

        # spin boxes
        self.spinbox_layout = QHBoxLayout()
        self.spinbox1_label = QLabel("Stiffness")
        self.spinbox1_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spinbox1 = QDoubleSpinBox()
        self.spinbox1.setRange(0.0, 1.0)
        self.spinbox1.setSingleStep(0.01)
        self.spinbox1.setDecimals(2)
        self.spinbox1.setValue(0.05)
        self.spinbox1.valueChanged.connect(self.on_pid_changed)

        self.spinbox2_label = QLabel("Damping:")
        self.spinbox2_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spinbox2 = QDoubleSpinBox()
        self.spinbox2.setRange(0.0, 1.0)
        self.spinbox2.setSingleStep(0.01)
        self.spinbox2.setDecimals(2)
        self.spinbox2.setValue(0.02)
        self.spinbox2.valueChanged.connect(self.on_pid_changed)

        self.spinbox3_label = QLabel("Proportional:")
        self.spinbox3_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spinbox3 = QDoubleSpinBox()
        self.spinbox3.setRange(0.0, 1.0)
        self.spinbox3.setSingleStep(0.01)
        self.spinbox3.setDecimals(2)
        self.spinbox3.setValue(0.3)
        self.spinbox3.valueChanged.connect(self.on_pid_changed)

        self.spinbox4_label = QLabel("Integral:")
        self.spinbox4_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spinbox4 = QDoubleSpinBox()
        self.spinbox4.setRange(0.01, 1.0)
        self.spinbox4.setSingleStep(0.01)
        self.spinbox4.setDecimals(2)
        self.spinbox4.setValue(0.01)
        self.spinbox4.valueChanged.connect(self.on_pid_changed)

        self.spinbox5_label = QLabel("Derivative:")
        self.spinbox5_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spinbox5 = QDoubleSpinBox()
        self.spinbox5.setRange(0.0, 1.0)
        self.spinbox5.setSingleStep(0.01)
        self.spinbox5.setDecimals(2)
        self.spinbox5.setValue(0.00)  # derivative default (was spinbox1 -- copy-paste bug)
        self.spinbox5.valueChanged.connect(self.on_pid_changed)


        self.spinbox_layout.addWidget(self.spinbox1_label)
        self.spinbox_layout.addWidget(self.spinbox1)
        self.spinbox_layout.addWidget(self.spinbox2_label)
        self.spinbox_layout.addWidget(self.spinbox2)
        self.spinbox_layout.addWidget(self.spinbox3_label)
        self.spinbox_layout.addWidget(self.spinbox3)
        self.spinbox_layout.addWidget(self.spinbox4_label)
        self.spinbox_layout.addWidget(self.spinbox4)
        self.spinbox_layout.addWidget(self.spinbox5_label)
        self.spinbox_layout.addWidget(self.spinbox5)
        main_layout.addLayout(self.spinbox_layout)

        main_layout.addLayout(system_panel_layout,stretch=1)
        self.setLayout(main_layout)

    # Handler stubs
    def on_pid_changed(self, value):
        print("Spinbox 1 value changed:", value)
        if self.controller:
            stiffness = self.spinbox1.value()
            damping = self.spinbox2.value()
            proportional = self.spinbox3.value()
            integral = self.spinbox4.value()
            derivative = self.spinbox5.value()
            self.controller.set_pid(stiffness, damping, proportional, integral, derivative)

    def update_system_status(self, system = None, status = None, message = None):
        self.system_panels[system].set_status(status, message)

    def set_controller(self, controller):
        self.controller = controller

    def on_skip_step_clicked(self):
        if self.controller:
            print("Skip Step")
            self.controller.switch_step("skip")

    class SystemWidget(QWidget):
        def __init__(self, system, error_recoveries):
            super().__init__()
            layout = QVBoxLayout()

            # Title
            self.title_label = QLabel(system.NAME)
            self.title_label.setAlignment(Qt.AlignCenter)
            self.title_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(self.title_label)

            # Status
            self.status_label = QLabel("Status: Not Initialized")
            self.status_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.status_label)
            
            # message
            self.message_label = QLabel("")
            self.message_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.message_label)
            

            # Buttons
            self.error_to_recovery_buttons = {}
            button_layout = QVBoxLayout()
            for err, rec in error_recoveries.items():
                # If Recovery method is set to None, then it means we cannot automate it by code, so we only want to display the message.
                if rec is None:
                    continue
                btn = QPushButton(rec)
                btn.clicked.connect(lambda _, r=rec: self.on_button_click(system,r))
                btn.setEnabled(False)
                self.error_to_recovery_buttons[err] = btn
                button_layout.addWidget(btn)
            layout.addLayout(button_layout)
            
            # Recovering Label
            self.recovering_label = QLabel("Recovering...")
            self.recovering_label.setAlignment(Qt.AlignCenter)
            self.recovering_label.setVisible(False)
            layout.addWidget(self.recovering_label)
            
            self.last_update_label = QLabel("Last update:")
            self.last_update_label.setAlignment(Qt.AlignCenter)
            self.last_update_label.setStyleSheet("font-style: italic; color: #B8B8B8")
            layout.addWidget(self.last_update_label)

            self.setLayout(layout)

        def set_status(self, status: str, message: str = None):
            # Disabling all buttons. A button should only be relevant if there is an ordinary error.
            for btn in self.error_to_recovery_buttons.values():
                btn.setEnabled(False)
            
            self.recovering_label.setVisible(False)
            
            if status == SystemStatus.OK:
                self.status_label.setStyleSheet("color: #0D9E42")
                self.status_label.setText("Status: OK")
                self.message_label.setText("")
            elif status == SystemStatus.ERROR:
                self.status_label.setStyleSheet("color: #B50E0E")
                self.status_label.setText(f"Status: ERROR")
                message_text = f"Message: {message}"
                if message in self.error_to_recovery_buttons.keys():
                    self.error_to_recovery_buttons[message].setEnabled(True)
                else:
                    message_text += "\nNo Recovery Implemented"
                self.message_label.setText(message_text)
            elif status == SystemStatus.NAN:
                self.status_label.setStyleSheet("color: #595959")
                self.status_label.setText("Status: Not Initialized")
                self.message_label.setText("")
            
            self.last_update_label.setText(f"Last update: {time.strftime('%H:%M:%S', time.localtime(time.time()))}")
        
        def set_recovery_success(self, success: bool):
            if success:
                self.recovering_label.setVisible(False)
            else:
                self.recovering_label.setText("Recovery Failed")

        def on_button_click(self, system, recovery):
            system.recover(recovery)
            self.recovering_label.setVisible(True)