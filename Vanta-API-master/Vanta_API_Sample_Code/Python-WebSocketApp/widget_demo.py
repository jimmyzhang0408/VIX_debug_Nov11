# widget_demo.py
# Example code showing how to use the Vanta_API_Widget which is a QT widget that can be dropped into a UI.
# The widget handles all the work needed to connect to a Vanta API client as a listener and can display messages
# and spectra.  The graphical functionality can be extended based on what we hear from users.
import datetime
import os
import tempfile
import sys
import math
import json
import platform
import ctypes

from Vanta_API_Widget import VantaWidget
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *


def save_json(filename, path, folder, data, fmt=False):
    file_name = filename
    if len(path) > 0:
        try:
            os.stat(path)
        except OSError:
            os.mkdir(path)
        full_path = os.path.join(path, folder)
    else:
        full_path = os.path.join(tempfile.gettempdir(), folder)
    try:
        os.stat(full_path)
    except OSError:
        os.mkdir(full_path)

    full_path = os.path.join(full_path, file_name)
    with open(full_path, 'w') as file:  # dump the data into a file for future access.
        if fmt:
            json.dump(data, file, indent=1, sort_keys=False)
        else:
            json.dump(data, file, indent=0, sort_keys=False)


class AppForm(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)

        QMainWindow.__init__(self, parent)
        self.setWindowTitle('Vanta Widgets')

        self.go_button = QPushButton()
        self.remove_button = QPushButton()
        self.add_button = QPushButton()
        self.login_button = QPushButton()
        self.main_frame = QWidget(parent)

        # Create some instances of the VantaWidget. This can be done using host names or IP Addresses.
        # If the unit is connected via USB it can be connected as "192.168.7.2"
        self.vantas = []

        # Here we are using a configuration file to load a list of vantas.
        with open('vanta_list.json', 'r') as vanta_list_file:
            vanta_list = json.load(vanta_list_file)

        for h in vanta_list['hosts']:
            try:
                controller = h['controller']
            except KeyError:
                controller = False
            try:
                method = h['method']
            except KeyError:
                method = "Alloy"

            try:
                name = h['Name']
            except KeyError:
                name = "vanta"

            v = VantaWidget(h['host'], controller, method, name)
            self.vantas.append(v)

        # Create the main windows. Any widgets created above will be added to this view.
        self.create_main_frame()

        # Connect a handler to the messages coming from a given widget.
        # We can use the same handler because the data contains a GUID corresponding to the Vanta that generated it.
        for v in self.vantas:
            v.widget_message_data.connect(self.on_vanta_messages)
        #   v.widget_spectrum_data.connect(self.on_vanta_spectrum)

        self.started_timestamp = datetime.datetime.utcnow()

    def on_login_button(self):
        for v in self.vantas:
            command = dict()
            command['commandId'] = 301
            command['id'] = 0
            params = dict()
            params["userId"] = str("Administrator")
            params["password"] = str("0000")
            command['params'] = params
            v.send_command(command)

        for v in self.vantas:
            command = dict()
            command["commandId"] = 703
            command["id"] = 0
            command["params"] = {"methodId": v.method}
            v.send_command(command)

    def all_units_done(self):

        start_times = []
        end_times = []
        run_times = []      # run times in seconds.


        start_ticks = []
        end_ticks = []
        run_ticks = []
        last_spectrum_delays = []

        start_packet_delays = []
        end_packet_delays = []

        for v in self.vantas:
            v.vanta.final_result = False
            end_time = v.vanta.final_result_timestamp

            end_times.append(end_time)
            end_tick = v.vanta.final_tick_count
            end_ticks.append(end_tick)

            start_time = v.vanta.started_timestamp
            start_times.append(start_time)
            start_tick = v.vanta.started_tick_count
            start_ticks.append(start_tick)

            run_time = end_time - start_time
            run_times.append((run_time.seconds * 1e6 + run_time.microseconds)/1e6)
            run_ticks.append((end_tick-start_tick)/1e3)

            ticks_from_start_time = round((start_time-datetime.datetime(1970, 1, 1)).total_seconds()*1000)
            start_delay = ticks_from_start_time-start_tick
            start_packet_delays.append(start_delay)

            ticks_from_end_time = round((end_time-datetime.datetime(1970, 1, 1)).total_seconds()*1000)
            end_delay = ticks_from_end_time-end_tick
            end_packet_delays.append(end_delay)

            if v.vanta.got_final_spectrum:
                last_spectrum_tick = v.vanta.final_spectrum_tick_count
                last_spectrum_delays.append((end_tick - last_spectrum_tick )/1e3)
            else:
                last_spectrum_delays.append(-1.0)

            # print("start {}, end {}".format(start_delay,end_delay))

        time_range = max(run_times)-min(run_times)

        with open("latency_single.txt", 'a') as f:

            output_string = datetime.datetime.utcnow().isoformat()+" ,"
            for t in run_times:
                output_string = output_string + str("{:.3f},").format(t)

            for t in run_ticks:
                output_string = output_string + str("{:.3f},").format(t)

            for s in start_packet_delays:
                output_string = output_string + str("{:.3f},").format(s)

            for e in end_packet_delays:
                output_string = output_string + str("{:.3f},").format(e)

            for s in last_spectrum_delays:
                output_string = output_string + str("{:.3f},").format(s)

            output_string = output_string + str("{:.3f}").format(time_range)
            output_string = output_string + "\n"
            f.write(output_string)

        # send start to all units
        self.on_go_button()

    def on_go_button(self):
        for v in self.vantas:
            v.send_basic_command(601)   # 601 is start command

    def on_remove_button(self):
        v = self.vantas[0]
        self.vantas.remove(v)
        self.widget_grid.removeWidget(v)

    def on_add_button(self):
        v = VantaWidget('192.168.7.2', False, '', 'Test')
        self.vantas.append(v)
        self.widget_grid.addWidget(v)

    def create_main_frame(self):
        main_layout = QVBoxLayout()

        self.go_button.setText("Go")
        self.go_button.setMinimumSize(100, 30)
        self.go_button.setMaximumSize(100, 30)
        self.go_button.clicked.connect(self.on_go_button)

        self.login_button.setText("Login")
        self.login_button.setMinimumSize(100, 30)
        self.login_button.setMaximumSize(100, 30)
        self.login_button.clicked.connect(self.on_login_button)

        self.remove_button.setText("Remove")
        self.remove_button.setMinimumSize(100, 30)
        self.remove_button.setMaximumSize(100, 30)
        self.remove_button.clicked.connect(self.on_remove_button)

        self.add_button.setText("Add")
        self.add_button.setMinimumSize(100, 30)
        self.add_button.setMaximumSize(100, 30)
        self.add_button.clicked.connect(self.on_add_button)

        self.widget_grid = QGridLayout()
        self.widget_grid.setSpacing(5)
        position = 0
        GRID_COLS = 5
        for v in self.vantas:
            row = math.trunc(position / GRID_COLS)
            col = position % GRID_COLS
            self.widget_grid.addWidget(v, row, col)
            position = position + 1

        main_layout.addLayout(self.widget_grid)
        main_layout.addWidget(self.login_button, alignment=Qt.AlignLeft)
        main_layout.addWidget(self.go_button, alignment=Qt.AlignLeft)
        main_layout.addWidget(self.remove_button, alignment=Qt.AlignLeft)
        main_layout.addWidget(self.add_button, alignment=Qt.AlignLeft)

        self.main_frame.setLayout(main_layout)
        self.setCentralWidget(self.main_frame)

    #   Message handlers.
    #   These get called when the widget emits either a notification, or a spectrum.
    #   This allows you to do additional processing or enhancing the UI based on the information coming in.
    #   These are not required to be connected.

    def on_vanta_messages(self, data):

        if data['id'] == 206:  # We got a result message

            all_done = True  # start out assuming that all the units are done.

            for v in self.vantas:   # Loop over all the units.  If any are not finished set all_done to False
                if not v.vanta.final_result:
                    all_done = False
                    break

            if all_done:
                self.all_units_done()   # If we are all done get the timing data.

    def on_vanta_spectrum(self, data):
        pass


def main():
    app = QApplication(sys.argv)
    form = AppForm()
    form.show()
    app.exec_()


if __name__ == "__main__":

    # The following block of code fixing a scaling issue in PyQtGraph when used with monitors of varying DPI.
    if int(platform.release()) >= 8:
        ctypes.windll.shcore.SetProcessDpiAwareness(True)
    # End DPI fix

    main()
    print("The end")
